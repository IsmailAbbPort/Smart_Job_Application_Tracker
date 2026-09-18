import type { Status } from "./types";

// Pipeline stages, in board order. Colours are theme tokens (see theme.css --st-*).
export const STAGES: { key: Status; label: string; color: string }[] = [
  { key: "saved", label: "Saved", color: "var(--st-saved)" },
  { key: "applied", label: "Applied", color: "var(--st-applied)" },
  { key: "screening", label: "Screening", color: "var(--st-screening)" },
  { key: "interview", label: "Interview", color: "var(--st-interview)" },
  { key: "offer", label: "Offer", color: "var(--st-offer)" },
  { key: "rejected", label: "Rejected", color: "var(--st-rejected)" },
  { key: "ghosted", label: "Ghosted", color: "var(--st-ghosted)" },
  { key: "withdrawn", label: "Withdrawn", color: "var(--st-withdrawn)" },
];

export const stageOf = (key?: string | null) => STAGES.find((s) => s.key === key);

export const STATUSES = STAGES.map((s) => s.key);

export const EFFORT_LABELS: Record<string, string> = {
  cover_letter: "Cover letter",
  coding_challenge: "Coding challenge",
  portfolio: "Portfolio",
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
  { value: "legal", label: "Legal" },
  { value: "industrial_eng", label: "Industrial & Hardware" },
  { value: "hospitality_retail", label: "Hospitality, Retail & Logistics" },
  { value: "consulting_research", label: "Consulting & Research" },
  { value: "other", label: "Other" },
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
  az: "Azerbaijani",
  bs: "Bosnian",
  ca: "Catalan",
  gl: "Galician",
  eu: "Basque",
  sq: "Albanian",
  mk: "Macedonian",
  mt: "Maltese",
  cy: "Welsh",
  la: "Latin",
  id: "Indonesian",
  ms: "Malay",
  vi: "Vietnamese",
  th: "Thai",
  fa: "Persian",
  ur: "Urdu",
  bn: "Bengali",
  ta: "Tamil",
  af: "Afrikaans",
  sw: "Swahili",
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
