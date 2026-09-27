"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { PDFDocumentLoadingTask, PDFDocumentProxy, PDFPageProxy, PageViewport, RenderTask } from "pdfjs-dist";
import { api } from "@/lib/api";

/** Evidence to point at: the page it sits on and the text to outline there. */
export type PdfHighlight = { page: number; text: string };

type PdfViewerProps = { documentId: string; highlight?: PdfHighlight | null };

type HighlightRect = { left: number; top: number; width: number; height: number };

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function fitViewport(sourcePage: PDFPageProxy, width: number, zoom: number): PageViewport {
  const original = sourcePage.getViewport({ scale: 1 });
  return sourcePage.getViewport({ scale: (width / original.width) * zoom });
}

/**
 * Rectangles (in viewport CSS pixels) covering the text items whose combined,
 * whitespace-normalized text contains the evidence. Empty when nothing matches.
 */
export async function locateEvidence(sourcePage: PDFPageProxy, viewport: PageViewport, evidence: string): Promise<HighlightRect[]> {
  const needle = normalizeText(evidence);
  if (!needle) return [];
  const content = await sourcePage.getTextContent();
  const items = content.items.filter(item => "str" in item && item.str.trim() !== "");
  let haystack = "";
  const spans: { start: number; end: number; index: number }[] = [];
  items.forEach((item, index) => {
    if (!("str" in item)) return;
    const text = normalizeText(item.str);
    if (haystack) haystack += " ";
    const start = haystack.length;
    haystack += text;
    spans.push({ start, end: haystack.length, index });
  });
  let at = haystack.indexOf(needle);
  if (at < 0) at = haystack.toLowerCase().indexOf(needle.toLowerCase());
  if (at < 0) return [];
  const end = at + needle.length;
  const rects: HighlightRect[] = [];
  for (const span of spans) {
    if (span.end <= at || span.start >= end) continue;
    const item = items[span.index];
    if (!("str" in item)) continue;
    const [, , , , x, y] = item.transform;
    // Text items sit on their baseline; drop the box a little to cover descenders.
    const [x1, y1] = viewport.convertToViewportPoint(x, y - item.height * 0.2).map(Number);
    const [x2, y2] = viewport.convertToViewportPoint(x + item.width, y + item.height * 0.8).map(Number);
    rects.push({ left: Math.min(x1, x2), top: Math.min(y1, y2), width: Math.abs(x2 - x1), height: Math.abs(y2 - y1) });
  }
  return rects;
}

function loadMessage(error: unknown) {
  if (error instanceof Error && error.message.startsWith("Invoice:")) return error.message.slice(8);
  return "The PDF could not be displayed. Try again, or download the original document.";
}

