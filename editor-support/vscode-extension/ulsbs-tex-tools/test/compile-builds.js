// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

// Exercise build arguments and scheduling with controllable terminal and process lifecycles.
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { EventEmitter } = require("node:events");
const { PassThrough } = require("node:stream");
const childProcess = require("node:child_process");
const path = require("node:path").posix;
const { setImmediate: flush } = require("node:timers/promises");
const { registerCompileCommands } = require("../core/compile");

function uri(value) {
  return { fsPath: value, path: value, toString: () => `file://${value}` };
}

function harness(t) {
  const folder = { uri: uri("/workspace/project with spaces") };
  const joinPath = (base, name) => uri(path.join(base.path, name));
  const a = joinPath(folder.uri, "book 'a'.tex");
  const b = joinPath(folder.uri, "book b.tex");
  const c = joinPath(folder.uri, "other.tex");
  const commands = new Map();
  const children = [];
  const terminals = [];
  const warnings = [];
  const info = [];
  const prompts = [];
  const subscriptions = [];
  const state = { wrapper: joinPath(folder.uri, "ulsbs/ulsbs-compile").path };
  t.mock.method(childProcess, "spawn", (command, args, options) => {
    const child = Object.assign(new EventEmitter(), {
      command, args, options,
      stdout: new PassThrough(), stderr: new PassThrough(),
      signals: [], kill(signal) { this.signals.push(signal); },
      finish(code) { this.emit("close", code); }
    });
    children.push(child);
    queueMicrotask(() => {
      if (state.spawnError) {
        child.emit("error", new Error("ENOENT"));
        child.finish(-2);
      } else {
        child.pid = 1;
        child.emit("spawn");
      }
    });
    return child;
  });
  const vscode = {
    Uri: { joinPath },
    UIKind: { Web: 2 }, env: { uiKind: 1 },
    EventEmitter: class {
      listeners = new Set();
      event = (callback) => { this.listeners.add(callback); };
      fire(value) { for (const callback of this.listeners) callback(value); }
      dispose() { this.listeners.clear(); }
    },
    commands: { registerCommand(name, callback) { commands.set(name, callback); } },
    workspace: {
      getWorkspaceFolder: () => folder,
      textDocuments: [],
      asRelativePath: (candidate) => path.relative(folder.uri.path, candidate.path),
      getConfiguration: () => ({ get: (key, fallback) =>
        ({ askProfileOnCompile: false, defaultProfile: "print" })[key] ?? fallback }),
      fs: { async stat(candidate) { if (candidate.path !== state.wrapper) throw new Error("Not found"); } }
    },
    window: {
      activeTextEditor: { document: { uri: a } },
      createTerminal({ pty }) {
        if (state.terminalError) throw new Error("Terminal rejected");
        const terminal = { pty, output: [], shown: false, disposed: false,
          show(preserveFocus) { assert.equal(preserveFocus, true); this.shown = true; },
          dispose() { this.disposed = true; pty.close(); } };
        pty.onDidWrite((text) => terminal.output.push(text));
        terminals.push(terminal);
        if (!state.pauseTerminal) queueMicrotask(() => { if (!terminal.disposed) pty.open(); });
        return terminal;
      },
      showInformationMessage: (message) => info.push(message),
      showWarningMessage(message, options, ...choices) {
        if (options?.modal) {
          prompts.push({ message, detail: options.detail, choices });
          return state.answer;
        }
        warnings.push(message);
      }
    }
  };
  const compile = registerCompileCommands(vscode, { subscriptions }, {
    getProfiles: async () => ["default", "print"],
    getAffectedSongbooks: async (uri) => uri.path.endsWith("unrelated.tex") ? [] : [{ uri: a }, { uri: b }],
    getAllSongbooks: async () => [{ uri: a }, { uri: b }, { uri: c }]
  });
  compile.setEnabled(true);
  const command = (name, item) => commands.get(`ulsbsTexTools.${name}`)(item);
  return { a, b, c, compile, command, folder, children, terminals, vscode, state, prompts, warnings, info, subscriptions };
}

