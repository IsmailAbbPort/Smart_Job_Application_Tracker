import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Shortlist } from "./features/shortlist/Shortlist";
import { Board } from "./features/board/Board";
import { AuthModal } from "./features/auth/AuthModal";
import { Modal } from "./components/Modal";
import { SegmentedToggle } from "./components/SegmentedToggle";
import { ThemeMenu, type ThemeOption } from "./components/ThemeMenu";
import type { Stats, User } from "./types";

type View = "shortlist" | "board";
type Theme = "dark" | "light";

// Dark is the default for new visitors; Light is the alternate scheme.
const THEMES: ThemeOption[] = [
  { value: "dark", label: "Dark", swatch: ["#0b0d12", "#6ea8fe"] },
  { value: "light", label: "Light", swatch: ["#ffffff", "#1f7a44"] },
];

export default function App() {
  const [view, setView] = useState<View>(
    new URLSearchParams(location.search).get("view") === "board" ? "board" : "shortlist",
  );
  const [user, setUser] = useState<User | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [stats, setStats] = useState<Stats>({ total: 0, by_status: {} });
  const [theme, setTheme] = useState<Theme>(() =>
    localStorage.getItem("sjt.theme") === "light" ? "light" : "dark",
  );

  // Apply + persist the colour scheme (data-theme drives the CSS variables). The
  // saved choice is restored on return for guests and signed-in users (point 2).
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("sjt.theme", theme);
  }, [theme]);

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
    setConfirmLogout(false);
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
          <SegmentedToggle
            className="tabs-seg"
            value={view}
            onChange={(v) => setView(v as View)}
            options={[
              { value: "shortlist", label: "Shortlist" },
              {
                value: "board",
                label: (
                  <>
                    Applications
                    {stats.total > 0 && <span className="seg-count">{stats.total}</span>}
                  </>
                ),
              },
            ]}
          />
          <div className="header-actions">
            <ThemeMenu value={theme} options={THEMES} onChange={(v) => setTheme(v as Theme)} />
            {user ? (
              <button className="authbtn" onClick={() => setConfirmLogout(true)} title={user.email}>
                {user.name} &middot; Log out
              </button>
            ) : (
              <button className="authbtn" onClick={() => setAuthOpen(true)}>
                Sign in
              </button>
            )}
          </div>
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

      <Modal
        open={confirmLogout}
        onOpenChange={setConfirmLogout}
        maxWidth={380}
        title={<h2>Log out?</h2>}
      >
        <p className="modal-text">You&rsquo;ll need to sign back in to see your saved data.</p>
        <div className="modal-actions">
          <button className="btn-ghost" onClick={() => setConfirmLogout(false)}>
            Cancel
          </button>
          <button className="btn-primary" onClick={logout}>
            Log out
          </button>
        </div>
      </Modal>
    </>
  );
}
