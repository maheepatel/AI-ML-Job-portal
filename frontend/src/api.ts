export type TrustLabel = "verified" | "likely_genuine" | "caution" | "likely_scam";

export interface JobSummary {
  id: number;
  title: string;
  company: string;
  url: string;
  location: string;
  city: string | null;
  country: string | null;
  work_mode: "remote" | "hybrid" | "onsite" | "unknown";
  role_family: string;
  seniority: string;
  exp_min: number | null;
  exp_max: number | null;
  skills: string[];
  source: string;
  source_kind: string;
  trust_score: number;
  trust_label: TrustLabel;
  salary: { min: number | null; max: number | null; currency: string | null; period: string | null } | null;
  employment_type: string | null;
  status: "open" | "closed";
  live_since: string | null;
  posted_at: string | null;
  first_seen_at: string;
  last_verified_at: string | null;
  closed_at: string | null;
  close_reason: string | null;
}

export interface JobDetail extends JobSummary {
  description: string;
  trust_reasons: { signal: string; impact: number; detail: string }[];
  close_evidence: string | null;
  reopened_count: number;
  last_seen_at: string;
  listings: { source: string; source_kind: string; url: string; status: string; first_seen_at: string }[];
}

export interface JobsPage {
  total: number;
  page: number;
  page_size: number;
  items: JobSummary[];
  family_counts: Record<string, number>;
}

export interface Stats {
  open: number;
  companies: number;
  new_4h: number;
  new_24h: number;
  closed_7d: number;
  india: number;
  remote: number;
  verified: number;
  flagged_scams: number;
  boards: number;
  families: Record<string, number>;
  interval_hours: number;
  running: boolean;
  next_run_at: string | null;
  last_run: { id: number; finished_at: string; status: string; stats: Record<string, number> } | null;
  ticker: { id: number; title: string; company: string; city: string | null; work_mode: string }[];
}

export interface Match {
  job_id: number;
  score: number;
  breakdown: Record<string, number>;
  matched_skills: string[];
  missing_skills: string[];
  why: string[];
  job: JobSummary;
}

export interface Profile {
  skills: string[];
  years_experience: number;
  target_roles: string[];
  locations: { city: string; country: string; remote_ok: boolean };
}

export interface MatchResponse {
  profile: Profile;
  matches: Match[];
}

export interface RunsResponse {
  runs: { id: number; started_at: string; finished_at: string | null; status: string; trigger: string; stats: Record<string, number> }[];
  sources: { source: string; sources: number; ok: number; failed: number; fetched: number; kept: number; new: number; closed: number }[];
  boards: Record<string, number>;
  boards_disabled: number;
  closures: Record<string, number>;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
  return res.json();
}

export const api = {
  stats: () => get<Stats>("/api/stats"),
  jobs: (params: URLSearchParams) => get<JobsPage>(`/api/jobs?${params}`),
  job: (id: string | number) => get<JobDetail>(`/api/jobs/${id}`),
  runs: () => get<RunsResponse>("/api/runs"),
  match: (exp?: string) => get<MatchResponse>(`/api/match?limit=60${exp ? `&exp=${exp}` : ""}`),
  matchResume: async (file: File): Promise<MatchResponse> => {
    const body = new FormData();
    body.append("file", file);
    const res = await fetch("/api/match/resume?limit=60", { method: "POST", body });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    return res.json();
  },
};

// ---------------------------------------------------------------- owner (needs the admin password)

export interface OwnerApp {
  id: number;
  job_id: number;
  lane: "direct" | "tailor";
  status: "queued" | "applied" | "skipped" | "interview" | "offer" | "rejected" | "ghosted";
  score: number;
  reasons: { matched_skills?: string[]; missing_skills?: string[]; why?: string[] };
  queued_on: string;
  applied_at: string | null;
  follow_up_at: string | null;
  notes: string | null;
  tailored: boolean;
  job: { id: number; title: string; company: string; url: string; location: string; city: string | null; country: string | null;
         work_mode: string; status: string; trust_label: TrustLabel; source: string; live_since: string | null } | null;
}

export interface QueueResponse {
  day: string;
  items: OwnerApp[];
  counts: Record<string, number>;
  queued_today: number;
  cap: number;
  callback_rate: number | null;
  applied_total: number;
}

export interface CV {
  name: string;
  headline?: string;
  summary: string;
  skills: string[];
  experience: { id: string; title: string; org: string; dates: string; bullets: string[] }[];
  projects: { id: string; title: string; bullets: string[] }[];
}

export interface Tailored {
  master: CV;
  cv: CV;
  gaps: string[];
  answers: Record<string, string>;
  warnings: string[];
}

export interface ScrapeStatus {
  run: { id: number; status: string; conclusion: string | null; event: string; created_at: string; started_at: string | null; url: string } | null;
  expected_seconds: number;
  eta_seconds: number | null;
  last_sweep: { id: number; finished_at: string; status: string; kept: number; new: number } | null;
  error: string | null;
}

const TOKEN_KEY = "gradient-owner";

export const ownerToken = {
  get: (): string | null => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string) => { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* private mode: session only */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } },
};

async function owner<T>(path: string, init: RequestInit = {}, token = ownerToken.get()): Promise<T> {
  const res = await fetch(`/api/owner${path}`, {
    ...init,
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), "X-Admin-Token": token ?? "", ...init.headers },
  });
  if (!res.ok) {
    const err = new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const ownerApi = {
  me: (token?: string) => owner<{ ok: boolean; features: Record<string, boolean>; daily_cap: number }>("/me", {}, token ?? ownerToken.get()),
  queue: (view: "today" | "backlog" | "tracker") => owner<QueueResponse>(`/queue?view=${view}`),
  build: () => owner<{ added: number }>("/queue/build", { method: "POST" }),
  update: (id: number, body: { status?: string; notes?: string; follow_up_days?: number }) =>
    owner<OwnerApp>(`/applications/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  save: (jobId: number) => owner<OwnerApp>(`/jobs/${jobId}/save`, { method: "POST" }),
  tailor: (id: number) => owner<Tailored>(`/applications/${id}/tailor`, { method: "POST" }),
  tailored: (id: number) => owner<Tailored>(`/applications/${id}/tailored`),
  scrape: () => owner<{ started: boolean; reason?: string }>("/scrape", { method: "POST" }),
  scrapeStatus: () => owner<ScrapeStatus>("/scrape"),
  pdf: async (id: number, which: "tailored" | "master", filename: string) => {
    const res = await fetch(`/api/owner/applications/${id}/cv.pdf?which=${which}`, { headers: { "X-Admin-Token": ownerToken.get() ?? "" } });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: filename });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  },
};
