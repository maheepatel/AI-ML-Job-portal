import { useEffect, useState } from "react";
import { api, type RunsResponse, type Stats } from "../api";
import { CLOSE_TEXT, SOURCE_TEXT, timeAgo } from "../format";
import { TrustBadge } from "../components/ui";

export default function Status() {
  const [runs, setRuns] = useState<RunsResponse | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    api.runs().then(setRuns).catch(() => {});
    api.stats().then(setStats).catch(() => {});
  }, []);

  const last = runs?.runs.find((r) => r.finished_at);
  const boardsTotal = runs ? Object.values(runs.boards).reduce((a, b) => a + b, 0) : 0;

  return (
    <>
      <section className="page-head">
        <div className="container">
          <h1>How Gradient works</h1>
          <p className="muted" style={{ margin: "6px 0 0" }}>Live pipeline status, sources, and the rules behind closed roles and trust scores.</p>
        </div>
      </section>

      <div className="container" style={{ padding: "32px 16px 96px", display: "flex", flexDirection: "column", gap: 32 }}>
        <div className="cards-3">
          <div className="panel">
            <div className="eyebrow">Last sweep</div>
            <h3>{last ? timeAgo(last.finished_at) : "—"}</h3>
            <div className="caption">
              {last ? `${last.stats.sources ?? 0} sources · ${(last.stats.requests ?? 0).toLocaleString()} requests · ${last.stats.duration_s ?? 0}s` : ""}
            </div>
            {stats?.running && <div className="badge likely_genuine" style={{ marginTop: 8 }}>Sweep running now</div>}
          </div>
          <div className="panel">
            <div className="eyebrow">Schedule</div>
            <h3>Every {stats?.interval_hours ?? 4} hours</h3>
            <div className="caption">00:00 · 04:00 · 08:00 · 12:00 · 16:00 · 20:00 IST. Next {stats?.next_run_at ? new Date(stats.next_run_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}.</div>
          </div>
          <div className="panel">
            <div className="eyebrow">Coverage</div>
            <h3>{boardsTotal.toLocaleString()} company boards</h3>
            <div className="caption">
              {runs && Object.entries(runs.boards).map(([k, v]) => `${v} ${k === "auto" ? "auto-discovered" : k}`).join(" · ")}
            </div>
          </div>
        </div>

        <div>
          <h2 style={{ fontSize: 32, marginBottom: 12 }}>Sources in the last sweep</h2>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Source</th><th>Boards / feeds</th><th>Healthy</th><th>Listed</th><th>AI/ML kept</th><th>New</th><th>Closed</th></tr></thead>
              <tbody>
                {runs?.sources.map((s) => (
                  <tr key={s.source}>
                    <td><b>{SOURCE_TEXT[s.source] ?? s.source}</b></td>
                    <td>{s.sources}</td>
                    <td>{s.failed ? <span style={{ color: "var(--warn)" }}>{s.ok}/{s.sources}</span> : `${s.ok}/${s.sources}`}</td>
                    <td>{s.fetched.toLocaleString()}</td>
                    <td>{s.kept.toLocaleString()}</td>
                    <td>{s.new.toLocaleString()}</td>
                    <td>{s.closed.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="cards-3">
          <div className="panel">
            <h3>Where jobs come from</h3>
            <p className="caption" style={{ fontSize: 14 }}>
              Employer ATS APIs (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Recruitee), Amazon & Microsoft
              careers, LinkedIn public listings, SimplifyJobs new-grad & intern lists, HN “Who is hiring”, Remotive,
              RemoteOK, Himalayas, Jobicy, The Muse, Arbeitnow. Any ATS link seen anywhere registers that company's whole board.
            </p>
          </div>
          <div className="panel">
            <h3>When a role is closed</h3>
            <ul className="caption" style={{ fontSize: 14, paddingLeft: 18 }}>
              <li>Missing from the employer's own listing for 2 sweeps in a row</li>
              <li>Job page returns 404/410, redirects away, or says “no longer accepting applications”</li>
              <li>Application deadline passed</li>
              <li>Not re-confirmed anywhere for 30 days</li>
            </ul>
            {runs && Object.keys(runs.closures).length > 0 && (
              <div className="caption">So far: {Object.entries(runs.closures).map(([k, v]) => `${v} ${CLOSE_TEXT[k] ?? k}`).join(" · ")}</div>
            )}
          </div>
          <div className="panel">
            <h3>Trust score</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 14 }}>
              <span><TrustBadge label="verified" /> 80+ · employer's own system</span>
              <span><TrustBadge label="likely_genuine" /> 60–79</span>
              <span><TrustBadge label="caution" /> 35–59 · check before applying</span>
              <span><TrustBadge label="likely_scam" /> &lt;35 · hidden by default</span>
            </div>
            <p className="caption" style={{ fontSize: 14 }}>
              Red flags: fees or deposits, WhatsApp/Telegram contact, free-mail recruiters, link shorteners, guaranteed income,
              requests for bank/ID details, identical text across companies, unrealistic pay.
            </p>
          </div>
        </div>

        <div>
          <h2 style={{ fontSize: 32, marginBottom: 12 }}>Recent sweeps</h2>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>#</th><th>Started</th><th>Status</th><th>Kept</th><th>New</th><th>Closed</th><th>Boards found</th><th>Duration</th></tr></thead>
              <tbody>
                {runs?.runs.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td>{timeAgo(r.started_at)}</td>
                    <td>{r.status}</td>
                    <td>{(r.stats.kept ?? 0).toLocaleString()}</td>
                    <td>{(r.stats.new ?? 0).toLocaleString()}</td>
                    <td>{((r.stats.closed ?? 0) + (r.stats.liveness_closed ?? 0) + (r.stats.expired ?? 0)).toLocaleString()}</td>
                    <td>{(r.stats.boards_discovered ?? 0).toLocaleString()}</td>
                    <td>{r.stats.duration_s ? `${Math.round(r.stats.duration_s)}s` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
