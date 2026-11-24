import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { outreachApi, ownerToken, signalsApi, type Contacts, type FundedStartup } from "../api";
import { timeAgo } from "../format";

const DAYS: [number, string][] = [[7, "This week"], [30, "30 days"], [90, "90 days"]];
const KINDS: [string, string][] = [["all", "All"], ["news", "Raised (news)"], ["yc", "New YC batch"]];
// The three people worth emailing at a seed-stage startup, when YC doesn't list them for us.
const ROLE_SEARCHES: [string, string][] = [["Founder / CEO", "founder OR CEO"], ["CTO / tech lead", "CTO OR \"head of engineering\" OR \"founding engineer\""], ["AI / ML lead", "\"machine learning\" OR AI lead"]];

function roundLabel(r: string) {
  if (r.startsWith("yc-")) return `YC ${r.slice(3).replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}`;
  return r === "funding" ? "Funding" : r.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function peopleSearch(company: string, roles: string) {
  return `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(`${company} ${roles}`)}`;
}

export default function Funded() {
  const [days, setDays] = useState(30);
  const [kind, setKind] = useState("all");
  const [ai, setAi] = useState(true);
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [data, setData] = useState<{ items: FundedStartup[]; total: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const isOwner = useMemo(() => !!ownerToken.get(), []);

  useEffect(() => { document.title = "Recently funded AI startups · Gradient"; }, []);
  useEffect(() => {
    setData(null);
    setErr(null);
    const p = new URLSearchParams({ days: String(days), kind, ai: String(ai) });
    if (query) p.set("q", query);
    signalsApi.funded(p).then(setData).catch((e) => setErr(e.message));
  }, [days, kind, ai, query]);

  const search = (e: FormEvent) => { e.preventDefault(); setQuery(q.trim()); };

  return (
    <div className="container page-pad">
      <div className="eyebrow">Funded</div>
      <h1 className="page-h1">Startups that just raised</h1>
      <p className="muted" style={{ maxWidth: 720 }}>
        Right after a seed round, founders still hire themselves: no HR, no pipeline, fast decisions. Pick 3 people at each
        (founders first), write to them directly, and keep it short and in your own words.
      </p>

      <form className="search-pill" onSubmit={search} role="search" style={{ marginTop: 16 }}>
        <span aria-hidden>🔎</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Company, product or keyword…" aria-label="Search funded startups" />
        <button className="btn btn-ink btn-sm" type="submit">Search</button>
      </form>
      <div className="chips">
        {DAYS.map(([d, l]) => <button key={d} type="button" className={`chip${days === d ? " on" : ""}`} onClick={() => setDays(d)}>{l}</button>)}
        {KINDS.map(([k, l]) => <button key={k} type="button" className={`chip${kind === k ? " on" : ""}`} onClick={() => setKind(k)}>{l}</button>)}
        <button type="button" className={`chip${ai ? " on" : ""}`} onClick={() => setAi((v) => !v)}>{ai ? "AI startups" : "All sectors"}</button>
      </div>

      {err && <p className="owner-err" role="alert">{err}</p>}
      {data && <p className="caption" style={{ margin: "14px 0" }}>{data.total} startups</p>}
      {!data && !err && <p className="muted" style={{ marginTop: 16 }}>Loading…</p>}
      {data && data.items.length === 0 && <div className="empty">Nothing matches. Try a longer window or all sectors.</div>}
      <div className="funded-list">
        {data?.items.map((s) => <FundedCard key={s.id} s={s} isOwner={isOwner} />)}
      </div>
    </div>
  );
}

function FundedCard({ s, isOwner }: { s: FundedStartup; isOwner: boolean }) {
  const [contacts, setContacts] = useState<Contacts | null>(null);
  const [open, setOpen] = useState(false);
  const [logged, setLogged] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);

  const toggle = async () => {
    setOpen((o) => !o);
    if (!contacts) {
      try { setContacts(await outreachApi.contacts(s.id)); } catch (e) { setErr((e as Error).message); }
    }
  };
  const log = async (person: string, email: string | null) => {
    try {
      await outreachApi.log({ company: s.company, person, email, kind: "funding", ref_id: s.id });
      setLogged((x) => new Set(x).add(person));
    } catch (e) { setErr((e as Error).message); }
  };
  const site = s.website ? s.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "") : null;

  return (
    <article className="owner-card">
      <div className="funded-top">
        <div style={{ minWidth: 0 }}>
          <h3 className="funded-name">{s.company}</h3>
          <div className="caption">
            <span className="badge likely_genuine">{roundLabel(s.round)}</span>
            {s.amount && <b style={{ color: "var(--ink)", marginLeft: 8 }}>{s.amount}</b>}
            {" · "}{timeAgo(s.announced_at)}{s.location ? ` · ${s.location}` : ""}
          </div>
        </div>
        {s.open_jobs > 0 && <Link className="btn btn-mint btn-sm" to={`/jobs?q=${encodeURIComponent(s.company)}`}>{s.open_jobs} open role{s.open_jobs > 1 ? "s" : ""}</Link>}
      </div>
      {s.one_liner && <p style={{ margin: 0 }}>{s.one_liner}</p>}
      {s.source !== "yc" && <a className="caption" href={s.url} target="_blank" rel="noreferrer">{s.headline} ↗</a>}

      <div className="people">
        {s.people.map((p) => (
          <div key={p.name} className="person">
            <b>{p.name}</b> <span className="caption">{p.title}</span>
            <span className="person-links">
              {p.linkedin_url && <a href={p.linkedin_url} target="_blank" rel="noreferrer">LinkedIn</a>}
              {p.x_url && <a href={p.x_url} target="_blank" rel="noreferrer">X</a>}
            </span>
          </div>
        ))}
        {s.people.length < 3 && (
          <div className="person-find">
            <span className="caption">{s.people.length ? "Find one more:" : "Find 3 people:"}</span>
            {ROLE_SEARCHES.slice(s.people.length ? 1 : 0).map(([label, roles]) => (
              <a key={label} href={peopleSearch(s.company, roles)} target="_blank" rel="noreferrer" className="chip">{label} ↗</a>
            ))}
          </div>
        )}
      </div>

      <div className="owner-btns">
        {site && <a className="btn btn-ghost" href={s.website!} target="_blank" rel="noreferrer">{site} ↗</a>}
        {s.yc_slug && <a className="btn btn-ghost" href={`https://www.ycombinator.com/companies/${s.yc_slug}`} target="_blank" rel="noreferrer">YC page ↗</a>}
        {isOwner && <button type="button" className="btn btn-ink btn-sm" onClick={toggle}>{open ? "Hide emails" : "Emails & log outreach"}</button>}
      </div>

      {err && <p className="owner-err">{err}</p>}
      {open && contacts && (
        <div className="owner-tailor">
          {!contacts.domain && <p className="caption">No website on file, so no email formats to suggest. Check their LinkedIn page or website.</p>}
          {contacts.people.map((p) => (
            <div key={p.name} className="owner-diff">
              <b>{p.name} <span className="caption">{p.title}</span></b>
              <div className="email-guesses">
                {p.emails.map((e) => <button key={e} type="button" className="chip" onClick={() => navigator.clipboard?.writeText(e)} title="Copy">{e}</button>)}
              </div>
              {p.contacted || logged.has(p.name)
                ? <span className="caption">Logged ✓</span>
                : <button type="button" className="btn btn-ghost" onClick={() => log(p.name, p.emails[0] ?? null)}>I emailed {p.name.split(" ")[0]}</button>}
            </div>
          ))}
          {contacts.generic.length > 0 && (
            <div className="owner-diff">
              <b>Team inboxes</b>
              <div className="email-guesses">{contacts.generic.map((e) => <button key={e} type="button" className="chip" onClick={() => navigator.clipboard?.writeText(e)}>{e}</button>)}</div>
            </div>
          )}
          <p className="caption">These are common email formats, not verified addresses. Small startups mostly use first@company. Check one with a free email verifier before sending.</p>
        </div>
      )}
    </article>
  );
}
