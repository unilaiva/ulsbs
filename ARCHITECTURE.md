# ULSBS Architecture

This reference describes ULSBS internals and implementation contracts. For setup
and compilation, start with the [README](README.md). For song syntax and book
customization, use [Writing Songbooks](WRITING_SONGBOOKS.md).

- [Developer Navigation](#developer-navigation)
- [Song Engine](#song-engine)
  - [Module loading and assets](#module-loading-and-assets)
  - [Reading and documenting runtime code](#reading-and-documenting-runtime-code)
  - [Song and page lifecycle](#song-and-page-lifecycle)
  - [Annotation scanner contract](#annotation-scanner-contract)
- [Index Lifecycle](#index-lifecycle)
- [Fixed Policies and Version Ownership](#fixed-policies-and-version-ownership)
- [PDF Font Sharing](#pdf-font-sharing)
- [Build Diagnostics](#build-diagnostics)
- [Multikey Books](#multikey-books)
  - [Build jobs and publication](#build-jobs-and-publication)
  - [PDF passes and resources](#pdf-passes-and-resources)
  - [Opt-in score layers](#opt-in-score-layers)
  - [Layer protocol](#layer-protocol)
  - [External multikey manifest](#external-multikey-manifest)
  - [Range index protocol v1](#range-index-protocol-v1)
  - [Viewer integration](#viewer-integration)
  - [Notation state and layout](#notation-state-and-layout)
  - [Key spelling](#key-spelling)
  - [Viewer compatibility](#viewer-compatibility)
  - [Validation and performance](#validation-and-performance)
- [Syntax Migration](#syntax-migration)
  - [V1 melody syntax](#v1-melody-syntax)
  - [V2 naming](#v2-naming)
- [Testing](#testing)

## Developer Navigation

The main entry points for extending or debugging the engine are:

| Area | Source |
|---|---|
| Document class and author-overridable styles | `src/ulsbs/assets/tex/ulsbs-songbook.cls`, `src/ulsbs/assets/tex/ulsbs.sty` |
| Instrument-variant post-setup files | `src/ulsbs/assets/tex/` |
| CLI and public configuration | `src/ulsbs/cli.py`, `src/ulsbs/config.py`, `ulsbs-config-example.toml` |
| Build orchestration and jobs | `src/ulsbs/pipeline.py`, `src/ulsbs/jobs.py` |
| Warning parsing and reporting | `src/ulsbs/diagnostics.py`, `src/ulsbs/pipeline.py` |
| Range extraction and validation | `src/ulsbs/multikey_ranges.py` |
| Family installation and deployment | `src/ulsbs/multikey_publish.py`, `src/ulsbs/deploy.py` |
| Score alternatives and persistent cache | `src/ulsbs/lilypond_scores.py`, `src/ulsbs/lilypond_score_cache.py` |
| Shared engine policies | `src/ulsbs/constants.py` |

The executable wrappers are `ulsbs-compile`, `ulsbs-bookmeta`,
`ulsbs-midi2audio`, `ulsbs-ly2tex`, `ulsbs-migrate-syntax-v1`,
`ulsbs-migrate-syntax-v2`, and `ulsbs-test`.
The [README](README.md) documents their author-facing use; release procedures
are in [MAINTAINERS.md](MAINTAINERS.md).

## Song Engine

`ulsbs-songbook.cls` and `ulsbs.sty` are the public entries. Both reject engines
other than LuaLaTeX before font/backend setup. `\NeedsTeXFormat{LaTeX2e}` names
the document format, not a competing engine: conventional LaTeX2e author syntax
and LaTeX3 (`expl3`) implementation coexist under LuaLaTeX.

ULSBS owns song rendering and in-process index generation. Required companion
modules are part of the installation; a missing module is an installation error.
The public compatibility contract is the documented ULSBS authoring API, not
complete feature compatibility with the historical `songs` package.

The package entry owns dependency order and stages configuration before its
consumers. Companion modules hold phase-specific defaults, shared style policy
and runtime implementations; they are private units, not independently loadable
author packages:

| Module under `src/ulsbs/assets/tex/` | Responsibility |
|---|---|
| `ulsbs-package-defaults.code.tex` | Pre-import paper, margin, header and chord-line defaults |
| `ulsbs-init.code.tex` | Public flags, counters, lengths and initial font defaults |
| `ulsbs-book-defaults.code.tex` | Visibility switches, early verse indentation and localized book metadata defaults |
| `ulsbs-style.code.tex` | Final colors, font policy, page headers, boxes and stanza-break styling |
| `ulsbs-utilities.code.tex` | General typesetting helpers, circle measurement/cache, paragraph tracking and repeat loops |
| `ulsbs-typography.code.tex` | Font families, document font defaults, additional languages and Unicode symbols |
| `ulsbs-frontmatter.code.tex` | Cover icons/pages, imprint, TOC and main chapter presentation |
| `ulsbs-boolmap.code.tex`, `ulsbs-chapter-marks.code.tex` | Boolean-map utilities and chapter corner marks |
| `ulsbs-song.code.tex` | Metadata, custom keys, titles, numbering, selection, anchors, lifecycle hooks and once-only index events |
| `ulsbs-layout.code.tex`, `ulsbs-layout.lua` | Song boxes, page/column positioning, break penalties, bottom glue and prose/block adapters |
| `ulsbs-verse.code.tex` | Verse modifiers, source newlines, numbering, indentation and lyric baselines |
| `ulsbs-chords.code.tex` | Token scanning, lyric boxes, chord anchoring, memory/replay and alternate chords |
| `ulsbs-music.code.tex` | Key-aware source transposition, melody composition, meters, bars and repeats |
| `ulsbs-pdf-layer-setup.code.tex` | Early PDF layer registries, occurrence/key metadata, safe chord splitting and shipout hooks |
| `ulsbs-multikey.code.tex`, `ulsbs-multikey.lua` | Effective-original/alternate visuals, key spelling, chord fitting, shipped-page tracking and multikey metadata |
| `ulsbs-diagrams.code.tex` | Guitar diagrams and deferred chord-annotation insets |
| `ulsbs-index.code.tex`, `ulsbs-index-records.lua` | Protected-token serialization, typed deferred page fields and record encoding |
| `ulsbs-index-state.lua`, `ulsbs-index.lua` | Previous-pass snapshot lifecycle, deterministic sorting and generated fragments |
| `ulsbs-index-display.code.tex` | Index display interface, headings, fonts, leaders, wrapping and columns |
| `ulsbs-score-layers.tex`, `ulsbs-score-layers.lua` | Score requests and original/alternative system overlays; Python owns engraving and cache work |

Keep semantic ownership separate from drawing: song metadata/index collection
must not be repeated for each chord or PDF alternative. The scanner accepts TeX
tokens and catcodes, not expanded lyric strings. It keeps groups, source spaces,
comments and physical newlines meaningful and typesets each lyric fragment once.
Chord fitting and syllable extension measure the retained box. The effective
original annotation is authoritative for dimensions; alternatives contribute no
layout geometry. Full-score transposition belongs to Python/LilyPond, not this
scanner. The [authoring guide](WRITING_SONGBOOKS.md#chords) and
[scanner contract below](#annotation-scanner-contract) specify source forms.

LaTeX owns the page builder and one/two-column output. ULSBS positions completed
song boxes using copied-node fit probes; probes must not execute source or
deferred writes again. `ulsbs-layout.lua` exposes the private `ulsbs_layout` Lua
bridge for these layout operations. `\ulSongColumns` accepts 0 (unpositioned flow),
1 or 2; `\ulSongPosition` accepts 0 through 3. Preserve scoped settings, physical
verse-newline paragraphs, explicit `\par` semantics and break penalties. Do not introduce a
private output routine merely to mimic historical invisible PDF operators.

Public extension points are documented class/pre-load options, fonts, lengths,
setters, `\ulNewSongKey{key}{reset}{set}` and the argument-free LaTeX hooks
`ulsbs/song/begin`, `ulsbs/stanza/start`, `ulsbs/stanza/finish`,
`ulsbs/song/finish`, `ulsbs/index/record` and `ulsbs/song/anchor`.
Metadata reset callbacks run before option parsing; set callbacks receive `#1`.
Hooks execute in their current song/stanza scope, not once per key alternative.
The anchor hook inserts nodes; physical positions are only known at shipout.
Selection can discard a song box after its hooks ran. Source occurrence counts
can therefore include discarded material, whereas index events only commit from
retained shipped boxes. Custom fields do not automatically extend JSON schemas.
Private `\__ulsbs_...` state and Lua tables are not public extension contracts.

### Module loading and assets

The entry first checks the engine and requires `expl3` directly. After
`etoolbox`, `ulsbs-package-defaults.code.tex` supplies pre-import settings;
`geometry` consumes the paper and margin values during import. The other imports
precede `ulsbs-init.code.tex` and its initial public font measurements.
PDF option defaults, validation and the optional `ocgx2` import stay in the entry; the
second-phase registries and scanner load from `ulsbs-pdf-layer-setup.code.tex`
immediately after `\makeatletter`. Main-language selection precedes
`ulsbs-utilities.code.tex`, which loads boolean maps at its end.
`ulsbs-book-defaults.code.tex` follows those helpers: localized book defaults use
`\ulIfLanguage`, and the initial `1em` verse indent is captured before typography.
Typography loads after the PDF color-profile setup and before
`ulsbs-style.code.tex`; that style phase loads chapter marks after TikZ calc,
chapter colors and dimensions. Front matter loads after shared styles and before
song-content helpers. These common styling, notation and PDF helpers precede the
ordered subsystem owners: index serialization/state/
sorting, song lifecycle, layout, verses, chords, music, multikey, diagrams, then
index display. The module table above is an ownership map, not a replacement for
this dependency order.

Do not gather all inputs at the top or turn the phases into a single early
configuration block. Pre-import values are consumed immediately; initial
font measurements must precede typography; final visual policy intentionally
overrides some early hooks. Subsystem-specific settings remain beside
their implementations when moving them would obscure evaluation timing or change
allocation/measurement order. In particular, passage indentation captures `em`
later than the early verse-indent default, and prelude title metrics run after
the final title-font policy.

Consumer overrides follow the declaration's contract, documented inline:
pre-load `\providecommand` defaults accept an earlier `\newcommand`, while
post-load macro hooks use `\renewcommand`. Use `\setlength` for lengths, integer
assignment for penalty counts, and explicit boolean setters such as
`\ulShowTags{false}` with real predicates such as `\ifulShowTags`. A later macro
change does not retroactively reconfigure an already-loaded package, captured
dimension or published PDF metadata. Private default files are not consumer
configuration files to input directly.

Companion `.code.tex` modules load without an extra TeX group. The style owns
`\makeatletter`; modules must restore syntax, grouping and active-character state.
Private functions use `\__ulsbs_...`, package-internal interfaces use
`\ulsbs_...`, and typed variables follow expl3 conventions. Keep consumer source
LaTeX2e-style and expose documented settings rather than mutable internal state.
New annotation forms need scanner and once-only source-effect tests; new index
letters need verified weights, diagnostics and sorting tests, not locale fallback.

`prepare_compile_dir()` stages the TeX tree; `TEXINPUTS` and `LUAINPUTS` resolve
companions. Setuptools package data and `MANIFEST.in` include `.code.tex` and
`.lua` assets. `build.lua` installs all top-level `.tex` and `.lua` companions,
including score layers and edition postsetup files. Installed books must resolve
these assets without a source checkout, upstream songs or an external indexer.
`keyval`, `etoolbox`, `environ`, `expl3` and `xparse` remain used dependencies.

### Reading and documenting runtime code

Start with a module's header: it describes its load site, prerequisites and state
ownership. Comments above functions describe arguments, results and effects;
comments inside them explain ordering, expansion or node-ownership constraints.
Keep those comments current when changing code. In particular, distinguish source
evaluation from measuring/copying retained boxes and from deferred shipout work.
Private modules share the package scope; moving a definition to a companion does
not make its state local or its dependencies independently loadable.

TeX whitespace is executable input: `%` suppresses the rest of its line including
the newline, while a blank line can produce `\par`. Tokenization also depends on
whether `\ExplSyntaxOn` or active-character catcodes are in force when a definition
is read. Preserve those boundaries when adding comments or moving code; keep
module inputs at their dependency sites rather than alphabetizing them.

Most engine TeX functions use expl3 names. The text before `:` names the operation;
the suffix describes its arguments: `N` is one unexpanded token (usually a
variable or function), `n` is an unexpanded token-list argument, `V` takes the
contents of a variable, `c` constructs a control-sequence name, and `x`/`e` expand
an argument. Generated variants adapt argument handling without changing the
underlying operation. Conditional forms ending in `T`, `F` or `TF` take the
corresponding true/false branches after their ordinary arguments. Variables use
`l_` for local working state, `g_` for globally maintained state and `c_` for
constants; the final component gives the type (`tl`, `seq`, `prop`, `dim`, `box`,
and so on). Assignment commands still determine the actual scope. Older drawing
and style helpers use LaTeX2e names with `@` instead of expl3 names; both styles
are private unless the authoring guide documents an extension point.

Private companions use `\ProvidesFile{filename}[Short description]`: retain a
short purpose description in the log and `\listfiles` output, but omit dates and
per-file version numbers. Git records edit history; private companions are shipped
and loaded together, not selected by per-file date comparisons. This declaration
does not load a file or prevent a second input. LaTeX also permits an omitted
identification string or a conventional date/version-prefixed string, but ULSBS
private companions consistently use description-only brackets.
For the LaTeX identification and loading interfaces, see the
[class/package writer's guide](https://www.latex-project.org/help/documentation/clsguide.pdf).

### Song and page lifecycle

`ulSongs`, `song`, `\beginsong` and `\endsong` use the same semantic lifecycle,
including the three-braced metadata form. Each `ulSongs` block starts printed
numbering at 1; chapter headings do not reset it. Counter overrides and
`\theulSongNumber` formatting are independent of persistent IDs and occurrences.
Metadata resets execute once before option parsing. Public metadata remains
available after `\endsong` in the surrounding scope; unknown fields and malformed
or nested lifecycles have owned diagnostics. Titles split only on top-level
`\\`; `\ulResetTitles`, `\ulNextTitle` and `\ulForEachTitle` iterate them. Accidental
catcodes change after title scanning, allowing raw `#`/`&` in musical key fields.

Selection activation is distinct from its list: absent selects all; explicitly
empty selects none. Retained boxes submit in requested printed-number order
without renumbering. Index, PSV and TOC writes stay in those boxes; discarded
boxes do not leak records. Intentional repeated selections get shipout replay
markers without evaluating source or hooks again. ID anchors are
`songid:<id>[-n]`; index targets separately use
`song<block>-<printed-number>.<outline-level>`. ID and number freeze at collection;
physical page and Y resolve at shipout. Only occurrences with transposable ink
enter the multikey manifest.

The body typesets before prelude/postlude, then assembles below the retained
prelude. Attributions compose once in a retained horizontal box and unpack for
paragraph layout. Badge widths measure in the title font; the save-position
marker stays at the title box's right edge. Initial public chord-font metrics
precede the shared document font policy. Preserve these boundaries to avoid
font-first-use or anchor changes without replaying source.

Positioning dry-splits copies of completed boxes against actual page contributions
and finite stretch/shrink, then submits real material once. Pending owned
continuations remain distinct from ordinary prose, even after the first page
ships. Empty-page lookahead retains even/odd spread reservations. Song clears use
the saved kernel clear locally, independent of an author's temporary include-clear
override; standard kernel column output stays untouched.

Column settings preserve grouping. Selection-time shaping must not change the
physical page mode; retained boxes submit under restored settings, and environment
exit restores the entry mode. A one-shot retained prefix places full-width
material above a two-column start without executing headings again. Intersong
top skip and outer stretch remain separate from internal column stretch.

The verse owner handles physical newlines, comments, groups, arguments, literal
spaces, modifiers, numbering, hanging indentation and one-shot stanza glue.
Implicit final lines close before local paragraph settings restore. Caller depth
survives stanza boxes; independent body boxes reset interline depth. Notes/prose
distinguish in-stanza, between-stanza and outside-song contexts. An attached note's
`\ulBreakPenalty=\ulVerseVersePenalty` lasts for the rest of the song scope;
glue requested before the first stanza waits for a real boundary. Block counters, alternate
colors and song-local settings reset at song end.

### Annotation scanner contract

The scanner reads TeX tokens without expanding lyric text. The first ungrouped
`]` closes `\[...]`; balanced braces, slash basses, accidental macros,
superscript/subscript typography, kerns and spaces remain tokens until typeset.
`\ulChordLocals` supplies parenthesis typography. Sharp/flat shorthand is active
only in notation scopes; escaped characters retain normal LaTeX meanings. The
[melody grammar](WRITING_SONGBOOKS.md#melody-hints-and-beat-marks) permits one
leading primary/secondary block per annotation. Separate blocks require adjacent
annotations.

A lyric fragment ends at a source space, another annotation, replay mark,
paragraph/group end or non-lyric command. An explicit `\endgroup` ends a word.
A literal closing brace first closes the authored group; the following token
determines continuation and alignment hyphenation. Closing a local `\noteson`
group before replay must not silently end that lyric word. Balanced groups and
declared lyric commands remain intact. Lookahead does not expand explicit spaces,
ties, accents or escaped punctuation. A hyphen run ends the fragment: a single
hyphen may serve as its alignment hyphen, while multiple hyphens stay literal.

The retained lyric box supplies fitting, syllable-extension and wrapping metrics;
measurement never typesets the source again. Adjacent annotations concatenate.
Each visible annotation immediately followed by literal whitespace independently
gets the configured minimum advance; hidden or zero-advance melody must not gain
that width. Disabling chords or measures uses ignored catcodes for the relevant
replay/bar characters. Invisible active macros are not equivalent: they separate
source spaces. Echo arguments rescan once while retaining active physical
newlines. A leading explicit bar already tokenized by stanza lookahead retains
the pending meter even in a true-lyrics edition; later toggles update scoped ink
state. Explicit `\par` has ordinary paragraph costs, distinct from the source
newline handler and its penalty.

Chord registers store raw annotations rather than rendered boxes. Each stanza
starts on the default register: the first records, later stanzas replay, and the
default resets per song. `\newchords` declares a named register;
`\memorize[name]` clears and records it, `\replay[name]` selects and rewinds it,
and bare `\replay` rewinds the current register. Replay interprets tokens using
current transposition, note visibility and melody styles. Unknown registers and
exhausted replay are errors. A leading `^` inside an annotation excludes it
while recording; while replaying, it consumes the next saved annotation inside
the same box without another lyric scan. Saved melody takes precedence over a
new prefix; extra chord-tail tokens remain unexpanded until rendering.

Source transposition and interactive offsets are separate. `key=` describes the
effective printed original; `t00` preserves that notation and alone supplies
dimensions. Eleven alternatives add visual ink with zero advance. Authored brace
groups remain opaque to transposition. Shared notation-side effects execute once,
not once per layer. Full-score transposition stays in Python/LilyPond.

## Index Lifecycle

The renderer stages semantic title, alternate-title, author and tag events.
The required `ulSongs` comma list is scoped routing for automatic records; `{}`
means none, while explicit `\ulIndexEntry[identifier]{...}` and
`\ulIndexTitleEntry[identifier]{...}` can override that routing. Repeated IDs
accumulate across blocks; separate destinations require separate declared IDs and
filename stems. Printed numbering restarts at 1 per block, independently of index
accumulation; counter and `\ulIndexSongsAs` label overrides remain available.
The package-declared IDs `titleidx`, `authidx`, and `tagidx` are not filename stems
or reserved keywords. `\ulNewIndex{id}{stem}` declares title destinations,
`\ulNewTagIndex{id}{stem}` tag destinations, and `\ulNewAuthorIndex{id}{stem}`
author destinations. Default title/author/tag stems are `idx_title`, `idx_auth`
and `idx_tag`.
Identifiers and reference labels freeze at collection; typed page-dependent data
resolves at shipout. Numeric handles in late-Lua nodes commit an event once,
including when boxes are copied; discarded boxes contribute no records.
`ulsbs-index-records.lua` serializes UTF-8 fields as byte-length-prefixed data
under the signature `ULSBS index records 1`, not executable Lua or TeX source.

At package initialization, `ulsbs-index-state.lua` loads the completed previous
`<jobname>.ulsbs-index-state` before a new collection can overwrite it. The
signature `ULSBS index snapshot 3 fi-compatible-v1` identifies the current schema
and collation policy; the snapshot records job/source identity, declarations and
events. These generated formats are current scratch build outputs, not historical
baselines or public interchange formats. There is no historical-format reader;
incompatible outputs must be cleared and regenerated.
A checksum detects accidental corruption, not malicious input. The source
fingerprint covers the file active at `\begin{document}`, not the entire input
graph; exact end-of-pass record comparison detects other source changes affecting
requested indices. Begin-document marks collection in progress, and finalization
after the last page atomically installs a complete snapshot by temporary write
and rename. Aborted, foreign, malformed or incompatible snapshots are errors with
recovery instructions, not silently reusable caches.

`\ulShowIndex` requests a title/author/tag fragment generated from that prior snapshot.
It renders the entire destination, not only songs preceding the call; placing it
before or between blocks does not partition the index.
The first pass warns and collects; it cannot display a final generated index.
Changed displayed/collected records request another LuaLaTeX run. The compiler
recognizes this warning and refuses publication if its bounded extra-pass budget
does not converge. There is no `songidx.lua`, `texlua`, `makeindex` or `xindy`
stage. Generated `.sbx` display fragments are bound to exact job-local paths and
cannot be shadowed by stale files on `TEXINPUTS`. Nonempty fragments are generated
only for requested destinations. Empty title/author/tag declarations
normally get empty fragments to clear stale results; the existing `ul-selection`
jobname convention suppresses unrequested empty fragments. `\nofiles` is invalid
when requesting generated indices. Manual parallel builds need separate output
directories, just as for `.aux` files.

Requested tag indices default to `include/tags.txt` first, then `tags.txt` through
TeX/kpse lookup. The preamble-only `\ulTagFile{filename}` setter selects an explicit
TeX-lookup filename; a missing configured file fails without default fallback.
Definitions are ordered UTF-8 plain text, one `canonical|alias|alias` line per tag,
with surrounding whitespace trimmed and blank/full-line `#` and `%` comments
ignored. There are no count lines, numbered scripture references or runtime
legacy `.can` parser. Automatic tag records come directly from `tags`/`\ulTagList`;
the inherited `sr` field, `\ulSongRefs` accessor and three-braced song metadata
adapter have been removed. Generated tag rows have empty entry text (`{}`)
because the heading carries the tag name. `\ulIndexTagFont` styles tag headings.
Missing definitions and unknown/malformed tags are actionable errors.
`\ulSongIndexes{false}` disables display and collection; `\ulShowTags{false}` hides
prelude badges only. Unrequested tag indices need no definition file.
Author destinations, including `\ulNewAuthorIndex{writers}{idx_writers}`, use the
same snapshot, request, empty-cleanup, output-directory and rerun lifecycle as
titles and tags. `by={Alice Smith, Bob Jones}` supplies raw author events;
`\ulShowIndex{Authors}{authidx}` generates `idx_auth.sbx`. No manual fragment or
external indexer is required. Old hand-authored `idx_auth.sbx` is not a runtime
fallback: generated stems may be replaced or cleared. Preserve valuable authored
fragments under separate filenames outside generated stems.

Author parsing splits top-level commas, semicolons and standalone
case-insensitive `and`. Braced groups and TeX arguments protect commas and
separator words; TeX control symbols are protected. A standalone default `by`
marker retains text after its last occurrence in each attribution segment.
Hyphenated and apostrophe-joined words are not standalone markers. Names stay as written, with no
surname or role inference; formatting survives in entries and
`\ulIndexAuthorFont` is unchanged. The first `\ulAuthorSepWord` or
`\ulAuthorByWord` replaces its respective default word list, later calls add
words, and an empty first call clears the default. Separator/attribution values
must be single alphabetic words or empty. `\ulAuthorIgnoreWord` matches
whole cleaned candidates case-insensitively, not substrings. Like title-prefix
settings these are global stream directives affecting following record events
only, regardless of TeX grouping. Directives enter the stream when TeX executes
their commands, while song records commit at shipout. Lexical source order alone
therefore does not determine their relative event order; configure parsing policy
in the preamble rather than relying on mid-document changes or grouping.
Empty author fields add nothing; duplicate names are removed within each raw
author event, not across events, preserving repeated selection links. Identical
display names group their references in event order.
Author entries use deterministic Finnish-compatible/natural collation without
visible letter heading panels (the author `ulIndexBlock` suppresses the heading).
Author generation uses the same snapshot schema 3 and record codec 1.

`ulsbs-index.lua` owns finite, explicit Finnish-compatible collation weights and
natural numeric tokens, independent of host locale and Lua byte ordering. Tests
cover A to Z followed by ring-A/umlaut-A/umlaut-O, accented Latin, tested Sanskrit
transliteration and Persian title letters, case/punctuation, numeric prefixes
(including Finnish decimal commas), aliases and duplicate reference order.
This is not complete Unicode collation or normalization. An unverified character
reports its code point and requires a reviewed table/test extension; changing
`LC_ALL` is not a solution. Tag group order remains the definition-file order.
Index labels and chapter context are independent of persistent IDs, occurrence
identities and physical multikey range offsets.

The pure sorter exposes `render(records, kind, definitions_bytes)` and
`normalize_title(text, prefixes)`. Normalized records hold the already
article-rotated title, label, target, ordinal and diagnostic line. Title rendering
sorts records in place; duplicate references and tag groups retain input order.

## Fixed Policies and Version Ownership

`src/ulsbs/constants.py` owns these fixed engine policies. They are not TOML,
environment, or CLI settings:

| Constant | Value | Purpose |
|---|---|---|
| `LILYPOND_SCORE_MIN_SCALE` | `0.60` | Minimum uniform fit accepted for an alternative score image |
| `MULTIKEY_MIN_QPDF_VERSION` | `(12, 2, 0)` | Minimum supported qpdf version, in addition to runtime output validation |
| `LUALATEX_MAX_EXTRA_PASSES` | `2` | Shared extra-full-pass budget for reference and optional-content convergence |
| `MULTIKEY_INDEX_MAX_BYTES` | `4 * 1024 * 1024` | Protocol-v1 bound on the entire UTF-8 index, including its manifest |

These policies differ from public configuration such as
`multikey-min-chordname-scale`, `multikey-max-pages-per-range`, and
`multikey-target-max-range-bytes`. The score-image fit floor is not a creator
knob, and the chord-name setting does not alter it. Internal fitting policy can
change in future engine builds; its value participates in score-cache identity
and generated TeX bindings so that cache validation and rendering agree without
manual cache clearing. The index size bound is instead a producer/consumer
format agreement, not a PDF-size limit or viewer memory budget. Raising that
bound requires consumer agreement; merely changing an engine constant is not a
compatible format migration.

Keep module-owned protocol, cache schema, and transformation-semantic versions
near their owners rather than hoisting them into `constants.py`.
`multikey_ranges.py` retains `PROTOCOL`; `lilypond_score_cache.py` retains
`SCHEMA_VERSION` and `IMPLEMENTATION_VERSION`. Their version changes have
different compatibility or cache-invalidation meanings from a fitting threshold
or tool-version floor. Cross-component policy is shared; local version identities
remain local.

## PDF Font Sharing

All published jobs run `pipeline.py:step_pdf_fonts` after the final
LuaLaTeX pass, before publishing the job PDF to `result/`. The step calls
`pdf_fonts.py:deduplicate_fonts` on the canonical job PDF, so publication,
printouts, and cover extraction all consume the same validated artifact. It also
runs for quick builds, ordinary editions of every variant, and supported multikey
editions. Multikey jobs first validate their final-pass metadata; disabled
companions are still skipped before
optimization or publication. LilyPond generation, the processed source tree,
MIDI/audio associations, and JSON export contracts are unchanged.

Font sharing is always enabled. `pikepdf>=10` is a required compiler dependency,
with its installed version checked before compilation even when there are no scores
or duplicate fonts. The container installs `python3-pikepdf`; host installation
and image-rebuild instructions are in the [README requirements](README.md#requirements).
No external optimizer executable is required. Syntax checking uses
`Pdf.check_pdf_syntax()` directly.

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
and media mappings. Multikey integration checks the external manifest and all twelve
key selections, requiring both identical baseline/candidate pixels and visible
differences between key selections. Rendering comparisons are regression checks,
not part of every production build's runtime validation. Savings depend on exact
duplication; substantial distinct-subset overhead may remain.

## Build Diagnostics

`src/ulsbs/diagnostics.py` parses source-aware `Diagnostic` records with a message,
category, log path, occurrence count and optional affected-item count. Multiline
continuations form one record; whitespace-normalized identical messages are
grouped with their occurrence counts. Job warning totals sum occurrences, not
distinct messages, log lines or raw matches of the word "warning". Callers with
artifact-level knowledge may attach `affected_count` (for example, eight songs
missing IDs); that count is separate from the warning total. Compact output
aggregates by source/category; verbose output shows messages and occurrences.

`pipeline.py:analyze_warnings` collects selected tool logs, including LilyPond,
and only the final LuaLaTeX invocation, not superseded typesetting passes.
Convergence reruns respond to specific recognized requests in the latest TeX log,
not arbitrary warnings. Closing TeX reference/font recaps are suppressed only
when their corresponding specific warnings occur in the same parsed text.
Missing glyphs and overfull boxes count as warnings; underfull boxes are
informational. Configuration, resource and cleanup advisories remain separate
from per-job warning totals.

Recognition of warning headers is distinct from message categorization: unfamiliar
messages matching supported TeX or generic tool-header patterns are retained
without a message whitelist. Messages with no more specific category use `other`
and display as unclassified warnings. A header format outside all supported
patterns requires a parser extension; category-specific wording is not required
merely to count an otherwise recognized warning.

`tests/test_diagnostics.py` covers multiline grouping, recap suppression, header
recognition and informational boxes. `tests/test_compiler_reporting.py` covers
final-pass selection, affected-item metadata, unknown messages and summaries;
`tests/test_reference_convergence.py` covers rerun recognition and unrelated
warnings that must not trigger retries.

## Multikey Books

### Build jobs and publication

`Job.variant` identifies the default, lyrics-only, or instrument variant;
`Job.multikey` is a separate boolean selecting the multikey edition. Each
selected variant has an ordinary job. Currently, only default and instrument
variants also get a multikey job when `multikey-books` is enabled. Lyrics-only
variants remain ordinary-only; this is a generation restriction, not a different
level in the variant hierarchy.
The existing `ULSBS-EXTRA-VARIANTS` comment selects instrument variants.

Ordinary and multikey compilations run independently in the same bounded
worker pool, including for a single book. `compile_one_job` returns a
`CompilationResult` containing its warning count and next numbered step;
multikey compilation leaves the optimized master private and does not yet
report job success. Once both matching compilations succeed, including ordinary
media and JSON export, the coordinator submits `finish_multikey_job` to that
same pool. It calls `step_multikey_ranges` to read the final-pass sidecar,
extract and validate ranges, copy the family to `result/multikey/` with the index
last, and update the ordinary JSON reference. Only then is the multikey job
successful. Failed compilations prevent publication, and a missing ordinary
edition fails its companion without starting it.

There is no global end-of-build packaging barrier: ready pairs can publish while
unrelated compilations continue. Pool capacity still bounds active work, and
workers never wait on other jobs, including with a single worker. Each phase
uses the existing per-job lock; packaging reacquires it after compilation. No
shared manifest-payload sink or additional locking mechanism is required.

The queue rejects duplicate publication paths before starting jobs: independent
locks cannot prevent two sources/editions from overwriting the same artifact.
Ordinary jobs reserve their PDF and optional `json/` export paths. Multikey jobs
reserve `multikey/<stem>_RANGES.json` regardless of `cfg.json`; that mandatory
index owns the whole range family, not a full PDF or a companion JSON export.

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

`build_job_basename` first applies `build_variant_basename` with the ordinary
musical variant, then appends `_MULTIKEY` after the complete ordinary stem.
The same stem identifies the index and its range family:

| Variant | Ordinary result | Multikey entry point |
|---|---|---|
| Main | `Book_A5.pdf` | `multikey/Book_A5_MULTIKEY_RANGES.json` |
| Charango | `Book_CHARANGO_A5.pdf` | `multikey/Book_CHARANGO_A5_MULTIKEY_RANGES.json` |
| Bass clef | `Book_BASSCLEF_A5.pdf` | `multikey/Book_BASSCLEF_A5_MULTIKEY_RANGES.json` |

Ordinary PDFs remain at the `result/` and deploy roots. Only the entry point and
range PDFs are published in their respective `multikey/` subdirectories. For
example, `Book_CHARANGO_A5_MULTIKEY_RANGE_1-50.pdf` is a range, not a full book.
The full layered PDF remains a temporary extraction source and is never a
published dependency. There is no full-book multikey JSON companion in `json/`.
Ordinary JSON exports remain there with existing media/path conventions.
New book/variant metadata emits `multikey_json_file` referencing the completed
index, never the old `multikey_file`, and omits it when multikey is disabled.
Generated ordinary `book_info.multikey_json_file` is result-root-relative
(`multikey/Book_A5_MULTIKEY_RANGES.json`); website catalog variant values remain
basenames resolved against the site's multikey directory.
Multikey jobs never generate printouts, MIDI, audio, or cover images.

`multikey-max-pages-per-range` defaults to `50` and
`multikey-target-max-range-bytes` defaults to `33554432` (32 MiB). Both require
positive TOML integers, reject booleans/floats/strings, accept dashed or
snake_case keys and follow existing file/profile inheritance. They do not
enable multikey themselves. The index is mandatory even with JSON export off.

Split nominal page intervals by physical pages, not songs. Extract from the
unchanged master, measure actual bytes and bisect oversized intervals until
they fit or contain one page. Warn for a single oversized page but retain it
with its true size. Every enabled package has at least one range, including
small books and empty song collections with a cover; zero-page output fails.

Packaging uses `constants.py:MULTIKEY_MIN_QPDF_VERSION` as its tool-version floor
and supports the bundled Ubuntu qpdf 12.2.0 without upgrading it, plus runtime
qualification of every output. Host evidence also uses 12.4.2; a version
floor alone does not prove correct catalog, resources, geometry or link preservation. Record the
actual version in the index. Use argument arrays equivalent to:

```sh
qpdf "temp/Book_A5_MULTIKEY.pdf" --deterministic-id --pages . 1-50 -- "staging/Book_A5_MULTIKEY_RANGE_1-50.pdf"
qpdf --check "staging/Book_A5_MULTIKEY_RANGE_1-50.pdf"
```

Do not substitute `--empty --pages` or `--split-pages`: the tested shortcuts
lost the OCG catalog. Keep all twelve exact layer names, View/default states,
fixed layers, font/image/resource closure, vector/text content, transparency,
page boxes, rotation and UserUnit. Retaining unused global OCG declarations is
acceptable; retaining unrequested page objects or most of the master is not.
Successful qpdf syntax checking alone does not establish equivalent appearance.

Compare effective printed page labels after qpdf rebases their number tree.
Preserve the existing read-only PGF workaround widgets and their appearance
resources; only off-range widgets disappear from the extracted AcroForm field
list. Editable forms and unsupported actions fail packaging. Hyperref's initial
GoTo view is not a Link annotation: when it points outside the range and qpdf
has replaced only that target page with null, remove the invalid startup action
using structured PDF tooling. This expected range normalization is quiet;
unexpected action changes still fail validation. Do not remove useful links,
outlines, or their appearances to avoid retained-page/resource validation.

The Ubuntu integration tests compile generic LilyPond content, deduplicate fonts
before extraction, and compare all twelve selected keys against the optimized
master. Cold and warm measurements with qpdf 12.2.0 were identical: 148400-byte
baseline master, 105781-byte optimized master, and two one-page ranges of 93708
and 101920 bytes. Each range independently embeds the needed Noto Sans and
Emmentaler fonts. These are qualification fixtures, not a real-large-book size
or mobile-memory guarantee; shared resources can increase the aggregate bytes.

A separate private 462-page build was qualified with qpdf 12.2.0 after the
long-header anchor regression was fixed. Its ordinary PDF was 21659093 bytes,
optimized layered master 41755668 bytes, and index 130563 bytes. Ten ranges
(50-page nominal limit, final 12-page range) measured 723080 to 11962236 bytes,
all below the 32 MiB target. All 1573 named destinations matched the ordinary
PDF exactly. Only measurements are documented here; no private music or PDFs
are included in public fixtures or release assets.

Validate ordinary/intermediate identity and geometry, the finalized manifest,
all staged range resources/layers/links, exact coverage, and final hashes before
publication. Publish ranges first and the index last, then metadata referencing
that complete package. Follow failed-build policy without a misleading partial
index, stale-package fallback or full-PDF fallback. Clean obsolete generated
ranges only from the build's own inventory, never unrelated files.

`multikey_publish.py:publish_package` revalidates the complete staged index,
range sizes/hashes, and paired ordinary PDF before changing destinations.
It copies through destination-local temporary files, retains byte-identical
outputs, and installs ranges before the index. Replaced files and obsolete-range
deletions have backups; installation exceptions, including interrupts, trigger
rollback. Cleanup recognizes only safe range basenames from that edition's
previous index, not neighboring files. Unreadable or oversized old inventories
conservatively leave orphan ranges rather than authorize a directory sweep.

Deployment preflights package identities before copying anything and can include
the paired ordinary PDF in the same rollback boundary. Result-list records and
ordinary JSON references remain the caller's responsibility. Index-last ordering
and rollback do not provide atomic multi-file visibility to concurrent HTTP
readers. A live site needs an atomic edition-directory deployment for a consistent
ordinary-PDF/index/ranges snapshot. The packager rejects unsupported numeric or
direct-page Link destinations rather than attempting automatic normalization;
the protocol's permitted normalization is not an implemented fallback.

Multikey jobs suppress even intermediate LilyPond MIDI generation, not merely
its publication. Ordinary editions of non-default variants suppress that MIDI
include only when neither MIDI export nor audio export is actually enabled for
the variant. Each export requires both its general feature flag and its
respective `midifiles-allow-for-optional-variants` or
`audiofiles-allow-for-optional-variants` opt-in. `--no-midi` and `--no-audio`
independently disable their respective exports even when an optional-variant
opt-in is set. The default variant's ordinary edition retains its original MIDI
include.

With opt-ins, both MIDI copying and audio encoding resolve
`song.midi_compile_file_relative` against that job's `compile_dir`, consuming
variant-local MIDI rather than reusing the default variant's files. Usual defaults
export media only from the default variant's ordinary edition. Audio-only export
still needs intermediate MIDI and the internal song metadata database, even with MIDI and
JSON exports disabled. `--no-midi` suppresses published MIDI files, not the
intermediate MIDI required by enabled audio; the metadata database is built when
JSON, actual MIDI export, or actual audio export needs it. LilyPond processing and score
engraving remain active for all jobs, including lyrics-only output; only the
job-local MIDI include is suppressed under the conditions above.

The pipeline defines `\ulPdfTranspositionLayers`, `\ulPdfTranspositionLayerUi`,
and `\ulPdfTranspositionRequireSongIds` before loading the class/package.
Layers are `true` only for multikey jobs and `false` for ordinary and lyrics
jobs. Manual LaTeX compilation defaults to layers `false` and UI `native`.
Manual builds may define `\newcommand{\ulPdfTranspositionLayers}{true}` before
class/package loading; pipeline-driven sources must not duplicate its definitions.

A companion candidate whose source initializes lyric-only mode or does not load
the renderer explicitly reports disabled capability. It is skipped without
publishing an ordinary PDF under a multikey name. This is different from an
enabled renderer whose valid songs currently hide every annotation.

### PDF passes and resources

Jobs normally use three LuaLaTeX passes: one draft followed by two full passes.
Requested title/author/tag indices are generated inside LuaLaTeX from the preceding
pass's song records, without a separate index process. The draft collects
the first complete snapshot; the first full pass renders it and the second full
pass settles references/resources. Index rerun requests share the existing bounded
convergence budget and must settle before publication.
See [Index Lifecycle](#index-lifecycle) for the snapshot contract
and [manual builds](WRITING_SONGBOOKS.md#manual-lualatex-builds) for direct TeX use.

In engine `-draftmode`, MULTIKEY builds construct only the original (`t00`)
visual boxes. These alone determine width, height, depth, and page breaking;
eleven zero-extent alternate chord/key/score boxes would be discarded without
producing a PDF. The draft still registers all layer groups, measures headers,
collects all twelve target keys, and writes the original score requests and index
data. Full PDF-producing passes always construct every alternative. This private
renderer flag follows LuaTeX's `\draftmode` parameter, not the document's
`draft` option or the graphics package's placeholder mode.

Draft mode omits image objects. Consequently, PDF object numbers recorded in a
draft run cannot safely describe final optional-content page resources. The
second full pass resolves resources against the preceding full run. This also
keeps the final reference-resolution pass consistent for ordinary books. Manual
layer-enabled builds must likewise rerun full, non-draft LuaLaTeX until
references settle; counting draft runs as equivalent is unsafe.

Before font deduplication, all jobs inspect the latest completed TeX log for
explicit LaTeX/rerunfilecheck/hyperref/lastpage reference-rerun requests.
Ordinary warnings, package-loading text, and undefined references without an
explicit rerun request retain their existing policy. MULTIKEY jobs additionally
inspect page and nested Form property resources without decoding their drawings.
If a cached reference resolves to a stream or another non-dictionary, or the log
requests another pass, rerun only LuaLaTeX. Both checks share the
`constants.py:LUALATEX_MAX_EXTRA_PASSES` budget (two additional full passes),
stopping as soon as they settle. This does not repeat
LilyPond engraving; in-process index collection/display still runs on each
LuaLaTeX pass. The latest log and fresh shipout manifest
remain authoritative. Persistent failure stops the job; the later complete
layer/resource validation is never bypassed. A generic regression changes object
allocation across three passes and verifies recovery on a fourth. A separate
ordinary-book test checks TOC, generated song index, and named page references:
pass-three and pass-four text geometry and destination coordinates match.

A read-only audit of one retained corpus run found no final reference-rerun
requests in 33 ordinary editions (12 still requested a rerun after pass two).
Only two of 33 MULTIKEY editions had invalid property resources: the verde and
completa bass-clef editions. Default completa passed. These observations are not
a guarantee about future inputs or a rule based on book size.

Each completed numbered LuaLaTeX log includes `ULSBS wall time` for that command.
Private `*.ulsbs-score-results.json` diagnostics separately record
`elapsed_seconds` for between-pass score generation/cache work. These are wall
times, including scheduling contention, not isolated CPU measurements. They do
not enter the published manifest or change its reproducibility.

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
is no Python parser for raw song-key strings or dedicated request-collection pass.
The effective-key policy currently supports major/minor keys; unsupported modal
metadata remains original-only rather than being reinterpreted as another key.
Between draft and full
passes, Python engraves supported alternatives and writes
`<job>.ulsbs-score-variants.tex` plus `<job>.ulsbs-score-results.json` diagnostics.
Stale dispatch/request files are cleared before draft collection. Preparation
writes a policy-only bindings header for that first pass; generation replaces it
with the same policy header followed by accepted variant dispatch definitions.

Recognized head/tail snippets and narrowly matched explicit named-variable score
assemblies are eligible, including contiguous duplicate identical headers.
The supported assemblies retain their named lyrics, fixed octave shifts, grouped
staves, numeric engraving settings, and original layout. Additional unknown
includes, arbitrary score expressions, and multiple explicit score blocks remain
fallbacks. `\transpose` assignments are inserted before the tail or score
assembly consumes the already-defined music variables. Structured `ly:make-pitch` operands avoid
interpreting generated intervals under a source's custom note-name language.
The shortest signed interval is tried first, then its opposite-octave equivalent
on failure. For positive shortest intervals, a third candidate one octave above
the preferred interval covers high/reentrant instrument tunings. Negative
shortest intervals already receive an upper candidate on the second attempt.
Every system PDF must be valid and fit both original dimensions at a
uniform scale of at least `constants.py:LILYPOND_SCORE_MIN_SCALE` (`0.60`), with no enlargement or
recognized omitted-tab diagnostic. Failure of any system rejects the complete
score for that offset; other successful offsets remain available.
Custom/unresolved-key scores fall back.
Alternative engravings force the C diagnostic locale, so localized hosts cannot
silently bypass warning-based tablature validation.

`constants.py:LILYPOND_SCORE_MIN_SCALE` is the single fitting-policy value. Python checks it when
accepting notation, passes it explicitly to cache publication, includes it in
candidate cache keys, and writes it as `\ulScoreMinimumScale` in both draft and
final TeX bindings. The TeX overlay consumes that value instead of maintaining
another threshold. A policy change therefore selects different cache entries
and applies to physical fitting in subsequent builds without clearing the cache.
TeX allows at most one scaled point of dimension-conversion noise per axis at
the exact threshold. The applied scale is never rounded up; Python and cache
validation still check the original PDF dimensions against the policy directly.
Standalone TeX without bindings has no generated alternatives and retains the
original notation at unity; that fallback is not a second shrinking policy.

An omitted-tab diagnostic rejects that candidate even when LilyPond exits zero.
A successful octave retry is normal operation, not a warning. If all candidates
fail, the original notation remains and the job warns once per song occurrence
and distinct final failure reason, combining score identities and listing the
affected `tNN (target)` selections. Different occurrences and failure reasons
remain separate. `--verbose` enables DEBUG candidate failures/log paths,
successful octave retries, and the engraving/cache/success/fallback summary;
ordinary output contains no per-offset progress or summary. The private
`<job>.ulsbs-score-results.json` retains every attempt and its individual reason,
including first-octave failures that are recovered by the next candidate.

For enabled jobs only, the pipeline appends `ulsbs-score-boundaries.ily` to both
copied common head and tail. Heads cover explicit assemblies with no tail;
tails preserve callbacks defined later by the source. The listener deduplicates
physical systems when repeated includes install nested callbacks.
Its `grob-transformer` composes with existing
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
adjacent content. Equal visual widths would require a separate spacing
refit with per-system validation, not another justification flag.
If a validated graphic later disappears or no longer fits, the TeX renderer's
last-resort per-system guard substitutes that original system; Python validation
normally rejects the entire offset before dispatch. LilyPond spelling
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
After regenerating hashes, run the cache and relevant score regressions,
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
Integration tests cover page-spanning multi-system overlays, exact
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

### External multikey manifest

The separate ranges index is the only authority for ULSBS book/MULTIKEY JSON.
The manifest comes from finalized compiler/build data and actual final-pass
pagination and UI control anchors. It is not recovered from a PDF, inferred from
song headers or independently maintained. Neither ordinary, range nor temporary
layered PDFs embed ULSBS JSON through `ulsbs:multikey` XMP, custom Info fields,
attachments or any other channel. Ordinary title/author/rights metadata and the
actual OCG declarations remain intact.

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

The nested manifest retains schema 2 and `layer_protocol: "ulsbs:transpose:v1"`;
the outer range index has its own protocol version 1. The backend writes the
envelope to a temporary `.ulsbs-multikey.json` compile artifact. Python captures
and validates this finalized data before cleanup and packages it in the index.
Ordinary book JSON retains `has_multikey_info: false` and `multikey_info: null`.

Each LuaLaTeX pass first removes any prior renderer artifact. Disabled capability
writes a current-run `false`/`null` envelope; a missing or
malformed artifact is an error, not evidence that the renderer is disabled.

### Range index protocol v1

The entry point is UTF-8 JSON bounded to 4 MiB by
`constants.py:MULTIKEY_INDEX_MAX_BYTES`; nested schema-v2 manifest bounds and
validation still apply. This producer/consumer bound requires agreement before
being raised, unlike an internal score-fitting policy. Its exact fields are:

| Field | Contract |
|---|---|
| `format` | Literal `"ulsbs:multikey-ranges"` |
| `schema_version` | Integer `1` |
| `page_count` | Positive global physical page count, identical in ordinary and intermediate PDFs |
| `max_pages_per_range` | Configured positive integer page maximum |
| `target_max_range_bytes` | Configured positive integer byte target |
| `link_policy` | Literal `"canonical-names-v1"`, only after strict validation |
| `canonical` | `{ "file": "Book_A5.pdf", "byte_length": <positive integer>, "sha256": <digest> }` describing the paired ordinary output |
| `geometry` | One `{ "view": [x1, y1, x2, y2], "rotation": 0, "user_unit": 1 }` per global page |
| `manifest` | Finalized `{ "has_multikey_info": true, "multikey_info": <schema-v2 object> }` envelope described above |
| `ranges` | Nonempty ordered array of range descriptors below |
| `packaging` | `{ "tool": "qpdf", "tool_version": <actual version string> }` |

Each range descriptor contains exactly `file`, `first_page`, `last_page`,
`page_count`, `byte_length` and `sha256`. For example its filename can be
`Book_A5_MULTIKEY_RANGE_1-50.pdf`, with endpoints 1 and 50 and page count 50.
Endpoints are unpadded decimal **1-based inclusive physical pages**, never
printed labels or zero-based indices. Ranges cover `1..page_count` exactly once,
without gaps, overlap or blank padding. Each local page count equals
`last_page - first_page + 1` and its actual PDF page count. Adaptive splits can
produce `RANGE_1-25`, `RANGE_26-50`, then `RANGE_51-100`; use the index rather
than guessing filenames or partitions.

All `file` values are plain sibling basenames, not URLs, paths, queries or
fragments; reject traversal, separators and encoded separator/scheme tricks.
Range basenames match the index's MULTIKEY stem and declared endpoints and are
resolved relative to the index directory. `canonical.file` identifies the
actual ordinary producer basename; the ordinary PDF remains at the output root.
It is not a full-MULTIKEY descriptor or a range-directory location override.
SHA-256 values are 64 lowercase hexadecimal characters over final exact bytes,
computed after all extraction/normalization; `byte_length` is the true final size.
No index hash is embedded in those PDFs, avoiding a circular dependency.

Geometry `view` is effective CropBox intersected with MediaBox in unscaled PDF
user coordinates, preserving precision and nonzero origins. Rotation is
normalized to 0/90/180/270; UserUnit defaults to 1. Ordinary/intermediate/range
geometry must agree. Manifest indices remain zero-based **global** indices and
anchors retain PDF user space. For global 1-based page `P`, locate the range
with `first_page <= P <= last_page`; its local 1-based page is
`P - first_page + 1`. Never rebase the manifest or truncate a cross-range song.

`canonical-names-v1` requires internal Link annotations to use exact named
destinations (PDF names/strings) present in the ordinary PDF with equivalent
canonical target and coordinates. Preserve names unchanged across extraction,
including targets outside the range. Preserve original safe external URI actions
and annotation geometry; introduce no active actions or editable form semantics.
Range-local numeric or indirect-page-reference destinations are forbidden.
Normalize only to an existing equivalent canonical name with structured PDF
tooling and revalidate; never invent names, regex-edit PDF bytes, discard target
coordinates or silently drop links. Unsupported cases fail packaging. A range's
own destination tree is not the authority for canonical navigation identity.

### Viewer integration

1. Read the external entry point referenced by `multikey_json_file`, validate
   protocol v1 and its complete range identities, then read `manifest`. Check
   `has_multikey_info`, require nested `schema_version === 2`, and check `layer_protocol`
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
// index is the validated external protocol-v1 entry point, not PDF XMP.
const envelope = index.manifest;
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

// Map global song.page_index + 1 through index.ranges before obtaining the
// range-local page viewport, including its current scale, crop and rotation.
const [left, top] = viewport.convertToViewportPoint(song.anchor.x, song.anchor.y);
```

Changing layers also switches opted-in score/TAB alternatives, but never audio.
Scores remain unchanged when score transposition is disabled. Printing should
use a fresh `intent: "print"` configuration, not the modified display configuration, to keep
the original-only print policy.

### Notation state and layout

The renderer separates musical visual alternatives from shared semantic state.
Chord memorization, replay, payload processing, and arbitrary source side effects
must execute once, not once per offset. Replay follows the
[scanner contract](#annotation-scanner-contract), and visibility is evaluated at
replay time.

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

Run the supported containerized suite with `./ulsbs-test`; see [Testing](#testing)
for runner options. Renderer regression coverage should include OCG names/counts,
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

A controlled Ubuntu-image benchmark (LuaHBTeX 1.18.0, qpdf 12.2.0) compared the
former draft behavior with original-only draft visuals. Its generic 40-song
book contains 320 chord chunks and 160 font-rich LilyPond system inclusions from
public synthetic exercises, with chord shrinking disabled as in the corpus
configuration. All five measured trials use fresh engine processes and fresh
auxiliary files, with warmed font/input caches, alternating condition order,
and no profiling callbacks. One font-cache warmup is excluded.

| Engine draft behavior | Median wall time | Five-trial range |
| --- | ---: | ---: |
| Construct all twelve visuals | 12.002 s | 11.998--12.100 s |
| Construct only original visuals | 4.398 s | 4.357--4.413 s |

The measured draft improvement is 2.73x (63.4% less time). Draft reference
labels, score requests, and global manifests matched exactly. Maintained
regressions also compare layout-bearing box dimensions, song index data,
physical pages, long headers, repeated occurrences, and original-view rendering,
then verify that full runs restore every actual layer. This benchmark does not
measure a three-hour full-book build or predict a 2.73x end-to-end improvement;
the two full passes and LilyPond generation remain separate costs.

PDF bundling was investigated but not adopted. In controlled synthetic tests,
large global bundles slowed distinct-page LuaTeX import substantially. Even
12/24-page bundles sharing only exactly identical whole font dictionaries were
7.7%/17.9% slower for the main TeX pass than separate PDFs; preparation also cost
time. Smaller output bytes or cheaper final font sharing alone are not evidence
of faster overall compilation. Separate graphics and the validated final font
deduplication remain in use.

Paired-edition validation also covered the default, charango, and bass-clef
variants. All visible word positions matched at 0.01 pt precision. Default and
charango each had an 18-pixel raster difference around one superscript on page 8
at 72 dpi; every other page matched exactly. Bass-clef pages matched exactly,
with no visible key-switching effect in that configuration. These small raster
differences must not be reported as strict pixel equality.

The maintained toolchain supplies `ocgx2` through `texlive-latex-extra`. Layer
creation remains TeX/LilyPond OCG output; qpdf packages and validates
page ranges without re-engraving, flattening, rasterizing or print-to-PDF.

## Syntax Migration

The destination-syntax version is part of each migration command's name. The
[v1 migration instructions](README.md#ulsbs-migrate-syntax-v1) cover the legacy
melody/beat conversion below. `ulsbs-migrate-melody-syntax` remains a compatibility
alias for `ulsbs-migrate-syntax-v1`, not for the newest destination syntax.
V1 deliberately retains its original destination names, including
`\melodySecondaryPosition{same}`; run v2 afterwards to adopt current naming.

### V1 melody syntax

`--diff` and `--write` process only files with no diagnostics. Writes are
file-atomic, not directory-atomic: other safe files in a directory may change
even when one file is rejected. Comments and verbatim-like regions are ignored.
Accidental macros are rewritten only inside standalone `\altchords`,
`\beginsong`'s `key`/`gk` values, and `\audio`'s `key` value; explicit macros
elsewhere remain intact.

Baseline alternate-only `\ma`/`\mac` forms become secondary notes under
`\melodySecondaryPosition{same}`. A uniform verse receives one scoped setting;
mixed placement receives a local TeX group. Missing secondary-note slots are
never inferred. `--normalize-low` normalizes reviewed low `\mnd`/`\mad` slots
but does not change verse environments.

The rendered one-slot circled `/` marker remains `/`, never the empty-slot `_`.
Legacy commands are migrated only from the leading melody/beat layer. A leading
replay caret remains before the generated block: `\[^\mnc{C}]` becomes
`\[^<C>]`. Alternate chords stay after that block while their selectors change
from `\ac<1>{Em}` to `\ac{1}{Em}`. A legacy melody command after chord content
produces a diagnostic instead of being hoisted across the chord. Malformed
arguments, compound pitches, incompatible offsets, and ambiguous secondary
placement also require author review rather than speculative conversion.

### V2 naming

The [v2 migration instructions](README.md#ulsbs-migrate-syntax-v2) describe the
current naming upgrade. `src/ulsbs/tools/naming_v2.py` is the authoritative
inventory: `COMMAND_RENAMES` maps bare control words, `BOOLEAN_SETTERS` maps old
true/false commands to explicit setter/value pairs, and `NAME_ARGUMENT_RENAMES`
maps literal counter, color and environment names only in their argument
contexts. Only public names are migrated; private implementation names are not
an author API.
Book and index assembly environments are `ulSongs` and `ulIndexBlock`; their
generated direct begin/end control words follow the same naming inventory.
The title constructor remains `\ulNewIndex`; the tag constructor and heading font
are `\ulNewTagIndex` and `\ulIndexTagFont`, replacing their former scripture names
without runtime aliases. `\ulTagFile{filename}` is a new preamble-only setter.

`COMMAND_EXPANSIONS` records the removed chorus wrapper's actual behavior:
`\beginchorus` and `\chorus` expand to `\beginverse\beginrep`, while
`\endchorus` expands to `\endrep\endverse`. Literal `\begin{chorus}` and
`\end{chorus}` become `verse` environment boundaries with explicit repeat
boundaries inside the environment group. Existing comments and lyric tokens
remain in place; no star or indent option is moved ahead of the inserted
`\beginrep`. `REMOVED_COMMANDS` lists inert configuration in both
old and v2 spellings. These settings diagnose, not map to live verse settings:
renaming an unused chorus penalty or font hook to a verse setting would introduce
effects that the source never had.
The inventory also diagnoses removed partial-list/raw-text switches, last-column
glue, index-book and note-name/printer hooks, prelude-good text and song-number
default-height controls, rather than emitting destinations absent from the runtime.

V2 preserves short lowercase song notation, class option and metadata keys,
hook paths and serialized metadata. Ordinary source migration preserves filenames;
the explicit tag-file migration described below renames its selected file.
Configuration, assembly, fonts and accessors use `ulCamelCase`; initialisms follow
the same casing (`ulToc`).
Boolean setters preserve defaults and scoped assignments; readable predicates
remain real TeX conditionals, for example `\ifulShowTags ... \else ... \fi`.
Generated true/false helpers are private. No old runtime aliases are installed.

The scanner accepts `.tex`, `.cls`, `.sty` and manual index `.sbx` files. It
preserves comments, inline verbatim, verbatim-like environments, literal URLs
and inline/environment LilyPond bodies. Direct one-to-one command references and
definition targets can be renamed; safe delayed boolean and chorus bodies can be converted.
Boolean references or targets that cannot accept an added argument, computed
identifiers, ambiguous unknown-macro boolean arguments and unsafe tokenization
constructs require review. A diagnostic suppresses all edits and diff output for
that file. Safe files in a mixed batch may still be written independently, with
file-atomic replacement preserving file mode and line endings. This is not a
TeX interpreter or a directory-atomic transaction. V1 source and destination
semantics remain unchanged; upgrading legacy melody sources is v1, then v2.
Chorus expansions likewise require executable contexts: references, definition
targets, expansion-time bodies, unknown macro arguments, environment definitions
or environment-hook identifiers require review instead of multi-token replacement.

`--tags-file FILE` explicitly selects legacy tag definitions and requires
`--check`, `--diff`, or `--write`. It works standalone or alongside source paths;
normal source migration emits a reminder, never automatic `.can` discovery.
Conversion preserves canonical/alias order, removes legacy `1` count lines, and
renames `.can` to `.txt` with the same basename. Destination collisions and symlinks
are refused. A custom basename requires the author's corresponding
`\ulTagFile{custom-name.txt}` preamble setting. This is migration support only;
the runtime reads only the new plain-text tag format. V1 melody and safe chorus
conversion contracts are unchanged.
The removed `sr=` field, three-braced metadata form and `songrefs`/`ulSongRefs`
accessors diagnose for review without partially rewriting the file. No automatic
scripture-to-tag conversion is provided. Explicit tag-index reference values with
numeric suffixes still need manual review: the migrator does not infer whether a
suffix is an old reference or part of a legitimate tag name.

## Testing

From the ULSBS source directory, run `./ulsbs-test`. The runner builds the normal
Docker or Podman `ulsbs-compiler` image when needed, runs LuaLaTeX regressions
through `l3build`, and runs compilation/PDF-structure tests through Python's
standard-library `unittest` runner.

The default command runs the whole retained regression suite, not a quick subset.
Python modules run in four separate worker processes by default; `--jobs 1`
serializes them on memory-constrained machines. Each module's output includes its
test/skip summary and elapsed time, followed by total suite wall time. The target
for the supported container is under about 20 minutes, excluding image builds.
Use `--verbose` to see individual test names and skip reasons.
A full run has been measured at about 10.5 minutes with four workers on the
maintainer's machine. This is not a timing guarantee for other hardware or a cold
image build.

```sh
./ulsbs-test --container-rebuild
./ulsbs-test --container-engine podman
./ulsbs-test --no-container
./ulsbs-test --verbose
./ulsbs-test --jobs 1
```

Host testing is intended for development only. The containerized suite is the
canonical result because it uses the supported ULSBS toolchain and fonts. See
[Validation and Performance](#validation-and-performance) for renderer/PDF
inspection and measurement guidance, [PDF Font Sharing](#pdf-font-sharing) for
optimizer coverage, and [Trusted Cache Assets](#trusted-cache-assets) for the
read-only asset audit and explicit trust-record maintenance workflow.

Focused Python tests live under `tests/`; normalized LuaLaTeX fixtures live under
`tests/tex/`. Select coverage for the changed subsystem, including representative
rendering, index or multikey builds when relevant. Runtime isolation and asset
packaging checks live in `tests/test_modules.py`; from the engine source
directory, `python3 tests/test_modules.py --packaging-smoke` builds wheel
and sdist assets and checks isolated installed resource lookup. Documentation-only
edits need link, consistency and whitespace checks, not a corpus build.

Tests protect engine behavior: parser/state transitions, once-only source effects,
selection and numbering, index ordering/convergence, PDF navigation, layer/print
policy, and publication/asset contracts. Normalized TeX logs check state, not page
images. When checking dimensions, set the relevant
styling explicitly or compare engine variants within the same run (for example,
layers on/off), rather than pinning the default typography or pagination. New
default styling should not require updating historical reference PDFs.

For focused Python work without the wrapper:

```sh
PYTHONPATH=src:tests python3 -m unittest test_song_lifecycle -v
```

External-tool tests report skips on an incomplete host toolchain; a host pass
with skips is not equivalent to a supported-container run. Test products and font
caches live in ignored `build/` or temporary directories and may be deleted when
no tests or builds are running.
