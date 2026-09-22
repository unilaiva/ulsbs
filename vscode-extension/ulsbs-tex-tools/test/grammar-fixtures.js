// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const grammar = JSON.parse(
  fs.readFileSync(path.join(root, "syntaxes", "ulsbs-chord.injection.tmLanguage.json"), "utf8")
);
const fixtures = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "ulsbs-chord-injection.json"), "utf8")
);
const pattern = grammar.patterns[0];
const chordPattern = new RegExp(pattern.match);

assert.equal(grammar.injectionSelector, "L:text.tex.latex");
assert.equal(pattern.name, "meta.ulsbs.chord.latex");

for (const fixture of fixtures.valid) {
  assert.equal(chordPattern.test(fixture), true, `Expected grammar to match: ${fixture}`);
}

for (const fixture of fixtures.invalid) {
  assert.equal(chordPattern.test(fixture), false, `Expected grammar not to match: ${fixture}`);
}
