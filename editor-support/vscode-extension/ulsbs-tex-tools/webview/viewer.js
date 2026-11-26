// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

// Render the PDF preview and bridge SyncTeX and build messages to the UI.

import { PdfjsViewer, PdfjsViewerRuntime } from "@unilarva/pdfjs-viewer";
import * as pdfjs from "pdfjs-dist/build/pdf.mjs";
import "@unilarva/pdfjs-viewer/default-ui.css";
import "./viewer.css";
import { findPdfWord, measurePdfText } from "./pdf-word.mjs";

const root = document.getElementById("pdf-viewer");
const status = document.getElementById("pdf-status");
const buildToolbar = document.getElementById("pdf-build-toolbar");
const buildButton = document.getElementById("pdf-build");
const buildStatus = document.getElementById("pdf-build-status");
const syncHint = document.getElementById("pdf-sync-hint");
const listeners = new AbortController();
const listenerOptions = { signal: listeners.signal };
const loadsByBytes = new WeakMap();

let vscode;
let workerUrl;
let worker;
let runtime;
let viewer;
let revision = -1;
let activeLoad;
let lastPage = 1;
let lastView;

function showStatus(message) {
  status.textContent = message;
  status.hidden = !message;
}

function reportError(message, error) {
  console.error(message, error);
  showStatus(message);
}

function dispose() {
  listeners.abort();
  activeLoad?.removeHighlight?.();
  activeLoad = undefined;
  viewer?.destroy();
  runtime?.destroy();
  worker?.terminate();
  if (workerUrl) URL.revokeObjectURL(workerUrl);
}

function isCurrent(load) {
  return activeLoad === load && load.documentId != null && viewer.documentId === load.documentId;
}

function isPage(page) {
  return Number.isSafeInteger(page) && page > 0;
}

function getPdfPage(load, page) {
  if (!load.pages.has(page)) {
    load.pages.set(page, load.task.promise.then(pdf => pdf.getPage(page)));
  }
  return load.pages.get(page);
}

function publishPage(type, load, page) {
  lastPage = page;
  vscode.setState({ page });
  vscode.postMessage({ type, revision: load.revision, page });
}

function captureView() {
  const scrollport = root.querySelector(".pdf-container");
  if (!scrollport?.clientWidth || !scrollport.clientHeight) return;
  const bounds = scrollport.getBoundingClientRect();
  const left = bounds.left + scrollport.clientLeft;
  const top = bounds.top + scrollport.clientTop;
  // Probe either side of the center as well, since the center of a spread
  // can land in its gutter. Keep the point's offset within the scrollport.
  let anchor;
  const offsetY = scrollport.clientHeight / 2;
  for (const fraction of [0.5, 0.25, 0.75]) {
    const offsetX = scrollport.clientWidth * fraction;
    const hit = viewer.getPagePointAtClientPosition(left + offsetX, top + offsetY);
    if (hit?.documentId === activeLoad.documentId) {
      anchor = { ...hit, offsetX, offsetY };
      break;
    }
  }
  const { currentPage, pageLayout, rotation, fitMode, fitActive, scale } = viewer.state;
  return { page: anchor?.page ?? currentPage, pageLayout, rotation, fitMode, fitActive, scale,
    anchor, top: scrollport.scrollTop, left: scrollport.scrollLeft };
}

