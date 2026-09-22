# ULSBS TeX Tools (VS Code Extension)

This extension provides editing support for **ULSBS songbook LaTeX files** in
Visual Studio Code.

It is meant to be used with the **ULSBS (Unilaiva Songbook System)** package:

- ULSBS repository: <https://github.com/unilaiva/ulsbs>
- ULSBS documentation: <https://github.com/unilaiva/ulsbs/blob/main/README.md>
- Extension changelog: [CHANGELOG.md](CHANGELOG.md)

The extension is useful in songbook workspaces that contain `ulsbs-config.toml`
and either:

- a vendored `ulsbs/` directory, or
- a wrapper script such as `ulsbs-compile`

## Features

The extension adds ULSBS-aware editing support for LaTeX files, including:

- snippets for common ULSBS song structures
- completion suggestions for common ULSBS environments (including `explanation`, `passage`, `feeler`, `intersong`)
- melody-block pitch and marker completions inside `\[ ... ]`
- a LaTeX grammar injection that scopes same-line chord annotations as `meta.ulsbs.chord.latex`
- scoped `\melodyPrimaryPosition{normal|low}`, `\melodySecondaryPosition{above|below|same}`, and `\melodyStyleMapping{normal|swapped}` completions
- indentation and folding for song environments
- Outline / breadcrumb structure for songs and related blocks
- parsing and warnings for common structural issues
- a ULSBS sidebar view for discovered songbooks in the workspace
- commands for compiling songbooks with `ulsbs-compile`

It understands ULSBS-specific structures such as:

```tex
\beginsong ... \endsong
\beginverse ... \endverse
\mnbeginverse ... \mnendverse
\beginrep ... \endrep
\begin{songs} ... \end{songs}
\begin{translation} ... \end{translation}
\begin{lilypond} ... \end{lilypond}
\begin{explanation} ... \end{explanation}
\begin{passage} ... \end{passage}
\begin{feeler} ... \end{feeler}
\begin{intersong} ... \end{intersong}
\[ ... ]
```

### Melody blocks

Inside a chord definition, write melody content as:

```tex
\[<[!] PRIMARY-NOTES[;SECONDARY-NOTES][ @ horizontal-offset]>Chord]
\[^<[!] PRIMARY-NOTES[;SECONDARY-NOTES][ @ horizontal-offset]>Chord]
```

For example:

```tex
\[<C>Am]Love
\[<C D E;E F G>F]Two melodies
\[^<*A/_C;EF_G@.2em>Am]Marked phrase
\[<!C>]
\[<!*>]
\[<!C@1em>Am]
```

The melody block must begin immediately after `\[` or after one leading `^`; it is not recognized elsewhere in the annotation. The chord, if present, follows the closing `>`. Use uppercase note names so transposition works. Spaces between items are optional: pitches are `A` through `G` with an optional `#` or `&`; `_` is an empty slot, `/` is a circled unpitched marker, and `*` is a beat mark. Beat marks are valid only inside the angle brackets. The optional leading `!` renders melody layers normally but gives them zero advance and disables that annotation's minimum whitespace; a chord after `>` keeps its natural width. The optional secondary sequence follows `;`; `@` adjusts the whole block. Configure the lanes with `\melodyPrimaryPosition{normal|low}` (default: `normal`) and `\melodySecondaryPosition{above|below|same}`. With a normal primary, secondary `above`, `same`, and `below` use the high, normal, and low lanes. With a low primary, they use the normal, low, and below-low lanes; below-low may intentionally overlap lyrics. Configure visual styles independently with `\melodyStyleMapping{normal|swapped}`. `same` overlays the secondary melody on the primary lane and is useful when migrating baseline alternate-only notes.

Only one melody block is supported in an annotation. To combine blocks at the same anchor, use adjacent annotations with a zero-advance block first, for example `\[<!C>]\[<D>Am]`.

A leading caret, as in `\[^<C>Am]`, excludes the complete annotation from chord memorization. A bare caret in lyric text replays the next full saved annotation.

The opening and closing melody delimiters, `<` and `>`, and the leading `!` modifier have a distinct subtle editor decoration. When a valid opening `<` has no closing `>` before the annotation's `]`, the opening delimiter is marked as incomplete; TeX remains responsible for reporting the malformed melody block when compiled.

