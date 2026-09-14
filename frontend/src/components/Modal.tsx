import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { createContext, useState, type ReactNode } from "react";

// Radix blocks pointer events outside the open dialog, so popovers (react-select
// menus) must portal INTO the dialog content rather than to <body>.
export const PortalTargetContext = createContext<HTMLElement | null>(null);

// Shared Radix dialog shell. Children render below the header; wrap content in
// .modal-b (scrolling body) and actions in .modal-f (footer bar).
export function Modal({
  open,
  onOpenChange,
  title,
  sub,
  children,
  maxWidth,
  anchorTop,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: ReactNode;
  sub?: ReactNode;
  children: ReactNode;
  maxWidth?: number;
  // Anchor to a fixed distance from the top (instead of vertical centering) so
  // modals whose height changes (auth sign up / log in) don't jump.
  anchorTop?: boolean;
}) {
  const [content, setContent] = useState<HTMLDivElement | null>(null);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-backdrop" />
        <Dialog.Content
          ref={setContent}
          className={"modal" + (anchorTop ? " modal-top" : "")}
          style={maxWidth ? { maxWidth } : undefined}
          aria-describedby={undefined}
        >
          <div className="modal-h">
            <Dialog.Title asChild>
              <h2>{title}</h2>
            </Dialog.Title>
            {sub && <span className="sub">{sub}</span>}
            <Dialog.Close asChild>
              <button className="iconbtn bare modal-x" aria-label="Close">
                <X size={16} />
              </button>
            </Dialog.Close>
          </div>
          <PortalTargetContext.Provider value={content}>{children}</PortalTargetContext.Provider>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
