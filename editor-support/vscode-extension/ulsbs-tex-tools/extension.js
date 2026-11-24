// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * VS Code extension entry point for ULSBS TeX tools.
 * @module
 */

const vscode = require("vscode");

const { isUlsbsWorkspace, ULSBS_CONFIG_BASENAME } = require("./core/workspace");
const { createSongbookService } = require("./core/songbooks");
const { registerSymbolProvider } = require("./core/symbols");
const { registerMeasureBarDecorations } = require("./core/measures");
const { registerChordDecorations } = require("./core/chords");
const { registerDiagnostics } = require("./core/diagnostics");
const { registerCompileCommands } = require("./core/compile");
const { registerTreeView } = require("./core/tree");
const { registerCompletionProvider } = require("./core/completions");
const {
  requirePrimaryWorkspaceFolder,
  uriExists,
  logAndShowError
} = require("./core/ui");

/**
 * Extension activation entry point.
 * Wires up ULSBS services, commands, views and decorations.
 * @param {vscode.ExtensionContext} context VS Code extension context
 */
async function activate(context) {
  const songbookService = createSongbookService(vscode);
  context.subscriptions.push(songbookService);

  registerSymbolProvider(vscode, context);
  registerMeasureBarDecorations(vscode, context);
  registerChordDecorations(vscode, context);
  registerCompletionProvider(vscode, context);

  // Controllers / feature modules
  const treeController = registerTreeView(vscode, context, songbookService);
  const diagnosticsController = registerDiagnostics(vscode, context, songbookService);
  const compileController = registerCompileCommands(
    vscode,
    context,
    songbookService,
    treeController
  );


  context.subscriptions.push(
    vscode.commands.registerCommand("ulsbsTexTools.openConfig", async () => {
      try {
        const folder = requirePrimaryWorkspaceFolder(vscode);
        if (!folder) {
          return;
        }

        const configUri = vscode.Uri.joinPath(folder.uri, ULSBS_CONFIG_BASENAME);
        if (!(await uriExists(vscode, configUri))) {
          void vscode.window.showErrorMessage(
            `ULSBS configuration file not found at ${vscode.workspace.asRelativePath(configUri, false)}`
          );
          return;
        }

        await vscode.window.showTextDocument(configUri);
      } catch (error) {
        logAndShowError(
          vscode,
          "ULSBS: Failed to open configuration file",
          error,
          "Failed to open ULSBS configuration file."
        );
      }
    }),

    vscode.commands.registerCommand("ulsbsTexTools.createSongbook", async () => {
      try {
        const folder = requirePrimaryWorkspaceFolder(vscode);
        if (!folder) {
          return;
        }

        // Ensure ULSBS exists in this workspace.
        const clsRelative = "ulsbs/src/ulsbs/assets/tex/ulsbs-songbook.cls";
        const clsUri = vscode.Uri.joinPath(folder.uri, clsRelative);

        if (!(await uriExists(vscode, clsUri))) {
          void vscode.window.showErrorMessage(
            `ULSBS songbook class not found at ${vscode.workspace.asRelativePath(clsUri, false)}`
          );
          return;
        }

        const base = await vscode.window.showInputBox({
          title: "New ULSBS songbook",
          prompt: "Base name for the new songbook; _A5.tex will be added",
          value: "my-songbook"
        });

        let name = base?.trim();
        if (!name) {
          return;
        }

        // Normalize to (something)_A5.tex
        name = name.replace(/\.tex$/i, "");
        if (!/_a5$/i.test(name)) {
          name = `${name}_A5`;
        }
        const filename = `${name}.tex`;

        const targetUri = vscode.Uri.joinPath(folder.uri, filename);
        if (await uriExists(vscode, targetUri)) {
          void vscode.window.showErrorMessage(
            `File already exists: ${vscode.workspace.asRelativePath(targetUri, false)}`
          );
          return;
        }

        // Read template from extension assets
        const templateUri = vscode.Uri.joinPath(
          context.extensionUri,
          "assets",
          "songbook-template_A5.tex"
        );

        let templateBytes;
        try {
          templateBytes = await vscode.workspace.fs.readFile(templateUri);
        } catch (error) {
          logAndShowError(
            vscode,
            "ULSBS: Failed to read songbook template",
            error,
            "Failed to read ULSBS songbook template."
          );
          return;
        }

        await vscode.workspace.fs.writeFile(targetUri, templateBytes);
        await vscode.window.showTextDocument(targetUri);

        await songbookService.refresh();
        treeController.refresh();
      } catch (error) {
        logAndShowError(
          vscode,
          "ULSBS: Failed to create new songbook",
          error,
          "Failed to create new ULSBS songbook."
        );
      }
    })
  );

  async function refreshFeatureState() {
    const enabled = await isUlsbsWorkspace(vscode);

    treeController.setEnabled(enabled);
    compileController.setEnabled(enabled);
    diagnosticsController.setEnabled(enabled);

    if (enabled) {
      await songbookService.refresh();
      diagnosticsController.refreshActive();
      treeController.refresh();
    } else {
      diagnosticsController.clear();
      treeController.refresh();
    }
  }

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(async (event) => {
      if (event.affectsConfiguration("ulsbsTexTools")) {
        await refreshFeatureState();
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(async () => {
      await refreshFeatureState();
    })
  );

  await refreshFeatureState();
}

/**
 * Extension deactivation hook.
 * (Most resources are disposed automatically via `context.subscriptions`.)
 */
function deactivate() {}

module.exports = {
  activate,
  deactivate
};
