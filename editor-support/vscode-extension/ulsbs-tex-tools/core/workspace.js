// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Workspace helpers (folder resolution + ULSBS workspace auto-detection).
 * @module
 */

const { getSettings } = require("./config");

/** Default ULSBS config file name at workspace root. */
const ULSBS_CONFIG_BASENAME = "ulsbs-config.toml";

/**
 * Detect whether ULSBS features should be enabled in the current workspace.
 * Respects `ulsbsTexTools.enable` (on/off/auto).
 * @param {import('vscode')} vscode
 * @returns {Promise<boolean>}
 */
async function isUlsbsWorkspace(vscode) {
  const settings = getSettings(vscode);

  if (settings.enable === "off") {
    return false;
  }
  if (settings.enable === "on") {
    return true;
  }

  const markers = await Promise.all([
    vscode.workspace.findFiles("**/ulsbs/ulsbs-compile", null, 1),
    vscode.workspace.findFiles(`**/${ULSBS_CONFIG_BASENAME}`, null, 1),
    vscode.workspace.findFiles("**/ulsbs/pyproject.toml", null, 1)
  ]);

  return markers.some((items) => items.length > 0);
}

/**
 * Resolve the workspace folder for a URI (or the first folder if URI is missing).
 * @param {import('vscode')} vscode
 * @param {import('vscode').Uri|null|undefined} uri
 * @returns {import('vscode').WorkspaceFolder|null}
 */
function getWorkspaceFolderForUri(vscode, uri) {
  if (!uri) {
    const first = vscode.workspace.workspaceFolders?.[0];
    return first ?? null;
  }
  return vscode.workspace.getWorkspaceFolder(uri) ?? null;
}

/**
 * @param {import('vscode')} vscode
 * @returns {import('vscode').WorkspaceFolder[]}
 */
function getAllWorkspaceFolders(vscode) {
  return vscode.workspace.workspaceFolders ?? [];
}

module.exports = {
  ULSBS_CONFIG_BASENAME,
  isUlsbsWorkspace,
  getWorkspaceFolderForUri,
  getAllWorkspaceFolders
};
