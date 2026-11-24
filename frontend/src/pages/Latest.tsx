import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type JobsPage } from "../api";
import { JobCard, Skeletons } from "../components/ui";

const SPANS: [number, string][] = [[1, "Last hour"], [3, "3 hours"], [6, "6 hours"], [12, "12 hours"], [24, "24 hours"], [72, "3 days"], [168, "7 days"]];
const REGIONS: [string, string][] = [["", "Anywhere"], ["india", "India"], ["bengaluru", "Bengaluru"], ["remote", "Remote"]];
const CORE = ["ML Engineer", "Data Scientist", "AI Engineer / LLM", "Computer Vision", "NLP & Speech", "MLOps & ML Platform", "Research", "AI Product Engineering"];

export default function Latest() {
  const [params, setParams] = useSearchParams();
  const hours = Number(params.get("h") || 24);
  const region = params.get("region") || "";
  const core = params.get("core") !== "0";
  const [data, setData] = useState<JobsPage | null>(null);
  const [page, setPage] = useState(1);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { document.title = "Latest AI/ML jobs · Gradient"; }, []);
  useEffect(() => setPage(1), [hours, region, core]);

  useEffect(() => {
    setErr(null);
    if (page === 1) setData(null);
    const q = new URLSearchParams({ posted_within: String(hours), sort: "newest", page: String(page), page_size: "48", exp: "no-intern" });
    if (region) q.append("region", region);
    if (core) CORE.forEach((f) => q.append("family", f));
    api.jobs(q).then((d) => setData((prev) => (page > 1 && prev ? { ...d, items: [...prev.items, ...d.items] } : d))).catch((e) => setErr(e.message));
  }, [hours, region, core, page]);

  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params);
    if (v == null || v === "") next.delete(k); else next.set(k, v);
    setParams(next, { replace: true });
  };

  return (
    <div className="container page-pad">
      <div className="eyebrow">Latest</div>
      <h1 className="page-h1">Just posted</h1>
      <p className="muted" style={{ maxWidth: 680 }}>
        Roles by the time the employer posted them. Applying in the first day puts you near the top of the pile, before hundreds of others do.
        Only roles whose source gives a real posted date are shown here.
      </p>

      <div className="chips" role="group" aria-label="Posted within">
        {SPANS.map(([h, label]) => (
          <button key={h} type="button" className={`chip${hours === h ? " on" : ""}`} onClick={() => set("h", h === 24 ? null : String(h))}>{label}</button>
        ))}
      </div>
      <div className="chips" role="group" aria-label="Region" style={{ marginTop: 8 }}>
        {REGIONS.map(([v, label]) => (
          <button key={label} type="button" className={`chip${region === v ? " on" : ""}`} onClick={() => set("region", v || null)}>{label}</button>
        ))}
        <button type="button" className={`chip${core ? " on" : ""}`} onClick={() => set("core", core ? "0" : null)}
          title="Hide data-analyst and BI roles">{core ? "Core AI/ML only" : "Including analytics"}</button>
      </div>

      <p className="caption" style={{ margin: "18px 0 12px" }} aria-live="polite">
        {data ? `${data.total.toLocaleString()} roles posted in the last ${SPANS.find(([h]) => h === hours)?.[1].toLowerCase() ?? `${hours}h`}` : " "}
      </p>
      {err && <p className="owner-err" role="alert">{err}</p>}
      <div className="grid-cards">
        {data ? data.items.map((j) => <JobCard key={j.id} job={j} />) : <Skeletons n={9} />}
        {data && data.items.length === 0 && (
          <div className="empty" style={{ gridColumn: "1 / -1" }}>Nothing dated in this window yet. Try a wider span.</div>
        )}
      </div>
      {data && data.items.length < data.total && (
        <div style={{ textAlign: "center", marginTop: 24 }}>
          <button type="button" className="btn btn-ink btn-sm" onClick={() => setPage((p) => p + 1)}>Show more</button>
        </div>
      )}
    </div>
  );
}
