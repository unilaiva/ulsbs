// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/** Refine a SyncTeX line jump using literal lyric or translation text. */

const { stripComment } = require("./parser");

const wordPattern = /[\p{L}\p{N}][\p{L}\p{N}\p{M}]*(?:['\u2019\u02bc\u2010\u2011-][\p{L}\p{N}][\p{L}\p{N}\p{M}]*)*/gu;
const inlineMarkup = /\\\[(?:\\.|[^\\\]])*(?:\]|$)|\\[A-Za-z@]+\*?|\\.|[{}^|~]/gu;
const textWrappers = new Set(["emph", "textbf", "textit", "textmd", "textnormal", "textrm", "textsc", "textsf",
  "textsl", "texttt", "textup", "underline", "mbox"]);

function normalize(word) {
  return word.normalize("NFKC").replace(/[\u2019\u02bc]/g, "'").replace(/[\u2010\u2011]/g, "-");
}

/** Return the UTF-16 column of a unique complete word, or undefined to keep the line jump. */
function findSourceWordColumn(line, word) {
  if (typeof word !== "string" || !word || word.length > 128) return undefined;
  const needle = normalize(word);
  if (needle.match(wordPattern)?.[0] !== needle) return undefined;

  const code = stripComment(line);
  let visible = "";
  const columns = [];
  let start = 0;
  function append(end) {
    visible += code.slice(start, end);
    for (let index = start; index < end; index++) columns.push(index);
  }
  for (const match of code.matchAll(inlineMarkup)) {
    const { 0: token, index } = match;
    append(index);
    start = index + token.length;
    // These tokens can split a printed word without ending it.
    if (token.startsWith("\\[") || token === "^" || token === "|" || token === "{" || token === "}" || token === "\\-") continue;

    if (textWrappers.has(token.slice(1))) {
      while (start < code.length && /\s/.test(code[start])) start++;
      continue;
    }
    // We cannot tell whether an unrecognized command prints its arguments.
    if (/^\\[A-Za-z@]/.test(token) && /^\s*(?:\[|\{)/.test(code.slice(start))) return undefined;

    visible += " ";
    columns.push(index);
  }
  append(code.length);

  let column;
  for (const match of visible.matchAll(wordPattern)) {
    if (normalize(match[0]) !== needle) continue;
    if (column !== undefined) return undefined;
    column = columns[match.index];
  }
  return column;
}

module.exports = { findSourceWordColumn };
