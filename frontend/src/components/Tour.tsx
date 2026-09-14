import { useCallback, useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export interface TourStep {
  // Matches an element's data-tour attribute.
  target: string;
  title: string;
  body: ReactNode;
}

const CARD_W = 320;
const GAP = 12;
const PAD = 6;

type Rect = { top: number; left: number; width: number; height: number };

const find = (target: string) => document.querySelector<HTMLElement>(`[data-tour="${target}"]`);

// The element's VISIBLE box: clipped by every scrolling ancestor and the viewport,
// so a table wider or taller than its scroll area isn't outlined past its edges.
function measure(target: string): Rect | null {
  const el = find(target);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  let top = r.top;
  let left = r.left;
  let right = r.right;
  let bottom = r.bottom;
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const { overflowX, overflowY } = getComputedStyle(p);
    if (overflowX === "visible" && overflowY === "visible") continue;
    const pr = p.getBoundingClientRect();
    top = Math.max(top, pr.top);
    left = Math.max(left, pr.left);
    right = Math.min(right, pr.right);
    bottom = Math.min(bottom, pr.bottom);
  }
  top = Math.max(top, 0);
  left = Math.max(left, 0);
  right = Math.min(right, window.innerWidth);
  bottom = Math.min(bottom, window.innerHeight);
  if (right - left < 1 || bottom - top < 1) return null;
  // Pad outward, but keep the outline on screen.
  const pt = Math.max(0, Math.min(PAD, top - 2));
  const pl = Math.max(0, Math.min(PAD, left - 2));
  const pr = Math.max(0, Math.min(PAD, window.innerWidth - right - 2));
  const pb = Math.max(0, Math.min(PAD, window.innerHeight - bottom - 2));
  return {
    top: top - pt,
    left: left - pl,
    width: right - left + pl + pr,
    height: bottom - top + pt + pb,
  };
}

// Place the card beside the highlighted element: right if it fits, else left,
// else below; always clamped inside the viewport.
function cardPosition(r: Rect | null, cardH: number): { top: number; left: number } {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!r) return { top: vh / 2 - cardH / 2, left: vw / 2 - CARD_W / 2 };
  let left: number;
  let top = r.top;
  if (r.left + r.width + GAP + CARD_W <= vw - 16) left = r.left + r.width + GAP;
  else if (r.left - GAP - CARD_W >= 16) left = r.left - GAP - CARD_W;
  else {
    left = r.left;
    top = r.top + r.height + GAP;
  }
  left = Math.min(Math.max(16, left), vw - CARD_W - 16);
  top = Math.min(Math.max(16, top), vh - cardH - 16);
  return { top, left };
}

// Lightweight guided tour: dims the page, spotlights one element per step.
export function Tour({
  open,
  steps,
  onClose,
}: {
  open: boolean;
  steps: TourStep[];
  onClose: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [cardH, setCardH] = useState(180);
  const [card, setCard] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    if (open) setIndex(0);
  }, [open]);

  const step = steps[index];

  const update = useCallback(() => {
    if (step) setRect(measure(step.target));
  }, [step]);

  // Track the target live: window resizes, any scroll, and the element (or the
  // page layout) changing size, e.g. a panel filling in after a fetch.
  useLayoutEffect(() => {
    if (!open || !step) return;
    find(step.target)?.scrollIntoView({ block: "nearest" });
    update();
    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    };
    const ro = new ResizeObserver(schedule);
    const el = find(step.target);
    if (el) ro.observe(el);
    ro.observe(document.body);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
    };
  }, [open, step, update]);

  useLayoutEffect(() => {
    if (card) setCardH(card.offsetHeight);
  }, [card, index]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setIndex((i) => Math.min(steps.length - 1, i + 1));
      if (e.key === "ArrowLeft") setIndex((i) => Math.max(0, i - 1));
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onClose, steps.length]);

  if (!open || !step) return null;
  const last = index === steps.length - 1;
  const pos = cardPosition(rect, cardH);

  return createPortal(
    <div className="tour" role="dialog" aria-modal="true" aria-label="Product tour">
      <div className="tour-block" />
      {rect ? <div className="tour-spot" style={rect} /> : <div className="tour-dim" />}
      <div
        className="tour-card"
        ref={setCard}
        style={{ top: pos.top, left: pos.left, width: CARD_W }}
      >
        <div className="tour-step num">
          {index + 1} of {steps.length}
        </div>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        <div className="tour-actions">
          <button className="linkbtn" onClick={onClose}>
            Skip tour
          </button>
          <span className="spacer" />
          {index > 0 && (
            <button className="btn" onClick={() => setIndex(index - 1)}>
              Back
            </button>
          )}
          <button
            className="btn primary"
            autoFocus
            onClick={() => (last ? onClose() : setIndex(index + 1))}
          >
            {last ? "Done" : "Next"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
