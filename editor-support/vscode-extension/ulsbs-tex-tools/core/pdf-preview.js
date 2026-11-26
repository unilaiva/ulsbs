// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later
// @ts-check

/** Coordinates compiled PDF webviews, artifact reloads, and source navigation. */

const { readSyncTeX } = require("./synctex");
const { findSourceWordColumn } = require("./pdf-source-word");
const { stripComment } = require("./parser");
const { getWorkspaceFolderForUri } = require("./workspace");
const { getSettings } = require("./config");

/** @typedef {import('vscode').Uri} Uri */
/** @typedef {import('vscode').WorkspaceFolder} WorkspaceFolder */
/** @typedef {{main: Uri, pdf: Uri, variant: string, label: string}} PreviewTarget */
/** @typedef {{panel: import('vscode').WebviewPanel, pdf: Uri, target?: PreviewTarget,
 * sourceColumn?: import('vscode').ViewColumn, forward: (source: string, line: number) => void,
 * build: () => Promise<void>, markBuilding: () => BuildFinished | undefined,
 * setTarget: (target: PreviewTarget) => void}} Preview */
/** @typedef {(code: number | undefined, error?: unknown) => void} BuildFinished */
/** @typedef {'open' | 'compile' | 'forward'} PreviewAction */

// Ordinary output markers, as defined in ulsbs-variants.def.tex. The compiler
// inserts them before the first paper-size token, not at the end of the stem.
const variants = [
  { variant: "default", marker: "", label: "Default" },
  { variant: "lyric", marker: "_LYRICS-ONLY", label: "Lyrics only" },
  { variant: "charango", marker: "_CHARANGO", label: "Charango" },
  { variant: "bassclef", marker: "_BASSCLEF", label: "Bass clef" }
];

/** @param {Uri} uri */
function basename(uri) {
  return uri.path.slice(uri.path.lastIndexOf("/") + 1);
}

/** Return the ordinary filenames a ULSBS main document can produce. @param {Uri} uri */
function pdfNames(uri) {
  const stem = basename(uri).replace(/\.[^.]+$/, "");
  const paper = stem.search(/_A\d/);
  const at = paper < 0 ? stem.length : paper;
  return variants.map(({ marker }) => `${stem.slice(0, at)}${marker}${stem.slice(at)}.pdf`);
}

/** Read a literal class option for the picker; the compiler validates availability. @param {string} text */
function declaredPreviewVariants(text) {
  const preamble = text.split(/\r?\n/).map(stripComment).join("\n").split(/\\begin\s*\{\s*document\s*\}/, 1)[0];
  const options = /\\documentclass\s*\[([^\]]*)\]\s*\{\s*ulsbs-songbook[\w./-]*\s*\}/.exec(preamble)?.[1];
  const names = /(?:^|,)\s*variants\s*=\s*\{([a-z,\s]+)\}\s*(?:,|$)/.exec(options ?? "")?.[1];
  return new Set(["default", ...(names?.split(",").map((name) => name.trim()) ?? [])]);
}

/** Resolve a published SyncTeX input, without opening external or generated files.
 * @param {typeof import('vscode')} vscode @param {Uri} root @param {Uri} pdfDir @param {string} name */
