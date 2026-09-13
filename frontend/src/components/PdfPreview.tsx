import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";

// Text/annotation layers are disabled below, so their CSS isn't needed.
// Serve the pdf.js worker from the bundled dependency (Vite resolves the URL).
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

// An in-app PDF viewer styled to the app rather than the browser's generic
// plugin (point 13). Renders every page into a themed, scrollable panel.
export function PdfPreview({ url }: { url: string }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(460);
  const [numPages, setNumPages] = useState(0);
  const [error, setError] = useState(false);

  useEffect(() => {
    const measure = () => {
      if (wrapRef.current) setWidth(wrapRef.current.clientWidth - 24);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  return (
    <div className="pdf-preview scroll-themed" ref={wrapRef}>
      {error ? (
        <div className="pdf-msg">Couldn&rsquo;t render this PDF.</div>
      ) : (
        <Document
          file={url}
          onLoadSuccess={({ numPages }) => setNumPages(numPages)}
          onLoadError={() => setError(true)}
          loading={<div className="pdf-msg">Loading preview...</div>}
          error={<div className="pdf-msg">Couldn&rsquo;t render this PDF.</div>}
        >
          {Array.from({ length: numPages }, (_, i) => (
            <Page
              key={i}
              pageNumber={i + 1}
              width={width > 0 ? width : undefined}
              renderAnnotationLayer={false}
              renderTextLayer={false}
            />
          ))}
        </Document>
      )}
    </div>
  );
}
