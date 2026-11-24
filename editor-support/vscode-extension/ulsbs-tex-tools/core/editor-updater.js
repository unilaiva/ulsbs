// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Shared wiring for “update decorations for the active editor” features.
 * Keeps chord/measure decorations consistent and avoids duplicated event code.
 * @module
 */

/**
 * @typedef {Object} ActiveEditorUpdaterOptions
 * @property {number} [debounceMs] Debounce delay for updates (default: 75ms).
 */

/**
 * Register listeners that keep an active-editor feature up to date.
 *
 * The updater is called for:
 * - active editor changes
 * - text document changes (only if it is the active document)
 * - document opens
 *
 * @param {import('vscode')} vscode
 * @param {import('vscode').ExtensionContext} context
 * @param {(editor: import('vscode').TextEditor) => (void|Promise<void>)} updateEditor
 * @param {ActiveEditorUpdaterOptions} [options]
 * @returns {{refreshActive: () => void}}
 */
function registerActiveEditorUpdater(vscode, context, updateEditor, options = {}) {
  const debounceMs =
    typeof options.debounceMs === "number" ? options.debounceMs : 75;

  /** @type {NodeJS.Timeout | null} */
  let timer = null;

  /** @param {import('vscode').TextEditor | undefined} editor */
  function schedule(editor) {
    if (!editor) {
      return;
    }

    if (timer) {
      clearTimeout(timer);
    }

    timer = setTimeout(() => {
      timer = null;
      try {
        void updateEditor(editor);
      } catch (error) {
        console.error("ULSBS: Active editor updater failed", error);
      }
    }, debounceMs);
  }

  function refreshActive() {
    schedule(vscode.window.activeTextEditor);
  }

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => schedule(editor)),
    vscode.workspace.onDidChangeTextDocument((event) => {
      const active = vscode.window.activeTextEditor;
      if (active && event.document === active.document) {
        schedule(active);
      }
    }),
    vscode.workspace.onDidOpenTextDocument(() => {
      const active = vscode.window.activeTextEditor;
      if (active) {
        schedule(active);
      }
    })
  );

  // Initial update for the currently active editor
  refreshActive();

  return { refreshActive };
}

module.exports = {
  registerActiveEditorUpdater
};
