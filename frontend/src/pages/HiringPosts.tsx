import { useEffect, useMemo, useState } from "react";
import { outreachApi, ownerToken, signalsApi, type HiringPost } from "../api";
import { timeAgo } from "../format";

const ROLES: [string, string][] = [
  ["ML engineer", '"machine learning engineer" OR "ML engineer"'],
  ["AI engineer", '"AI engineer" OR "LLM engineer" OR "GenAI"'],
  ["Data scientist", '"data scientist"'],
  ["Computer vision", '"computer vision"'],
  ["Founding engineer", '"founding engineer" AI'],
];
const WINDOWS: [number, string][] = [[6, "6 hours"], [24, "24 hours"], [72, "3 days"], [168, "7 days"]];
const LIKES: [number, string][] = [[20, "Under 20 likes"], [100, "Under 100 likes"], [100000, "Any"]];

function linkedinPosts(role: string, india: boolean) {
  const kw = `hiring (${role})${india ? " (India OR Bengaluru OR Bangalore OR remote)" : ""}`;
  return `https://www.linkedin.com/search/results/content/?keywords=${encodeURIComponent(kw)}&datePosted=%22past-24h%22&sortBy=%22date_posted%22`;
}

function xPosts(role: string, india: boolean) {
  const since = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
  // -min_faves:100 keeps posts under 100 likes: the ones few people have answered yet.
  const q = `("we're hiring" OR "we are hiring" OR "is hiring") (${role})${india ? " (India OR Bengaluru OR remote)" : ""} -min_faves:100 -filter:replies since:${since}`;
  return `https://x.com/search?q=${encodeURIComponent(q)}&f=live`;
}

export default function HiringPosts() {
  const [hours, setHours] = useState(24);
  const [maxLikes, setMaxLikes] = useState(100);
  const [showBots, setShowBots] = useState(false);
  const [role, setRole] = useState(ROLES[0]);
  const [india, setIndia] = useState(true);
  const [data, setData] = useState<{ items: HiringPost[]; hidden: Record<string, number> } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [contacted, setContacted] = useState<Set<number>>(new Set());
  const isOwner = useMemo(() => !!ownerToken.get(), []);

  useEffect(() => { document.title = "Fresh hiring posts · Gradient"; }, []);
  useEffect(() => {
    setData(null);
    setErr(null);
    const q = new URLSearchParams({ hours: String(hours), max_likes: String(maxLikes), people_only: String(!showBots) });
    signalsApi.posts(q).then(setData).catch((e) => setErr(e.message));
  }, [hours, maxLikes, showBots]);

  const markContacted = async (p: HiringPost) => {
    try {
      await outreachApi.log({ company: p.author, person: p.author_handle, kind: "post", ref_id: p.id });
      setContacted((s) => new Set(s).add(p.id));
    } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="container page-pad">
      <div className="eyebrow">Hiring posts</div>
      <h1 className="page-h1">“We're hiring” posts, before the crowd</h1>
      <p className="muted" style={{ maxWidth: 720 }}>
        A post under a day old with fewer than 100 likes has barely been seen. Find the person who posted it, then send them
        a short email of your own: who you are, one thing you built with a number, why their team, and a 15-minute ask.
      </p>

      <section className="signal-box">
        <div>
          <b>Most of these posts are on LinkedIn and X</b>
          <p className="caption" style={{ margin: "2px 0 10px" }}>
            Both need you to be signed in, so Gradient can't read them. These buttons open their search already filtered to the last 24 hours, newest first
            {" "}(on X, also to posts under 100 likes).
          </p>
          <div className="chips" style={{ marginTop: 0 }}>
            {ROLES.map((r) => <button key={r[0]} type="button" className={`chip${role[0] === r[0] ? " on" : ""}`} onClick={() => setRole(r)}>{r[0]}</button>)}
            <button type="button" className={`chip${india ? " on" : ""}`} onClick={() => setIndia((v) => !v)}>{india ? "India + remote" : "Anywhere"}</button>
          </div>
        </div>
        <div className="signal-actions">
          <a className="btn btn-ink btn-sm" href={linkedinPosts(role[1], india)} target="_blank" rel="noreferrer">LinkedIn posts ↗</a>
          <a className="btn btn-ghost" href={xPosts(role[1], india)} target="_blank" rel="noreferrer">X posts ↗</a>
        </div>
      </section>

      <h2 className="sub-h2">Found for you on Bluesky and Mastodon</h2>
      <div className="chips" role="group" aria-label="Posted within">
        {WINDOWS.map(([h, l]) => <button key={h} type="button" className={`chip${hours === h ? " on" : ""}`} onClick={() => setHours(h)}>{l}</button>)}
      </div>
      <div className="chips" role="group" aria-label="Likes" style={{ marginTop: 8 }}>
        {LIKES.map(([n, l]) => <button key={n} type="button" className={`chip${maxLikes === n ? " on" : ""}`} onClick={() => setMaxLikes(n)}>{l}</button>)}
        <button type="button" className={`chip${showBots ? " on" : ""}`} onClick={() => setShowBots((v) => !v)}>{showBots ? "Including job-board bots" : "People only"}</button>
      </div>

      {err && <p className="owner-err" role="alert">{err}</p>}
      {data && (
        <p className="caption" style={{ margin: "14px 0" }}>
          {data.items.length} posts · hidden: {data.hidden.bots ?? 0} job-board bots, {data.hidden.senior ?? 0} senior/academic, {data.hidden.duplicates ?? 0} duplicates
        </p>
      )}
      {!data && !err && <p className="muted">Loading…</p>}
      {data && data.items.length === 0 && <div className="empty">No posts in this window. Widen it, or use the LinkedIn and X buttons above.</div>}
      <div className="post-list">
        {data?.items.map((p) => (
          <article key={p.id} className="post-card">
            <div className="post-head">
              <a href={p.author_url} target="_blank" rel="noreferrer" className="post-author">{p.author || p.author_handle}</a>
              <span className="caption">@{p.author_handle} · {p.source} · {timeAgo(p.posted_at)}</span>
              <span className={`post-likes${p.likes < 20 ? " low" : ""}`} title="Likes: fewer means fewer people have seen it">♥ {p.likes}</span>
            </div>
            <p className="post-text">{p.text}</p>
            {p.skills.length > 0 && <div className="owner-skills">{p.skills.slice(0, 6).map((s) => <span key={s} className="skill have">{s}</span>)}</div>}
            <div className="owner-btns">
              <a className="btn btn-ink btn-sm" href={p.url} target="_blank" rel="noreferrer">Open post ↗</a>
              {p.links.slice(0, 2).map((l) => <a key={l} className="btn btn-ghost" href={l} target="_blank" rel="noreferrer">{hostOf(l)} ↗</a>)}
              {isOwner && (contacted.has(p.id)
                ? <span className="caption">Logged in outreach ✓</span>
                : <button type="button" className="btn btn-ghost" onClick={() => markContacted(p)}>I emailed them</button>)}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function hostOf(url: string) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return "link"; }
}
