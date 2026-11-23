# ULSBS TeX Tools for VS Code

Editing and build shortcuts for songbooks written with
[ULSBS](https://github.com/unilaiva/ulsbs). The extension helps you navigate large
song collections, insert ULSBS markup, and compile the books that use the file
you are editing.

- Navigate songs and included files through the **Songbooks** sidebar and editor outline.
- Insert chord, melody, verse, translation, and score markup with snippets and completions.
- See structural diagnostics, folding, and chord/measure/melody decorations while editing.
- Compile one book, all discovered books, or the books affected by the active file.
- Create an A5 main document from the bundled songbook template.

The extension does **not** install the ULSBS engine, LaTeX, or LilyPond. To create
your first project or set up compilation, follow the
[ULSBS README](https://github.com/unilaiva/ulsbs/blob/main/README.md). For song
syntax and book customization, use
[Writing Songbooks](https://github.com/unilaiva/ulsbs/blob/main/WRITING_SONGBOOKS.md).

## Installation

The extension is shipped as source in the ULSBS repository. Build a `.vsix`
package and install it locally. You need VS Code 1.112.0 or newer and a current
Node.js LTS release with npm to build the package. Node.js is not needed just
to use an already-built VSIX.

1. From a songbook project containing the `ulsbs/` submodule, open a terminal and run:

```sh
cd ulsbs/vscode-extension/ulsbs-tex-tools
npm ci
npm run package
```

If you opened the ULSBS engine checkout itself, the directory is instead
`vscode-extension/ulsbs-tex-tools`. The package command builds the web bundle
and creates `ulsbs-tex-tools-<version>.vsix` in that directory.

2. Install the generated file using **Extensions > ... > Install from VSIX...**,
   or run this command from the directory containing it:

```sh
code --install-extension ulsbs-tex-tools-<version>.vsix
```

Replace `<version>` with the actual version in the generated filename. Reload
VS Code if prompted. To update from a newer checkout, repeat the build and
installation steps.

## Getting started

1. Open your **songbook project root** in VS Code, not just an individual song
   file or the engine subdirectory. The recommended layout has
   `ulsbs-config.toml`, main `.tex` documents, and `ulsbs/` in that folder.
2. Open a `.tex` song file and check that its language mode is **LaTeX**.
3. Select **ULSBS** in the Activity Bar to open the **Songbooks** view. Expand a
   book to navigate its included files and songs; selecting an entry opens its source.
4. Use the command palette and search for `ULSBS` to see the available actions.

With `ulsbsTexTools.enable` set to `auto` (the default), any of these workspace
markers enables ULSBS-specific features:

- `ulsbs-config.toml`
- `ulsbs/pyproject.toml`
- `ulsbs/ulsbs-compile`

These are alternative detection markers, not a requirement to have all three.
A compiler script is needed for compilation, but not for editing. You can set
`ulsbsTexTools.enable` to `on` to enable the features without automatic detection.

### Create a main document

Run **ULSBS: Create new songbook** from the command palette or the Songbooks
toolbar. It prompts for a name and creates `<name>_A5.tex` from the bundled
template, then opens the file. It does not overwrite an existing file.

This action requires the vendored engine at `ulsbs/` and uses the **first
workspace folder** in a multi-root workspace. It creates the main document,
not a complete project: add its filename to `songbooks` in `ulsbs-config.toml`
if you want the normal CLI build to select it. A wrapper-only or separately
installed engine can still compile existing documents, but does not satisfy
this command's engine check. The template declares `variants={default}`;
add companion names to that list to make them available to your build profiles.

## Compiling songbooks

Compilation runs the configured ULSBS script in the **ULSBS Build** terminal.
The script needs the same Python/container or host-toolchain setup as a
command-line build. The extension is a shortcut to that build, not a replacement
for it.

| Command | What it builds |
|---|---|
| **ULSBS: Compile current context** | Every discovered main book that includes the active file, or the active main book itself |
| **ULSBS: Compile all songbooks** | All main documents discovered in the relevant workspace folder |
| **ULSBS: Compile this songbook** | The selected book in the Songbooks view |
| **ULSBS: Compile this songbook with profile** | The selected book, with explicit profile selection |
| **ULSBS: Choose compile profile** | Select the active build profile |
| **ULSBS: Open configuration (ulsbs-config.toml)** | Open the project configuration |
| **ULSBS: Refresh workspace index** | Rescan documents and their include relationships |

The Songbooks view has build actions in its toolbar and each book's context
menu. It also shows the active profile and books affected by the current file.
If a song collection belongs to several books, compiling its current context
can start several book builds.

Build commands reuse the active profile, initially `default`. Use **Choose
compile profile** or **Compile this songbook with profile** to select another.
Names come from `[profiles.NAME]` headings in the root configuration;
`default` is always available. Selection normally opens a picker. When
`ulsbsTexTools.askProfileOnCompile` is `false`, those profile-selection actions
apply `ulsbsTexTools.defaultProfile` without opening the picker.

In a multi-root workspace, **Compile all songbooks** uses the active file's
workspace folder, or the first folder when there is no active file.

The extension passes the discovered main-document paths explicitly to the
compiler. In particular, **Compile all songbooks** means all discovered mains,
not only those listed in the selected config profile's `songbooks` array.
Use the CLI directly when you want the configuration alone to select books,
or when you need flags such as `--quick`.

Variant and edition selection belongs in your compiler profile, not the editor
settings. For example, use `variants = ["default", "lyric"]` in a profile after
declaring both variants in the main source. The extension passes the profile and
main filenames to the compiler; it does not choose variants independently.

## Editing features

The extension understands `\beginsong` / `\endsong`, all canonical
`\beginverse` modifier combinations, repeat blocks, chord annotations, and
environments such as `translation`, `explanation`, `passage`, `feeler`,
`intersong`, `lilywrap`, and `lilypond`.
Book assembly uses `\begin{ulSongs}{...}` / `\end{ulSongs}`; completions,
structural diagnostics, folding and indentation recognize this current name.
The outline also recognizes `\ulSongChapter` and `\ulSongSection`, including
starred forms and optional short titles.

It provides outline entries, folding and indentation, structural warnings in
VS Code's diagnostics, and context-aware completions. These checks are not a
full TeX or LilyPond validator; the compiler remains authoritative.

### Snippets and completions

In a LaTeX document, type a prefix and select the suggestion. If it does not
appear automatically, invoke **Trigger Suggest** (usually Ctrl+Space).
Use Tab to move between a snippet's editable fields.

| Prefix | Inserts |
|---|---|
| `\[` | A chord annotation |
| `melodychord` | A chord with a leading melody block |
| `melodychordzero` | A zero-advance melody block and chord |
| `melodychordskip` | An annotation excluded from chord memorization |
| `translation`, `explanation`, `feeler` | The corresponding text environment |
| `passage`, `passage*` | Normal or alternate-style passage with an optional language code and a required title argument |
| `lilywrap` | Wrapped LilyPond environment delimiters |
| `begin{ulSongs}` | Book-level song collection with its required index-list argument |
| `ulMelodyPrimaryPosition`, `ulMelodySecondaryPosition`, `ulMelodyStyleMapping` | Scoped melody-placement/style commands |
| `ulLaneAwareAnnotationSpacing` | Set `false` to opt out of default lane-aware annotation spacing |
| `ulSpace`, `ulSpace*` | Insert a breakable lyric space, or center a continuation hyphen within a word; both accept an optional multiplier |
| `ulTagFile` | Preamble-only tag filename setter with its required argument |
| `ulNewIndex`, `ulNewAuthorIndex`, `ulNewTagIndex` | Title/author/tag index declaration with identifier and filename-stem arguments |
| `ulIndexTagFont` | Tag-index heading font customization |
| `variants` | Literal `variants={default,lyric,charango,bassclef}` class option |
| `ulLocalShow` | Scoped visibility request with all 21 canonical feature choices and `true`/`false` |
| `ulIfVariant` | Immutable variant-identity test with yes/no branches |
| `ulIfMusical` | Effective musical-visibility test with yes/no branches |
| `ulVerseBaseline`, `ulVerseSeparation` | Natural/stretch/shrink spacing scalars, applied after font setup |
| `ulVerseMinimumGap` | Minimum lyric-line clearance as a dimension |
| `ulVerseSpacingScale` | Read a stored spacing scalar for relative calculations |

Place `variants={default,lyric,charango,bassclef}` literally in the main document's
`\documentclass[...]` options and remove unwanted companion variants, keeping
`default`. Omitting the option declares only `default`, not an implicit lyric
variant. Availability does not select the current variant; choose it through
the compiler profile.

`\ulLocalShow{translation}{false}` changes a local request until its enclosing
TeX group ends; `true` cannot override a book-wide prohibition. Its `notes` key
means inline pitches and `scores` means whole scores. `\ulIfVariant{name}{yes}{no}`
tests identity independently of visibility. `\ulIfMusical{yes}{no}` tests effective
chords OR inline pitches OR whole scores at the call site, excluding beats and
measure bars; it does not test whether the song actually contains music.

Snippets provide a starting point, not a complete song or score. Fill in any
required arguments and music using the writing guide's examples.
The `ulSongs` snippet and template suggest `titleidx,authidx,tagidx`, routing title,
author and tag index records. Leave the required braces empty to collect none.
Likewise, keep `{}` for an untitled `passage` rather than deleting its title argument.
The `passage*` prefix inserts `\begin{passage}*[LANG]{Title}` with the same
`\end{passage}` closing command.

Verse clearance is automatic. Baseline and separation snippets use nonnegative
scalars multiplying the lyric font's capital-`A` height; their sample values are
not defaults. The baseline is the total nominal distance, not an addition to the
font size. Apply these
setters after font customization and keep grouped overrides around the verses
they affect. Actual ink may require extra clearance.

The extension targets the current ULSBS API and does not migrate sources.
Review existing books with
[`ulsbs-migrate-syntax-v2`](https://github.com/unilaiva/ulsbs/blob/main/README.md#ulsbs-migrate-syntax-v2);
older melody syntax needs v1 first, then v2.

### Chords and melody hints

Same-line ULSBS `\[ ... ]` annotations receive chord-aware syntax highlighting
rather than ordinary display-math highlighting. Melody blocks are recognized
only immediately after `\[` or one leading `^`:

```tex
\[Am]lyrics
\[<C>Am]Love
\[<C D E;E F G>F]Two melodies
\[^<*A/_C;EF_G@.2em>Am]Marked phrase
\[<!C>]
\[<!*>]
\[<!C@1em>Am]
```

Pitches use uppercase A--G with optional `#` or `&`. `_` is an empty slot,
`/` an unpitched circled marker, and `*` a beat mark inside a melody block.
The secondary sequence follows `;`, `@` adds an offset, and a leading `!` gives
the melody zero advance. A leading caret excludes the annotation from chord
memorization; bare carets in lyrics replay saved annotations.

Only one melody block is supported per annotation. To share an anchor between
two blocks, use a zero-advance block first: `\[<!C>]\[<D>Am]`.
The editor subtly decorates `<`, `>`, and the leading `!`; an unclosed melody
block marks the opening delimiter as incomplete. Compilation reports malformed
syntax independently.

For all placement, spacing, replay, and visibility rules, see
[Melody hints and beat marks](https://github.com/unilaiva/ulsbs/blob/main/WRITING_SONGBOOKS.md#melody-hints-and-beat-marks).

## Configuration

Change these through VS Code Settings by searching for `ulsbsTexTools`, or in
your workspace's `.vscode/settings.json`. These are **editor settings**, separate
from the compiler's `ulsbs-config.toml`.

| Setting | Default | Purpose |
|---|---|---|
| `ulsbsTexTools.enable` | `"auto"` | Auto-detect a project, force features `"on"`, or turn them `"off"` |
| `ulsbsTexTools.compileCommand` | `"ulsbs/ulsbs-compile"` | Compiler script path, relative to the relevant workspace folder |
| `ulsbsTexTools.askProfileOnCompile` | `true` | Show a picker for profile-selection actions |
| `ulsbsTexTools.defaultProfile` | `"default"` | Profile applied by those actions when the picker is disabled |
| `ulsbsTexTools.autoRefreshDiagnostics` | `true` | Update structural diagnostics automatically on edits and saves |
| `ulsbsTexTools.fileGlob` | `"**/*.*tex"` | TeX-like files considered for indexing and editing features |
| `ulsbsTexTools.excludeGlob` | See below | General scan/editing exclusions |
| `ulsbsTexTools.songbookExcludeGlob` | `[]` | Additional Songbooks-discovery exclusions, without disabling editing features |

For example, if your compiler wrapper is at the project root:

```json
{
  "ulsbsTexTools.compileCommand": "./ulsbs-compile",
  "ulsbsTexTools.askProfileOnCompile": false,
  "ulsbsTexTools.defaultProfile": "default"
}
```

General exclusions default to `**/temp/**`, `**/ulsbs/assets/tex/**`, and
`**/ulsbs-tex-tools/assets/**`. Internal extension-template exclusions are always
added, even when you override that setting.

Songbook discovery also always skips hidden directories (names beginning with
`.`), `ulsbs/tests`, and `tests/fixtures`. `songbookExcludeGlob` adds to those
built-in exclusions rather than replacing them. Use it to hide a document from
the Songbooks view while keeping ULSBS editing features in that file.

## Browser support

The package includes a web build for editing and navigation in `vscode.dev`,
`github.dev`, and browser-based Codespaces. Availability still depends on the
workspace's files and the installed extension.

The extension's **compile commands are disabled in browser-only VS Code**,
including a browser-based Codespaces session. They require a desktop VS Code
UI with a terminal and a usable compiler environment. The web build does not
run LaTeX or LilyPond in the browser.

## Troubleshooting

- **No ULSBS features:** open the project folder, check its detection markers
  and the `enable` setting, and use LaTeX language mode for `.tex` documents.
- **Songbooks view is empty:** check that main documents contain
  `\documentclass` or `\begin{document}`, are covered by `fileGlob`, and are not
  excluded. Run **ULSBS: Refresh workspace index**.
- **Current context finds no book:** the active file must be a main document
  or reachable through its indexed `\input` / `\include` dependencies. Check
  include paths and refresh the index.
- **Compiler script not found:** check `compileCommand` relative to the
  relevant workspace folder. A root-level wrapper needs `./ulsbs-compile`.
- **Build fails:** inspect the **ULSBS Build** terminal and test the compiler
  directly from the project root. The extension does not install build tools.
- **Create new songbook fails:** this command needs the vendored engine in the
  first workspace folder and will not overwrite an existing filename.
- **Profile is missing:** define it under `[profiles.NAME]` in the project-root
  config, then choose the profile again.

See the [extension changelog](CHANGELOG.md) for release history.

## License

GNU General Public License version 3 or later (GPL 3.0+).
