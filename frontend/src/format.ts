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

// Compact relative age for tables: "5d", "3w", "11mo", "2y".
export function fmtAgo(iso?: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "";
  const days = Math.floor((Date.now() - t) / 86_400_000);
  if (days < 1) return "today";
  if (days < 7) return days + "d";
  if (days < 60) return Math.round(days / 7) + "w";
  if (days < 365) return Math.round(days / 30) + "mo";
  return Math.round(days / 365) + "y";
}

export function fmtAgoLong(iso?: string | null): string {
  const a = fmtAgo(iso);
  return !a || a === "today" ? a : a + " ago";
}

// Postings older than ~6 months are probably filled; the UI flags them.
export function isStale(iso?: string | null): boolean {
  if (!iso) return false;
  const t = new Date(iso).getTime();
  return !isNaN(t) && Date.now() - t > 180 * 86_400_000;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}

export function locationText(job: Job): string {
  return job.city || job.country || job.location || "Location not specified";
}

export function effortText(job: Job): string {
  return (job.effort_signals || []).map((e) => EFFORT_LABELS[e] || e).join(", ");
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
