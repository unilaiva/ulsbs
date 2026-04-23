// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Lightweight line-based parser for ULSBS songbook TeX.
 * Produces (1) an outline-like tree of songs/sections and (2) basic structural warnings.
 * @module
 */

/**
 * @typedef {{severity: 'warning'|'error', message: string, line: number, start: number, end: number}} Issue
 * @typedef {{rawTarget: string, line: number, start: number, end: number}} Include
 * @typedef {{
 *   type: string,
 *   name: string,
 *   detail: string,
 *   startLine: number,
 *   startChar: number,
 *   endLine: number,
 *   endChar: number,
 *   openTextLength: number,
 *   children: OutlineNode[],
 *   meta: Record<string, any>
 * }} OutlineNode
 * @typedef {{
 *   isMainCandidate: boolean,
 *   includes: Include[],
 *   songs: OutlineNode[],
 *   outline: OutlineNode[],
 *   issues: Issue[],
 *   tokenCount: number
 * }} Analysis
 */

const { tokenizeSongLine } = require("./songsyntax");

/** @param {string} text @param {number} index @returns {boolean} */
function isEscapedPercent(text, index) {
  let backslashes = 0;
  for (let i = index - 1; i >= 0 && text[i] === "\\"; i--) {
    backslashes += 1;
  }
  return backslashes % 2 === 1;
}

/**
 * Strip the LaTeX comment portion of a line (`% ...`).
 * @param {string} line
 * @returns {string}
 */
function stripComment(line) {
  for (let i = 0; i < line.length; i++) {
    if (line[i] === "%" && !isEscapedPercent(line, i)) {
      return line.slice(0, i);
    }
  }
  return line;
}

function makeIssue(severity, message, token) {
  return {
    severity,
    message,
    line: token.line,
    start: token.index,
    end: token.index + token.text.length
  };
}

function extractSongMeta(optionText) {
  const meta = {};
  if (!optionText) {
    return meta;
  }

  const byMatch = optionText.match(/\bby\s*=\s*\{([^}]*)\}/);
  if (byMatch) {
    meta.by = byMatch[1].trim();
  }

  const keyMatch = optionText.match(/\bkey\s*=\s*\{([^}]*)\}/);
  if (keyMatch) {
    meta.key = keyMatch[1].trim();
  }

  return meta;
}

function makeNode(type, name, detail, token, meta = {}) {
  return {
    type,
    name,
    detail,
    startLine: token.line,
    startChar: token.index,
    endLine: token.line,
    endChar: token.index + token.text.length,
    openTextLength: token.text.length,
    children: [],
    meta
  };
}

/**
 * Analyze a full document.
 * @param {string} text
 * @returns {Analysis}
 */
