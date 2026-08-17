import * as RCheckbox from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";

// Radix checkbox styled to the palette (point 16). Renders as a clickable label.
export function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="check">
      <RCheckbox.Root
        className="check-box"
        checked={checked}
        onCheckedChange={(v) => onChange(v === true)}
      >
        <RCheckbox.Indicator>
          <Check size={13} strokeWidth={3} />
        </RCheckbox.Indicator>
      </RCheckbox.Root>
      <span>{label}</span>
    </label>
  );
}
