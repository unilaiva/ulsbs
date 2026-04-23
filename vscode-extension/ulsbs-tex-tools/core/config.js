// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * VS Code configuration helpers for `ulsbsTexTools.*` settings.
 * @module
 */

/**
 * @typedef {Object} UlsbsTexToolsSettings
 * @property {"auto"|"on"|"off"} enable Feature toggle.
 * @property {string} fileGlob Workspace file glob for TeX-like sources.
 * @property {string[]} excludeGlob Glob(s) excluded from indexing.
 * @property {string} compileCommand Path to `ulsbs-compile` (relative to workspace root).
 * @property {boolean} askProfileOnCompile Ask for profile on compile.
 * @property {string} defaultProfile Default profile when not asking.
 * @property {boolean} autoRefreshDiagnostics Refresh diagnostics on edits.
 */

/** Globs always excluded from scanning, even if the user overrides `excludeGlob`. */
const INTERNAL_EXCLUDE_GLOBS = [
  "**/ulsbs-tex-tools/assets/**",
  "**/vscode-extension/ulsbs-tex-tools/assets/**"
];

/** @param {import('vscode')} vscode */
function getConfiguration(vscode) {
  return vscode.workspace.getConfiguration("ulsbsTexTools");
}

/**
 * Read extension settings with defaults.
 * @param {import('vscode')} vscode
 * @returns {UlsbsTexToolsSettings}
 */
function getSettings(vscode) {
  const cfg = getConfiguration(vscode);

  // Note: VS Code already applies defaults from `package.json` (contributes.configuration).
  // We only keep runtime fallbacks here and *always* append internal excludes.
  const userExclude = cfg.get("excludeGlob");
  const excludeGlobs = Array.isArray(userExclude)
    ? userExclude
    : typeof userExclude === "string" && userExclude.trim()
      ? [userExclude]
      : [];

  const excludeGlob = Array.from(
    new Set([...excludeGlobs, ...INTERNAL_EXCLUDE_GLOBS])
  );

  return {
    enable: cfg.get("enable") ?? "auto",
    fileGlob: cfg.get("fileGlob") ?? "**/*.*tex",
    excludeGlob,
    compileCommand: cfg.get("compileCommand") ?? "ulsbs/ulsbs-compile",
    askProfileOnCompile: cfg.get("askProfileOnCompile") ?? true,
    defaultProfile: cfg.get("defaultProfile") ?? "default",
    autoRefreshDiagnostics: cfg.get("autoRefreshDiagnostics") ?? true
  };
}

module.exports = {
  getSettings
};
