import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Shortlist } from "./features/shortlist/Shortlist";
import { Board } from "./features/board/Board";
import { AuthModal } from "./features/auth/AuthModal";
import type { Stats, User } from "./types";

type View = "shortlist" | "board";

export default function App() {
  const [view, setView] = useState<View>(
    new URLSearchParams(location.search).get("view") === "board" ? "board" : "shortlist",
  );
  const [user, setUser] = useState<User | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [stats, setStats] = useState<Stats>({ total: 0, by_status: {} });

  const refreshStats = useCallback(async () => {
    try {
      setStats(await api.stats());
    } catch {
      /* keep last */
    }
  }, []);

  useEffect(() => {
    refreshStats();
    const onChanged = () => refreshStats();
    window.addEventListener("apps-changed", onChanged);
    window.addEventListener("apps-changed-silent", onChanged);
    return () => {
      window.removeEventListener("apps-changed", onChanged);
      window.removeEventListener("apps-changed-silent", onChanged);
    };
  }, [refreshStats]);

  // Resolve the current session; greet new visitors once (until dismissed).
  useEffect(() => {
    api
      .me()
      .then((u) => {
        setUser(u);
        if (!u && !localStorage.getItem("authDismissed")) {
          setTimeout(() => setAuthOpen(true), 500);
        }
      })
      .catch(() => {
        if (!localStorage.getItem("authDismissed")) setTimeout(() => setAuthOpen(true), 500);
      });
  }, []);

  const onAuthClose = (open: boolean) => {
    setAuthOpen(open);
    if (!open) localStorage.setItem("authDismissed", "1");
  };

  const logout = async () => {
    await api.logout().catch(() => {});
    setUser(null);
  };

  const pipeline = stats.total
    ? "Pipeline - " +
      Object.entries(stats.by_status)
        .filter(([, n]) => n > 0)
        .map(([k, n]) => `${k}: ${n}`)
        .join("  ·  ")
    : "";

  return (
    <>
      <header>
        <div className="brand">
          <h1>
            Smart Job<span className="dot">.</span>Tracker
          </h1>
          <nav className="tabs">
            <button
              className={"tab" + (view === "shortlist" ? " active" : "")}
              onClick={() => setView("shortlist")}
            >
              Shortlist
            </button>
            <button
              className={"tab" + (view === "board" ? " active" : "")}
              onClick={() => setView("board")}
            >
              Applications {stats.total > 0 && <span className="tab-count">{stats.total}</span>}
            </button>
          </nav>
          {user ? (
            <button className="authbtn" onClick={logout} title={user.email}>
              {user.name} &middot; Log out
            </button>
          ) : (
            <button className="authbtn" onClick={() => setAuthOpen(true)}>
              Sign in
            </button>
          )}
        </div>
      </header>

      <main>
        {view === "board" && pipeline && <div className="pipeline">{pipeline}</div>}
        {view === "shortlist" ? <Shortlist user={user} /> : <Board />}
      </main>

      <footer>Smart Job Application Tracker</footer>

      <AuthModal
        open={authOpen}
        onOpenChange={onAuthClose}
        onAuthed={(u) => {
          setUser(u);
          refreshStats();
        }}
      />
    </>
  );
}
