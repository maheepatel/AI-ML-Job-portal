from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="GRADIENT_", extra="ignore")

    database_url: str = f"sqlite:///{(DATA_DIR / 'gradient.db').as_posix()}"
    companies_file: Path = DATA_DIR / "companies.yaml"
    profile_file: Path = DATA_DIR / "profile.json"
    # Hosts that build from a public repo get the owner profile as an env var instead of a file.
    profile_json: str | None = None
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    # Scheduling
    scrape_interval_hours: int = 12  # two sweeps a day: 06:00 and 18:00 IST
    run_on_start: bool = False
    # Single-container deploys: run the scheduler inside the API process (one machine, one disk).
    embedded_worker: bool = False
    # First boot on an empty disk: copy this snapshot in so the site is populated immediately.
    seed_db: Path = BACKEND_DIR / "seed" / "gradient-seed.db"

    # Fetching
    max_concurrency: int = 24
    sources_in_flight: int = 48  # lower on small machines to cap memory
    per_host_concurrency: int = 4
    request_timeout: int = 30

    # Lifecycle
    missed_runs_to_close: int = 2
    expire_after_days: int = 30
    liveness_batch: int = 600

    # Scope
    max_years_experience: int = 4

    # Optional sources
    enable_linkedin: bool = True

    # Owner tools (apply queue, CV tailoring, scrape-now). Unset admin_token = owner API disabled.
    admin_token: str | None = None
    github_token: str | None = None  # fine-grained PAT: Actions read/write on github_repo only
    github_repo: str = "maheepatel/AI-ML-Job-portal"
    scrape_workflow: str = "scrape.yml"
    master_cv_json: str | None = None  # structured master CV JSON (template: backend/data/master_cv.json, gitignored)
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    daily_apply_cap: int = 35
    site_url: str = "https://gradient-fau6.onrender.com"
    # Email alerts (Gmail: an app password, not the account password)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str | None = None
    smtp_password: str | None = None
    notify_to: str | None = None

    trust_proxy_headers: bool = False  # true on Fly/any reverse proxy that sets client-IP headers
    cors_origins: list[str] = ["http://localhost:5270"]


settings = Settings()
