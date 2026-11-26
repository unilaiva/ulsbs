// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

const assert = require("node:assert/strict");

const { getSettings } = require("../core/config");
const { shouldProcessDocument } = require("../core/filetypes");
const { createSongbookService, isSongbookDiscoveryExcludedUri } = require("../core/songbooks");
const path = require("node:path").posix;

const configuredValues = {
  excludeGlob: ["**/temp/**"],
  songbookExcludeGlob: ["**/drafts/**"]
};

const vscode = {
  workspace: {
    getConfiguration() {
      return {
        get(name) {
          return configuredValues[name];
        }
      };
    },
    asRelativePath(uri) {
      return uri.path;
    }
  }
};

const settings = getSettings(vscode);
const discoveryExcludes = [
  ...settings.excludeGlob,
  ...settings.songbookExcludeGlob
];

assert.ok(settings.songbookExcludeGlob.includes("**/.*/**"));
assert.ok(settings.songbookExcludeGlob.includes("**/build/**"));
assert.ok(settings.songbookExcludeGlob.includes("**/ulsbs/tests/**"));
assert.ok(settings.songbookExcludeGlob.includes("**/tests/fixtures/**"));
assert.ok(settings.songbookExcludeGlob.includes("**/drafts/**"));
assert.deepEqual(configuredValues.songbookExcludeGlob, ["**/drafts/**"]);

function isExcluded(path) {
  return isSongbookDiscoveryExcludedUri(vscode, { path }, discoveryExcludes);
}

assert.equal(isExcluded("content/songbook.tex"), false);
assert.equal(isExcluded("build/songbook.tex"), true);
assert.equal(isExcluded("ulsbs/build/lib/ulsbs/assets/songbook.tex"), true);
assert.equal(isExcluded("content/build-notes/songbook.tex"), false);
assert.equal(isExcluded(".kilo/generated-songbook.tex"), true);
assert.equal(isExcluded("project/.venv-release/songbook.tex"), true);
assert.equal(isExcluded("vendor/ulsbs/tests/songbook.tex"), true);
assert.equal(isExcluded("ulsbs/editor-support/vscode-extension/ulsbs-tex-tools/assets/songbook-template_A5.tex"), true);
assert.equal(isExcluded("vendor/tests/fixtures/songbook.tex"), true);
assert.equal(isExcluded("drafts/songbook.tex"), true);
assert.equal(isExcluded("temp/songbook.tex"), true);
assert.equal(
  shouldProcessDocument(
    vscode,
    { uri: { path: ".kilo/generated-songbook.tex" } },
    settings
  ),
  true
);
assert.equal(
  shouldProcessDocument(
    vscode,
    { uri: { path: "drafts/songbook.tex" } },
    settings
  ),
  true
);
assert.equal(shouldProcessDocument(vscode, { uri: { path: "build/songbook.tex" } }, settings), true);

async function testDiscovery() {
  class Uri {
    constructor(value) { this.path = this.fsPath = value; }
    toString() { return `file://${this.path}`; }
    with({ path }) { return new Uri(path); }
    static joinPath(base, ...parts) { return new Uri(path.join(base.path, ...parts)); }
  }
  const folder = { uri: new Uri("/workspace/second project") };
  const source = "\\beginsong{Shared song}[by={Author},key={C}]\n\\beginverse\n\\[<C>Am]Words\n\\endverse\n\\endsong";
  const files = new Map([
    ["book_A5.tex", "\\documentclass[\n variants={default,lyric,charango,bassclef}\n]{ulsbs-songbook}\n\\begin{document}\n\\begin{ulSongs}{titleidx,authidx,tagidx}\n\\input{content/songs}\n\\end{ulSongs}\n\\end{document}"],
    ["draft_A5.tex", "\\documentclass[\n variants={default}\n]{ulsbs-songbook}\n\\input{content/songs}"],
    ["content/songs.tex", source],
    [".cache/generated.tex", "\\documentclass{ulsbs-songbook}"],
    ["ulsbs/build/lib/book.tex", "\\documentclass{ulsbs-songbook}"],
    ["tests/fixtures/book.tex", "\\documentclass{ulsbs-songbook}"],
    ["ulsbs-config.toml", '[profiles.print]\nvariants = ["default", "lyric"]\n[profiles.proof]\nvariants = "all"']
  ]);
  const settings = { askProfileOnCompile: false, defaultProfile: "print" };
  const api = {
    Uri,
    RelativePattern: class {},
    workspace: {
      workspaceFolders: [folder],
      getConfiguration: () => ({ get: (key) => settings[key] }),
      getWorkspaceFolder: () => folder,
      asRelativePath: (uri) => path.relative(folder.uri.path, uri.path),
      findFiles: async () => [...files.keys()].filter((name) => name.endsWith(".tex"))
        .map((name) => Uri.joinPath(folder.uri, name)),
      fs: {
        async readFile(uri) {
          const text = files.get(path.relative(folder.uri.path, uri.path));
          if (text === undefined) throw new Error("Not found");
          return new TextEncoder().encode(text);
        }
      }
    }
  };
  const service = createSongbookService(api);
  const index = await service.getIndexForUri(folder.uri);
  assert.deepEqual(index.roots.map((root) => root.basename), ["book_A5.tex", "draft_A5.tex"]);
  assert.deepEqual(index.profiles, ["default", "print", "proof"]);
  for (const root of index.roots) {
    assert.deepEqual(root.allSongs.map((song) => [song.name, song.meta.by, song.meta.key]),
      [["Shared song", "Author", "C"]]);
    assert.equal(root.allSongs[0].sourceUri.path, Uri.joinPath(folder.uri, "content/songs.tex").path);
  }
  assert.equal((await service.getAffectedSongbooks(Uri.joinPath(folder.uri, "content/songs.tex"))).length, 2);
  service.dispose();
}

testDiscovery().then(() => console.log("Songbook exclusion and discovery tests passed."))
  .catch((error) => { console.error(error); process.exitCode = 1; });
