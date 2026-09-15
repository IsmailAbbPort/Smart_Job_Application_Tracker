import { useEffect, useState } from "react";
import { Modal } from "../../components/Modal";
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
import { advancedCount, defaultFilters, type FilterState } from "./filterState";

const REMOTE_OPTS: Option[] = [
  { value: "", label: "Any" },
  { value: "true", label: "Remote only" },
  { value: "false", label: "Not remote" },
];
const LIMIT_OPTS: Option[] = ["10", "25", "50", "100"].map((v) => ({ value: v, label: v }));
const PERIOD_OPTS: Option[] = [
  { value: "year", label: "Per year" },
  { value: "month", label: "Per month" },
];
const TZ_OPTS: Option[] = TIMEZONES.map((t) => ({
  value: String(t.offset),
  label: tzLabel(t.offset),
}));

const ROLE_HELP =
  "Keep only jobs the classifier placed in these categories (e.g. Engineering, Data & ML). Leave empty to include every category.";
const MAX_OVER_HELP =
  "Drop jobs that require more than this many years above your experience. Leave empty to only rank (not hide) stretch roles.";

const pick = (opts: Option[], v: string) => opts.find((o) => o.value === v) ?? null;
const multi = (opts: Option[], vs: string[]) => opts.filter((o) => vs.includes(o.value));

