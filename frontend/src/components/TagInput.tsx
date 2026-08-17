import { useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import { HelpTip } from "./HelpTip";

// Free-text field where each entry becomes a pill on Enter (point 4: Exclude
// Titles). Mirrors the react-select multi pill look/behaviour, but for arbitrary
// typed values rather than a fixed option list.
export function TagInput({
  label,
  help,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  help?: string;
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const v = draft.trim().toLowerCase();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  };
  const remove = (v: string) => onChange(values.filter((x) => x !== v));
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !draft && values.length) {
      remove(values[values.length - 1]);
    }
  };

  return (
    <div className="field">
      <label>
        {label}
        {help && <HelpTip text={help} />}
      </label>
      <input
        className="input"
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={add}
      />
      {values.length > 0 && (
        <div className="pill-row">
          {values.map((v) => (
            <span className="pill" key={v}>
              {v}
              <button
                type="button"
                className="pill-x"
                aria-label={`Remove ${v}`}
                onClick={() => remove(v)}
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
