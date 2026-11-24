import type { JobSummary } from "./api";

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return "just now";
  const mins = secs / 60;
  if (mins < 60) return `${Math.floor(mins)}m ago`;
  const hours = mins / 60;
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  const days = hours / 24;
  if (days < 30) return `${Math.floor(days)}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

export function liveFor(iso: string | null | undefined): string {
  if (!iso) return "Live";
  const hours = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  if (hours < 1) return "Live · just posted";
  if (hours < 24) return `Live for ${Math.floor(hours)}h`;
  return `Live for ${Math.floor(hours / 24)}d`;
}

/** "Posted 3h ago" when the source dates the role, else "Found 3h ago" (when Gradient first saw it). */
export function postedLabel(posted: string | null | undefined, firstSeen: string | null | undefined): string {
  const iso = posted ?? firstSeen;
  if (!iso) return "Date not given";
  const ago = timeAgo(iso);
  return `${posted ? "Posted" : "Found"} ${ago === "just now" ? "just now" : ago}`;
}

export function isFresh(iso: string | null | undefined): boolean {
  return !!iso && Date.now() - new Date(iso).getTime() < 72 * 3_600_000;
}

export function duration(from: string | null, to: string | null): string {
  if (!from || !to) return "—";
  const days = (new Date(to).getTime() - new Date(from).getTime()) / 86_400_000;
  if (days < 1) return `${Math.max(1, Math.round(days * 24))}h`;
  return `${Math.round(days)} days`;
}

export function place(job: Pick<JobSummary, "city" | "country" | "work_mode" | "location">): string {
  const where = job.city || job.country || job.location || "Location not listed";
  if (job.work_mode === "remote") return job.city || job.country ? `Remote · ${job.city || job.country}` : "Remote";
  if (job.work_mode === "hybrid") return `Hybrid · ${where}`;
  return where;
}

export function experience(job: Pick<JobSummary, "exp_min" | "exp_max" | "seniority">): string {
  if (job.seniority === "intern") return "Internship";
  if (job.exp_min != null) return job.exp_max != null ? `${job.exp_min}–${job.exp_max} yrs` : `${job.exp_min}+ yrs`;
  if (job.seniority === "entry") return "Entry level";
  if (job.seniority === "junior") return "Junior";
  if (job.seniority === "mid") return "Mid level";
  return "Exp. not stated";
}

const CUR: Record<string, string> = { USD: "$", INR: "₹", EUR: "€", GBP: "£" };

export function salary(job: JobSummary): string | null {
  const s = job.salary;
  if (!s || (!s.min && !s.max)) return null;
  const sym = CUR[s.currency || ""] ?? (s.currency ? `${s.currency} ` : "");
  const fmt = (n: number) => {
    if (s.currency === "INR" && n >= 100_000) return `${(n / 100_000).toFixed(n % 100_000 ? 1 : 0)}L`;
    if (n >= 1000) return `${Math.round(n / 1000)}k`;
    return `${n}`;
  };
  const range = s.min && s.max && s.max !== s.min ? `${fmt(s.min)}–${fmt(s.max)}` : fmt((s.min || s.max)!);
  const per = s.period === "hour" ? "/hr" : s.period === "month" ? "/mo" : "/yr";
  return `${sym}${range}${per}`;
}

export const TRUST_TEXT: Record<string, string> = {
  verified: "Verified",
  likely_genuine: "Likely genuine",
  caution: "Use caution",
  likely_scam: "Likely scam",
};

export const SOURCE_TEXT: Record<string, string> = {
  greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", workable: "Workable", recruitee: "Recruitee",
  smartrecruiters: "SmartRecruiters", workday: "Workday", amazon: "Amazon Jobs", microsoft: "Microsoft Careers",
  linkedin: "LinkedIn", simplify: "Simplify", remotive: "Remotive", remoteok: "RemoteOK", arbeitnow: "Arbeitnow",
  himalayas: "Himalayas", jobicy: "Jobicy", themuse: "The Muse", hn: "Hacker News",
};

export const CLOSE_TEXT: Record<string, string> = {
  removed_from_source: "Taken down by employer",
  liveness_failed: "Link dead / filled",
  deadline_passed: "Deadline passed",
  expired: "Expired (not re-confirmed)",
  out_of_scope: "Changed to senior / out of scope",
};
