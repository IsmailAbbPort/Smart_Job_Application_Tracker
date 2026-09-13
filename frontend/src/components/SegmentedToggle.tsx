import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { motion } from "framer-motion";

export interface SegOption {
  value: string;
  label: ReactNode;
}

// Sliding-pill segmented toggle shared by the auth modal (Sign up / Log in) and
// the header tabs (Shortlist / Applications). A framer-motion slider animates
// between segments; the hover highlight sits beneath it and the label above
// (see the .seg styles in theme.css).
//
// The slider tracks each segment's MEASURED geometry rather than assuming equal
// halves: the header segments are content-width (e.g. "Applications" + a count
// badge is wider than "Shortlist"), so a percentage slider would sit off-centre
// and let the badge spill out. A ResizeObserver re-measures when the active
// segment grows/shrinks (badge appears) or the container reflows.
export function SegmentedToggle({
  options,
  value,
  onChange,
  className,
}: {
  options: SegOption[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const btnRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [pill, setPill] = useState<{ left: number; width: number }>({ left: 0, width: 0 });

  const index = Math.max(
    0,
    options.findIndex((o) => o.value === value),
  );

  useLayoutEffect(() => {
    const measure = () => {
      const el = btnRefs.current[index];
      if (el) setPill({ left: el.offsetLeft, width: el.offsetWidth });
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (containerRef.current) ro.observe(containerRef.current);
    btnRefs.current.forEach((b) => b && ro.observe(b));
    return () => ro.disconnect();
  }, [index, options]);

  return (
    <div ref={containerRef} className={"seg" + (className ? " " + className : "")} role="tablist">
      <motion.div
        className="seg-slider"
        initial={false}
        animate={{ left: pill.left, width: pill.width }}
        transition={{ type: "spring", stiffness: 500, damping: 38 }}
      />
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => {
            btnRefs.current[i] = el;
          }}
          type="button"
          role="tab"
          aria-selected={o.value === value}
          className={"seg-btn" + (o.value === value ? " active" : "")}
          onClick={() => onChange(o.value)}
        >
          <span className="seg-label">{o.label}</span>
        </button>
      ))}
    </div>
  );
}
