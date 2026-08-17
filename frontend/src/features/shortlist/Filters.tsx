import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
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
  onSubmit,
  submitting,
}: {
  f: FilterState;
  set: <K extends keyof FilterState>(key: K, value: FilterState[K]) => void;
  languageOptions: Option[];
  onSubmit: () => void;
  submitting: boolean;
}) {
  const [open, setOpen] = useState(false);
  const count = advancedCount(f);

  return (
    <div className="controls-card">
      {/* Quick filters: Remote / City / Results (point 2) */}
      <div className="toolbar">
        <div className="field" style={{ minWidth: 160 }}>
          <label>Remote</label>
          <Select
            options={REMOTE_OPTS}
            value={pick(REMOTE_OPTS, f.remote)}
            isSearchable={false}
            onChange={(o) => set("remote", ((o as Option)?.value ?? "") as FilterState["remote"])}
          />
        </div>
        <div className="field" style={{ minWidth: 170 }}>
          <label htmlFor="city">City</label>
          <input
            id="city"
            className="input"
            value={f.city}
            placeholder="e.g. Berlin"
            onChange={(e) => set("city", e.target.value)}
          />
        </div>
        <div className="field" style={{ minWidth: 120 }}>
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
                  <TagInput
                    label="Cities"
                    values={f.cities}
                    onChange={(v) => set("cities", v)}
                    placeholder="Type a city, press Enter"
                  />
                  <div className="field">
                    <label htmlFor="country">Country</label>
                    <input
                      id="country"
                      className="input"
                      value={f.country}
                      placeholder="e.g. Germany"
                      onChange={(e) => set("country", e.target.value)}
                    />
                  </div>
                  <Select
                    label="Region"
                    isClearable
                    options={REGIONS}
                    value={pick(REGIONS, f.region)}
                    placeholder="Any region"
                    onChange={(o) => set("region", (o as Option)?.value ?? "")}
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
                    label="Known Languages"
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
                    <div className="salary-row">
                      <div className="salary-field">
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
                      <div className="currency-field">
                        <Select
                          label="Currency"
                          options={CURRENCIES}
                          value={pick(CURRENCIES, f.currency)}
                          isSearchable={false}
                          onChange={(o) => set("currency", (o as Option)?.value ?? "")}
                        />
                      </div>
                      <div className="period-field">
                        <label style={{ fontSize: 12, color: "var(--muted)" }}>Period</label>
                        <Select
                          options={PERIOD_OPTS}
                          value={pick(PERIOD_OPTS, f.period)}
                          isSearchable={false}
                          onChange={(o) =>
                            set("period", ((o as Option)?.value ?? "year") as "year" | "month")
                          }
                        />
                      </div>
                    </div>
                  </div>
                  <div className="field">
                    <label htmlFor="years_exp">Your Experience (yrs)</label>
                    <input
                      id="years_exp"
                      className="input"
                      type="number"
                      min={0}
                      value={f.yearsExp}
                      placeholder="e.g. 3"
                      onChange={(e) => set("yearsExp", e.target.value)}
                    />
                  </div>
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

              <div className="filters-foot">
                <Checkbox
                  checked={f.ignorePrefs}
                  onChange={(v) => set("ignorePrefs", v)}
                  label="Ignore Saved Prefs"
                />
                <span className="subtle">Filters you set here are saved for next time.</span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// Language options are the corpus languages, shown with full names (points 8, 9).
export function buildLanguageOptions(langs: { code: string; count: number }[]): Option[] {
  return [...langs]
    .sort((a, b) => a.code.localeCompare(b.code))
    .map((l) => ({ value: l.code, label: `${languageName(l.code)} (${l.count})` }));
}
