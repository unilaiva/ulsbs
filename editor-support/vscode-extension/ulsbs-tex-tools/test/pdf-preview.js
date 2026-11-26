// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/** Exercise the preview controller's commands, webview protocol, and reload lifecycle. */
const assert = require("node:assert/strict");
const { posix } = require("node:path");
const { test } = require("node:test");
const { setTimeout: delay } = require("node:timers/promises");
const { gzipSync } = require("node:zlib");
const { pdfNames, sourceKey, registerPdfPreview, songOpeningForClosingLine, lilypondOpening, declaredPreviewVariants } = require("../core/pdf-preview");
const { findSourceWordColumn } = require("../core/pdf-source-word");

function uri(path) {
  return {
    path,
    fsPath: path,
    toString: () => `file://${encodeURI(path)}`,
    with: (changes) => uri(changes.path ?? path)
  };
}

const Uri = {
  joinPath: (root, ...parts) => uri(posix.join(root.path, ...parts)),
  parse: (value) => uri(decodeURI(value.slice("file://".length)))
};

test("word sync matches literal text, not TeX syntax or a repeated word", () => {
  const lyric = String.raw`  \[<E G>Am]One \emph{mor\[G]ning} |ex^tra sunshine % morning`;
  assert.equal(findSourceWordColumn(lyric, "morning"), lyric.indexOf("mor"));
  assert.equal(findSourceWordColumn(lyric, "extra"), lyric.indexOf("ex^tra"));
  assert.equal(findSourceWordColumn(lyric, "One"), lyric.indexOf("One"));
  assert.equal(findSourceWordColumn(lyric, "Am"), undefined);
  assert.equal(findSourceWordColumn(lyric, "emph"), undefined);
  assert.equal(findSourceWordColumn(lyric, "sun"), undefined);
  assert.equal(findSourceWordColumn(lyric, "One morning"), undefined);
  assert.equal(findSourceWordColumn("shine, then shine", "shine"), undefined);
  assert.equal(findSourceWordColumn(String.raw` \label{shine}`, "shine"), undefined);
  assert.equal(findSourceWordColumn(String.raw` one \[shine`, "shine"), undefined);
  assert.equal(findSourceWordColumn("  Let life flourish.", "\ufb02ourish"), 11);
  assert.equal(findSourceWordColumn("  It's pa\u0303o.", "It\u2019s"), 2);
  assert.equal(findSourceWordColumn("  It's pa\u0303o.", "p\u00e3o"), 7);
  assert.equal(findSourceWordColumn("  Sing bem-te-vi!", "bem\u2011te\u2011vi"), 7);
  assert.equal(findSourceWordColumn("\u{1f31e} daylight", "daylight"), 3);
});

test("only ordinary compiler artifact names are suggested", () => {
  assert.deepEqual(pdfNames(uri("/songs/Some Book_A5.latex")), [
    "Some Book_A5.pdf", "Some Book_LYRICS-ONLY_A5.pdf", "Some Book_CHARANGO_A5.pdf", "Some Book_BASSCLEF_A5.pdf"
  ]);
  assert.equal(pdfNames(uri("/songs/book.v3.tex"))[1], "book.v3_LYRICS-ONLY.pdf");
});

test("preview build can offer literal variants that have not been built yet", () => {
  assert.deepEqual([...declaredPreviewVariants(String.raw`
% \documentclass[variants={default,bassclef}]{ulsbs-songbook}
\documentclass[paper=a5,
 variants={default, lyric, charango}]{ulsbs-songbook-fixture}
\begin{document}`)], ["default", "lyric", "charango"]);
  assert.deepEqual([...declaredPreviewVariants(String.raw`\documentclass{ulsbs-songbook}`)], ["default"]);
});

test("SyncTeX paths keep their full names inside the project", () => {
  const root = uri("/workspace");
  const pdfDir = uri("/workspace/result");
  const key = (name) => sourceKey({ Uri }, root, pdfDir, name);
  assert.equal(key("/workspace/content/first/á song.tex"), uri("/workspace/content/first/á song.tex").toString());
  assert.equal(key("../content/second/song.tex"), uri("/workspace/content/second/song.tex").toString());
  assert.equal(key("/workspace-other/song.tex"), null);
  assert.equal(key("../content/../../other.tex"), null);
  assert.equal(key("/workspace/temp/snippet-systems.tex"), null);
  assert.equal(sourceKey({ Uri }, uri("/c:/project"), uri("/c:/project/result"), "..\\content\\song.tex"),
    uri("/c:/project/content/song.tex").toString());
});

