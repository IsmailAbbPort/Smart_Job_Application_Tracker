import { useEffect, useRef, useState } from "react";
import { Check, Palette } from "lucide-react";

export interface ThemeOption {
  value: string;
  label: string;
  swatch: string[]; // small preview colours
}

// Palette button that opens a small menu of colour schemes right beneath it.
export function ThemeMenu({
  value,
  options,
  onChange,
}: {
  value: string;
  options: ThemeOption[];
  onChange: (value: string) => void;
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

  return (
    <div className="theme-menu" ref={ref}>
      <button
        className="authbtn theme-btn"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        title="Colour scheme"
      >
        <Palette size={16} />
      </button>
      {open && (
        <div className="theme-menu-pop" role="menu">
          {options.map((o) => (
            <button
              key={o.value}
              role="menuitemradio"
              aria-checked={o.value === value}
              className={"theme-menu-item" + (o.value === value ? " active" : "")}
              onClick={() => {
                onChange(o.value);
                setOpen(false);
              }}
            >
              <span className="theme-swatch">
                {o.swatch.map((c, i) => (
                  <span key={i} style={{ background: c }} />
                ))}
              </span>
              <span className="theme-name">{o.label}</span>
              {o.value === value && <Check size={15} className="theme-check" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
