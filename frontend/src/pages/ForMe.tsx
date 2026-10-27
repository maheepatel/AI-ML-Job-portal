import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Match, type MatchResponse } from "../api";
import { experience, place, salary, timeAgo } from "../format";
import { LiveTag, ScoreRing, Skeletons, TrustBadge } from "../components/ui";

const LABELS: Record<string, string> = {
  skills: "Skills", similarity: "Text match", experience: "Experience", role: "Role fit", location: "Location", freshness: "Freshness",
};

export default function ForMe() {
  const [data, setData] = useState<MatchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"owner" | "upload">("owner");
  const [hideInterns, setHideInterns] = useState(true);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (mode !== "owner") return;
    setData(null);
    setError(null);
    api.match(hideInterns ? "no-intern" : undefined).then(setData).catch((e) => setError(e.message));
  }, [mode, hideInterns]);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      setData(await api.matchResume(file));
      setMode("upload");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const matches = (data?.matches ?? []).filter((m) => !(hideInterns && m.job.seniority === "intern"));
  const p = data?.profile;

  return (
    <>
      <section className="band band-mint" style={{ paddingTop: 48, paddingBottom: 48 }}>
        <div className="container feature" style={{ alignItems: "start" }}>
          <div>
            <div className="eyebrow">For me</div>
            <h1 style={{ fontSize: "clamp(36px,5.5vw,60px)" }}>Roles that fit your résumé</h1>
            <p style={{ font: "300 18px/1.6 var(--ui)", maxWidth: 520 }}>
              {mode === "owner"
                ? "Ranked against Mahendar's résumé: AI/software developer, ~2 years, Python · ML · NLP · GenAI · CV, Bengaluru."
                : "Ranked against the résumé you uploaded. It was parsed in memory and not stored."}
            </p>
            <div className="upload" onClick={() => fileRef.current?.click()} role="button" tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && fileRef.current?.click()}>
              <input ref={fileRef} type="file" accept="application/pdf" hidden onChange={(e) => onFile(e.target.files?.[0])} />
              <b>{busy ? "Reading résumé…" : "Match a different résumé"}</b>
              <div className="caption">PDF up to 5 MB · parsed in memory, never saved</div>
            </div>
            {mode === "upload" && (
              <button type="button" className="btn btn-ghost" style={{ marginTop: 12 }} onClick={() => setMode("owner")}>← Back to Mahendar's matches</button>
            )}
          </div>
          <div className="profile-card">
            {p ? (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <b style={{ font: "700 24px var(--display)" }}>Profile read from résumé</b>
                  <span className="badge likely_genuine">{p.years_experience} yrs exp</span>
                </div>
                <div className="caption" style={{ margin: "6px 0 12px" }}>
                  📍 {p.locations.city}, {p.locations.country} · open to remote
                </div>
                <h4 className="eyebrow" style={{ margin: "0 0 6px" }}>Skills detected ({p.skills.length})</h4>
                <div className="tags" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {p.skills.map((s) => <span key={s} className="tag hit">{s}</span>)}
                </div>
                <h4 className="eyebrow" style={{ margin: "16px 0 6px" }}>Target roles</h4>
                <div className="tags" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {p.target_roles.map((s) => <span key={s} className="tag">{s}</span>)}
                </div>
              </>
            ) : <Skeletons n={2} />}
          </div>
        </div>
      </section>

      <section className="container" style={{ padding: "32px 16px 96px" }}>
        <div className="list-head" style={{ marginBottom: 16 }}>
          <span><b>{matches.length}</b> best-fit open roles</span>
          <label style={{ display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
            <input type="checkbox" checked={hideInterns} onChange={(e) => setHideInterns(e.target.checked)} /> Hide internships
          </label>
        </div>
        {error && <div className="empty">{error}</div>}
        {!data && !error && <Skeletons n={6} />}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {matches.map((m) => <MatchRow key={m.job_id} m={m} />)}
        </div>
      </section>
    </>
  );
}

function MatchRow({ m }: { m: Match }) {
  const j = m.job;
  const pay = salary(j);
  return (
    <div className="match-row">
      <ScoreRing value={m.score} />
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <LiveTag job={j} />
          <TrustBadge label={j.trust_label} score={j.trust_score} />
          <span className="caption">first seen {timeAgo(j.first_seen_at)}</span>
        </div>
        <Link to={`/jobs/${j.id}`}><h3 style={{ font: "600 17px/1.35 var(--ui)", margin: "6px 0 2px" }}>{j.title}</h3></Link>
        <div style={{ fontSize: 14 }}>
          <b>{j.company}</b> · {place(j)} · {experience(j)}{pay ? ` · ${pay}` : ""}
        </div>
        <div className="caption" style={{ marginTop: 4 }}>{m.why.join(" · ")}</div>
        <div className="tags" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
          {m.matched_skills.slice(0, 6).map((s) => <span key={s} className="tag hit">✓ {s}</span>)}
          {m.missing_skills.slice(0, 4).map((s) => <span key={s} className="tag miss">+ {s}</span>)}
        </div>
        <div className="bars">
          {Object.entries(m.breakdown).map(([k, v]) => (
            <div key={k} className="bar">{LABELS[k] ?? k}<i style={{ ["--w" as string]: `${Math.round(v * 100)}%` }} /></div>
          ))}
        </div>
      </div>
      <a className="btn btn-ink btn-sm apply" href={j.url} target="_blank" rel="noopener noreferrer nofollow">Apply ↗</a>
    </div>
  );
}