/** One-page SyncTeX v1 document with two independent source lines. */
function sidecar(line, score = false) {
  return gzipSync(`SyncTeX Version:1
Input:1:/project/content/song.tex
Output:pdf
Magnification:1000
Unit:1
X Offset:0
Y Offset:0
Content:
{1
(1,${line}:6578176,6578176:6578176,657817,0
${score ? `(2,1:6578176,6578176:6578176,657817,0
)` : `x1,${line}:7235994,6578176`}
)
}1
${score ? "Input:2:/project/temp/work/test-systems.tex\n" : ""}Postamble:
Count:5
Post scriptum:
`);
}

function fixture(lines = []) {
  const project = uri("/project");
  const document = {
    uri: uri("/project/content/song.tex"), lineCount: 20,
    lineAt(lineNumber) {
      const text = lines[lineNumber] ?? "  Singing brings joy and joy";
      return { lineNumber, text, firstNonWhitespaceCharacterIndex: text.length - text.trimStart().length };
    }
  };
  const pdf = uri("/project/result/book_A5.pdf");
  const lyric = uri("/project/result/book_LYRICS-ONLY_A5.pdf");
  const commands = {};
  const sent = [];
  const warnings = [];
  const builds = [];
  const disposable = { dispose() {} };
  let onMessage, onSave, shown, created = 0, pick, buildOnSave = false;
  const watchers = [];
  const files = new Map();
  const newPanel = () => {
    let onDispose;
    return {
    viewColumn: 2,
    reveal() {},
    dispose() { onDispose(); },
    onDidDispose(callback) { onDispose = callback; },
    onDidChangeViewState() { return disposable; },
    webview: {
      asWebviewUri: (value) => value,
      cspSource: "https://webview.invalid",
      onDidReceiveMessage(callback) { onMessage = callback; return disposable; },
      async postMessage(message) { sent.push(message); return true; }
    }
    };
  };
  const vscode = {
    Uri,
    FileType: { File: 1 }, ViewColumn: { One: 1, Two: 2, Beside: -2 },
    RelativePattern: class {},
    Position: class { constructor(line, character) { Object.assign(this, { line, character }); } },
    Range: class { constructor(start, end) { Object.assign(this, { start, end }); } },
    UIKind: { Desktop: 1, Web: 2 }, env: { uiKind: 1 },
    FileSystemError: class extends Error { code = "FileNotFound"; },
    workspace: {
      isTrusted: true,
      onDidGrantWorkspaceTrust() { return disposable; },
      getWorkspaceFolder: () => ({ uri: project }),
      getConfiguration: () => ({ get: (name) => name === "buildPreviewOnSave" ? buildOnSave : undefined }),
      onDidSaveTextDocument(callback) { onSave = callback; return disposable; },
      fs: {
        async readDirectory() { return [...files.keys()].map((path) => [posix.basename(path), 1]); },
        async readFile(path) {
          if (files.has(path.path)) return files.get(path.path);
          throw new vscode.FileSystemError("File not found");
        }
      },
      createFileSystemWatcher: () => ({
        onDidCreate(callback) { watchers.push(callback); return disposable; },
        onDidChange() { return disposable; },
        onDidDelete() { return disposable; },
        dispose() {}
      }),
      async openTextDocument(source) { assert.equal(source.path, document.uri.path); return document; }
    },
    commands: {
      registerCommand(name, command) { commands[name] = command; return disposable; }
    },
    window: {
      activeTextEditor: { document, selection: { active: { line: 6 } }, viewColumn: 1 },
      visibleTextEditors: [],
      createWebviewPanel() { ++created; return newPanel(); },
      async showQuickPick(items) { return pick ? items.find((item) => item.label === pick) : items[0]; },
      showInformationMessage(message) { warnings.push(message); },
      showWarningMessage(message) { warnings.push(message); },
      showErrorMessage(message) { warnings.push(message); },
      async showTextDocument(doc, options) { shown = { doc, options }; }
    }
  };
  let manualBuildTargets;
  const controller = registerPdfPreview(vscode, { extensionUri: uri("/extension"), subscriptions: [] },
    { getAffectedSongbooks: async () => [{ uri: uri("/project/book_A5.tex") }] },
    { compilePreview: async (main, variant, options) => { builds.push({ main, variant, options }); return true; },
      getBuildSaveTargets: () => manualBuildTargets });
  controller.setEnabled(true);
  return {
    sent, warnings, builds, controller,
    command: (name) => commands[`ulsbsTexTools.${name}`](),
    receive: (message) => onMessage(message),
    save: (path = document.uri.path) => onSave({ uri: uri(path) }),
    saveForManualBuild() {
      manualBuildTargets = new Set([uri("/project/book_A5.tex").toString()]);
      onSave({ uri: document.uri });
      manualBuildTargets = undefined;
    },
    pick: (label) => { pick = label; },
    enableBuildOnSave: () => { buildOnSave = true; },
    replace: (line, score = false, variant = "default", sync = true) => {
      // The desktop provider can return a Buffer view into a larger allocation.
      const bytes = Buffer.from([0, 1, 2, 0]).subarray(1, 3);
      const target = variant === "lyric" ? lyric : pdf;
      files.set(target.path, bytes);
      if (sync) files.set(target.path.replace(".pdf", ".synctex.gz"), sidecar(line, score));
      for (const watch of watchers) watch(target);
    },
    get shown() { return shown; },
    get created() { return created; }
  };
}

