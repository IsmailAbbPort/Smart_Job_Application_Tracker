// Shapes mirrored from the FastAPI schemas. Kept intentionally close to the
// JSON the endpoints return so the port stays a faithful 1:1 of the old UI.

export interface Cv {
  id: number;
  label: string;
  embedded: boolean;
  created_at: string;
  filename?: string | null;
  size_bytes?: number | null;
  content_type?: string | null;
  suggested_role_families?: string[];
}

export interface Job {
  id: number;
  title: string;
  company: string;
  url: string;
  source: string;
  similarity: number;
  city?: string | null;
  country?: string | null;
  location?: string | null;
  is_remote?: boolean;
  is_european?: boolean;
  language?: string | null;
  required_languages?: string[];
  visa_sponsorship?: boolean | null;
  remote_region?: string | null;
  timezone_overlap_hours?: number | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  effort_signals?: string[];
  experience_gap?: number | null;
  min_years_experience?: number | null;
  seniority?: string | null;
  role_family?: string | null;
  posted_at?: string | null;
  source_gone_at?: string | null;
  application_status?: string | null;
}

export interface ShortlistResponse {
  cv_id: number;
  count: number;
  items: Job[];
}

export interface RequirementCheck {
  requirement: string;
  importance: "must_have" | "nice_to_have";
  cv_evidence: string;
  status: "met" | "partial" | "absent";
}

export interface Verdict {
  job_id: number;
  overall_score: number;
  verdict: "strong" | "medium" | "weak";
  one_line_verdict: string;
  dealbreakers: string[];
  requirements: RequirementCheck[];
  matched_requirements: { requirement: string; cv_evidence: string }[];
  gaps: string[];
}

export interface LetterClaim {
  claim: string;
  supported: boolean;
}

export interface Letter {
  job_id: number;
  body: string;
  edited: boolean;
  fabrication: {
    claims?: LetterClaim[];
    placeholders?: string[];
    unsupported_count?: number;
    grounded_ratio?: number;
  };
}

export interface Application {
  status: string;
  applied_at?: string | null;
  job: Job;
}

export interface Stats {
  total: number;
  by_status: Record<string, number>;
}

export interface Preferences {
  years_experience?: number | null;
  user_utc_offset?: number | null;
  known_languages?: string[];
  work_rights?: string[];
  exclude_title_keywords?: string[];
  include_role_families?: string[];
  exclude_seniorities?: string[];
}

export interface SavedView {
  id: number;
  name: string;
  filters: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ManualApplicationInput {
  title: string;
  company: string;
  url: string;
  location: string | null;
  description: string;
  is_remote: boolean;
  status: Status;
}

export interface User {
  id: number;
  name: string;
  email: string;
}

export type Status =
  | "saved"
  | "applied"
  | "screening"
  | "interview"
  | "offer"
  | "rejected"
  | "ghosted"
  | "withdrawn";
