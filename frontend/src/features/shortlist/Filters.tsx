import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, RotateCcw } from "lucide-react";
import { Select, type Option } from "../../components/Select";
import { Checkbox } from "../../components/Checkbox";
import { TagInput } from "../../components/TagInput";
import { HelpTip } from "../../components/HelpTip";
import {
  CURRENCIES,
  KNOWN_LANGUAGE_OPTIONS,
  REGIONS,
  ROLE_FAMILIES,
  TIMEZONES,
  languageName,
  tzLabel,
} from "../../constants";
import { advancedCount, type FilterState } from "./filterState";

const REMOTE_OPTS: Option[] = [
  { value: "", label: "Any" },
  { value: "true", label: "Remote only" },
  { value: "false", label: "Not remote" },
];
const LIMIT_OPTS: Option[] = ["10", "25", "50", "100"].map((v) => ({ value: v, label: v }));
const PERIOD_OPTS: Option[] = [
  { value: "year", label: "/yr" },
  { value: "month", label: "/mo" },
];
const TZ_OPTS: Option[] = TIMEZONES.map((t) => ({ value: String(t.offset), label: tzLabel(t.offset) }));

const ROLE_HELP =
  "Keep only jobs the classifier placed in these categories (e.g. Engineering, Data & ML). Leave empty to include every category.";
const MAX_OVER_HELP =
  "Drop jobs that require more than this many years above your experience. Leave empty to only rank (not hide) stretch roles.";

const pick = (opts: Option[], v: string) => opts.find((o) => o.value === v) ?? null;
const multi = (opts: Option[], vs: string[]) => opts.filter((o) => vs.includes(o.value));