test("preview builds selected PDF variants, passes literal args and uses normal wrapper fallbacks", async (t) => {
  const { a, compile, command, folder, children, terminals, state } = harness(t);
  await command("chooseCompileProfile");
  const exits = [];
  assert.equal(await compile.compilePreview(a, "lyric", { background: true, onExit: (code) => exits.push(code) }), true);
  assert.equal(children[0].command, state.wrapper);
  assert.equal(children[0].options.cwd, folder.uri.path);
  assert.equal(children[0].options.env.TERM, "xterm-256color");
  assert.equal(children[0].options.env.ULSBS_INTERNAL_TERMINAL_OUTPUT, "1");
  assert.equal(children[0].options.env.NO_COLOR, process.env.NO_COLOR);
  assert.deepEqual(children[0].args, ["--synctex", "--variants", "lyric", "--no-deploy", "--no-printouts",
    "--no-multikey", "--no-coverimage", "--no-json", "--no-midi", "--no-audio", "--keep-temp", "--profile", "print", a.path]);
  assert.equal(terminals[0].shown, false);
  children[0].stdout.write("\x1b[32mfirst\x1b[0m\nsecond\r\n\r\x1b[KWorking...");
  assert.deepEqual(terminals[0].output, ["\x1b[32mfirst\x1b[0m\r\nsecond\r\n\r\x1b[KWorking..."]);
  children[0].finish(7);
  await flush();
  assert.deepEqual(exits, [7]);

  state.wrapper = path.join(folder.uri.path, "ulsbs-compile");
  assert.equal(await compile.compilePreview(a), true);
  assert.equal(children[1].command, state.wrapper);
  assert.equal(children[1].args[2], "default");
  assert.equal(terminals[1].shown, true);
  assert.equal(terminals[0].disposed, false, "finished output is still available");
  children[1].finish(0);
  await flush();
  assert.equal(terminals[0].disposed, true, "keep only the latest finished log");
  state.wrapper = undefined;
  assert.equal(await compile.compilePreview(a, ["default", "lyric", "lyric"]), true);
  assert.equal(children[2].command, "ulsbs-compile");
  assert.equal(children[2].args[2], "default,lyric");
  children[2].finish(0);
  for (const invalid of ["all", "default,lyric", "--no-deploy", "", null, [], ["lyric", "all"]]) {
    assert.equal(await compile.compilePreview(a, invalid), false);
  }
  assert.equal(children.length, 3);
});

test("replacement waits for actual child exit; a cancelled batch still reserves all its books", async (t) => {
  const { a, b, c, compile, command, children, terminals } = harness(t);
  const exits = [];
  await command("compileCurrentContext");
  assert.deepEqual(children[0].args, ["--synctex", a.path, b.path]);
  const cancelled = compile.compilePreview(a, "lyric", { onExit: (code) => exits.push(["queued", code]) });
  const latest = compile.compilePreview(a, "default", { background: true, onExit: (code) => exits.push(["latest", code]) });
  const otherBatchBook = compile.compilePreview(b);
  assert.equal(await compile.compilePreview(c), true);
  assert.deepEqual(children.map((child) => child.args.at(-1)), [b.path, c.path]);
  assert.deepEqual(children[0].signals, ["SIGINT"]);
  terminals[0].dispose(); // Closing the terminal must not let a successor overlap the compiler.
  await flush();
  assert.equal(children.length, 2);
  children[0].finish(130);
  assert.equal(await cancelled, false);
  assert.equal(await latest, true);
  assert.equal(await otherBatchBook, true);
  assert.deepEqual(exits, [["queued", undefined]]);
  assert.deepEqual(children.slice(2).map((child) => child.args.at(-1)).sort(), [a.path, b.path].sort());

  const launched = children.find((child, index) => index > 1 && child.args.at(-1) === a.path);
  const normal = command("compileSongbookWithProfile", { uri: a });
  await flush();
  assert.deepEqual(launched.signals, ["SIGINT"]);
  assert.equal(children.length, 4);
  launched.finish(1);
  await normal;
  assert.deepEqual(exits, [["queued", undefined], ["latest", undefined]]);
  assert.deepEqual(children[4].args, ["--synctex", "--profile", "print", a.path]);
  for (const child of children.slice(1)) child.finish(0);
});

