import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, type JobDetail, type JobsPage } from "../api";
import { JobDetailView } from "../components/JobDetailView";
import { JobCard, Skeletons } from "../components/ui";

const FAMILIES = ["ML Engineer", "Data Scientist", "AI Engineer / LLM", "Research", "Computer Vision", "NLP & Speech",
  "MLOps & ML Platform", "AI Product Engineering", "Data & Analytics"];
const REGIONS: [string, string][] = [["bengaluru", "Bengaluru"], ["india", "India"], ["remote", "Remote"], ["north-america", "US & Canada"], ["europe", "Europe & UK"]];
const EXP: [string, string][] = [["", "Any"], ["fresher", "Fresher / intern"], ["1-2", "1–2 yrs"], ["2-4", "2–4 yrs"], ["no-intern", "No internships"]];
const POSTED: [string, string][] = [["", "Any time"], ["12", "Last 12h"], ["24", "24h"], ["72", "3 days"], ["168", "7 days"], ["720", "30 days"]];
const TRUST: [string, string][] = [["default", "Hide scams"], ["genuine", "Genuine+"], ["verified", "Verified only"], ["all", "Show all"]];
const KINDS: [string, string][] = [["ats", "Company ATS"], ["bigtech", "Big tech"], ["linkedin", "LinkedIn"], ["board", "Job boards"], ["community", "HN"]];

export default function Jobs({ status = "open" }: { status?: "open" | "closed" }) {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<JobsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [q, setQ] = useState(params.get("q") ?? "");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const nav = useNavigate();

  const query = useMemo(() => {
    const p = new URLSearchParams(params);
    p.set("status", status);
    if (status === "closed") p.set("sort", "closed");
    if (!p.get("page_size")) p.set("page_size", "30");
    return p;
  }, [params, status]);

  useEffect(() => {
    setData(null);
    setError(null);
    api.jobs(query).then((d) => {
      setData(d);
      if (d.items.length && window.innerWidth > 1100) setSelected(d.items[0].id);
    }).catch((e) => setError(e.message));
  }, [query]);

  useEffect(() => {
    if (selected == null) return;
    setDetail(null);
    api.job(selected).then(setDetail).catch(() => {});
  }, [selected]);

  useEffect(() => {
    const t = setTimeout(() => {
      if ((params.get("q") ?? "") !== q) update("q", q || null);
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  function update(key: string, value: string | null, multi = false) {
    const p = new URLSearchParams(params);
    if (multi && value) {
      const cur = p.getAll(key);
      p.delete(key);
      (cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value]).forEach((v) => p.append(key, v));
    } else if (value) p.set(key, value);
    else p.delete(key);
    p.delete("page");
    setParams(p, { replace: true });
  }

  const select = (id: number) => (window.innerWidth > 1100 ? setSelected(id) : nav(`/jobs/${id}`));
  const page = Number(params.get("page") || 1);
  const pages = data ? Math.ceil(data.total / data.page_size) : 1;
  const active = (key: string, v: string) => (params.getAll(key).length ? params.getAll(key).includes(v) : false);
  const single = (key: string, v: string, dflt = "") => (params.get(key) ?? dflt) === v;

  return (
    <>
      <section className="page-head">
        <div className="container">
          <h1>{status === "closed" ? "Recently closed" : "AI/ML jobs"}</h1>
          <p className="muted" style={{ margin: "6px 0 0" }}>
            {status === "closed"
              ? "Roles that were filled, taken down or expired, with the evidence and how long they stayed open."
              : "Fresher to 4 years. Sorted by when the employer posted."}
          </p>
        </div>
      </section>
      <div className="container jobs-layout">
        <aside className={`filters${filtersOpen ? "" : " collapsed"}`}>
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, company, city" aria-label="Search" />
          <button type="button" className="btn btn-ghost" onClick={() => setFiltersOpen((o) => !o)} style={{ display: window.innerWidth <= 760 ? "inline-flex" : "none" }}>
            {filtersOpen ? "Hide filters" : "Show filters"}
          </button>
          <div className="filter-body" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            <Group title="Role">
              {FAMILIES.map((f) => (
                <button key={f} type="button" className={`chip${active("family", f) ? " on" : ""}`} onClick={() => update("family", f, true)}>
                  {f}{data?.family_counts[f] ? <span style={{ opacity: 0.6 }}> {data.family_counts[f]}</span> : null}
                </button>
              ))}
            </Group>
            <Group title="Experience">
              {EXP.map(([v, l]) => <button key={l} type="button" className={`chip${single("exp", v) ? " on" : ""}`} onClick={() => update("exp", v || null)}>{l}</button>)}
            </Group>
            <Group title="Location">
              {REGIONS.map(([v, l]) => <button key={v} type="button" className={`chip${active("region", v) ? " on" : ""}`} onClick={() => update("region", v, true)}>{l}</button>)}
            </Group>
            <Group title="Posted">
              {POSTED.map(([v, l]) => <button key={l} type="button" className={`chip${single("posted_within", v) ? " on" : ""}`} onClick={() => update("posted_within", v || null)}>{l}</button>)}
            </Group>
            <Group title="Trust">
              {TRUST.map(([v, l]) => <button key={v} type="button" className={`chip${single("trust", v, "default") ? " on" : ""}`} onClick={() => update("trust", v === "default" ? null : v)}>{l}</button>)}
            </Group>
            <Group title="Source">
              {KINDS.map(([v, l]) => <button key={v} type="button" className={`chip${active("kind", v) ? " on" : ""}`} onClick={() => update("kind", v, true)}>{l}</button>)}
            </Group>
            {[...params.keys()].length > 0 && (
              <button type="button" className="btn btn-ghost" onClick={() => { setQ(""); setParams({}, { replace: true }); }}>Clear all filters</button>
            )}
          </div>
        </aside>

        <section className="list" aria-live="polite">
          <div className="list-head">
            <span>{data ? <><b>{data.total.toLocaleString()}</b> {status === "closed" ? "closed roles" : "open roles"}</> : "Loading…"}</span>
          </div>
          {error && <div className="empty">Couldn't load jobs: {error}</div>}
          {!data && !error && <Skeletons n={6} />}
          {data && data.items.length === 0 && <div className="empty">No roles match these filters. Try widening location or time.</div>}
          {data?.items.map((j) => <JobCard key={j.id} job={j} selected={j.id === selected} onSelect={select} />)}
          {data && pages > 1 && (
            <div className="pager">
              <button type="button" className="btn btn-ghost" disabled={page <= 1} onClick={() => update("page", String(page - 1))}>← Prev</button>
              <span style={{ alignSelf: "center", fontSize: 14 }}>Page {page} of {pages}</span>
              <button type="button" className="btn btn-ghost" disabled={page >= pages} onClick={() => { const p = new URLSearchParams(params); p.set("page", String(page + 1)); setParams(p); window.scrollTo({ top: 0 }); }}>Next →</button>
            </div>
          )}
        </section>

        <aside className="detail">
          {detail ? <JobDetailView job={detail} /> : <Skeletons n={3} />}
        </aside>
      </div>
    </>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4>{title}</h4>
      <div className="chips">{children}</div>
    </div>
  );
}