test("preview waits for a build, synchronizes both ways, and updates to replaced artifacts", async () => {
  const view = fixture();
  await view.command("compilePdfPreview");
  view.receive({ type: "ready" });
  await waitFor(() => view.sent.some(({ type }) => type === "waiting"));
  view.replace(7);
  await waitFor(() => view.sent.at(-1)?.type === "load");
  const { revision, buffer } = view.sent.at(-1);
  assert.ok(buffer instanceof ArrayBuffer, "payload survives VS Code's binary message serialization");
  assert.deepEqual([...new Uint8Array(buffer)], [1, 2]);
  await view.command("syncToPdf");
  assert.equal(view.created, 1);
  assert.ok(!view.sent.some(({ type }) => type === "forward"));
  view.receive({ type: "loaded", revision, page: 1 });
  await waitFor(() => view.sent.at(-1)?.type === "forward" || view.warnings.length);
  assert.deepEqual(view.warnings, []);
  const { point } = view.sent.at(-1);
  assert.equal(point.page, 1);
  view.receive({ type: "inverse", revision, ...point, word: "brings" });
  await waitFor(() => Boolean(view.shown));
  assert.equal(view.shown.options.viewColumn, 1);
  assert.equal(view.shown.options.selection.start.line, 6);
  assert.equal(view.shown.options.selection.start.character, 10);
  view.receive({ type: "inverse", revision, ...point, word: "joy" });
  await waitFor(() => view.shown.options.selection.start.character === 2);
  view.replace(12);
  await waitFor(() => view.sent.at(-1)?.type === "load");
  const next = view.sent.at(-1).revision;
  assert.ok(next > revision);
  view.receive({ type: "loaded", revision: next, page: 1 });
  view.receive({ type: "inverse", revision: next, ...point });
  await waitFor(() => view.shown.options.selection.start.line === 11);
  view.controller.setEnabled(false);
});

test("opening without a PDF does not compile; Build Preview completes a queued sync", async () => {
  const view = fixture();
  await view.command("syncToPdf");
  view.receive({ type: "ready" });
  await waitFor(() => view.sent.some(({ type }) => type === "waiting"));
  assert.equal(view.builds.length, 0);
  view.replace(7, false, "default", false);
  await waitFor(() => view.sent.at(-1)?.type === "load");
  view.receive({ type: "loaded", revision: view.sent.at(-1).revision, page: 1 });
  await waitFor(() => view.sent.at(-1)?.message?.includes("enable source sync"));
  view.receive({ type: "build" });
  await waitFor(() => view.builds.length === 1);
  view.replace(7);
  await waitFor(() => view.sent.at(-1)?.type === "load");
  view.receive({ type: "loaded", revision: view.sent.at(-1).revision, page: 1 });
  await waitFor(() => view.sent.at(-1)?.type === "forward");
  view.controller.setEnabled(false);
});

