import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronsUpDown,
  Download,
  ListFilter,
  Loader2,
  Search,
  Sparkles,
  Upload,
} from "lucide-react";
import { api } from "../../api";
import { Dropdown } from "../../components/Dropdown";
import type { Option } from "../../components/Select";
import { REGIONS, ROLE_FAMILIES, languageName, tzLabel } from "../../constants";
import { effortText, fmtAgo, fmtAgoLong, isStale } from "../../format";
import { useBackToClose, useIsMobile } from "../../hooks";
import type { Cv, Job, SavedView, ShortlistResponse, Verdict } from "../../types";
import { JobInspector, StatusDot } from "../inspector/JobInspector";
import { FiltersModal, buildLanguageOptions, buildNameOptions } from "./FiltersModal";
import { exportCsv, exportPdf, exportTxt } from "./exports";
import { advancedCount, buildParams, filtersToPrefs, type FilterState } from "./filterState";

const RERANK_N = 10;

const label = (opts: Option[], v: string) => opts.find((o) => o.value === v)?.label ?? v;
const list = (vs: string[], max = 2) =>
  vs.length > max ? `${vs.slice(0, max).join(", ")} +${vs.length - max}` : vs.join(", ");

// Active filters as compact "key: value" chips for the toolbar.
function filterChips(f: FilterState): [string, string][] {
  const chips: [string, string][] = [];
  if (f.remote) chips.push(["Remote", f.remote === "true" ? "Remote only" : "Not remote"]);
  if (f.yearsExp.trim()) chips.push(["Experience", `${f.yearsExp} yrs`]);
  if (f.region) chips.push(["Region", label(REGIONS, f.region)]);
  if (f.country.trim()) chips.push(["Country", f.country]);
  if (f.cities.length) chips.push(["Cities", list(f.cities)]);
  if (f.language) chips.push(["Posting language", languageName(f.language)]);
  if (f.knownLangs.length) chips.push(["Languages", list(f.knownLangs.map(languageName))]);
  if (f.tzOffset != null) chips.push(["Time zone", tzLabel(f.tzOffset).split(" ")[0]]);
  if (f.minSalary.trim())
    chips.push([
      "Min salary",
      `${f.minSalary}${f.currency ? " " + f.currency : ""}${f.period === "month" ? "/mo" : ""}`,
    ]);
  if (f.requireSalary) chips.push(["Salary", "Listed only"]);
  if (f.maxGap.trim()) chips.push(["Max years short", f.maxGap]);
  if (f.maxAge.trim()) chips.push(["Posted within", `${f.maxAge} days`]);
  if (f.roleFamilies.length)
    chips.push(["Roles", list(f.roleFamilies.map((r) => label(ROLE_FAMILIES, r)))]);
  if (f.exclTitles.length) chips.push(["Excluding", list(f.exclTitles)]);
  if (f.hideSenior) chips.push(["Hide", "Senior"]);
  if (f.hideIntern) chips.push(["Hide", "Intern"]);
  return chips;
}

