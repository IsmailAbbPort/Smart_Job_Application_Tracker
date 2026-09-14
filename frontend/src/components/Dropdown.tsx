import { useEffect, useRef, useState, type ReactNode } from "react";

// Button + popover menu that closes on outside click or Escape. Used for the
// export menu and the CV switcher.
export function Dropdown({
  trigger,
  placement = "down",
  className,
  children,
}: {
  trigger: (p: { open: boolean; toggle: () => void }) => ReactNode;
  placement?: "down" | "up";
  className?: string;
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const close = () => setOpen(false);

  return (
    <div className={"menu-wrap" + (className ? " " + className : "")} ref={ref}>
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && (
        <div className={"menu " + placement} role="menu">
          {children(close)}
        </div>
      )}
    </div>
  );
}
