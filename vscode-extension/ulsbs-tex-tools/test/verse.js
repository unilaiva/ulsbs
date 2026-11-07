// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { tokenizeSongLine } = require("../core/songsyntax");
const { analyzeText } = require("../core/parser");
const { updateVerseState } = require("../core/regions");
const { registerCompletionProvider } = require("../core/completions");
const { registerSymbolProvider } = require("../core/symbols");

const config = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "language-configuration.json"), "utf8"));
const starts = [config.folding.markers.start, config.indentationRules.increaseIndentPattern,
  ...config.onEnterRules.map((rule) => rule.beforeText)];
const ends = [config.folding.markers.end, config.indentationRules.decreaseIndentPattern,
  config.onEnterRules[1].afterText];

let provider;
let symbolProvider;
const vscode = {
  workspace: { getConfiguration: () => ({ get: () => [] }) },
  languages: { registerCompletionItemProvider: (_selector, implementation) => {
    provider = implementation;
    return { dispose() {} };
  }, registerDocumentSymbolProvider: (_selector, implementation) => {
    symbolProvider = implementation;
    return { dispose() {} };
  } },
  Position: class { constructor(line, character) { Object.assign(this, { line, character }); } },
  Range: class { constructor(start, end) { Object.assign(this, { start, end }); } },
  CompletionItem: class { constructor(label) { this.label = label; } },
  CompletionItemKind: { Snippet: 1, Keyword: 2 },
  SnippetString: class { constructor(value) { this.value = value; } },
  SymbolKind: { Module: 1, Namespace: 2, File: 3 },
  DocumentSymbol: class {
    constructor(name, detail, kind, range, selectionRange) {
      Object.assign(this, { name, detail, kind, range, selectionRange, children: [] });
    }
  },
  MarkdownString: class {
    appendMarkdown() {}
    appendCodeblock() {}
  }
};
registerCompletionProvider(vscode, { subscriptions: [] });
registerSymbolProvider(vscode, { subscriptions: [] });

function completions(text) {
  const lines = text.split("\n");
  const line = lines.length - 1;
  const document = {
    uri: { path: "/song.tex" },
    lineAt: (index) => ({ text: lines[index] })
  };
  return provider.provideCompletionItems(document, new vscode.Position(line, lines[line].length)) || [];
}

const variants = ["", "[2]", "*", "*[2]", "+", "+[2]", "*+", "*+[2]"];
for (const suffix of variants) {
  const open = `\\beginverse${suffix}`;
  const tokens = tokenizeSongLine(open, 0);
  assert.deepEqual(tokens.map(({ type, text }) => ({ type, text })),
    [{ type: "beginverse", text: open }], open);

  const analysis = analyzeText(`\\beginsong{Test}\n${open}\n\\beginrep\n\\endrep\n\\endverse\n\\endsong`);
  assert.deepEqual(analysis.issues, [], open);
  const verse = analysis.songs[0].children[0];
  assert.equal(verse.type, "verse", open);
  assert.equal(verse.detail, open);
  assert.equal(verse.openTextLength, open.length);
  assert.equal(verse.endLine, 4);
  assert.equal(verse.children[0].type, "rep");

  assert.deepEqual(updateVerseState(false, open), { lineInVerse: true, nextInVerse: true });
  assert.deepEqual(updateVerseState(true, "\\endverse"), { lineInVerse: true, nextInVerse: false });
  for (const expression of starts) assert.equal(new RegExp(expression).test(open), true, open);
  assert.ok(completions(`\\beginsong{Test}\n${open}\n\\en`).some((item) => item.label.label === "endverse"), open);
  assert.ok(!completions(`\\beginsong{Test}\n${open}\n\\endverse\n\\en`).some((item) => item.label.label === "endverse"), open);
}

const snippets = completions("\\beginsong{Test}\n\\beginver").filter((item) =>
  item.label.label.startsWith("beginverse"));
