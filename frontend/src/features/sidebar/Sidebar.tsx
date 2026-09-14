import {
  Check,
  CircleHelp,
  ChevronsUpDown,
  Columns3,
  ListFilter,
  LogIn,
  LogOut,
  Moon,
  Pencil,
  Rows3,
  Sun,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { Logo } from "../../components/Logo";
import { Dropdown } from "../../components/Dropdown";
import { STAGES } from "../../constants";
import { fmtDate, initials } from "../../format";
import type { Cv, SavedView, Stats, User } from "../../types";

export type View = "shortlist" | "board";

export function Sidebar({
  view,
  onView,
  stats,
  shortlistCount,
  views,
  activeViewId,
  onApplyView,
  onDeleteView,
  cvs,
  cvId,
  onSelectCv,
  onEditCv,
  onDeleteCv,
  onUploadCv,
  user,
  onSignIn,
  onLogout,
  theme,
  onToggleTheme,
  onTour,
}: {
  view: View;
  onView: (v: View) => void;
  stats: Stats;
  shortlistCount: number | null;
  views: SavedView[];
  activeViewId: number | null;
  onApplyView: (v: SavedView) => void;
  onDeleteView: (v: SavedView) => void;
  cvs: Cv[];
  cvId: string;
  onSelectCv: (id: string) => void;
  onEditCv: () => void;
  onDeleteCv: () => void;
  onUploadCv: () => void;
  user: User | null;
  onSignIn: () => void;
  onLogout: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onTour: () => void;
}) {
  const cv = cvs.find((c) => String(c.id) === cvId) ?? null;

  return (
    <aside className="side scroll-themed">
      <div className="brand">
        <Logo />
        <div className="wm">
          <b>Smart Job Tracker</b>
          <span>AI-ranked job search</span>
        </div>
      </div>

      <button
        className={"nav" + (view === "shortlist" ? " on" : "")}
        onClick={() => onView("shortlist")}
      >
        <Rows3 size={15} />
        Shortlist
        {shortlistCount != null && <span className="count num">{shortlistCount}</span>}
      </button>
      <button
        className={"nav" + (view === "board" ? " on" : "")}
        onClick={() => onView("board")}
        data-tour="applications"
      >
        <Columns3 size={15} />
        Applications
        <span className="count num">{stats.total || ""}</span>
      </button>

      <h6>Pipeline</h6>
      {STAGES.slice(0, 6).map((s) => (
        <button key={s.key} className="nav" onClick={() => onView("board")}>
          <span className="dot" style={{ background: s.color }} />
          {s.label}
          <span className="count num">{stats.by_status[s.key] || ""}</span>
        </button>
      ))}

      <h6 data-tour="views">Saved views</h6>
      {views.length === 0 && (
        <div className="side-empty">Save a filter set from the Filters popup to reuse it here.</div>
      )}
      {views.map((v) => (
        <div className="view-row" key={v.id}>
          <button
            className={"nav" + (activeViewId === v.id && view === "shortlist" ? " on" : "")}
            onClick={() => onApplyView(v)}
            title={v.name}
          >
            <ListFilter size={14} />
            <span className="label">{v.name}</span>
          </button>
          <button
            className="view-x"
            onClick={() => onDeleteView(v)}
            aria-label={`Delete view ${v.name}`}
          >
            <X size={13} />
          </button>
        </div>
      ))}

      <div className="cvbox">
        <h6>Matching against</h6>
        <div className="cvcard" data-tour="cv">
          <Dropdown
            placement="up"
            trigger={({ toggle }) => (
              <button
                className="cvswitch"
                onClick={toggle}
                title="Switch CV"
                disabled={!cvs.length}
              >
                <div className="file">
                  {cv?.content_type === "application/pdf" ? "PDF" : cv?.filename ? "TXT" : "CV"}
                </div>
                <div className="lbl">
                  <b>{cv ? cv.label : "No CV yet"}</b>
                  <small>
                    {cv ? `Uploaded ${fmtDate(cv.created_at)}` : "Upload one to start matching"}
                  </small>
                </div>
                {cvs.length > 0 && <ChevronsUpDown size={14} className="faint" />}
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
                    <span className="menu-label">
                      {c.label}
                      {c.embedded ? "" : " (no embedding)"}
                    </span>
                    {String(c.id) === cvId && <Check size={14} className="check-mark" />}
                  </button>
                ))}
                <div className="sep" />
                <button
                  onClick={() => {
                    close();
                    onUploadCv();
                  }}
                >
                  <Upload size={14} /> Upload another CV
                </button>
              </>
            )}
          </Dropdown>
          <div className="cvactions">
            <button className="iconbtn" onClick={onEditCv} disabled={!cv} title="Edit this CV">
              <Pencil size={14} />
            </button>
            <button
              className="iconbtn danger"
              onClick={onDeleteCv}
              disabled={!cv}
              title="Delete this CV"
            >
              <Trash2 size={14} />
            </button>
            <button className="btn upload" onClick={onUploadCv}>
              <Upload size={14} /> Upload CV
            </button>
          </div>
        </div>

        <div className="account">
          <div className="avatar">{user ? initials(user.name) : "G"}</div>
          <div className="who">
            <b>{user ? user.name : "Guest"}</b>
            {user && <small>{user.email}</small>}
          </div>
          <button className="iconbtn bare" onClick={onTour} title="Show me around">
            <CircleHelp size={15} />
          </button>
          <button
            className="iconbtn bare"
            onClick={onToggleTheme}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          {user ? (
            <button className="iconbtn bare" onClick={onLogout} title="Log out">
              <LogOut size={15} />
            </button>
          ) : (
            <button className="iconbtn bare" onClick={onSignIn} title="Sign in">
              <LogIn size={15} />
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
