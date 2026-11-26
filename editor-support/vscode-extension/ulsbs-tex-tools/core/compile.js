// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later
// @ts-check

/**
 * Compile commands, save confirmation, and per-songbook build scheduling.
 * @module
 */

const { getSettings } = require("./config");
const { getWorkspaceFolderForUri } = require("./workspace");
const { uriExists } = require("./ui");

/** @typedef {{background?: boolean, onExit?: (code: number | undefined) => void}} BuildOptions */
/** @typedef {{keys: Set<string>, done: Promise<void>, started: (ok: boolean) => void,
 * cancelled: boolean, cancel: () => void, interrupt?: () => void}} Build */
/** @typedef {{uri: import('vscode').Uri, selection?: {line: number, character?: number}}} SongbookItem */

const PREVIEW_ARGS = [
  "--no-deploy", "--no-printouts", "--no-multikey", "--no-coverimage",
  "--no-json", "--no-midi", "--no-audio", "--keep-temp"
];

/** @param {typeof import('vscode')} vscode */
function isWeb(vscode) {
  return vscode.env.uiKind === vscode.UIKind.Web;
}

/**
 * Use our own terminal so VS Code's task runner cannot save dirty editors.
 * Wait for the compiler to exit after SIGINT, even if its terminal is closed.
 * @param {typeof import('vscode')} vscode
 * @param {Build} build
 * @param {import('vscode').WorkspaceFolder} folder
 * @param {string} command
 * @param {string[]} args
 * @param {boolean | undefined} background
 * @param {(terminal: import('vscode').Terminal) => void} keepLog
 * @returns {Promise<number | undefined>}
 */
function executeBuild(vscode, build, folder, command, args, background, keepLog) {
  return new Promise((resolve, reject) => {
    /** @type {import('vscode').EventEmitter<string>} */
    const output = new vscode.EventEmitter();
    let opened = false;
    let finished = false;
    let closed = false;
    /** @type {import('vscode').Terminal | undefined} */
    let terminal;

    /** @param {number} [code] @param {unknown} [error] */
    function finish(code, error) {
      if (finished) return;
      finished = true;
      if (!closed && terminal) {
        const status = build.cancelled ? "Build stopped." : code === 0 ? "Build finished." :
          code === undefined ? "Build could not start." : `Build failed (exit code ${code}).`;
        write(`\x1b[?25h\r\x1b[K${status}\n`);
        keepLog(terminal);
      }
      output.dispose();
      if (error && !build.cancelled) reject(error);
      else resolve(code);
    }

    /** @param {string} text */
    const write = (text) => output.fire(text.replace(/\r?\n/g, "\r\n"));
    /** @type {import('vscode').Pseudoterminal} */
    const pty = {
      onDidWrite: output.event,
      open() {
        if (opened || finished) return;
        opened = true;
        if (build.cancelled) {
          finish();
          return;
        }
        try {
          // Only the desktop/workspace extension host can run the compiler.
          const { spawn } = process.getBuiltinModule("node:child_process");
          const child = spawn(command, args, {
            cwd: folder.uri.fsPath || folder.uri.path,
            stdio: ["ignore", "pipe", "pipe"],
            // The child sees pipes, but the receiver is VS Code's terminal emulator.
            env: { ...process.env, TERM: "xterm-256color", ULSBS_INTERNAL_TERMINAL_OUTPUT: "1" }
          });
          /** @type {Error | undefined} */
          let launchError;
          build.interrupt = () => child.kill("SIGINT");
          child.stdout.setEncoding("utf8").on("data", write);
          child.stderr.setEncoding("utf8").on("data", write);
          child.once("spawn", () => build.started(!build.cancelled));
          child.on("error", (error) => {
            if (!child.pid) launchError = error;
            write(`${error.message}\n`);
          });
          child.once("close", (code) => finish(code ?? undefined, launchError));
        } catch (error) {
          finish(undefined, error);
        }
      },
      close() {
        closed = true;
        if (finished) return;
        build.cancel();
        if (!opened) finish();
      },
      handleInput(data) {
        if (data.includes("\x03")) build.cancel();
      }
    };
    try {
      terminal = vscode.window.createTerminal({ name: "ULSBS Build", pty, isTransient: true });
      // Cancellation before VS Code opens the PTY must also release the queue.
      if (!opened) build.interrupt = () => terminal?.dispose();
      if (!background) terminal.show(true);
    } catch (error) {
      finish(undefined, error);
    }
  });
}