export function Filters({
  f,
  set,
  languageOptions,
  cityOptions,
  countryOptions,
  onSubmit,
  onReset,
  submitting,
}: {
  f: FilterState;
  set: <K extends keyof FilterState>(key: K, value: FilterState[K]) => void;
  languageOptions: Option[];
  cityOptions: Option[];
  countryOptions: Option[];
  onSubmit: () => void;
  onReset: () => void;
  submitting: boolean;
}) {
  const [open, setOpen] = useState(false);
  const count = advancedCount(f);

  return (
    <div className="controls-card">
      {/* Quick filters: Remote / Your Experience / Results (points 1, 2) */}
      <div className="toolbar">
        <div className="field" style={{ width: 152, minWidth: 152, flex: "none" }}>
          <label>Remote</label>
          <Select
            options={REMOTE_OPTS}
            value={pick(REMOTE_OPTS, f.remote)}
            isSearchable={false}
            onChange={(o) => set("remote", ((o as Option)?.value ?? "") as FilterState["remote"])}
          />
        </div>
        <div className="field" style={{ width: 152, minWidth: 152, flex: "none" }}>
          <label htmlFor="years_exp_quick">Your Experience (yrs)</label>
          <input
            id="years_exp_quick"
            className="input"
            type="number"
            min={0}
            value={f.yearsExp}
            placeholder="e.g. 3"
            onChange={(e) => set("yearsExp", e.target.value)}
          />
        </div>
        <div className="field" style={{ width: 114, minWidth: 114, flex: "none" }}>
          <label>Results</label>
          <Select
            options={LIMIT_OPTS}
            value={pick(LIMIT_OPTS, f.limit)}
            isSearchable={false}
            onChange={(o) => set("limit", (o as Option)?.value ?? "25")}
          />
        </div>
        <button
          type="button"
          className={"filters-toggle" + (open ? " open" : "")}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          Filters {count > 0 && <span className="count-chip">{count}</span>}
          <span className="chev">
            <ChevronDown size={14} />
          </span>
        </button>
        <button type="button" className="filters-toggle" onClick={onReset} title="Reset all filters">
          <RotateCcw size={14} /> Reset
        </button>
        <div className="spacer" />
        <button type="button" className="btn-primary" onClick={onSubmit} disabled={submitting}>
          Shortlist
        </button>
      </div>

      {/* Advanced filters, inside the same card (point 3) */}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            style={{ overflow: "hidden" }}
          >
            <div className="filters-panel">
              <div className="filter-grid">
                {/* Location */}
                <fieldset className="filter-group">
                  <legend>Location</legend>
                  <Select
                    label="Region"
                    isClearable
                    options={REGIONS}
                    value={pick(REGIONS, f.region)}
                    placeholder="Any region"
                    onChange={(o) => set("region", (o as Option)?.value ?? "")}
                  />
                  <Select
                    label="Country"
                    isClearable
                    options={countryOptions}
                    value={
                      countryOptions.find((o) => o.value === f.country) ??
                      (f.country ? { value: f.country, label: f.country } : null)
                    }
                    placeholder="Any country"
                    onChange={(o) => set("country", (o as Option)?.value ?? "")}
                  />
                  <Select
                    label="Cities"
                    isMulti
                    options={cityOptions}
                    value={f.cities.map(
                      (c) => cityOptions.find((o) => o.value === c) ?? { value: c, label: c },
                    )}
                    placeholder="Any city"
                    onChange={(o) => set("cities", (o as Option[]).map((x) => x.value))}
                  />
                </fieldset>

                {/* Language & timezone */}
                <fieldset className="filter-group">
                  <legend>Language &amp; timezone</legend>
                  <Select
                    label="Job Posting Language"
                    isClearable
                    options={languageOptions}
                    value={languageOptions.find((o) => o.value === f.language) ?? null}
                    placeholder="Any language"
                    onChange={(o) => set("language", (o as Option)?.value ?? "")}
                  />
                  <Select
                    label="Languages You Speak"
                    isMulti
                    options={KNOWN_LANGUAGE_OPTIONS}
                    value={multi(KNOWN_LANGUAGE_OPTIONS, f.knownLangs)}
                    placeholder="Languages you speak"
                    onChange={(o) => set("knownLangs", (o as Option[]).map((x) => x.value))}
                  />
                  <Select
                    label="Preferred Time Zone"
                    isClearable
                    options={TZ_OPTS}
                    value={f.tzOffset != null ? pick(TZ_OPTS, String(f.tzOffset)) : null}
                    placeholder="Select a time zone"
                    onChange={(o) =>
                      set("tzOffset", o ? Number((o as Option).value) : null)
                    }
                  />
                </fieldset>

                {/* Compensation & experience */}
                <fieldset className="filter-group">
                  <legend>Compensation &amp; experience</legend>
                  <div className="field">
                    <label htmlFor="min_salary">Min Salary</label>
                    <input
                      id="min_salary"
                      className="input"
                      type="number"
                      min={0}
                      value={f.minSalary}
                      placeholder="any"
                      onChange={(e) => set("minSalary", e.target.value)}
                    />
                  </div>
                  <Select
                    label="Currency"
                    options={CURRENCIES}
                    value={pick(CURRENCIES, f.currency)}
                    isSearchable={false}
                    onChange={(o) => set("currency", (o as Option)?.value ?? "")}
                  />
                  <Select
                    label="Period"
                    options={PERIOD_OPTS}
                    value={pick(PERIOD_OPTS, f.period)}
                    isSearchable={false}
                    onChange={(o) => set("period", ((o as Option)?.value ?? "year") as "year" | "month")}
                  />
                  <div className="field">
                    <label htmlFor="max_gap">
                      Max Years Above Experience
                      <HelpTip text={MAX_OVER_HELP} />
                    </label>
                    <input
                      id="max_gap"
                      className="input"
                      type="number"
                      min={0}
                      value={f.maxGap}
                      placeholder="off"
                      onChange={(e) => set("maxGap", e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="max_age">Posted Within (days)</label>
                    <input
                      id="max_age"
                      className="input"
                      type="number"
                      min={1}
                      value={f.maxAge}
                      placeholder="any"
                      onChange={(e) => set("maxAge", e.target.value)}
                    />
                  </div>
                  <div className="checks-stack">
                    <Checkbox
                      checked={f.requireSalary}
                      onChange={(v) => set("requireSalary", v)}
                      label="Salary Listed Only"
                    />
                  </div>
                </fieldset>

                {/* Role & seniority */}
                <fieldset className="filter-group">
                  <legend>Role &amp; seniority</legend>
                  <Select
                    label="Role Categories"
                    help={ROLE_HELP}
                    isMulti
                    options={ROLE_FAMILIES}
                    value={multi(ROLE_FAMILIES, f.roleFamilies)}
                    placeholder="All categories"
                    onChange={(o) => set("roleFamilies", (o as Option[]).map((x) => x.value))}
                  />
                  <TagInput
                    label="Exclude Titles"
                    values={f.exclTitles}
                    onChange={(v) => set("exclTitles", v)}
                    placeholder="e.g. sales, then Enter"
                  />
                  <div className="checks-stack">
                    <Checkbox
                      checked={f.hideSenior}
                      onChange={(v) => set("hideSenior", v)}
                      label="Hide Senior/Lead Jobs"
                    />
                    <Checkbox
                      checked={f.hideIntern}
                      onChange={(v) => set("hideIntern", v)}
                      label="Hide Intern/Student Jobs"
                    />
                  </div>
                </fieldset>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// Language options are the corpus languages, shown with full names, ordered by
// frequency (most common first, point 4).
export function buildLanguageOptions(langs: { code: string; count: number }[]): Option[] {
  return [...langs]
    .sort((a, b) => b.count - a.count)
    .map((l) => ({ value: l.code, label: `${languageName(l.code)} (${l.count})` }));
}

// Corpus cities/countries -> options, most common first, value = the raw name.
export function buildNameOptions(rows: { name: string; count: number }[]): Option[] {
  return [...rows]
    .sort((a, b) => b.count - a.count)
    .map((r) => ({ value: r.name, label: `${r.name} (${r.count})` }));
}