test("preview builds target the current variant and save batches all open variants", async () => {
  const view = fixture();
  view.replace(7);
  view.replace(7, false, "lyric");
  await view.command("openPdfPreview");
  view.pick("book_LYRICS-ONLY_A5.pdf");
  await view.command("openPdfPreview");
  assert.equal(view.created, 2);
  assert.equal(view.builds.length, 0);
  await view.command("compilePdfPreview");
  assert.deepEqual(view.builds.map(({ variant }) => variant), ["lyric"]);
  assert.equal(view.builds[0].options.background, false);
  view.enableBuildOnSave();
  view.save();
  view.save();
  await waitFor(() => view.builds.length === 2);
  assert.deepEqual(view.builds[1].variant, ["default", "lyric"]);
  assert.equal(view.builds[1].options.background, true);
  view.saveForManualBuild();
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.equal(view.builds.length, 2, "manual build saves must not restart their own previews");
  view.controller.setEnabled(false);
});

test("a generated song prelude jumps to the matching song declaration", async () => {
  const view = fixture([
    String.raw`\beginsong{First}`,
    String.raw`\endsong`,
    String.raw`    \beginsong`,
    "{Second}",
    String.raw`% \beginsong{Not a song}`,
    "  Sing here",
    String.raw`  \endsong % prelude is rendered here`
  ]);
  view.replace(7);
  await view.command("openPdfPreview");
  view.receive({ type: "ready" });
  await waitFor(() => view.sent.at(-1)?.type === "load");
  const { revision } = view.sent.at(-1);
  view.receive({ type: "loaded", revision, page: 1 });
  view.receive({ type: "inverse", revision, page: 1, x: 105, y: 95, word: "Second" });
  await waitFor(() => Boolean(view.shown));
  assert.equal(view.shown.options.selection.start.line, 2);
  assert.equal(view.shown.options.selection.start.character, 4);
  view.controller.setEnabled(false);
});

test("song-boundary refinement supports the song environment and leaves uncertain hits alone", () => {
  function opening(lines) {
    const document = { lineAt: (lineNumber) => ({ lineNumber, text: lines[lineNumber] }) };
    return songOpeningForClosingLine(document, document.lineAt(lines.length - 1))?.lineNumber;
  }
  assert.equal(opening([String.raw`\begin {song}{Title}`, "lyrics", String.raw`\end{song}`]), 0);
  assert.equal(opening([String.raw`\beginsong{Title}`, String.raw`some lyrics \endsong`]), undefined);
  assert.equal(opening([String.raw`\beginsong{Title}`, String.raw`\endsong`, "other content", String.raw`\endsong`]), undefined);
  assert.equal(opening([String.raw`% \beginsong{Title}`, String.raw`\endsong`]), undefined);
});

test("LilyPond clicks jump to the owning score instead of the song boundary", async () => {
  const view = fixture([
    String.raw`\beginsong{A Song}`,
    String.raw`  \begin{lilywrap}\begin{lilypond}[]`,
    "    c d e f",
    String.raw`  \end{lilypond}\end{lilywrap}`,
    String.raw`  % \lilypondfile{not-a-score.ly}`,
    "",
    String.raw`\endsong`
  ]);
  view.replace(7, true);
  await view.command("openPdfPreview");
  view.receive({ type: "ready" });
  await waitFor(() => view.sent.at(-1)?.type === "load");
  const { revision } = view.sent.at(-1);
  view.receive({ type: "loaded", revision, page: 1 });
  view.receive({ type: "inverse", revision, page: 1, x: 105, y: 95, word: "e" });
  await waitFor(() => Boolean(view.shown));
  assert.equal(view.shown.options.selection.start.line, 1);
  assert.equal(view.shown.options.selection.start.character, 18);
  view.controller.setEnabled(false);
});

test("LilyPond source matching handles file includes and does not cross song boundaries", () => {
  function opening(lines) {
    return lilypondOpening({ lineAt: (line) => ({ text: lines[line] }) }, lines.length - 1);
  }
  assert.deepEqual(opening([String.raw`    \lilypondfile[fragment]{one.ly}`, String.raw`\endsong`]), { line: 0, character: 4 });
  assert.equal(opening([String.raw`\lilypondfile{one.ly}`, String.raw`\beginsong{Other}`, "lyrics"]), undefined);
  assert.equal(opening([String.raw`\lilypondfile{one.ly}`, String.raw`\endsong`, "other material"]), undefined);
});

async function waitFor(predicate) {
  for (let attempt = 0; attempt < 100; ++attempt) {
    if (predicate()) return;
    await delay(10);
  }
  assert.fail("Timed out waiting for preview event");
}
