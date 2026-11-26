// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

// Index ULSBS's LuaLaTeX PDF sidecar without the native SyncTeX library.
// Record syntax and coordinate math follow TeX Live's synctex.5 and
// synctex_parser.c (not its filename lookup or query heuristics).

const SP_TO_BP = 72 / (72.27 * 65536);
const RECORD = /^([\[(vhxkg$r])(\d+),(-?\d+)(?:,-?\d+)?:([+-]?\d+),([+-]?\d+|=)(?::([+-]?\d+)(?:,([+-]?\d+),([+-]?\d+))?)?$/;
const UNLINKED = /^(?:[c?]|f\d+:)[+-]?\d+,([+-]?\d+|=)(?::[+-]?\d+,[+-]?\d+)?$/;
const POSITIVE_INT = (value) => Number.isSafeInteger(value) && value > 0;
const MAX_INVERSE_DISTANCE = 36; // bp from the nearest useful record, including penalties

/** Read gzip bytes, calling resolveSource with the exact published input name.
 * Queries use 1-based pages and lines, and top-left PDF big points (1/72 in).
 */
async function readSyncTeX(bytes, resolveSource) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  const text = new TextDecoder("utf-8", { fatal: true }).decode(await new Response(stream).arrayBuffer());
  const tags = new Map();
  const scoreTags = new Set();
  const scores = new Map();
  const headers = new Map();
  const pages = new Map();
  const sources = new Map();
  const boxes = [];
  let section = "header";
  let page = 0;
  let lastV;
  let unit, mag, offsetX, offsetY;

  // Scan in file order so compressed points can borrow even from untrusted
  // or unmapped records. Links are resolved only after collecting all inputs.
  const records = [];
  for (const [row] of text.matchAll(/[^\r\n]+/g)) {
    if (section === "header") {
      if (row !== "SyncTeX Version:1") throw new Error("Unsupported SyncTeX version");
      section = "preamble";
      continue;
    }
    if (row === "Postamble:") break; // ULSBS does not post-process its PDFs or sidecar coordinates.
    const input = /^Input:(\d+):([^\0]+)$/.exec(row);
    if (input) {
      const tag = Number(input[1]);
      if (POSITIVE_INT(tag)) {
        tags.set(tag, resolveSource(input[2]));
        if (/-systems\.tex$/.test(input[2])) scoreTags.add(tag);
      }
      continue;
    }
    if (section === "preamble") {
      if (row === "Content:") section = "content";
      else if (row.startsWith("Unit:")) unit = Number(row.slice(5));
      else if (row.startsWith("Magnification:")) mag = Number(row.slice(14));
      else if (row.startsWith("X Offset:")) offsetX = Number(row.slice(9));
      else if (row.startsWith("Y Offset:")) offsetY = Number(row.slice(9));
      continue;
    }
    if (/^[{}]\d+$/.test(row)) {
      const number = Number(row.slice(1));
      page = row[0] === "{" && POSITIVE_INT(number) ? number : 0;
      boxes.length = 0;
      continue;
    }
    if (row === "]" || row === ")") {
      boxes.pop();
      continue;
    }
    const match = RECORD.exec(row);
    if (!match) {
      const unlinked = UNLINKED.exec(row);
      if (unlinked && unlinked[1] !== "=" && Number.isSafeInteger(Number(unlinked[1]))) {
        lastV = Number(unlinked[1]);
      }
      continue;
    }
    const [, type, rawTag, rawLine, rawH, rawV, w = "0", h = "0", d = "0"] = match;
    const v = rawV === "=" ? lastV : Number(rawV);
    if (!Number.isSafeInteger(v)) continue;
    lastV = v;
    if (!page) continue;

    const [tag, line, x, width, height, depth] = [rawTag, rawLine, rawH, w, h, d].map(Number);
    if (![tag, line, x, width, height, depth].every(Number.isSafeInteger)) continue;
    const box = boxes[boxes.length - 1];
    // x records mark the end of a run of text. The previous run's endpoint
    // (or the hbox's start on the same baseline) also covers clicks on that run.
    let left = x + (type === "k" ? -width : 0);
    const right = x + (type === "k" ? 0 : width);
    let inverseLine = line;
    if (type === "x" && box?.type === "(" && box.v === v) {
      left = box.end;
      box.end = x;
      // A boundary can be tagged with the enclosing vertical list's output
      // line instead of the lyric line in its hbox. Only prefer the hbox when
      // the competing tag actually matches an ancestor in the same source.
      if (box.tag === tag && box.line > 0 && box.line !== line &&
          boxes.some((ancestor) => ancestor.type === "[" && ancestor.tag === tag && ancestor.line === line)) {
        inverseLine = box.line;
      }
    }
    if (type === "[" && box?.type === "[" && box.tag === tag && box.line === line &&
        box.x === x && box.v === v && box.width === width && width > 0 &&
        height > 0 && depth === 0 && box.height > 16 * height &&
        height * SP_TO_BP < 30 && v * SP_TO_BP < 65) {
      // The page output routine puts the running head in a shallow full-width
      // vbox at the start of the page envelope, tagged with the shipout line.
      if (!headers.has(page)) headers.set(page, { x, v, width, height });
    }
    if (type === "(" || type === "[") boxes.push({ type, tag, line, x, v, width, height, end: x });
    if (tag > 0 && line > 0) {
      const record = { page, tag, line, inverseLine, type, x, v, left, right, height, depth };
      if (type === "(" && box?.type === "(" && box.tag !== tag) record.owner = box;
      records.push(record);
    }
  }

  if (section !== "content" || !POSITIVE_INT(unit) || !POSITIVE_INT(mag) ||
      !Number.isSafeInteger(offsetX) || !Number.isSafeInteger(offsetY)) {
    throw new Error("Invalid SyncTeX preamble");
  }
  const scale = unit * SP_TO_BP * mag / 1000;
  const xOffset = offsetX * unit * SP_TO_BP;
  const yOffset = offsetY * unit * SP_TO_BP;

  for (const r of records) {
    const source = tags.get(r.tag);
    if (!source && scoreTags.has(r.tag)) {
      // An engraved system is an imported PDF box. Its enclosing authored hbox
      // identifies this placement, even if LilyPond reuses the same system file.
      const owner = r.owner;
      const authored = owner && tags.get(owner.tag);
      if (authored && POSITIVE_INT(owner.line) && r.right > r.left && r.height > 0 && r.depth >= 0) {
        if (!scores.has(r.page)) scores.set(r.page, []);
        scores.get(r.page).push({ source: authored, line: owner.line,
          left: xOffset + r.left * scale, right: xOffset + r.right * scale,
          top: yOffset + (r.v - r.height) * scale, bottom: yOffset + (r.v + r.depth) * scale });
      }
      continue;
    }
    if (typeof source !== "string" || !source) continue;
    const x = xOffset + r.x * scale;
    const y = yOffset + r.v * scale;
    const horizontal = r.type === "(" || r.type === "h";
    const vertical = r.type === "[" || r.type === "v";
    const sparse = r.type === "g" || r.type === "k";
    const rule = r.type === "r";
    const priority = r.type === "x" ? 0 : horizontal || r.type === "$" || rule ? 1 : sparse ? 2 : 3;

    if (!sources.has(source)) sources.set(source, new Map());
    const lines = sources.get(source);
    if (!lines.has(r.line)) lines.set(r.line, new Map());
    const hits = lines.get(r.line);
    const prior = hits.get(r.page);
    if (!prior || priority < prior.priority) hits.set(r.page, { page: r.page, x, y, priority });

    // Page/container boxes usually carry the source line that caused shipout,
    // not the text clicked. Exclude tall boxes from inverse search entirely.
    if ((horizontal || vertical) && Math.abs(r.height + r.depth) * scale > MAX_INVERSE_DISTANCE) continue;
    if (!pages.has(r.page)) pages.set(r.page, []);
    // Musical bars are TeX rules, not text boxes. Their raw dimensions can
    // contain TeX's running-dimension sentinel (-2^30), not a measured size.
    // Use only their anchor as a fallback so a bar cannot capture distant lyrics.
    const left = rule ? x : xOffset + Math.min(r.left, r.right) * scale;
    const right = rule ? x : xOffset + Math.max(r.left, r.right) * scale;
    const top = rule ? y : y - Math.max(r.height, -r.depth, 0) * scale;
    const bottom = rule ? y : y + Math.max(r.depth, -r.height, 0) * scale;
    const penalty = vertical ? 16 : sparse || rule ? 8 : horizontal ? 4 : 0;
    pages.get(r.page).push({ source, line: r.inverseLine, left, right, top, bottom, x, y, penalty });
  }

  return {
    forward(sourceKey, line, pageHint) {
      if (!POSITIVE_INT(line)) return null;
      const hits = sources.get(sourceKey)?.get(line);
      if (!hits) return null;
      let best;
      let bestDistance = Infinity;
      for (const hit of hits.values()) {
        const distance = POSITIVE_INT(pageHint) ? Math.abs(pageHint - hit.page) : 0;
        if (!best || distance < bestDistance || (distance === bestDistance &&
            (hit.priority < best.priority || (hit.priority === best.priority && hit.page < best.page)))) {
          best = hit;
          bestDistance = distance;
        }
      }
      return { page: best.page, x: best.x, y: best.y };
    },
    inverse(page, x, y) {
      if (!POSITIVE_INT(page) || !Number.isFinite(x) || !Number.isFinite(y)) return null;
      const header = headers.get(page);
      if (header && x >= xOffset + header.x * scale && x <= xOffset + (header.x + header.width) * scale &&
          y >= yOffset + header.v * scale && y <= yOffset + (header.v + header.height) * scale) {
        return { kind: "header" };
      }
      let scoreTarget;
      for (const score of scores.get(page) || []) {
        if (x < score.left || x > score.right || y < score.top || y > score.bottom) continue;
        if (scoreTarget && (scoreTarget.source !== score.source || scoreTarget.line !== score.line)) return null;
        scoreTarget = score;
      }
      if (scoreTarget) return { source: scoreTarget.source, line: scoreTarget.line, kind: "lilypond" };
      let best;
      let bestScore = MAX_INVERSE_DISTANCE;
      let bestAnchorDistance = Infinity;
      for (const hit of pages.get(page) || []) {
        const dx = Math.max(hit.left - x, x - hit.right, 0);
        const dy = Math.max(hit.top - y, y - hit.bottom, 0);
        // Prefer the nearby text row to a merely closer endpoint horizontally.
        const score = Math.hypot(dx * 0.5, dy) + hit.penalty;
        const anchorDistance = Math.hypot(x - hit.x, y - hit.y);
        if (score < bestScore || (best && score === bestScore && anchorDistance < bestAnchorDistance)) {
          best = hit;
          bestScore = score;
          bestAnchorDistance = anchorDistance;
        }
      }
      return best ? { source: best.source, line: best.line } : null;
    }
  };
}

module.exports = { readSyncTeX };
