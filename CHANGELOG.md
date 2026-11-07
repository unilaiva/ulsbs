# Changelog

## Unreleased

> [!IMPORTANT]
> **Source migration required before rebuilding existing books.** Public macro
> and book-assembly environment names have changed; old names are not runtime
> aliases. Run `ulsbs-migrate-syntax-v2` on your songbook sources, custom classes
> and includes. Review changes in version control:
>
> ```sh
> ulsbs-migrate-syntax-v2 --diff PATH
> ulsbs-migrate-syntax-v2 --write PATH
> ```
>
> Resolve any review diagnostics before compiling. Migrate separate legacy tag
> definitions explicitly with `--tags-file FILE`; source-directory scans do not
> convert them. See [v2 migration instructions](README.md#ulsbs-migrate-syntax-v2).

- Replaced the vendored `songs` runtime with native ULSBS TeX/Lua modules for
  song metadata/lifecycle, verses, chords, key-aware transposition, page layout,
  diagrams, multikey annotations and index display. LuaLaTeX is now the sole
  supported engine; no backend selection or upstream runtime install is needed.
  The short song notation remains supported; use v2 migration for the API and
  metadata cleanup described below.
- Renamed configuration, book-assembly, font and accessor macros to consistent
  `\ulCamelCase` names; assembly environments are now `ulSongs` and `ulIndexBlock`.
  Boolean settings use explicit setters such as `\ulShowTags{false}` and readable
  predicates such as `\ifulShowTags`. V2 migration updates supported old spellings.
- Title, author and tag indices are generated automatically inside LuaLaTeX with
  deterministic Finnish-compatible sorting and actionable input diagnostics.
  No separate indexing command is needed. Normal builds handle the required passes
  and convergence checks; manual LuaLaTeX builds must repeat until rerun warnings
  disappear.
- Tag definitions now use ordered UTF-8 `tags.txt` files without numeric count
  lines. Added `\ulTagFile`, renamed tag-index APIs, and extended v2 migration with
  explicit `--tags-file` conversion and safe file renaming.
- Removed chorus commands and settings; use verses with explicit repeat regions.
  V2 migration converts safe chorus notation and flags unsupported cases for review.
- Removed inherited `sr` metadata, song-reference accessors and three-braced
  metadata input. V2 migration diagnoses these for review instead of creating
  runtime aliases or converting scripture references into tags.
- Documented native module ownership, lifecycle hooks, custom metadata keys,
  verse/chord token boundaries and manual LuaLaTeX builds. Multikey layer names,
  effective-original layout, occurrence identity, external range manifests and
  page-range publication contracts remain unchanged.
- Updated the `songs` acknowledgement and derivative-work GPL-3.0-or-later
  account, citing the upstream package and implementation source's
  GPL-2.0-or-later grant and retaining Kevin W. Hamlen's attribution.

## v0.2.2 - 2026-10-24

- Compiler warnings now use structured, source-aware diagnostic counts, compact
  per-job summaries, clickable log paths, and retained `_DIAGNOSTICS.json` reports
  under `result/diagnostics/` with host paths. Successful jobs remain `SUCCESS`
  with a warning count; related output lines print atomically. Only the final
  LuaLaTeX invocation contributes warnings. Native TeX error file/line locations
  are retained in failed-job reports and linked in failure output without
  guessing original lines for generated TeX.
- Independent jobs continue after failures, while dependency-blocked multikey
  companions are distinguished from compilation failures. Automatic deployment
  requires a complete successful run; explicit `--deploy-last` deploys only
  finally successful jobs from the newest inventory, excluding partial artifacts.
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
