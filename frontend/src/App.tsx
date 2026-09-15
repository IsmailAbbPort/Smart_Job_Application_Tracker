import { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { api } from "./api";
import { Shortlist } from "./features/shortlist/Shortlist";
import { Board } from "./features/board/Board";
import { AuthModal } from "./features/auth/AuthModal";
import { CvModal } from "./features/shortlist/CvModal";
import { Sidebar } from "./features/sidebar/Sidebar";
import { TabBar, type Tab } from "./features/sidebar/TabBar";
import { YouPage } from "./features/sidebar/YouPage";
import { useIsMobile } from "./hooks";
import { Modal } from "./components/Modal";
import { Tour, type TourStep } from "./components/Tour";
import {
  defaultFilters,
  loadStoredFilters,
  saveFilters,
  type FilterState,
} from "./features/shortlist/filterState";
import type { Cv, SavedView, Stats, User } from "./types";

type Theme = "light" | "dark";
const THEME_KEY = "sjt.colorScheme";
// localStorage, not sessionStorage: the tour should show once per browser, not
// again in every new tab.
const TOUR_KEY = "sjt.tourDone";

const TOUR_STEPS: TourStep[] = [
  {
    target: "cv",
    title: "Your CV drives the ranking",
    body: "Every role is scored by how closely it matches this CV. Switch between CVs, rename or replace one, or upload a new one here.",
  },
  {
    target: "filters",
    title: "Narrow the list",
    body: "Filter by remote, experience, location, language, salary and role type. Active filters show as chips next to this button.",
  },
  {
    target: "table",
    title: "Roles ranked for you",
    body: (
      <>
        Fit is how similar a role is to your CV, relative to the best match. Click a row, or use{" "}
        <ArrowUp size={13} className="inline-icon" aria-label="up arrow" /> and{" "}
        <ArrowDown size={13} className="inline-icon" aria-label="down arrow" />, to open it.
      </>
    ),
  },
  {
    target: "inspector",
    title: "Details, AI fit and cover letters",
    body: "Assess fit gives a 0-100 score with matched requirements and gaps. Draft cover letter writes a letter grounded only in your CV. Set the status to start tracking.",
  },
  {
    target: "rank",
    title: "Rank the top 10 with AI",
    body: "Scores the first ten roles in one go and reorders them by the AI score.",
  },
  {
    target: "applications",
    title: "Track your applications",
    body: "Everything you track lands on a board. Drag cards between stages, or add a job you found somewhere else.",
  },
  {
    target: "views",
    title: "Save filter sets",
    body: "Save a set of filters from the Filters popup and it appears here, one click to apply.",
  },
];

// The phone layout has no sidebar or side inspector, so its tour points at the
// header controls and the tab bar instead.
const MOBILE_TOUR_STEPS: TourStep[] = [
  {
    target: "cv",
    title: "Your CV drives the ranking",
    body: "Every role is scored by how closely it matches this CV. Tap to switch CVs.",
  },
  {
    target: "filters",
    title: "Narrow the list",
    body: "Filter by remote, experience, location, language, salary and role type.",
  },
  {
    target: "views",
    title: "Saved filter sets",
    body: "Views you save from Filters sit here, one tap to apply.",
  },
  {
    target: "table",
    title: "Roles ranked for you",
    body: "Fit is how similar a role is to your CV, relative to the best match. Tap a role for details, an AI fit score and a cover letter.",
  },
  {
    target: "rank",
    title: "Rank the top 10 with AI",
    body: "Scores the first ten roles in one go and reorders them by the AI score.",
  },
  {
    target: "applications",
    title: "Track your applications",
    body: "Everything you track lands here, one stage at a time. Hold a card and drag it onto a stage to move it.",
  },
  {
    target: "you",
    title: "CVs, views and settings",
    body: "Upload, edit or replace CVs, manage saved views, switch theme or replay this tour.",
  },
];

const sameFilters = (a: FilterState, b: FilterState) => JSON.stringify(a) === JSON.stringify(b);

export default function App() {
  const mobile = useIsMobile();
  const [view, setView] = useState<Tab>(
    new URLSearchParams(location.search).get("view") === "board" ? "board" : "shortlist",
  );
  const [user, setUser] = useState<User | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [stats, setStats] = useState<Stats>({ total: 0, by_status: {} });
  const [theme, setTheme] = useState<Theme>(() =>
    localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light",
  );

  const [cvs, setCvs] = useState<Cv[]>([]);
  const [cvId, setCvId] = useState("");
  const [cvsLoaded, setCvsLoaded] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const [filters, setFilters] = useState<FilterState>(loadStoredFilters);
  const [runToken, setRunToken] = useState(0);
  const [shortlistCount, setShortlistCount] = useState<number | null>(null);
  const [views, setViews] = useState<SavedView[]>([]);
  const [viewToDelete, setViewToDelete] = useState<SavedView | null>(null);
  const [notice, setNotice] = useState("");
  const [tourOpen, setTourOpen] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  // The You tab only exists on phones; widening the window falls back to the shortlist.
  useEffect(() => {
    if (!mobile && view === "you") setView("shortlist");
  }, [mobile, view]);

  // The open tab is shareable; nothing else (no record ids) goes in the URL.
  useEffect(() => {
    history.replaceState(null, "", view === "board" ? "/?view=board" : "/");
  }, [view]);

  const refreshStats = useCallback(async () => {
    try {
      setStats(await api.stats());
    } catch {
      /* keep last */
    }
  }, []);

  const loadCvs = useCallback(async () => {
    try {
      const list = await api.listCvs();
      setCvs(list);
      setCvId((cur) =>
        cur && list.some((c) => String(c.id) === cur) ? cur : list[0] ? String(list[0].id) : "",
      );
    } catch {
      setCvs([]);
    } finally {
      setCvsLoaded(true);
    }
  }, []);

  const loadViews = useCallback(async () => {
    try {
      setViews(await api.listViews());
    } catch {
      setViews([]);
    }
  }, []);

  // Everything scoped to the account reloads when the signed-in user changes.
  const reloadAccountData = useCallback(() => {
    refreshStats();
    loadViews();
    loadCvs().then(() => setRunToken((t) => t + 1));
  }, [refreshStats, loadViews, loadCvs]);

  useEffect(() => {
    refreshStats();
    loadViews();
    loadCvs();
    const onChanged = () => refreshStats();
    window.addEventListener("apps-changed", onChanged);
    window.addEventListener("apps-changed-silent", onChanged);
    return () => {
      window.removeEventListener("apps-changed", onChanged);
      window.removeEventListener("apps-changed-silent", onChanged);
    };
  }, [refreshStats, loadViews, loadCvs]);

  // Resolve the current session; greet new visitors once (until dismissed).
  useEffect(() => {
    api
      .me()
      .then((u) => {
        setUser(u);
        if (!u && !localStorage.getItem("authDismissed")) setTimeout(() => setAuthOpen(true), 500);
      })
      .catch(() => {
        if (!localStorage.getItem("authDismissed")) setTimeout(() => setAuthOpen(true), 500);
      })
      .finally(() => setTimeout(() => setAuthChecked(true), 600));
  }, []);

  // First visit: show the tour once the sign-in prompt is out of the way and the
  // shortlist has rendered (the steps point at real elements).
  useEffect(() => {
    if (!authChecked || authOpen || view !== "shortlist" || shortlistCount == null) return;
    if (localStorage.getItem(TOUR_KEY)) return;
    const t = setTimeout(() => setTourOpen(true), 400);
    return () => clearTimeout(t);
  }, [authChecked, authOpen, view, shortlistCount]);

  const startTour = () => {
    setView("shortlist");
    setTimeout(() => setTourOpen(true), 150);
  };

  const closeTour = useCallback(() => {
    setTourOpen(false);
    localStorage.setItem(TOUR_KEY, "1");
  }, []);

  const onAuthClose = (open: boolean) => {
    setAuthOpen(open);
    if (!open) localStorage.setItem("authDismissed", "1");
  };

  const logout = async () => {
    setConfirmLogout(false);
    await api.logout().catch(() => {});
    setUser(null);
    reloadAccountData();
  };

  const applyFilters = (f: FilterState) => {
    setFilters(f);
    saveFilters(f);
    setView("shortlist");
    setRunToken((t) => t + 1);
  };

  const applyView = (v: SavedView) =>
    applyFilters({ ...defaultFilters, ...(v.filters as Partial<FilterState>) });

  const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  const saveView = async (name: string, f: FilterState) => {
    const created = await api.createView({
      name,
      filters: f as unknown as Record<string, unknown>,
    });
    setViews((prev) => [created, ...prev]);
  };

  const deleteView = async () => {
    const target = viewToDelete;
    setViewToDelete(null);
    if (!target) return;
    setViews((prev) => prev.filter((v) => v.id !== target.id));
    api.deleteView(target.id).catch(() => loadViews());
  };

  const selectedCv = cvs.find((c) => String(c.id) === cvId) ?? null;

  const deleteSelectedCv = async () => {
    setConfirmDelete(false);
    if (!selectedCv) return;
    try {
      await api.deleteCv(selectedCv.id);
      setCvId("");
      await loadCvs();
    } catch (e) {
      setNotice("Could not delete CV: " + (e as Error).message);
    }
  };

  const activeView = views.find((v) =>
    sameFilters({ ...defaultFilters, ...(v.filters as Partial<FilterState>) }, filters),
  );

  return (
    <div className={"app" + (mobile ? " mobile" : view === "board" ? " no-inspector" : "")}>
      {!mobile && (
        <Sidebar
          view={view === "board" ? "board" : "shortlist"}
          onView={setView}
          stats={stats}
          shortlistCount={shortlistCount}
          views={views}
          activeViewId={activeView?.id ?? null}
          onApplyView={applyView}
          onDeleteView={setViewToDelete}
          cvs={cvs}
          cvId={cvId}
          onSelectCv={setCvId}
          onEditCv={() => setEditOpen(true)}
          onDeleteCv={() => setConfirmDelete(true)}
          onUploadCv={() => setUploadOpen(true)}
          user={user}
          onSignIn={() => setAuthOpen(true)}
          onLogout={() => setConfirmLogout(true)}
          theme={theme}
          onToggleTheme={toggleTheme}
          onTour={startTour}
        />
      )}

      {view === "board" ? (
        <Board cvId={cvId} />
      ) : view === "you" && mobile ? (
        <YouPage
          cvs={cvs}
          cvId={cvId}
          onSelectCv={setCvId}
          onEditCv={() => setEditOpen(true)}
          onDeleteCv={() => setConfirmDelete(true)}
          onUploadCv={() => setUploadOpen(true)}
          views={views}
          activeViewId={activeView?.id ?? null}
          onApplyView={applyView}
          onDeleteView={setViewToDelete}
          user={user}
          onSignIn={() => setAuthOpen(true)}
          onLogout={() => setConfirmLogout(true)}
          theme={theme}
          onToggleTheme={toggleTheme}
          onTour={startTour}
        />
      ) : (
        <Shortlist
          cvId={cvId}
          ready={cvsLoaded}
          filters={filters}
          onFiltersChange={applyFilters}
          runToken={runToken}
          onCount={setShortlistCount}
          onSaveView={saveView}
          cvs={cvs}
          onSelectCv={setCvId}
          onUploadCv={() => setUploadOpen(true)}
          views={views}
          activeViewId={activeView?.id ?? null}
          onApplyView={applyView}
        />
      )}

      {mobile && <TabBar view={view} onView={setView} appCount={stats.total} />}

      <Tour
        open={tourOpen}
        steps={
          mobile
            ? MOBILE_TOUR_STEPS.filter((s) => s.target !== "views" || views.length > 0)
            : TOUR_STEPS
        }
        onClose={closeTour}
      />

      <AuthModal
        open={authOpen}
        onOpenChange={onAuthClose}
        onAuthed={(u) => {
          setUser(u);
          reloadAccountData();
        }}
      />

      <CvModal
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        mode="upload"
        user={user}
        existingCount={cvs.length}
        onSaved={async (cv) => {
          await loadCvs();
          setCvId(String(cv.id));
        }}
      />
      <CvModal
        open={editOpen}
        onOpenChange={setEditOpen}
        mode="edit"
        cv={selectedCv}
        user={user}
        existingCount={cvs.length}
        onSaved={async (_cv, change) => {
          await loadCvs();
          if (change === "file") setRunToken((t) => t + 1);
        }}
      />

      <Modal open={confirmDelete} onOpenChange={setConfirmDelete} maxWidth={400} title="Delete CV?">
        <div className="modal-b">
          <p className="modal-text">
            {selectedCv && (
              <>
                <b>&ldquo;{selectedCv.label}&rdquo;</b> will be permanently removed. This
                can&rsquo;t be undone.
              </>
            )}
          </p>
        </div>
        <div className="modal-f">
          <button className="btn left" onClick={() => setConfirmDelete(false)}>
            Cancel
          </button>
          <button className="btn danger" onClick={deleteSelectedCv}>
            Delete CV
          </button>
        </div>
      </Modal>

      <Modal
        open={!!viewToDelete}
        onOpenChange={(o) => !o && setViewToDelete(null)}
        maxWidth={400}
        title="Delete saved view?"
      >
        <div className="modal-b">
          <p className="modal-text">
            <b>&ldquo;{viewToDelete?.name}&rdquo;</b> will be removed. Your current filters stay as
            they are.
          </p>
        </div>
        <div className="modal-f">
          <button className="btn left" onClick={() => setViewToDelete(null)}>
            Cancel
          </button>
          <button className="btn danger" onClick={deleteView}>
            Delete view
          </button>
        </div>
      </Modal>

      <Modal open={confirmLogout} onOpenChange={setConfirmLogout} maxWidth={380} title="Log out?">
        <div className="modal-b">
          <p className="modal-text">You&rsquo;ll need to sign back in to see your saved data.</p>
        </div>
        <div className="modal-f">
          <button className="btn left" onClick={() => setConfirmLogout(false)}>
            Cancel
          </button>
          <button className="btn primary" onClick={logout}>
            Log out
          </button>
        </div>
      </Modal>

      <Modal
        open={!!notice}
        onOpenChange={(o) => !o && setNotice("")}
        maxWidth={400}
        title="Something went wrong"
      >
        <div className="modal-b">
          <p className="modal-text">{notice}</p>
        </div>
        <div className="modal-f">
          <span className="spacer" />
          <button className="btn primary" onClick={() => setNotice("")}>
            OK
          </button>
        </div>
      </Modal>
    </div>
  );
}
