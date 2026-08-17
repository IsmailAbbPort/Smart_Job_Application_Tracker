import * as Tooltip from "@radix-ui/react-tooltip";
import { HelpCircle } from "lucide-react";

// The "?" in a circle used next to filter labels (points 4, 14). Hover/focus
// reveals the explanation.
export function HelpTip({ text }: { text: string }) {
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <span className="help-icon" tabIndex={0} aria-label={text}>
            <HelpCircle size={14} />
          </span>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content className="tooltip-content" sideOffset={6}>
            {text}
            <Tooltip.Arrow className="tooltip-arrow" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