/**
 * Register compile-related commands.
 * @param {typeof import('vscode')} vscode
 * @param {import('vscode').ExtensionContext} context
 * @param {ReturnType<typeof import('./songbooks').createSongbookService>} songbookService
 * @param {{refresh: () => void, setSelectedProfile: (profile: string) => void}|undefined|null} treeController
 */
function registerCompileCommands(vscode, context, songbookService, treeController) {
  let enabled = false;
  let selectedProfile = "default";
  let disposed = false;
  /** @type {Set<Build>} */
  const builds = new Set();
  /** @type {Map<string, import('vscode').Terminal>} */
  const buildLogs = new Map();
  /** @type {Map<string, Set<string>>} */
  const savingForBuild = new Map();

  /** @param {Set<string>} keys @param {import('vscode').WorkspaceFolder} folder */
  async function confirmBuildSave(keys, folder) {
    const config = vscode.Uri.joinPath(folder.uri, "ulsbs-config.toml").toString();
    const dirty = await Promise.all(vscode.workspace.textDocuments.filter((doc) => doc.isDirty && !doc.isUntitled &&
      vscode.workspace.getWorkspaceFolder(doc.uri)?.uri.toString() === folder.uri.toString()).map(async (doc) => {
      const key = doc.uri.toString();
      if (keys.has(key) || key === config) return doc;
      const books = await songbookService.getAffectedSongbooks(doc.uri);
      return books.some((book) => keys.has(book.uri.toString())) ? doc : undefined;
    }));
    const documents = dirty.filter((doc) => doc !== undefined).filter((doc) => doc.isDirty);
    if (!documents.length) return true;
    const save = "Save and Build";
    const build = "Build Without Saving";
    const answer = await vscode.window.showWarningMessage("Save changes before building?", {
      modal: true,
      detail: `ULSBS builds from disk. Unsaved files for this build:\n${documents.map((doc) => vscode.workspace.asRelativePath(doc.uri)).join("\n")}`
    }, save, build);
    if (answer !== save) return answer === build;
    if (disposed) return false;
    for (const doc of documents) {
      if (!doc.isDirty) continue;
      const key = doc.uri.toString();
      savingForBuild.set(key, keys);
      try {
        if (await doc.save() && !doc.isDirty) continue;
      } finally {
        if (savingForBuild.get(key) === keys) savingForBuild.delete(key);
      }
      void vscode.window.showWarningMessage(`ULSBS build stopped: could not save ${vscode.workspace.asRelativePath(doc.uri)}.`);
      return false;
    }
    return true;
  }

  /** @param {import('vscode').Uri} uri */
  async function chooseProfileForUri(uri) {
    const settings = getSettings(vscode);
    const profiles = await songbookService.getProfiles(uri);

    if (!settings.askProfileOnCompile) {
      selectedProfile = settings.defaultProfile || "default";
      treeController?.setSelectedProfile?.(selectedProfile);
      treeController?.refresh?.();
      return selectedProfile;
    }

    const picked = await vscode.window.showQuickPick(
      profiles.map((profile) => ({
        label: profile,
        description:
          profile === selectedProfile
            ? "current"
            : profile === "default"
              ? "implicit default"
              : ""
      })),
      { placeHolder: "Select ULSBS compile profile" }
    );

    if (!picked) {
      return null;
    }

    selectedProfile = picked.label;
    treeController?.setSelectedProfile?.(selectedProfile);
    treeController?.refresh?.();
    return selectedProfile;
  }

  /**
   * @param {import('vscode').Uri[]} mainUris
   * @param {string} profile
   * @param {import('vscode').Uri} anchorUri
   * @param {string[]} [extraArgs]
   * @param {BuildOptions} [options]
   */
  async function runCompile(mainUris, profile, anchorUri, extraArgs = [], options = {}) {
    if (isWeb(vscode)) {
      vscode.window.showInformationMessage(
        "ULSBS compilation is not available in browser-only VS Code."
      );
      return false;
    }
    if (vscode.workspace.isTrusted === false) {
      if (!options.background) vscode.window.showWarningMessage("ULSBS compilation requires a trusted workspace.");
      return false;
    }

    const folder = getWorkspaceFolderForUri(vscode, anchorUri);
    if (!folder) {
      vscode.window.showWarningMessage("No workspace folder found for compilation.");
      return false;
    }

    if (disposed) return false;
    const keys = new Set(mainUris.map((uri) => uri.toString()));
    if (!options.background && vscode.workspace.textDocuments.some((doc) => doc.isDirty && !doc.isUntitled)) {
      try {
        if (!(await confirmBuildSave(keys, folder))) return false;
      } catch (error) {
        void vscode.window.showWarningMessage(`Could not prepare ULSBS compilation: ${error instanceof Error ? error.message : String(error)}`);
        return false;
      }
    }
    if (disposed) return false;

    const settings = getSettings(vscode);
    const args = ["--synctex", ...extraArgs];
    if (profile && profile !== "default") {
      args.push("--profile", profile);
    }
    for (const uri of mainUris) {
      args.push(uri.fsPath || uri.path);
    }

    /** @type {PromiseWithResolvers<boolean>} */
    const { promise: launching, resolve: started } = Promise.withResolvers();
    /** @type {PromiseWithResolvers<void>} */
    const { promise: done, resolve: ended } = Promise.withResolvers();
    /** @type {Build} */
    const build = {
      keys,
      done, started,
      cancelled: false,
      cancel() {
        if (build.cancelled) return;
        build.cancelled = true;
        build.interrupt?.();
      }
    };

    // Keep cancelled batches reserved until they stop, including books that
    // weren't targeted by the request that cancelled the batch.
    const blockers = [...builds].filter((other) => [...build.keys].some((key) => other.keys.has(key)));
    builds.add(build);
    for (const other of blockers) other.cancel();

    void (async () => {
      let exitCode;
      let reportExit = false;
      try {
        await Promise.all(blockers.map((other) => other.done));
        if (build.cancelled) return;
        /** @type {import('vscode').Uri | undefined} */
        let commandUri = vscode.Uri.joinPath(folder.uri, settings.compileCommand);
        if (settings.compileCommand === "ulsbs/ulsbs-compile" && !(await uriExists(vscode, commandUri))) {
          const wrapper = vscode.Uri.joinPath(folder.uri, "ulsbs-compile");
          commandUri = await uriExists(vscode, wrapper) ? wrapper : undefined;
        }
        if (build.cancelled) return;
        // A standalone installation can expose the same wrapper on PATH.
        const compilePath = commandUri?.fsPath || commandUri?.path || "ulsbs-compile";
        exitCode = await executeBuild(vscode, build, folder, compilePath, args, options.background, (terminal) => {
          if (disposed) {
            terminal.dispose();
            return;
          }
          const folderKey = folder.uri.toString();
          buildLogs.get(folderKey)?.dispose();
          buildLogs.set(folderKey, terminal);
        });
        reportExit = true;
      } catch (error) {
        if (!build.cancelled) vscode.window.showWarningMessage(`Could not start ULSBS compilation: ${error instanceof Error ? error.message : String(error)}`);
      } finally {
        builds.delete(build);
        ended();
        started(false);
        if ((reportExit || build.cancelled) && typeof options.onExit === "function") {
          try {
            options.onExit(build.cancelled ? undefined : exitCode);
          } catch (error) {
            console.error("ULSBS build exit callback failed", error);
          }
        }
      }
    })();
    return launching;
  }

  async function compileCurrentContext() {
    if (!enabled) {
      return;
    }

    const uri = vscode.window.activeTextEditor?.document?.uri;
    if (!uri) {
      vscode.window.showInformationMessage("No active document.");
      return;
    }

    const roots = await songbookService.getAffectedSongbooks(uri);
    if (!roots.length) {
      vscode.window.showInformationMessage(
        "No containing songbooks found for the current file."
      );
      return;
    }

    await runCompile(
      roots.map((root) => root.uri),
      selectedProfile,
      uri
    );
  }

  async function compileAllSongbooks() {
    if (!enabled) {
      return;
    }

    const uri =
      vscode.window.activeTextEditor?.document?.uri ??
      vscode.workspace.workspaceFolders?.[0]?.uri;

    if (!uri) {
      vscode.window.showInformationMessage("No workspace is open.");
      return;
    }

    const roots = await songbookService.getAllSongbooks(uri);
    if (!roots.length) {
      vscode.window.showInformationMessage("No main songbooks detected.");
      return;
    }

    await runCompile(
      roots.map((root) => root.uri),
      selectedProfile,
      uri
    );
  }

  /** @param {SongbookItem} [item] */
  async function compileSingleSongbook(item) {
    if (!enabled || !item?.uri) {
      return;
    }
    await runCompile([item.uri], selectedProfile, item.uri);
  }

  /** @param {SongbookItem} [item] */
  async function compileSingleSongbookWithProfile(item) {
    if (!enabled || !item?.uri) {
      return;
    }
    const picked = await chooseProfileForUri(item.uri);
    if (!picked) {
      return;
    }
    await runCompile([item.uri], picked, item.uri);
  }

  const disposables = [
    vscode.commands.registerCommand(
      "ulsbsTexTools.compileCurrentContext",
      compileCurrentContext
    ),
    vscode.commands.registerCommand(
      "ulsbsTexTools.compileAllSongbooks",
      compileAllSongbooks
    ),
    vscode.commands.registerCommand(
      "ulsbsTexTools.chooseCompileProfile",
      async () => {
        const uri =
          vscode.window.activeTextEditor?.document?.uri ??
          vscode.workspace.workspaceFolders?.[0]?.uri;
        if (!uri) {
          return;
        }
        await chooseProfileForUri(uri);
      }
    ),
    vscode.commands.registerCommand(
      "ulsbsTexTools.compileSongbook",
      compileSingleSongbook
    ),
    vscode.commands.registerCommand(
      "ulsbsTexTools.compileSongbookWithProfile",
      compileSingleSongbookWithProfile
    ),
    vscode.commands.registerCommand(
      "ulsbsTexTools.openSongbook",
      async (item) => {
        const uri = item?.uri ?? item;
        if (!uri) {
          return;
        }

        const doc = await vscode.workspace.openTextDocument(uri);

        if (item?.selection && typeof item.selection.line === "number") {
          const line = Math.max(0, item.selection.line);
          const character = Math.max(0, item.selection.character ?? 0);
          const position = new vscode.Position(line, character);

          await vscode.window.showTextDocument(doc, {
            selection: new vscode.Range(position, position)
          });
          return;
        }

        await vscode.window.showTextDocument(doc);
      }
    ),
    vscode.commands.registerCommand(
      "ulsbsTexTools.refreshWorkspace",
      async () => {
        await songbookService.refresh();
        treeController?.refresh?.();
        vscode.window.showInformationMessage("ULSBS workspace index refreshed.");
      }
    )
  ];

  context.subscriptions.push(...disposables, {
    dispose() {
      disposed = true;
      for (const build of builds) build.cancel();
      for (const terminal of buildLogs.values()) terminal.dispose();
      buildLogs.clear();
    }
  });

  return {
    /** @param {boolean} value */
    setEnabled(value) {
      enabled = value;
    },
    /**
     * Launch a PDF build of one or more named variants. Returns false if unable to launch or
     * superseded first. `onExit` reports its exit code, or undefined if cancelled.
     * @param {import('vscode').Uri} uri
     * @param {string | string[]} [variant]
     * @param {BuildOptions} [options]
     */
    async compilePreview(uri, variant = "default", options = {}) {
      const names = [...new Set(Array.isArray(variant) ? variant : [variant])];
      if (!names.length || names.some((name) => typeof name !== "string" || name === "all" || !/^[a-z][a-z0-9-]*$/.test(name))) return false;
      return runCompile([uri], selectedProfile, uri, ["--variants", names.join(","), ...PREVIEW_ARGS], options);
    },
    /** @param {import('vscode').Uri} uri */
    getBuildSaveTargets(uri) {
      return savingForBuild.get(uri.toString());
    },
    getSelectedProfile() {
      return selectedProfile;
    }
  };
}

module.exports = {
  registerCompileCommands
};
