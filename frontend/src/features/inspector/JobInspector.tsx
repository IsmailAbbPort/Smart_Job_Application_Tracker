import { useEffect, useState } from "react";
import { ArrowUpRight, Loader2, X } from "lucide-react";
import { api } from "../../api";
import { STAGES, stageOf } from "../../constants";
import { effortText, fmtAgoLong, fmtSalary, isStale } from "../../format";
import { Select, type Option } from "../../components/Select";
import type { Job, Letter, Verdict } from "../../types";

const STATUS_OPTS: Option[] = [
  { value: "", label: "Not tracked" },
  ...STAGES.map((s) => ({ value: s.key, label: s.label })),
];

const DIMENSIONS: [string, string][] = [
  ["skills", "Skills"],
  ["seniority", "Seniority"],
  ["domain", "Domain"],
  ["location_remote", "Location eligibility"],
];

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function StatusDot({ status }: { status?: string | null }) {
  const stage = stageOf(status);
  if (!stage) return <span className="status none">Not tracked</span>;
  return (
    <span className="status">
      <span className="dot" style={{ background: stage.color }} />
      {stage.label}
    </span>
  );
}

function placeText(job: Job): string {
  const place = job.city
    ? `${job.city}, ${job.country}`
    : job.country || job.location || "Not specified";
  return job.is_remote ? `${place} · Remote` : place;
}

function experienceText(job: Job): string {
  if (typeof job.min_years_experience !== "number") return "Not stated";
  const gap =
    typeof job.experience_gap === "number" && job.experience_gap > 0
      ? ` (you are ${job.experience_gap} short)`
      : "";
  return `${job.min_years_experience}+ years${gap}`;
}

function visaText(job: Job): string | null {
  if (job.visa_sponsorship === true) return "Sponsors visa";
  if (job.visa_sponsorship === false) return "No sponsorship";
  return null;
}

// Highlight [placeholders] the drafter left for the user to fill in.
function LetterText({ body }: { body: string }) {
  const parts = body.split(/(\[[^\]]+\])/g);
  return (
    <pre className="letter">
      {parts.map((p, i) =>
        /^\[[^\]]+\]$/.test(p) ? (
          <span className="ph" key={i}>
            {p}
          </span>
        ) : (
          p
        ),
      )}
    </pre>
  );
}

