// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

// Hit-test ordinary horizontal text in native PDF coordinates, independent of the text layer.

const words = /[\p{L}\p{N}][\p{L}\p{N}\p{M}]*(?:['\u02bc\u2019\u2010\u2011-][\p{L}\p{N}\p{M}]+)*[\u2010\u2011-]?/gu;

function getRun(item, styles) {
  const style = styles[item.fontName];
  if (!item.str?.trim() || item.dir !== "ltr" || !style || style.vertical) return;
  const [a, b, c, size, x, y] = item.transform;
  const width = item.width;
  if (![a, b, c, size, x, y, width].every(Number.isFinite) ||
      a <= 0 || size <= 0 || width <= 0 || Math.abs(b) > 1e-6 || Math.abs(c) > 1e-6) return;
  return { x, y, size, width, text: item.str, font: style.fontFamily };
}

// PDF.js supplies whole-run advances, not per-word bounds. Use font measurements
// for the proportions inside a run and the PDF advance for its actual width.
export function findPdfWord({ items, styles }, x, y, measure) {
  const runs = [];
  let hit;
  for (const item of items) {
    const run = getRun(item, styles);
    if (!run || Math.abs(run.y - y) > run.size) continue;
    runs.push(run);
    if (x < run.x || x >= run.x + run.width) continue;

    const metrics = text => measure(run.font, text);
    const width = metrics(run.text).width;
    if (!(width > 0)) continue;
    const localX = (x - run.x) * width / run.width;
    for (const match of run.text.matchAll(words)) {
      const [word] = match;
      const start = match.index;
      const end = start + word.length;
      const left = start ? metrics(run.text.slice(0, start)).width : 0;
      const right = end < run.text.length ? metrics(run.text.slice(0, end)).width : width;
      if (localX < left || localX >= right) continue;
      const { actualBoundingBoxAscent: ascent, actualBoundingBoxDescent: descent } = metrics(word);
      const localY = (y - run.y) * 100 / run.size;
      if (!(localY >= -descent && localY <= ascent)) continue;
      if (hit) return; // Overlapping word boxes give no unique hit.
      hit = { word, start, end, run };
    }
  }
  if (!hit) return;

  // ULSBS can interleave notes/chords between syllables in extraction order.
  // Join only at adjoining run edges on the same physical baseline and size.
  // The join never creates a hit in the gap, and a competing neighbor is ambiguous.
  let word = hit.word;
  const seen = new Set([hit.run]);
  for (const backwards of [true, false]) {
    let part = hit;
    while (backwards ? part.start === 0 : part.end === part.run.text.length) {
      const { run } = part;
      let next;
      for (const candidate of runs) {
        if (seen.has(candidate) || Math.abs(candidate.y - run.y) > run.size * 0.02 ||
            Math.abs(candidate.size - run.size) > run.size * 0.02) continue;
        const gap = backwards ? run.x - candidate.x - candidate.width : candidate.x - run.x - run.width;
        if (Math.abs(gap) > run.size * 0.08 || (backwards ? candidate.x >= run.x : candidate.x <= run.x)) continue;
        const match = Array.from(candidate.text.matchAll(words)).find(match => backwards
          ? match.index + match[0].length === candidate.text.length : match.index === 0);
        if (!match) continue;
        if (next) return;
        next = { word: match[0], start: match.index, end: match.index + match[0].length, run: candidate };
      }
      if (!next) break;
      seen.add(next.run);
      word = backwards ? next.word + word : word + next.word;
      part = next;
    }
  }
  if (!/[\u2010\u2011-]$/.test(word)) return word;
}

let context;

export function measurePdfText(font, text) {
  context ??= document.createElement("canvas").getContext("2d");
  context.font = `100px ${font}`;
  return context.measureText(text);
}
