import { useState } from "react";
import { api } from "../../api";
import { STATUSES } from "../../constants";
import { fmtDate, jobBadges, locationText } from "../../format";
import { Select, type Option } from "../../components/Select";
import type { Job, Letter, Verdict } from "../../types";

const STATUS_OPTS: Option[] = [
  { value: "", label: "Not tracked" },
  ...STATUSES.map((s) => ({ value: s, label: s })),
];

function VerdictView({ v }: { v: Verdict }) {
  const d = v.dimension_scores || {};
  return (
    <div className="verdict">
      <div className="headline">
        <span className={"tier " + v.verdict}>{v.verdict}</span>
        <strong>{v.overall_score}/100</strong>
        <span>{v.one_line_verdict}</span>
      </div>
      <div className="dims">
        skills {d.skills} &middot; seniority {d.seniority} &middot; domain {d.domain} &middot;
        location/remote {d.location_remote}
      </div>
      {v.matched_requirements?.length > 0 && (
        <>
          <div>Matched:</div>
          <ul>
            {v.matched_requirements.map((m, i) => (
              <li key={i}>
                {m.requirement} <span style={{ color: "var(--muted)" }}>- {m.cv_evidence}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {v.gaps?.length > 0 && (
        <>
          <div>Gaps:</div>
          <ul>
            {v.gaps.map((g, i) => (
              <li className="gap" key={i}>
                {g}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function LetterView({
  letter,
  cvId,
  onSaved,
}: {
  letter: Letter;
  cvId: string;
  onSaved: (l: Letter) => void;
}) {
  const [body, setBody] = useState(letter.body);
  const [saving, setSaving] = useState(false);
  const f = letter.fabrication || {};
  const unsupported = (f.claims || []).filter((c) => !c.supported);
  const pct = Math.round((f.grounded_ratio ?? 1) * 100);

  const save = async () => {
    setSaving(true);
    try {
      onSaved(await api.saveLetter(letter.job_id, body, cvId));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="letterbox">
      <div className="fab">
        <span className={"badge " + (f.unsupported_count ? "bad" : "good")}>
          Fabrication check: {f.unsupported_count || 0} unsupported ({pct}% grounded)
        </span>
        {letter.edited && <span className="badge">edited</span>}
      </div>
      {unsupported.length > 0 && (
        <div className="fab-list">
          Unsupported claims (remove or back with a real fact):
          <ul>
            {unsupported.map((c, i) => (
              <li className="gap" key={i}>
                {c.claim}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(f.placeholders || []).length > 0 && (
        <div className="fab-list">
          Fill in before sending:
          <ul>
            {f.placeholders!.map((p, i) => (
              <li className="gap" key={i}>
                [{p}]
              </li>
            ))}
          </ul>
        </div>
      )}
      <textarea className="letter-body" value={body} onChange={(e) => setBody(e.target.value)} />
      <div>
        <button className="assess-btn" onClick={save} disabled={saving}>
          Save edits
        </button>
      </div>
    </div>
  );
}

export function JobCard({
  job,
  rank,
  relWidth,
  cvId,
  judged,
  onTrack,
}: {
  job: Job;
  rank: number;
  relWidth: number;
  cvId: string;
  judged?: Verdict;
  onTrack: (jobId: number, status: string) => void;
}) {
  const [verdict, setVerdict] = useState<Verdict | undefined>(judged);
  const [verdictErr, setVerdictErr] = useState("");
  const [judging, setJudging] = useState(false);
  const [letter, setLetter] = useState<Letter | null>(null);
  const [letterMsg, setLetterMsg] = useState("");
  const [drafting, setDrafting] = useState(false);

  const badges = jobBadges(job);
  const posted = fmtDate(job.posted_at);

  const assess = async () => {
    setJudging(true);
    setVerdictErr("");
    try {
      setVerdict(await api.judge(job.id, cvId));
    } catch (e) {
      setVerdictErr("Judge unavailable: " + (e as Error).message);
    } finally {
      setJudging(false);
    }
  };

  const draft = async () => {
    setDrafting(true);
    setLetterMsg("Drafting a CV-grounded letter and auditing it...");
    try {
      setLetter(await api.draftLetter(job.id, cvId));
      setLetterMsg("");
    } catch (e) {
      setLetterMsg("Drafter unavailable: " + (e as Error).message);
    } finally {
      setDrafting(false);
    }
  };

  return (
    <div className="card">
      <div className="top">
        <div>
          <a className="title" href={job.url} target="_blank" rel="noopener">
            {job.title}
          </a>
          <div className="company">
            {job.company} &middot; {locationText(job)}{" "}
            <span className="jobid" title="job id in the database">
              #{job.id}
            </span>
          </div>
        </div>
        {verdict ? (
          <div className="score" title="AI judge score (calibrated 0-100)">
            <div className="num">{verdict.overall_score}</div>
            <div className="lbl">{verdict.verdict}</div>
          </div>
        ) : (
          <div className="score" title={`cosine similarity ${job.similarity}`}>
            <div className="num">#{rank}</div>
            <div className="lbl">by fit</div>
          </div>
        )}
      </div>
      <div className="meter" title="fit relative to the top match">
        <span style={{ width: `${relWidth}%` }} />
      </div>
      <div className="badges">
        {badges.map((b, i) => (
          <span className={"badge " + b.cls} key={i}>
            {b.text}
          </span>
        ))}
        <span className="badge">{job.source}</span>
        {posted && <span className="badge">Posted {posted}</span>}
      </div>
      <div className="assess">
        <div className="status-sel">
          <Select
            options={STATUS_OPTS}
            value={STATUS_OPTS.find((o) => o.value === (job.application_status ?? "")) ?? STATUS_OPTS[0]}
            isSearchable={false}
            onChange={(o) => onTrack(job.id, (o as Option)?.value ?? "")}
          />
        </div>
        <button className="assess-btn" onClick={assess} disabled={judging}>
          {judging ? "Asking the judge..." : "Assess fit (AI judge)"}
        </button>
        <button className="assess-btn" onClick={draft} disabled={drafting}>
          Draft cover letter
        </button>
        {verdictErr && <div className="verdict err">{verdictErr}</div>}
        {!verdictErr && verdict && <VerdictView v={verdict} />}
        {letterMsg && <div className="letterbox"><div className="muted">{letterMsg}</div></div>}
        {letter && <LetterView letter={letter} cvId={cvId} onSaved={setLetter} />}
      </div>
    </div>
  );
}
