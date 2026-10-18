# ULSBS Architecture

This reference describes ULSBS internals and implementation contracts. For writing
sources and compiling books, start with the [README](README.md).

## PDF Font Sharing

All published jobs run `pipeline.py:step_pdf_fonts` after the third and final
LuaLaTeX pass, before publishing the job PDF to `result/`. The step calls
`pdf_fonts.py:deduplicate_fonts` on the canonical job PDF, so publication,
printouts, and cover extraction all consume the same validated artifact. It also
runs for quick, lyrics-only, instrument, and multikey editions. Multikey jobs first
validate their final-pass metadata; disabled companions are still skipped before
optimization or publication. LilyPond generation, the processed source tree,
MIDI/audio associations, and JSON export contracts are unchanged.

Font sharing is always enabled. `pikepdf>=8` is a required compiler dependency,
checked before compilation even when there are no scores
or duplicate fonts. The container installs `python3-pikepdf`; host installation
and image-rebuild instructions are in the [README requirements](README.md#requirements).
No external optimizer executable is required. Syntax checking supports both the
older `Pdf.check()` API and its replacement, `Pdf.check_pdf_syntax()`.

The optimizer shares only identical decoded `/FontFile`, `/FontFile2`, or
`/FontFile3` streams whose semantic dictionaries also match. Hashes locate
candidates, but exact byte equality authorizes sharing. Stream length, filter,
and decoding parameters are excluded from the identity after decoding; other
entries, such as font subtype and Type 1 segment lengths, must match. Font
names alone are never evidence of equivalence. Each font dictionary, encoding,
width table, and Unicode map remains intact. Different subsets are not merged,
and every original embedded glyph program remains available, including Noto Sans
programs used by LilyPond lyrics. Fonts are neither substituted nor unembedded.

A rewrite is saved to a temporary file in the job directory. Before replacement,
the candidate must be smaller, pass libqpdf syntax checks, and preserve the entire
reachable logical document graph. Comparison covers decoded streams, resource
dictionaries, metadata, multikey layer configuration, page dimensions, outlines,
links, and destinations; page identity is checked even for identical-looking
pages. Physical cross-reference
serialization and the PDF file identifiers (`/ID`) are not compared. Unsupported image codecs
must retain their encoded bytes and decoding parameters. Metadata rewriting is
disabled. Only a validated candidate is atomically renamed over the canonical
PDF. No-duplicate inputs are not rewritten; non-shrinking candidates are discarded.
Optimization or validation errors fail the job before publication without
replacing the original PDF. Encrypted or signed inputs are rejected rather than
silently invalidated.

`tests/test_pdf_fonts.py` covers stream identity, semantic validation, idempotence,
and atomic replacement/failure behavior. Pipeline tests cover publication order,
failure handling, and multikey publication. `tests/test_pdf_fonts_integration.py`
exercises real cold/warm lilypond-book and LuaLaTeX builds, comparing rendered
pixels and text geometry, checking embedded fonts, and preserving staged sources
and media mappings. Multikey integration checks embedded JSON and all twelve
key selections, requiring both identical baseline/candidate pixels and visible
differences between key selections. Rendering comparisons are regression checks,
not part of every production build's runtime validation. Savings depend on exact
duplication; substantial distinct-subset overhead may remain.

## Multikey Books

### Build jobs and publication

`Job.multikey` is a boolean orthogonal to the musical variant. Each selected
non-lyrics variant has an ordinary job and, when `multikey-books` is enabled, a
multikey job for the same source and variant. Lyrics-only jobs remain ordinary.
The existing `ULSBS-EXTRA-VARIANTS` comment selects instrument variants.

The queue rejects duplicate publication paths before starting jobs: independent
locks cannot prevent two sources/editions from overwriting the same artifact.
PDF directory separation does not eliminate collisions in the shared JSON folder.

`multikey-books` defaults to `false` and follows normal profile inheritance.
Profiles may override it in either direction, including root `false` to child
`true`. `multikey-layer-ui` is `native` by default and also accepts `hidden`.
`multikey-min-chordname-scale` defaults to the existing TeX floor, `0.85`, and
accepts finite numeric TOML values in `[0.5, 1]`, rejecting booleans and strings.
It follows the same root/profile inheritance and is supplied before class loading
as `\ulPdfTranspositionMinimumScale`. A value of `1` prevents chord-name scaling
both during initial overlay construction and late Lua lyric-space fitting.

The CLI `--no-multikey` override disables companions, and `-q`/`--quick` also
forces `multikey-books` off for that invocation.

Result mapping distinguishes multikey PDFs with `RESULT_TYPE_MULTIKEY_PDF`.
Their names put `MULTIKEY` before the musical variant and paper suffix:

| Variant | Ordinary result | Multikey result |
|---|---|---|
| Main | `book_A5.pdf` | `multikey/book_MULTIKEY_A5.pdf` |
| Charango | `book_CHARANGO_A5.pdf` | `multikey/book_MULTIKEY_CHARANGO_A5.pdf` |
| Bass clef | `book_BASSCLEF_A5.pdf` | `multikey/book_MULTIKEY_BASSCLEF_A5.pdf` |

Ordinary PDFs remain at the `result/` and deploy roots. Multikey PDFs are routed
to their respective `multikey/` subdirectories using `RESULT_TYPE_MULTIKEY_PDF`;
result-list entries retain the basename rather than embedding the subdirectory.
Multikey jobs
never generate printouts, MIDI, audio, or cover images. When JSON export is
enabled, the coordinator publishes matching multikey JSON under the existing
`json/` directory, after all ordinary jobs finish. It copies the successful
ordinary variant's full metadata and final media links, then adds the renderer's
multikey payload. It never rebuilds or exports those media for the companion.
Only current-run successful JSON is used; stale files are not a fallback.
JSON companions remain in `json/`, not `multikey/`. Their media references are
relative to the result/deploy root, not the multikey PDF's directory.

Multikey jobs suppress even intermediate LilyPond MIDI generation, not merely
its publication. Ordinary optional variants suppress that MIDI
include only when neither MIDI export nor audio export is actually enabled for
the variant. Each export requires both its general feature flag and its
respective `midifiles-allow-for-optional-variants` or
`audiofiles-allow-for-optional-variants` opt-in. `--no-midi` and `--no-audio`
independently disable their respective exports even when an optional-variant
opt-in is set. The main ordinary variant retains its original MIDI include.

With opt-ins, both MIDI copying and audio encoding resolve
`song.midi_compile_file_relative` against that job's `compile_dir`, consuming
variant-local MIDI rather than reusing the main variant's files. Usual defaults
export media only from the main ordinary variant. Audio-only export still needs
intermediate MIDI and the internal song metadata database, even with MIDI and
JSON exports disabled. `--no-midi` suppresses published MIDI files, not the
intermediate MIDI required by enabled audio; the metadata database is built when
JSON, actual MIDI export, or actual audio export needs it. LilyPond processing and score
engraving remain active for all jobs, including lyrics-only output; only the
job-local MIDI include is suppressed under the conditions above.

The pipeline defines `\ulPdfTranspositionLayers`, `\ulPdfTranspositionLayerUI`,
and `\ulPdfTranspositionRequireSongIDs` before loading the class/package.
Layers are `true` only for multikey jobs and `false` for ordinary and lyrics
jobs. Manual LaTeX compilation defaults to layers `false` and UI `native`.
Manual builds may define `\newcommand{\ulPdfTranspositionLayers}{true}` before
class/package loading; pipeline-driven sources must not duplicate its definitions.

A companion candidate whose source initializes lyric-only mode or does not load
the renderer explicitly reports disabled capability. It is skipped without
publishing an ordinary PDF under a multikey name. This is different from an
enabled renderer whose valid songs currently hide every annotation.

### PDF passes and resources

All jobs use three LuaLaTeX passes: one draft pass followed by two full passes.
Song indices are generated between the first and second passes.

Draft mode omits image objects. Consequently, PDF object numbers recorded in a
draft run cannot safely describe final optional-content page resources. The
second full pass resolves resources against the preceding full run. This also
keeps the final reference-resolution pass consistent for ordinary books. Manual
layer-enabled builds must likewise rerun full, non-draft LuaLaTeX until
references settle; counting draft runs as equivalent is unsafe.

The renderer uses `ocgx2`/`ocgbase` named `/Properties` resources for marked
content. Every `/OC` marked-content name must resolve to an actual catalog OCG.
An experimental inline OCMD approach with indirect references embedded in content
streams was rejected: PDF.js accepted it, but Poppler reported syntax errors,
and PDF rewriting could not safely renumber those embedded references. A clean
`qpdf --check` alone is not sufficient evidence of correct layer rendering.

### Opt-in score layers

`multikey-lilypond-scores` defaults to `false` and only affects multikey,
non-lyrics jobs. Originals still use the normal LilyPond pipeline. The focused
`lilypond_scores.py` module wraps generated per-system graphics inclusions with
snippet identities while preserving their existing inter-system break tokens.
Repeated references to the same system retain their original placements.

The existing first LuaLaTeX draft pass writes `<job>.ulsbs-scores.json` through
`ulsbs-score-layers.tex` and `ulsbs-score-layers.lua`. This private request
manifest contains the runtime song occurrence, effective tonic/mode, and twelve
structured target tonics obtained from the existing TeX spelling policy. There
is no raw song-key parser and no additional TeX pass. Between draft and full
passes, Python engraves supported alternatives and writes
`<job>.ulsbs-score-variants.tex` plus `<job>.ulsbs-score-results.json` diagnostics.
Stale dispatch/request files are cleared before draft collection.

Recognized head/tail snippets without additional custom includes are eligible.
Native `\transpose` assignments are inserted before the tail consumes the
already-defined music variables. Structured `ly:make-pitch` operands avoid
interpreting generated intervals under a source's custom note-name language.
The shortest signed interval is tried first, then its octave equivalent on
failure. Every system PDF must be valid and fit both original dimensions at a
uniform scale of at least 0.80, with no enlargement or recognized omitted-tab
diagnostic. Failure of any system rejects the complete score for that offset;
other successful offsets remain available. Custom/unresolved-key scores fall back.
Alternative engravings force the C diagnostic locale, so localized hosts cannot
silently bypass warning-based tablature validation.

An omitted-tab diagnostic rejects that candidate even when LilyPond exits zero.
A successful octave retry is normal operation, not a warning. If both candidates
fail, the original notation remains and the job warns once per song occurrence
and distinct final failure reason, combining score identities and listing the
affected `tNN (target)` selections. Different occurrences and failure reasons
remain separate. `--verbose` enables DEBUG candidate failures/log paths,
successful octave retries, and the engraving/cache/success/fallback summary;
ordinary output contains no per-offset progress or summary. The private
`<job>.ulsbs-score-results.json` retains every attempt and its individual reason,
including first-octave failures that are recovered by the next candidate.

For enabled jobs only, the pipeline appends `ulsbs-score-boundaries.ily` to the
copied common tail. Its `grob-transformer` composes with existing
`System.after-line-breaking` callbacks rather than replacing them, leaving t00
music and drawing unchanged. `<snippet>.ulsbs-boundaries` records exact rational
main/grace moments at both ends of every system during original engraving.
Python validates contiguous ordered boundaries against the original graphics
inventory. All candidates receive a parallel structured timing voice with
automatic line breaks disabled; multi-system originals also supply forced
`LineBreakEvent`s at their internal boundaries. A single-system original needs
the same line lock: transposed accidentals/chord labels can otherwise wrap it
into two systems even when the notation fits the original footprint after scaling.
This does not parse or change staff sizes: head defaults and effective
`\setStaffSize` overrides remain authoritative. There is no automatic staff-size
search on count mismatch; exact replay and whole-offset fallback remain required.
Candidate boundaries must exactly equal the originals, not merely have the same
count.
Pickups, initial grace music, and internal breaks at negative grace moments are
supported. Replay groups endpoints sharing a main time into one bare structured
`GraceMusic` branch: forced breaks and rational skips advance from the earliest
requested negative grace moment to zero. An ordinary break at that same main
time follows outside the grace block. The original music tree is not rewritten
or unfolded. Positive grace-time boundaries and nonzero final grace moments
remain explicit fallbacks. Incompatible repeats/custom timing also fall back if
replay does not reproduce the authoritative full main/grace boundary sequence.

Full passes overlay each system in its existing occurrence-specific OCGs using
the original box dimensions and baseline; alternatives never enlarge or reserve
additional layout space. Score overlays reuse the public OCG names and metadata
contract described below, including their shipped page dependencies.
The original LilyPond justification settings are retained, including per-snippet
overrides; both standard heads explicitly set `ragged-right = ##f` and
`ragged-last = ##f`. This does not guarantee equal rendered staff lengths after
overlay fitting. If the alternative is taller, the uniform fit can be limited by
the original height and shrink its horizontal extent too. Stretching only the
horizontal PDF axis would distort notation; fitting width alone could overlap
adjacent content. Equal visual widths would require a separate native spacing
refit with per-system validation, not another justification flag.
If a validated graphic later disappears or no longer fits, the TeX renderer's
last-resort per-system guard substitutes that original system; Python validation
normally rejects the entire offset before dispatch. Native LilyPond spelling
can retain double accidentals that the TeX labels simplify.
`ulsbs-score-variants/` remains disposable job-local output, not evidence of a
cache hit. `lilypond_score_cache.py` maintains a separate content-addressed cache
under `$XDG_CACHE_HOME/ulsbs/lilypond-scores` (or `~/.cache`), with an absolute
`ULSBS_SCORE_CACHE_DIR` override. The normal container already mounts its home
on the persistent home-cache volume. Keys include source and recursive include
contents, tuning, geometry, original musical boundaries, signed/spelled interval,
transformation semantics and version, LilyPond executable/version/data, fonts
and rendering-related environment. Job-local paths normalize to `$JOB`;
container hostnames, build IDs and source-copy timestamps do not invalidate
entries. Unresolved/dynamic dependencies or unaudited Scheme conservatively
disable caching while retaining ordinary engraving and validation.

The standard container runner mounts the named Docker/Podman volume
`ulsbs-compiler-homecache` at `/home/ulsbs` and sets `HOME` accordingly. Score
entries therefore normally live at `/home/ulsbs/.cache/ulsbs/lilypond-scores`.
The project, temp output and Python sources are separate bind mounts. Container
removal and job-temp cleanup preserve the named volume; the existing image
rebuild path attempts to remove the whole volume, which also contains other
home caches. No new cache-specific mount is required.

The CLI-only `--clear-score-cache` option is forwarded through the host wrapper
and executes once in the actual compilation environment, after plan/tool
validation and before starting jobs. With `--no-container` it uses the host cache;
with the normal container it uses the cache inside that volume. `cache_root()`
resolves the same environment-specific override/default as normal reads/writes.
Missing caches are a no-op. Clearing preserves the root, unrelated files and
in-progress `.publish-*` directories, and removes only completed hash-named
directories with recognized flat cache contents. Unrelated hash-named regular
files cause refusal before anything is deleted. Corrupt manifests are removable;
symlink targets are never traversed and symlinked roots/unrecognized entry
contents are refused. Failure is fatal for this explicit request, unlike an
ordinary nonfatal cache miss. Help, shell and deploy-only modes do not clear.
This is not a global cache lock: another running compiler can republish entries;
avoid concurrent builds when requiring a reliably cold run.

#### Trusted Cache Assets

Trusted hashes live in the packaged `assets/lilypond-score-cache-assets.json`
(in the checkout, `src/ulsbs/assets/lilypond-score-cache-assets.json`), not in
Python's former `_TRUSTED_ASSETS` set. The manifest has `schema_version: 1`, an
`assets` map from bundled source filenames to SHA-256 digests, and a `variants`
map from reviewed generated-variant labels to SHA-256 digests. The shipped
variants include `common-tail-convert-ly-2.26.0` and `midi-disabled`.
Runtime validates the manifest; a missing or malformed file makes score caching
ineligible with a nonfatal warning, never automatic approval. Unknown asset
digests likewise disable caching, not engraving or validation.

This trust record is neither a security sandbox nor a LilyPond-version allowlist.
Toolchain fingerprints automatically invalidate entries when the executable,
version, data or other keyed toolchain inputs change.
The two explicitly recognized pipeline mutations are normalized for this trust
check only; their full modified bytes are still part of the cache fingerprint.
A LilyPond upgrade alone needs no manifest edit. If an upgrade also requires
changed assets or different `convert-ly` output, review and explicitly approve
those exact file contents before expecting cache reuse for them.

Use the read-only developer audit command after changing assets or running
`convert-ly`:

```bash
# Installed command: audit all bundled .ly/.ily assets.
ulsbs-score-cache-assets

# Audit a copied/mutated job asset directory or an individual converted tail.
ulsbs-score-cache-assets /path/to/job/ulsbs-assets/ly
ulsbs-score-cache-assets /path/to/converted-tail.ly

# From the engine checkout, without reinstalling entry points.
PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache

# Inside a normal compiler shell (PYTHONPATH is already configured).
python3 -m ulsbs.lilypond_score_cache /path/to/job/ulsbs-assets/ly
```

Each line reports `TRUSTED` or `UNTRUSTED`, the audit SHA-256 digest and the path.
Directory arguments scan their immediate `.ly` and `.ily` files. The audit
normalizes only the same two approved pipeline mutations used by cache
eligibility; its digest can therefore differ from raw `sha256sum` output for
mutated job copies. The complete modified bytes remain fingerprinted separately.
Exit status is 0 when all files match audited hashes, 1 for unknown hashes, and
2 for unreadable/missing inputs or an asset directory without `.ly`/`.ily` files.
Without `--rewrite`, the command is read-only and never approves hashes or edits
the manifest. It checks hash membership, not whole-score cache eligibility or
the safety of arbitrary code. Neither audit nor rewrite executes LilyPond,
Scheme, or `convert-ly`.

Before approving changes, inspect the source diffs and all dependencies, ensure
that executable Scheme has no untracked file/environment inputs. `--rewrite` records the maintainer's
explicit approval; it does not verify code safety. All 21 bundled `.ly`/`.ily`
source headers carry maintenance notes with rewrite instructions.

After that review, regenerate the source records from the ULSBS source root:

```bash
# Source-root invocation avoids an entry point that may require installation.
PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache --rewrite

# Equivalent installed entry point (uses sources bundled next to that tool).
ulsbs-score-cache-assets --rewrite
```

`--rewrite` always reads the bundled sources next to the tool, never positional
paths. It atomically replaces the entire `assets` map with current source
records, removing obsolete source records while preserving named `variants`.
The optional `--manifest FILE` selects the manifest used for audit or the output
manifest for rewrite, for developer workflows; it does not change which bundled
sources rewrite approves.

For a generated common-tail variant, convert a copy separately, review its diff
and dependencies before approval. For example,
using `convert-ly` 2.26.0 from the ULSBS source root:

```bash
cp src/ulsbs/assets/ly/ulsbs-internal-common-tail.ly /path/to/converted-tail.ly
convert-ly -f2.24.4 -e /path/to/converted-tail.ly
# Only after reviewing the conversion and its dependencies:
PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache --rewrite --variant common-tail-convert-ly-2.26.0=/path/to/converted-tail.ly
```

`--variant NAME=FILE` is allowed only with `--rewrite`. It adds or replaces the
reviewed generated variant by label; all other variants are retained. Manually
remove obsolete named variants from the manifest after review. A variant rewrite
also refreshes all bundled source records, so review those sources too. Do not
approve every reported hash merely to silence a warning.
After regenerating hashes, run the cache and relevant native score regressions,
audit the sources again, and review the manifest diff before committing.

When a score-generation job has requests, it audits the job's copied bundled
asset directory once. Each unknown asset produces one warning with its filename,
audit hash and maintenance command, not eleven warnings per score or repeated
occurrence. Audit failures are nonfatal warnings; ordinary source/dependency
eligibility checks remain authoritative. Known instrument/boundary mutations and
audited converted tails do not warn. The pipeline's exact comment-only
MIDI-disabled replacement is recorded as the `midi-disabled` variant. Ordinary
editions and jobs not generating score alternatives do not run this check.
Changed custom song Scheme retains
the existing debug diagnostics rather than being presented as bundled-asset drift.

The manifest workflow changes trust-record maintenance, not the two recognized
mutation normalizations or cache fingerprint semantics. `--clear-score-cache`
and the named home-cache volume retain the behavior described above.

#### Cache Validation

Only successful, musically validated alternatives are published. Publication
uses a private staging directory and atomic rename; concurrent first writers
cannot expose partial entries. Manifests and every artifact carry content
hashes, and restored PDFs, logs, crops, scales and musical boundaries are
revalidated. Files are copied, not hard-linked, into the job. Missing/corrupt or
unwritable entries are nonfatal cache misses; failed attempts are not cached.
Originals are still engraved normally. The result manifest reports actual
`engravings` and `cache_hits` separately from requested candidate `attempts`.
Warm processing uses a fresh `_lp-source` directory containing the configured
main input and engine asset aliases, not processed song imports. Both source
discovery and LilyPond's LaTeX geometry probe exclude the job's generated
root/content/include search paths. Probe outputs stay inside the job; source
directories need not be writable. `_lp` is cleared before each invocation.

The private `lilypond_book.py` launcher runs the installed Python lilypond-book
script with its recursive `do_file` traversal guarded by normalized output
document path. LilyPond 2.24 and 2.26 otherwise concatenate repeated visits into
the same generated TeX file. Processing each output once preserves every TeX
input command, so repeated runtime song occurrences remain independent without
duplicating the imported file's content. The launcher does not change snippets,
musical transformations, or installed toolchain files.

Each successful run writes `<job>.ulsbs-lilypond-systems.json`, a private array
of job-relative current systems fragments. Score preparation uses this inventory
instead of mistaking old, removed snippets for current candidates. Retained
graphics are working files, not cache entries. Warm tests cover source and
dependency edits, preamble geometry changes, removals, repeated/nested inputs,
engine aliases, source-tree cleanliness, and fatal original engraving failure.
Source include paths are supplied to lilypond-book itself as well as its
engraving subprocess, so external `\lilypondfile` inputs resolve from original
sources. External snippets use the same content-hashed output naming as inline
snippets. `--use-source-file-names` is deliberately absent: with the shared
engraving/output directory, LilyPond does not create the renamed files, leaving
dangling TeX references. Hashed naming also avoids collisions between different
external scores sharing a basename. Tests resolve actual graphics through TeX
and verify independent edits of such external scores.
Native integration tests cover page-spanning multi-system overlays, exact
boundary replay, original callback preservation, note-name language changes,
major/minor/chromatic material, source transposition, slash chords, both voices,
charango tunings, bass clef, tablature retries, and fresh-directory cache reuse.

### Layer protocol

Layers transpose verse chords, inline `\ac` references, pitched melody hints and
the declared `key=` badge. Recommended singing keys (`gk=`), standalone
`\altchords`, prose and chord diagrams do not switch. LilyPond notation switches
only with the separate score opt-in. The stock bass-clef setup hides transposable
annotations, so its companion has no visible switching effect unless annotations
or score transposition are enabled. Original notation determines layout and
default viewing/printing; hidden notation may still appear in search, copy/paste
or accessibility output. The ordinary PDF is the conventional printing fallback.

Each retained transposable occurrence with a valid `\beginsong` `id=` has twelve
mutually exclusive optional-content groups (OCGs).
IDs follow the existing lowercase `[a-z0-9-]+` convention. First occurrences use
`ulsbs:transpose:v1:id:example-song:t00` through `:t11`. Repeating that ID appends
`:o02`, `:o03`, etc. before `:tNN`, for example
`ulsbs:transpose:v1:id:example-song:o02:t05`. Occurrence padding is at least two
digits, not a limit of 99. Each exact name is `layer_prefix + ":tNN"` and is
unique across repeated occurrences. Different occurrences are independent, even
when their original keys differ. Printed song numbers are never part of this identity.

A private document sequence still identifies TeX/PDF objects, but is not the
exposed layer name or a public song ID. Missing/invalid IDs keep ordinary
notation and skip interactive layers with a warning. Set
`multikey-require-song-ids = true` or pass `--require-song-ids` for strict multikey
validation; ordinary editions are unaffected. ID assignment is an explicit
source-editing preflight, not a compilation-worker side effect.

`t00` is the effective notation after the user's source-level transposition at
that occurrence. `t01` through `t11` add semitone offsets modulo an octave to
that notation. Each occurrence has an independent radio-button group; switching
one occurrence must not alter another. Initially only `t00` is visible. Print usage and automatic-state
policies select original notation rather than the screen-selected alternative.

Creation is lazy: the first generated transposable box allocates the occurrence's
OCG family. An occurrence that generates no such box allocates no family. Boxes
later discarded may leave unused OCGs, but only actual shipped marked content
retains an occurrence in the metadata `songs` array; unused OCG declarations do
not create manifest records.

`native` exposes the layer list. `hidden` changes native panel exposure without
removing groups, stable names, radio groups, or programmatic switching. Neither
mode requires JavaScript or interactive form controls for transposition.

### Embedded multikey metadata

The LuaLaTeX backend embeds UTF-8 JSON in XMP property `ulsbs:multikey`, namespace
`urn:ulsbs:multikey:1`. This stream is self-contained and does not rely on a JSON
sidecar. Standard PDF Info fields remain unchanged. An existing catalog XMP
writer is rejected rather than silently overwritten; integrating competing XMP
writers requires an explicit merge strategy.

The following illustrates the envelope; position values depend on layout:

```json
{
  "has_multikey_info": true,
  "multikey_info": {
    "schema_version": 2,
    "layer_protocol": "ulsbs:transpose:v1",
    "coordinate_space": "pdf-user-space",
    "songs": [{
      "song_id": "example-song",
      "occurrence": 1,
      "original_key": "Am",
      "key_labels": ["Am", "B♭m", "Bm", "Cm", "C♯m", "Dm", "D♯m", "Em", "Fm", "F♯m", "Gm", "G♯m"],
      "layer_prefix": "ulsbs:transpose:v1:id:example-song",
      "page_index": 5,
      "layer_page_indices": [5, 6],
      "anchor": {"x": 397.125, "y": 554.375},
      "has_transposable_content": true
    }]
  }
}
```

`original_key` is the trimmed, detokenized `key=` value, or `null`. Use the twelve
compiler-generated `key_labels` for human-facing labels: they normalize `#`/`&`
to Unicode accidentals and use exactly the target-key spelling policy of the
notation renderer. Labels are `null` when the key cannot be interpreted; use
"Original" and semitone-offset labels instead. Offsets are relative to each
occurrence's effective original key, not a global key for that song ID.

`page_index` is zero-based physical PDF order, including covers and preliminary
pages, independent of printed page counters. `anchor` is in native PDF user
space (normally points, bottom-left origin), two bp to the right of the virtual
top tag row. It exists even without a key or any tags. Zero-size late-Lua markers
capture actual shipout positions without reserving layout space. No UI widget is
drawn in the PDF. Unshipped headers have `null` positions.

`layer_page_indices` is required for every song entry: a sorted, unique array of
zero-based physical PDF page indices containing actual shipped `/OC`
marked content for that occurrence. It is the union across all twelve alternatives,
not just the default or currently visible layer. Different songs may share any
of these pages. It does not replace or change the navigation `page_index` or
`anchor`. Tracking follows actual shipout, not generated measurement boxes,
header ranges, or the next song's position. Incomplete or inconsistent tracking
is fatal; the compiler must not guess page ranges.

`UL_pdf_mark:nn` is the shared marked-content emitter for chords, melody hints,
key badges and opt-in LilyPond systems. Every alternative contains a late-Lua
page marker. Page-list sentinels delimit actual physical shipout, excluding
reusable PDF form serialization, which executes late Lua once per form rather
than once per page placement. Wrapping transposable ULSBS content in such forms
is unsupported and fails compilation; imported LilyPond graphics inside the
outer marked-content wrapper remain supported. TeX leaders suppress late Lua;
the shipout list check rejects transposable content inside leaders rather than
silently omitting dependencies. Ordinary copied boxes are supported. No separate
production PDF analysis pass is needed.

The twelve layer names are derived from `layer_prefix`; there is no need to
duplicate them or repeat the occurrence's union page array for every step.

`has_transposable_content` records actual shipped marked content, not measurement
boxes. The field is preserved and is `true` with nonempty `layer_page_indices`
for every retained entry; occurrences without shipped transposable content are
omitted from `songs`. If a false entry
is ever present, its `layer_page_indices` must be `[]`. An enabled manifest may
therefore have an empty `songs` array, for example when the stock bass-clef setup
hides every eligible annotation and score transposition is disabled.

Schema 2 changes the metadata contract only: `layer_protocol` remains
`ulsbs:transpose:v1`, and the XMP property and namespace remain unchanged.

The backend writes the same envelope to a temporary `.ulsbs-multikey.json` compile
artifact. Python captures it before cleanup. Exported ordinary book JSON has
`has_multikey_info: false` and `multikey_info: null`; exported multikey book JSON
retains ordinary book metadata and adds the exact embedded `multikey_info`
object with `has_multikey_info: true`. Full book metadata is not embedded in
ordinary PDFs. Embedding multikey metadata requires no extra PDF postprocessing
stage; font sharing is the separate step described above and preserves that metadata.

Each LuaLaTeX pass first removes any prior renderer artifact. Disabled capability
writes a current-run `false`/`null` envelope without adding XMP; a missing or
malformed artifact is an error, not evidence that the renderer is disabled.

### Viewer integration

1. Read XMP from the opened PDF, or use the matching exported JSON. Check
   `has_multikey_info`, require `schema_version === 2`, and check `layer_protocol`
   before using it. Validate each required `layer_page_indices` as sorted, unique,
   integer page indices within the document, consistent with
   `has_transposable_content`.
2. For each positioned entry with `has_transposable_content: true`, create a
   selector using `key_labels` or offset labels. Keep repeated occurrences separate.
3. Resolve all twelve exact names `layer_prefix + ":t" + String(offset).padStart(2, "0")`
   against the viewer's optional-content groups. Never assume PDF object IDs equal
   names, and never select by `song_id` or prefix matching alone.
4. Turn on the selected group and turn off the other eleven in that family only.
   Apply the updated configuration and invalidate every page in that occurrence's
   `layer_page_indices`, including cached pages not currently visible. Rerender
   visible affected pages now; off-screen affected pages must use the new state
   when next rendered. Keep invalidation page-local, not document-wide, and do
   not infer ranges from the header's `page_index` or the next song's header.
5. Transform the anchor with the actual page viewport. Do not treat it as CSS
   pixels, percentages, or a top-left coordinate. Widget dimensions and clamping
   remain viewer policy; use text content, not HTML interpolation, for labels.

PDF.js example (its v5 `getGroups()` API and v6 iterable configuration are both
shown because deployed viewers may use either):

```js
const { metadata } = await pdfDocument.getMetadata();
const raw = metadata?.get("ulsbs:multikey");
// Metadata is optional; a malformed payload must not prevent ordinary viewing.
let envelope = null;
try { envelope = raw ? JSON.parse(raw) : null; } catch { /* no multikey UI */ }
const info = envelope?.has_multikey_info ? envelope.multikey_info : null;
// Proceed only for schema_version === 2 and the supported layer_protocol;
// validate layer_page_indices and the other entry fields before creating UI.

const config = await pdfDocument.getOptionalContentConfig({ intent: "display" });
const groups = typeof config.getGroups === "function"
  ? Object.entries(config.getGroups() ?? {}) : Array.from(config);
const byName = new Map(groups.map(([id, group]) => [group.name, id]));

function selectOffset(song, offset) {
  const ids = Array.from({ length: 12 }, (_, n) =>
    byName.get(`${song.layer_prefix}:t${String(n).padStart(2, "0")}`));
  if (!Number.isInteger(offset) || offset < 0 || offset > 11 ||
      ids.some(id => id === undefined)) throw new Error("Invalid multikey selection");
  ids.forEach((id, n) => config.setVisibility(id, n === offset));
  // Invalidate all song.layer_page_indices, including off-screen cached pages.
  // Rerender visible affected views using this updated optional-content config.
}

// Use the viewport of pdfDocument.getPage(song.page_index + 1), including its
// current scale, crop, and rotation, for an overlay in that page's view.
const [left, top] = viewport.convertToViewportPoint(song.anchor.x, song.anchor.y);
```

Changing layers also switches opted-in score/TAB alternatives, but never audio.
Scores remain unchanged when score transposition is disabled. Printing should
use a fresh `intent: "print"` configuration, not the modified display configuration, to keep
the original-only print policy.

### Notation state and layout

The renderer separates musical visual alternatives from shared semantic state.
Chord memorization, replay, payload processing, and arbitrary source side effects
must execute once, not once per offset. Replay retains the existing `songs`
semantics, and visibility is evaluated at replay time.

Interactive content comprises verse chords, inline verse `\ac` references,
pitched primary and secondary melody hints, and the declared prelude `key=`
badge. Beat marks and unpitched markers remain shared. General prose, explanations,
chord diagrams, `gk=` recommendations, standalone `\altchords`, and LilyPond
scores remain outside interactive transposition by default; the opt-in score
layers described above reuse the same occurrence-specific OCGs. Standalone
alternate chord sets retain their existing authoring/transposition API.

The stock bass-clef post-setup disables chords and pitched hints, which also
hides the key badge. Without opt-in score layers or reenabled annotations, its
occurrences generate no transposable boxes, allocate no OCG families, and are
omitted from `songs`. More generally, discarded boxes can allocate unused OCGs
without creating manifest entries. Do not confuse such unused declarations with
dangling resource references.

Only original notation determines box dimensions, advance, line breaks, and
pagination. Alternative labels are drawn in the original box. Narrower or equal
labels keep their scale; wider labels shrink proportionally, bounded by
`\ulPdfTranspositionMinimumScale` (default `0.85`, valid range greater than zero
and at most one for manual TeX; the compiler's `multikey-min-chordname-scale`
option restricts this to `[0.5, 1]`). A floor of `1` leaves every alternative
chord label at natural size. If that floor is insufficient, labels may overflow without
reflow. Empty/zero-width originals must not cause division by zero. Melody
circles retain their geometry; the pitched glyph changes inside the circle.
The setting does not affect key-badge typography or LilyPond's independent
whole-score image fit floor.

The prelude badge uses the already-effective declared key, without reapplying
the user's source offset. Alternative badges keep a fixed right edge, with only
the original contributing dimensions. Non-default badges use
`transposedkeycolor`, a dark red with a slight blue component (`rgb={0.60,0,0.04}`),
and prefix the tag label with the reusable `\symudarrow` (`⮁`, U+2B81) and a normal
space. The glyph comes from Noto Sans Symbols 2. Consumers may override the color
with `\colorlet{transposedkeycolor}{...}` or `\definecolor`. Original viewing and
printing preserve the original key and original color.

Ordinary chord syntax, slash basses, accidentals, and common typography such as
`\up`, `\textsuperscript`, and `\kern` are supported. Unsupported commands or
command-bearing groups use conservative shared text, with a song-context warning,
rather than reexecuting arbitrary macros twelve times. Such custom content does
not automatically acquire interactive transposition. Do not split a command
from its unbraced, optional, or dimension arguments, or break a complete chord
into independently scaled typographic fragments.

### Key spelling

Key-aware spelling is independent of layers: ordinary `\transpose` must use it
even when `\ulPdfTranspositionLayers` is `false`. `key=` is always the effective
destination key. Ordinary source transposition infers the source tonic by
subtracting the active source offset, choosing its letter from the conventional
tonic table. For `key={F}` and `\transpose{5}`, source C major is inferred:
source F becomes B-flat and source G-sharp becomes C-sharp. For declared F and
offset -2, inferred G-major F-natural is a lowered seventh and becomes E-flat.

For each note, preserve the diatonic degree relative to the source tonic and
its signed chromatic alteration relative to the source scale. Apply that degree
and alteration to the target scale. Chord roots, slash basses, and both melody
sequences share the policy; chord qualities and extensions are retained. The
prelude layer key is derived from the declared effective key, not raw source
chords. Natural minor is the reference for minor keys, so raised degrees used
in harmonic or melodic minor retain their alterations.

Conventional major tonics by pitch class are C, D-flat, D, E-flat, E, F,
F-sharp, G, A-flat, A, B-flat, B. Minor tonics are C minor, C-sharp minor,
D minor, D-sharp minor, E minor, F minor, F-sharp minor, G minor, G-sharp minor,
A minor, B-flat minor, B minor. These are spelling conventions, not claims that
enharmonic alternatives are invalid. The effective key and offset alone cannot
recover an author's original F-sharp-versus-G-flat source tonic choice.

If degree preservation would require a double accidental, use a pitch-equivalent
single-accidental enharmonic spelling. Missing keys use the current
`\preferflats`/`\prefersharps` preference without guessing from the first chord.
Unsupported or decorated keys use the same fallback and issue a song-context
warning. Supported keys are an A--G tonic, an optional accidental, and optional
`m`; supported accidentals are `#`, `&`, `\shrp`, and `\flt`. Lowercase `b` is
not a flat alias.

Zero-offset notation is not respelled merely by enabling layers. Alternate
evaluation must preserve ambient transposition and accidental preferences.
Typography-only note conversion must not inherit a key-aware transformation
and apply the interval a second time. Standalone `\altchords` retain their
independent opt-in source-transposition policy, not the song-key policy.

### Viewer compatibility

Layer support, native controls, and optional-content print policies vary by
viewer. Use ordinary PDFs for conventional printing or maximum compatibility.
Hidden layer text may still appear in search, copy/paste, and accessibility data.

PDF.js 6.4.299 library/canvas validation confirmed independent song switching,
distinct rendering for all twelve offsets, and original-only rendering with a
fresh `getOptionalContentConfig({intent: "print"})`. A viewer must not reuse a
user-modified display configuration for print rendering. PDF.js text extraction
still includes hidden alternatives. Its `getOrder()` falls back to all groups
when `/Order` is omitted, so a PDF.js-based panel may expose groups in hidden
mode despite the PDF's UI policy.

The songbook site's `@unilarva/pdfjs-viewer` honors the native/hidden UI policy;
that is viewer behavior, not a universal PDF guarantee. Okular may expose native
controls even in hidden mode. It may also show an otherwise ineffective forms
notice: the `pdfbase` backend adds a dummy `pbs@ARFix@N` widget per page as an
Adobe Reader compatibility workaround for annotations on hidden layers. Those
widgets are not transposition controls. Removing the workaround requires separate
compatibility testing.

### Validation and performance

Run the supported containerized suite with `./ulsbs-test`; see the README for
runner options. Renderer regression coverage should include OCG names/counts,
initial visibility, independent radio groups, print usage, actual resource
targets, balanced marked content, and native/hidden switching. Test the real
one-draft/two-full sequence with images, not only small all-full fixtures.

Compare original/default multikey rendering with ordinary output using raster
pixels and visible-text geometry. Raw text extraction can include hidden groups;
mask hidden spans for visible-text comparisons without confusing extraction with
actual renderer behavior. Cover replay, memorization, inline alternatives,
primary/secondary melody, typography arguments, source macro side effects,
bounded scaling and overflow, and ordinary disabled-layer key-aware spelling.
Use an independent degree/alteration oracle for transposition, not only the
implementation's own helper. Validate PDF.js and Poppler behavior in addition
to structural checks.

Earlier validation of the 23-page Transparencia book found identical default-view
pixels on all pages and valid resources for 72 layers. The layered PDF grew by
116,674 bytes (approximately 0.79%). Cached quick builds took roughly 96--101
seconds layered versus 26 seconds ordinary. These historical single-run
observations included different cache work and the former four-versus-three pass schedule;
they are not controlled benchmarks of the new paired-job workflow. Extra jobs
and notation increase total compilation work even when PDF size growth is small.

Paired-edition validation also covered the default, charango, and bass-clef
variants. All visible word positions matched at 0.01 pt precision. Default and
charango each had an 18-pixel raster difference around one superscript on page 8
at 72 dpi; every other page matched exactly. Bass-clef pages matched exactly,
with no visible key-switching effect in that configuration. These small raster
differences must not be reported as strict pixel equality.

The maintained toolchain supplies `ocgx2` through `texlive-latex-extra`. No
separate PDF post-processing tool is required to create the layers.
