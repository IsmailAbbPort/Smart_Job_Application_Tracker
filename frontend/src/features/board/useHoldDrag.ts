import { useCallback, useEffect, useRef, useState } from "react";

const HOLD_MS = 350;
// Moving further than this before the hold completes means the user is scrolling.
const SLOP_PX = 8;

export interface HoldDrag {
  jobId: number;
  x: number;
  y: number;
  offsetX: number;
  offsetY: number;
  width: number;
  over: string | null;
}

// Touch drag and drop for the phone board. HTML5 drag events don't fire on touch,
// so a card is lifted by holding it, then follows the finger until it's dropped
// on an element carrying data-drop-stage.
export function useHoldDrag(onDrop: (jobId: number, stage: string) => void) {
  const [drag, setDrag] = useState<HoldDrag | null>(null);
  const dropRef = useRef(onDrop);
  dropRef.current = onDrop;
  const stop = useRef<(() => void) | null>(null);
  const dragged = useRef(false);

  useEffect(() => () => stop.current?.(), []);

  const start = useCallback(
    (jobId: number, el: HTMLElement, x0: number, y0: number, touch: boolean) => {
      stop.current?.();
      let lifted = false;
      let over: string | null = null;

      const timer = window.setTimeout(() => {
        lifted = true;
        dragged.current = true;
        const r = el.getBoundingClientRect();
        navigator.vibrate?.(10);
        setDrag({
          jobId,
          x: x0,
          y: y0,
          offsetX: x0 - r.left,
          offsetY: y0 - r.top,
          width: r.width,
          over: null,
        });
      }, HOLD_MS);

      const move = (x: number, y: number, e: Event) => {
        if (!lifted) {
          if (Math.hypot(x - x0, y - y0) > SLOP_PX) end(false);
          return;
        }
        e.preventDefault();
        const target = document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-drop-stage]");
        over = target?.dataset.dropStage ?? null;
        setDrag((d) => d && { ...d, x, y, over });
      };

      const onTouchMove = (e: TouchEvent) => move(e.touches[0].clientX, e.touches[0].clientY, e);
      const onMouseMove = (e: MouseEvent) => move(e.clientX, e.clientY, e);
      const onEnd = () => end(true);
      const onCancel = () => end(false);

      function end(commit: boolean) {
        window.clearTimeout(timer);
        window.removeEventListener("touchmove", onTouchMove);
        window.removeEventListener("touchend", onEnd);
        window.removeEventListener("touchcancel", onCancel);
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onEnd);
        stop.current = null;
        if (!lifted) return;
        window.setTimeout(() => (dragged.current = false), 400);
        setDrag(null);
        if (commit && over) dropRef.current(jobId, over);
      }

      if (touch) {
        // Non-passive so a lifted card can cancel the page scroll.
        window.addEventListener("touchmove", onTouchMove, { passive: false });
        window.addEventListener("touchend", onEnd);
        window.addEventListener("touchcancel", onCancel);
      } else {
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onEnd);
      }
      stop.current = () => end(false);
    },
    [],
  );

  // The click that follows a drop must not also open the card.
  const consumeClick = useCallback(() => {
    const was = dragged.current;
    dragged.current = false;
    return was;
  }, []);

  return { drag, start, consumeClick };
}
