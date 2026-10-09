import { useEffect, useRef, useState } from "react";
import * as Tooltip from "@radix-ui/react-tooltip";
import { ArrowLeft, ArrowUpRight, ChevronLeft, Loader2, X } from "lucide-react";
import { api } from "../../api";
import { STAGES, stageOf } from "../../constants";
import { effortText, fmtAgoLong, fmtDate, fmtSalary, isStale } from "../../format";
import { Select, type Option } from "../../components/Select";
import type { Job, Letter, RequirementCheck, Verdict } from "../../types";

const STATUS_OPTS: Option[] = [
  { value: "", label: "Not tracked" },
  ...STAGES.map((s) => ({ value: s.key, label: s.label })),
];

const STATUS_LABEL: Record<RequirementCheck["status"], string> = {
  met: "Met",
  partial: "Partial",
  absent: "Missing",
};

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

// The explanation is hover/keyboard only: the tooltip is hidden on touch screens.
export function ExpiredTag({ job, focusable }: { job: Job; focusable?: boolean }) {
  const text = `This job is no longer listed on ${capital(job.source)} (noticed ${fmtDate(job.source_gone_at)}). The details shown are the last saved copy.`;
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <span className="tag expired" tabIndex={focusable ? 0 : undefined}>
            Expired
          </span>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content className="tooltip-content hover-only" sideOffset={6}>
            {text}
            <Tooltip.Arrow className="tooltip-arrow" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

function DescriptionPanel({ job, open, onBack }: { job: Job; open: boolean; onBack: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const backRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setText(null);
    setErr("");
  }, [job.id]);

  useEffect(() => {
    if (open) backRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open || text !== null) return;
    let alive = true;
    api
      .jobDescription(job.id)
      .then((d) => alive && setText(d.description))
      .catch((e) => alive && setErr("Could not load the description: " + (e as Error).message));
    return () => {
      alive = false;
    };
  }, [open, job.id, text]);

  return (
    <div
      className={"desc-panel" + (open ? " open" : "")}
      role="dialog"
      aria-label="Description"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onBack();
        }
      }}
    >
      <div className="desc-head">
        <button
          ref={backRef}
          className="iconbtn bare"
          onClick={onBack}
          aria-label="Back to job details"
        >
          <ArrowLeft size={16} />
        </button>
        <h3>Description</h3>
      </div>
      <div className="desc-note">
        Saved copy. Removed from {capital(job.source)} on {fmtDate(job.source_gone_at)}.
      </div>
      <div className="desc-body scroll-themed">
        {err ? (
          <div className="sec-err">{err}</div>
        ) : text === null ? (
          <div className="faint">Loading description...</div>
        ) : (
          text || <span className="faint">No description was saved for this job.</span>
        )}
      </div>
    </div>
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
  page,
}: {
  job: Job;
  cvId: string;
  verdict?: Verdict;
  onVerdict?: (v: Verdict) => void;
  onStatus: (jobId: number, status: string) => void;
  onClose?: () => void;
  drawer?: boolean;
  // Phone: a full-screen page with a back bar, labelled with where back goes.
  page?: string;
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
  const [descOpen, setDescOpen] = useState(false);
  const descBtnRef = useRef<HTMLButtonElement>(null);

  // Load any stored verdict / letter for this job (free: no model call).
  useEffect(() => {
    let alive = true;
    setVerdict(givenVerdict ?? null);
    setLetter(null);
    setVerdictErr("");
    setLetterErr("");
    setEditing(false);
    setDescOpen(false);
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

  // An expired posting has no live URL worth opening, so the link becomes the
  // saved-copy panel instead. Shared by the desktop header and the phone nav.
  const posting = job.source_gone_at ? (
    <button
      ref={descBtnRef}
      className="linkbtn posting"
      onClick={() => setDescOpen(true)}
      title="Read the last saved copy of the description"
    >
      View description
    </button>
  ) : (
    job.url && (
      <a
        className="linkbtn posting"
        href={job.url}
        target="_blank"
        rel="noopener"
        title="Open the original posting"
      >
        Posting <ArrowUpRight size={page ? 16 : 14} />
      </a>
    )
  );
  const statusSelect = (
    <Select
      options={STATUS_OPTS}
      value={STATUS_OPTS.find((o) => o.value === (job.application_status ?? "")) ?? STATUS_OPTS[0]}
      isSearchable={false}
      aria-label="Status"
      maxMenuHeight={page ? 400 : undefined}
      onChange={(o) => onStatus(job.id, (o as Option)?.value ?? "")}
      formatOptionLabel={(o) => (o.value ? <StatusDot status={o.value} /> : o.label)}
    />
  );

  return (
    <aside
      className={"inspector" + (drawer ? " drawer" : "") + (page ? " page" : "")}
      aria-label="Job details"
      data-tour={drawer || page ? undefined : "inspector"}
    >
      {page && (
        <div className="m-nav">
          <button className="m-back" onClick={onClose}>
            <ChevronLeft size={24} strokeWidth={1.75} />
            {page}
          </button>
          <span className="spacer" />
          {posting}
        </div>
      )}
      <div className="insp-head">
        <div className="co">
          {job.company}
          <span className="tag">
            {job.source === "manual" ? "Added manually" : capital(job.source)}
          </span>
          {job.source_gone_at && <ExpiredTag job={job} focusable />}
          {!page && posting}
          {onClose && !page && (
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
          {!page && (
            <>
              <dt>Status</dt>
              <dd>{statusSelect}</dd>
            </>
          )}
        </dl>
      </div>

      <div className={"insp-actions" + (page ? " m-actionbar" : "")}>
        {page && <div className="m-status">{statusSelect}</div>}
        {!letter && (
          <button className="btn primary" onClick={() => draft()} disabled={drafting || noCv}>
            {drafting ? (
              <span className="btn-spin">
                <Loader2 size={14} className="spin" /> Drafting...
              </span>
            ) : page ? (
              "Draft letter"
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
        {job.application_status && (
          <button
            className="btn danger"
            title="Stop tracking this job"
            onClick={() => onStatus(job.id, "")}
          >
            Remove
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
          </div>
        )}
        {verdict && verdict.dealbreakers?.length > 0 && (
          <div className="sec">
            <h4>Dealbreakers</h4>
            {verdict.dealbreakers.map((d, i) => (
              <div className="bullet bad" key={i}>
                {d}
              </div>
            ))}
          </div>
        )}
        {verdict && verdict.requirements?.length > 0 && (
          <div className="sec">
            <h4>Requirements</h4>
            {[...verdict.requirements]
              .sort(
                (a, b) =>
                  Number(a.importance !== "must_have") - Number(b.importance !== "must_have"),
              )
              .map((r, i) => (
                <div className="req" key={i}>
                  <b>
                    <span className={"reqstatus " + r.status}>{STATUS_LABEL[r.status]}</span>
                    {r.requirement}
                    {r.importance === "nice_to_have" && (
                      <span className="faint"> (nice to have)</span>
                    )}
                  </b>
                  {r.cv_evidence && <span>{r.cv_evidence}</span>}
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
      {job.source_gone_at && (
        <DescriptionPanel
          job={job}
          open={descOpen}
          onBack={() => {
            setDescOpen(false);
            descBtnRef.current?.focus();
          }}
        />
      )}
    </aside>
  );
}
