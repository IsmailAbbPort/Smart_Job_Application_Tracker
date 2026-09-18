import type {
  Application,
  Cv,
  Letter,
  ManualApplicationInput,
  Preferences,
  SavedView,
  ShortlistResponse,
  Stats,
  User,
  Verdict,
} from "./types";
import { mockApi } from "./mock";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

// Thin fetch wrapper. Surfaces the FastAPI `detail` string on error so the UI can
// show the same friendly messages the old vanilla app did. Cookies (the auth
// session) ride along via credentials: "include".
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const body = (v: unknown) => JSON.stringify(v);

// Cached-result lookups (stored verdict / letter) answer 404 until one exists.
async function orNull<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

const cvQuery = (cvId?: string, refresh?: boolean) => {
  const q = new URLSearchParams();
  if (cvId) q.set("cv_id", cvId);
  if (refresh) q.set("refresh", "true");
  const s = q.toString();
  return s ? "?" + s : "";
};

const realApi = {
  // ---- CVs ----
  listCvs: () => req<Cv[]>("/cv"),
  uploadCv: (payload: { label: string; filename: string; content_base64: string }) =>
    req<Cv>("/cv/upload", { method: "POST", body: body(payload) }),
  updateCv: (id: number, payload: { label: string }) =>
    req<Cv>(`/cv/${id}`, { method: "PATCH", body: body(payload) }),
  deleteCv: (id: number) => req<unknown>(`/cv/${id}`, { method: "DELETE" }),
  replaceCvFile: (id: number, payload: { filename: string; content_base64: string }) =>
    req<Cv>(`/cv/${id}/file`, { method: "PUT", body: body(payload) }),
  cvFileUrl: (id: number) => `/cv/${id}/file`,

  // ---- Jobs / filter option sources ----
  languages: () => req<{ code: string; count: number }[]>("/jobs/languages"),
  cities: () => req<{ name: string; count: number }[]>("/jobs/cities"),
  countries: () => req<{ name: string; count: number }[]>("/jobs/countries"),
  jobDescription: (id: number) => req<{ description: string }>(`/jobs/${id}`),
  existingJobs: (ids: number[]) =>
    req<{ ids: number[] }>(
      "/jobs/existing?" + new URLSearchParams(ids.map((id) => ["ids", String(id)])).toString(),
    ),

  // ---- Preferences ----
  getPrefs: () => req<Preferences>("/preferences"),
  putPrefs: (p: Preferences) => req<Preferences>("/preferences", { method: "PUT", body: body(p) }),

  // ---- Matching ----
  shortlist: (params: URLSearchParams) =>
    req<ShortlistResponse>("/match/shortlist?" + params.toString()),
  judge: (jobId: number, cvId?: string, refresh?: boolean) =>
    req<Verdict>(`/match/${jobId}${cvQuery(cvId, refresh)}`, { method: "POST" }),
  getVerdict: (jobId: number, cvId?: string) =>
    orNull(req<Verdict>(`/match/${jobId}${cvQuery(cvId)}`)),
  rerank: (payload: { cv_id: number | null; job_ids: number[] }) =>
    req<Verdict[]>("/match/rerank", { method: "POST", body: body(payload) }),

  // ---- Letters ----
  draftLetter: (jobId: number, cvId?: string, refresh?: boolean) =>
    req<Letter>(`/letters/${jobId}${cvQuery(cvId, refresh)}`, { method: "POST" }),
  getLetter: (jobId: number, cvId?: string) =>
    orNull(req<Letter>(`/letters/${jobId}${cvQuery(cvId)}`)),
  saveLetter: (jobId: number, letterBody: string, cvId?: string) =>
    req<Letter>(`/letters/${jobId}${cvQuery(cvId)}`, {
      method: "PUT",
      body: body({ body: letterBody }),
    }),

  // ---- Applications ----
  applications: () => req<Application[]>("/applications"),
  stats: () => req<Stats>("/applications/stats"),
  track: (jobId: number, status: string) =>
    req<unknown>("/applications", { method: "POST", body: body({ job_id: jobId, status }) }),
  untrack: (jobId: number) => req<unknown>(`/applications/${jobId}`, { method: "DELETE" }),
  addManualApplication: (payload: ManualApplicationInput) =>
    req<Application>("/applications/manual", { method: "POST", body: body(payload) }),

  // ---- Saved views (filter presets) ----
  listViews: () => req<SavedView[]>("/views"),
  createView: (payload: { name: string; filters: Record<string, unknown> }) =>
    req<SavedView>("/views", { method: "POST", body: body(payload) }),
  renameView: (id: number, name: string) =>
    req<SavedView>(`/views/${id}`, { method: "PATCH", body: body({ name }) }),
  deleteView: (id: number) => req<unknown>(`/views/${id}`, { method: "DELETE" }),

  // ---- Auth ----
  me: () => req<User | null>("/auth/me"),
  register: (payload: { name: string; email: string; password: string }) =>
    req<User>("/auth/register", { method: "POST", body: body(payload) }),
  login: (payload: { email: string; password: string }) =>
    req<User>("/auth/login", { method: "POST", body: body(payload) }),
  logout: () => req<unknown>("/auth/logout", { method: "POST" }),
};

export type Api = typeof realApi;

// Built with VITE_MOCK=1 -> serve the static-demo fixtures (mock.ts); otherwise
// talk to the real FastAPI backend. The env value is inlined at build time, so a
// normal build drops the mock module entirely.
export const api: Api = import.meta.env.VITE_MOCK === "1" ? mockApi : realApi;
