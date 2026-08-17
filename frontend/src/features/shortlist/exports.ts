import { fmtSalary, locationText } from "../../format";
import type { Job } from "../../types";

function downloadFile(name: string, text: string, type: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function exportCsv(items: Job[], cvId: number) {
  const cols = [
    "rank", "id", "title", "company", "location", "url", "similarity", "source",
    "language", "salary_min", "salary_max", "salary_currency", "min_years_experience",
    "remote_region", "visa_sponsorship", "timezone_overlap_hours", "posted_at", "application_status",
  ];
  const cell = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const rows = items.map((j, i) =>
    [
      i + 1, j.id, j.title, j.company, locationText(j), j.url, j.similarity, j.source,
      j.language, j.salary_min, j.salary_max, j.salary_currency, j.min_years_experience,
      j.remote_region, j.visa_sponsorship, j.timezone_overlap_hours, j.posted_at, j.application_status,
    ].map(cell).join(","),
  );
  downloadFile(`shortlist-cv${cvId}.csv`, [cols.join(","), ...rows].join("\r\n"), "text/csv");
}

export function exportTxt(items: Job[], cvId: number) {
  const text = items
    .map((j, i) => {
      const sal = fmtSalary(j);
      return (
        `#${i + 1}  ${j.title} - ${j.company} (${locationText(j)})  [id ${j.id}]\n` +
        `    ${j.url}\n` +
        `    fit ${j.similarity}${sal ? " | " + sal : ""}` +
        `${j.min_years_experience != null ? " | " + j.min_years_experience + "+ yrs" : ""}` +
        `${j.application_status ? " | " + j.application_status : ""}`
      );
    })
    .join("\n\n");
  downloadFile(`shortlist-cv${cvId}.txt`, text, "text/plain");
}

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

// PDF via the browser's print-to-PDF (no library): open a clean printable page.
export function exportPdf(items: Job[], cvId: number, onError: (m: string) => void) {
  const rows = items
    .map((j, i) => {
      const sal = fmtSalary(j);
      const bits = [`fit ${j.similarity}`, `id ${j.id}`, j.source];
      if (sal) bits.push(sal);
      if (j.application_status) bits.push(j.application_status);
      return `<div class="row"><div class="h">#${i + 1}. ${esc(j.title)}</div>
        <div class="c">${esc(j.company)} &middot; ${esc(locationText(j))}</div>
        <div class="u">${esc(j.url)}</div>
        <div class="m">${esc(bits.join("  |  "))}</div></div>`;
    })
    .join("");
  const w = window.open("", "_blank");
  if (!w) {
    onError("Allow pop-ups to export PDF.");
    return;
  }
  w.document.write(
    `<!doctype html><html><head><meta charset="utf-8"><title>Shortlist CV ${cvId}</title>
    <style>body{font:13px/1.5 system-ui,Segoe UI,Roboto,sans-serif;color:#111;padding:28px;max-width:720px}
    h1{font-size:18px;margin:0 0 4px}.sub{color:#666;margin:0 0 18px;font-size:12px}
    .row{margin:0 0 14px;padding-bottom:10px;border-bottom:1px solid #eee}
    .h{font-weight:600}.c{color:#444}.u{color:#06c;font-size:11px;word-break:break-all}
    .m{color:#777;font-size:11px;margin-top:2px}</style></head>
    <body><h1>Job Shortlist</h1><p class="sub">CV #${cvId} &middot; ${items.length} matches &middot; ranked by fit x freshness</p>
    ${rows}</body></html>`,
  );
  w.document.close();
  w.focus();
  w.print();
}
