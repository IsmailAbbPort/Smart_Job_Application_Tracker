import { EFFORT_LABELS } from "./constants";
import type { Job } from "./types";

export function fmtSalary(job: Job): string | null {
  if (!job.salary_max && !job.salary_min) return null;
  const sym =
    ({ USD: "$", EUR: "€", GBP: "£" } as Record<string, string>)[job.salary_currency ?? ""] ||
    (job.salary_currency ? job.salary_currency + " " : "");
  const k = (n: number) => Math.round(n / 1000) + "k";
  if (job.salary_min && job.salary_max && job.salary_min !== job.salary_max)
    return `${sym}${k(job.salary_min)}-${k(job.salary_max)}`;
  return `${sym}${k(job.salary_max || job.salary_min!)}`;
}

export function fmtDate(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function fmtBytes(n?: number | null): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function locationText(job: Job): string {
  return job.city || job.country || job.location || "Location not specified";
}

export interface Badge {
  cls: string;
  text: string;
}

// Ported 1:1 from the old jobBadges(), returning data instead of HTML.
export function jobBadges(job: Job): Badge[] {
  const b: Badge[] = [];
  if (job.is_remote) b.push({ cls: "remote", text: "Remote" });
  if (job.is_european) b.push({ cls: "eu", text: "Europe" });
  if (job.language) b.push({ cls: "", text: job.language.toUpperCase() });
  if (job.required_languages?.length)
    b.push({ cls: "warn", text: `needs ${job.required_languages.join(", ")}` });
  if (job.visa_sponsorship === true) b.push({ cls: "good", text: "sponsors visa" });
  if (job.visa_sponsorship === false) b.push({ cls: "bad", text: "no sponsorship" });
  if (job.remote_region) b.push({ cls: "warn", text: `${job.remote_region.toUpperCase()}-only` });
  if (typeof job.timezone_overlap_hours === "number")
    b.push({
      cls: job.timezone_overlap_hours >= 4 ? "good" : "bad",
      text: `TZ ${job.timezone_overlap_hours}h`,
    });
  const salary = fmtSalary(job);
  if (salary) b.push({ cls: "good", text: salary });
  (job.effort_signals || []).forEach((e) =>
    b.push({ cls: "warn", text: EFFORT_LABELS[e] || e }),
  );
  if (typeof job.experience_gap === "number" && job.experience_gap > 0)
    b.push({ cls: "bad", text: `stretch +${job.experience_gap}y` });
  else if (typeof job.min_years_experience === "number")
    b.push({ cls: "", text: `${job.min_years_experience}+ yrs` });
  if (job.seniority) b.push({ cls: "warn", text: job.seniority });
  if (job.role_family) b.push({ cls: "", text: job.role_family });
  return b;
}

// Read a File as base64 (sans the data: prefix) for the CV upload endpoint.
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("could not read file"));
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.readAsDataURL(file);
  });
}
