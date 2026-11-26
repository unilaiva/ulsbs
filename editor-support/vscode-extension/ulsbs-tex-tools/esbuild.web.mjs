// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

// Bundle the browser extension host and its separately sandboxed PDF viewer.

import * as esbuild from "esbuild";
import { cp, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const watch = process.argv.includes("--watch");
const require = createRequire(import.meta.url);
const pdfjs = dirname(require.resolve("pdfjs-dist/package.json"));
const viewer = dirname(require.resolve("@unilarva/pdfjs-viewer/package.json"));
const pdfOutput = "dist/pdf";

/** @type {import('esbuild').BuildOptions} */
const options = {
  entryPoints: ["extension.js"],
  bundle: true,
  outfile: "dist/web/extension.js",
  platform: "browser",
  format: "cjs",
  target: "es2020",
  external: ["vscode"],
  sourcemap: true,
  logLevel: "info"
};

const pdfOptions = {
  entryPoints: ["webview/viewer.js"],
  bundle: true,
  outfile: `${pdfOutput}/viewer.js`,
  platform: "browser",
  format: "esm",
  target: "esnext",
  sourcemap: true,
  logLevel: "info"
};

// Keep the worker and its support data on the same PDF.js build/version as the API.
// The upstream worker is a standalone module, suitable for loading from a blob URL.
await mkdir(pdfOutput, { recursive: true });
await Promise.all([
  cp(join(pdfjs, "build/pdf.worker.min.mjs"), join(pdfOutput, "pdf.worker.min.mjs")),
  cp(join(pdfjs, "LICENSE"), join(pdfOutput, "LICENSE-pdfjs-dist")),
  cp(join(viewer, "LICENSE"), join(pdfOutput, "LICENSE-unilarva-pdfjs-viewer")),
  ...["cmaps", "iccs", "standard_fonts", "wasm"].map(name =>
    cp(join(pdfjs, name), join(pdfOutput, name), { recursive: true })
  )
]);

if (watch) {
  const contexts = await Promise.all([esbuild.context(options), esbuild.context(pdfOptions)]);
  await Promise.all(contexts.map(ctx => ctx.watch()));
  console.log("Watching web extension build...");
} else {
  await Promise.all([esbuild.build(options), esbuild.build(pdfOptions)]);
}
