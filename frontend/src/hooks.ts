import { useEffect, useRef, useSyncExternalStore } from "react";

// Below this width the app switches to the phone layout (tab bar, full-screen pages).
const MOBILE_QUERY = "(max-width: 640px)";

const subscribeMobile = (cb: () => void) => {
  const mq = window.matchMedia(MOBILE_QUERY);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};

export const useIsMobile = () =>
  useSyncExternalStore(subscribeMobile, () => window.matchMedia(MOBILE_QUERY).matches);

// A full-screen layer (job page) takes a history entry while open, so the phone's
// back gesture closes it instead of leaving the app.
export function useBackToClose(open: boolean, onClose: () => void) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    history.pushState({ sjtLayer: true }, "");
    let popped = false;
    const onPop = () => {
      popped = true;
      closeRef.current();
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      if (!popped && history.state?.sjtLayer) history.back();
    };
  }, [open]);
}
