"""Shared ingest primitives: the RawJob contract, the Source interface and the HTTP client."""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from scrapling.fetchers import AsyncFetcher

from ..config import settings

log = logging.getLogger("gradient.ingest")
logging.getLogger("scrapling").setLevel(logging.WARNING)


@dataclass
class RawJob:
    source_job_id: str
    title: str
    company: str
    url: str
    description: str = ""  # HTML or text; normalised later
    location: str = ""
    remote: bool | None = None
    posted_at: datetime | None = None
    deadline_at: datetime | None = None
    employment_type: str | None = None
    salary_text: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    company_domain: str | None = None
    # True when the source skipped the detail request because we already store this job;
    # the pipeline then refreshes sightings only and keeps the stored content.
    detail_skipped: bool = False


@dataclass
class FetchResult:
    jobs: list[RawJob] = field(default_factory=list)
    # Every id the source listed (before our AI/ML filtering). Lifecycle uses this, so a job
    # dropped by a classifier change is never mistaken for a job the employer removed.
    seen_ids: set[str] = field(default_factory=set)


class SourceError(Exception):
    pass


class Source(ABC):
    name: str = "source"
    kind: str = "board"  # ats | bigtech | linkedin | board | community
    # Authoritative = returns the employer's complete listing, so absence means removal.
    authoritative: bool = False
    min_interval_hours: float = 0
    priority: int = 50  # higher wins when the same job appears on several sources
    board_id: int | None = None  # set when the source comes from the boards table

    def __init__(self, key_suffix: str, company: str | None = None, domain: str | None = None):
        self.key = f"{self.name}:{key_suffix}"
        self.company = company
        self.domain = domain
        self.known_ids: set[str] = set()  # set by the pipeline before fetch()

    def known(self, job_id: str, title: str, url: str, company: str | None = None) -> RawJob | None:
        """Sighting-only RawJob for a job we already store (saves a detail request)."""
        if job_id in self.known_ids:
            return RawJob(source_job_id=job_id, title=title, company=company or self.company or "", url=url, detail_skipped=True)
        return None

    @abstractmethod
    async def fetch(self, http: "Http") -> FetchResult: ...

    def __repr__(self) -> str:
        return f"<{self.key}>"


# Hosts that throttle aggressively get fewer parallel requests than the default.
HOST_LIMITS = {"apply.careers.microsoft.com": 1, "www.linkedin.com": 2, "remotive.com": 1, "jobicy.com": 1}


class Http:
    """Scrapling AsyncFetcher with global + per-host concurrency limits and polite retries."""

    def __init__(self, max_concurrency: int | None = None, per_host: int | None = None):
        self._global = asyncio.Semaphore(max_concurrency or settings.max_concurrency)
        self._per_host_limit = per_host or settings.per_host_concurrency
        self._hosts: dict[str, asyncio.Semaphore] = {}
        self.requests = 0

    async def request(self, method: str, url: str, *, attempts: int = 3, **kwargs):
        host = urlparse(url).hostname or ""
        kwargs.setdefault("timeout", settings.request_timeout)
        kwargs.setdefault("retries", 1)
        kwargs.setdefault("follow_redirects", True)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            if host not in self._hosts:
                self._hosts[host] = asyncio.Semaphore(HOST_LIMITS.get(host, self._per_host_limit))
            async with self._global, self._hosts[host]:
                try:
                    self.requests += 1
                    fn = AsyncFetcher.get if method == "GET" else AsyncFetcher.post
                    resp = await fn(url, **kwargs)
                except Exception as exc:  # network errors, timeouts, TLS
                    last_exc = exc
                    resp = None
            if resp is not None:
                if resp.status in (429, 503, 999) or resp.status >= 500:
                    retry_after = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and str(retry_after).isdigit() else 2 ** attempt * 2
                    last_exc = SourceError(f"HTTP {resp.status} from {host}")
                    await asyncio.sleep(min(delay, 30) + random.random())
                    continue
                return resp
            await asyncio.sleep(2 ** attempt + random.random())
        raise SourceError(str(last_exc) if last_exc else f"request failed: {url}")

    async def get(self, url: str, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def get_json(self, url: str, **kwargs):
        resp = await self.get(url, **kwargs)
        if resp.status != 200:
            raise SourceError(f"HTTP {resp.status} for {url}")
        return resp.json()

    async def post_json(self, url: str, payload: dict, **kwargs):
        headers = {"Content-Type": "application/json", "Accept": "application/json", **kwargs.pop("headers", {})}
        resp = await self.request("POST", url, json=payload, headers=headers, **kwargs)
        if resp.status != 200:
            raise SourceError(f"HTTP {resp.status} for {url}")
        return resp.json()
