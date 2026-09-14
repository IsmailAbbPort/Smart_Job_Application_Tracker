import { useEffect, useState } from "react";
import { api } from "../../api";
import { Checkbox } from "../../components/Checkbox";
import { Modal } from "../../components/Modal";
import { Select, type Option } from "../../components/Select";
import { STAGES } from "../../constants";
import type { Application, Status } from "../../types";

const STATUS_OPTS: Option[] = STAGES.map((s) => ({ value: s.key, label: s.label }));

// Track a job that isn't in the ingested corpus (a referral, a company site, ...).
// Pasting the description lets the AI judge and cover letter work on it too.
export function AddApplicationModal({
  open,
  onOpenChange,
  initialStatus,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  initialStatus: string;
  onAdded: (app: Application) => void;
}) {
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [url, setUrl] = useState("");
  const [location, setLocation] = useState("");
  const [remote, setRemote] = useState(false);
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<string>(initialStatus);
  const [errs, setErrs] = useState<{ title?: string; company?: string; form?: string }>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setTitle("");
      setCompany("");
      setUrl("");
      setLocation("");
      setRemote(false);
      setDescription("");
      setStatus(initialStatus);
      setErrs({});
    }
  }, [open, initialStatus]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const next: typeof errs = {};
    if (!title.trim()) next.title = "Enter the job title";
    if (!company.trim()) next.company = "Enter the company";
    setErrs(next);
    if (Object.keys(next).length) return;
    setBusy(true);
    try {
      const app = await api.addManualApplication({
        title: title.trim(),
        company: company.trim(),
        url: url.trim(),
        location: location.trim() || null,
        description: description.trim(),
        is_remote: remote,
        status: status as Status,
      });
      onAdded(app);
      onOpenChange(false);
    } catch (err) {
      setErrs({ form: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} maxWidth={520} title="Add application">
      <form onSubmit={submit} noValidate style={{ display: "contents" }}>
        <div className="modal-b scroll-themed stack">
          <div className="row2">
            <div className="field">
              <label htmlFor="app_title">Job title</label>
              <input
                id="app_title"
                className="input"
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                aria-invalid={!!errs.title}
              />
              {errs.title && <div className="field-error">{errs.title}</div>}
            </div>
            <div className="field">
              <label htmlFor="app_company">Company</label>
              <input
                id="app_company"
                className="input"
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                aria-invalid={!!errs.company}
              />
              {errs.company && <div className="field-error">{errs.company}</div>}
            </div>
          </div>
          <div className="field">
            <label htmlFor="app_url">Posting link (optional)</label>
            <input
              id="app_url"
              className="input"
              type="url"
              placeholder="https://"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          <div className="row2">
            <div className="field">
              <label htmlFor="app_loc">Location (optional)</label>
              <input
                id="app_loc"
                className="input"
                placeholder="e.g. Berlin, Germany"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
            </div>
            <Select
              label="Stage"
              options={STATUS_OPTS}
              value={STATUS_OPTS.find((o) => o.value === status) ?? STATUS_OPTS[0]}
              isSearchable={false}
              onChange={(o) => setStatus((o as Option)?.value ?? "saved")}
            />
          </div>
          <Checkbox checked={remote} onChange={setRemote} label="Remote role" />
          <div className="field">
            <label htmlFor="app_desc">Job description (optional)</label>
            <textarea
              id="app_desc"
              className="input"
              rows={5}
              placeholder="Paste the posting so the AI can assess fit and draft a cover letter"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          {errs.form && <div className="modal-msg err">{errs.form}</div>}
        </div>
        <div className="modal-f">
          <button
            type="button"
            className="btn left"
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? "Adding..." : "Add application"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
