import type {
  Application,
  Cv,
  Letter,
  Preferences,
  ShortlistResponse,
  Stats,
  User,
  Verdict,
} from "./types";

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
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const body = (v: unknown) => JSON.stringify(v);

export const api = {
  // ---- CVs ----
  listCvs: () => req<Cv[]>("/cv"),
  uploadCv: (payload: { label: string; filename: string; content_base64: string }) =>
    req<Cv>("/cv/upload", { method: "POST", body: body(payload) }),
  updateCv: (id: number, payload: { label: string }) =>
    req<Cv>(`/cv/${id}`, { method: "PATCH", body: body(payload) }),
  deleteCv: (id: number) => req<unknown>(`/cv/${id}`, { method: "DELETE" }),
  cvFileUrl: (id: number) => `/cv/${id}/file`,

  // ---- Jobs / filter option sources ----
  languages: () => req<{ code: string; count: number }[]>("/jobs/languages"),
  cities: () => req<{ name: string; count: number }[]>("/jobs/cities"),
  countries: () => req<{ name: string; count: number }[]>("/jobs/countries"),

  // ---- Preferences ----
  getPrefs: () => req<Preferences>("/preferences"),
  putPrefs: (p: Preferences) => req<Preferences>("/preferences", { method: "PUT", body: body(p) }),

  // ---- Matching ----
  shortlist: (params: URLSearchParams) =>
    req<ShortlistResponse>("/match/shortlist?" + params.toString()),
  judge: (jobId: number, cvId?: string) =>
    req<Verdict>(`/match/${jobId}${cvId ? `?cv_id=${cvId}` : ""}`, { method: "POST" }),
  rerank: (payload: { cv_id: number | null; job_ids: number[] }) =>
    req<Verdict[]>("/match/rerank", { method: "POST", body: body(payload) }),

  // ---- Letters ----
  draftLetter: (jobId: number, cvId?: string) =>
    req<Letter>(`/letters/${jobId}${cvId ? `?cv_id=${cvId}` : ""}`, { method: "POST" }),
  saveLetter: (jobId: number, letterBody: string, cvId?: string) =>
    req<Letter>(`/letters/${jobId}${cvId ? `?cv_id=${cvId}` : ""}`, {
      method: "PUT",
      body: body({ body: letterBody }),
    }),

  // ---- Applications ----
  applications: () => req<Application[]>("/applications"),
  stats: () => req<Stats>("/applications/stats"),
  track: (jobId: number, status: string) =>
    req<unknown>("/applications", { method: "POST", body: body({ job_id: jobId, status }) }),
  untrack: (jobId: number) => req<unknown>(`/applications/${jobId}`, { method: "DELETE" }),

  // ---- Auth ----
  me: () => req<User | null>("/auth/me"),
  register: (payload: { name: string; email: string; password: string }) =>
    req<User>("/auth/register", { method: "POST", body: body(payload) }),
  login: (payload: { email: string; password: string }) =>
    req<User>("/auth/login", { method: "POST", body: body(payload) }),
  logout: () => req<unknown>("/auth/logout", { method: "POST" }),
};
