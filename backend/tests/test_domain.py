from datetime import datetime, timezone

from gradient.domain.classify import classify, experience_years, seniority, title_candidate
from gradient.domain.normalize import fingerprint, parse_location, parse_relative, parse_salary
from gradient.domain.trust import score_trust
from gradient.ingest.discovery import board_from_url

AI_DESC = "We train PyTorch models, build RAG pipelines with LLMs and embeddings, and deploy machine learning systems. " * 5


def test_core_ai_roles_are_in_scope():
    for title in ["Machine Learning Engineer", "Data Scientist I", "AI Engineer - LLM", "Applied Scientist Intern",
                  "Computer Vision Engineer", "MLOps Engineer", "Associate Data Scientist"]:
        c = classify(title, AI_DESC)
        assert c.in_scope, (title, c.reject_reason)


def test_senior_and_non_practitioner_roles_are_rejected():
    assert classify("Senior Machine Learning Engineer", AI_DESC).reject_reason == "senior_title"
    assert classify("Staff Data Scientist", AI_DESC).reject_reason == "senior_title"
    assert classify("ML Engineering Manager", AI_DESC).reject_reason == "senior_title"
    assert classify("AI Sales Account Executive", AI_DESC).reject_reason == "non_practitioner"
    assert classify("Office Manager", "We are a nice company").reject_reason == "not_ai_ml"


def test_experience_requirement_filters():
    assert experience_years("Requires 2-4 years of experience in ML") == (2, 4)
    assert experience_years("3+ years of professional experience") == (3, None)
    assert experience_years("We have 10 years in business") == (None, None)
    c = classify("Machine Learning Engineer", AI_DESC + " Minimum 6+ years of industry experience required.")
    assert c.reject_reason == "too_much_experience"


def test_software_engineer_with_ai_heavy_description_counts():
    c = classify("Software Engineer", AI_DESC + " fine-tuning transformers hugging face vector database agentic")
    assert c.in_scope and c.role_family == "AI Product Engineering"
    assert not classify("Software Engineer", "Build REST APIs in Java").in_scope


def test_seniority_levels():
    assert seniority("Machine Learning Intern") == "intern"
    assert seniority("Associate Product Manager, AI") == "entry"
    assert seniority("Data Scientist II") == "mid"
    assert title_candidate("Machine Learning Engineer")
    assert not title_candidate("Principal ML Engineer")


def test_location_parsing():
    loc = parse_location("Bengaluru, Karnataka, India")
    assert (loc.city, loc.country, loc.work_mode) == ("Bengaluru", "India", "onsite")
    assert parse_location("Remote - US").work_mode == "remote"
    assert parse_location("San Francisco, CA").country == "United States"


def test_salary_parsing():
    assert parse_salary("$120k - $150k per year")[:3] == (120000, 150000, "USD")
    lo, hi, cur, _ = parse_salary("CTC ₹12 LPA - ₹18 LPA")
    assert (lo, hi, cur) == (1_200_000, 1_800_000, "INR")


def test_relative_dates():
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    assert parse_relative("Posted 3 Days Ago", now).day == 19
    assert parse_relative("2 hours ago", now).hour == 22 or parse_relative("2 hours ago", now).day == 21


def test_fingerprint_ignores_noise():
    assert fingerprint("OpenAI, Inc.", "ML Engineer (Remote)", "Bengaluru") == fingerprint("openai", "ML Engineer", "Bengaluru")


def test_trust_ats_is_verified_and_fee_scam_is_flagged():
    good = score_trust(title="ML Engineer", company="Acme", description=AI_DESC * 3,
                       url="https://boards.greenhouse.io/acme/jobs/1", source_kind="ats")
    assert good.label == "verified"
    scam = score_trust(title="AI Data Entry Work From Home", company="Hiring",
                       description="Earn $500 per day! Pay a registration fee of Rs 999. Contact on WhatsApp +91...",
                       url="https://bit.ly/x", source_kind="board")
    assert scam.label == "likely_scam"
    assert {r["signal"] for r in scam.reasons} >= {"asks_for_fee", "off_platform_contact", "too_good_to_be_true"}


def test_board_discovery_from_urls():
    assert board_from_url("https://job-boards.greenhouse.io/celonis/jobs/7784391003") == ("greenhouse", "celonis")
    assert board_from_url("https://boards.greenhouse.io/embed/job_app?for=stripe&token=1") == ("greenhouse", "stripe")
    assert board_from_url("https://jobs.lever.co/zoox/abc") == ("lever", "zoox")
    assert board_from_url("https://jobs.ashbyhq.com/openai/123") == ("ashby", "openai")
    assert board_from_url("https://draper.wd5.myworkdayjobs.com/Draper_Careers/job/x") == ("workday", "draper|wd5|Draper_Careers")
    assert board_from_url("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/y") == ("workday", "nvidia|wd5|NVIDIAExternalCareerSite")
    assert board_from_url("https://www.linkedin.com/jobs/view/123") is None


def test_fee_disclaimers_are_not_scams():
    desc = AI_DESC * 2
    for disclaimer in [
        "Authorized recruitment agencies will never charge a candidate a registration fee, hiring fee, or any other fee.",
        "Kitware will not pay a fee for any placement resulting from the receipt of an unsolicited resume.",
        "We'll never ask you to pay a fee, send money, deposit or cash a check.",
        "We are not responsible for any fees related to unsolicited resumes and will not pay fees to any third-party agency.",
    ]:
        r = score_trust(title="ML Engineer", company="Airbnb", description=desc + disclaimer,
                        url="https://boards.greenhouse.io/airbnb/jobs/1", source_kind="ats")
        assert r.label == "verified", disclaimer
    scam = score_trust(title="AI Intern", company="X", description=desc + " Candidates must pay a registration fee of Rs 2000 before joining.",
                       url="https://example.com", source_kind="board")
    assert any(x["signal"] == "asks_for_fee" for x in scam.reasons)


def test_fee_regex_needs_whole_words():
    r = score_trust(title="AI Engineer", company="OpenAI", description=AI_DESC * 2 + " Experience with post-training feedback loops.",
                    url="https://jobs.ashbyhq.com/openai/1", source_kind="ats")
    assert not any(x["signal"] in ("asks_for_fee", "mentions_fee") for x in r.reasons)
