// Static-demo backend. When the app is built with VITE_MOCK=1 (see api.ts), every
// `api.*` call is served from these in-memory fixtures instead of fetch(), so the
// UI can be hosted on a plain static host with no server. Kept side-effect free at
// module top level (only literals + lazy state) so a normal build tree-shakes it out.

import type { Api } from "./api";
import type {
  Application,
  Cv,
  Letter,
  Preferences,
  SavedView,
  ShortlistResponse,
  Stats,
  User,
  Verdict,
} from "./types";

const DEMO_USER: User = { id: 1, name: "Demo User", email: "demo@example.com" };

const CVS: Cv[] = [
  {
    id: 1,
    label: "AI/ML Engineer CV",
    embedded: true,
    created_at: "2026-08-15",
    filename: "ismail-ai-ml.pdf",
    size_bytes: 148_000,
    content_type: "application/pdf",
  },
  {
    id: 2,
    label: "Full-Stack (MERN) CV",
    embedded: true,
    created_at: "2026-07-30",
    filename: "ismail-fullstack.pdf",
    size_bytes: 132_000,
    content_type: "application/pdf",
  },
];

// A hand-picked corpus that exercises every badge/branch in the UI.
const JOBS = [
  {
    id: 101,
    title: "Senior Machine Learning Engineer",
    company: "Nordwind AI",
    url: "https://example.com/jobs/101",
    source: "greenhouse",
    similarity: 0.61,
    city: "Remote",
    country: "Germany",
    is_remote: true,
    is_european: true,
    language: "en",
    visa_sponsorship: true,
    timezone_overlap_hours: 5,
    salary_min: 85_000,
    salary_max: 110_000,
    salary_currency: "EUR",
    min_years_experience: 4,
    seniority: "senior",
    role_family: "data_ml",
    posted_at: "2026-09-08",
    effort_signals: ["cover_letter"],
  },
  {
    id: 102,
    title: "AI Engineer (LLM Applications)",
    company: "Helvetia Labs",
    url: "https://example.com/jobs/102",
    source: "lever",
    similarity: 0.58,
    city: "Berlin",
    country: "Germany",
    is_remote: false,
    is_european: true,
    language: "en",
    visa_sponsorship: true,
    timezone_overlap_hours: 6,
    salary_min: 75_000,
    salary_max: 95_000,
    salary_currency: "EUR",
    min_years_experience: 3,
    seniority: "mid",
    role_family: "engineering",
    posted_at: "2026-09-05",
  },
  {
    id: 103,
    title: "Full-Stack Engineer (React / Node)",
    company: "Tulip Systems",
    url: "https://example.com/jobs/103",
    source: "greenhouse",
    similarity: 0.55,
    city: "Amsterdam",
    country: "Netherlands",
    is_remote: true,
    is_european: true,
    language: "en",
    visa_sponsorship: true,
    timezone_overlap_hours: 6,
    salary_min: 70_000,
    salary_max: 88_000,
    salary_currency: "EUR",
    min_years_experience: 3,
    seniority: "mid",
    role_family: "engineering",
    posted_at: "2026-09-03",
  },
  {
    id: 104,
    title: "Backend Engineer, Python",
    company: "Cascais Cloud",
    url: "https://example.com/jobs/104",
    source: "workable",
    similarity: 0.52,
    city: "Lisbon",
    country: "Portugal",
    is_remote: true,
    is_european: true,
    language: "en",
    timezone_overlap_hours: 7,
    salary_min: 55_000,
    salary_max: 70_000,
    salary_currency: "EUR",
    min_years_experience: 2,
    seniority: "mid",
    role_family: "engineering",
    posted_at: "2026-08-29",
  },
  {
    id: 105,
    title: "Data Engineer",
    company: "Liffey Data",
    url: "https://example.com/jobs/105",
    source: "lever",
    similarity: 0.49,
    city: "Dublin",
    country: "Ireland",
    is_remote: false,
    is_european: true,
    language: "en",
    visa_sponsorship: false,
    timezone_overlap_hours: 5,
    min_years_experience: 4,
    experience_gap: 1,
    seniority: "senior",
    role_family: "data_ml",
    posted_at: "2026-08-26",
  },
  {
    id: 106,
    title: "Founding Engineer",
    company: "Thames Ventures",
    url: "https://example.com/jobs/106",
    source: "yc",
    similarity: 0.46,
    city: "London",
    country: "United Kingdom",
    is_remote: false,
    is_european: true,
    language: "en",
    visa_sponsorship: false,
    timezone_overlap_hours: 4,
    salary_min: 90_000,
    salary_max: 120_000,
    salary_currency: "GBP",
    min_years_experience: 5,
    experience_gap: 2,
    seniority: "senior",
    role_family: "engineering",
    posted_at: "2026-08-22",
    effort_signals: ["coding_challenge", "portfolio"],
  },
  {
    id: 107,
    title: "NLP Engineer",
    company: "Seine Intelligence",
    url: "https://example.com/jobs/107",
    source: "greenhouse",
    similarity: 0.43,
    city: "Paris",
    country: "France",
    is_remote: false,
    is_european: true,
    language: "fr",
    required_languages: ["French"],
    timezone_overlap_hours: 6,
    salary_min: 60_000,
    salary_max: 78_000,
    salary_currency: "EUR",
    min_years_experience: 3,
    seniority: "mid",
    role_family: "data_ml",
    posted_at: "2026-08-19",
  },
  {
    id: 108,
    title: "Platform Engineer (Remote)",
    company: "Andes Compute",
    url: "https://example.com/jobs/108",
    source: "workable",
    similarity: 0.4,
    country: "Argentina",
    is_remote: true,
    is_european: false,
    language: "en",
    remote_region: "latam",
    timezone_overlap_hours: 2,
    min_years_experience: 3,
    seniority: "mid",
    role_family: "engineering",
    posted_at: "2026-08-14",
  },
] satisfies Array<ShortlistResponse["items"][number]>;