async function restoreView(load, view) {
  if (viewer.state.pageLayout !== view.pageLayout) await viewer.setPageLayout(view.pageLayout);
  if (!isCurrent(load)) return;
  if (viewer.state.rotation !== view.rotation) await viewer.rotateTo(view.rotation);
  if (!isCurrent(load)) return;
  if (viewer.state.fitMode !== view.fitMode) await viewer.setFitMode(view.fitMode);
  if (!isCurrent(load)) return;
  if (!view.fitActive) viewer.zoomTo(view.scale);
  if (!isCurrent(load) || load.jump || view.page > viewer.state.pageCount) return;

  const scrollport = root.querySelector(".pdf-container");
  if (!scrollport?.clientWidth || !scrollport.clientHeight) return;
  const anchor = view.anchor;
  if (anchor) {
    const page = await getPdfPage(load, anchor.page);
    if (!isCurrent(load) || load.jump) return;
    const displayedViewport = () => {
      const { scale, rotation } = viewer.state;
      return page.getViewport({ scale, rotation: (page.rotate + rotation) % 360 });
    };
    const viewport = displayedViewport();
    const [x, y] = viewport.convertToViewportPoint(anchor.x, anchor.y);
    const clamp = (value, max) => Math.min(Math.max(0, value), max);
    // The viewer centers the navigation point horizontally and aligns it at
    // the top vertically. Offset the target to keep the old point in place.
    const [scrollX, scrollY] = viewport.convertToPdfPoint(
      clamp(x + scrollport.clientWidth / 2 - anchor.offsetX, viewport.width),
      clamp(y - anchor.offsetY, viewport.height)
    );
    const result = await viewer.navigateToPagePoint({ page: anchor.page, x: scrollX, y: scrollY }, load.documentId);
    if (!isCurrent(load) || load.jump) return;
    if (result.ok && x >= 0 && x <= viewport.width && y >= 0 && y <= viewport.height) {
      const wrapper = scrollport.querySelector(`.pdf-page[data-page="${anchor.page}"]`);
      if (wrapper) {
        // Fit again once navigation has prepared the target row's geometry.
        // Never call zoomTo for this case: it would disable automatic fitting.
        if (view.fitActive) {
          await viewer.fit();
          if (!isCurrent(load) || load.jump) return;
        }
        const [anchorX, anchorY] = displayedViewport().convertToViewportPoint(anchor.x, anchor.y);
        // Correct for a clamped navigation point at a page edge or gutter.
        const pageBounds = scrollport.querySelector(`.pdf-page[data-page="${anchor.page}"]`)?.getBoundingClientRect();
        if (!pageBounds) return;
        const portBounds = scrollport.getBoundingClientRect();
        const dx = pageBounds.left + anchorX - portBounds.left - scrollport.clientLeft - anchor.offsetX;
        const dy = pageBounds.top + anchorY - portBounds.top - scrollport.clientTop - anchor.offsetY;
        if (Math.abs(dx) >= 1 || Math.abs(dy) >= 1) scrollport.scrollBy({ left: dx, top: dy, behavior: "instant" });
        return;
      }
    }
  }
  scrollport.scrollTo({ top: view.top, left: view.left, behavior: "instant" });
}

async function loadPdf(message) {
  const view = lastView;
  const initialPage = view?.page ?? lastPage;
  const load = { revision: message.revision, pages: new Map() };
  activeLoad = load;
  showStatus("Loading PDF preview...");
  let data;
  try {
    if (!(message.buffer instanceof ArrayBuffer)) throw new Error("PDF bytes did not reach the webview.");
    if (!message.buffer.byteLength) throw new Error("The PDF file is empty.");
    data = new Uint8Array(message.buffer);
    loadsByBytes.set(data, load);
    const result = await viewer.load({ type: "data", data, filename: message.filename }, { initialPage });
    if (activeLoad !== load) return;
    if (!result.ok) {
      if (result.reason === "error") throw result.error;
      showStatus("PDF preview load cancelled.");
      return;
    }
    load.documentId = viewer.documentId;
    if (view) {
      try {
        await restoreView(load, view);
      } catch (error) {
        if (isCurrent(load)) console.warn("Could not restore PDF preview position.", error);
      }
    }
    if (!isCurrent(load)) return;
    load.ready = true;
    showStatus("");
    // The viewer may report its initial reading-position calculation before
    // the scroll to initialPage has settled. Keep the requested page on reload.
    publishPage("loaded", load, Math.min(initialPage, viewer.state.pageCount));
    if (load.jump) void forward(load, load.jump);
  } catch (error) {
    if (activeLoad === load) {
      const detail = typeof error?.message === "string" && error.message;
      reportError(detail ? `Could not load PDF preview: ${detail}` : "Could not load PDF preview.", error);
    }
  } finally {
    if (data) loadsByBytes.delete(data);
  }
}

