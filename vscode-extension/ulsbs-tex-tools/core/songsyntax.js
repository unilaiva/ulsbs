// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Tokenizer for ULSBS song-related TeX macros (\beginsong, \beginverse, ...).
 * Consumed by the parser, outline/symbols and workspace index.
 * @module
 */

/**
 * @typedef {{type: string, line: number, index: number, text: string, [key: string]: any}} SongToken
 */

const PATTERNS = [
  {
    type: "beginsong",
    regex: /\\beginsong(?:\[(.*?)\])?\{([^}]*)\}(?:\[(.*?)\])?/g,
    map: (match) => ({
      title: (match[2] || "").trim(),
      options: (match[1] || match[3] || "").trim()
    })
  },
  {
    type: "beginsongsenv",
    regex: /\\begin\{songs\}/g
  },
  {
    type: "endsongsenv",
    regex: /\\end\{songs\}/g
  },
  {
    type: "beginintersong",
    regex: /\\begin\{intersong\*?\}/g
  },
  {
    type: "endintersong",
    regex: /\\end\{intersong\*?\}/g
  },
  {
    type: "beginexplanation",
    regex: /\\begin\{explanation\}(?:\[(.*?)\])?/g,
    map: (match) => ({
      language: (match[1] || "").trim()
    })
  },
  {
    type: "endexplanation",
    regex: /\\end\{explanation\}/g
  },
  {
    type: "beginpassage",
    regex: /\\begin\{passage\}(?:\[(.*?)\])?/g,
    map: (match) => ({
      language: (match[1] || "").trim()
    })
  },
  {
    type: "endpassage",
    regex: /\\end\{passage\}/g
  },
  {
    type: "beginfeeler",
    regex: /\\begin\{feeler\}/g
  },
  {
    type: "endfeeler",
    regex: /\\end\{feeler\}/g
  },
  { type: "beginverse", regex: /\\beginverse\b/g },
  { type: "mnbeginverse", regex: /\\mnbeginverse\b/g },
  { type: "beginrep", regex: /\\beginrep\b/g },
  {
    type: "begintranslation",
    regex:
      /\\begin\{translation\}(?:\[(.*?)\])?|\\begintranslation(?:\[(.*?)\])?/g,
    map: (match) => ({
      language: (match[1] || match[2] || "").trim()
    })
  },
  {
    type: "beginlilywrap",
    regex: /\\begin\{lilywrap\}/g
  },
  {
    type: "endlilywrap",
    regex: /\\end\{lilywrap\}/g
  },
  { type: "beginlilypond", regex: /\\begin\{lilypond\}/g },
  { type: "endsong", regex: /\\endsong\b/g },
  { type: "endverse", regex: /\\endverse\b/g },
  { type: "mnendverse", regex: /\\mnendverse\b/g },
  { type: "endrep", regex: /\\endrep\b/g },
  {
    type: "endtranslation",
    regex: /\\end\{translation\}|\\endtranslation\b/g
  },
  { type: "endlilypond", regex: /\\end\{lilypond\}/g },
  {
    type: "include",
    regex: /\\(?:input|include|subfile)\{([^}]+)\}/g,
    map: (match) => ({ target: match[1].trim() })
  },
  {
    type: "documentclass",
    regex: /\\documentclass(?:\[[^\]]*\])?\{[^}]+\}/g
  },
  { type: "begindocument", regex: /\\begin\{document\}/g }
];

/**
 * Tokenize a single (comment-stripped) line.
 * @param {string} code
 * @param {number} lineNumber Zero-based line index.
 * @returns {SongToken[]}
 */
function tokenizeSongLine(code, lineNumber) {
  const tokens = [];

  for (const pattern of PATTERNS) {
    pattern.regex.lastIndex = 0;
    let match;
    while ((match = pattern.regex.exec(code)) !== null) {
      tokens.push({
        type: pattern.type,
        line: lineNumber,
        index: match.index,
        text: match[0],
        ...(pattern.map ? pattern.map(match) : {})
      });
    }
  }

  tokens.sort((a, b) => {
    if (a.index !== b.index) {
      return a.index - b.index;
    }
    return a.type.localeCompare(b.type);
  });

  return tokens;
}

module.exports = {
  tokenizeSongLine
};