const jobById = (id: number) => JOBS.find((j) => j.id === id);

// Lazy so module top level stays inert (tree-shakeable). Seeded with a few tracked
// applications spread across pipeline stages.
let _tracked: Map<number, { status: string; applied_at: string | null }> | null = null;
const tracked = () =>
  (_tracked ??= new Map([
    [102, { status: "applied", applied_at: "2026-09-06" }],
    [101, { status: "interview", applied_at: "2026-08-28" }],
    [104, { status: "saved", applied_at: null }],
    [106, { status: "rejected", applied_at: "2026-08-24" }],
  ]));

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function verdictFor(id: number): Verdict {
  const job = jobById(id);
  const sim = job?.similarity ?? 0.4;
  const overall = Math.min(96, Math.round(sim * 90) + 35);
  const tier: Verdict["verdict"] = overall >= 80 ? "strong" : overall >= 65 ? "medium" : "weak";
  return {
    job_id: id,
    overall_score: overall,
    verdict: tier,
    one_line_verdict:
      tier === "strong"
        ? "Strong overlap on core ML/engineering skills; apply."
        : tier === "medium"
          ? "Solid fit with a couple of gaps worth addressing in the letter."
          : "Reachable stretch; lead with transferable strengths.",
    dealbreakers: tier === "weak" && !job?.is_remote ? ["On-site, and you want remote only"] : [],
    requirements: [
      {
        requirement: "Python + ML tooling",
        importance: "must_have",
        cv_evidence: "Built and shipped LLM-backed features end to end.",
        status: "met",
      },
      {
        requirement: "Production web services",
        importance: "must_have",
        cv_evidence: "MERN stack in two full-time roles.",
        status: "met",
      },
      {
        requirement: "MLOps / production-scale training",
        importance: tier === "strong" ? "nice_to_have" : "must_have",
        cv_evidence: "",
        status: "absent",
      },
    ],
    matched_requirements: [
      {
        requirement: "Python + ML tooling",
        cv_evidence: "Built and shipped LLM-backed features end to end.",
      },
      { requirement: "Production web services", cv_evidence: "MERN stack in two full-time roles." },
    ],
    gaps:
      typeof job?.experience_gap === "number" && job.experience_gap > 0
        ? [
            `Posting wants ~${job.min_years_experience ?? 0}y; you're about ${job.experience_gap}y under.`,
          ]
        : ["No formal MLOps/production-scale training experience listed."],
  };
}

function letterFor(id: number, edited = false): Letter {
  const job = jobById(id);
  const company = job?.company ?? "the company";
  const title = job?.title ?? "the role";
  return {
    job_id: id,
    edited,
    body:
      `Dear ${company} hiring team,\n\n` +
      `I'm applying for the ${title} role. Over two full-time engineering roles I've shipped ` +
      `LLM-backed product features end to end, from data pipelines to a React front end, and I'm ` +
      `now focused on AI engineering.\n\n` +
      `I'd welcome the chance to talk. I'm available to start after [your notice period].\n\n` +
      `Best regards,\nIsmail`,
    fabrication: {
      claims: [
        { claim: "Shipped LLM-backed product features end to end.", supported: true },
        { claim: "Led a team of ten engineers.", supported: false },
      ],
      placeholders: ["your notice period"],
      unsupported_count: 1,
      grounded_ratio: 0.85,
    },
  };
}