## Installation

The extension is currently shipped as **source** inside the ULSBS repository.
To install it locally, build a `.vsix` package.

Requirement: `npm`

### 1. Install tooling

```sh
cd ulsbs/vscode-extension/ulsbs-tex-tools
npm ci
```

### 2. Build the extension package

```sh
npm run package
```

This creates a file like:

- `ulsbs-tex-tools-x.y.z.vsix`

### 3. Install into VS Code

From command line:

```sh
code --install-extension ulsbs-tex-tools-x.y.z.vsix
```

Or from within VS Code:

- **Extensions -> ... -> Install from VSIX...**

Then reload VS Code.

## Usage

In a detected ULSBS workspace, the extension can:

- discover songbooks from the workspace
- show them in the **ULSBS** activity-bar view
- run `ulsbs-compile` commands from VS Code
- help navigate song structures in the editor outline

By default, the extension auto-enables itself only when it detects a ULSBS
workspace.

Common detection markers include:

- `ulsbs-config.toml`
- `ulsbs/pyproject.toml`
- `ulsbs/ulsbs-compile`

## Configuration

Available settings include:

- `ulsbsTexTools.enable`
  - `auto`, `on`, or `off`
- `ulsbsTexTools.compileCommand`
  - path to the compile script, relative to the workspace root
  - default: `ulsbs/ulsbs-compile`
- `ulsbsTexTools.askProfileOnCompile`
  - ask for a ULSBS profile when compiling
- `ulsbsTexTools.defaultProfile`
  - fallback profile if prompting is disabled
- `ulsbsTexTools.autoRefreshDiagnostics`
  - refresh diagnostics automatically on edits and saves
- `ulsbsTexTools.fileGlob`, `ulsbsTexTools.excludeGlob`
  - control which files are scanned

If your project uses a root-level wrapper script instead of
`ulsbs/ulsbs-compile`, change `ulsbsTexTools.compileCommand` accordingly, for
example to `./ulsbs-compile`.

## Development

To test the extension during development:

1. Open this folder in VS Code:
   - `ulsbs/vscode-extension/ulsbs-tex-tools`
2. Press **F5**

This launches a **VS Code Extension Development Host** with the extension
loaded.

Quick cheat sheet:

- snippets (static templates): `snippets/latex.json`
- injected LaTeX grammar: `syntaxes/ulsbs-chord.injection.tmLanguage.json`
- grammar fixture check: `npm run test:grammar`
- completions (context-aware suggestions + some block snippets): `core/completions.js`
- indentation / folding: `language-configuration.json`
- tokenizer for structural macros/environments: `core/songsyntax.js`
- parser (structure + issue production): `core/parser.js`
- issue helpers (VS Code-independent): `core/issues.js`
- diagnostics adapter (issues -> VS Code diagnostics): `core/diagnostics.js`
- symbols / outline provider: `core/symbols.js`
- verse / lilypond region helpers (decorations): `core/regions.js`
- workspace detection: `core/workspace.js`
- workspace scanning / songbook index: `core/songbooks.js`
- sidebar tree view: `core/tree.js`
- compile commands: `core/compile.js`
- chord decorations: `core/chords.js`
- measure bar decorations: `core/measures.js`
- shared active-editor update wiring: `core/editor-updater.js`
- supported file types / exclusions: `core/filetypes.js`
- extension entry point: `extension.js`
- settings: `package.json`, `core/config.js`
- command UI helpers: `core/ui.js`
- new songbook template: `assets/songbook-template_A5.tex`

### Architecture notes

- If you add a new ULSBS block/macro:
  1. Add tokens in `core/songsyntax.js`.
  2. Add structure + misuse warnings in `core/parser.js`.
  3. Diagnostics will pick up warnings automatically via `core/diagnostics.js`.
  4. Add outline mapping in `core/symbols.js` if you want it in the Outline view.
  5. Add context-aware suggestions in `core/completions.js` (and/or a static snippet in `snippets/latex.json`).

## Browser support

In addition to the desktop version, the extension includes a web build for:

- `vscode.dev`
- `github.dev`
- Codespaces

## License

GNU General Public License version 3 or later (GPL 3.0+)
