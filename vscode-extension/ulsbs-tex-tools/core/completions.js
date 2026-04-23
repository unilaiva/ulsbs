// SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
// SPDX-License-Identifier: GPL-3.0-or-later

/**
 * Completion/suggestion provider for ULSBS environments.
 * @module
 */

const { getDocumentSelector, shouldProcessDocument } = require("./filetypes");
const { stripComment } = require("./parser");
const { tokenizeSongLine } = require("./songsyntax");

/**
 * Compute a lightweight context for completion filtering.
 *
 * Notes:
 * - This is intentionally line-based and local to the current document.
 * - It cannot reliably know whether this file is included from another file
 *   (so e.g. songs-environment nesting across file boundaries is best-effort).
 *
 * @param {import('vscode').TextDocument} document
 * @param {import('vscode').Position} position
 */
/**
 * Check whether a line prefix is currently inside a chord bracket ("\\[ ... ]").
 * @param {string} codePrefix Comment-stripped text from start of line to cursor.
 */
function isInsideChordBracket(codePrefix) {
  let open = false;

  for (let i = 0; i < codePrefix.length; i++) {
    // chord open token: \[
    if (codePrefix[i] === "\\" && codePrefix[i + 1] === "[") {
      open = true;
      i += 1;
      continue;
    }

    if (codePrefix[i] === "]") {
      // best-effort: ignore escaped \]
      const prev = codePrefix[i - 1];
      if (prev === "\\") {
        continue;
      }
      open = false;
    }
  }

  return open;
}

function computeCompletionContext(document, position) {
  let songDepth = 0;
  let songsEnvDepth = 0;
  let lilypondDepth = 0;
  let lilywrapDepth = 0;
  let verseDepth = 0;
  let repDepth = 0;

  let translationDepth = 0;
  let explanationDepth = 0;
  let passageDepth = 0;
  let feelerDepth = 0;
  let intersongDepth = 0;

  /** @type {Array<'verse'|'mnverse'>} */
  const verseStack = [];

  for (let line = 0; line <= position.line; line++) {
    let text = document.lineAt(line).text;
    if (line === position.line) {
      text = text.slice(0, position.character);
    }

    const code = stripComment(text);
    const tokens = tokenizeSongLine(code, line);

    for (const token of tokens) {
      if (token.type === "beginsong") {
        songDepth += 1;
      } else if (token.type === "endsong") {
        songDepth = Math.max(0, songDepth - 1);
      }

      if (token.type === "beginsongsenv") {
        songsEnvDepth += 1;
      } else if (token.type === "endsongsenv") {
        songsEnvDepth = Math.max(0, songsEnvDepth - 1);
      }

      if (token.type === "beginlilypond") {
        lilypondDepth += 1;
      } else if (token.type === "endlilypond") {
        lilypondDepth = Math.max(0, lilypondDepth - 1);
      }

      if (token.type === "beginlilywrap") {
        lilywrapDepth += 1;
      } else if (token.type === "endlilywrap") {
        lilywrapDepth = Math.max(0, lilywrapDepth - 1);
      }

      if (token.type === "beginverse") {
        verseDepth += 1;
        verseStack.push("verse");
      } else if (token.type === "mnbeginverse") {
        verseDepth += 1;
        verseStack.push("mnverse");
      } else if (token.type === "endverse") {
        verseDepth = Math.max(0, verseDepth - 1);
        // Best-effort stack unwind
        for (let i = verseStack.length - 1; i >= 0; i--) {
          if (verseStack[i] === "verse") {
            verseStack.splice(i, 1);
            break;
          }
        }
      } else if (token.type === "mnendverse") {
        verseDepth = Math.max(0, verseDepth - 1);
        for (let i = verseStack.length - 1; i >= 0; i--) {
          if (verseStack[i] === "mnverse") {
            verseStack.splice(i, 1);
            break;
          }
        }
      }

      if (token.type === "beginrep") {
        repDepth += 1;
      } else if (token.type === "endrep") {
        repDepth = Math.max(0, repDepth - 1);
      }

      if (token.type === "begintranslation") {
        translationDepth += 1;
      } else if (token.type === "endtranslation") {
        translationDepth = Math.max(0, translationDepth - 1);
      }

      if (token.type === "beginexplanation") {
        explanationDepth += 1;
      } else if (token.type === "endexplanation") {
        explanationDepth = Math.max(0, explanationDepth - 1);
      }

      if (token.type === "beginpassage") {
        passageDepth += 1;
      } else if (token.type === "endpassage") {
        passageDepth = Math.max(0, passageDepth - 1);
      }

      if (token.type === "beginfeeler") {
        feelerDepth += 1;
      } else if (token.type === "endfeeler") {
        feelerDepth = Math.max(0, feelerDepth - 1);
      }

      if (token.type === "beginintersong") {
        intersongDepth += 1;
      } else if (token.type === "endintersong") {
        intersongDepth = Math.max(0, intersongDepth - 1);
      }
    }
  }

  // Chord context is line-local (\[ ... ] does not normally span lines).
  const linePrefix = document
    .lineAt(position.line)
    .text.slice(0, position.character);
  const chordCodePrefix = stripComment(linePrefix);
  const inChordLine = isInsideChordBracket(chordCodePrefix);

  return {
    inSong: songDepth > 0,
    inSongsEnv: songsEnvDepth > 0,
    inLilypond: lilypondDepth > 0,
    inLilywrap: lilywrapDepth > 0,

    inVerse: verseDepth > 0,
    inRep: repDepth > 0,
    inTranslation: translationDepth > 0,
    inExplanation: explanationDepth > 0,
    inPassage: passageDepth > 0,
    inFeeler: feelerDepth > 0,
    inIntersong: intersongDepth > 0,

    inChordLine,
    currentVerseType: verseStack.length ? verseStack[verseStack.length - 1] : null
  };
}

