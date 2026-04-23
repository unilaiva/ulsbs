// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Shared UI/guard helpers for commands.
 * @module
 */

/**
 * @param {import('vscode')} vscode
 * @returns {import('vscode').WorkspaceFolder|null}
 */
function getPrimaryWorkspaceFolder(vscode) {
  return vscode.workspace.workspaceFolders?.[0] ?? null;
}

/**
 * @param {import('vscode')} vscode
 * @param {string} [message]
 * @returns {import('vscode').WorkspaceFolder|null}
 */
function requirePrimaryWorkspaceFolder(vscode, message = "No workspace folder is open.") {
  const folder = getPrimaryWorkspaceFolder(vscode);
  if (!folder) {
    void vscode.window.showErrorMessage(message);
    return null;
  }
  return folder;
}

/**
 * @param {import('vscode')} vscode
 * @param {import('vscode').Uri} uri
 */
async function uriExists(vscode, uri) {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

/**
 * Consistent error logging + user messaging.
 * @param {import('vscode')} vscode
 * @param {string} contextMessage For logs.
 * @param {unknown} error
 * @param {string} userMessage
 */
function logAndShowError(vscode, contextMessage, error, userMessage) {
  console.error(contextMessage, error);
  void vscode.window.showErrorMessage(userMessage);
}

module.exports = {
  getPrimaryWorkspaceFolder,
  requirePrimaryWorkspaceFolder,
  uriExists,
  logAndShowError
};
