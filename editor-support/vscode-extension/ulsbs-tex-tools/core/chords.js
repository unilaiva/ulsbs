// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Decorations for ULSBS chord markup and melody blocks inside verse lines.
 * @module
 */

const { stripComment } = require("./parser");
const { shouldProcessDocument } = require("./filetypes");
const { updateVerseState } = require("./regions");
const { registerActiveEditorUpdater } = require("./editor-updater");

/** @param {string} ch */
function isLetter(ch) {
  return /[A-Za-z@]/.test(ch);
}

/**
 * Parse a balanced group like `{...}` or `[...]` starting at `startIndex`.
 * Returns the index *after* the closing delimiter.
 * @param {string} text
 * @param {number} startIndex
 * @param {string} openChar
 * @param {string} closeChar
 * @returns {{endIndex: number}}
 */
function parseBalancedGroup(text, startIndex, openChar, closeChar) {
  // startIndex points at openChar
  if (text[startIndex] !== openChar) {
    return { endIndex: startIndex + 1 };
  }

  let depth = 0;
  let i = startIndex;

  while (i < text.length) {
    const ch = text[i];

    // Skip escaped characters like \{ \} \]
    if (ch === "\\") {
      i += 2;
      continue;
    }

    if (ch === openChar) {
      depth += 1;
    } else if (ch === closeChar) {
      depth -= 1;
      if (depth === 0) {
        return { endIndex: i + 1 };
      }
    }

    i += 1;
  }

  // Unbalanced; consume to end.
  return { endIndex: text.length };
}

/**
 * Find ranges inside `\\[ ... ]` content to decorate as chords/melody.
 * @param {string} content
 * @param {number} baseOffsetInLine Offset where `content` starts in the full line.
 */
