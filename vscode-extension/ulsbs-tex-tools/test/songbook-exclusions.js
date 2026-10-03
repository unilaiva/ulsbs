// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

const assert = require("node:assert/strict");

const { getSettings } = require("../core/config");
const { shouldProcessDocument } = require("../core/filetypes");
const { isSongbookDiscoveryExcludedUri } = require("../core/songbooks");

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
assert.ok(settings.songbookExcludeGlob.includes("**/ulsbs/tests/**"));
assert.ok(settings.songbookExcludeGlob.includes("**/tests/fixtures/**"));
assert.ok(settings.songbookExcludeGlob.includes("**/drafts/**"));
assert.deepEqual(configuredValues.songbookExcludeGlob, ["**/drafts/**"]);

function isExcluded(path) {
  return isSongbookDiscoveryExcludedUri(vscode, { path }, discoveryExcludes);
}

assert.equal(isExcluded("content/songbook.tex"), false);
assert.equal(isExcluded(".kilo/generated-songbook.tex"), true);
assert.equal(isExcluded("project/.venv-release/songbook.tex"), true);
assert.equal(isExcluded("vendor/ulsbs/tests/songbook.tex"), true);
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

console.log("Songbook exclusion tests passed.");
