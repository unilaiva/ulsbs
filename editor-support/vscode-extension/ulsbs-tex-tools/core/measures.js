// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Decorations for measure bars (`|`) inside verse/lilypond regions.
 * @module
 */

const { stripComment } = require("./parser");
const { shouldProcessDocument } = require("./filetypes");
const { updateVerseState, updateLilypondState } = require("./regions");
const { registerActiveEditorUpdater } = require("./editor-updater");

/**
 * Register live editor decorations for measure bars.
 * @param {import('vscode')} vscode
 * @param {import('vscode').ExtensionContext} context
 */
function registerMeasureBarDecorations(vscode, context) {
  const decorationType = vscode.window.createTextEditorDecorationType({
    color: new vscode.ThemeColor("editorCodeLens.foreground"),
    //backgroundColor: new vscode.ThemeColor("editor.wordHighlightBackground"),
    //borderRadius: "2px"
  });

  async function updateEditor(editor) {
    if (!editor) {
      return;
    }

    const document = editor.document;
    if (!shouldProcessDocument(vscode, document)) {
      editor.setDecorations(decorationType, []);
      return;
    }

    const text = document.getText();
    const lines = text.split(/\r?\n/);

    const ranges = [];
    let inVerse = false;
    let inLilypond = false;

    for (let lineIndex = 0; lineIndex < lines.length; lineIndex++) {
      const rawLine = lines[lineIndex];
      const code = stripComment(rawLine);

      const { lineInVerse, nextInVerse } = updateVerseState(inVerse, code);
      const { lineInLily, nextInLily } = updateLilypondState(inLilypond, code);

      const lineInRegion = lineInVerse || lineInLily;

      if (lineInRegion) {
        for (let col = 0; col < code.length; col++) {
          if (code[col] === "|") {
            const start = new vscode.Position(lineIndex, col);
            const end = new vscode.Position(lineIndex, col + 1);
            ranges.push(new vscode.Range(start, end));
          }
        }
      }

      inVerse = nextInVerse;
      inLilypond = nextInLily;
    }

    editor.setDecorations(decorationType, ranges);
  }

  context.subscriptions.push(decorationType);

  // Keep decorations up to date for the active editor.
  return registerActiveEditorUpdater(vscode, context, updateEditor);
}

module.exports = {
  registerMeasureBarDecorations
};