function sourceKey(vscode, root, pdfDir, name) {
  const drive = /^[a-z]:[\\/]/i.test(name);
  const windows = /^\/[a-z]:\//i.test(root.path);
  const path = windows || drive ? name.replace(/\\/g, "/") : name;
  if (!path || /[\u0000-\u001f]/.test(path)) return null;

  const uri = path.startsWith("/") || drive
    ? vscode.Uri.joinPath(root.with({ path: "/" }), path)
    : vscode.Uri.joinPath(pdfDir, path);
  const rootPrefix = root.path.replace(/\/$/, "") + "/";
  /** @param {string} value */
  const compare = (value) => windows ? value.toLowerCase() : value;
  if (!compare(uri.path).startsWith(compare(rootPrefix))) return null;
  const relative = uri.path.slice(rootPrefix.length);
  if (!relative || /^(?:temp|result)\//.test(compare(relative))) return null;
  return vscode.Uri.joinPath(root, relative).toString();
}

/** Resolve a generated song-boundary hit to the opening declaration in the same file.
 * @param {import('vscode').TextDocument} document @param {import('vscode').TextLine} line */
function songOpeningForClosingLine(document, line) {
  const closing = /^\s*(\\endsong|\\end\s*\{\s*song\s*\})\s*$/.exec(stripComment(line.text));
  if (!closing) return undefined;
  // LuaLaTeX tags the generated prelude with the closing command's source line.
  // Do not look past another close or try to infer boundaries across includes.
  for (let number = line.lineNumber - 1; number >= 0; number--) {
    const candidate = document.lineAt(number);
    const boundary = /^\s*(\\(begin|end)song(?![a-zA-Z@])|\\(begin|end)\s*\{\s*song\s*\})/.exec(stripComment(candidate.text));
    if (!boundary) continue;
    const matchingOpening = closing[1] === "\\endsong" ? boundary[2] === "begin" : boundary[3] === "begin";
    return matchingOpening ? candidate : undefined;
  }
  return undefined;
}

/** Locate the score declaration associated with a nearby LilyPond wrapper line.
 * @param {import('vscode').TextDocument} document @param {number} anchor */
function lilypondOpening(document, anchor) {
  const markup = /\\(?:begin\s*\{(lilypond|song)\}|end\s*\{(lilypond|song)\}|(lilypondfile|lilypond|beginsong|endsong)(?![a-zA-Z@])|[^a-zA-Z@])/g;
  let closed;
  for (let line = anchor; line >= 0; line--) {
    const code = stripComment(document.lineAt(line).text);
    const matches = Array.from(code.matchAll(markup)).reverse();
    for (const match of matches) {
      const [, begin, end, command] = match;
      if (begin === "song" || command === "beginsong" || (line !== anchor && (end === "song" || command === "endsong"))) {
        return undefined;
      }
      if (end === "lilypond") {
        if (closed) return undefined;
        closed = true;
      } else if ((begin === "lilypond" && (closed || line === anchor)) ||
                 (!closed && (command === "lilypondfile" || command === "lilypond"))) {
        return { line, character: match.index };
      } else if (begin === "lilypond") {
        return undefined;
      }
    }
  }
  return undefined;
}

/** Register PDF commands for a workspace, sharing one panel per built artifact.
 * @param {typeof import('vscode')} vscode @param {import('vscode').ExtensionContext} context
 * @param {ReturnType<typeof import('./songbooks').createSongbookService>} songbookService
 * @param {ReturnType<typeof import('./compile').registerCompileCommands>} compileController */
function registerPdfPreview(vscode, context, songbookService, compileController) {
  /** @type {Map<string, Preview>} */
  const panels = new Map();
  /** @type {Map<string, {timer: ReturnType<typeof setTimeout>, sequence: number}>} */
  const saveTimers = new Map();
  let saveSequence = 0;
  /** @type {Preview | undefined} */
  let lastPreview;
  let enabled = false;
  const canBuild = () => vscode.workspace.isTrusted && vscode.env.uiKind !== vscode.UIKind.Web;

  /** @param {Uri} pdf @param {WorkspaceFolder} folder @param {import('vscode').TextEditor | undefined} editor
   * @param {boolean} preserveFocus @param {PreviewTarget} [target] */
  function openPanel(pdf, folder, editor, preserveFocus, target) {
    const key = pdf.toString();
    const existing = panels.get(key);
    if (existing) {
      if (target) existing.setTarget(target);
      if (editor?.viewColumn && editor.viewColumn !== existing.panel.viewColumn) {
        existing.sourceColumn = editor.viewColumn;
      }
      existing.panel.reveal(undefined, preserveFocus);
      lastPreview = existing;
      return existing;
    }

    const pdfDir = vscode.Uri.joinPath(pdf, "..");
    const filename = basename(pdf);
    const assetDir = vscode.Uri.joinPath(context.extensionUri, "dist", "pdf");
    const panel = vscode.window.createWebviewPanel(
      "ulsbsPdfPreview", filename,
      { viewColumn: vscode.ViewColumn.Beside, preserveFocus },
      { enableScripts: true, localResourceRoots: [assetDir], retainContextWhenHidden: true }
    );
    /** @type {Preview} */
    const state = { panel, pdf, target, sourceColumn: editor?.viewColumn, forward, markBuilding, setTarget,
      build: () => buildPreviews([state], false) };
    panels.set(key, state);
    lastPreview = state;

    let disposed = false;
    let ready = false;
    let revision = 0;
    let loadedRevision = -1;
    /** @type {{source: string, line: number, job: number} | undefined} */
    let pendingForward;
    let activeJob = 0;
    /** @type {number | undefined} */
    let pageHint;
    /** @type {ReturnType<typeof setTimeout> | undefined} */
    let timer;
    /** @type {Uint8Array | undefined} */
    let sidecar;
    /** @type {ReturnType<typeof readSyncTeX> | undefined} */
    let index;
    let buildStatus = "";
    let buildId = 0;
    let building = false;
    const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(pdfDir, "*"));
    const buildAvailable = () => Boolean(state.target) && canBuild();

    /** @param {string} message */
    function reportBuild(message) {
      buildStatus = message;
      if (ready && !disposed) void panel.webview.postMessage({ type: "buildState", available: buildAvailable(), message });
    }

    /** @param {PreviewTarget} value */
    function setTarget(value) {
      state.target = value;
      reportBuild(buildStatus);
    }

    /** @returns {BuildFinished | undefined} */
    function markBuilding() {
      if (!enabled || disposed || !canBuild() || !state.target) return undefined;
      const id = ++buildId;
      const before = revision;
      building = true;
      reportBuild(`Building ${state.target.label.toLowerCase()} preview...`);
      return (code, error) => {
        if (id !== buildId || disposed) return;
        building = false;
        if (code === 0 && ready && revision === before) onPdfChange(pdf);
        reportBuild(error ? `Could not start build: ${errorText(error)}` :
          code === 0 ? (sidecar || index ? "" : "Waiting for SyncTeX data...") :
          code === undefined ? "Build stopped." : "Build failed. See the ULSBS build terminal.");
      };
    }

    /** @param {number} version */
    function current(version) {
      return !disposed && revision === version;
    }

    async function publishPdf() {
      const version = revision;
      try {
        const [bytes, syncBytes] = await Promise.all([
          vscode.workspace.fs.readFile(pdf),
          Promise.resolve(vscode.workspace.fs.readFile(vscode.Uri.joinPath(pdfDir, filename.replace(/\.pdf$/i, ".synctex.gz"))))
            .catch(() => undefined)
        ]);
        if (!current(version)) return;
        sidecar = syncBytes;
        if (!building) reportBuild(syncBytes ? "" : "This PDF has no SyncTeX data.");
        // VS Code's desktop filesystem can return a Node Buffer. Its toJSON()
        // runs before VS Code extracts binary payloads from webview messages.
        const buffer = bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength &&
          bytes.buffer instanceof ArrayBuffer ? bytes.buffer : Uint8Array.from(bytes).buffer;
        await panel.webview.postMessage({ type: "load", revision: version, filename, buffer });
      } catch (error) {
        if (!current(version)) return;
        const message = error instanceof vscode.FileSystemError && error.code === "FileNotFound"
          ? (buildAvailable() ? `No PDF yet for ${filename}. Select Build Preview to create it.` : `No PDF found for ${filename}.`)
          : `Could not read ${filename}: ${errorText(error)}`;
        await panel.webview.postMessage({ type: "waiting", revision: version, message });
      }
    }

    /** @param {Uri} uri */
    function onPdfChange(uri) {
      if (!ready || uri.toString() !== key) return;
      ++revision;
      sidecar = index = undefined;
      clearTimeout(timer);
      // ULSBS publishes the PDF by rename after the sidecar is in place. A
      // short debounce coalesces file-provider create/change/delete events.
      timer = setTimeout(() => void publishPdf(), 150);
    }

    async function getIndex() {
      if (!index && sidecar) {
        index = readSyncTeX(sidecar, (/** @type {string} */ name) => sourceKey(vscode, folder.uri, pdfDir, name));
        sidecar = undefined;
      }
      return index;
    }

    /** @param {string} source @param {number} line */
    function forward(source, line) {
      pendingForward = { source, line, job: ++activeJob };
      if (loadedRevision === revision) void flushForward();
    }

    async function flushForward() {
      if (!pendingForward) return;
      const request = pendingForward;
      const version = revision;
      const valid = () => current(version) && request.job === activeJob;
      try {
        const map = await getIndex();
        if (!valid()) return;
        if (!map) {
          if (buildAvailable()) {
            if (!building) reportBuild("Build Preview to enable source sync for this PDF.");
          } else {
            pendingForward = undefined;
            vscode.window.showInformationMessage("No SyncTeX data for this PDF.");
          }
          return;
        }
        pendingForward = undefined;
        const point = map.forward(request.source, request.line, pageHint);
        if (point) {
          await panel.webview.postMessage({ type: "forward", revision: version, point });
        } else {
          vscode.window.showInformationMessage("No PDF location for this source line in the current build.");
        }
      } catch (error) {
        if (valid()) {
          pendingForward = undefined;
          vscode.window.showWarningMessage(`Could not read SyncTeX data: ${errorText(error)}`);
        }
      }
    }

    /** @param {{page: number, x: number, y: number, word?: string}} point */
    async function inverse({ page, x, y, word }) {
      if (!Number.isSafeInteger(page) || page < 1 || !Number.isFinite(x) || !Number.isFinite(y)) return;
      const job = ++activeJob;
      pendingForward = undefined;
      const version = revision;
      const valid = () => current(version) && job === activeJob;
      try {
        const map = await getIndex();
        if (!valid()) return;
        if (!map) {
          if (buildAvailable()) {
            if (!building) reportBuild("Build Preview to enable source sync for this PDF.");
          } else {
            vscode.window.showInformationMessage("No SyncTeX data for this PDF.");
          }
          return;
        }
        const location = map.inverse(page, x, y);
        if (location?.kind === "header") return;
        if (!location) {
          vscode.window.showInformationMessage("No project source location for this PDF point.");
          return;
        }
        const uri = vscode.Uri.parse(location.source);
        const document = await vscode.workspace.openTextDocument(uri);
        if (!valid()) return;
        const line = document.lineAt(Math.min(location.line, document.lineCount) - 1);
        const exactLine = line.lineNumber + 1 === location.line;
        let position;
        if (location.kind === "lilypond") {
          const opening = exactLine && lilypondOpening(document, line.lineNumber);
          if (!opening) {
            vscode.window.showInformationMessage("No matching LilyPond block found in the source. If it moved, recompile the PDF.");
            return;
          }
          position = new vscode.Position(opening.line, opening.character);
        } else {
          const opening = exactLine ? songOpeningForClosingLine(document, line) : undefined;
          const target = opening ?? line;
          const column = exactLine && !opening ? findSourceWordColumn(line.text, word) : undefined;
          position = new vscode.Position(target.lineNumber, column ?? target.firstNonWhitespaceCharacterIndex);
        }
        /** @param {import('vscode').ViewColumn} [column] */
        const otherColumn = (column) => column && column !== panel.viewColumn;
        const viewColumn = vscode.window.visibleTextEditors.find((editor) =>
          editor.document.uri.toString() === location.source && otherColumn(editor.viewColumn))?.viewColumn
          ?? (otherColumn(state.sourceColumn) ? state.sourceColumn : undefined)
          ?? (panel.viewColumn === vscode.ViewColumn.One ? vscode.ViewColumn.Two : vscode.ViewColumn.One);
        await vscode.window.showTextDocument(document, { viewColumn, selection: new vscode.Range(position, position) });
      } catch (error) {
        if (valid()) vscode.window.showWarningMessage(`Could not jump to the SyncTeX source: ${errorText(error)}`);
      }
    }

    const listeners = [
      watcher,
      watcher.onDidCreate(onPdfChange), watcher.onDidChange(onPdfChange), watcher.onDidDelete(onPdfChange),
      vscode.workspace.onDidGrantWorkspaceTrust(() => reportBuild(buildStatus)),
      panel.onDidChangeViewState(({ webviewPanel }) => { if (webviewPanel.active) lastPreview = state; }),
      panel.webview.onDidReceiveMessage((message) => {
        if (!message || disposed) return;
        if (message.type === "ready") {
          if (ready) {
            // VS Code can recreate the webview while leaving its panel open.
            ++revision;
            sidecar = index = undefined;
            clearTimeout(timer);
          }
          ready = true;
          reportBuild(buildStatus);
          void publishPdf();
        } else if (message.type === "build") {
          void state.build();
        } else if (message.revision === revision) {
          if (message.type === "loaded") {
            loadedRevision = revision;
            pageHint = message.page;
            void flushForward();
          } else if (message.type === "page" && Number.isSafeInteger(message.page) && message.page > 0) {
            pageHint = message.page;
          } else if (message.type === "inverse" && loadedRevision === revision) {
            void inverse(message);
          }
        }
      })
    ];
    panel.onDidDispose(() => {
      disposed = true;
      clearTimeout(timer);
      for (const listener of listeners) listener.dispose();
      panels.delete(key);
      if (lastPreview === state) lastPreview = undefined;
    });
    panel.webview.html = previewHtml(vscode, panel.webview, assetDir);
    return state;
  }

  /** All previews in one request share a main source, but can show different variants.
   * @param {Preview[]} previews @param {boolean} background */
  async function buildPreviews(previews, background) {
    const targets = previews.flatMap((preview) => {
      const target = preview.target;
      const finish = target && preview.markBuilding();
      return finish ? [{ target, finish }] : [];
    });
    if (!targets.length) return;
    const main = targets[0].target.main;
    clearTimeout(saveTimers.get(main.toString())?.timer);
    saveTimers.delete(main.toString());
    const names = targets.map(({ target }) => target.variant);
    /** @type {BuildFinished} */
    const complete = (code, error) => targets.forEach(({ finish }) => finish(code, error));
    try {
      if (!(await compileController.compilePreview(main, names.length === 1 ? names[0] : names,
        { background, onExit: complete }))) complete(undefined);
    } catch (error) {
      complete(undefined, error);
    }
  }

  /** @param {{uri: Uri}[]} roots @param {WorkspaceFolder} folder */
  function previewTargets(roots, folder) {
    const dir = vscode.Uri.joinPath(folder.uri, "result");
    return roots.flatMap(({ uri: main }) => pdfNames(main).map((name, index) => ({
      ...variants[index], main, pdf: vscode.Uri.joinPath(dir, name)
    })));
  }

  /** @param {PreviewTarget[]} targets @param {WorkspaceFolder} folder @param {PreviewAction} action */
  async function selectTarget(targets, folder, action) {
    const open = targets.filter(({ pdf }) => panels.has(pdf.toString()));
    if (action !== "open" && open.length) {
      const preferred = open.find(({ pdf }) => pdf.toString() === lastPreview?.pdf.toString());
      if (preferred) return preferred;
      if (open.length === 1) return open[0];
    }
    const dir = vscode.Uri.joinPath(folder.uri, "result");
    const entries = await Promise.resolve(vscode.workspace.fs.readDirectory(dir)).catch(() => []);
    const files = new Set(entries.filter(([, type]) => type & vscode.FileType.File).map(([name]) => name));
    const built = targets.filter(({ pdf }) => files.has(basename(pdf)));
    const defaults = targets.filter(({ variant }) => variant === "default");
    let buildable = defaults;
    if (action === "compile" && !open.length) {
      const declared = new Map(await Promise.all(defaults.map(async ({ main }) => {
        const bytes = await Promise.resolve(vscode.workspace.fs.readFile(main)).catch(() => undefined);
        return /** @type {const} */ ([main.toString(), declaredPreviewVariants(bytes ? new TextDecoder().decode(bytes) : "")]);
      })));
      buildable = targets.filter(({ main, variant }) => declared.get(main.toString())?.has(variant));
    }
    const choices = action !== "open" && open.length ? open : action === "compile"
      ? [...new Set([...buildable, ...built])] : built.length ? built : defaults;
    if (choices.length === 1) return choices[0];
    return (await vscode.window.showQuickPick(choices.map((target) => ({ label: basename(target.pdf),
      description: files.has(basename(target.pdf)) ? target.label : `${target.label} (not built)`, target })), {
      placeHolder: action === "compile" ? "Select a PDF preview to build" : "Select a songbook PDF preview"
    }))?.target;
  }

  /** @param {PreviewAction} action @param {Uri | {uri: Uri, kind?: string}} [item] */
  async function run(action, item) {
    if (!enabled) return;
    const editor = vscode.window.activeTextEditor;
    const position = editor?.selection.active;
    const entry = item && "uri" in item ? item : undefined;
    const uri = item && "uri" in item ? item.uri : item ?? editor?.document.uri;
    if (action === "compile" && !uri && lastPreview?.target) return lastPreview.build();
    const folder = getWorkspaceFolderForUri(vscode, uri);
    if (!uri || !folder) {
      vscode.window.showInformationMessage("Open a songbook source in the workspace first.");
      return;
    }
    if (action === "open" && /\.pdf$/i.test(uri.path)) {
      const roots = await songbookService.getAllSongbooks(uri);
      const target = previewTargets(roots, folder).find(({ pdf }) => pdf.toString() === uri.toString());
      openPanel(uri, folder, editor, false, target);
      return;
    }
    if (action === "compile" && !canBuild()) {
      vscode.window.showInformationMessage("PDF preview builds require a trusted workspace in desktop VS Code.");
      return;
    }
    const roots = entry?.kind === "songbook" ? [entry] : await songbookService.getAffectedSongbooks(uri);
    if (!roots.length) {
      vscode.window.showInformationMessage("No containing songbooks found for the current file.");
      return;
    }
    const target = await selectTarget(previewTargets(roots, folder), folder, action);
    if (!target || !enabled) return;
    const preview = openPanel(target.pdf, folder, editor, action !== "open", target);
    if (action === "compile") return preview.build();
    if (action === "forward" && position) preview.forward(uri.toString(), position.line + 1);
  }

  /** @param {import('vscode').TextDocument} document @param {Set<string>} [manualBuildTargets] */
  async function saved(document, manualBuildTargets) {
    if (!enabled || !panels.size || !getSettings(vscode).buildPreviewOnSave) return;
    const sequence = ++saveSequence;
    const roots = await songbookService.getAffectedSongbooks(document.uri);
    if (!enabled || !getSettings(vscode).buildPreviewOnSave) return;
    for (const { uri } of roots) {
      const key = uri.toString();
      if (manualBuildTargets?.has(key)) continue;
      const matching = [...panels.values()].filter((panel) => panel.target?.main.toString() === key);
      if (!matching.length) continue;
      const current = saveTimers.get(key);
      if (current && current.sequence > sequence) continue;
      clearTimeout(current?.timer);
      const timer = setTimeout(() => {
        if (saveTimers.get(key)?.sequence !== sequence) return;
        saveTimers.delete(key);
        if (!enabled || !getSettings(vscode).buildPreviewOnSave) return;
        const previews = [...panels.values()].filter((panel) => panel.target?.main.toString() === key);
        void buildPreviews(previews, true);
      }, 350);
      saveTimers.set(key, { timer, sequence });
    }
  }

  /** @type {Record<string, PreviewAction>} */
  const actions = {
    openPdfPreview: "open", compilePdfPreview: "compile", syncToPdf: "forward"
  };
  for (const [command, action] of Object.entries(actions)) {
    context.subscriptions.push(vscode.commands.registerCommand(`ulsbsTexTools.${command}`, async (item) => {
      try {
        await run(action, item);
      } catch (error) {
        vscode.window.showErrorMessage(`ULSBS PDF preview: ${errorText(error)}`);
      }
    }));
  }
  const disposePanels = () => {
    for (const { timer } of saveTimers.values()) clearTimeout(timer);
    saveTimers.clear();
    for (const entry of panels.values()) entry.panel.dispose();
  };
  context.subscriptions.push(vscode.workspace.onDidSaveTextDocument((document) => {
    void saved(document, compileController.getBuildSaveTargets(document.uri))
      .catch((error) => vscode.window.showErrorMessage(`ULSBS build on save: ${errorText(error)}`));
  }));
  context.subscriptions.push({ dispose: disposePanels });
  /** @param {boolean} value */
  function setEnabled(value) {
    enabled = value;
    if (!value) disposePanels();
  }
  return { setEnabled };
}

