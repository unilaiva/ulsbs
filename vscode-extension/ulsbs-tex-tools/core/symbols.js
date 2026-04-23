// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * DocumentSymbol provider for ULSBS TeX.
 * Powers the VS Code Outline view.
 * @module
 */

const { analyzeText, stripComment } = require("./parser");
const { getDocumentSelector, shouldProcessDocument } = require("./filetypes");

function pos(vscode, line, ch) {
  return new vscode.Position(line, ch);
}

function range(vscode, startLine, startChar, endLine, endChar) {
  return new vscode.Range(
    pos(vscode, startLine, startChar),
    pos(vscode, endLine, endChar)
  );
}

function clampSelectionEnd(startChar, openTextLength) {
  const len = Number.isFinite(openTextLength) ? openTextLength : 1;
  return startChar + Math.max(1, len);
}

/**
 * @param {import('vscode')} vscode
 * @param {string} name
 * @param {string} detail
 * @param {import('vscode').SymbolKind} kind
 * @param {{startLine:number,startChar:number,endLine:number,endChar:number,openTextLength?:number}} span
 */
function makeSpanSymbol(vscode, name, detail, kind, span) {
  const fullRange = range(vscode, span.startLine, 0, span.endLine, span.endChar);
  const selection = range(
    vscode,
    span.startLine,
    span.startChar,
    span.startLine,
    clampSelectionEnd(span.startChar, span.openTextLength)
  );

  return new vscode.DocumentSymbol(name, detail, kind, fullRange, selection);
}

/**
 * Convert the parser outline nodes into VS Code DocumentSymbols.
 * @param {import('vscode')} vscode
 * @param {any} node
 * @returns {import('vscode').DocumentSymbol|null}
 */
function symbolFromOutlineNode(vscode, node) {
  const kindByType = {
    song: vscode.SymbolKind.Module,
    verse: vscode.SymbolKind.Namespace,
    mnverse: vscode.SymbolKind.Namespace,
    translation: vscode.SymbolKind.Namespace,
    lilypond: vscode.SymbolKind.Namespace,
    explanation: vscode.SymbolKind.Namespace,
    passage: vscode.SymbolKind.Namespace,
    feeler: vscode.SymbolKind.Namespace,
    intersong: vscode.SymbolKind.Namespace
  };

  const kind = kindByType[node.type];
  if (!kind) {
    return null;
  }

  const symbol = makeSpanSymbol(vscode, node.name, node.detail, kind, node);

  for (const child of node.children ?? []) {
    // Rep blocks are intentionally kept out of the outline for now.
    if (child.type === "rep") {
      continue;
    }

    const childSymbol = symbolFromOutlineNode(vscode, child);
    if (childSymbol) {
      symbol.children.push(childSymbol);
    }
  }

  return symbol;
}

/**
 * Register the symbol provider.
 * @param {import('vscode')} vscode
 * @param {import('vscode').ExtensionContext} context
 */
