// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { tokenizeSongLine } = require("../core/songsyntax");
const { analyzeText } = require("../core/parser");
const { updateVerseState } = require("../core/regions");
const { registerCompletionProvider } = require("../core/completions");

const config = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "language-configuration.json"), "utf8"));
const starts = [config.folding.markers.start, config.indentationRules.increaseIndentPattern,
  ...config.onEnterRules.map((rule) => rule.beforeText)];
const ends = [config.folding.markers.end, config.indentationRules.decreaseIndentPattern,
  config.onEnterRules[1].afterText];

let provider;
const vscode = {
  workspace: { getConfiguration: () => ({ get: () => [] }) },
  languages: { registerCompletionItemProvider: (_selector, implementation) => {
    provider = implementation;
    return { dispose() {} };
  } },
  Position: class { constructor(line, character) { Object.assign(this, { line, character }); } },
  Range: class { constructor(start, end) { Object.assign(this, { start, end }); } },
  CompletionItem: class { constructor(label) { this.label = label; } },
  CompletionItemKind: { Snippet: 1, Keyword: 2 },
  SnippetString: class { constructor(value) { this.value = value; } },
  MarkdownString: class {
    appendMarkdown() {}
    appendCodeblock() {}
  }
};
registerCompletionProvider(vscode, { subscriptions: [] });

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
