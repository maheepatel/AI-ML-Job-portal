"""Fixture-based tests for the YC, extra-ATS, Oracle and regional sources (no network)."""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from gradient.db import init_db, session_scope
from gradient.domain.classify import classify
from gradient.domain.normalize import html_to_text
from gradient.ingest.base import SourceError
from gradient.ingest.discovery import board_from_url
from gradient.ingest.registry import _seed_file, board_source
from gradient.ingest.sources.ats_extra import BambooHR, Breezy, JazzHR, Personio, Rippling, Teamtailor
from gradient.ingest.sources.oracle import OracleHCM
from gradient.ingest.sources.regional import GetOnBoard, HabrCareer, MyCareersFuture, WorkingNomads
from gradient.ingest.sources.yc import ROLE_PAGES, YCJobBoard, ai_hiring, ats_links, crawl_yc_websites
from gradient.models import Board

FIX = Path(__file__).parent / "fixtures"


def fx(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class FakeHttp:
    """Answers by URL substring; the first matching route wins. Unrouted URLs raise like a 404."""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[str] = []

    def _body(self, url: str) -> str:
        self.calls.append(url)
        for needle, name in self.routes.items():
            if needle in url:
                return fx(name)
        raise SourceError(f"HTTP 404 for {url}")

    async def get_text(self, url, **kw):
        return self._body(url)

    async def get_json(self, url, **kw):
        return json.loads(self._body(url))


def run(src, routes):
    http = FakeHttp(routes)
    return asyncio.run(src.fetch(http)), http


def in_scope(job) -> bool:
    return classify(job.title, html_to_text(job.description)).in_scope


# ---------------------------------------------------------------- YC


def test_yc_job_board_reads_role_pages_and_company_slice():
    companies = [{"slug": "acme", "name": "Acme"}, {"slug": "circuithub", "name": "CircuitHub"}]
    src = YCJobBoard(companies, run_id=0)
    src.PAUSE_S = 0
    assert src.pages()[len(ROLE_PAGES):] == ["/companies/acme/jobs", "/companies/circuithub/jobs"]
    res, http = run(src, {"/companies/circuithub/jobs": "yc_company.html", "/jobs/role/": "yc_role.html"})
    assert len(http.calls) == len(ROLE_PAGES) + 1  # the unrouted acme page fails like a 429: the source stops there
    ids = {j.source_job_id for j in res.jobs}
    assert "53662" in ids and "93234" not in ids  # SWE titles are listed but not AI/ML candidates
    ml = next(j for j in res.jobs if j.source_job_id == "53662")
    assert ml.title == "Machine Learning Engineer (New Grad)" and ml.url.startswith("https://www.ycombinator.com/companies/")
    assert "Experience: Any (new grads ok)" in ml.description and "PyTorch" in ml.description
    assert ml.posted_at is not None and in_scope(ml)


def test_yc_job_board_company_page_and_rotation():
    companies = [{"slug": f"c{i:02d}"} for i in range(40)]
    a, b = YCJobBoard(companies, run_id=0).pages(), YCJobBoard(companies, run_id=1).pages()
    assert len(a) == YCJobBoard.BUDGET and not set(a[len(ROLE_PAGES):]) & set(b[len(ROLE_PAGES):])
    src = YCJobBoard([{"slug": "circuithub"}])
    src.PAUSE_S = 0
    res, _ = run(src, {"/companies/circuithub/jobs": "yc_company.html", "/jobs/role/": "yc_role.html"})
    cv = next(j for j in res.jobs if j.title == "Computer Vision Engineer")
    assert cv.company == "CircuitHub" and cv.salary_text.startswith("£80K") and cv.company_domain == "circuithub.com"


def test_yc_job_board_raises_when_rate_limited_from_the_start():
    src = YCJobBoard()
    src.PAUSE_S = 0
    with pytest.raises(SourceError):
        run(src, {})


def test_ai_hiring_filters_by_tags_and_one_liner():
    hiring = [{"slug": "b", "tags": ["Fintech"], "one_liner": "Payments"}, {"slug": "a", "tags": ["Generative AI"]},
              {"slug": "c", "tags": [], "one_liner": "ML for radiology"}]
    assert [c["slug"] for c in ai_hiring(hiring)] == ["a", "c"]


def test_ats_links_finds_boards_and_same_site_careers_page():
    page = ('<a href="https://jobs.ashbyhq.com/acme">Jobs</a> <a href="/careers">Careers</a> '
            '<a href="https://twitter.com/careers">x</a> <iframe src="https://boards.greenhouse.io/embed/job_board?for=acme"></iframe>')
    boards, careers = ats_links(page, "https://www.acme.ai/")
    assert ("ashby", "acme") in boards
    assert careers == "https://www.acme.ai/careers"


def test_yc_website_crawl_rotates_and_follows_careers_page():
    companies = [{"slug": f"c{i}", "name": f"C{i}", "website": f"https://c{i}.com"} for i in range(4)]
    pages = {"https://c1.com": '<a href="/jobs">Jobs</a>', "https://c1.com/jobs": '<a href="https://jobs.lever.co/cone/1">x</a>',
             "https://c2.com": '<a href="https://jobs.ashbyhq.com/ctwo">x</a>'}

    class Http:
        async def get_text(self, url, **kw):
            if url not in pages:
                raise SourceError("HTTP 404")
            return pages[url]

    first = asyncio.run(crawl_yc_websites(Http(), companies, run_id=0, per_run=2))  # c0, c1
    second = asyncio.run(crawl_yc_websites(Http(), companies, run_id=1, per_run=2))  # c2, c3
    assert first == {("lever", "cone"): "C1"}
    assert second == {("ashby", "ctwo"): "C2"}


@pytest.fixture
def clean_boards():
    init_db()
    with session_scope() as s:
        s.execute(delete(Board))
    yield
    with session_scope() as s:
        s.execute(delete(Board))


def test_seed_file_supports_new_board_types_and_origin(clean_boards, tmp_path):
    f = tmp_path / "boards.yaml"
    f.write_text("ashby:\n- slug: acme\n  company: Acme\npersonio:\n- acme-gmbh\noracle:\n"
                 "- {host: jpmc.fa.oraclecloud.com, site: CX_1001, company: JPMorgan Chase}\nunknown:\n- x\n", encoding="utf-8")
    with session_scope() as s:
        assert _seed_file(s, f, "yc", set()) == 3
    with session_scope() as s:
        boards = {b.ats: b for b in s.scalars(select(Board))}
        assert set(boards) == {"ashby", "personio", "oracle"}
        assert boards["ashby"].origin == "yc"
        src = board_source(boards["oracle"])
        assert isinstance(src, OracleHCM) and src.key == "oracle:jpmc-CX_1001"


# ---------------------------------------------------------------- discovery


@pytest.mark.parametrize("url,board", [
    ("https://acme.jobs.personio.de/job/123?language=en", ("personio", "acme")),
    ("https://acme.jobs.personio.com/job/123", ("personio", "acme")),
    ("https://polestar.teamtailor.com/jobs/8710722-ml-engineer", ("teamtailor", "polestar")),
    ("https://asuresoftware.bamboohr.com/careers/1058", ("bamboohr", "asuresoftware")),
    ("https://acme.breezy.hr/p/98323abf2296-ml-engineer", ("breezy", "acme")),
    ("https://imanagecom.applytojob.com/apply/2sEdqwy08T/Applied-AI-Engineer", ("jazzhr", "imanagecom")),
    ("https://ats.rippling.com/zededa/jobs/3e34a738-5eb1-405d-b46b-e9737226f5be", ("rippling", "zededa")),
    ("https://ats.rippling.com/en-GB/acme/jobs/x", ("rippling", "acme")),
    ("https://www.ycombinator.com/companies/circuithub/jobs/js2U2cL-computer-vision-engineer", None),
    ("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210723353",
     ("oracle", "jpmc.fa.oraclecloud.com|CX_1001")),
    ("https://fa-etbx-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/nfcu/job/1",
     ("oracle", "fa-etbx-saasfaprod1.fa.ocs.oraclecloud.com|nfcu")),
    ("https://www.ycombinator.com/companies/circuithub", None),
    ("https://app.breezy.hr/signin", None),
    ("https://www.bamboohr.com/careers", None),
])
def test_board_from_url_new_ats_patterns(url, board):
    assert board_from_url(url) == board


# ---------------------------------------------------------------- extra ATSes


def test_personio_parses_descriptions_offices_and_years():
    res, _ = run(Personio("acme"), {"acme.jobs.personio.de/xml": "personio.xml"})
    assert res.seen_ids == {"2885200", "2885178"}
    job = next(j for j in res.jobs if j.source_job_id == "2885200")
    assert job.company == "Acme Robotics GmbH"
    assert job.location == "Berlin / Munich"
    assert job.url == "https://acme.jobs.personio.de/job/2885200"
    assert "PyTorch" in job.description and "1 to 2 years" in job.description
    assert in_scope(job)


def test_personio_falls_back_to_the_com_domain():
    res, http = run(Personio("acme"), {"acme.jobs.personio.com/xml": "personio.xml"})
    assert len(res.jobs) == 2 and res.jobs[0].url.startswith("https://acme.jobs.personio.com/")
    assert any(".personio.de" in c for c in http.calls)


def test_teamtailor_rss():
    res, _ = run(Teamtailor("polestar"), {"polestar.teamtailor.com/jobs.rss": "teamtailor.rss"})
    assert len(res.seen_ids) == 2
    job = res.jobs[0]
    assert job.source_job_id == "8710722" and job.title == "Machine Learning Engineer, Autonomy"
    assert job.company == "Polestar" and "Brussels, Belgium" in job.location
    assert job.posted_at is not None and job.description


def test_bamboohr_details_only_ai_titles():
    res, http = run(BambooHR("asuresoftware"), {"/careers/1058/detail": "bamboo_detail.json", "/careers/list": "bamboo_list.json"})
    assert res.seen_ids == {"774", "1058"}
    assert [j.title for j in res.jobs] == ["Associate AI Software Engineer"]
    job = res.jobs[0]
    assert job.url == "https://asuresoftware.bamboohr.com/careers/1058"
    assert "Addison" in job.location and job.posted_at.year == 2026 and job.salary_text == "$80,000"
    assert sum("detail" in c for c in http.calls) == 1


def test_breezy_listing_plus_jsonld_detail():
    res, _ = run(Breezy("breezy"), {"breezy.hr/json": "breezy.json", "/p/": "breezy_detail.html"})
    assert len(res.seen_ids) == 2
    job = res.jobs[0]
    assert job.title == "Junior Data Scientist" and job.location == "Chaos, FL"
    assert job.salary_text.startswith("$90,000") and "PyTorch" in job.description  # from the page's JSON-LD
    assert in_scope(job)


def test_jazzhr_list_and_description():
    res, _ = run(JazzHR("imanagecom"), {"/apply/": "jazz_detail.html", "applytojob.com/apply": "jazz_list.html"})
    assert len(res.seen_ids) == 2
    assert len(res.jobs) == 1
    job = res.jobs[0]
    assert "AI" in job.title and job.url.startswith("https://imanagecom.applytojob.com/apply/")
    assert "Applied AI Engineer" in job.description


def test_rippling_list_and_detail():
    res, _ = run(Rippling("rippling"), {"/jobs/": "rippling_detail.json", "/board/rippling/jobs": "rippling_list.json"})
    assert len(res.seen_ids) == 2
    job = res.jobs[0]
    assert "Data Science Intern" in job.title and job.company == "Rippling"
    assert job.location == "San Francisco, CA" and "PyTorch" in job.description
    assert in_scope(job)


# ---------------------------------------------------------------- Oracle


def test_oracle_search_and_detail():
    src = OracleHCM("jpmc.fa.oraclecloud.com", "CX_1001", "JPMorgan Chase", terms=["machine learning"])
    res, http = run(src, {"recruitingCEJobRequisitionDetails": "oracle_detail.json", "recruitingCEJobRequisitions": "oracle_list.json"})
    assert len(res.seen_ids) == 2
    assert all(c.count("siteNumber=CX_1001") == 1 for c in http.calls)
    job = next(j for j in res.jobs if j.source_job_id == "210781971")
    assert job.title == "AI Automation Engineer Associate"
    assert job.url == "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210781971"
    assert job.location.startswith("Bengaluru") and job.posted_at.year == 2026 and job.deadline_at is not None
    assert len(job.description) > 200


# ---------------------------------------------------------------- regional


def test_mycareersfuture():
    res, _ = run(MyCareersFuture(), {"mycareersfuture": "mcf.json"})
    assert len(res.seen_ids) == 2  # every search page returns the same two jobs: deduped
    job = res.jobs[0]
    assert job.location == "Singapore" and job.salary_currency == "SGD" and job.salary_period == "month"
    assert "Minimum 4 years of experience" in job.description
    assert job.url.startswith("https://www.mycareersfuture.gov.sg/job/") and job.deadline_at is not None
    assert job.company == "Talentsis Pte. Ltd."


def test_getonboard():
    res, _ = run(GetOnBoard(), {"getonbrd.com/api": "getonbrd.json"})
    assert len(res.seen_ids) == 2
    job = res.jobs[0]
    assert job.company == "Duoc UC" and job.location == "Chile"
    assert job.url.startswith("https://www.getonbrd.com/jobs/") and job.posted_at is not None
    assert "Seniority: Senior" in job.description


def test_habr_skips_senior_cards_and_reads_jsonld():
    res, http = run(HabrCareer(), {"/vacancies/1000169302": "habr_detail.html", "api/frontend/vacancies": "habr_list.json"})
    assert len(res.seen_ids) == 3
    assert [j.source_job_id for j in res.jobs] == ["1000169302"]  # Senior/Lead cards and non-English titles skipped
    job = res.jobs[0]
    assert job.url == "https://career.habr.com/vacancies/1000169302" and job.remote
    assert "PyTorch" in job.description and job.posted_at is not None


def test_working_nomads():
    res, _ = run(WorkingNomads(), {"workingnomads.com/api": "workingnomads.json"})
    assert len(res.jobs) == 2 and all(j.remote for j in res.jobs)
    assert res.jobs[0].url.startswith("https://www.workingnomads.com/job/")