function PdfDocument({ documentId, highlight }: PdfViewerProps) {
  const descriptionId = useId();
  const frame = useRef<HTMLDivElement>(null);
  const canvasHost = useRef<HTMLDivElement>(null);
  const renderingTask = useRef<RenderTask | null>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState("");
  const [pageText, setPageText] = useState("");
  const [highlightRects, setHighlightRects] = useState<HighlightRect[]>([]);
  const [highlightState, setHighlightState] = useState<"found" | "missing" | null>(null);

  useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const measure = () => setWidth(Math.max(160, Math.floor(element.clientWidth - 24)));
    measure();
    // Re-rendering a page is expensive; wait for the layout to settle first.
    let settle: number | undefined;
    const observer = new ResizeObserver(() => {
      window.clearTimeout(settle);
      settle = window.setTimeout(measure, 150);
    });
    observer.observe(element);
    return () => {
      window.clearTimeout(settle);
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    let timedOut = false;
    let task: PDFDocumentLoadingTask | undefined;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
      void task?.destroy().catch(() => undefined);
      if (!disposed) {
        setError("The PDF took too long to load. Check your connection and retry.");
        setLoading(false);
      }
    }, 30_000);
    setPdf(null);
    setPage(1);
    setLoading(true);
    setError("");

    async function load() {
      try {
        // Dynamic import avoids evaluating browser canvas APIs during server rendering.
        const [library, result] = await Promise.all([
          // The official compatibility build includes browser polyfills in
          // both the library and worker (for example Promise.try).
          import("pdfjs-dist/legacy/build/pdf.mjs"),
          api.GET("/v1/documents/{document_id}/file", {
            params: { path: { document_id: documentId } },
            parseAs: "arrayBuffer",
            signal: controller.signal,
            cache: "no-store",
          }),
        ]);
        if (disposed || timedOut) return;
        if (result.response.status === 401 || result.response.status === 403) {
          throw new Error("Invoice:Your session or invoice access changed. Sign in again to continue.");
        }
        if (result.response.status === 404) {
          throw new Error("Invoice:This invoice is unavailable or you no longer have access.");
        }
        if (!result.response.ok || !result.data) throw new Error("PDF request failed");
        const assets = `/pdfjs/${library.version}/`;
        library.GlobalWorkerOptions.workerSrc = `${assets}pdf.worker.min.mjs`;
        task = library.getDocument({
          data: new Uint8Array(result.data),
          cMapUrl: `${assets}cmaps/`,
          cMapPacked: true,
          standardFontDataUrl: `${assets}standard_fonts/`,
          wasmUrl: `${assets}wasm/`,
          iccUrl: `${assets}iccs/`,
          enableXfa: false,
          // PDF.js 6 dropped `isEvalSupported`: PostScript functions are always
          // interpreted, so a strict Content-Security-Policy without 'unsafe-eval'
          // cannot break rendering. Re-add the flag if the library is downgraded.
        });
        const loaded = await task.promise;
        if (!disposed && !timedOut) setPdf(loaded);
      } catch (failure) {
        if (!disposed && !timedOut) setError(loadMessage(failure));
      } finally {
        window.clearTimeout(timeout);
        if (!disposed) setLoading(false);
      }
    }
    void load();
    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
      renderingTask.current?.cancel();
      void task?.destroy().catch(() => undefined);
    };
  }, [documentId, attempt]);

  useEffect(() => {
    const host = canvasHost.current;
    if (!pdf || !host || !width) return;
    // Captured after the guard so the hoisted render function sees non-null values.
    const loadedPdf = pdf;
    const pageHost = host;
    let disposed = false;
    let task: RenderTask | undefined;
    host.replaceChildren();
    setRendering(true);
    setPageText("");
    setError("");

    async function render() {
      try {
        const sourcePage = await loadedPdf.getPage(page);
        if (disposed) return;
        const viewport = fitViewport(sourcePage, width, zoom);
        // Bound canvas memory on large pages and high-density mobile displays.
        const resolution = Math.min(
          window.devicePixelRatio || 1, 2,
          Math.sqrt(16_000_000 / (viewport.width * viewport.height)),
          8192 / viewport.width, 8192 / viewport.height,
        );
        // Each render owns a canvas, so cancellation/rapid paging can never draw
        // different pages concurrently onto the same canvas.
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.floor(viewport.width * resolution));
        canvas.height = Math.max(1, Math.floor(viewport.height * resolution));
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        canvas.className = "block bg-white shadow-sm";
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", `Invoice PDF page ${page} of ${loadedPdf.numPages}`);
        canvas.setAttribute("aria-describedby", descriptionId);
        task = sourcePage.render({
          canvas, viewport,
          transform: [resolution, 0, 0, resolution, 0, 0],
          background: "white",
        });
        renderingTask.current = task;
        await task.promise;
        if (disposed) return;
        pageHost.replaceChildren(canvas);
        setRendering(false);
        const text = await sourcePage.getTextContent();
        if (!disposed) setPageText(text.items.map(item => "str" in item ? item.str + (item.hasEOL ? "\n" : " ") : "").join(""));
      } catch (failure) {
        if (!disposed) {
          setError(loadMessage(failure));
          setRendering(false);
        }
      }
    }
    void render();
    return () => {
      disposed = true;
      task?.cancel();
      if (renderingTask.current === task) renderingTask.current = null;
      host.replaceChildren();
    };
  }, [pdf, page, width, zoom, descriptionId]);

  // A new highlight jumps to its page; the overlay itself follows the rendered page.
  useEffect(() => {
    if (!pdf || !highlight) return;
    const target = Math.min(Math.max(highlight.page, 1), pdf.numPages);
    setPage(target);
    frame.current?.scrollTo({ top: 0, left: 0 });
  }, [pdf, highlight]);

  useEffect(() => {
    if (!pdf || !width || !highlight || highlight.page !== page) {
      setHighlightRects([]);
      setHighlightState(null);
      return;
    }
    let disposed = false;
    const loadedPdf = pdf;
    const evidence = highlight.text;
    async function locate() {
      try {
        const sourcePage = await loadedPdf.getPage(page);
        const rects = await locateEvidence(sourcePage, fitViewport(sourcePage, width, zoom), evidence);
        if (disposed) return;
        setHighlightRects(rects);
        setHighlightState(rects.length > 0 ? "found" : "missing");
      } catch {
        if (!disposed) {
          setHighlightRects([]);
          setHighlightState("missing");
        }
      }
    }
    void locate();
    return () => { disposed = true; };
  }, [pdf, page, width, zoom, highlight]);

  function navigate(next: number) {
    setPage(next);
    frame.current?.scrollTo({ top: 0, left: 0 });
  }

  return <div className="min-w-0 space-y-3" aria-label="Invoice PDF viewer">
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-2">
        <button type="button" className="secondary px-3 text-xs" disabled={!pdf || page <= 1} onClick={() => navigate(page - 1)} aria-label="Previous PDF page">← Previous</button>
        <span className="text-xs font-semibold tabular-nums text-slate-700" aria-live="polite">{pdf ? `Page ${page} of ${pdf.numPages}` : "Loading pages…"}</span>
        <button type="button" className="secondary px-3 text-xs" disabled={!pdf || page >= pdf.numPages} onClick={() => navigate(page + 1)} aria-label="Next PDF page">Next →</button>
      </div>
      <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">Zoom
        <select className="rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs" aria-label="PDF zoom" value={zoom} onChange={event => setZoom(Number(event.target.value))} disabled={!pdf}>
          <option value={0.75}>75% of width</option><option value={1}>Fit width</option><option value={1.25}>125% of width</option><option value={1.5}>150% of width</option><option value={2}>200% of width</option>
        </select>
      </label>
    </div>
    {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}<button type="button" className="ml-2 font-semibold underline" onClick={() => setAttempt(value => value + 1)}>Retry PDF</button></div>}
    <div ref={frame} className="relative max-h-[72vh] min-h-64 overflow-auto rounded-xl border border-slate-200 bg-slate-100 p-3" aria-busy={loading || rendering} tabIndex={0} aria-label="Scrollable PDF page">
      {(loading || rendering) && !error && <p role="status" className="py-16 text-center text-sm text-slate-500">{loading ? "Loading PDF…" : `Rendering page ${page}…`}</p>}
      <div className="relative mx-auto w-max min-w-0">
        <div ref={canvasHost} />
        {highlightRects.length > 0 && !rendering && <div className="pointer-events-none absolute inset-0" aria-hidden="true" data-testid="evidence-highlight">
          {highlightRects.map((rect, index) => <span key={index} className="absolute rounded-sm bg-amber-300/40 ring-2 ring-amber-500/80" style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }} />)}
        </div>}
      </div>
    </div>
    {highlight && highlightState && <p role="status" className={`text-xs font-semibold ${highlightState === "found" ? "text-amber-800" : "text-slate-500"}`}>{highlightState === "found" ? `Evidence highlighted on page ${page}.` : `Evidence text was not found on page ${page}; showing the page instead.`}</p>}
    <p id={descriptionId} className="text-xs leading-5 text-slate-500">Navigate through every page and zoom to check invoice details. Select “Read page text” for a copyable text version.</p>
    {pdf && !loading && !rendering && !error && <details className="rounded-xl border border-slate-200 bg-white p-3">
      <summary className="cursor-pointer text-xs font-semibold text-slate-700">Read page {page} text</summary>
      <p className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{pageText.trim() || "No selectable text is available on this page. Inspect the page image above."}</p>
    </details>}
  </div>;
}

export function PdfViewer({ documentId, highlight = null }: PdfViewerProps) {
  // A changed document immediately disposes its worker and erases the old page.
  return <PdfDocument key={documentId} documentId={documentId} highlight={highlight} />;
}