assert.deepEqual(snippets.map((item) => item.label.label), [
  "beginverse", "beginverse[n]", "beginverse*", "beginverse*[n]",
  "beginverse+", "beginverse+[n]", "beginverse*+", "beginverse*+[n]"
]);
assert.ok(snippets.every((item) => item.insertText.value.endsWith("\\endverse")));
for (const expression of ends) assert.equal(new RegExp(expression).test("\\endverse"), true);
assert.deepEqual(updateVerseState(true, "\\endverse \\beginverse*+[2]"),
  { lineInVerse: true, nextInVerse: true });
assert.deepEqual(updateVerseState(false, "\\beginverse+ \\endverse"),
  { lineInVerse: true, nextInVerse: false });

for (const invalid of ["\\beginverseword", "\\beginverse**", "\\beginverse+[", "\\beginverse+*"]) {
  assert.equal(tokenizeSongLine(invalid, 0).length, 0, invalid);
  for (const expression of starts) assert.equal(new RegExp(expression).test(invalid), false, invalid);
}
assert.match(analyzeText("\\endverse").issues[0].message, /without matching \\beginverse/);
assert.ok(analyzeText("\\beginsong{Test}\n\\beginverse*\n\\beginverse+\n\\endverse\n\\endverse\n\\endsong")
  .issues.some((issue) => issue.message.includes("Nested verse start")));
assert.ok(analyzeText("\\beginsong{Test}\n\\beginverse*+[2]\n\\endsong")
  .issues.some((issue) => issue.message.includes("Unclosed \\beginverse*+[2]")));

const template = fs.readFileSync(path.join(__dirname, "..", "assets", "songbook-template_A5.tex"), "utf8");
assert.match(template, /\\ulToc\b/);
assert.doesNotMatch(template, /\\ulTOC\b/);
assert.match(template, /\\begin\{ulSongs\}\{titleidx,authidx,tagidx\}/);
assert.doesNotMatch(template, /author indices are manual/i);
assert.match(template, /\\end\{ulSongs\}/);
assert.doesNotMatch(template, /\\(?:begin|end)\{songs\}/);

assert.equal(tokenizeSongLine("\\begin{ulSongs}", 0)[0].type, "beginsongsenv");
assert.equal(tokenizeSongLine("\\end{ulSongs}", 0)[0].type, "endsongsenv");
assert.deepEqual(tokenizeSongLine("\\begin{songs}", 0), []);
const book = "\\documentclass{ulsbs-songbook}\n\\begin{ulSongs}{titleidx}\n\\beginsong{Test}\n\\beginverse\nLyrics\n\\endverse\n\\endsong\n\\end{ulSongs}";
assert.deepEqual(analyzeText(book).issues, []);
assert.ok(analyzeText("\\end{ulSongs}").issues.some((issue) =>
  issue.message.includes("without matching \\begin{ulSongs}")));
for (const expression of starts) assert.equal(new RegExp(expression).test("\\begin{ulSongs}"), true);
for (const expression of ends) assert.equal(new RegExp(expression).test("\\end{ulSongs}"), true);
assert.ok(config.brackets.some(([begin, end]) =>
  begin === "\\begin{ulSongs}" && end === "\\end{ulSongs}"));
assert.ok(completions("\\begin{ulS").some((item) => item.label === "ulSongs"));
assert.ok(completions("\\begin{ulSongs}{titleidx}\n\\end{ulS").some((item) => item.label === "ulSongs"));
assert.deepEqual(completions("\\begin{song"), []);

const staticSnippets = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "snippets", "latex.json"), "utf8"));
assert.ok(Object.values(staticSnippets).some((snippet) =>
  Array.isArray(snippet.body) && snippet.body.includes("\\begin{ulSongs}{${1:titleidx,authidx,tagidx}}") &&
  snippet.body.includes("\\end{ulSongs}")));
