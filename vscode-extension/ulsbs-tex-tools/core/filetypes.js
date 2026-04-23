// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * File-type helpers and document filtering for ULSBS TeX tools.
 * Centralizes "should we process this document/URI" checks.
 * @module
 */

/** @returns {string[]} */
function getSupportedExtensions() {
  return [".tex", ".lytex", ".latex", ".lylatex"];
}

/**
 * @param {string} path
 * @returns {boolean}
 */
function hasSupportedExtension(path) {
  const lower = String(path).toLowerCase();
  return getSupportedExtensions().some((ext) => lower.endsWith(ext));
}

/**
 * Document selector used by providers.
 * @returns {import('vscode').DocumentSelector}
 */
function getDocumentSelector() {
  return [
    { language: "latex" },
    ...getSupportedExtensions().map((ext) => ({
      scheme: "file",
      language: "latex",
      pattern: `**/*${ext}`
    }))
  ];
}

/**
 * @param {import('vscode').TextDocument|import('vscode').Uri|{uri?: import('vscode').Uri}|null|undefined} documentOrUri
 * @returns {boolean}
 */
function isSupportedDocument(documentOrUri) {
  if (!documentOrUri) {
    return false;
  }

  const path =
    documentOrUri.uri?.path ??
    documentOrUri.path ??
    documentOrUri.fsPath ??
    "";

  return hasSupportedExtension(path);
}

/**
 * Normalize `excludeGlob` setting to a string array.
 * @param {string|string[]|undefined|null} excludeGlob
 * @returns {string[]}
 */
function normalizeExcludeGlobs(excludeGlob) {
  if (Array.isArray(excludeGlob)) {
    return excludeGlob.filter(
      (item) => typeof item === "string" && item.trim() !== ""
    );
  }
  if (typeof excludeGlob === "string" && excludeGlob.trim() !== "") {
    return [excludeGlob];
  }
  return [];
}

/** @param {string} path */
function normalizePath(path) {
  return String(path || "")
    .replace(/\\/g, "/")
    .replace(/\/+/g, "/")
    .toLowerCase();
}

/**
 * Heuristic conversion from a glob-ish pattern to a substring needle.
 * (This intentionally avoids a full glob implementation.)
 * @param {string} pattern
 */
function globLikePatternToNeedle(pattern) {
  let needle = normalizePath(pattern);

  needle = needle.replace(/^\{|\}$/g, "");
  needle = needle.replace(/\*\*/g, "");
  needle = needle.replace(/\*/g, "");
  needle = needle.replace(/\/+/g, "/");

  if (needle.endsWith("/")) {
    needle = needle.slice(0, -1);
  }
  if (needle.startsWith("/")) {
    needle = needle.slice(1);
  }

  return needle;
}

/** @param {string} path @param {string} needle */
function pathContainsSegment(path, needle) {
  if (!needle) {
    return false;
  }

  if (path === needle) {
    return true;
  }

  return (
    path.includes(`/${needle}/`) ||
    path.endsWith(`/${needle}`) ||
    path.startsWith(`${needle}/`)
  );
}

/**
 * Check whether a URI matches the configured exclude globs.
 * @param {import('vscode')} vscode
 * @param {import('vscode').Uri} uri
 * @param {string|string[]|undefined|null} excludeGlobs
 */
function isExcludedUri(vscode, uri, excludeGlobs) {
  if (!uri) {
    return false;
  }

  const globs = normalizeExcludeGlobs(excludeGlobs);
  if (!globs.length) {
    return false;
  }

  const relativePath = normalizePath(vscode.workspace.asRelativePath(uri, false));
  const fullPath = normalizePath(uri.fsPath || uri.path || "");

  return globs.some((pattern) => {
    const needle = globLikePatternToNeedle(pattern);
    if (!needle) {
      return false;
    }

    return (
      pathContainsSegment(relativePath, needle) ||
      pathContainsSegment(fullPath, needle)
    );
  });
}

/**
 * Unified filter used by most providers/decoration updaters.
 * @param {import('vscode')} vscode
 * @param {import('vscode').TextDocument} document
 * @param {{excludeGlob?: string|string[]} | undefined | null} [settings]
 */
function shouldProcessDocument(vscode, document, settings) {
  if (!isSupportedDocument(document)) {
    return false;
  }

  const excludeGlob =
    settings?.excludeGlob ??
    vscode.workspace
      .getConfiguration("ulsbsTexTools")
      .get("excludeGlob", []);

  return !isExcludedUri(vscode, document.uri, excludeGlob);
}

module.exports = {
  getSupportedExtensions,
  getDocumentSelector,
  isSupportedDocument,
  hasSupportedExtension,
  normalizeExcludeGlobs,
  isExcludedUri,
  shouldProcessDocument
};
