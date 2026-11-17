# Changelog

## Unreleased

> [!IMPORTANT]
> **Existing books require source and configuration migration.** Review the
> [v2 migration instructions](README.md#ulsbs-migrate-syntax-v2) before rebuilding,
> including custom classes, shared includes, tag definitions and compiler profiles.
> The migrator previews safe source changes; configuration changes require manual
> review. For sources predating the melody-block syntax, run v1 before v2.

### Variants and rendering

- Declare available variants in the main document with
  `variants={default,lyric,charango,bassclef}`. Omission now builds default only,
  without an implicit lyrics-only companion. Select declared variants with TOML
  `variants` or CLI `--variants`; explicit subsets do not add default. Quick mode
  builds only the ordinary default PDF and rejects conflicting selections.
- Variant presets apply before author preamble overrides. Visibility settings now
  distinguish preamble book permissions from grouped local requests:
  `\ulLocalShow` and short on/off commands cannot bypass a book-wide denial.
  `\ifulShow...` tests effective visibility, `\ulIfVariant` tests the selected
  variant, and `\ulIfMusical` tests whether chords, pitches or scores are enabled.
- Chords, melody pitches, beats, measures, scores and musical prose have separate
  visibility controls. Replay works without visible chords. Line spacing and bar
  heights follow visible notation; beat-only lines stay compact and hidden
  annotations leave no extra space. Ordinary verses handle melody hints without
  a spacing modifier. Existing books may paginate differently.
- Added scalar verse baseline/separation settings, minimum-gap and bar-height
  controls, and consistent melody-note sizing through `\ulMelodySize`.
  Translations, passages and explanations use their fonts' normal line spacing
  rather than lyric verse spacing.
- Default and instrument variants support optional multikey editions; lyrics-only
  does not. Bass-clef scores retain engraved chord names despite hidden inline
  chords. MIDI/audio exports remain ordinary-default-only unless explicitly
  enabled for other variants; score display does not control media generation.
- PDF titles now reflect the selected variant and final preamble metadata;
  explicit `\hypersetup` metadata takes precedence. Covers and badges keep
  variant-specific presentation even when visibility settings are customized.
- Improved narrow-layout typesetting: song titles wrap with configurable badge
  overlap (`\ulTitleBadgeOverlap`, default `false`), and `ulChordDiagramGrid`
  provides width-aware, nut-aligned diagrams. Fixed TOC, song-number and repeat-bar
  overfull warnings; oversized LilyPond systems shrink consistently across
  ordinary and multikey editions. Underfull boxes now have separate advisory
  counts, verbose details and retained JSON reports.

### Source and toolchain upgrade

- ULSBS no longer depends on the `songs` package or a separate indexer; song
  typesetting and title, author and tag indexing are built in.
- LuaLaTeX is now the only supported TeX engine. Configuration, book assembly,
  fonts and metadata accessors use `\ulCamelCase` names; song blocks use `ulSongs`.
  Boolean setters take explicit values, such as `\ulShowTags{false}`. Short
  song-content notation remains supported.
- Title, author and tag indices are generated automatically, with consistent
  Finnish-compatible sorting. Tag definitions use ordered UTF-8 `tags.txt` files;
  `\ulTagFile` selects a custom file. The compiler handles the required reruns.
- The v2 migrator now covers supported naming, variant declarations, local display
  settings and simple instrument-specific pagination. It also converts explicitly
  selected tag files. Ambiguous changes require review, and selected TOML configs
  are diagnostic-only, never rewritten. See the migration guide for removed
  metadata and chorus forms and their supported replacements.

### Other highlights

- MULTIKEY supplemental score engraving now uses spare parallel build capacity
  without increasing configured worker or memory limits. Retry order and parent-owned
  diagnostics are preserved; cancellation also stops active tool descendants.
- Compiler success messages now show per-edition compilation/packaging time and
  total compiler-run duration.
- Container builds now honor host spinner suppression, keeping redirected output
  free of spinner frames and forwarding `ULSBS_NOSPINNER` independently of color settings.
- Added `--plain-output` argument: disables colors and the status spinner on the host
  and in the container, overriding environment settings.
- Fixed duplicate transparency groups in imported PDF graphics. PDF optimization
  now requires `pikepdf` 10+ for host builds; rebuild older compiler images.
- Updated editor syntax help and snippets for the current public API, and
  reorganized the installation and author guides.
- Clarified GPL-3.0-or-later licensing and retained acknowledgement of Kevin W.
  Hamlen's `songs` package.

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
