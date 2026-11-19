import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ownerApi, ownerToken, type OwnerApp, type QueueResponse, type ScrapeStatus, type Tailored } from "../api";
import { timeAgo } from "../format";
import { ScoreRing, TrustBadge } from "../components/ui";

type Tab = "direct" | "tailor" | "backlog" | "tracker";

export default function Apply() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [features, setFeatures] = useState<Record<string, boolean>>({});

  useEffect(() => {
    document.title = "Apply queue · Gradient";
    if (!ownerToken.get()) return setAuthed(false);
    ownerApi.me().then((r) => { setFeatures(r.features); setAuthed(true); }).catch(() => setAuthed(false));
  }, []);

  if (authed === null) return <div className="container owner"><p className="muted">Checking…</p></div>;
  if (!authed) return <Login onOk={(f) => { setFeatures(f); setAuthed(true); }} />;
  return <Owner features={features} onLogout={() => { ownerToken.clear(); setAuthed(false); }} />;
}

function Login({ onOk }: { onOk: (f: Record<string, boolean>) => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const r = await ownerApi.me(pw);
      ownerToken.set(pw);
      onOk(r.features);
    } catch (x) {
      const status = (x as { status?: number }).status;
      setErr(status === 404 ? "Owner tools are off: set GRADIENT_ADMIN_TOKEN on Render first." : (x as Error).message);
    }
  };
  return (
    <div className="container owner" style={{ maxWidth: 440 }}>
      <h1 className="owner-h1">Owner sign-in</h1>
      <p className="muted">Your apply queue, tailored CVs and the scrape-now button live here.</p>
      <form onSubmit={submit} className="owner-login">
        <label htmlFor="pw" className="caption">Owner password (GRADIENT_ADMIN_TOKEN)</label>
        <input id="pw" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" required />
        <button className="btn btn-ink btn-sm" type="submit">Sign in</button>
        {err && <p className="owner-err" role="alert">{err}</p>}
      </form>
    </div>
  );
}

