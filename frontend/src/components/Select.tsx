import ReactSelect, { type Props as SelectProps } from "react-select";
import { HelpTip } from "./HelpTip";

export interface Option {
  value: string;
  label: string;
}

// Every dropdown in the app funnels through here so they share one look and all
// get: type-to-search (built in), pills for multi (point 7), a wider arrow gutter
// (point 5), no native spinner. `unstyled` hands styling to theme.css via the
// classNamePrefix hooks (.rs__*).
type BaseProps = {
  label?: string;
  help?: string;
  id?: string;
} & SelectProps<Option, boolean>;

export function Select({ label, help, id, ...props }: BaseProps) {
  const control = (
    <ReactSelect<Option, boolean>
      classNamePrefix="rs"
      className="rs-container"
      unstyled
      inputId={id}
      placeholder={props.placeholder ?? "Select..."}
      noOptionsMessage={() => "No matches"}
      {...props}
    />
  );
  if (!label) return control;
  return (
    <div className="field">
      <label htmlFor={id}>
        {label}
        {help && <HelpTip text={help} />}
      </label>
      {control}
    </div>
  );
}