export function Shortlist({
  cvId,
  ready,
  filters,
  onFiltersChange,
  runToken,
  onCount,
  onSaveView,
  cvs,
  onSelectCv,
  onUploadCv,
  views,
  activeViewId,
  onApplyView,
}: {
  cvId: string;
  ready: boolean;
  filters: FilterState;
  onFiltersChange: (f: FilterState) => void;
  runToken: number;
  onCount: (n: number | null) => void;
  onSaveView: (name: string, f: FilterState) => Promise<void>;
  // The phone layout has no sidebar, so the CV switcher and saved views live here.
  cvs: Cv[];
  onSelectCv: (id: string) => void;
  onUploadCv: () => void;
  views: SavedView[];
  activeViewId: number | null;
  onApplyView: (v: SavedView) => void;
}) {
  const mobile = useIsMobile();
  const [langOptions, setLangOptions] = useState<Option[]>([]);
  const [cityOptions, setCityOptions] = useState<Option[]>([]);
  const [countryOptions, setCountryOptions] = useState<Option[]>([]);
  const [results, setResults] = useState<ShortlistResponse | null>(null);
  const [judged, setJudged] = useState<Record<number, Verdict>>({});
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [reranking, setReranking] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [query, setQuery] = useState("");

  const say = (text: string, error = false) => setMessage({ text, error });

  const filtersRef = useRef(filters);
  filtersRef.current = filters;
  const cvIdRef = useRef(cvId);
  cvIdRef.current = cvId;

  const runShortlist = useCallback(async () => {
    const f = filtersRef.current;
    setLoading(true);
    setJudged({});
    setMessage(null);
    try {
      await api.putPrefs(filtersToPrefs(f)).catch(() => {});
      const data = await api.shortlist(buildParams(f, cvIdRef.current));
      setResults(data);
      onCount(data.count);
      setSelectedId((cur) =>
        data.items.some((j) => j.id === cur) ? cur : (data.items[0]?.id ?? null),
      );
    } catch (e) {
      say("Shortlist failed: " + (e as Error).message, true);
    } finally {
      setLoading(false);
    }
  }, [onCount]);

  useEffect(() => {
    api
      .languages()
      .then((l) => setLangOptions(buildLanguageOptions(l)))
      .catch(() => {});
    api
      .cities()
      .then((c) => setCityOptions(buildNameOptions(c)))
      .catch(() => {});
    api
      .countries()
      .then((c) => setCountryOptions(buildNameOptions(c)))
      .catch(() => {});
  }, []);

  // Re-rank whenever the CV changes or the parent asks (filters applied, view picked).
  useEffect(() => {
    if (ready) runShortlist();
  }, [ready, cvId, runToken, runShortlist]);

  const onStatus = useCallback(async (jobId: number, statusVal: string) => {
    try {
      if (!statusVal) await api.untrack(jobId);
      else await api.track(jobId, statusVal);
    } catch (e) {
      say("Could not update status: " + (e as Error).message, true);
      return;
    }
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
  }, []);

  const rerank = async () => {
    if (!results?.items.length) return;
    const ids = results.items.slice(0, RERANK_N).map((j) => j.id);
    setReranking(true);
    say(`Asking the AI judge to score the top ${ids.length} (${ids.length} model calls)...`);
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

  const items: Job[] = results?.items ?? [];
  const maxSim = useMemo(() => Math.max(...items.map((j) => j.similarity), 0.0001), [items]);
  const selected = items.find((j) => j.id === selectedId) ?? null;
  const chips = filterChips(filters);
  const activeCount = advancedCount(filters) + (filters.remote ? 1 : 0);

  // Keyboard: J/K or arrows move the selection through the table.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, [role=dialog], .rs-container") || !items.length) return;
      const i = items.findIndex((j) => j.id === selectedId);
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedId(items[Math.min(items.length - 1, i + 1)].id);
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedId(items[Math.max(0, i - 1)].id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, selectedId]);

  useEffect(() => {
    if (selectedId != null)
      document.querySelector(`tr[data-row="${selectedId}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  useBackToClose(mobile && openId != null, () => setOpenId(null));

  const exportMenu = (close: () => void) => (
    <>
      <button
        onClick={() => {
          if (results) exportCsv(items, results.cv_id);
          close();
        }}
      >
        CSV spreadsheet
      </button>
      <button
        onClick={() => {
          if (results) exportTxt(items, results.cv_id);
          close();
        }}
      >
        Plain text
      </button>
      <button
        disabled={items.length > 50}
        title={items.length > 50 ? "Available for 50 results or fewer" : undefined}
        onClick={() => {
          if (results) exportPdf(items, results.cv_id, (m) => say(m, true));
          close();
        }}
      >
        PDF
      </button>
    </>
  );

  const filtersModal = (
    <FiltersModal
      open={filtersOpen}
      onOpenChange={setFiltersOpen}
      filters={filters}
      onApply={(f) => {
        setFiltersOpen(false);
        onFiltersChange(f);
      }}
      onSaveView={onSaveView}
      languageOptions={langOptions}
      cityOptions={cityOptions}
      countryOptions={countryOptions}
    />
  );

  if (mobile) {
    const cv = cvs.find((c) => String(c.id) === cvId) ?? null;
    const q = query.trim().toLowerCase();
    const rows = items
      .map((job, i) => ({ job, rank: i + 1 }))
      .filter(
        ({ job }) =>
          !q || job.title.toLowerCase().includes(q) || job.company.toLowerCase().includes(q),
      );
    const opened = items.find((j) => j.id === openId) ?? null;

    return (
      <>
        <main>
          <header className="m-head">
            <div className="m-title">
              <h1>Shortlist</h1>
              <span className="spacer" />
              <Dropdown
                trigger={({ toggle }) => (
                  <button
                    className="iconbtn m-icon"
                    onClick={toggle}
                    disabled={!items.length}
                    aria-label="Export"
                  >
                    <Download size={18} />
                  </button>
                )}
              >
                {exportMenu}
              </Dropdown>
              <button
                className="iconbtn m-icon"
                data-tour="rank"
                onClick={rerank}
                disabled={reranking || !items.length}
                aria-label="Rank top 10 with AI"
              >
                {reranking ? <Loader2 size={18} className="spin" /> : <Sparkles size={18} />}
              </button>
            </div>
            <Dropdown
              className="m-cvmenu"
              trigger={({ toggle }) => (
                <button className="cvpill" onClick={toggle} data-tour="cv">
                  <span className="file">
                    {cv?.content_type === "application/pdf" ? "PDF" : cv?.filename ? "TXT" : "CV"}
                  </span>
                  {cv ? (
                    <>
                      Matching <b>{cv.label}</b>
                    </>
                  ) : (
                    "No CV yet"
                  )}
                  <ChevronsUpDown size={14} className="faint" />
                </button>
              )}
            >
              {(close) => (
                <>
                  {cvs.map((c) => (
                    <button
                      key={c.id}
                      className={String(c.id) === cvId ? "on" : ""}
                      onClick={() => {
                        onSelectCv(String(c.id));
                        close();
                      }}
                    >
                      <span className="menu-label">{c.label}</span>
                      {String(c.id) === cvId && <Check size={14} className="check-mark" />}
                    </button>
                  ))}
                  {cvs.length > 0 && <div className="sep" />}
                  <button
                    onClick={() => {
                      close();
                      onUploadCv();
                    }}
                  >
                    <Upload size={14} /> Upload {cvs.length ? "another" : "a"} CV
                  </button>
                </>
              )}
            </Dropdown>
          </header>

          <div className="m-search">
            <label className="search">
              <Search size={16} />
              <input
                type="search"
                placeholder="Search roles or companies"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <button
              className="iconbtn m-icon"
              onClick={() => setFiltersOpen(true)}
              data-tour="filters"
              aria-label="Filters"
            >
              <ListFilter size={18} />
              {activeCount > 0 && <span className="badge num">{activeCount}</span>}
            </button>
          </div>

          {views.length > 0 && (
            <div className="m-chips" data-tour="views">
              {views.map((v) => (
                <button
                  key={v.id}
                  className={"m-chip" + (activeViewId === v.id ? " on" : "")}
                  onClick={() => onApplyView(v)}
                >
                  {v.name}
                </button>
              ))}
            </div>
          )}

          <div className="m-meta num">
            <span>
              {loading
                ? "Ranking..."
                : results
                  ? `${q ? `${rows.length} of ` : ""}${results.count} roles · fit × freshness`
                  : ""}
            </span>
            {activeCount > 0 && (
              <span>
                {activeCount} filter{activeCount === 1 ? "" : "s"} on
              </span>
            )}
          </div>

          {message && (
            <div className={"banner" + (message.error ? " error" : "")}>{message.text}</div>
          )}

          <div className="m-scroll scroll-themed" data-tour="table">
            {results && rows.length === 0 && !loading ? (
              <div className="empty">
                {q ? "No roles match this search." : "No roles match these filters."}{" "}
                {!q && (
                  <button className="linkbtn" onClick={() => setFiltersOpen(true)}>
                    Adjust filters
                  </button>
                )}
              </div>
            ) : (
              rows.map(({ job: j, rank }) => {
                const fit = Math.max(3, Math.round((j.similarity / maxSim) * 100));
                const v = judged[j.id];
                const effort = effortText(j);
                return (
                  <button key={j.id} className="m-job" onClick={() => setOpenId(j.id)}>
                    <span className="m-job-main">
                      <span className="t">{j.title}</span>
                      <span className="s">
                        {j.company} · {j.city || j.country || j.location || "Not specified"}
                        {j.is_remote ? " · Remote" : ""}
                      </span>
                      <span className="m">
                        {j.posted_at && (
                          <span className={"num" + (isStale(j.posted_at) ? " stale" : "")}>
                            {fmtAgoLong(j.posted_at)}
                          </span>
                        )}
                        {j.application_status && <StatusDot status={j.application_status} />}
                        {v && <span className={"num tier-" + v.verdict}>AI {v.overall_score}</span>}
                        {effort && <span className="tag">{effort}</span>}
                      </span>
                    </span>
                    <span className="m-job-fit num">
                      <b>{fit}</b>
                      <span className="fitbar">
                        <i style={{ width: `${fit}%` }} />
                      </span>
                      <small>#{rank}</small>
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </main>

        {opened && (
          <JobInspector
            page="Shortlist"
            job={opened}
            cvId={cvId}
            verdict={judged[opened.id]}
            onVerdict={(v) => setJudged((prev) => ({ ...prev, [v.job_id]: v }))}
            onStatus={onStatus}
            onClose={() => setOpenId(null)}
          />
        )}

        {filtersModal}
      </>
    );
  }

  return (
    <>
      <main>
        <div className="top">
          <h1>Shortlist</h1>
          <div className="spacer" />
          <Dropdown
            trigger={({ toggle }) => (
              <button className="btn" onClick={toggle} disabled={!items.length}>
                Export <ChevronDown size={14} />
              </button>
            )}
          >
            {exportMenu}
          </Dropdown>
          <button
            className="btn primary"
            data-tour="rank"
            onClick={rerank}
            disabled={reranking || !items.length}
            title="Score the top 10 with the AI judge and re-order by fit"
          >
            {reranking ? (
              <span className="btn-spin">
                <Loader2 size={14} className="spin" /> Ranking...
              </span>
            ) : (
              "Rank top 10 with AI"
            )}
          </button>
        </div>

        <div className="toolbar">
          <button className="chip filters" onClick={() => setFiltersOpen(true)} data-tour="filters">
            <ListFilter size={14} />
            Filters
            {activeCount > 0 && <span className="n num">{activeCount}</span>}
          </button>
          {chips.map(([k, v], i) => (
            <button
              className="chip"
              key={k + i}
              onClick={() => setFiltersOpen(true)}
              title={`${k}: ${v}`}
            >
              <span className="k">{k}</span>
              <span>{v}</span>
            </button>
          ))}
          <span className="meta num">
            {loading
              ? "Ranking..."
              : results
                ? `${results.count} roles · sorted by fit × freshness`
                : ""}
          </span>
        </div>

        {message && (
          <div className={"banner" + (message.error ? " error" : "")}>{message.text}</div>
        )}

        <div className="table-scroll scroll-themed">
          {results && items.length === 0 && !loading ? (
            <div className="empty">
              No roles match these filters.{" "}
              <button className="linkbtn" onClick={() => setFiltersOpen(true)}>
                Adjust filters
              </button>
            </div>
          ) : (
            <table className="jobs" data-tour="table">
              <thead>
                <tr>
                  <th className="c-rank" />
                  <th>Role</th>
                  <th className="c-loc">Location</th>
                  <th className="c-fit" title="Embedding similarity, relative to the top match">
                    Fit
                  </th>
                  <th
                    className="c-ai"
                    title="AI judge score (0-100), after Assess fit or Rank top 10"
                  >
                    AI
                  </th>
                  <th className="c-posted">Posted</th>
                  <th className="c-status">Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((j, i) => {
                  const fit = Math.max(3, Math.round((j.similarity / maxSim) * 100));
                  const v = judged[j.id];
                  return (
                    <tr
                      key={j.id}
                      data-row={j.id}
                      className={j.id === selectedId ? "sel" : ""}
                      onClick={() => setSelectedId(j.id)}
                    >
                      <td className="rank num">{i + 1}</td>
                      <td className="role" title={`${j.title} · ${j.company}`}>
                        <b>{j.title}</b>
                        <span className="co">{j.company}</span>
                      </td>
                      <td className="muted">
                        {j.city || j.country || j.location || "Not specified"}
                        {j.is_remote ? " · Remote" : ""}
                      </td>
                      <td>
                        <div className="fit num">
                          <div className="fitbar">
                            <i style={{ width: `${fit}%` }} />
                          </div>
                          {fit}
                        </div>
                      </td>
                      <td className={"num" + (v ? " tier-" + v.verdict : " faint")}>
                        {v ? v.overall_score : "-"}
                      </td>
                      <td className={"num " + (isStale(j.posted_at) ? "stale" : "muted")}>
                        {fmtAgo(j.posted_at)}
                      </td>
                      <td>
                        <StatusDot status={j.application_status} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </main>

      {selected ? (
        <JobInspector
          job={selected}
          cvId={cvId}
          verdict={judged[selected.id]}
          onVerdict={(v) => setJudged((prev) => ({ ...prev, [v.job_id]: v }))}
          onStatus={onStatus}
        />
      ) : (
        <aside className="inspector">
          <div className="insp-empty">
            {loading ? "Ranking roles..." : "Select a role to see details."}
          </div>
        </aside>
      )}

      {filtersModal}
    </>
  );
}
