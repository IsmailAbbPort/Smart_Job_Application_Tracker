import { CAIRO_OFFSET } from "../../constants";
import type { Preferences } from "../../types";

// One flat object drives the whole filter card. Split into the three quick
// filters (Remote / City / Results, point 2) plus the advanced set (point 4).
export interface FilterState {
  // Quick (always visible)
  remote: "" | "true" | "false";
  city: string;
  limit: string;
  // Location (advanced)
  cities: string[];
  country: string;
  region: string;
  // Language & timezone (advanced)
  language: string; // ISO code, single
  knownLangs: string[]; // ISO codes, multi
  tzOffset: number | null;
  // Compensation & experience (advanced)
  minSalary: string;
  currency: string;
  period: "year" | "month";
  yearsExp: string;
  maxGap: string;
  maxAge: string;
  requireSalary: boolean;
  // Role & seniority (advanced)
  roleFamilies: string[];
  exclTitles: string[];
  hideSenior: boolean;
  hideIntern: boolean;
  // Meta
  ignorePrefs: boolean;
}

export const defaultFilters: FilterState = {
  remote: "",
  city: "",
  limit: "25",
  cities: [],
  country: "",
  region: "",
  language: "",
  knownLangs: [],
  tzOffset: CAIRO_OFFSET,
  minSalary: "",
  currency: "",
  period: "year",
  yearsExp: "",
  maxGap: "",
  maxAge: "",
  requireSalary: false,
  roleFamilies: [],
  exclTitles: [],
  hideSenior: false,
  hideIntern: false,
  ignorePrefs: false,
};

// Number of advanced filters currently set (drives the chip on the toggle).
export function advancedCount(f: FilterState): number {
  let n = 0;
  if (f.cities.length) n++;
  if (f.country.trim()) n++;
  if (f.region) n++;
  if (f.language) n++;
  if (f.knownLangs.length) n++;
  if (f.minSalary.trim()) n++;
  if (f.yearsExp.trim()) n++;
  if (f.maxGap.trim()) n++;
  if (f.maxAge.trim()) n++;
  if (f.roleFamilies.length) n++;
  if (f.exclTitles.length) n++;
  if (f.requireSalary) n++;
  if (f.hideSenior) n++;
  if (f.hideIntern) n++;
  if (f.ignorePrefs) n++;
  return n;
}

// Build the /match/shortlist query string (ported from buildParams()).
export function buildParams(f: FilterState, cvId: string): URLSearchParams {
  const p = new URLSearchParams();
  if (cvId) p.set("cv_id", cvId);
  p.set("limit", f.limit || "25");
  if (f.remote) p.set("is_remote", f.remote);
  if (f.region) p.set("region", f.region);
  if (f.ignorePrefs) p.set("ignore_prefs", "true");
  if (f.country.trim()) p.set("country", f.country.trim());
  if (f.language) p.set("language", f.language);
  if (f.maxAge.trim()) p.set("max_age_days", f.maxAge.trim());

  const rawSalary = parseFloat(f.minSalary);
  if (!isNaN(rawSalary) && rawSalary > 0) {
    const annual = f.period === "month" ? rawSalary * 12 : rawSalary;
    if (annual >= 1) {
      p.set("min_salary", String(Math.round(annual)));
      if (f.currency) p.set("min_salary_currency", f.currency);
    }
  }
  if (f.requireSalary) p.set("require_salary", "true");
  if (f.maxGap.trim() !== "") p.set("max_experience_gap", f.maxGap.trim());

  // The quick "City" field and the advanced "Cities" pills both feed `cities`.
  const allCities = [...f.cities, f.city.trim()].map((c) => c.trim()).filter(Boolean);
  Array.from(new Set(allCities)).forEach((c) => p.append("cities", c));
  return p;
}

// Map preferences from the API into filter state (ported from loadPrefs()).
export function prefsToFilters(p: Preferences, base: FilterState): FilterState {
  return {
    ...base,
    yearsExp: p.years_experience != null ? String(p.years_experience) : "",
    tzOffset: p.user_utc_offset ?? CAIRO_OFFSET,
    knownLangs: p.known_languages ?? [],
    exclTitles: p.exclude_title_keywords ?? [],
    roleFamilies: p.include_role_families ?? [],
    hideSenior: (p.exclude_seniorities ?? []).includes("senior"),
    hideIntern: (p.exclude_seniorities ?? []).includes("intern"),
  };
}

// Map filter state back to the preferences PUT body (ported from persistPrefs()).
export function filtersToPrefs(f: FilterState): Preferences {
  const sen: string[] = [];
  if (f.hideSenior) sen.push("senior");
  if (f.hideIntern) sen.push("intern");
  return {
    years_experience: f.yearsExp.trim() === "" ? null : Number(f.yearsExp),
    user_utc_offset: f.tzOffset,
    known_languages: f.knownLangs,
    exclude_title_keywords: f.exclTitles,
    include_role_families: f.roleFamilies,
    exclude_seniorities: sen,
  };
}
