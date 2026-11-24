// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Shared issue helpers.
 *
 * An "issue" is a lightweight, VS Code-independent representation of a warning/error
 * located at a single line + character span.
 *
 * Parser/linting code should produce these. Diagnostics/UI adapters can then map them
 * to `vscode.Diagnostic` or other presentations.
 * @module
 */

/**
 * @typedef {{severity: 'warning'|'error', message: string, line: number, start: number, end: number}} Issue
 */

/**
 * Create an issue located at a token span.
 * @param {'warning'|'error'} severity
 * @param {string} message
 * @param {{line:number,index:number,text:string}} token
 * @returns {Issue}
 */
function issueFromToken(severity, message, token) {
  return {
    severity,
    message,
    line: token.line,
    start: token.index,
    end: token.index + (token.text?.length ?? 1)
  };
}

/**
 * Create an issue located at an explicit span.
 * @param {'warning'|'error'} severity
 * @param {string} message
 * @param {number} line
 * @param {number} start
 * @param {number} end
 * @returns {Issue}
 */
function issueAt(severity, message, line, start, end) {
  return {
    severity,
    message,
    line: Math.max(0, line | 0),
    start: Math.max(0, start | 0),
    end: Math.max(Math.max(0, start | 0) + 1, end | 0)
  };
}

module.exports = {
  issueFromToken,
  issueAt
};
