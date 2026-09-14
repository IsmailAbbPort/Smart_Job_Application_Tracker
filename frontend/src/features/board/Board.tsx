import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, Search } from "lucide-react";
import { api } from "../../api";
import { STAGES } from "../../constants";
import { fmtDate } from "../../format";
import type { Application } from "../../types";
import { JobInspector } from "../inspector/JobInspector";
import { AddApplicationModal } from "./AddApplicationModal";

export function Board({ cvId }: { cvId: string }) {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [query, setQuery] = useState("");
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [addStage, setAddStage] = useState<string>("saved");
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

  useEffect(() => {
    if (openId == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !(e.target as HTMLElement).closest("[role=dialog]"))
        setOpenId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openId]);

  // Optimistic: move/remove locally first, then sync. The header counts refresh
  // only after the request lands so the stats read never races the write.
  const changeStatus = useCallback(
    (jobId: number, status: string) => {
      if (!status) {
        setApps((prev) => prev.filter((a) => a.job.id !== jobId));
        setOpenId((cur) => (cur === jobId ? null : cur));
        api
          .untrack(jobId)
          .then(() => window.dispatchEvent(new CustomEvent("apps-changed-silent")))
          .catch(() => load());
        return;
      }
      setApps((prev) =>
        prev.map((a) =>
          a.job.id === jobId ? { ...a, status, job: { ...a.job, application_status: status } } : a,
        ),
      );
      api
        .track(jobId, status)
        .then(() => window.dispatchEvent(new CustomEvent("apps-changed-silent")))
        .catch(() => load());
    },
    [load],
  );

  const drop = (target: string) => {
    const d = drag.current;
    setDragOver(null);
    drag.current = null;
    if (d && target && target !== d.from) changeStatus(d.jobId, target);
  };

  const q = query.trim().toLowerCase();
  const visible = useMemo(
    () =>
      q
        ? apps.filter((a) =>
            [a.job.title, a.job.company, a.job.city, a.job.country, a.job.location]
              .filter(Boolean)
              .some((s) => s!.toLowerCase().includes(q)),
          )
        : apps,
    [apps, q],
  );
  const active = apps.filter((a) =>
    ["applied", "screening", "interview", "offer"].includes(a.status),
  ).length;
  const open = apps.find((a) => a.job.id === openId) ?? null;

  return (
    <>
      <main>
        <div className="top">
          <h1>Applications</h1>
          <div className="spacer" />
          <button
            className="btn primary"
            onClick={() => {
              setAddStage("saved");
              setAddOpen(true);
            }}
          >
            <Plus size={14} /> Add application
          </button>
        </div>
        <div className="toolbar">
          <label className="search">
            <Search size={14} />
            <input
              placeholder="Search by role, company or place"
              size={32}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <span className="meta num">
            {q ? `${visible.length} of ${apps.length} shown · ` : ""}
            {apps.length} tracked · {active} active · drag a card to change its stage
          </span>
        </div>
        {err && <div className="banner error">{err}</div>}

        {loading ? (
          <div className="empty">Loading applications...</div>
        ) : (
          <div className="board scroll-themed">
            {STAGES.map((s) => {
              const items = visible.filter((a) => a.status === s.key);
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
                  <div className="col-h">
                    <span className="dot" style={{ background: s.color }} />
                    {s.label}
                    <span className="c num">{items.length}</span>
                    <span className="spacer" />
                    <button
                      className="iconbtn bare"
                      style={{ width: 22, height: 22 }}
                      title={`Add to ${s.label}`}
                      onClick={() => {
                        setAddStage(s.key);
                        setAddOpen(true);
                      }}
                    >
                      <Plus size={13} />
                    </button>
                  </div>
                  <div className="col-body scroll-themed">
                    {items.length ? (
                      items.map((a) => (
                        <button
                          key={a.job.id}
                          className={"appcard" + (a.job.id === openId ? " sel" : "")}
                          draggable
                          onDragStart={() => (drag.current = { jobId: a.job.id, from: a.status })}
                          onClick={() => setOpenId(a.job.id)}
                        >
                          <div className="t">{a.job.title}</div>
                          <div className="c">
                            {a.job.company}
                            {a.job.city || a.job.country || a.job.location
                              ? ` · ${a.job.city || a.job.country || a.job.location}`
                              : ""}
                          </div>
                          <div className="m">
                            <span className="num">
                              {a.applied_at
                                ? "Applied " + fmtDate(a.applied_at)
                                : "Not applied yet"}
                            </span>
                            {a.job.source === "manual" && <span className="tag">Manual</span>}
                          </div>
                        </button>
                      ))
                    ) : (
                      <div className="col-empty">{q ? "No matches" : "No applications"}</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {open && (
        <JobInspector
          drawer
          job={{ ...open.job, application_status: open.status }}
          cvId={cvId}
          onStatus={changeStatus}
          onClose={() => setOpenId(null)}
        />
      )}

      <AddApplicationModal
        open={addOpen}
        onOpenChange={setAddOpen}
        initialStatus={addStage}
        onAdded={(app) => {
          setApps((prev) => [app, ...prev]);
          window.dispatchEvent(new CustomEvent("apps-changed-silent"));
        }}
      />
    </>
  );
}
