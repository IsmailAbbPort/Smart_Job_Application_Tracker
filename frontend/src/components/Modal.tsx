import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

// Shared Radix dialog shell for the auth / CV upload / CV edit modals.
export function Modal({
  open,
  onOpenChange,
  title,
  children,
  maxWidth,
  anchorTop,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title?: ReactNode;
  children: ReactNode;
  maxWidth?: number;
  // Anchor to a fixed distance from the top (instead of vertical centering) so
  // modals of different heights start at the same level (point 17).
  anchorTop?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-backdrop" />
        <Dialog.Content
          className={"modal" + (anchorTop ? " modal-top" : "")}
          style={maxWidth ? { maxWidth } : undefined}
        >
          <Dialog.Close asChild>
            <button className="modal-x" aria-label="Close">
              <X size={20} />
            </button>
          </Dialog.Close>
          {title && <Dialog.Title asChild>{title}</Dialog.Title>}
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