function Owner({ features, onLogout }: { features: Record<string, boolean>; onLogout: () => void }) {
  const [tab, setTab] = useState<Tab>("direct");
  const [data, setData] = useState<QueueResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);

  const load = useCallback(() => {
    setErr(null);
    const view = tab === "tracker" ? "tracker" : tab === "backlog" ? "backlog" : "today";
    ownerApi.queue(view).then(setData).catch((e) => setErr(e.message));
  }, [tab]);
  useEffect(load, [load]);

  const build = async () => {
    setBuilding(true);
    try { await ownerApi.build(); load(); } catch (e) { setErr((e as Error).message); } finally { setBuilding(false); }
  };

  const patch = async (a: OwnerApp, body: { status?: string; notes?: string; follow_up_days?: number }) => {
    try {
      const next = await ownerApi.update(a.id, body);
      setData((d) => d && { ...d, items: d.items.map((x) => (x.id === a.id ? next : x)).filter((x) => tab === "tracker" || x.status === "queued") });
    } catch (e) { setErr((e as Error).message); }
  };

  const items = (data?.items ?? []).filter((a) => (tab === "direct" ? a.lane === "direct" : tab === "tailor" ? a.lane === "tailor" : true));
  const lanes = { direct: data?.items.filter((a) => a.lane === "direct").length, tailor: data?.items.filter((a) => a.lane === "tailor").length };

  return (
    <div className="container owner">
      <div className="owner-head">
        <div>
          <div className="eyebrow">Owner</div>
          <h1 className="owner-h1">Apply queue</h1>
          {data && (
            <p className="muted" style={{ margin: 0 }}>
              {data.queued_today}/{data.cap} queued today · {data.applied_total} applied overall
              {data.callback_rate != null && ` · ${data.callback_rate}% callback rate`}
            </p>
          )}
        </div>
        <div className="owner-actions">
          <button type="button" className="btn btn-ghost" onClick={build} disabled={building}>{building ? "Finding roles…" : "Top up today's queue"}</button>
          <button type="button" className="btn btn-ghost" onClick={onLogout}>Sign out</button>
        </div>
      </div>

      <ScrapePanel enabled={!!features.scrape_button} onDone={load} />

      {!features.tailoring && <p className="owner-note">CV tailoring is off: add GRADIENT_GROQ_API_KEY and GRADIENT_MASTER_CV_JSON on Render.</p>}

      <div className="chips" role="tablist" style={{ marginBottom: 16 }}>
        {([["direct", `Ready to apply${tab !== "tracker" && tab !== "backlog" && lanes.direct != null ? ` (${lanes.direct})` : ""}`],
           ["tailor", `Tailor CV first${tab !== "tracker" && tab !== "backlog" && lanes.tailor != null ? ` (${lanes.tailor})` : ""}`],
           ["backlog", "Earlier days"], ["tracker", "Tracker"]] as [Tab, string][]).map(([t, label]) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={`chip${tab === t ? " on" : ""}`} onClick={() => setTab(t)}>{label}</button>
        ))}
      </div>

      {err && <p className="owner-err" role="alert">{err}</p>}
      {!data && !err && <p className="muted">Loading…</p>}
      {data && items.length === 0 && (
        <div className="empty">
          {tab === "tracker" ? "Nothing applied yet. Mark roles as applied from the queue and they show up here."
            : "Nothing here. Click “Top up today's queue”, or wait for the next sweep."}
        </div>
      )}
      <div className="owner-list">
        {items.map((a) => tab === "tracker"
          ? <TrackerRow key={a.id} a={a} onPatch={(b) => patch(a, b)} />
          : <QueueCard key={a.id} a={a} canTailor={!!features.tailoring} onPatch={(b) => patch(a, b)} />)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- scrape now

function ScrapePanel({ enabled, onDone }: { enabled: boolean; onDone: () => void }) {
  const [st, setSt] = useState<ScrapeStatus | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const wasRunning = useRef(false);

  const poll = useCallback(() => ownerApi.scrapeStatus().then(setSt).catch(() => {}), []);
  useEffect(() => { if (enabled) poll(); }, [enabled, poll]);

  const running = !!st?.run && st.run.status !== "completed";
  useEffect(() => {
    if (!running) {
      if (wasRunning.current && st?.run) {
        const ok = st.run.conclusion === "success";
        setMsg(ok ? "Sweep finished. The email with today's queue is on its way." : `Sweep ended: ${st.run.conclusion}.`);
        try {
          if ("Notification" in window && Notification.permission === "granted") new Notification("Gradient sweep finished", { body: ok ? "New roles are in your queue." : `Result: ${st.run.conclusion}` });
        } catch { /* notifications unsupported */ }
        onDone();
      }
      wasRunning.current = false;
      return;
    }
    wasRunning.current = true;
    const t = setInterval(poll, 15000);
    return () => clearInterval(t);
  }, [running, st, poll, onDone]);

  // Count down locally between polls so the ETA moves every second.
  const [now, setNow] = useState(Date.now());
  useEffect(() => { if (!running) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, [running]);

  const start = async () => {
    setMsg(null);
    try { if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission(); } catch { /* ignore */ }
    try {
      const r = await ownerApi.scrape();
      setMsg(r.started ? "Started. GitHub takes ~20 s to pick it up." : r.reason ?? "Not started");
      setTimeout(poll, 8000);
    } catch (e) { setMsg((e as Error).message); }
  };

  if (!enabled) {
    return <p className="owner-note">Scrape-now button is off: add GRADIENT_GITHUB_TOKEN on Render. Sweeps still run twice a day.</p>;
  }
  const startedAt = st?.run ? new Date(st.run.started_at ?? st.run.created_at).getTime() : 0;
  const elapsed = running ? Math.max(0, (now - startedAt) / 1000) : 0;
  const total = st?.expected_seconds ?? 900;
  const left = Math.max(0, total - elapsed);
  const pct = running ? Math.min(97, (elapsed / total) * 100) : 0;

  return (
    <section className="owner-scrape" aria-live="polite">
      <div>
        <b>{running ? (st?.run?.status === "queued" ? "Sweep queued on GitHub…" : "Sweep running") : "Scrape every source now"}</b>
        <div className="caption">
          {running ? `About ${fmt(left)} left (a sweep usually takes ${fmt(total)})`
            : st?.last_sweep ? `Last sweep ${timeAgo(st.last_sweep.finished_at)} · ${st.last_sweep.kept?.toLocaleString() ?? 0} roles` : "Runs on GitHub Actions, ~15–20 min"}
          {st?.run && <> · <a href={st.run.url} target="_blank" rel="noreferrer">GitHub run</a></>}
        </div>
        {running && <div className="owner-bar"><span style={{ width: `${pct}%` }} /></div>}
        {msg && <div className="caption" style={{ marginTop: 6 }}>{msg}</div>}
        {st?.error && <div className="owner-err">{st.error}</div>}
      </div>
      <button type="button" className="btn btn-ink btn-sm" onClick={start} disabled={running}>{running ? "Running…" : "Scrape now"}</button>
    </section>
  );
}

function fmt(s: number) {
  const m = Math.round(s / 60);
  return m < 1 ? "under a minute" : `${m} min`;
}

// ---------------------------------------------------------------- queue card

function QueueCard({ a, canTailor, onPatch }: { a: OwnerApp; canTailor: boolean; onPatch: (b: { status: string }) => void }) {
  const [open, setOpen] = useState(false);
  const j = a.job;
  if (!j) return null;
  const where = j.city ?? (j.work_mode === "remote" ? "Remote" : j.country ?? "");
  const filename = `CV_${j.company.replace(/[^a-z0-9]/gi, "")}.pdf`;
  return (
    <article className="owner-card">
      <div className="owner-card-top">
        <ScoreRing value={a.score} small />
        <div style={{ flex: 1, minWidth: 0 }}>
          <Link to={`/jobs/${j.id}`} className="owner-title">{j.title}</Link>
          <div className="caption">{j.company} · {where}{j.live_since && ` · live ${timeAgo(j.live_since)}`} · via {j.source}</div>
        </div>
        <TrustBadge label={j.trust_label} />
      </div>
      <div className="owner-skills">
        {(a.reasons.matched_skills ?? []).slice(0, 6).map((s) => <span key={s} className="skill have">{s}</span>)}
        {(a.reasons.missing_skills ?? []).slice(0, 4).map((s) => <span key={s} className="skill miss" title="The job asks for this; your CV doesn't show it">{s}</span>)}
      </div>
      {a.reasons.why && <div className="caption">{a.reasons.why.join(" · ")}</div>}
      <div className="owner-btns">
        <a className="btn btn-ink btn-sm" href={j.url} target="_blank" rel="noreferrer">Open &amp; apply ↗</a>
        <button type="button" className="btn btn-ghost" onClick={() => onPatch({ status: "applied" })}>Mark applied</button>
        {canTailor && <button type="button" className={`btn ${a.lane === "tailor" ? "btn-mint btn-sm" : "btn-ghost"}`} onClick={() => setOpen((o) => !o)}>{open ? "Hide CV" : a.tailored ? "Tailored CV" : "Tailor CV"}</button>}
        <button type="button" className="btn btn-ghost" onClick={() => ownerApi.pdf(a.id, "master", filename)}>Master CV</button>
        <button type="button" className="btn btn-ghost" onClick={() => onPatch({ status: "skipped" })}>Skip</button>
      </div>
      {open && <TailorPanel a={a} filename={filename} />}
    </article>
  );
}

function TailorPanel({ a, filename }: { a: OwnerApp; filename: string }) {
  const [t, setT] = useState<Tailored | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try { setT(await ownerApi.tailor(a.id)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }, [a.id]);

  useEffect(() => {
    if (a.tailored) ownerApi.tailored(a.id).then(setT).catch(() => run());
    else run();
  }, [a.id, a.tailored, run]);

  if (busy) return <div className="owner-tailor"><p className="muted">Tailoring your CV to this role (10–20 s)…</p></div>;
  if (err) return <div className="owner-tailor"><p className="owner-err">{err}</p><button type="button" className="btn btn-ghost" onClick={run}>Try again</button></div>;
  if (!t) return null;

  const changed: { where: string; before: string; after: string }[] = [];
  for (const sec of ["experience", "projects"] as const) {
    for (const item of t.cv[sec]) {
      const orig = t.master[sec].find((x) => x.id === item.id);
      item.bullets.forEach((b) => { if (orig && !orig.bullets.includes(b)) changed.push({ where: item.title, before: closest(b, orig.bullets), after: b }); });
    }
  }
  const dropped = t.master.projects.filter((p) => !t.cv.projects.some((x) => x.id === p.id)).map((p) => p.title);

  return (
    <div className="owner-tailor">
      <h4>Review before you download</h4>
      <p className="caption">Only reordered and reworded from your real CV. Anything that added facts was rejected automatically.</p>
      {t.cv.summary !== t.master.summary && (
        <Diff where="Summary" before={t.master.summary} after={t.cv.summary} />
      )}
      <div className="owner-diff"><b>Skills order</b><div className="caption">{t.cv.skills.slice(0, 12).join(", ")}…</div></div>
      {changed.map((c, i) => <Diff key={i} {...c} />)}
      {dropped.length > 0 && <div className="owner-diff"><b>Projects left out for this role</b><div className="caption">{dropped.join(", ")}</div></div>}
      {t.warnings.length > 0 && (
        <div className="owner-warn"><b>Rewrites rejected</b><ul>{t.warnings.map((w) => <li key={w}>{w}</li>)}</ul></div>
      )}
      {t.gaps.length > 0 && (
        <div className="owner-warn"><b>Gaps the job asks for (don't claim these; mention honestly or learn them)</b><ul>{t.gaps.map((g) => <li key={g}>{g}</li>)}</ul></div>
      )}
      {Object.keys(t.answers).length > 0 && (
        <div className="owner-answers">
          <b>Draft answers for the application form</b>
          {Object.entries(t.answers).map(([k, v]) => (
            <div key={k} className="owner-answer">
              <div className="caption">{k.replace(/_/g, " ")}</div>
              <p>{v}</p>
              <button type="button" className="btn btn-ghost" onClick={() => navigator.clipboard?.writeText(v)}>Copy</button>
            </div>
          ))}
        </div>
      )}
      <div className="owner-btns">
        <button type="button" className="btn btn-ink btn-sm" onClick={() => ownerApi.pdf(a.id, "tailored", filename)}>Download tailored CV (PDF)</button>
        <button type="button" className="btn btn-ghost" onClick={run}>Regenerate</button>
      </div>
    </div>
  );
}

function Diff({ where, before, after }: { where: string; before: string; after: string }) {
  return (
    <div className="owner-diff">
      <b>{where}</b>
      <div className="owner-before">{before}</div>
      <div className="owner-after">{after}</div>
    </div>
  );
}

function closest(text: string, options: string[]): string {
  const words = new Set(text.toLowerCase().split(/\W+/));
  let best = options[0] ?? "", score = -1;
  for (const o of options) {
    const s = o.toLowerCase().split(/\W+/).filter((w) => words.has(w)).length;
    if (s > score) { best = o; score = s; }
  }
  return best;
}

// ---------------------------------------------------------------- tracker

const STATUSES = ["applied", "interview", "offer", "rejected", "ghosted", "queued"];

function TrackerRow({ a, onPatch }: { a: OwnerApp; onPatch: (b: { status?: string; notes?: string; follow_up_days?: number }) => void }) {
  const [notes, setNotes] = useState(a.notes ?? "");
  const j = a.job;
  const due = a.follow_up_at && new Date(a.follow_up_at).getTime() < Date.now() && a.status === "applied";
  return (
    <article className="owner-card owner-row">
      <div style={{ flex: 1, minWidth: 0 }}>
        {j ? <Link to={`/jobs/${j.id}`} className="owner-title">{j.title}</Link> : <b>Job removed</b>}
        <div className="caption">
          {j?.company} · applied {a.applied_at ? timeAgo(a.applied_at) : "-"}
          {a.follow_up_at && a.status === "applied" && (due ? <b className="owner-due"> · follow up now</b> : ` · follow up ${new Date(a.follow_up_at).toLocaleDateString()}`)}
        </div>
        <input className="owner-notes" value={notes} placeholder="Notes: recruiter name, referral, round…" onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (a.notes ?? "") && onPatch({ notes })} aria-label="Notes" />
      </div>
      <div className="owner-row-side">
        <select value={a.status} onChange={(e) => onPatch({ status: e.target.value })} aria-label="Status">
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {a.status === "applied" && <button type="button" className="btn btn-ghost" onClick={() => onPatch({ follow_up_days: 7 })}>Followed up</button>}
      </div>
    </article>
  );
}
