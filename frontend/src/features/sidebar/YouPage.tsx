import {
  Check,
  ChevronRight,
  CircleHelp,
  ListFilter,
  LogIn,
  LogOut,
  Moon,
  Pencil,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { fmtDate, initials } from "../../format";
import type { Cv, SavedView, User } from "../../types";

// Phone "You" tab: everything the desktop sidebar holds below the nav.
export function YouPage({
  cvs,
  cvId,
  onSelectCv,
  onEditCv,
  onDeleteCv,
  onUploadCv,
  views,
  activeViewId,
  onApplyView,
  onDeleteView,
  user,
  onSignIn,
  onLogout,
  theme,
  onToggleTheme,
  onTour,
}: {
  cvs: Cv[];
  cvId: string;
  onSelectCv: (id: string) => void;
  onEditCv: () => void;
  onDeleteCv: () => void;
  onUploadCv: () => void;
  views: SavedView[];
  activeViewId: number | null;
  onApplyView: (v: SavedView) => void;
  onDeleteView: (v: SavedView) => void;
  user: User | null;
  onSignIn: () => void;
  onLogout: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onTour: () => void;
}) {
  return (
    <main>
      <header className="m-head">
        <div className="m-title">
          <h1>You</h1>
        </div>
      </header>

      <div className="m-scroll scroll-themed">
        <h6 className="m-label">Matching against</h6>
        <div className="m-group" role="radiogroup" aria-label="CV">
          {cvs.length === 0 && (
            <div className="m-item faint">No CV yet. Upload one to start matching.</div>
          )}
          {cvs.map((c) => {
            const on = String(c.id) === cvId;
            return (
              <button
                key={c.id}
                className="m-item"
                role="radio"
                aria-checked={on}
                onClick={() => onSelectCv(String(c.id))}
              >
                <span className={"m-radio" + (on ? " on" : "")} />
                <span className="file">
                  {c.content_type === "application/pdf" ? "PDF" : c.filename ? "TXT" : "CV"}
                </span>
                <span className="lbl">
                  <b>
                    {c.label}
                    {c.embedded ? "" : " (no embedding)"}
                  </b>
                  <small>Uploaded {fmtDate(c.created_at)}</small>
                </span>
              </button>
            );
          })}
          <div className="m-group-actions">
            <button className="btn" onClick={onEditCv} disabled={!cvId}>
              <Pencil size={14} /> Edit
            </button>
            <button className="btn m-danger" onClick={onDeleteCv} disabled={!cvId}>
              <Trash2 size={14} /> Delete
            </button>
            <span className="spacer" />
            <button className="btn" onClick={onUploadCv}>
              <Upload size={14} /> Upload CV
            </button>
          </div>
        </div>

        <h6 className="m-label">Saved views</h6>
        <div className="m-group">
          {views.length === 0 && (
            <div className="m-item faint">Save a filter set from Filters to reuse it here.</div>
          )}
          {views.map((v) => (
            <div className="m-item" key={v.id}>
              <button className="m-item-main" onClick={() => onApplyView(v)}>
                <ListFilter size={16} className="muted" />
                <span className="lbl">
                  <b>{v.name}</b>
                </span>
                {activeViewId === v.id && <Check size={16} className="muted" />}
              </button>
              <button
                className="iconbtn bare"
                onClick={() => onDeleteView(v)}
                aria-label={`Delete view ${v.name}`}
              >
                <X size={16} />
              </button>
            </div>
          ))}
        </div>

        <h6 className="m-label">App</h6>
        <div className="m-group">
          <button
            className="m-item"
            role="switch"
            aria-checked={theme === "dark"}
            onClick={onToggleTheme}
          >
            <Moon size={16} className="muted" />
            <span className="lbl">
              <b>Dark theme</b>
            </span>
            <span className={"m-toggle" + (theme === "dark" ? " on" : "")} />
          </button>
          <button className="m-item" onClick={onTour}>
            <CircleHelp size={16} className="muted" />
            <span className="lbl">
              <b>Show me around</b>
            </span>
            <ChevronRight size={16} className="faint" />
          </button>
        </div>

        <div className="m-group">
          <div className="m-item">
            <div className="avatar">{user ? initials(user.name) : "G"}</div>
            <span className="lbl">
              <b>{user ? user.name : "Guest"}</b>
              {user && <small>{user.email}</small>}
            </span>
            {user ? (
              <button className="btn" onClick={onLogout}>
                <LogOut size={14} /> Log out
              </button>
            ) : (
              <button className="btn primary" onClick={onSignIn}>
                <LogIn size={14} /> Sign in
              </button>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