export const mockApi: Api = {
  // ---- CVs ----
  listCvs: async () => CVS,
  uploadCv: async (payload) => ({
    id: 3,
    label: payload.label,
    embedded: true,
    created_at: "2026-09-14",
    filename: payload.filename,
    size_bytes: 120_000,
    content_type: "application/pdf",
  }),
  updateCv: async (id, payload) => ({
    ...(CVS.find((c) => c.id === id) ?? CVS[0]),
    id,
    label: payload.label,
  }),
  deleteCv: async (_id) => ({}),
  replaceCvFile: async (id, payload) => ({
    ...(CVS.find((c) => c.id === id) ?? CVS[0]),
    id,
    filename: payload.filename,
  }),
  cvFileUrl: (_id) => "#",

  // ---- Jobs / filter option sources ----
  languages: async () => [
    { code: "en", count: 132 },
    { code: "de", count: 41 },
    { code: "fr", count: 23 },
    { code: "nl", count: 12 },
    { code: "pt", count: 9 },
  ],
  cities: async () => [
    { name: "Berlin", count: 22 },
    { name: "Amsterdam", count: 17 },
    { name: "London", count: 15 },
    { name: "Lisbon", count: 11 },
    { name: "Dublin", count: 9 },
    { name: "Paris", count: 8 },
  ],
  countries: async () => [
    { name: "Germany", count: 58 },
    { name: "Netherlands", count: 31 },
    { name: "United Kingdom", count: 27 },
    { name: "Portugal", count: 19 },
    { name: "Ireland", count: 14 },
    { name: "France", count: 12 },
  ],
  jobDescription: async () => ({
    description: "Demo mode does not include full job descriptions.",
  }),
  existingJobs: async (ids) => ({ ids }),

  // ---- Preferences ----
  getPrefs: async (): Promise<Preferences> => ({
    years_experience: 3,
    user_utc_offset: 2,
    known_languages: ["en", "ar", "uk"],
  }),
  putPrefs: async (p) => p,

  // ---- Matching ----
  shortlist: async (params): Promise<ShortlistResponse> => {
    await wait(250);
    const cv_id = Number(params.get("cv_id")) || 1;
    const items = JOBS.map((j) => ({
      ...j,
      application_status: tracked().get(j.id)?.status ?? null,
    }));
    return { cv_id, count: items.length, items };
  },
  judge: async (jobId, _cvId, _refresh) => {
    await wait(500);
    return verdictFor(jobId);
  },
  getVerdict: async (_jobId, _cvId) => null,
  rerank: async (payload) => {
    await wait(700);
    return payload.job_ids.map(verdictFor);
  },

  // ---- Letters ----
  draftLetter: async (jobId, _cvId, _refresh) => {
    await wait(600);
    return letterFor(jobId);
  },
  getLetter: async (_jobId, _cvId) => null,
  saveLetter: async (jobId, _body, _cvId) => letterFor(jobId, true),

  // ---- Applications ----
  applications: async (): Promise<Application[]> => {
    const out: Application[] = [];
    for (const [id, t] of tracked().entries()) {
      const job = jobById(id);
      if (job) out.push({ status: t.status, applied_at: t.applied_at, job });
    }
    return out;
  },
  stats: async (): Promise<Stats> => {
    const by_status: Record<string, number> = {};
    for (const t of tracked().values()) by_status[t.status] = (by_status[t.status] ?? 0) + 1;
    return { total: tracked().size, by_status };
  },
  track: async (jobId, status) => {
    const prev = tracked().get(jobId);
    tracked().set(jobId, { status, applied_at: prev?.applied_at ?? null });
    return {};
  },
  untrack: async (jobId) => {
    tracked().delete(jobId);
    return {};
  },
  addManualApplication: async (payload) => ({
    status: payload.status,
    applied_at: null,
    job: {
      id: 900,
      title: payload.title,
      company: payload.company,
      url: payload.url,
      source: "manual",
      similarity: 0,
      location: payload.location,
      is_remote: payload.is_remote,
    },
  }),

  // ---- Saved views ----
  listViews: async (): Promise<SavedView[]> => [],
  createView: async (payload) => ({
    id: 1,
    name: payload.name,
    filters: payload.filters,
    created_at: "2026-09-14",
    updated_at: "2026-09-14",
  }),
  renameView: async (id, name) => ({
    id,
    name,
    filters: {},
    created_at: "2026-09-14",
    updated_at: "2026-09-14",
  }),
  deleteView: async (_id) => ({}),

  // ---- Auth ----
  me: async () => DEMO_USER,
  register: async (payload) => ({ id: 1, name: payload.name, email: payload.email }),
  login: async (payload) => ({ id: 1, name: DEMO_USER.name, email: payload.email }),
  logout: async () => ({}),
};
