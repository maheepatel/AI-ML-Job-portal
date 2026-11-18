"""Start the scrape workflow and read its progress through GitHub's REST API."""

import json
import urllib.error
import urllib.request

from ..config import settings

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


def _call(method: str, path: str, body: dict | None = None) -> dict:
    if not settings.github_token:
        raise GitHubError("GRADIENT_GITHUB_TOKEN is not set on the server")
    req = urllib.request.Request(
        f"{API}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "gradient-jobs"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        # The token itself never reaches the message; GitHub's error text is safe to show the owner.
        detail = exc.read().decode(errors="replace")[:300]
        raise GitHubError(f"GitHub {exc.code}: {detail}") from None
    return json.loads(raw) if raw else {}


def dispatch_scrape() -> None:
    _call("POST", f"/repos/{settings.github_repo}/actions/workflows/{settings.scrape_workflow}/dispatches", {"ref": "main"})


def latest_scrape_run() -> dict | None:
    data = _call("GET", f"/repos/{settings.github_repo}/actions/workflows/{settings.scrape_workflow}/runs?per_page=1")
    runs = data.get("workflow_runs") or []
    if not runs:
        return None
    r = runs[0]
    return {"id": r["id"], "status": r["status"], "conclusion": r["conclusion"], "event": r["event"],
            "created_at": r["created_at"], "started_at": r.get("run_started_at"), "updated_at": r["updated_at"],
            "url": r["html_url"]}
