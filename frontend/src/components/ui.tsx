import { Link, NavLink } from "react-router-dom";
import type { JobSummary, TrustLabel } from "../api";
import { experience, isFresh, place, postedLabel, salary, SOURCE_TEXT, TRUST_TEXT } from "../format";

export function Logo() {
  return (
    <Link to="/" className="logo" aria-label="Gradient home">
      <span className="logo-mark">
        <svg width="18" height="18" viewBox="0 0 32 32" aria-hidden>
          <path d="M5 24 L13 13 L19 19 L27 7" stroke="#00f0a0" strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      gradient
    </Link>
  );
}

export function Nav() {
  return (
    <header className="nav">
      <div className="container nav-inner">
        <Logo />
        <nav className="nav-links">
          <NavLink to="/jobs" className="keep">Jobs</NavLink>
          <NavLink to="/latest" className="keep">Latest</NavLink>
          <NavLink to="/hiring-posts">Hiring posts</NavLink>
          <NavLink to="/funded">Funded</NavLink>
          <NavLink to="/closed">Closed</NavLink>
          <NavLink to="/status">Status</NavLink>
          <NavLink to="/for-me" className="cta">For me</NavLink>
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="footer">
      <div className="container footer-inner">
        <div>
          <Logo />
          <p style={{ maxWidth: 420 }}>
            AI/ML openings for freshers to 4 years of experience, aggregated from employer career systems, LinkedIn and
            public job boards. Refreshed twice a day. We link to the original posting; apply on the employer's site.
          </p>
        </div>
        <div style={{ display: "flex", gap: 40 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <b style={{ color: "#000" }}>Explore</b>
            <Link to="/jobs">All jobs</Link>
            <Link to="/jobs?region=india">India</Link>
            <Link to="/jobs?region=remote">Remote</Link>
            <Link to="/for-me">Matched for me</Link>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <b style={{ color: "#000" }}>Platform</b>
            <Link to="/status">How it works</Link>
            <Link to="/closed">Closed roles</Link>
            <a href="/api/docs">API</a>
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Terms</Link>
            {import.meta.env.VITE_CONTACT_EMAIL ? <a href={`mailto:${import.meta.env.VITE_CONTACT_EMAIL}`}>Contact</a> : <Link to="/privacy">Contact</Link>}
          </div>
        </div>
      </div>
    </footer>
  );
}

export function TrustBadge({ label, score }: { label: TrustLabel; score?: number }) {
  return (
    <span className={`badge ${label}`} title={score != null ? `Trust score ${score}/100` : undefined}>
      {label === "verified" && "✓"} {TRUST_TEXT[label]}
    </span>
  );
}

export function ScoreRing({ value, small }: { value: number; small?: boolean }) {
  return (
    <div className={`ring${small ? " sm" : ""}`} style={{ ["--v" as string]: value }} aria-label={`Match score ${value}`}>
      <span>{value}</span>
    </div>
  );
}

export function LiveTag({ job }: { job: JobSummary }) {
  if (job.status === "closed") return <span className="badge closed">Closed</span>;
  const when = job.posted_at ?? job.first_seen_at;
  return (
    <span className={`live${isFresh(when) ? "" : " old"}`} title={job.posted_at ? `Posted ${new Date(job.posted_at).toLocaleString()}` : "The source gives no posted date; this is when Gradient first found it"}>
      {postedLabel(job.posted_at, job.first_seen_at)}
    </span>
  );
}

export function JobCard({ job, selected, onSelect, matched }: {
  job: JobSummary;
  selected?: boolean;
  onSelect?: (id: number) => void;
  matched?: string[];
}) {
  const pay = salary(job);
  const body = (
    <>
      <div className="card-top">
        <LiveTag job={job} />
        <TrustBadge label={job.trust_label} score={job.trust_score} />
      </div>
      <h3>{job.title}</h3>
      <div className="company">{job.company}</div>
      <div className="meta">
        <span>📍 {place(job)}</span>
        <span>{experience(job)}</span>
        {pay && <span>{pay}</span>}
        <span className="muted">via {SOURCE_TEXT[job.source] ?? job.source}</span>
      </div>
      {job.skills.length > 0 && (
        <div className="tags">
          {job.skills.slice(0, 5).map((s) => (
            <span key={s} className={`tag${matched?.includes(s) ? " hit" : ""}`}>{s}</span>
          ))}
        </div>
      )}
    </>
  );
  if (onSelect) {
    return (
      <button
        type="button"
        className={`job-card${selected ? " selected" : ""}`}
        style={{ textAlign: "left", width: "100%", font: "inherit", color: "inherit" }}
        onClick={() => onSelect(job.id)}
      >
        {body}
      </button>
    );
  }
  return <Link to={`/jobs/${job.id}`} className="job-card">{body}</Link>;
}

export function Skeletons({ n = 5 }: { n?: number }) {
  return <>{Array.from({ length: n }, (_, i) => <div key={i} className="skeleton" />)}</>;
}
