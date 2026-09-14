import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { FileText, UploadCloud } from "lucide-react";
import { Modal } from "../../components/Modal";

// pdf.js is heavy (~1 MB); load it only when a PDF preview is actually shown.
const PdfPreview = lazy(() =>
  import("../../components/PdfPreview").then((m) => ({ default: m.PdfPreview })),
);
import { api } from "../../api";
import { CV_ACCEPT, CV_LIMIT_HINT, CV_MAX_BYTES } from "../../constants";
import { fileToBase64, fmtBytes } from "../../format";
import type { Cv, User } from "../../types";

// Auto-name scheme: {Name|guest}-{YYYY-MM-DD}-{version}, where the version is
// blank for the first CV, then 1, 2, ... for each later one.
function autoLabel(user: User | null, existingCount: number): string {
  const who = user?.name?.trim() || "guest";
  const date = new Date().toISOString().slice(0, 10);
  const version = existingCount === 0 ? "" : `-${existingCount}`;
  return `${who}-${date}${version}`;
}

export function CvModal({
  open,
  onOpenChange,
  mode,
  cv,
  user,
  existingCount,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  mode: "upload" | "edit";
  cv?: Cv | null;
  user: User | null;
  existingCount: number;
  onSaved: (cv: Cv, change: "new" | "label" | "file") => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [label, setLabel] = useState("");
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setFile(null);
      setLabel(mode === "edit" ? (cv?.label ?? "") : "");
      setMsg("");
    }
  }, [open, mode, cv]);

  // Preview URL: the freshly-picked file, else the stored file (edit).
  const previewUrl = useMemo(() => {
    if (file) return URL.createObjectURL(file);
    if (mode === "edit" && cv?.filename) return api.cvFileUrl(cv.id);
    return null;
  }, [file, mode, cv]);
  useEffect(() => {
    return () => {
      if (file && previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [file, previewUrl]);

  const isPdf = file
    ? file.type === "application/pdf"
    : mode === "edit" &&
      (cv?.content_type === "application/pdf" || !!cv?.filename?.endsWith(".pdf"));

  const accept = (f: File | undefined) => {
    if (!f) return;
    if (f.size > CV_MAX_BYTES) {
      setMsg(`That file is ${fmtBytes(f.size)}. The limit is ${CV_LIMIT_HINT}.`);
      return;
    }
    setMsg("");
    setFile(f);
  };

  const placeholder = autoLabel(user, existingCount);

  const submit = async () => {
    setBusy(true);
    setMsg("");
    try {
      if (mode === "edit" && cv) {
        let saved = cv;
        let change: "label" | "file" = "label";
        const nextLabel = label.trim() || cv.label;
        if (nextLabel !== cv.label) saved = await api.updateCv(cv.id, { label: nextLabel });
        if (file) {
          saved = await api.replaceCvFile(cv.id, {
            filename: file.name,
            content_base64: await fileToBase64(file),
          });
          change = "file";
        }
        onSaved(saved, change);
        onOpenChange(false);
        return;
      }
      if (!file) {
        setMsg("Pick a CV file first.");
        return;
      }
      const saved = await api.uploadCv({
        label: label.trim() || placeholder,
        filename: file.name,
        content_base64: await fileToBase64(file),
      });
      onSaved(saved, "new");
      onOpenChange(false);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const dropzone = (
    <div
      className={"dropzone" + (drag ? " drag" : "") + (mode === "edit" ? " compact" : "")}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        accept(e.dataTransfer.files[0]);
      }}
    >
      {mode === "upload" && (
        <div className="dz-icon">
          <UploadCloud size={24} />
        </div>
      )}
      <div>
        {mode === "edit" ? "Replace the file: " : ""}
        <strong>Click to browse</strong> or drop a file here
      </div>
      <div className="dz-hint">{CV_LIMIT_HINT}</div>
      <input
        ref={inputRef}
        type="file"
        accept={CV_ACCEPT}
        hidden
        onChange={(e) => accept(e.target.files?.[0])}
      />
    </div>
  );

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      maxWidth={520}
      title={mode === "edit" ? "Edit CV" : "Upload a CV"}
    >
      <div className="modal-b scroll-themed">
        {mode === "upload" && dropzone}

        {file && (
          <div className="file-chip">
            <FileText size={16} />
            {file.name} <span className="subtle">({fmtBytes(file.size)})</span>
          </div>
        )}

        {previewUrl && isPdf && (
          <Suspense fallback={<div className="pdf-msg">Loading preview...</div>}>
            <PdfPreview url={previewUrl} />
          </Suspense>
        )}
        {previewUrl && !isPdf && (
          <div className="cv-textnote">
            <FileText size={16} /> Text CV, no visual preview.
          </div>
        )}

        {mode === "edit" && dropzone}
        {mode === "edit" && file && (
          <div className="subtle" style={{ marginTop: 6 }}>
            Replacing the file re-embeds the CV and clears its saved AI assessments and cover
            letters.
          </div>
        )}

        <div className="field" style={{ marginTop: 14 }}>
          <label htmlFor="cvlabel">Name</label>
          <input
            id="cvlabel"
            className="input"
            value={label}
            placeholder={mode === "edit" ? cv?.label : placeholder}
            onChange={(e) => setLabel(e.target.value)}
          />
          {mode === "upload" && (
            <span className="subtle">Leave blank to auto-name: {placeholder}</span>
          )}
        </div>

        {msg && <div className="modal-msg err">{msg}</div>}
      </div>
      <div className="modal-f">
        <button className="btn left" onClick={() => onOpenChange(false)} disabled={busy}>
          Cancel
        </button>
        <button className="btn primary" onClick={submit} disabled={busy}>
          {busy ? "Saving..." : mode === "edit" ? "Save changes" : "Upload and rank"}
        </button>
      </div>
    </Modal>
  );
}
