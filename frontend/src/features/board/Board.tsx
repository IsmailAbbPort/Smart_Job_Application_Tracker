import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, Search } from "lucide-react";
import { api } from "../../api";
import { STAGES, stageOf } from "../../constants";
import { fmtDate } from "../../format";
import { useBackToClose, useIsMobile } from "../../hooks";
import type { Application } from "../../types";
import { ExpiredTag, JobInspector } from "../inspector/JobInspector";
import { AddApplicationModal } from "./AddApplicationModal";
import { useHoldDrag } from "./useHoldDrag";

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
  const mobile = useIsMobile();
  const [stage, setStage] = useState<string>("saved");
  const [searchOpen, setSearchOpen] = useState(false);

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

  const holdDrag = useHoldDrag((jobId, target) => {
    const from = apps.find((a) => a.job.id === jobId)?.status;
    if (target !== from) changeStatus(jobId, target);
  });

  useBackToClose(mobile && openId != null, () => setOpenId(null));

  // Phone shows one stage at a time; start on the first one with anything in it.
  const stagePicked = useRef(false);
  useEffect(() => {
    if (loading || stagePicked.current) return;
    stagePicked.current = true;
    const first = STAGES.find((s) => apps.some((a) => a.status === s.key));
    if (first) setStage(first.key);
  }, [loading, apps]);

  useEffect(() => {
    if (mobile)
      document
        .querySelector(`.m-stage[data-drop-stage="${stage}"]`)
        ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [mobile, stage]);

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

  const addModal = (
    <AddApplicationModal
      open={addOpen}
      onOpenChange={setAddOpen}
      initialStatus={addStage}
      onAdded={(app) => {
        setApps((prev) => [app, ...prev]);
        window.dispatchEvent(new CustomEvent("apps-changed-silent"));
      }}
    />
  );

  const cardBody = (a: Application) => (
    <>
      <div className="t">{a.job.title}</div>
      <div className="c">
        {a.job.company}
        {a.job.city || a.job.country || a.job.location
          ? ` · ${a.job.city || a.job.country || a.job.location}`
          : ""}
      </div>
      <div className="m">
        <span className="num">
          {a.applied_at ? "Applied " + fmtDate(a.applied_at) : "Not applied yet"}
        </span>
        {a.job.source === "manual" && <span className="tag">Manual</span>}
        {a.job.source_gone_at && <ExpiredTag job={a.job} />}
      </div>
    </>
  );

  if (mobile) {
    const items = visible.filter((a) => a.status === stage);
    const stageLabel = stageOf(stage)?.label ?? stage;
    const dragged = holdDrag.drag && apps.find((a) => a.job.id === holdDrag.drag!.jobId);

    return (
      <>
        <main>
          <header className="m-head">
            <div className="m-title">
              <h1>Applications</h1>
              <span className="spacer" />
              <button
                className={"iconbtn m-icon" + (searchOpen ? " on" : "")}
                onClick={() => {
                  setSearchOpen((o) => !o);
                  setQuery("");
                }}
                aria-label="Search applications"
                aria-pressed={searchOpen}
              >
                <Search size={18} />
              </button>
              <button
                className="iconbtn m-icon"
                onClick={() => {
                  setAddStage(stage);
                  setAddOpen(true);
                }}
                aria-label="Add application"
              >
                <Plus size={18} />
              </button>
            </div>
            <div className="m-sub num">
              {q ? `${visible.length} of ${apps.length} shown · ` : ""}
              {apps.length} tracked · {active} active
            </div>
          </header>

          {searchOpen && (
            <div className="m-search">
              <label className="search">
                <Search size={16} />
                <input
                  type="search"
                  autoFocus
                  placeholder="Search by role, company or place"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
            </div>
          )}

          <div className="m-stages" role="tablist" aria-label="Stages">
            {STAGES.map((s) => (
              <button
                key={s.key}
                role="tab"
                aria-selected={stage === s.key}
                data-drop-stage={s.key}
                className={
                  "m-stage" +
                  (stage === s.key ? " on" : "") +
                  (holdDrag.drag?.over === s.key ? " over" : "")
                }
                onClick={() => setStage(s.key)}
              >
                <span className="dot" style={{ background: s.color }} />
                {s.label}
                <span className="c num">
                  {visible.filter((a) => a.status === s.key).length}
                </span>
              </button>
            ))}
          </div>

          {err && <div className="banner error">{err}</div>}

          {loading ? (
            <div className="empty">Loading applications...</div>
          ) : (
            <div className="m-scroll scroll-themed">
              {apps.length > 0 && (
                <div className="m-hint">Hold a card, then drag it onto a stage to move it.</div>
              )}
              <div className="m-cards">
                {items.length ? (
                  items.map((a) => (
                    <button
                      key={a.job.id}
                      className={
                        "appcard" + (holdDrag.drag?.jobId === a.job.id ? " lifted" : "")
                      }
                      onTouchStart={(e) =>
                        holdDrag.start(
                          a.job.id,
                          e.currentTarget,
                          e.touches[0].clientX,
                          e.touches[0].clientY,
                          true,
                        )
                      }
                      onMouseDown={(e) =>
                        e.button === 0 &&
                        holdDrag.start(a.job.id, e.currentTarget, e.clientX, e.clientY, false)
                      }
                      onContextMenu={(e) => e.preventDefault()}
                      onClick={() => !holdDrag.consumeClick() && setOpenId(a.job.id)}
                    >
                      {cardBody(a)}
                    </button>
                  ))
                ) : (
                  <div className="col-empty">
                    {q ? "No matches" : `Nothing in ${stageLabel} yet`}
                  </div>
                )}
              </div>
            </div>
          )}
        </main>

        {holdDrag.drag && dragged && (
          <>
            <div
              className="appcard drag-ghost"
              style={{
                left: holdDrag.drag.x - holdDrag.drag.offsetX,
                top: holdDrag.drag.y - holdDrag.drag.offsetY,
                width: holdDrag.drag.width,
              }}
            >
              {cardBody(dragged)}
            </div>
            <div className="drop-tray">
              <h6>Drop on a stage</h6>
              <div className="drop-grid">
                {STAGES.map((s) => (
                  <div
                    key={s.key}
                    data-drop-stage={s.key}
                    className={
                      "drop-tile" +
                      (holdDrag.drag?.over === s.key ? " over" : "") +
                      (dragged.status === s.key ? " current" : "")
                    }
                  >
                    <span className="dot" style={{ background: s.color }} />
                    {s.label}
                    {dragged.status === s.key && <small>Current</small>}
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {open && (
          <JobInspector
            page="Applications"
            job={{ ...open.job, application_status: open.status }}
            cvId={cvId}
            onStatus={changeStatus}
            onClose={() => setOpenId(null)}
          />
        )}

        {addModal}
      </>
    );
  }

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
                          {cardBody(a)}
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

      {addModal}
    </>
  );
}