assert.equal(completions("\\begin{ulS").find((item) => item.label === "ulSongs").insertText.value,
  "ulSongs}{${1:titleidx,authidx,tagidx}}\n$0\n\\end{ulSongs}");
assert.equal(completions("\\begin{pass").find((item) => item.label === "passage").insertText.value,
  "passage}[$1]{${2:Title}}\n$0\n\\end{passage}");
assert.ok(Object.values(staticSnippets).some((snippet) =>
  Array.isArray(snippet.body) && snippet.body.includes("\\begin{passage}[$1]{${2:Title}}")));
for (const suffix of ["PrimaryPosition", "SecondaryPosition", "StyleMapping"]) {
  const name = `ulMelody${suffix}`;
  const item = completions(`\\${name}`).find((entry) => entry.label.label === name);
  assert.ok(item, name);
  assert.ok(item.insertText.value.startsWith(`${name}{`), name);
  assert.ok(Object.values(staticSnippets).some((snippet) =>
    snippet.prefix === name && snippet.body.startsWith(`\\${name}{`)), name);
  assert.deepEqual(completions(`\\melody${suffix}`), [], "No old setting completions");
}

for (const [name, body] of [
  ["ulTagFile", "ulTagFile{${1:tags.txt}}"],
  ["ulNewIndex", "ulNewIndex{${1:customidx}}{${2:idx_custom}}"],
  ["ulNewAuthorIndex", "ulNewAuthorIndex{${1:customidx}}{${2:idx_custom}}"],
  ["ulNewTagIndex", "ulNewTagIndex{${1:customidx}}{${2:idx_custom}}"]
]) {
  const item = completions(`\\${name}`).find((entry) => entry.label.label === name);
  assert.equal(item?.insertText.value, body, name);
  assert.ok(Object.values(staticSnippets).some((snippet) =>
    snippet.prefix === name && snippet.body === `\\${body}`), name);
  assert.deepEqual(completions(`\\begin{document}\n\\${name}`), [], "Preamble-only declaration");
  assert.deepEqual(completions(`\\begin{ulSongs}{}\n\\${name}`), [], "Not inside song blocks");
  assert.deepEqual(completions(`\\beginsong{Test}\n\\${name}`), [], "Not inside songs");
  assert.ok(completions(`% \\begin{document}\n\\${name}`).length, "Ignore commented boundary");
}
assert.ok(Object.values(staticSnippets).some((snippet) =>
  snippet.prefix === "ulIndexTagFont" && snippet.body.includes("\\ulIndexTagFont}")));
for (const name of ["ulNewScriptureIndex", "ulIndexScriptureFont"]) {
  assert.deepEqual(completions(`\\${name}`), [], "No legacy index completions");
  assert.ok(!JSON.stringify(staticSnippets).includes(name), "No legacy public static snippets");
}

const headingCommands = ["ulSongChapter", "ulSongSection", "chapter", "section", "subsection"];
const headingLines = headingCommands.flatMap((name) => [
  `\\${name}{${name} title}`,
  `\\${name}*{${name} starred}`,
  `\\${name}[${name} short]{${name} long}`
]);
const headings = symbolProvider.provideDocumentSymbols({
  uri: { path: "/book.tex" },
  getText: () => headingLines.join("\n")
});
assert.equal(headings.length, headingLines.length);
for (const [index, name] of headingCommands.entries()) {
  assert.deepEqual(headings.slice(index * 3, index * 3 + 3).map((symbol) =>
    [symbol.name, symbol.detail, symbol.selectionRange.start.line]), [
    [`${name} title`, `\\${name}`, index * 3],
    [`${name} starred`, `\\${name}`, index * 3 + 1],
    [`${name} short`, `\\${name}`, index * 3 + 2]
  ]);
}
assert.deepEqual(symbolProvider.provideDocumentSymbols({
  uri: { path: "/book.tex" },
  getText: () => "\\songchapter{Not a public command}"
}), []);