function analyzeText(text) {
  const lines = text.split(/\r?\n/);
  const tokens = [];
  let isMainCandidate = false;

  for (let i = 0; i < lines.length; i++) {
    const code = stripComment(lines[i]);
    const lineTokens = tokenizeSongLine(code, i);
    for (const token of lineTokens) {
      if (token.type === "documentclass" || token.type === "begindocument") {
        isMainCandidate = true;
      }
      tokens.push(token);
    }
  }

  const analysis = {
    isMainCandidate,
    includes: [],
    songs: [],
    outline: [],
    issues: [],
    tokenCount: tokens.length
  };

  const stack = [];
  const counters = {
    verse: 0,
    rep: 0,
    translation: 0,
    lilypond: 0
  };

  function currentNearest(types) {
    for (let i = stack.length - 1; i >= 0; i--) {
      if (types.includes(stack[i].type)) {
        return stack[i];
      }
    }
    return null;
  }

  function currentSong() {
    return currentNearest(["song"]);
  }

  function currentSongsEnv() {
    return currentNearest(["songsenv"]);
  }

  function resetSongCounters() {
    counters.verse = 0;
    counters.rep = 0;
    counters.translation = 0;
    counters.lilypond = 0;
  }

  function attachChild(node, preferredParents) {
    const parent = currentNearest(preferredParents);
    if (parent) {
      parent.node.children.push(node);
      return true;
    }
    return false;
  }

  function closeNearest(type, token) {
    for (let i = stack.length - 1; i >= 0; i--) {
      if (stack[i].type === type) {
        const entry = stack.splice(i, 1)[0];
        entry.node.endLine = token.line;
        entry.node.endChar = token.index + token.text.length;
        if (entry.type === "song") {
          analysis.songs.push(entry.node);
        }
        return entry;
      }
    }
    return null;
  }

  function closeNearestAny(types, token) {
    for (let i = stack.length - 1; i >= 0; i--) {
      if (types.includes(stack[i].type)) {
        const entry = stack.splice(i, 1)[0];
        entry.node.endLine = token.line;
        entry.node.endChar = token.index + token.text.length;
        if (entry.type === "song") {
          analysis.songs.push(entry.node);
        }
        return entry;
      }
    }
    return null;
  }

  for (const token of tokens) {
    if (token.type === "include") {
      analysis.includes.push({
        rawTarget: token.target,
        line: token.line,
        start: token.index,
        end: token.index + token.text.length
      });
      continue;
    }

    if (token.type === "beginsongsenv") {
      const node = makeNode("songsenv", "songs", "\\begin{songs}", token);
      stack.push({ type: "songsenv", node });
      continue;
    }

    if (token.type === "endsongsenv") {
      if (!closeNearest("songsenv", token)) {
        analysis.issues.push(makeIssue("warning", "\\end{songs} without matching \\begin{songs}", token));
      }
      continue;
    }

    if (token.type === "beginintersong") {
      const inSong = !!currentSong();

      if (inSong) {
        analysis.issues.push(
          makeIssue(
            "warning",
            "\\begin{intersong} inside a song; intersong blocks must be between songs, not inside them",
            token
          )
        );
      }

      const node = makeNode("intersong", "intersong", "intersong", token);

      if (!attachChild(node, ["song"])) {
        analysis.outline.push(node);
      }

      stack.push({ type: "intersong", node });
      continue;
    }

    if (token.type === "endintersong") {
      if (!closeNearest("intersong", token)) {
        analysis.issues.push(
          makeIssue(
            "warning",
            "\\end{intersong} without matching \\begin{intersong}",
            token
          )
        );
      }
      continue;
    }

    if (token.type === "beginexplanation") {
      const lang = token.language || "";
      const label = lang ? `explanation [${lang}]` : "explanation";
      const detail = lang ? `explanation (${lang})` : "explanation";
      const node = makeNode("explanation", label, detail, token, { language: lang });

      if (!attachChild(node, ["song"])) {
        analysis.outline.push(node);
      }

      stack.push({ type: "explanation", node });
      continue;
    }

    if (token.type === "endexplanation") {
      if (!closeNearest("explanation", token)) {
        analysis.issues.push(
          makeIssue(
            "warning",
            "\\end{explanation} without matching \\begin{explanation}",
            token
          )
        );
      }
      continue;
    }

    if (token.type === "beginpassage") {
      const lang = token.language || "";
      const label = lang ? `passage [${lang}]` : "passage";
      const detail = lang ? `passage (${lang})` : "passage";
      const node = makeNode("passage", label, detail, token, { language: lang });

      if (!attachChild(node, ["song"])) {
        analysis.outline.push(node);
      }

      stack.push({ type: "passage", node });
      continue;
    }

    if (token.type === "endpassage") {
      if (!closeNearest("passage", token)) {
        analysis.issues.push(
          makeIssue(
            "warning",
            "\\end{passage} without matching \\begin{passage}",
            token
          )
        );
      }
      continue;
    }

    if (token.type === "beginfeeler") {
      const node = makeNode("feeler", "feeler", "feeler", token);

      if (!attachChild(node, ["song"])) {
        analysis.outline.push(node);
      }

      stack.push({ type: "feeler", node });
      continue;
    }

    if (token.type === "endfeeler") {
      if (!closeNearest("feeler", token)) {
        analysis.issues.push(
          makeIssue(
            "warning",
            "\\end{feeler} without matching \\begin{feeler}",
            token
          )
        );
      }
      continue;
    }

    if (token.type === "beginsong") {
      resetSongCounters();

      if (isMainCandidate && !currentSongsEnv()) {
        analysis.issues.push(
          makeIssue(
            "warning",
            "\\beginsong is not inside a \\begin{songs} ... \\end{songs} environment in this main document",
            token
          )
        );
      }

      const meta = extractSongMeta(token.options);
      const detailParts = [];
      if (meta.by) detailParts.push(`by: ${meta.by}`);
      if (meta.key) detailParts.push(`key: ${meta.key}`);

      const node = makeNode(
        "song",
        token.title || "Song",
        detailParts.join(" · "),
        token,
        meta
      );

      // Keep songs (and other blocks) in source order for outline consumers.
      analysis.outline.push(node);

      stack.push({ type: "song", node });
      continue;
    }

    if (token.type === "beginverse") {
      const song = currentSong();
      if (!song) {
        analysis.issues.push(makeIssue("warning", "\\beginverse outside a song", token));
        continue;
      }
      counters.verse += 1;
      const node = makeNode("verse", `verse ${counters.verse}`, "\\beginverse", token);
      attachChild(node, ["song"]);
      stack.push({ type: "verse", node });
      continue;
    }

    if (token.type === "mnbeginverse") {
      const song = currentSong();
      if (!song) {
        analysis.issues.push(makeIssue("warning", "\\mnbeginverse outside a song", token));
        continue;
      }
      counters.verse += 1;
      const node = makeNode("mnverse", `verse ${counters.verse}`, "\\mnbeginverse", token);
      attachChild(node, ["song"]);
      stack.push({ type: "mnverse", node });
      continue;
    }

    if (token.type === "beginrep") {
      const parent = currentNearest(["rep", "verse", "mnverse", "translation"]);
      if (!parent) {
        analysis.issues.push(makeIssue("warning", "\\beginrep outside a verse or translation", token));
        continue;
      }
      counters.rep += 1;
      const node = makeNode("rep", `rep ${counters.rep}`, "\\beginrep", token);
      attachChild(node, ["rep", "verse", "mnverse", "translation"]);
      stack.push({ type: "rep", node });
      continue;
    }

    if (token.type === "begintranslation") {
      if (!currentSong()) {
        analysis.issues.push(makeIssue("warning", "translation block outside a song", token));
        continue;
      }
      counters.translation += 1;
      const lang = token.language || "";
      const label = lang
        ? `translation ${counters.translation} [${lang}]`
        : `translation ${counters.translation}`;
      const detail = lang
        ? `translation (${lang})`
        : "translation";
      const node = makeNode(
        "translation",
        label,
        detail,
        token,
        { language: lang }
      );
      attachChild(node, ["song"]);
      stack.push({ type: "translation", node });

      if (!lang) {
        analysis.issues.push(
          makeIssue(
            "warning",
            "Translation block has no language code; consider using [EN] or similar",
            token
          )
        );
      }
      continue;
    }

    if (token.type === "beginlilypond") {
      if (!currentSong()) {
        analysis.issues.push(makeIssue("warning", "\\begin{lilypond} outside a song", token));
        continue;
      }
      counters.lilypond += 1;
      const node = makeNode(
        "lilypond",
        `lilypond ${counters.lilypond}`,
        "\\begin{lilypond}",
        token
      );
      attachChild(node, ["song"]);
      stack.push({ type: "lilypond", node });
      continue;
    }

    if (token.type === "endverse") {
      if (!closeNearestAny(["verse", "mnverse"], token)) {
        analysis.issues.push(makeIssue("warning", "\\endverse without matching \\beginverse or \\mnbeginverse", token));
      }
      continue;
    }

    if (token.type === "mnendverse") {
      if (!closeNearest("mnverse", token)) {
        analysis.issues.push(makeIssue("warning", "\\mnendverse without matching \\mnbeginverse", token));
      }
      continue;
    }

    if (token.type === "endrep") {
      if (!closeNearest("rep", token)) {
        analysis.issues.push(makeIssue("warning", "\\endrep without matching \\beginrep", token));
      }
      continue;
    }

    if (token.type === "endtranslation") {
      if (!closeNearest("translation", token)) {
        analysis.issues.push(makeIssue("warning", "translation end without matching translation start", token));
      }
      continue;
    }

    if (token.type === "endlilypond") {
      if (!closeNearest("lilypond", token)) {
        analysis.issues.push(makeIssue("warning", "\\end{lilypond} without matching \\begin{lilypond}", token));
      }
      continue;
    }

    if (token.type === "endsong") {
      if (!closeNearest("song", token)) {
        analysis.issues.push(makeIssue("warning", "\\endsong without matching \\beginsong", token));
      }
      continue;
    }
  }

  const lastLine = Math.max(0, lines.length - 1);
  const lastChar = lines[lastLine] ? lines[lastLine].length : 0;

  for (const entry of stack) {
    entry.node.endLine = lastLine;
    entry.node.endChar = lastChar;

    if (entry.type === "song") {
      analysis.songs.push(entry.node);
      analysis.issues.push({
        severity: "warning",
        message: "Unclosed \\beginsong at end of file",
        line: entry.node.startLine,
        start: entry.node.startChar,
        end: entry.node.startChar + 10
      });
    } else if (entry.type === "songsenv") {
      analysis.issues.push({
        severity: "warning",
        message: "Unclosed \\begin{songs} at end of file",
        line: entry.node.startLine,
        start: entry.node.startChar,
        end: entry.node.startChar + 13
      });
    } else {
      analysis.issues.push({
        severity: "warning",
        message: `Unclosed ${entry.node.detail || entry.node.type} at end of file`,
        line: entry.node.startLine,
        start: entry.node.startChar,
        end: entry.node.startChar + 10
      });
    }
  }

  return analysis;
}

module.exports = {
  analyzeText,
  stripComment,
  extractSongMeta
};
