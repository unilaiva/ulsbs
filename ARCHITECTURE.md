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

`multikey-books` defaults to `true` and follows normal profile inheritance.
Profiles may override it in either direction, including root `false` to child
`true`. `multikey-layer-ui` is `native` by default and also accepts `hidden`.

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

### Layer protocol

Each song with a valid `\beginsong` `id=` gets twelve optional-content groups.
IDs follow the existing lowercase `[a-z0-9-]+` convention. First occurrences use
`ulsbs:transpose:v1:id:example-song:t00` through `:t11`. Repeating that ID appends
`:o02`, `:o03`, etc. before `:tNN`, for example
`ulsbs:transpose:v1:id:example-song:o02:t05`. Occurrence padding is at least two
digits, not a limit of 99. Different occurrences are independent, even when their
original keys differ. Printed song numbers are never part of this identity.

A private document sequence still identifies TeX/PDF objects, but is not the
exposed layer name or a public song ID. Missing/invalid IDs keep ordinary
notation and skip interactive layers with a warning. Set
`multikey-require-song-ids = true` or pass `--require-song-ids` for strict multikey
validation; ordinary editions are unaffected. ID assignment is an explicit
source-editing preflight, not a compilation-worker side effect.

`t00` is the effective notation after the user's source-level transposition at
that occurrence. `t01` through `t11` add semitone offsets to that notation.
Each song has an independent radio-button group; switching one song must not
alter another. Initially only `t00` is visible. Print usage and automatic-state
policies select original notation rather than the screen-selected alternative.

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
    "schema_version": 1,
    "layer_protocol": "ulsbs:transpose:v1",
    "coordinate_space": "pdf-user-space",
    "songs": [{
      "song_id": "example-song",
      "occurrence": 1,
      "original_key": "Am",
      "key_labels": ["Am", "B♭m", "Bm", "Cm", "C♯m", "Dm", "D♯m", "Em", "Fm", "F♯m", "Gm", "G♯m"],
      "layer_prefix": "ulsbs:transpose:v1:id:example-song",
      "page_index": 5,
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

`has_transposable_content` records actual shipped marked content, not measurement
boxes. It is false for the stock bass-clef setup and other styles that hide every
eligible annotation. A manifest can be present without any usable controls.

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
   `has_multikey_info`, `schema_version`, and `layer_protocol` before using it.
2. For each positioned entry with `has_transposable_content: true`, create a
   selector using `key_labels` or offset labels. Keep repeated occurrences separate.
3. Resolve all twelve exact names `layer_prefix + ":t" + String(offset).padStart(2, "0")`
   against the viewer's optional-content groups. Never assume PDF object IDs equal
   names, and never select by `song_id` or prefix matching alone.
4. Turn on the selected group and turn off the other eleven in that family only.
   Apply the updated configuration to the viewer and rerender affected visible
   pages; songs can span pages beyond the header's `page_index`.
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
// Proceed only for schema_version === 1 and the supported layer_protocol.

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
  // Rerender visible page views using this updated optional-content config.
}

// Use the viewport of pdfDocument.getPage(song.page_index + 1), including its
// current scale, crop, and rotation, for an overlay in that page's view.
const [left, top] = viewport.convertToViewportPoint(song.anchor.x, song.anchor.y);
```

Changing layers does not change scores, TAB, or audio. Printing should use a fresh
`intent: "print"` configuration, not the modified display configuration, to keep
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
scores remain outside interactive transposition. Standalone alternate chord sets
retain their existing authoring/transposition API.

The stock bass-clef post-setup disables chords and pitched hints, which also
hides the key badge. Its multikey edition currently declares layers without
rendering content in them. This is valid optional-content structure, but offers
no visible switching until eligible annotations are enabled. Do not confuse
unused layer declarations with dangling resource references or transpose scores
as a workaround without an explicit change in scope.

Only original notation determines box dimensions, advance, line breaks, and
pagination. Alternative labels are drawn in the original box. Narrower or equal
labels keep their scale; wider labels shrink proportionally, bounded by
`\ulPdfTranspositionMinimumScale` (default `0.85`, valid range greater than zero
and at most one). If that floor is insufficient, labels may overflow without
reflow. Empty/zero-width originals must not cause division by zero. Melody
circles retain their geometry; the pitched glyph changes inside the circle.

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
with the empty-layer limitation described above. These small raster differences
must not be reported as strict pixel equality.

The maintained toolchain supplies `ocgx2` through `texlive-latex-extra`. No
separate PDF post-processing tool is required to create the layers.