test("terminal cancellation and closing before open surface undefined", async (t) => {
  const { a, compile, children, terminals, state } = harness(t);
  const exits = [];
  const options = { onExit: (code) => exits.push(code) };
  assert.equal(await compile.compilePreview(a, undefined, options), true);
  terminals[0].pty.handleInput("\x03");
  terminals[0].dispose();
  assert.deepEqual(children[0].signals, ["SIGINT"]);
  assert.deepEqual(exits, []);
  children[0].finish(130);
  await flush();
  assert.deepEqual(exits, [undefined]);

  state.pauseTerminal = true;
  const launching = compile.compilePreview(a, undefined, options);
  await flush();
  terminals[1].dispose();
  assert.equal(await launching, false);
  assert.deepEqual(exits, [undefined, undefined]);
  assert.equal(children.length, 1);
});

test("manual builds ask before saving only affected dirty files", async (t) => {
  const { a, folder, compile, children, vscode, state, prompts, warnings } = harness(t);
  const saved = [];
  const dirty = (source) => ({ uri: source, isDirty: true, async save() {
    assert.ok(compile.getBuildSaveTargets(this.uri).has(a.toString()));
    saved.push(this.uri.path);
    this.isDirty = false;
    return true;
  } });
  const main = dirty(a);
  const song = dirty(uri(`${folder.uri.path}/songs.tex`));
  const unrelated = dirty(uri(`${folder.uri.path}/unrelated.tex`));
  vscode.workspace.textDocuments.push(main, song, unrelated);

  assert.equal(await compile.compilePreview(a), false, "dismissing the prompt cancels the build");
  assert.equal(children.length, 0);
  assert.deepEqual(saved, []);
  assert.match(prompts[0].detail, /songs\.tex/);
  assert.doesNotMatch(prompts[0].detail, /unrelated\.tex/);

  state.answer = "Build Without Saving";
  assert.equal(await compile.compilePreview(a), true);
  assert.deepEqual(saved, []);
  state.answer = undefined;
  assert.equal(await compile.compilePreview(a), false);
  assert.deepEqual(children[0].signals, [], "dismissing the prompt leaves the current build running");
  children[0].finish(0);
  await flush();

  state.answer = "Save and Build";
  assert.equal(await compile.compilePreview(a), true);
  assert.deepEqual(saved, [a.path, song.uri.path]);
  assert.equal(unrelated.isDirty, true);
  assert.equal(compile.getBuildSaveTargets(a), undefined);
  assert.equal(compile.getBuildSaveTargets(song.uri), undefined);
  children[1].finish(0);
  await flush();

  song.isDirty = true;
  song.save = async () => false;
  assert.equal(await compile.compilePreview(a), false);
  assert.match(warnings.at(-1), /could not save songs\.tex/);
  assert.equal(children.length, 2);

  assert.equal(await compile.compilePreview(a, undefined, { background: true }), true);
  assert.equal(prompts.length, 5, "background builds must not prompt or save");
  assert.equal(song.isDirty, true);
  children[2].finish(0);
});

test("startup failures, untrusted workspaces and browser-only builds do not report a compiler exit", async (t) => {
  const { a, compile, command, children, state, vscode, warnings, info } = harness(t);
  const options = { onExit: () => assert.fail("Compiler did not start") };
  state.terminalError = true;
  assert.equal(await compile.compilePreview(a, undefined, options), false);
  assert.match(warnings.at(-1), /Terminal rejected/);
  state.terminalError = false;
  state.spawnError = true;
  assert.equal(await compile.compilePreview(a, undefined, options), false);
  assert.match(warnings.at(-1), /ENOENT/);

  vscode.workspace.isTrusted = false;
  assert.equal(await compile.compilePreview(a, undefined, options), false);
  assert.match(warnings.at(-1), /trusted workspace/);
  assert.equal(await compile.compilePreview(a, undefined, { ...options, background: true }), false);
  assert.equal(warnings.length, 3);

  vscode.env.uiKind = vscode.UIKind.Web;
  assert.equal(await compile.compilePreview(a, undefined, options), false);
  await command("compileAllSongbooks");
  assert.equal(children.length, 1);
  assert.equal(info.length, 2);
});
