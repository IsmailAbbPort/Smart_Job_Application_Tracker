import { CircleUser, Columns3, Rows3 } from "lucide-react";
import type { View } from "./Sidebar";

export type Tab = View | "you";

const TABS: { key: Tab; label: string; icon: typeof Rows3; tour?: string }[] = [
  { key: "shortlist", label: "Shortlist", icon: Rows3 },
  { key: "board", label: "Applications", icon: Columns3, tour: "applications" },
  { key: "you", label: "You", icon: CircleUser, tour: "you" },
];

// Phone navigation: the sidebar's nav, pinned to the bottom within thumb reach.
export function TabBar({
  view,
  onView,
  appCount,
}: {
  view: Tab;
  onView: (v: Tab) => void;
  appCount: number;
}) {
  return (
    <nav className="tabbar" aria-label="Main">
      {TABS.map(({ key, label, icon: Icon, tour }) => (
        <button
          key={key}
          className={"tab" + (view === key ? " on" : "")}
          aria-current={view === key ? "page" : undefined}
          onClick={() => onView(key)}
          data-tour={tour}
        >
          <Icon size={20} strokeWidth={1.75} />
          {label}
          {key === "board" && appCount > 0 && <span className="badge num">{appCount}</span>}
        </button>
      ))}
    </nav>
  );
}
