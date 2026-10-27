import type { JobDetail } from "../api";
import { CLOSE_TEXT, duration, experience, place, salary, SOURCE_TEXT, timeAgo } from "../format";
import { LiveTag, TrustBadge } from "./ui";

export function JobDetailView({ job }: { job: JobDetail }) {
  const pay = salary(job);
  const others = job.listings.filter((l) => l.url !== job.url);
  return (
    <article>
      <div className="card-top">
        <LiveTag job={job} />
        <TrustBadge label={job.trust_label} score={job.trust_score} />
      </div>
      <h2>{job.title}</h2>
      <div style={{ fontWeight: 600 }}>{job.company}</div>
      <div className="meta" style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", fontSize: 14, color: "#4b5259", marginTop: 8 }}>
        <span>📍 {place(job)}</span>
        <span>{experience(job)}</span>
        <span>{job.role_family}</span>
        {pay && <span>{pay}</span>}
        {job.employment_type && <span>{job.employment_type}</span>}
      </div>

      {job.status === "open" ? (
        <a className="btn btn-ink" href={job.url} target="_blank" rel="noopener noreferrer nofollow" style={{ marginTop: 18 }}>
          Apply on {SOURCE_TEXT[job.source] ?? "employer site"} ↗
        </a>
      ) : (
        <div className="panel" style={{ marginTop: 18, background: "var(--surface-soft)", border: 0 }}>
          <b>Closed {timeAgo(job.closed_at)}</b> — {CLOSE_TEXT[job.close_reason ?? ""] ?? job.close_reason}
          <div className="caption">{job.close_evidence} · was live for {duration(job.live_since, job.closed_at)}</div>
        </div>
      )}

      <div className="timeline">
        <div><b>{timeAgo(job.live_since)}</b><span>Posted by employer</span></div>
        <div><b>{timeAgo(job.first_seen_at)}</b><span>First seen by us</span></div>
        <div><b>{timeAgo(job.last_verified_at)}</b><span>Last verified live</span></div>
      </div>

      {job.skills.length > 0 && (
        <div className="tags" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 18 }}>
          {job.skills.map((s) => <span key={s} className="tag">{s}</span>)}
        </div>
      )}

      <section className="panel" style={{ marginBottom: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <b>Why this trust score: {job.trust_score}/100</b>
          <TrustBadge label={job.trust_label} />
        </div>
        <ul className="reasons">
          <li><span className="pts muted">50</span><span className="muted">Starting score</span></li>
          {job.trust_reasons.map((r) => (
            <li key={r.signal}>
              <span className={`pts ${r.impact >= 0 ? "pos" : "neg"}`}>{r.impact >= 0 ? `+${r.impact}` : r.impact}</span>
              <span>{r.detail}</span>
            </li>
          ))}
        </ul>
        {others.length > 0 && (
          <p className="caption" style={{ marginBottom: 0 }}>
            Also listed on:{" "}
            {others.map((l, i) => (
              <span key={l.url}>
                {i > 0 && ", "}
                <a href={l.url} target="_blank" rel="noopener noreferrer nofollow" style={{ textDecoration: "underline" }}>
                  {SOURCE_TEXT[l.source] ?? l.source}
                </a>
              </span>
            ))}
          </p>
        )}
      </section>

      {job.description ? (
        <div className="desc">{job.description}</div>
      ) : (
        <p className="muted">This source lists the role without a description. Open the posting for full details.</p>
      )}
    </article>
  );
}
