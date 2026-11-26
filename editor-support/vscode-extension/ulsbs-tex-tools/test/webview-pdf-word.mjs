// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

// Verify native-coordinate text hits without relying on installed browser fonts.
import assert from "node:assert/strict";
import test from "node:test";
import { findPdfWord } from "../webview/pdf-word.mjs";

function run(str, x, y = 30, width = str.length * 5) {
  return { str, width, dir: "ltr", transform: [10, 0, 0, 10, x, y], fontName: "body" };
}

const measure = (font, str) => ({
  width: Array.from(str, char => char === "W" ? 80 : 50).reduce((a, b) => a + b, 0),
  actualBoundingBoxAscent: 70,
  actualBoundingBoxDescent: 20
});
const lookup = (items, x, y = 34) => findPdfWord({ items, styles: { body: { fontFamily: "sans-serif" } } }, x, y, measure);

test("uses measured proportions within a run and misses its space and exterior", () => {
  const items = [run("WW sol", 10, 30, 36)];
  assert.equal(lookup(items, 25), "WW");
  assert.equal(lookup(items, 29), undefined);
  assert.equal(lookup(items, 36), "sol");
  assert.equal(lookup(items, 9.9), undefined);
  assert.equal(lookup(items, 46), undefined);
  assert.equal(lookup(items, 36, 38), undefined);
});

test("joins touching fragments across interleaved notes without joining different rows", () => {
  const items = [run("Mas a", 10), run("F", 35, 42), run("", 35), run("gora n\u00e3o", 35)];
  assert.equal(lookup(items, 32), "agora");
  assert.equal(lookup(items, 43), "agora");
  assert.equal(lookup(items, 62), "n\u00e3o");
  assert.equal(lookup(items, 37, 46), "F");
});

test("wide gaps, whitespace and punctuation do not create joined words or hits", () => {
  const items = [run("re", 10), run("vela", 22), run("--", 55), run("mais ", 100), run("um", 125)];
  assert.equal(lookup(items, 17), "re");
  assert.equal(lookup(items, 21), undefined);
  assert.equal(lookup(items, 30), "vela");
  assert.equal(lookup(items, 57), undefined);
  assert.equal(lookup(items, 116), "mais");
  assert.equal(lookup(items, 127), "um");
});

test("rejects ambiguous hits and unsupported text orientations", () => {
  const tilted = { ...run("rotate", 50), transform: [10, 0.5, 0, 10, 50, 30] };
  assert.equal(lookup([run("one", 10), run("two", 12), tilted], 17), undefined);
  assert.equal(lookup([run("one", 10), run("two", 12), tilted], 55), undefined);
  assert.equal(lookup([run("a", 10), run("b", 15), run("c", 15)], 12), undefined);
});

test("keeps internal punctuation but cannot resolve a trailing hyphen alone", () => {
  assert.equal(lookup([run("senti-", 10), run("do", 40)], 31), "senti-do");
  assert.equal(lookup([run("senti-", 10), run("do", 45)], 31), undefined);
  assert.equal(lookup([run("guarda\u2011chuva", 10)], 52), "guarda\u2011chuva");
  assert.equal(lookup([run("d\u2019agua", 10)], 23), "d\u2019agua");
});