function registerSymbolProvider(vscode, context) {
  const provider = vscode.languages.registerDocumentSymbolProvider(
    getDocumentSelector(),
    {
      provideDocumentSymbols(document) {
        try {
          if (!shouldProcessDocument(vscode, document)) {
            return [];
          }

          const text = document.getText();
          const lines = text.split(/\r?\n/);

          // 1) Song/ULSBS structure from the shared parser.
          const analysis = analyzeText(text);
          const outlineSymbols = (analysis.outline ?? [])
            .map((node) => symbolFromOutlineNode(vscode, node))
            .filter(Boolean);

          // 2) Single-line structural macros that are useful in the outline,
          // even outside of ULSBS song environments.
          const tokenDefs = [
            {
              type: "ulmainchapter",
              regex: /\\ulMainChapter\*?(?:\[(.*?)\])?\{([^}]*)\}\{([^}]*)\}(?:\[(.*?)\])?/g
            },
            {
              type: "chapter",
              regex: /\\chapter\*?(?:\[(.*?)\])?\{([^}]*)\}/g
            },
            {
              type: "songchapter",
              regex: /\\songchapter\*?(?:\[(.*?)\])?\{([^}]*)\}/g
            },
            {
              type: "section",
              regex: /\\section\*?(?:\[(.*?)\])?\{([^}]*)\}/g
            },
            {
              type: "subsection",
              regex: /\\subsection\*?(?:\[(.*?)\])?\{([^}]*)\}/g
            },
            {
              type: "includegraphics",
              regex: /\\includegraphics(?:\[[^\]]*])?\{([^}]*)\}/g
            },
            {
              type: "image",
              regex: /\\image[a-zA-Z]*\s*(?:\[[^\]]*])?\{([^}]*)\}/g
            }
          ];

          /** @type {{line: number, ch: number, symbol: import('vscode').DocumentSymbol}[]} */
          const atomic = [];

          for (let lineIndex = 0; lineIndex < lines.length; lineIndex++) {
            const code = stripComment(lines[lineIndex]);

            for (const def of tokenDefs) {
              def.regex.lastIndex = 0;
              let match;
              while ((match = def.regex.exec(code)) !== null) {
                const start = match.index;
                const end = match.index + match[0].length;

                if (def.type === "ulmainchapter") {
                  const shortTitle = (match[1] || "").trim();
                  const longTitle = (match[2] || "").trim();
                  const name = shortTitle || longTitle || "Chapter";

                  atomic.push({
                    line: lineIndex,
                    ch: start,
                    symbol: new vscode.DocumentSymbol(
                      name,
                      "\\ulMainChapter",
                      vscode.SymbolKind.Namespace,
                      range(vscode, lineIndex, start, lineIndex, end),
                      range(vscode, lineIndex, start, lineIndex, end)
                    )
                  });
                  continue;
                }

                if (def.type === "chapter" || def.type === "songchapter") {
                  const shortTitle = (match[1] || "").trim();
                  const longTitle = (match[2] || "").trim();
                  const name = shortTitle || longTitle || "Chapter";
                  const detail = def.type === "chapter" ? "\\chapter" : "\\songchapter";

                  atomic.push({
                    line: lineIndex,
                    ch: start,
                    symbol: new vscode.DocumentSymbol(
                      name,
                      detail,
                      vscode.SymbolKind.Namespace,
                      range(vscode, lineIndex, start, lineIndex, end),
                      range(vscode, lineIndex, start, lineIndex, end)
                    )
                  });
                  continue;
                }

                if (def.type === "section" || def.type === "subsection") {
                  const shortTitle = (match[1] || "").trim();
                  const longTitle = (match[2] || "").trim();
                  const name =
                    shortTitle ||
                    longTitle ||
                    (def.type === "section" ? "Section" : "Subsection");

                  const detail = def.type === "section" ? "\\section" : "\\subsection";

                  atomic.push({
                    line: lineIndex,
                    ch: start,
                    symbol: new vscode.DocumentSymbol(
                      name,
                      detail,
                      vscode.SymbolKind.Namespace,
                      range(vscode, lineIndex, start, lineIndex, end),
                      range(vscode, lineIndex, start, lineIndex, end)
                    )
                  });
                  continue;
                }

                if (def.type === "includegraphics" || def.type === "image") {
                  const rawPath = (match[1] || "").trim();
                  if (!rawPath) {
                    continue;
                  }

                  const fileName = rawPath.split(/[\\/]/).pop() || rawPath;
                  const detail = def.type === "includegraphics" ? "\\includegraphics" : "\\image*";

                  atomic.push({
                    line: lineIndex,
                    ch: start,
                    symbol: new vscode.DocumentSymbol(
                      fileName,
                      detail,
                      vscode.SymbolKind.File,
                      range(vscode, lineIndex, start, lineIndex, end),
                      range(vscode, lineIndex, start, lineIndex, end)
                    )
                  });
                }
              }
            }
          }

          const atomicSymbols = atomic.map((a) => a.symbol);
          const all = [...atomicSymbols, ...outlineSymbols];

          all.sort((a, b) => {
            const da = a.selectionRange.start;
            const db = b.selectionRange.start;
            return da.line - db.line || da.character - db.character;
          });

          return all;
        } catch (error) {
          console.error("ULSBS symbol provider failed:", error);
          return [];
        }
      }
    },
    { label: "ULSBS Song Structure" }
  );

  context.subscriptions.push(provider);
  return provider;
}

module.exports = {
  registerSymbolProvider
};
