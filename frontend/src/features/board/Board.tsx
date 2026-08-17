import { useCallback, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { api } from "../../api";
import { STAGES, STATUSES } from "../../constants";
import { fmtDate, fmtSalary, locationText } from "../../format";
import { Select, type Option } from "../../components/Select";
import type { Application } from "../../types";

const STATUS_OPTS: Option[] = STATUSES.map((s) => ({ value: s, label: s }));

function AppCard({
  app,
  onDragStart,
  onRemove,
  onStatus,
}: {
  app: Application;
  onDragStart: (jobId: number, from: string) => void;
  onRemove: (jobId: number) => void;
  onStatus: (jobId: number, status: string) => void;
}) {
  const job = app.job;
  const bits = [locationText(job)];
  const sal = fmtSalary(job);
  if (sal) bits.push(sal);
  if (app.applied_at) bits.push("applied " + fmtDate(app.applied_at));

  return (
    <div
      className="appcard"
      draggable
      onDragStart={(e) => {
        // Let the status dropdown / remove button work without starting a drag.
        if ((e.target as HTMLElement).closest(".appstatus, .rm")) {
          e.preventDefault();
          return;
        }
        onDragStart(job.id, app.status);
      }}
    >
      <button className="rm" title="Untrack" onClick={() => onRemove(job.id)}>
        <X size={15} />
      </button>
      <div className="t">
        <a href={job.url} target="_blank" rel="noopener">
          {job.title}
        </a>
      </div>
      <div className="c">
        {job.company} <span className="jobid">#{job.id}</span>
      </div>
      <div className="m">
        {bits.map((b, i) => (
          <span key={i}>{b}</span>
        ))}
      </div>
      <div className="appstatus">
        <Select
          options={STATUS_OPTS}
          value={STATUS_OPTS.find((o) => o.value === app.status) ?? null}
          isSearchable={false}
          menuPlacement="auto"
          onChange={(o) => onStatus(job.id, (o as Option)?.value ?? app.status)}
        />
      </div>
    </div>
  );
}

export function Board() {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [dragOver, setDragOver] = useState<string | null>(null);
  const drag = useRef<{ jobId: number; from: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setApps(await api.applications());
      setErr("");
    } catch (e) {
      setErr("Could not load applications: " + (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const onChanged = () => load();
    window.addEventListener("apps-changed", onChanged);
    return () => window.removeEventListener("apps-changed", onChanged);
  }, [load]);

  // Seamless remove (point 29): drop the card from local state immediately, no
  // refetch and no re-render of the whole board. The DELETE runs in the background.
  const remove = useCallback((jobId: number) => {
    setApps((prev) => prev.filter((a) => a.job.id !== jobId));
    api.untrack(jobId).catch(() => load());
    window.dispatchEvent(new CustomEvent("apps-changed-silent"));
  }, [load]);

  const changeStatus = useCallback(
    (jobId: number, status: string) => {
      setApps((prev) => prev.map((a) => (a.job.id === jobId ? { ...a, status } : a)));
      api.track(jobId, status).catch(() => load());
    },
    [load],
  );

  const drop = (target: string) => {
    const d = drag.current;
    setDragOver(null);
    drag.current = null;
    if (d && target && target !== d.from) changeStatus(d.jobId, target);
  };

  const total = apps.length;

  return (
    <section>
      <div className="board-bar">
        <span className="summary">
          {total
            ? `${total} tracked application${total === 1 ? "" : "s"}`
            : "No applications tracked yet, try adding some from the Shortlist tab."}
        </span>
        <button className="assess-btn" onClick={load}>
          Refresh
        </button>
        <span className="hint">Drag a card between columns to change its stage.</span>
      </div>

      {loading ? (
        <div className="empty">Loading applications...</div>
      ) : err ? (
        <div className="empty">{err}</div>
      ) : (
        <div className="board scroll-themed">
          {STAGES.map((s) => {
            const items = apps.filter((a) => a.status === s.key);
            return (
              <div
                key={s.key}
                className={"col" + (dragOver === s.key ? " drag-over" : "")}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(s.key);
                }}
                onDragLeave={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(null);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  drop(s.key);
                }}
              >
                <div className="col-head">
                  <span className="swatch" style={{ background: s.color }} />
                  <span className="name">{s.key}</span>
                  <span className="cnt">{items.length}</span>
                </div>
                <div className="col-body scroll-themed">
                  {items.length ? (
                    items.map((a) => (
                      <AppCard
                        key={a.job.id}
                        app={a}
                        onDragStart={(jobId, from) => (drag.current = { jobId, from })}
                        onRemove={remove}
                        onStatus={changeStatus}
                      />
                    ))
                  ) : (
                    <div className="col-empty">- empty -</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
