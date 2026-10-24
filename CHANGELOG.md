# Changelog

Changes accumulate under Unreleased and move to a dated version heading when
the extension is released.

## Unreleased

- Added `\symdim` and `\symhalfdim` macros for diminished and half-diminished chords.
- Added optional MULTIKEY editions with independent per-song key selection, native or
  programmatic layer controls, configurable chord-name shrinking, optional strict
  song-ID validation, and page-aware JSON metadata. Enable with
  `multikey-books = true`; ordinary PDFs remain layer-free. Each edition provides
  a `_MULTIKEY_RANGES.json` entry point and layered page-range PDFs in `multikey/`,
  with `_MULTIKEY` appended after the ordinary filename stem, for example
  `Book_A5_MULTIKEY_RANGE_1-50.pdf`. Range sizing is configurable with
  `multikey-max-pages-per-range` (50) and `multikey-target-max-range-bytes`
  (33554432, 32 MiB). Book metadata uses `multikey_json_file`; PDFs contain no
  embedded JSON. See [Multikey PDF editions](README.md#multikey-pdf-editions).
- Added opt-in LilyPond score transposition for MULTIKEY editions, with validated persistent
  caching, original-score fallback, `--clear-score-cache`, and asset audit/rewrite tools.
- Added a `+` modifier for `\beginverse`, enabling the larger melody-note line spacing
  previously selected by a separate verse command. It composes with the
  existing unnumbered `*` modifier and `[n]` indentation as
  `\beginverse*+[n]`.
- Songbook PDFs, including multikey editions, now use automatic, lossless font
  sharing to reduce file size while preserving appearance and all embedded glyphs.
  Host builds require `pikepdf` 8+; rebuild existing compiler images after upgrading. See
  [requirements](README.md#requirements).
- Source and multikey transposition follow `key=`, preserving scale degrees and
  chromatic alterations; non-original key badges use a red transpose indicator.
- Builds normally use three LuaLaTeX passes, with bounded extra passes only when
  references or MULTIKEY resources need to settle. MULTIKEY draft compilation
  avoids unused alternate visuals while preserving full twelve-key PDF output.
  Detailed job settings require `--verbose`; optional editions avoid unnecessary
  MIDI generation while preserving audio dependencies and explicit export settings.
- `ulsbs-migrate-syntax-v1` now converts legacy melody-spaced verse delimiters
  to `\beginverse+...\endverse` while preserving numbering and indentation.
- Song metadata extraction and the VS Code extension now recognize every
  supported `\beginverse` modifier combination through the single canonical
  verse construct.
- Removed the separate melody-spaced verse commands. Use `\beginverse+` and
  `\endverse` instead, and run `ulsbs-migrate-syntax-v1` on existing sources.

## v0.2.1 - 2026-09-26

- Added `#` and `&` accidental shorthand in alternate chords and musical key
  metadata, while retaining `\shrp` and `\flt`.
- Added a default-off `\iftransposealtchords` control for transposing `\altchords`,
  including nested `\id` and `\ac` content and `\notrans` exclusions.
  Transposable alternate chords must use `#` and `&` for accidentals rather
  than `\shrp` and `\flt`.
- Renamed the expanded migration tool and its module to
  `ulsbs-migrate-syntax-v1`; `ulsbs-migrate-melody-syntax` remains available as
  a compatibility alias.
- `ulsbs-migrate-syntax-v1` now also migrates explicit accidental macros to the
  shorthand within the newly supported contexts.

## v0.2.0 - 2026-09-23

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

- Added melody-block syntax and renderer with sequences, two voices, beats, gaps,
  offsets, zero-advance blocks, scoped positioning/styles, replay, and
  visibility controls.
- Added `ulsbs-migrate-melody-syntax` for checked, file-atomic source migration.
- Removed legacy `\mn*`, `\ma*`, `\bm*`, and `\usealtmnstyle...` authoring macros.
- Replaced legacy `\ac<n>{Chord}` syntax with `\ac{n}{Chord}`.
