import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
import { api } from "../../api";
import { Modal } from "../../components/Modal";
import { Select, type Option } from "../../components/Select";
import type { Cv, Job, ShortlistResponse, User, Verdict } from "../../types";
import { Filters, buildLanguageOptions, buildNameOptions } from "./Filters";
import { JobCard } from "./JobCard";
import { CvModal } from "./CvModal";
import { exportCsv, exportPdf, exportTxt } from "./exports";
import {
  buildParams,
  clearStoredFilters,
  defaultFilters,
  filtersToPrefs,
  loadStoredFilters,
  saveFilters,
  type FilterState,
} from "./filterState";

const RERANK_N = 10;

export function Shortlist({ user }: { user: User | null }) {
  const [filters, setFilters] = useState<FilterState>(loadStoredFilters);
  const [cvs, setCvs] = useState<Cv[]>([]);
  const [cvId, setCvId] = useState<string>("");
  const [langOptions, setLangOptions] = useState<Option[]>([]);
  const [cityOptions, setCityOptions] = useState<Option[]>([]);
  const [countryOptions, setCountryOptions] = useState<Option[]>([]);
  const [results, setResults] = useState<ShortlistResponse | null>(null);
  const [judged, setJudged] = useState<Record<number, Verdict>>({});
  const [status, setStatus] = useState("");
  const [statusErr, setStatusErr] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [reranking, setReranking] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const set = useCallback(
    <K extends keyof FilterState>(key: K, value: FilterState[K]) =>
      setFilters((prev) => ({ ...prev, [key]: value })),
    [],
  );

  const say = (msg: string, err = false) => {
    setStatus(msg);
    setStatusErr(err);
  };

  const loadCvs = useCallback(async () => {
    const list = await api.listCvs();
    setCvs(list);
    setCvId((cur) => (cur && list.some((c) => String(c.id) === cur) ? cur : list[0] ? String(list[0].id) : ""));
    return list;
  }, []);

  // Filters live in a ref so the debounced-free runShortlist always sees current state.
  const filtersRef = useRef(filters);
  filtersRef.current = filters;
  const cvIdRef = useRef(cvId);
  cvIdRef.current = cvId;

  const runShortlist = useCallback(async () => {
    const f = filtersRef.current;
    setSubmitting(true);
    setJudged({});
    say("Loading shortlist...");
    try {
      await api.putPrefs(filtersToPrefs(f)).catch(() => {});
      const params = buildParams(f, cvIdRef.current);
      history.replaceState(null, "", "/?" + params.toString());
      const data = await api.shortlist(params);
      setResults(data);
      if (!data.items.length) say(`0 results for CV #${data.cv_id}.`);
      else
        say(
          `${data.count} result${data.count === 1 ? "" : "s"} for CV #${data.cv_id}, ranked by fit x freshness. ` +
            `Bars show fit relative to the top match; "Assess fit" gives the AI judge's calibrated 0-100 score.`,
        );
    } catch (e) {
      say("Shortlist failed: " + (e as Error).message, true);
    } finally {
      setSubmitting(false);
    }
  }, []);

  // Persist the whole filter card locally so it survives reloads (point 8).
  useEffect(() => {
    saveFilters(filters);
  }, [filters]);

  // Initial load: CVs + filter option sources, then the first shortlist. Filters
  // themselves come from localStorage (no server-seeded defaults).
  useEffect(() => {
    (async () => {
      try {
        await loadCvs();
        api.languages().then((l) => setLangOptions(buildLanguageOptions(l))).catch(() => {});
        api.cities().then((c) => setCityOptions(buildNameOptions(c))).catch(() => {});
        api.countries().then((c) => setCountryOptions(buildNameOptions(c))).catch(() => {});
      } finally {
        runShortlist();
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onReset = useCallback(() => {
    clearStoredFilters();
    setFilters(defaultFilters);
    // Run against the cleared filters on the next tick (state is async).
    setTimeout(runShortlist, 0);
  }, [runShortlist]);

  const deleteSelectedCv = async () => {
    const target = cvs.find((c) => String(c.id) === cvId);
    if (!target) return;
    setConfirmDelete(false);
    try {
      await api.deleteCv(target.id);
      await loadCvs();
      say(`Deleted "${target.label}".`);
      runShortlist();
    } catch (e) {
      say("Could not delete CV: " + (e as Error).message, true);
    }
  };

  const onTrack = useCallback(
    async (jobId: number, statusVal: string) => {
      try {
        if (!statusVal) await api.untrack(jobId);
        else await api.track(jobId, statusVal);
      } catch (e) {
        say("Could not update status: " + (e as Error).message, true);
        return;
      }
      // Reflect on the shortlist in place (no refetch, no flash).
      setResults((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.map((j) =>
                j.id === jobId ? { ...j, application_status: statusVal || null } : j,
              ),
            }
          : prev,
      );
      window.dispatchEvent(new CustomEvent("apps-changed"));
    },
    [],
  );

  const rerank = async () => {
    if (!results?.items.length) return;
    const ids = results.items.slice(0, RERANK_N).map((j) => j.id);
    setReranking(true);
    say(`Asking the AI judge to score the top ${ids.length} (${ids.length} model calls, ~a few cents)...`);
    try {
      const verdicts = await api.rerank({ cv_id: Number(cvId) || null, job_ids: ids });
      const map: Record<number, Verdict> = {};
      verdicts.forEach((v) => (map[v.job_id] = v));
      setJudged(map);
      // Judged jobs first (by score desc); the rest keep their fit order.
      setResults((prev) =>
        prev
          ? {
              ...prev,
              items: [...prev.items].sort((a, b) => {
                const sa = map[a.id]?.overall_score;
                const sb = map[b.id]?.overall_score;
                if (sa != null && sb != null) return sb - sa;
                if (sa != null) return -1;
                if (sb != null) return 1;
                return 0;
              }),
            }
          : prev,
      );
      say(`Reranked the top ${verdicts.length} by the AI judge's 0-100 score.`);
    } catch (e) {
      say("Rerank failed: " + (e as Error).message, true);
    } finally {
      setReranking(false);
    }
  };

  const cvOptions: Option[] = cvs.length
    ? cvs.map((c) => ({ value: String(c.id), label: c.label + (c.embedded ? "" : " (no embedding)") }))
    : [{ value: "", label: "no CV found - upload one" }];
  const selectedCv = cvs.find((c) => String(c.id) === cvId) ?? null;

  const maxSim = useMemo(
    () => Math.max(...(results?.items.map((j) => j.similarity) ?? [0.0001]), 0.0001),
    [results],
  );

  const items: Job[] = results?.items ?? [];

  return (
    <section>
      {/* CV selector + edit + upload */}
      <div className="cvbar">
        <div className="field grow">
          <label>Matching against CV</label>
          <Select
            options={cvOptions}
            value={cvOptions.find((o) => o.value === cvId) ?? null}
            isSearchable={false}
            onChange={(o) => setCvId((o as Option)?.value ?? "")}
          />
        </div>
        <button
          className="icon-btn"
          title="Delete this CV"
          disabled={!selectedCv}
          onClick={() => setConfirmDelete(true)}
        >
          <Trash2 size={16} />
        </button>
        <button
          className="icon-btn"
          title="Edit this CV"
          disabled={!selectedCv}
          onClick={() => setEditOpen(true)}
        >
          <Pencil size={16} />
        </button>
        <button className="btn-ghost" onClick={() => setUploadOpen(true)}>
          Upload new CV
        </button>
      </div>

      <Filters
        f={filters}
        set={set}
        languageOptions={langOptions}
        cityOptions={cityOptions}
        countryOptions={countryOptions}
        onSubmit={runShortlist}
        onReset={onReset}
        submitting={submitting}
      />

      <div className={"status" + (statusErr ? " error" : "")}>{status}</div>

      {items.length > 0 && (
        <div className="results-bar">
          <button
            className="btn-primary"
            onClick={rerank}
            disabled={reranking}
            title="Batch-judge the top jobs with Claude and re-order by fit"
          >
            {reranking ? "Judging..." : "Rank top 10 with AI"}
          </button>
          <span className="hint">Export:</span>
          <button className="assess-btn" onClick={() => results && exportCsv(items, results.cv_id)}>
            CSV
          </button>
          <button className="assess-btn" onClick={() => results && exportTxt(items, results.cv_id)}>
            TXT
          </button>
          {items.length <= 50 && (
            <button
              className="assess-btn"
              title="Available for 50 results or fewer"
              onClick={() => results && exportPdf(items, results.cv_id, (m) => say(m, true))}
            >
              PDF
            </button>
          )}
          <div className="spacer" />
          <span className="results-count">
            {items.length} result{items.length === 1 ? "" : "s"}
          </span>
        </div>
      )}

      {results && items.length === 0 && <div className="empty">No matches for these filters.</div>}

      <div>
        {items.map((job, i) => (
          <JobCard
            key={job.id}
            job={job}
            rank={i + 1}
            relWidth={Math.max(3, Math.round((job.similarity / maxSim) * 100))}
            cvId={cvId}
            judged={judged[job.id]}
            onTrack={onTrack}
          />
        ))}
      </div>

      <CvModal
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        mode="upload"
        user={user}
        existingCount={cvs.length}
        onSaved={async (cv) => {
          await loadCvs();
          setCvId(String(cv.id));
          say(`Uploaded "${cv.label}" (CV #${cv.id}). Ranking...`);
          runShortlist();
        }}
      />
      <CvModal
        open={editOpen}
        onOpenChange={setEditOpen}
        mode="edit"
        cv={selectedCv}
        user={user}
        existingCount={cvs.length}
        onSaved={async () => {
          await loadCvs();
          say("CV updated.");
        }}
      />

      <Modal
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        maxWidth={380}
        title={<h2>Delete CV?</h2>}
      >
        <p className="modal-text">
          {selectedCv ? (
            <>
              &ldquo;{selectedCv.label}&rdquo; will be permanently removed. This can&rsquo;t be
              undone.
            </>
          ) : null}
        </p>
        <div className="modal-actions">
          <button className="btn-ghost" onClick={() => setConfirmDelete(false)}>
            Cancel
          </button>
          <button className="btn-primary" onClick={deleteSelectedCv}>
            Delete
          </button>
        </div>
      </Modal>
    </section>
  );
}