export function JobInspector({
  job,
  cvId,
  verdict: givenVerdict,
  onVerdict,
  onStatus,
  onClose,
  drawer,
}: {
  job: Job;
  cvId: string;
  verdict?: Verdict;
  onVerdict?: (v: Verdict) => void;
  onStatus: (jobId: number, status: string) => void;
  onClose?: () => void;
  drawer?: boolean;
}) {
  const [verdict, setVerdict] = useState<Verdict | null>(givenVerdict ?? null);
  const [letter, setLetter] = useState<Letter | null>(null);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [judging, setJudging] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [verdictErr, setVerdictErr] = useState("");
  const [letterErr, setLetterErr] = useState("");
  const [editing, setEditing] = useState(false);
  const [draftBody, setDraftBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  // Load any stored verdict / letter for this job (free: no model call).
  useEffect(() => {
    let alive = true;
    setVerdict(givenVerdict ?? null);
    setLetter(null);
    setVerdictErr("");
    setLetterErr("");
    setEditing(false);
    if (!cvId) return;
    setLoadingSaved(true);
    Promise.all([
      givenVerdict ? Promise.resolve(givenVerdict) : api.getVerdict(job.id, cvId).catch(() => null),
      api.getLetter(job.id, cvId).catch(() => null),
    ])
      .then(([v, l]) => {
        if (!alive) return;
        if (v) setVerdict(v);
        setLetter(l);
      })
      .finally(() => alive && setLoadingSaved(false));
    return () => {
      alive = false;
    };
    // givenVerdict is only a seed for a newly selected job.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id, cvId]);

  useEffect(() => {
    if (givenVerdict) setVerdict(givenVerdict);
  }, [givenVerdict]);

  const assess = async (refresh = false) => {
    setJudging(true);
    setVerdictErr("");
    try {
      const v = await api.judge(job.id, cvId, refresh);
      setVerdict(v);
      onVerdict?.(v);
    } catch (e) {
      setVerdictErr("AI judge unavailable: " + (e as Error).message);
    } finally {
      setJudging(false);
    }
  };

  const draft = async (refresh = false) => {
    setDrafting(true);
    setLetterErr("");
    setEditing(false);
    try {
      setLetter(await api.draftLetter(job.id, cvId, refresh));
    } catch (e) {
      setLetterErr("Cover letter drafter unavailable: " + (e as Error).message);
    } finally {
      setDrafting(false);
    }
  };

  const saveEdit = async () => {
    if (!letter) return;
    setSaving(true);
    try {
      setLetter(await api.saveLetter(job.id, draftBody, cvId));
      setEditing(false);
    } catch (e) {
      setLetterErr("Could not save: " + (e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const copy = async () => {
    if (!letter) return;
    try {
      await navigator.clipboard.writeText(letter.body);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked (e.g. insecure context); nothing to do */
    }
  };

  const fab = letter?.fabrication || {};
  const unsupported = (fab.claims || []).filter((c) => !c.supported);
  const placeholders = fab.placeholders || [];
  const salary = fmtSalary(job);
  const visa = visaText(job);
  const effort = effortText(job);
  const noCv = !cvId;

  return (
    <aside
      className={"inspector" + (drawer ? " drawer" : "")}
      aria-label="Job details"
      data-tour={drawer ? undefined : "inspector"}
    >
      <div className="insp-head">
        <div className="co">
          {job.company}
          <span className="tag">
            {job.source === "manual" ? "Added manually" : capital(job.source)}
          </span>
          {job.url && (
            <a
              className="linkbtn posting"
              href={job.url}
              target="_blank"
              rel="noopener"
              title="Open the original posting"
            >
              Posting <ArrowUpRight size={14} />
            </a>
          )}
          {onClose && (
            <button className="iconbtn bare close" onClick={onClose} aria-label="Close details">
              <X size={15} />
            </button>
          )}
        </div>
        <h2>{job.title}</h2>
        <dl className="props">
          <dt>Location</dt>
          <dd>{placeText(job)}</dd>
          {job.posted_at && (
            <>
              <dt>Posted</dt>
              <dd className={isStale(job.posted_at) ? "stale" : ""}>{fmtAgoLong(job.posted_at)}</dd>
            </>
          )}
          <dt>Experience</dt>
          <dd>{experienceText(job)}</dd>
          {salary && (
            <>
              <dt>Salary</dt>
              <dd>{salary}</dd>
            </>
          )}
          {visa && (
            <>
              <dt>Visa</dt>
              <dd>{visa}</dd>
            </>
          )}
          {!!job.required_languages?.length && (
            <>
              <dt>Languages</dt>
              <dd>Requires {job.required_languages.join(", ")}</dd>
            </>
          )}
          <dt>Extra effort</dt>
          <dd>{effort || "None"}</dd>
          <dt>Status</dt>
          <dd>
            <Select
              options={STATUS_OPTS}
              value={
                STATUS_OPTS.find((o) => o.value === (job.application_status ?? "")) ??
                STATUS_OPTS[0]
              }
              isSearchable={false}
              onChange={(o) => onStatus(job.id, (o as Option)?.value ?? "")}
              formatOptionLabel={(o) => (o.value ? <StatusDot status={o.value} /> : o.label)}
            />
          </dd>
        </dl>
      </div>

      <div className="insp-actions">
        {!letter && (
          <button className="btn primary" onClick={() => draft()} disabled={drafting || noCv}>
            {drafting ? (
              <span className="btn-spin">
                <Loader2 size={14} className="spin" /> Drafting...
              </span>
            ) : (
              "Draft cover letter"
            )}
          </button>
        )}
        {!verdict && (
          <button
            className={"btn" + (letter ? " primary" : "")}
            onClick={() => assess()}
            disabled={judging || noCv}
          >
            {judging ? (
              <span className="btn-spin">
                <Loader2 size={14} className="spin" /> Assessing...
              </span>
            ) : (
              "Assess fit"
            )}
          </button>
        )}
      </div>

      <div className="insp-body scroll-themed">
        {noCv && <div className="sec-cta">Upload a CV to assess fit and draft cover letters.</div>}
        {loadingSaved && !verdict && !letter && (
          <div className="faint">Loading saved results...</div>
        )}

        {!noCv && !loadingSaved && !verdict && !letter && !verdictErr && !letterErr && (
          <div className="sec-cta">
            No AI results for this role yet. Assess fit scores it against your CV; Draft cover
            letter writes a letter grounded in it. Each is one model call.
          </div>
        )}
        {verdictErr && <div className="sec-err">{verdictErr}</div>}
        {verdict && (
          <div className="sec">
            <h4>
              AI fit assessment
              <span className="acts">
                <button
                  onClick={() => assess(true)}
                  disabled={judging}
                  title="Run the AI judge again"
                >
                  {judging ? "Assessing..." : "Re-assess"}
                </button>
              </span>
            </h4>
            <div className="score">
              <b className="num">{verdict.overall_score}</b>
              <span className={"tier tier-" + verdict.verdict}>{capital(verdict.verdict)} fit</span>
            </div>
            <div className="verdict-line">{verdict.one_line_verdict}</div>
            <div className="dims num">
              {DIMENSIONS.map(([key, label]) => {
                const s = verdict.dimension_scores?.[key];
                return typeof s === "number" ? <DimRow key={key} label={label} score={s} /> : null;
              })}
            </div>
            <div className="dimhint">
              Location eligibility: whether you can work from where you live (remote region, time
              zone, visa).
            </div>
          </div>
        )}
        {verdict && verdict.matched_requirements?.length > 0 && (
          <div className="sec">
            <h4>Matched requirements</h4>
            {verdict.matched_requirements.map((m, i) => (
              <div className="req" key={i}>
                <b>{m.requirement}</b>
                <span>{m.cv_evidence}</span>
              </div>
            ))}
          </div>
        )}
        {verdict && verdict.gaps?.length > 0 && (
          <div className="sec">
            <h4>Gaps</h4>
            {verdict.gaps.map((g, i) => (
              <div className="bullet" key={i}>
                {g}
              </div>
            ))}
          </div>
        )}

        {letterErr && <div className="sec-err">{letterErr}</div>}
        {letter && (
          <div className="sec">
            <h4>
              Cover letter{letter.edited ? " (edited)" : " draft"}
              <span className="acts">
                {editing ? (
                  <>
                    <button onClick={() => setEditing(false)} disabled={saving}>
                      Cancel
                    </button>
                    <button onClick={saveEdit} disabled={saving}>
                      {saving ? "Saving..." : "Save"}
                    </button>
                  </>
                ) : (
                  <>
                    <button onClick={copy}>{copied ? "Copied" : "Copy"}</button>
                    <button
                      onClick={() => {
                        setDraftBody(letter.body);
                        setEditing(true);
                      }}
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => draft(true)}
                      disabled={drafting}
                      title="Draft a new letter (replaces the current one)"
                    >
                      {drafting ? "Drafting..." : "Regenerate"}
                    </button>
                  </>
                )}
              </span>
            </h4>
            {editing ? (
              <textarea
                className="letter"
                value={draftBody}
                onChange={(e) => setDraftBody(e.target.value)}
                autoFocus
              />
            ) : (
              <LetterText body={letter.body} />
            )}
            <div className="lettermeta num">
              <span>
                {Math.round((fab.grounded_ratio ?? 1) * 100)}% of claims grounded in your CV
              </span>
              {placeholders.length > 0 && (
                <span>
                  {placeholders.length} placeholder{placeholders.length === 1 ? "" : "s"} to fill
                </span>
              )}
            </div>
            {unsupported.length > 0 && (
              <div className="letter-issues">
                <span className="lbl">Unsupported claims (remove or back with a real fact)</span>
                {unsupported.map((c, i) => (
                  <div className="bullet bad" key={i}>
                    {c.claim}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

function DimRow({ label, score }: { label: string; score: number }) {
  return (
    <>
      <span>{label}</span>
      <div className="fitbar">
        <i style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
      </div>
      <span>{score}</span>
    </>
  );
}
