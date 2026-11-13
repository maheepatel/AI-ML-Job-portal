import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type JobsPage, type Stats } from "../api";
import { timeAgo } from "../format";
import { JobCard, ScoreRing, Skeletons, TrustBadge } from "../components/ui";

const QUICK = [
  ["Bengaluru", "region=bengaluru"],
  ["India", "region=india"],
  ["Remote", "region=remote"],
  ["Freshers", "exp=fresher"],
  ["LLM / GenAI", "family=AI+Engineer+%2F+LLM"],
  ["Data Scientist", "family=Data+Scientist"],
  ["Posted today", "posted_within=24"],
];

const FAQ = [
  ["Where do the jobs come from?", "Straight from employer career systems (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Recruitee), big-tech career APIs (Amazon, Microsoft), LinkedIn's public listings, SimplifyJobs' new-grad and internship lists, Hacker News 'Who is hiring' and remote job boards. Every apply link we see teaches us a new company board, so coverage grows every run."],
  ["How fresh is it?", "A full sweep runs every 4 hours. Each job shows when the employer published it and when we first saw it, so 'live for 3h' means exactly that."],
  ["How do you know a job is closed?", "Employer ATS feeds list every open role, so a job that disappears from two consecutive sweeps — or whose page returns 404 or 'no longer accepting applications' — moves to Closed with the evidence attached."],
  ["How do you spot scams?", "Every job gets an explainable trust score: posted on the employer's own system, apply link on the company domain, and cross-listings raise it; fees, WhatsApp/Telegram contact, free-mail recruiters, guaranteed income and copy-paste text across companies lower it. Likely scams are hidden by default."],
  ["Who is this for?", "Anyone from fresher to about 4 years of experience looking for ML, data science, AI/LLM, computer vision, NLP, MLOps, research or data roles. Senior, staff, lead and 5+ year roles are filtered out."],
];