/** @param {unknown} error */
function errorText(error) {
  return error instanceof Error ? error.message : String(error);
}

/** Render a script-isolated shell; the webview receives PDF bytes by message.
 * @param {typeof import('vscode')} vscode @param {import('vscode').Webview} webview @param {Uri} assetDir */
function previewHtml(vscode, webview, assetDir) {
  const assets = webview.asWebviewUri(assetDir);
  /** @param {string} name */
  const uri = (name) => webview.asWebviewUri(vscode.Uri.joinPath(assetDir, name)).toString();
  const src = webview.cspSource;
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src ${src} 'wasm-unsafe-eval'; style-src ${src} 'unsafe-inline'; img-src ${src} data: blob:; font-src ${src} data: blob:; connect-src ${src}; worker-src blob:; child-src blob:;">
  <title>ULSBS PDF Preview</title>
  <link rel="stylesheet" href="${uri("viewer.css")}">
</head>
<body>
  <header id="pdf-build-toolbar" hidden>
    <button id="pdf-build" type="button">Build Preview</button>
    <span id="pdf-build-status" role="status"></span>
    <span id="pdf-sync-hint">Ctrl-click to jump to source</span>
  </header>
  <main id="pdf-viewer" data-assets="${assets}"></main>
  <p id="pdf-status" role="status">Starting ULSBS PDF preview...</p>
  <script type="module" src="${uri("viewer.js")}"></script>
</body>
</html>`;
}

module.exports = { registerPdfPreview, pdfNames, sourceKey, songOpeningForClosingLine, lilypondOpening, declaredPreviewVariants };