async function forward(load, jump) {
  const { page, x, y } = jump;
  const currentJump = () => isCurrent(load) && load.jump === jump;
  let overlay;
  let retained = false;
  try {
    if (page > viewer.state.pageCount) return;
    const pdfPage = await getPdfPage(load, page);
    if (!currentJump()) return;
    // SyncTeX uses top-left big points on the unrotated page.
    const [pdfX, pdfY] = pdfPage.getViewport({ scale: 1, rotation: 0 }).convertToPdfPoint(x, y);

    const element = document.createElement("span");
    element.className = "synctex-highlight";
    element.setAttribute("aria-hidden", "true");
    overlay = await viewer.registerPageOverlay({
      page, anchor: { x: pdfX, y: pdfY }, element
    }, load.documentId);
    if (!overlay.ok || !currentJump()) return;
    const mountedOverlay = overlay;

    if (!markerFitsInView(element)) {
      // Offset only the scroll target, in displayed CSS pixels. The marker
      // keeps its exact PDF anchor even when the page or viewer is rotated.
      const { scale, rotation } = viewer.state;
      const displayed = pdfPage.getViewport({ scale, rotation: (pdfPage.rotate + rotation) % 360 });
      const [left, top] = displayed.convertToViewportPoint(pdfX, pdfY);
      const [scrollX, scrollY] = displayed.convertToPdfPoint(left, Math.max(0, top - 32));
      const result = await viewer.navigateToPagePoint({ page, x: scrollX, y: scrollY }, load.documentId);
      if (!result.ok || !currentJump()) return;
    }

    const timer = setTimeout(removeHighlight, 2200);
    function removeHighlight() {
      clearTimeout(timer);
      mountedOverlay.dispose();
      if (load.removeHighlight === removeHighlight) load.removeHighlight = undefined;
    }
    load.removeHighlight = removeHighlight;
    retained = true;
  } catch (error) {
    if (currentJump()) console.warn("Could not navigate to SyncTeX point.", error);
  } finally {
    if (overlay?.ok && !retained) overlay.dispose();
  }
}

function markerFitsInView(element) {
  const scrollport = element.closest(".pdf-container");
  if (!scrollport) return false;
  const marker = element.getBoundingClientRect();
  const bounds = scrollport.getBoundingClientRect();
  const left = bounds.left + scrollport.clientLeft;
  const top = bounds.top + scrollport.clientTop;
  return marker.width > 0 && marker.height > 0 && marker.left >= left && marker.top >= top &&
    marker.right <= left + scrollport.clientWidth && marker.bottom <= top + scrollport.clientHeight;
}

function onMessage({ data: message }) {
  if (message?.type === "buildState") {
    if (buildToolbar) buildToolbar.hidden = message.available !== true;
    if (buildStatus) buildStatus.textContent = typeof message.message === "string" ? message.message : "";
    return;
  }
  if (!message || !Number.isSafeInteger(message.revision) || message.revision < revision) return;
  if (message.type === "forward") {
    const load = activeLoad;
    const point = message.point;
    if (!load || message.revision !== load.revision || !isPage(point?.page) ||
        !Number.isFinite(point.x) || !Number.isFinite(point.y)) return;
    load.removeHighlight?.();
    load.jump = point;
    if (load.ready && isCurrent(load)) void forward(load, point);
    return;
  }
  if (message.type !== "waiting" && message.type !== "load") return;
  revision = message.revision;
  if (activeLoad?.ready && isCurrent(activeLoad)) lastView = captureView() ?? lastView;
  activeLoad?.removeHighlight?.();
  activeLoad = undefined;
  if (message.type === "waiting") {
    viewer.close();
    showStatus(message.message || "Waiting for a compiled PDF...");
  } else {
    void loadPdf(message);
  }
}

