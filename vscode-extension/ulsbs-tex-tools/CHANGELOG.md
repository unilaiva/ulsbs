# Changelog

Changes accumulate under Unreleased and move to a dated version heading when
the extension is released.

## [Unreleased]

## [0.2.0] - 2026-09-23


### Added

- Editing support for ULSBS melody blocks, including snippets, completions,
  delimiter feedback, compact tokens, and scoped placement/style commands.
- Leading `!` support for zero-advance melody blocks, including completion,
  decoration, a snippet, and grammar fixture coverage.
- A LaTeX injection grammar that prevents same-line ULSBS `\[...]` annotations
  from being interpreted as display math.

### Changed

- Chord and melody decorations now follow the new melody-block syntax; chords
  remain bold while melody tokens and delimiters use separate subtle styling.
