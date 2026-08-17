import type { Status } from "./types";

// Pipeline stages, in board order, each with a colour accent (ported 1:1).
export const STAGES: { key: Status; color: string }[] = [
  { key: "saved", color: "#9aa3b2" },
  { key: "applied", color: "#6ea8fe" },
  { key: "screening", color: "#a78bfa" },
  { key: "interview", color: "#fbbf24" },
  { key: "offer", color: "#4ade80" },
  { key: "rejected", color: "#f87171" },
  { key: "ghosted", color: "#6b7280" },
  { key: "withdrawn", color: "#6b7280" },
];

export const STATUSES = STAGES.map((s) => s.key);

export const EFFORT_LABELS: Record<string, string> = {
  cover_letter: "cover letter",
  coding_challenge: "coding challenge",
  portfolio: "portfolio",
};

// Continents for the region filter (point 4). Value is a stable slug the backend
// maps to countries; label is what the user sees.
export const REGIONS = [
  { value: "africa", label: "Africa" },
  { value: "asia", label: "Asia" },
  { value: "europe", label: "Europe" },
  { value: "latin_america", label: "Latin America" },
  { value: "north_america", label: "North America" },
  { value: "oceania", label: "Oceania" },
];

// Role families the backend classifier emits (point 4: "Role Categories").
export const ROLE_FAMILIES = [
  { value: "engineering", label: "Engineering" },
  { value: "data_ml", label: "Data & ML" },
  { value: "security", label: "Security" },
  { value: "product", label: "Product" },
  { value: "design", label: "Design" },
  { value: "sales", label: "Sales" },
  { value: "support", label: "Support" },
  { value: "marketing", label: "Marketing" },
  { value: "people", label: "People" },
  { value: "finance_ops", label: "Finance & Ops" },
  { value: "media_content", label: "Media & Content" },
];

export const CURRENCIES = [
  { value: "", label: "Any" },
  { value: "EUR", label: "EUR" },
  { value: "GBP", label: "GBP" },
  { value: "USD", label: "USD" },
];

// Full language names keyed by ISO 639-1 (points 8, 9, 10). The posting-language
// dropdown intersects these with what the corpus actually has.
export const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  de: "German",
  fr: "French",
  es: "Spanish",
  pt: "Portuguese",
  it: "Italian",
  nl: "Dutch",
  sv: "Swedish",
  da: "Danish",
  no: "Norwegian",
  fi: "Finnish",
  pl: "Polish",
  cs: "Czech",
  ro: "Romanian",
  hu: "Hungarian",
  el: "Greek",
  tr: "Turkish",
  ru: "Russian",
  uk: "Ukrainian",
  ar: "Arabic",
  he: "Hebrew",
  zh: "Chinese",
  ja: "Japanese",
  ko: "Korean",
  hi: "Hindi",
  bg: "Bulgarian",
  sk: "Slovak",
  sl: "Slovenian",
  hr: "Croatian",
  sr: "Serbian",
  et: "Estonian",
  lv: "Latvian",
  lt: "Lithuanian",
  ga: "Irish",
  is: "Icelandic",
};

export const languageName = (code: string): string =>
  LANGUAGE_NAMES[code.toLowerCase()] ?? code.toUpperCase();

// The full list of known languages the user can claim to speak (point 10).
export const KNOWN_LANGUAGE_OPTIONS = Object.entries(LANGUAGE_NAMES)
  .map(([value, label]) => ({ value, label }))
  .sort((a, b) => a.label.localeCompare(b.label));

// Timezone picker. Value is the UTC offset (int); the label is a readable city.
export const TIMEZONES: { offset: number; label: string }[] = [
  { offset: -8, label: "Los Angeles (PST)" },
  { offset: -7, label: "Denver (MST)" },
  { offset: -6, label: "Chicago (CST)" },
  { offset: -5, label: "New York (EST)" },
  { offset: -3, label: "Sao Paulo (BRT)" },
  { offset: 0, label: "London (GMT)" },
  { offset: 1, label: "Berlin / Paris (CET)" },
  { offset: 2, label: "Cairo (EET)" },
  { offset: 3, label: "Moscow (MSK)" },
  { offset: 4, label: "Dubai (GST)" },
  { offset: 5, label: "Karachi (PKT)" },
  { offset: 6, label: "Dhaka (BST)" },
  { offset: 8, label: "Singapore (SGT)" },
  { offset: 9, label: "Tokyo (JST)" },
  { offset: 10, label: "Sydney (AEST)" },
];

export const CAIRO_OFFSET = 2;

export const tzLabel = (off: number): string => {
  const city = TIMEZONES.find((t) => t.offset === off)?.label ?? "";
  const sign = off >= 0 ? "+" : "-";
  return `UTC${sign}${String(Math.abs(off)).padStart(2, "0")}:00 ${city}`.trim();
};

// CV upload limits (point 22). Surface these in the form copy too.
export const CV_MAX_BYTES = 5 * 1024 * 1024; // 5 MB
export const CV_ACCEPT = ".pdf,.txt,text/plain,application/pdf";
export const CV_LIMIT_HINT = "PDF or .txt, max 5 MB";