/**
 * Determine whether we are completing an environment name inside \begin{... or \end{...
 * @param {string} linePrefix text from start of line to cursor
 */
function getEnvCompletionContext(linePrefix) {
  const beginMatch = linePrefix.match(/\\begin\{([A-Za-z]*)$/);
  if (beginMatch) {
    return {
      kind: "begin",
      typed: beginMatch[1] || "",
      replaceStart: linePrefix.length - (beginMatch[1] || "").length
    };
  }

  const endMatch = linePrefix.match(/\\end\{([A-Za-z]*)$/);
  if (endMatch) {
    return {
      kind: "end",
      typed: endMatch[1] || "",
      replaceStart: linePrefix.length - (endMatch[1] || "").length
    };
  }

  return null;
}

/**
 * Determine whether we are completing a control sequence name after a backslash.
 * @param {string} linePrefix
 */
function getMacroCompletionContext(linePrefix) {
  const match = linePrefix.match(/\\([A-Za-z0-9]*)$/);
  if (!match) {
    return null;
  }

  return {
    typed: match[1] || "",
    replaceStart: linePrefix.length - (match[1] || "").length
  };
}

/**
 * @param {import('vscode')} vscode
 * @param {string} title
 * @param {string} body
 * @param {string} code
 */
function makeCompletionDoc(vscode, title, body, code) {
  const md = new vscode.MarkdownString();
  md.appendMarkdown(`**${title}**\n\n`);
  md.appendMarkdown(`${body}\n\n`);
  md.appendCodeblock(code, "tex");
  md.isTrusted = false;
  return md;
}

/**
 * Register completion provider.
 * @param {import('vscode')} vscode
 * @param {import('vscode').ExtensionContext} context
 */
function registerCompletionProvider(vscode, context) {
  const provider = vscode.languages.registerCompletionItemProvider(
    getDocumentSelector(),
    {
      provideCompletionItems(document, position) {
        try {
          if (!shouldProcessDocument(vscode, document)) {
            return undefined;
          }

          const lineText = document.lineAt(position.line).text;
          const linePrefix = lineText.slice(0, position.character);

          const completionCtx = computeCompletionContext(document, position);

          // Chordline-specific completions (inside \[ ... ])
          if (completionCtx.inChordLine) {
            const macroCtx = getMacroCompletionContext(linePrefix);
            if (!macroCtx) {
              return undefined;
            }

            const nextChar = lineText[position.character] ?? "";
            const needsSpaceAfterBareMacro = nextChar !== "]" && nextChar !== "\\";

            /** @type {{name: string, argCount: number, title: string, doc: string}[]} */
            const chordMacros = [
              {
                name: "bm",
                argCount: 0,
                title: "Beat mark (ULSBS)",
                doc: "Beat mark that takes horizontal space."
              },
              {
                name: "bmc",
                argCount: 0,
                title: "Beat mark (ULSBS)",
                doc: "Beat mark that takes no horizontal space (can be stacked with chords and melody notes)."
              },
              {
                name: "bmadj",
                argCount: 1,
                title: "Beat mark, adjusted (ULSBS)",
                doc: "Beat mark that is adjusted horizontally and takes horizontal space."
              },
              {
                name: "bmcadj",
                argCount: 1,
                title: "Beat mark, adjusted (ULSBS)",
                doc: "Beat mark that is adjusted horizontally, but takes no horizontal space (can be stacked with chords and melody notes)"
              },

              { name: "mn", argCount: 1, title: "Melody note (ULSBS)", doc: "Melody note that takes horizontal space." },
              { name: "mnc", argCount: 1, title: "Melody note (ULSBS)", doc: "Melody note that does not take horizontal space (can be stacked with beat marks and chords)." },
              { name: "mncadj", argCount: 1, title: "Melody note, adjusted (ULSBS)", doc: "Horizontally adjusted melody note that does not take horizontal space (can be stacked with beat marks and chords)." },
              { name: "mnd", argCount: 1, title: "Melody note, low (ULSBS)", doc: "Melody note that takes horizontal space. Placed below normal melody note position." },

              { name: "mncii", argCount: 2, title: "2 melody notes (ULSBS)", doc: "2 melody notes that do not take horizontal space (can be stacked with beat marks and chords)." },
              { name: "mnciii", argCount: 3, title: "3 melody notes (ULSBS)", doc: "3 melody notes that do not take horizontal space (can be stacked with beat marks and chords)." },
              { name: "mnciv", argCount: 4, title: "4 melody notes (ULSBS)", doc: "4 melody notes that do not take horizontal space (can be stacked with beat marks and chords)." },
              { name: "mncv", argCount: 5, title: "5 melody notes (ULSBS)", doc: "5 melody notes that do not take horizontal space (can be stacked with beat marks and chords)." },
              { name: "mncvi", argCount: 6, title: "6 melody notes (ULSBS)", doc: "6 melody notes that do not take horizontal space (can be stacked with beat marks and chords)." },

              { name: "ma", argCount: 1, title: "Alt. melody note (ULSBS)", doc: "Alternatively colored melody note that takes horizontal space." },
              { name: "mac", argCount: 1, title: "Alt. melody note (ULSBS)", doc: "Alternatively colored melody note that does not take horizontal space (can be stacked with beat marks and chords)." },
              { name: "mau", argCount: 1, title: "Alt. melody note (ULSBS)", doc: "Alternatively colored melody note that takes horizontal space. Placed above normal melody note position." },
              { name: "mauc", argCount: 1, title: "Alt. melody note (ULSBS)", doc: "Alternatively colored melody note that does not take horizontal space (can be stacked with beat marks and chords). Placed above normal melody note line." },
              { name: "mad", argCount: 1, title: "Alt. melody note (ULSBS)", doc: "Alternatively colored melody note that takes horizontal space. Placed below normal melody note position." },

              { name: "mauii", argCount: 2, title: "Alt. + normal melody note (ULSBS)", doc: "Alternatively colored melody note placed high + normal melody note stacked; together they take horizontal space." },
              { name: "mauiic", argCount: 2, title: "Alt. + normal melody note (ULSBS)", doc: "Alternatively colored melody note placed high + normal melody note stacked; they don't take horizontal space (can be stacked with beat marks and chords)." },
              { name: "madii", argCount: 2, title: "Alt. + normal melody note (ULSBS)", doc: "Alternatively colored melody note placed low + normal melody note stacked; together they take horizontal space." },
              { name: "mncii", argCount: 2, title: "Alt. + normal melody note (ULSBS)", doc: "Alternatively colored melody note placed low + normal melody note stacked; they don't take horizontal space (can be stacked with beat marks and chords)." },
            ];

            const typed = macroCtx.typed.toLowerCase();

            const startPos = new vscode.Position(position.line, macroCtx.replaceStart);
            const replaceRange = new vscode.Range(startPos, position);

            return chordMacros
              .filter((m) => m.name.toLowerCase().startsWith(typed))
              .map((m) => {
                const item = new vscode.CompletionItem(
                  m.name,
                  vscode.CompletionItemKind.Snippet
                );

                item.detail = `${m.title} (${m.argCount} args)`;
                item.sortText = `ulsbs_chord_${m.name}`;
                item.range = replaceRange;

                const parts = [`\\${m.name}`];

                if (m.argCount === 0) {
                  item.insertText =
                    m.name +
                    (needsSpaceAfterBareMacro && (m.name === "bm" || m.name === "bmc")
                      ? " "
                      : "");

                  item.documentation = makeCompletionDoc(
                    vscode,
                    m.title,
                    m.doc,
                    parts[0]
                  );

                  return item;
                }

                for (let i = 1; i <= m.argCount; i++) {
                  parts.push(`{$${i}}`);
                }

                item.insertText = new vscode.SnippetString([m.name, ...parts.slice(1)].join(""));
                item.documentation = makeCompletionDoc(
                  vscode,
                  m.title,
                  m.doc,
                  parts.join("")
                );

                return item;
              });
          }

          // (1) \begin{...} / \end{...} environment name completion
          const envCtx = getEnvCompletionContext(linePrefix);
          if (envCtx) {
            /**
             * @type {{
             *   name: string,
             *   hasLang?: boolean,
             *   allowBegin: (ctx: any) => boolean,
             *   allowEnd: (ctx: any) => boolean,
             *   beginSnippet?: (name: string) => string
             * }[]}
             */
            const envs = [
              {
                name: "explanation",
                title: "Explanation environment (ULSBS)",
                doc: "Explanation environment (optional language code).",
                hasLang: true,
                allowBegin: () => true,
                allowEnd: (ctx) => ctx.inExplanation
              },
              {
                name: "passage",
                title: "Passage environment (ULSBS)",
                doc: "Passage environment (optional language code).",
                hasLang: true,
                allowBegin: () => true,
                allowEnd: (ctx) => ctx.inPassage
              },
              {
                name: "feeler",
                title: "Feeler environment (ULSBS)",
                doc: "Feeler environment.",
                allowBegin: () => true,
                allowEnd: (ctx) => ctx.inFeeler
              },
              {
                name: "intersong",
                title: "Intersong environment (ULSBS)",
                doc: "Intersong blocks must be between songs (not inside a song) within songs environment.",
                // Begin only between songs, and do not nest intersong blocks.
                allowBegin: (ctx) => !ctx.inSong && !ctx.inIntersong,
                allowEnd: (ctx) => ctx.inIntersong
              },
              {
                name: "songs",
                title: "Songs environment (ULSBS)",
                doc: "Songs environment (best-effort local-file detection).",
                // Best-effort, local-file only.
                allowBegin: (ctx) => !ctx.inSong && !ctx.inSongsEnv,
                allowEnd: (ctx) => ctx.inSongsEnv
              },
              {
                name: "translation",
                title: "Translation environment (ULSBS)",
                doc: "Translation environment (optional language code).",
                hasLang: true,
                allowBegin: () => true,
                allowEnd: (ctx) => ctx.inTranslation
              },
              {
                name: "lilywrap",
                title: "Lilypond wrapper environment (ULSBS)",
                doc: "Lilywrap wrapper environment. Put lilypond environment within this.",
                // Lilywrap can appear anywhere but not within lilypond.
                allowBegin: (ctx) => !ctx.inLilypond,
                // Prefer closing lilypond before lilywrap.
                allowEnd: (ctx) => ctx.inLilywrap && !ctx.inLilypond
              },
              {
                name: "lilypond",
                title: "Lilypond environment (ULSBS)",
                doc: "Lilypond environment. Put this inside lilywrap environment.",
                allowBegin: (ctx) => ctx.inLilywrap && !ctx.inLilypond,
                allowEnd: (ctx) => ctx.inLilypond
              }
            ];

            const allowed = envs.filter((e) =>
              envCtx.kind === "begin" ? e.allowBegin(completionCtx) : e.allowEnd(completionCtx)
            );

            const startPos = new vscode.Position(position.line, envCtx.replaceStart);
            const replaceRange = new vscode.Range(startPos, position);

            return allowed
              .filter((e) => e.name.toLowerCase().startsWith(envCtx.typed.toLowerCase()))
              .map((e) => {
                const item = new vscode.CompletionItem(
                  e.name,
                  vscode.CompletionItemKind.Snippet
                );

                item.detail = e.title || "ULSBS environment";
                item.sortText = `ulsbs_env_${e.name}`;
                item.range = replaceRange;

                if (envCtx.kind === "begin") {
                  const langSnippet = e.hasLang ? "[$1]" : "";
                  const defaultSnippet = `${e.name}}${langSnippet}\n$0\n\\end{${e.name}}`;
                  const snippetText = e.beginSnippet ? e.beginSnippet(e.name) : defaultSnippet;
                  item.insertText = new vscode.SnippetString(snippetText);

                  const code = `\\begin{${e.name}}${langSnippet}\n...\n\\end{${e.name}}`;
                  item.documentation = makeCompletionDoc(
                    vscode,
                    e.title || "ULSBS environment",
                    (e.doc || "") + "\n\nSuggested here because this looks like a valid location for `\\begin{...}`.",
                    code
                  );
                } else {
                  item.insertText = `${e.name}}`;

                  const code = `\\end{${e.name}}`;
                  item.documentation = makeCompletionDoc(
                    vscode,
                    e.title || "ULSBS environment",
                    (e.doc || "") + "\n\nSuggested here because you appear to be inside this environment.",
                    code
                  );
                }

                return item;
              });
          }

          // (2) Control-sequence snippets (\beginsong, \beginverse, \beginrep) with context filters
          const macroCtx = getMacroCompletionContext(linePrefix);
          if (!macroCtx) {
            return undefined;
          }

          /** @type {{name:string, snippet: string, isAllowed: (ctx:any)=>boolean, title: string, doc: string}[]} */
          const snippetMacros = [
            {
              name: "beginsong",
              title: "Song (ULSBS)",
              doc: "Insert a `\\beginsong{...}` ... `\\endsong` block.",
              snippet: "beginsong{${1:title}}\n\t$0\n\\endsong",
              isAllowed: (ctx) => !ctx.inSong
            },
            {
              name: "beginverse",
              title: "Verse (ULSBS)",
              doc: "Insert a `\\beginverse` ... `\\endverse` block (only inside a song).",
              snippet: "beginverse\n\t$0\n\\endverse",
              isAllowed: (ctx) => ctx.inSong && !ctx.inVerse
            },
            {
              name: "mnbeginverse",
              title: "Verse (MN: with space for melody note hints, ULSBS)",
              doc: "Insert a `\\mnbeginverse` ... `\\mnendverse` block (only inside a song).",
              snippet: "mnbeginverse\n\t$0\n\\mnendverse",
              isAllowed: (ctx) => ctx.inSong && !ctx.inVerse
            },
            {
              name: "beginrep",
              title: "Repetition (ULSBS)",
              doc: "Insert a `\\beginrep` ... `\\endrep` block (only inside a verse or translation).",
              snippet: "beginrep\n\t$0\n\\endrep",
              isAllowed: (ctx) => ctx.inVerse || ctx.inTranslation
            }
          ];

          /** @type {{name:string, insert: string, isAllowed: (ctx:any)=>boolean, title: string, doc: string}[]} */
          const closingMacros = [
            {
              name: "endverse",
              insert: "endverse",
              title: "ULSBS macro",
              doc: "Close a `\\beginverse` block.",
              isAllowed: (ctx) =>
                ctx.inVerse &&
                (ctx.currentVerseType === "verse" || ctx.currentVerseType == null)
            },
            {
              name: "mnendverse",
              insert: "mnendverse",
              title: "ULSBS macro",
              doc: "Close a `\\mnbeginverse` block.",
              isAllowed: (ctx) =>
                ctx.inVerse &&
                (ctx.currentVerseType === "mnverse" || ctx.currentVerseType == null)
            },
            {
              name: "endrep",
              insert: "endrep",
              title: "ULSBS macro",
              doc: "Close a `\\beginrep` block.",
              isAllowed: (ctx) => ctx.inRep
            },
            {
              name: "endtranslation",
              insert: "endtranslation",
              title: "ULSBS macro",
              doc: "Close a translation block (e.g. `\\begin{translation}` / `\\begintranslation`).",
              isAllowed: (ctx) => ctx.inTranslation
            },
            {
              name: "endsong",
              insert: "endsong",
              title: "ULSBS macro",
              doc: "Close a `\\beginsong` block.",
              isAllowed: (ctx) => ctx.inSong
            }
          ];

          const startPos = new vscode.Position(position.line, macroCtx.replaceStart);
          const replaceRange = new vscode.Range(startPos, position);

          /** @type {import('vscode').CompletionItem[]} */
          const items = [];

          for (const m of snippetMacros) {
            if (!m.isAllowed(completionCtx)) continue;
            if (!m.name.toLowerCase().startsWith(macroCtx.typed.toLowerCase())) continue;

            const item = new vscode.CompletionItem(
              {
                label: m.name,
                description: "block"
              },
              vscode.CompletionItemKind.Snippet
            );

            item.detail = m.title;
            // Make block snippets sort before plain macro completions.
            item.sortText = `!ulsbs_macro_block_${m.name}`;
            item.preselect = true;
            item.filterText = m.name;
            item.range = replaceRange;
            item.insertText = new vscode.SnippetString(m.snippet);

            const md = new vscode.MarkdownString();
            md.appendMarkdown(`**${m.title}**\n\n`);
            md.appendMarkdown(`${m.doc}\n\n`);
            md.appendCodeblock(`\\${m.name}`, "tex");
            item.documentation = md;

            items.push(item);
          }

          for (const m of closingMacros) {
            if (!m.isAllowed(completionCtx)) continue;
            if (!m.name.toLowerCase().startsWith(macroCtx.typed.toLowerCase())) continue;

            const item = new vscode.CompletionItem(
              {
                label: m.name,
                description: "macro"
              },
              vscode.CompletionItemKind.Keyword
            );

            item.detail = m.title;
            item.sortText = `~ulsbs_macro_${m.name}`;
            item.filterText = m.name;
            item.range = replaceRange;
            item.insertText = m.insert;
            item.documentation = makeCompletionDoc(
              vscode,
              m.title,
              m.doc,
              `\\${m.name}`
            );
            items.push(item);
          }

          return items.length ? items : undefined;
        } catch (error) {
          console.error("ULSBS completion provider failed:", error);
          return undefined;
        }
      }
    },
    "{",
    "\\"
  );

  context.subscriptions.push(provider);
  return provider;
}

module.exports = {
  registerCompletionProvider
};