export default function Home() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [fresh, setFresh] = useState<JobsPage | null>(null);
  const [q, setQ] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    const loadStats = (attempt = 0) =>
      api.stats().then(setStats).catch(() => attempt < 4 && setTimeout(() => loadStats(attempt + 1), 1500 * (attempt + 1)));
    loadStats();
    const core = new URLSearchParams({ trust: "genuine", page_size: "8", exp: "no-intern" });
    ["ML Engineer", "Data Scientist", "AI Engineer / LLM", "Computer Vision", "NLP & Speech", "MLOps & ML Platform"].forEach((f) => core.append("family", f));
    api.jobs(core).then(setFresh).catch(() => {});
  }, []);

  const search = (e: FormEvent) => {
    e.preventDefault();
    nav(`/jobs${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
  };

  const ticker = stats?.ticker ?? [];

  return (
    <>
      <section className="hero">
        <div className="container">
          <div className="eyebrow" style={{ marginBottom: 14 }}>
            {stats?.last_run ? `Updated ${timeAgo(stats.last_run.finished_at)} · next sweep in ${nextIn(stats.next_run_at)}` : "AI/ML jobs · 0–4 years"}
          </div>
          <h1>
            Every <span className="hl">AI/ML opening</span> on the internet. Built for 0–4 years.
          </h1>
          <p className="lead">
            Pulled from company career portals, LinkedIn and job boards every 4 hours — de-duplicated, scam-checked,
            and dropped the moment a role closes.
          </p>
          <form className="search-pill" onSubmit={search} role="search">
            <span aria-hidden>🔎</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Try “LLM engineer”, “computer vision”, “Razorpay”…" aria-label="Search jobs" />
            <button className="btn btn-ink btn-sm" type="submit">Search</button>
          </form>
          <div className="chips">
            {QUICK.map(([label, qs]) => <Link key={label} className="chip" to={`/jobs?${qs}`}>{label}</Link>)}
          </div>

          <div className="stats">
            <Stat value={stats?.open} label="open AI/ML roles" />
            <Stat value={stats?.companies} label="hiring companies" />
            <Stat value={stats?.new_24h} label="posted in the last 24h" />
            <Stat value={stats?.closed_7d} label="closed roles caught this week" />
          </div>
        </div>
      </section>

      {ticker.length > 0 && (
        <div className="ticker" aria-label="Latest openings">
          <div className="ticker-track">
            {[...ticker, ...ticker].map((t, i) => (
              <Link key={i} to={`/jobs/${t.id}`} className="ticker-item">
                <span className="ticker-dot" />
                <b>{t.title}</b>
                <span style={{ opacity: 0.7 }}>{t.company}{t.city ? ` · ${t.city}` : t.work_mode === "remote" ? " · Remote" : ""}</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      <section className="band">
        <div className="container">
          <div className="section-head">
            <div>
              <div className="eyebrow">Fresh off the wire</div>
              <h2>Just posted, already verified</h2>
            </div>
            <Link to="/jobs" className="btn btn-ink">Browse all {stats?.open ? stats.open.toLocaleString() : ""} jobs</Link>
          </div>
          <div className="grid-cards">
            {fresh ? fresh.items.map((j) => <JobCard key={j.id} job={j} />) : <Skeletons n={8} />}
            {fresh && fresh.items.length === 0 && (
              <div className="empty" style={{ gridColumn: "1 / -1" }}>
                {stats?.running
                  ? "The first sweep is running — new roles appear here as each source finishes."
                  : "No roles yet. The next sweep fills this in; sweeps run every 4 hours."}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="band band-mint">
        <div className="container">
          <div className="feature">
            <div>
              <div className="eyebrow">For me</div>
              <h2>Roles ranked against your résumé</h2>
              <p>
                Upload a résumé and every open role gets a match score you can actually read: skills you have, skills
                they want, whether the experience bar fits, and where it is.
              </p>
              <Link to="/for-me" className="btn btn-ink">See my matches</Link>
            </div>
            <div className="mock">
              {[
                [92, "Applied Scientist I", "Bengaluru · 1+ yrs"],
                [87, "ML Engineer — Computer Vision", "Remote · India"],
                [81, "Data Scientist II", "Hyderabad · 2+ yrs"],
              ].map(([v, t, m]) => (
                <div className="mock-row" key={t as string}>
                  <ScoreRing value={v as number} small />
                  <div>
                    <b>{t}</b>
                    <div className="caption">{m}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="feature">
            <div className="mock">
              <div className="mock-row"><TrustBadge label="verified" /> <span>Posted on the employer's own Greenhouse</span></div>
              <div className="mock-row"><TrustBadge label="likely_genuine" /> <span>LinkedIn, also found on company ATS</span></div>
              <div className="mock-row"><TrustBadge label="caution" /> <span>Short description, recruiter uses gmail</span></div>
              <div className="mock-row"><TrustBadge label="likely_scam" /> <span>“Pay ₹999 registration fee, contact on WhatsApp”</span></div>
            </div>
            <div>
              <div className="eyebrow">Trust score</div>
              <h2>Scams don't make it to your feed</h2>
              <p>
                {stats?.open ? `${(stats.verified ?? 0).toLocaleString()} roles verified on employer systems; ${stats.flagged_scams ?? 0} flagged as likely scams and hidden. ` : ""}
                Every score shows its reasons, point by point.
              </p>
              <Link to="/status" className="btn btn-ink">How we score</Link>
            </div>
          </div>
        </div>
      </section>

      <section className="band band-ink">
        <div className="container">
          <div className="feature">
            <div>
              <div className="eyebrow" style={{ color: "#9aa3ad" }}>Lifecycle tracking</div>
              <h2>Closed means closed</h2>
              <p style={{ color: "#d0d5da" }}>
                No more applying to ghost listings. When an employer takes a role down or the link dies, it moves to
                Closed with the evidence — and how long it stayed open.
              </p>
              <Link to="/closed" className="btn btn-mint">See recently closed</Link>
            </div>
            <div className="stats" style={{ marginTop: 0 }}>
              <Stat value={stats?.boards} label="company boards tracked" dark />
              <Stat value={stats?.india} label="roles in India" dark />
              <Stat value={stats?.remote} label="remote roles" dark />
              <Stat value={stats?.new_4h} label="new since last sweep" dark />
            </div>
          </div>
        </div>
      </section>

      <section className="band band-mint">
        <div className="container" style={{ maxWidth: 860 }}>
          <h2 style={{ fontSize: "clamp(32px,4.5vw,48px)", marginBottom: 12 }}>Questions</h2>
          <div className="faq">
            {FAQ.map(([qq, a]) => (
              <details key={qq}>
                <summary>{qq}</summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}

function Stat({ value, label, dark }: { value?: number; label: string; dark?: boolean }) {
  return (
    <div className="stat">
      <b>{value == null ? "—" : value.toLocaleString()}</b>
      <span style={dark ? { color: "#c3c9cf" } : undefined}>{label}</span>
    </div>
  );
}

function nextIn(iso: string | null): string {
  if (!iso) return "—";
  const mins = Math.max(0, (new Date(iso).getTime() - Date.now()) / 60000);
  return mins < 60 ? `${Math.round(mins)}m` : `${Math.floor(mins / 60)}h ${Math.round(mins % 60)}m`;
}