async function onClick(event) {
  if (event.button !== 0 || (!event.ctrlKey && !event.metaKey)) return;
  const load = activeLoad;
  if (!load?.ready || !isCurrent(load)) return;
  const click = load.inverseClick = {};
  const currentClick = () => load.inverseClick === click && isCurrent(load);
  const hit = viewer.getPagePointAtClientPosition(event.clientX, event.clientY);
  if (!hit || hit.documentId !== load.documentId) return;
  event.preventDefault();
  event.stopPropagation();
  try {
    const pdfPage = await getPdfPage(load, hit.page);
    if (!currentClick()) return;
    const viewport = pdfPage.getViewport({ scale: 1, rotation: 0 });
    const [x, y] = viewport.convertToViewportPoint(hit.x, hit.y);
    const message = { type: "inverse", revision: load.revision, page: hit.page, x, y };
    try {
      if (load.text?.page !== hit.page) {
        const content = pdfPage.getTextContent();
        load.text = { page: hit.page, content };
      }
      const content = await load.text.content;
      if (!currentClick()) return;
      const word = findPdfWord(content, hit.x, hit.y, measurePdfText);
      if (word) message.word = word;
    } catch {
      // Text extraction and geometry are optional; the point still locates a line.
    }
    if (currentClick()) vscode.postMessage(message);
  } catch (error) {
    if (currentClick()) console.warn("Could not locate SyncTeX point.", error);
  }
}

async function initialize() {
  try {
    showStatus("Waiting for a compiled PDF...");
    window.addEventListener("pagehide", dispose, { once: true });
    vscode = acquireVsCodeApi();
    if (syncHint && /Mac|iPhone|iPad/.test(navigator.platform)) {
      syncHint.textContent = "Cmd-click to jump to source";
    }
    const savedPage = vscode.getState()?.page;
    if (isPage(savedPage)) lastPage = savedPage;

    const assets = root.dataset.assets;
    const response = await fetch(`${assets}/pdf.worker.min.mjs`, listenerOptions);
    if (!response.ok) throw new Error(`PDF.js worker request failed (${response.status})`);
    const source = await response.blob();
    if (listeners.signal.aborted) return;
    workerUrl = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
    worker = new Worker(workerUrl, { type: "module" });
    worker.addEventListener("error", error => {
      dispose();
      reportError("Could not start the PDF.js worker.", error);
    }, listenerOptions);

    runtime = new PdfjsViewerRuntime({
      pdfjs: {
        ...pdfjs,
        getDocument(options) {
          const task = pdfjs.getDocument(options);
          // Capture the viewer's base document without reloading or owning it.
          const load = loadsByBytes.get(options.data);
          if (load) load.task = task;
          return task;
        }
      },
      workerPort: worker
    });
    viewer = new PdfjsViewer({
      rootEl: root,
      runtime,
      defaultDocumentOptions: {
        cMapUrl: `${assets}/cmaps/`,
        iccUrl: `${assets}/iccs/`,
        standardFontDataUrl: `${assets}/standard_fonts/`,
        wasmUrl: `${assets}/wasm/`
      }
    });
    root.addEventListener("click", onClick, { ...listenerOptions, capture: true });
    root.addEventListener("pdf:pagechange", ({ detail }) => {
      const load = activeLoad;
      if (load?.ready && isCurrent(load)) publishPage("page", load, detail.page);
    }, listenerOptions);
    // Leave the button enabled so another click can restart a running build.
    buildButton?.addEventListener("click", () => vscode.postMessage({ type: "build" }), listenerOptions);
    window.addEventListener("message", onMessage, listenerOptions);
    vscode.postMessage({ type: "ready" });
  } catch (error) {
    if (listeners.signal.aborted) return;
    dispose();
    reportError("Could not initialize the PDF preview.", error);
  }
}

void initialize();
