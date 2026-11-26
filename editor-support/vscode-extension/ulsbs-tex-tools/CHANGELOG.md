# Changelog

## Unreleased

- Require VS Code 1.138.0 or newer.
- Preview ordinary songbook PDFs beside the source, with two-way SyncTeX.
  Use the keyboard shortcut to locate the current source line in the PDF.
  Ctrl-click (Cmd-click on macOS) in the PDF to jump back to the source, down
  to the word when the match is unambiguous. Song headers and engraved scores
  jump to their declarations. Rebuild the displayed variant from the preview
  toolbar or editor context menu, or opt into rebuilding affected open variants
  on save. Reloads preserve scroll position, manual zoom, and Fit mode.
- Extension builds request SyncTeX and show compiler colors and progress in the
  terminal. Manual builds ask before saving relevant files, and a new build
  replaces an older one for the same songbook.
- Exclude directories named `build` from songbook discovery.
- Add completions and snippets for lane-aware annotation spacing and explicit
  lyric spaces (`\ulSpace` and `\ulSpace*`), including `\ulSpace` between bars.
- Add snippets for selecting songs by stable ID (preferred) or printed number,
  choosing selection numbering, and setting a selected song's printed key.
- Add completion and a snippet for `\ulVerseBaselineToTopGap`.

## v0.3.0 - 2026-11-18

- Updated editing support and the new-book template for the current ULSBS API,
  including variant availability, local visibility, identity and musical tests,
  and scalar verse-spacing controls.
- Added title, author and tag index snippets and corrected required arguments
  in song-collection and passage completions.
- Improved chapter/section outlines and discovery of multiline main declarations.
- Build terminals now start in the selected book's workspace folder.

## v0.2.2 - 2026-10-24

- Added editing support for every canonical `\beginverse` modifier combination,
  including unnumbered `*`, melody-spacing `+`, and `[n]` indentation.
- Added a `ulsbsTexTools.songbookExcludeGlob` setting for adding Songbooks view
  discovery exclusions without disabling editing features in matching files.
- Unified verse parsing, outlines, completions, region tracking, folding, and
  indentation around `\beginverse...\endverse` as the sole verse construct.
- Songbook discovery now always skips hidden directories, `ulsbs/tests`, and
  `tests/fixtures`; configured Songbooks exclusions are merged with these
  defaults.
- Removed support for the separate legacy melody-spaced verse delimiters.

## v0.2.1 - 2026-09-26

- Synchronized the extension version with ULSBS 0.2.1. This release contains
  no extension functionality changes.

## v0.2.0 - 2026-09-23

- Added editing support for ULSBS melody blocks, including snippets, completions,
  delimiter feedback, compact tokens, and scoped placement/style commands.
- Added leading `!` support for zero-advance melody blocks, including completion,
  decoration, a snippet, and grammar fixture coverage.
- Added a LaTeX injection grammar that prevents same-line ULSBS `\[...]` annotations
  from being interpreted as display math.
- Chord and melody decorations now follow the new melody-block syntax; chords
  remain bold while melody tokens and delimiters use separate subtle styling.
