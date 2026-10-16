# Changelog

Changes accumulate under Unreleased and move to a dated version heading when
the extension is released.

## [Unreleased]

### Added

- Separate `_MULTIKEY` PDFs in `multikey/` with per-song key selection for non-lyrics variants;
  ordinary PDFs remain layer-free. See [Multikey PDF editions](README.md#multikey-pdf-editions).
- `multikey-books`, `multikey-layer-ui`, and `--no-multikey` controls. Quick
  builds skip multikey output.
- Song-ID-based layers, independent repeated-song controls, and embedded multikey
  metadata shared with JSON companions. `--require-song-ids` enables strict validation.
- An [architecture reference](ARCHITECTURE.md) for implementation details.
- `+` modifier for `\beginverse`, enabling the larger melody-note line spacing
  previously selected by a separate verse command. It composes with the
  existing unnumbered `*` modifier and `[n]` indentation as
  `\beginverse*+[n]`.

### Changed

- Source and multikey transposition follow `key=`, preserving scale degrees and
  chromatic alterations.
- All books use three LuaLaTeX passes (draft, full, full). Non-original key tags
  use a red transpose indicator; detailed job settings are shown only with `--verbose`.
- Avoid unnecessary MIDI generation for multikey and optional editions while
  preserving audio dependencies and explicit optional-variant export settings.
- `ulsbs-migrate-syntax-v1` now converts legacy melody-spaced verse delimiters
  to `\beginverse+...\endverse` while preserving numbering and indentation.
- Song metadata extraction and the VS Code extension now recognize every
  supported `\beginverse` modifier combination through the single canonical
  verse construct.

### Removed

- The separate melody-spaced verse commands. Use `\beginverse+` and
  `\endverse` instead, and run `ulsbs-migrate-syntax-v1` on existing sources.

## [0.2.1] - 2026-09-26

### Added

- `#` and `&` accidental shorthand in alternate chords and musical key
  metadata, while retaining `\shrp` and `\flt`.
- Default-off `\iftransposealtchords` control for transposing `\altchords`,
  including nested `\id` and `\ac` content and `\notrans` exclusions.
  Transposable alternate chords must use `#` and `&` for accidentals rather
  than `\shrp` and `\flt`.

### Changed

- Renamed the expanded migration tool and its module to
  `ulsbs-migrate-syntax-v1`; `ulsbs-migrate-melody-syntax` remains available as
  a compatibility alias.
- `ulsbs-migrate-syntax-v1` now also migrates explicit accidental macros to the
  shorthand within the newly supported contexts.

## [0.2.0] - 2026-09-23

> [!IMPORTANT]
> This release completely replaces the melody-note and beat-mark authoring
> system. Existing song sources must be migrated; the removed `\mn*`, `\ma*`,
> `\bm*`, and `\ac<n>{Chord}` syntaxes are not backward compatible. Review
> changes in version control and run:
>
> ```sh
> ulsbs-migrate-melody-syntax --diff PATH
> ulsbs-migrate-melody-syntax --write PATH
> ```

### Added

- Melody-block syntax and renderer with sequences, two voices, beats, gaps,
  offsets, zero-advance blocks, scoped positioning/styles, replay, and
  visibility controls.
- `ulsbs-migrate-melody-syntax` for checked, file-atomic source migration.

### Removed

- Legacy `\mn*`, `\ma*`, `\bm*`, and `\usealtmnstyle...` authoring macros.
- Legacy `\ac<n>{Chord}` syntax, replaced by `\ac{n}{Chord}`.
