// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Tiny state machines for detecting song regions (verse/lilypond) line-by-line.
 * Used by decorations and other lightweight scanners.
 * @module
 */

const { tokenizeSongLine } = require("./songsyntax");

/**
 * Update verse region state for the next line.
 * @param {boolean} prevInVerse
 * @param {string} code Comment-stripped line.
 * @returns {{lineInVerse: boolean, nextInVerse: boolean}}
 */
function updateVerseState(prevInVerse, code) {
  let nextInVerse = prevInVerse;
  let lineInVerse = prevInVerse;
  for (const token of tokenizeSongLine(code, 0)) {
    if (token.type === "beginverse") {
      lineInVerse = true;
      nextInVerse = true;
    } else if (token.type === "endverse") {
      nextInVerse = false;
    }
  }

  return { lineInVerse, nextInVerse };
}

/**
 * Update lilypond region state for the next line.
 * @param {boolean} prevInLily
 * @param {string} code Comment-stripped line.
 * @returns {{lineInLily: boolean, nextInLily: boolean}}
 */
function updateLilypondState(prevInLily, code) {
  const hasBeginLily = /\\begin\{lilypond\}/.test(code);
  const hasEndLily = /\\end\{lilypond\}/.test(code);

  const lineInLily = prevInLily || hasBeginLily;

  let nextInLily;
  if (hasBeginLily && hasEndLily) {
    // single-line lilypond block
    nextInLily = false;
  } else if (hasEndLily) {
    nextInLily = false;
  } else if (hasBeginLily) {
    nextInLily = true;
  } else {
    nextInLily = prevInLily;
  }

  return { lineInLily, nextInLily };
}

module.exports = {
  updateVerseState,
  updateLilypondState
};
