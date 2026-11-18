"""After-sweep email: run summary + today's apply queue. Sent from the scrape workflow over SMTP."""

import html
import json
import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Application, Job, ScrapeRun
from .queue import build_queue, today_ist

log = logging.getLogger("gradient.notify")


def owner_profile() -> dict | None:
    if settings.profile_json:
        return json.loads(settings.profile_json)
    if settings.profile_file.exists():
        return json.loads(settings.profile_file.read_text())
    return None


def _row(app: Application, job: Job) -> str:
    where = job.city or ("Remote" if job.work_mode == "remote" else job.country or "")
    missing = ", ".join((app.reasons or {}).get("missing_skills", [])[:4])
    extra = f'<br><span style="color:#8a6d00">CV gap: {html.escape(missing)}</span>' if app.lane == "tailor" and missing else ""
    return (f'<tr><td style="padding:6px 8px;border-bottom:1px solid #eee"><b>{app.score}</b></td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #eee"><a href="{html.escape(job.url)}">{html.escape(job.title)}</a>'
            f'<br><span style="color:#666">{html.escape(job.company)} · {html.escape(where)}</span>{extra}</td></tr>')


def compose(session: Session, added: list[Application], event: str) -> tuple[str, str]:
    day = today_ist()
    run = session.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(1)).first()
    st = (run.stats if run else {}) or {}
    apps = session.scalars(select(Application).where(Application.queued_on == day, Application.status == "queued")
                           .order_by(Application.score.desc())).all()
    jobs = {j.id: j for j in session.scalars(select(Job).where(Job.id.in_([a.job_id for a in apps])))} if apps else {}
    direct = [a for a in apps if a.lane == "direct" and a.job_id in jobs]
    tailor = [a for a in apps if a.lane == "tailor" and a.job_id in jobs]

    head = "Manual sweep finished" if event == "workflow_dispatch" else "Sweep finished"
    subject = f"Gradient: {len(direct)} ready + {len(tailor)} need a CV tweak ({len(added)} new today)"
    table = lambda rows: ('<table style="border-collapse:collapse;width:100%;font-size:14px">'  # noqa: E731
                          + "".join(_row(a, jobs[a.job_id]) for a in rows) + "</table>") if rows else "<p>None right now.</p>"
    body = f"""<div style="font-family:Arial,sans-serif;max-width:640px">
<h2 style="margin:0 0 4px">{head}</h2>
<p style="color:#555;margin:0 0 12px">Run #{run.id if run else '-'} · {run.status if run else '-'} ·
{st.get('kept', 0):,} AI/ML roles kept from {st.get('sources', 0):,} sources · {st.get('new', 0):,} new ·
{st.get('closed', 0):,} closed · {round(st.get('duration_s', 0) / 60)} min</p>
<p><a href="{settings.site_url}/apply" style="background:#111;color:#fff;padding:8px 14px;border-radius:6px;text-decoration:none">Open today's apply queue</a></p>
<h3>Ready to apply ({len(direct)})</h3><p style="color:#555;margin-top:-6px">Your CV already fits. Apply on the employer's site.</p>
{table(direct)}
<h3>Tailor your CV first ({len(tailor)})</h3><p style="color:#555;margin-top:-6px">Good roles where your CV undersells the fit. Open each in the queue and click "Tailor CV".</p>
{table(tailor)}
<p style="color:#999;font-size:12px;margin-top:18px">Daily cap {settings.daily_apply_cap}. Sent by your Gradient scrape workflow.</p></div>"""
    return subject, body


def send(subject: str, body: str) -> bool:
    if not (settings.smtp_user and settings.smtp_password):
        log.warning("email not configured (GRADIENT_SMTP_USER / GRADIENT_SMTP_PASSWORD); skipping")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"Gradient <{settings.smtp_user}>", settings.notify_to or settings.smtp_user
    msg.set_content("Open this email in an HTML-capable client, or visit " + settings.site_url + "/apply")
    msg.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as s:
        s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)
    return True


def after_sweep(session: Session, event: str) -> dict:
    """Top up today's queue, then email when it's a manual run or the queue gained roles."""
    profile = owner_profile()
    added = build_queue(session, profile) if profile else []
    session.commit()
    should_send = event == "workflow_dispatch" or bool(added)
    sent = False
    if should_send:
        subject, body = compose(session, added, event)
        sent = send(subject, body)
    return {"profile": bool(profile), "queued": len(added), "emailed": sent, "wanted_email": should_send}
