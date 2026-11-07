# Changelog

## Unreleased

- Updated snippets, completions, structural editing and the new-songbook template
  for current ULSBS command names and verse/repeat syntax.
- Added title, author and tag index declarations and configuration, including
  `\ulTagFile`; songbook templates and collection snippets include all three indices.
- Updated outlines for `\ulSongChapter` and `\ulSongSection`, including starred
  and optional short-title forms.
- Fixed missing required arguments in `ulSongs` and `passage` snippets and
  contextual completions.

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
