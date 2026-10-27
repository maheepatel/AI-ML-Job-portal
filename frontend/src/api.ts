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