function getDecorationRangesInBracketContent(content, baseOffsetInLine) {
  const chordRanges = [];
  const melodyRanges = [];
  const melodyDelimiterRanges = [];
  const unclosedMelodyRanges = [];

  let chordStart = null;

  function flushChord(endPos) {
    if (chordStart === null) return;
    if (endPos > chordStart) {
      chordRanges.push({
        start: baseOffsetInLine + chordStart,
        end: baseOffsetInLine + endPos
      });
    }
    chordStart = null;
  }

  function pushMelodyTokenRanges(blockStart, blockEndExclusive) {
    const block = content.slice(blockStart + 1, blockEndExclusive - 1);
    const offsetIndex = block.indexOf("@");
    const sequences = offsetIndex === -1 ? block : block.slice(0, offsetIndex);
    // Whitespace is optional: decorate each pitch or marker separately.
    const tokenPattern = /[A-G](?:[#&])?|[_*/]/g;
    let match;

    while ((match = tokenPattern.exec(sequences))) {
      melodyRanges.push({
        start: baseOffsetInLine + blockStart + 1 + match.index,
        end: baseOffsetInLine + blockStart + 1 + match.index + match[0].length
      });
    }
  }

  const melodyBlockStart = content.startsWith("^<") ? 1 : content.startsWith("<") ? 0 : -1;
  let i = 0;
  while (i < content.length) {
    const ch = content[i];

    if (i === 0 && melodyBlockStart === 1) {
      // A leading caret belongs to the annotation, not the chord remainder.
      i += 1;
      continue;
    }

    if (ch === "<" && i === melodyBlockStart) {
      flushChord(i);
      const blockEnd = content.indexOf(">", i + 1);
      if (content[i + 1] === "!") {
        melodyDelimiterRanges.push({
          start: baseOffsetInLine + i + 1,
          end: baseOffsetInLine + i + 2
        });
      }
      if (blockEnd === -1) {
        unclosedMelodyRanges.push({
          start: baseOffsetInLine + i,
          end: baseOffsetInLine + i + 1
        });
        pushMelodyTokenRanges(i, content.length + 1);
        break;
      }
      melodyDelimiterRanges.push(
        { start: baseOffsetInLine + i, end: baseOffsetInLine + i + 1 },
        { start: baseOffsetInLine + blockEnd, end: baseOffsetInLine + blockEnd + 1 }
      );
      pushMelodyTokenRanges(i, blockEnd + 1);
      i = blockEnd + 1;
      continue;
    }

    if (ch === "\\") {
      flushChord(i);
      i += 1;

      if (i >= content.length) {
        break;
      }

      // Control sequence name
      let name = "";
      if (isLetter(content[i])) {
        const nameStart = i;
        while (i < content.length && isLetter(content[i])) {
          i += 1;
        }
        name = content.slice(nameStart, i);
      } else {
        name = content[i];
        i += 1;
      }

      // Optional args: [ ... ] (skip, do not treat as chord)
      while (i < content.length && content[i] === "[") {
        const parsed = parseBalancedGroup(content, i, "[", "]");
        i = parsed.endIndex;
      }

      // Mandatory args: { ... } (skip; do not treat as chord content)
      while (i < content.length && content[i] === "{") {
        const parsed = parseBalancedGroup(content, i, "{", "}");
        i = parsed.endIndex;
      }

      continue;
    }

    if (ch === "{") {
      // A brace group without a macro prefix; treat as non-chord content.
      flushChord(i);
      const parsed = parseBalancedGroup(content, i, "{", "}");
      i = parsed.endIndex;
      continue;
    }

    if (/\s/.test(ch)) {
      flushChord(i);
      i += 1;
      continue;
    }

    // Normal chord characters
    if (chordStart === null) {
      chordStart = i;
    }

    i += 1;
  }

  flushChord(content.length);
  return { chordRanges, melodyRanges, melodyDelimiterRanges, unclosedMelodyRanges };
}

function findBracketSegments(line) {
  // Returns [{ openIndex, closeIndex }] for each \[ ... ] pair on the line.
  const segments = [];
  let i = 0;

  while (i < line.length) {
    const open = line.indexOf("\\[", i);
    if (open === -1) {
      break;
    }

    const close = line.indexOf("]", open + 2);
    if (close === -1) {
      break;
    }

    segments.push({ openIndex: open, closeIndex: close });
    i = close + 1;
  }

  return segments;
}

/**
 * Register live chord/melody decorations for the active editor.
 * @param {import('vscode')} vscode
 * @param {import('vscode').ExtensionContext} context
 */
function registerChordDecorations(vscode, context) {
  const chordDecorationType = vscode.window.createTextEditorDecorationType({
    fontWeight: "bold"
  });

  const melodyDecorationType = vscode.window.createTextEditorDecorationType({
    fontStyle: "italic"
  });
  const melodyDelimiterDecorationType = vscode.window.createTextEditorDecorationType({
    color: new vscode.ThemeColor("editorCodeLens.foreground")
  });
  const unclosedMelodyDecorationType = vscode.window.createTextEditorDecorationType({
    color: new vscode.ThemeColor("editorError.foreground"),
    textDecoration: "underline wavy"
  });

  async function updateEditor(editor) {
    if (!editor) {
      return;
    }

    const document = editor.document;
    if (!shouldProcessDocument(vscode, document)) {
      editor.setDecorations(chordDecorationType, []);
      editor.setDecorations(melodyDecorationType, []);
      editor.setDecorations(melodyDelimiterDecorationType, []);
      editor.setDecorations(unclosedMelodyDecorationType, []);
      return;
    }

    const lines = document.getText().split(/\r?\n/);

    const chordRanges = [];
    const melodyRanges = [];
    const melodyDelimiterRanges = [];
    const unclosedMelodyRanges = [];

    let inVerse = false;

    for (let lineIndex = 0; lineIndex < lines.length; lineIndex++) {
      const rawLine = lines[lineIndex];
      const code = stripComment(rawLine);

      const { lineInVerse, nextInVerse } = updateVerseState(inVerse, code);

      if (lineInVerse) {
        const segments = findBracketSegments(code);

        for (const seg of segments) {
          const contentStart = seg.openIndex + 2;
          const contentEnd = seg.closeIndex;
          const content = code.slice(contentStart, contentEnd);

          const ranges = getDecorationRangesInBracketContent(content, contentStart);

          for (const r of ranges.chordRanges) {
            if (r.end <= r.start) continue;
            chordRanges.push(
              new vscode.Range(
                new vscode.Position(lineIndex, r.start),
                new vscode.Position(lineIndex, r.end)
              )
            );
          }

          for (const r of ranges.melodyRanges) {
            if (r.end <= r.start) continue;
            melodyRanges.push(
              new vscode.Range(
                new vscode.Position(lineIndex, r.start),
                new vscode.Position(lineIndex, r.end)
              )
            );
          }

          for (const r of ranges.melodyDelimiterRanges) {
            melodyDelimiterRanges.push(
              new vscode.Range(
                new vscode.Position(lineIndex, r.start),
                new vscode.Position(lineIndex, r.end)
              )
            );
          }

          for (const r of ranges.unclosedMelodyRanges) {
            unclosedMelodyRanges.push(
              new vscode.Range(
                new vscode.Position(lineIndex, r.start),
                new vscode.Position(lineIndex, r.end)
              )
            );
          }
        }
      }

      inVerse = nextInVerse;
    }

    editor.setDecorations(chordDecorationType, chordRanges);
    editor.setDecorations(melodyDecorationType, melodyRanges);
    editor.setDecorations(melodyDelimiterDecorationType, melodyDelimiterRanges);
    editor.setDecorations(unclosedMelodyDecorationType, unclosedMelodyRanges);
  }

  context.subscriptions.push(
    chordDecorationType,
    melodyDecorationType,
    melodyDelimiterDecorationType,
    unclosedMelodyDecorationType
  );

  const updater = registerActiveEditorUpdater(vscode, context, updateEditor);

  return {
    refreshActive: updater.refreshActive
  };
}

module.exports = {
  registerChordDecorations
};