// The whole filter set, edited as a draft in a popup. Nothing changes the shortlist
// until "Show results"; "Save as view" stores the draft as a named preset.
export function FiltersModal({
  open,
  onOpenChange,
  filters,
  onApply,
  onSaveView,
  languageOptions,
  cityOptions,
  countryOptions,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  filters: FilterState;
  onApply: (f: FilterState) => void;
  onSaveView: (name: string, f: FilterState) => Promise<void>;
  languageOptions: Option[];
  cityOptions: Option[];
  countryOptions: Option[];
}) {
  const [f, setF] = useState<FilterState>(filters);
  const [naming, setNaming] = useState(false);
  const [viewName, setViewName] = useState("");
  const [saveErr, setSaveErr] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setF(filters);
      setNaming(false);
      setViewName("");
      setSaveErr("");
    }
  }, [open, filters]);

  const set = <K extends keyof FilterState>(key: K, value: FilterState[K]) =>
    setF((prev) => ({ ...prev, [key]: value }));

  const saveView = async () => {
    const name = viewName.trim();
    if (!name) {
      setSaveErr("Give the view a name.");
      return;
    }
    setSaving(true);
    setSaveErr("");
    try {
      await onSaveView(name, f);
      onApply(f);
    } catch (e) {
      setSaveErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const count = advancedCount(f) + (f.remote ? 1 : 0);

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      maxWidth={760}
      title="Filters"
      sub={count ? `${count} active` : undefined}
    >
      <div className="modal-b scroll-themed">
        <div className="row3 filters-quick">
          <Select
            label="Remote"
            options={REMOTE_OPTS}
            value={pick(REMOTE_OPTS, f.remote)}
            isSearchable={false}
            onChange={(o) => set("remote", ((o as Option)?.value ?? "") as FilterState["remote"])}
          />
          <div className="field">
            <label htmlFor="years_exp">Your experience (years)</label>
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
          <Select
            label="Results"
            options={LIMIT_OPTS}
            value={pick(LIMIT_OPTS, f.limit)}
            isSearchable={false}
            onChange={(o) => set("limit", (o as Option)?.value ?? "25")}
          />
        </div>

        <div className="filter-grid">
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
              onChange={(o) =>
                set(
                  "cities",
                  (o as Option[]).map((x) => x.value),
                )
              }
            />
          </fieldset>

          <fieldset className="filter-group">
            <legend>Language and time zone</legend>
            <Select
              label="Job posting language"
              isClearable
              options={languageOptions}
              value={languageOptions.find((o) => o.value === f.language) ?? null}
              placeholder="Any language"
              onChange={(o) => set("language", (o as Option)?.value ?? "")}
            />
            <Select
              label="Languages you speak"
              isMulti
              options={KNOWN_LANGUAGE_OPTIONS}
              value={multi(KNOWN_LANGUAGE_OPTIONS, f.knownLangs)}
              placeholder="Any"
              onChange={(o) =>
                set(
                  "knownLangs",
                  (o as Option[]).map((x) => x.value),
                )
              }
            />
            <Select
              label="Preferred time zone"
              isClearable
              options={TZ_OPTS}
              value={f.tzOffset != null ? pick(TZ_OPTS, String(f.tzOffset)) : null}
              placeholder="Any time zone"
              onChange={(o) => set("tzOffset", o ? Number((o as Option).value) : null)}
            />
          </fieldset>

          <fieldset className="filter-group">
            <legend>Compensation and experience</legend>
            <div className="field">
              <label htmlFor="min_salary">Minimum salary</label>
              <div className="row2">
                <input
                  id="min_salary"
                  className="input"
                  type="number"
                  min={0}
                  value={f.minSalary}
                  placeholder="Any"
                  onChange={(e) => set("minSalary", e.target.value)}
                />
                <Select
                  options={CURRENCIES}
                  value={pick(CURRENCIES, f.currency)}
                  isSearchable={false}
                  aria-label="Currency"
                  onChange={(o) => set("currency", (o as Option)?.value ?? "")}
                />
              </div>
            </div>
            <Select
              label="Salary period"
              options={PERIOD_OPTS}
              value={pick(PERIOD_OPTS, f.period)}
              isSearchable={false}
              onChange={(o) => set("period", ((o as Option)?.value ?? "year") as "year" | "month")}
            />
            <div className="row2">
              <div className="field">
                <label htmlFor="max_gap">
                  Max years short
                  <HelpTip text={MAX_OVER_HELP} />
                </label>
                <input
                  id="max_gap"
                  className="input"
                  type="number"
                  min={0}
                  value={f.maxGap}
                  placeholder="Off"
                  onChange={(e) => set("maxGap", e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="max_age">Posted within (days)</label>
                <input
                  id="max_age"
                  className="input"
                  type="number"
                  min={1}
                  value={f.maxAge}
                  placeholder="Any"
                  onChange={(e) => set("maxAge", e.target.value)}
                />
              </div>
            </div>
            <Checkbox
              checked={f.requireSalary}
              onChange={(v) => set("requireSalary", v)}
              label="Only jobs with a listed salary"
            />
          </fieldset>

          <fieldset className="filter-group">
            <legend>Role and seniority</legend>
            <Select
              label="Role categories"
              help={ROLE_HELP}
              isMulti
              options={ROLE_FAMILIES}
              value={multi(ROLE_FAMILIES, f.roleFamilies)}
              placeholder="All categories"
              onChange={(o) =>
                set(
                  "roleFamilies",
                  (o as Option[]).map((x) => x.value),
                )
              }
            />
            <TagInput
              label="Exclude titles containing"
              values={f.exclTitles}
              onChange={(v) => set("exclTitles", v)}
              placeholder="e.g. sales, then Enter"
            />
            <Checkbox
              checked={f.hideSenior}
              onChange={(v) => set("hideSenior", v)}
              label="Hide senior and lead jobs"
            />
            <Checkbox
              checked={f.hideIntern}
              onChange={(v) => set("hideIntern", v)}
              label="Hide intern and student jobs"
            />
          </fieldset>
        </div>
        {saveErr && <div className="modal-msg err">{saveErr}</div>}
      </div>

      <div className="modal-f">
        {naming ? (
          <div className="save-view left">
            <input
              className="input"
              autoFocus
              placeholder="View name"
              value={viewName}
              onChange={(e) => setViewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveView();
                if (e.key === "Escape") {
                  e.stopPropagation();
                  setNaming(false);
                }
              }}
            />
            <button className="btn" onClick={saveView} disabled={saving}>
              {saving ? "Saving..." : "Save and apply"}
            </button>
            <button className="linkbtn" onClick={() => setNaming(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <div className="left" style={{ display: "flex", gap: 14 }}>
            <button className="linkbtn" onClick={() => setF(defaultFilters)}>
              Reset all
            </button>
            <button className="linkbtn" onClick={() => setNaming(true)}>
              Save as view
            </button>
          </div>
        )}
        <button className="btn hide-mobile" onClick={() => onOpenChange(false)}>
          Cancel
        </button>
        <button className="btn primary" onClick={() => onApply(f)}>
          Show results
        </button>
      </div>
    </Modal>
  );
}

// Language options are the corpus languages, shown with full names, ordered by
// frequency (most common first).
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
