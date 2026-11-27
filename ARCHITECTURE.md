# ULSBS Architecture

This reference describes ULSBS internals and implementation contracts. For setup
and compilation, start with the [README](README.md). For song syntax and book
customization, use [Writing Songbooks](WRITING_SONGBOOKS.md).

- [Developer Navigation](#developer-navigation)
- [Song Engine](#song-engine)
  - [Module loading and assets](#module-loading-and-assets)
  - [Named variants](#named-variants)
  - [Reading and documenting runtime code](#reading-and-documenting-runtime-code)
  - [Song and page lifecycle](#song-and-page-lifecycle)
  - [Prelude layout](#prelude-layout)
  - [Annotation scanner contract](#annotation-scanner-contract)
  - [Retained geometry and spacing](#retained-geometry-and-spacing)
  - [Chord diagrams for guitar](#chord-diagrams-for-guitar)
- [Index Lifecycle](#index-lifecycle)
- [Fixed Policies and Version Ownership](#fixed-policies-and-version-ownership)
- [PDF Font Sharing](#pdf-font-sharing)
- [Build Diagnostics](#build-diagnostics)
- [Performance Optimizations](#performance-optimizations)
  - [Implemented: parallel engraving of alternative score keys](#implemented-parallel-engraving-of-alternative-score-keys)
  - [Not retained](#not-retained)
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
  - [V2 naming and semantics](#v2-naming-and-semantics)
- [Testing](#testing)

## Developer Navigation

The main entry points for extending or debugging the engine are:

| Area | Source |
|---|---|
| Document class and author-overridable styles | `src/ulsbs/assets/tex/ulsbs-songbook.cls`, `src/ulsbs/assets/tex/ulsbs.sty` |
| Variant presets and lifecycle | `src/ulsbs/assets/tex/ulsbs-variant-*.code.tex`, `ulsbs-variants.code.tex` |
| CLI and public configuration | `src/ulsbs/cli.py`, `src/ulsbs/config.py`, `ulsbs-config-example.toml` |
| Build orchestration and jobs | `src/ulsbs/pipeline.py`, `src/ulsbs/jobs.py` |
| Warning parsing and reporting | `src/ulsbs/diagnostics.py`, `src/ulsbs/pipeline.py` |
| Range extraction and validation | `src/ulsbs/multikey_ranges.py` |
| Family installation and deployment | `src/ulsbs/multikey_publish.py`, `src/ulsbs/deploy.py` |
| Score alternatives and persistent cache | `src/ulsbs/lilypond_scores.py`, `src/ulsbs/lilypond_score_cache.py` |
| Shared engine policies | `src/ulsbs/constants.py` |
| Named-variant registry and literal availability reader | `src/ulsbs/variants.py`, `src/ulsbs/assets/tex/ulsbs-variants.def.tex` |

The executable wrappers are `ulsbs-compile`, `ulsbs-bookmeta`,
`ulsbs-midi2audio`, `ulsbs-ly2tex`, `ulsbs-migrate-syntax-v1`,
`ulsbs-migrate-syntax-v2`, and `ulsbs-test`.
The [README](README.md) documents their author-facing use; release procedures
are in [MAINTAINERS.md](MAINTAINERS.md).

Compiler output policy belongs to `ui.py`, independently of build configuration.
The CLI bootstraps `--plain-output` before creating the UI and full parser, so
colors and the spinner are disabled even for help and argument errors. This
CLI-only policy overrides environment/TTY detection without changing the process
environment. Container delegation preserves the flag and forwards disabled colors
and spinner state via `NO_COLOR` and `ULSBS_NOSPINNER`, since its pseudo-TTY hides
host redirection. Without the flag, `NO_COLOR` remains color-only. The VS Code
extension forwards build output directly to an ANSI terminal, so it sets
`ULSBS_INTERNAL_TERMINAL_OUTPUT=1` and `TERM` for the compiler. Container
delegation forwards both without requesting a container TTY for those pipes.

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
| `ulsbs-variants.code.tex`, `ulsbs-variants.def.tex` | Literal main-source availability, immutable active identity, shared registry and automatic preset lifecycle |
| `ulsbs-variant-*.code.tex` | Selected preset's post-class rendering defaults, never identity setters |
| `ulsbs-init.code.tex` | Bootstrap public flags, counters, lengths, font hooks and pre-typography measurements; not the final style defaults |
| `ulsbs-book-defaults.code.tex` | Visibility installation, simple book presentation switches, early verse indentation and localized book metadata defaults |
| `ulsbs-visibility.code.tex` | Book permissions, local requests, effective visibility, lazy musical guards and the document-start permission freeze |
| `ulsbs-style.code.tex` | Final colors, font policy, page headers, boxes and stanza-break styling |
| `ulsbs-utilities.code.tex` | General typesetting helpers, circle measurement/cache, paragraph tracking and repeat loops |
| `ulsbs-typography.code.tex` | Font families, document font defaults, additional languages and Unicode symbols |
| `ulsbs-frontmatter.code.tex` | Cover icons/pages, imprint, TOC and main chapter presentation |
| `ulsbs-song-helpers.code.tex` | Navigation/indentation, alternate-chord display helpers and lyric annotations |
| `ulsbs-prose.code.tex` | Shared language sections, passages, translations, explanations and in-song prose blocks |
| `ulsbs-media.code.tex` | Width-safe score graphics, whole-score display gate and image placement |
| `ulsbs-melody.code.tex` | Melody syntax, lane/style policy, parser state, beat drawing and raw replay payloads |
| `ulsbs-song-metadata.code.tex` | Song IDs/anchors, physical-position records, prelude fields/measurements and audio metadata |
| `ulsbs-notes.code.tex` | Attached text/music-note helpers and capo instructions |
| `ulsbs-spacing.code.tex` | Shared validated bar/verse spacing setters and their font-resolved initial policy |
| `ulsbs-repeats.code.tex`, `ulsbs-repeats.lua` | Repeat-bar fragments/state, inline repeat signs and shipout coalescing/continuation dashes |
| `ulsbs-boolmap.code.tex`, `ulsbs-chapter-marks.code.tex` | Boolean-map utilities and chapter corner marks |
| `ulsbs-song.code.tex` | Metadata, custom keys, titles, numbering, selection, anchors, lifecycle hooks and once-only index events |
| `ulsbs-layout.code.tex`, `ulsbs-layout.lua` | Song boxes, page/column positioning, break penalties, bottom glue and prose/block adapters |
| `ulsbs-verse.code.tex` | Verse modifiers, source newlines, numbering, indentation and lyric baselines |
| `ulsbs-chords.code.tex` | Token scanning, lyric boxes, chord anchoring, memory/replay and alternate chords |
| `ulsbs-music.code.tex`, `ulsbs-music.lua` | Source transposition, melody composition and retained physical-line annotation/bar/repeat geometry |
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
`ulsbs-book-defaults.code.tex` follows those helpers and first installs the visibility
owner. Visibility owns its baseline permission/request state together with its API;
the book-defaults module then supplies ordinary casing/color/chord-adjustment
switches and book strings. Localized defaults use `\ulIfLanguage`, and the initial `1em` verse indent
is captured before typography.
Typography loads after the PDF color-profile setup and before
`ulsbs-style.code.tex`; that style phase loads chapter marks after TikZ calc,
chapter colors and dimensions. Front matter loads after shared styles and before
song-content helpers. The entry then loads song helpers, prose, media, melody,
song metadata, attached notes and repeats in that order. Each extraction retains
its original load-time assignments and measurements, not just its macro bodies.
Repeats installs the shared bar/verse spacing API at its original point before
allocating repeat attributes and registering its shipout callback. Its Lua companion
executes once through `dofile(kpse.find_file('ulsbs-repeats.lua'))` there; it does not
defer callback installation until document start or first drawing. These common
styling, notation and PDF helpers precede the ordered subsystem owners: index
serialization/state/sorting, song lifecycle, layout, verses, chords, music, multikey, diagrams, then
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

Default values live with the phase or subsystem that owns their meaning. Keep
bootstrap declarations distinct from final shared style and from subsystem-local
policy. The author-facing [layout and style reference](WRITING_SONGBOOKS.md#layout-and-style-reference)
is the customization catalog; do not make a private companion a second author
configuration entry point. Public current-song fields are data, not book defaults,
and replaceable renderers remain with their rendering implementation.

Consumer overrides follow the declaration's contract, documented inline:
pre-load `\providecommand` defaults accept an earlier `\newcommand`, while
post-load macro hooks use `\renewcommand`. Use `\setlength` for lengths, integer
assignment for penalty counts, and explicit boolean setters such as
`\ulShowTags{false}` with real predicates such as `\ifulShowTags`. A later macro
change does not retroactively reconfigure an already-loaded package or captured
dimension. Book PDF metadata defaults are finalized after the preamble as described
below; changing strings in the body does not republish them. Private default files are not consumer
configuration files to input directly.

Derived geometry also has an evaluation boundary: cover dimensions capture page
geometry when front matter loads, chapter-mark segment length is computed when
chapter marks load, and circle diameter/radius are cached on first use for each
font size. Changing an input later does not automatically rerun these computations.
Index typography may be evaluated repeatedly while measuring/wrapping fragments;
style hooks are not once-only source-effect callbacks.

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
including score layers and registered variant presets. Installed books must resolve
these assets without a source checkout, upstream songs or an external indexer.
`keyval`, `etoolbox`, `environ`, `expl3` and `xparse` remain used dependencies.

### Named variants

The TeX class accepts literal main-source
`variants={default,lyric,charango,bassclef}` and a pre-class `\ulBuildVariant`
launcher selector; omission means default-only availability and default identity.
The Python queue/compiler discover main-source availability and prepend the
reserved selector. External score preparation uses registered recipe references;
the v2 migrator combines naming and bounded semantic source conversion in one
original-source transaction.
Cover/imprint and PDF metadata use registered
presentation policy; inline chords, melody pitches, beats, measures, whole scores,
alternate sets, main-key/good-key badges, authors/dedications/extra info, music
comments, tags, prelude/TOC phases, translations, explanations, passages, feelers
and chapter artwork have book/local/effective visibility.

The registry is one installed TeX asset, not parallel Python/TeX lists or generated
checkout-relative data. Each literal `\ulsbsVariantRecord` line contains six
arguments: identifier, TeX preset filename, score recipe, output filename marker,
presentation-policy reference and supported editions. Python reads these records
with `importlib.resources`; a TeX consumer supplies the record macro before input.
Records contain no executable expressions. Python's immutable records describe
build policy, never duplicate the TeX presets' visibility defaults. Every record
references an owned `ulsbs-variant-*.code.tex` asset. The default preset deliberately
leaves the source class's baseline configuration intact, rather than imposing an
intrinsic musical book type.
Recipe and presentation references are dispatch keys, not feature predicates.

`validate_variant_names` accepts nonempty comma-separated canonical lowercase
registered names, with surrounding whitespace but no duplicates or expansion.
Availability additionally requires `default`. It preserves declaration order;
selection owns default-first ordering. The canonical key is `lyric`, while
the output marker deliberately remains `_LYRICS-ONLY`.

`read_documentclass` finds one literal top-level main-source class invocation
before `\begin{document}`, retaining raw options and source offsets for migration.
The bounded reader skips comments, grouped definitions/arguments and common
verbatim, URL, detokenized and literal-environment regions. It balances braces,
including comma-containing metadata and closing brackets protected by braces.
`available_variants` reads only the braced `variants={...}` option for classes
whose names start with `ulsbs-songbook`. Omission and unrelated inputs mean only
`default`. Repeated options are rejected even if identical; malformed, empty,
computed, duplicate and unknown list entries fail rather than being ignored.
Neither helper expands macros, follows inputs/custom classes, evaluates conditional
execution nor models arbitrary catcodes. Availability must be a literal main-source
declaration, not something constructed by those mechanisms. Historical migrators
retain their own existing behavior.

`Config.variants` is `all` (the default) or a validated tuple of canonical names.
TOML accepts `"all"` or an array of names; `--variants all|NAME,NAME` overrides the
selected profile. Category booleans and their negative CLI flags are removed,
not aliases. The queue intersects explicit selection with each main source,
without adding default; selected default comes first, then declaration order.
A single input rejects any unavailable requested name. Collections report each
intersection and skipped names, and reject names matching none of the inputs.
Omitted availability and unrelated documents have only default; unrelated inputs
never gain multikey editions. Legacy extra-variant comments grant no availability.
Planning rejects malformed declarations and output collisions before temporary
build setup. `--quick` selects ordinary default only and rejects conflicting
explicit selection. Naming and edition eligibility come from registry records;
lyric is ordinary-only while bass-clef supports score-based multikey.

`make_variant_tex` revalidates identity/availability/edition before writing, leaves
the source bytes intact after its pre-load configuration, and adds
`\def\ulBuildVariant{NAME}` only for non-default jobs. No compiler code injects a
TeX preset or visibility mutation: the existing outer-class lifecycle owns it.
The registry's `score_recipe` reference selects a small explicit strategy in
`_prepare_score_recipe`: default is a no-op (also used by lyric), charango inserts
the audited tuning assignment, and bassclef copies the bundled bass-clef tails
over their ordinary filenames. Unknown recipes fail before the generated TeX is
written, not silently as baseline. Preparation uses only job-local copied assets
and is idempotent when repeated with the same recipe; retained compilation first
refreshes those assets from the package. Recipe remapping never changes identity,
TeX presets, edition support or media permissions. The complete modified bytes
remain cache inputs, with no new trust normalization or asset-manifest changes.
LilyPond diagnostics are collected for every variant: lyric still preprocesses
scores and can author-enable display or opt into media exports, so its printed
preset denial cannot justify discarding tool warnings or unreadable-log reports.

`ulsbs-variants.code.tex` resolves identity before option processing/package
imports, snapshots exactly one replacement level of the reserved build selector,
and validates it against the same installed registry and the main declaration.
`\ulIfVariant{name}{yes}{no}` validates a literal registered name and tests that
private immutable snapshot, independently of later selector/visibility changes.
There is no public identity setter or per-variant mutable boolean. Old book-type
and variant flags are no longer defined by the runtime; historical source tokens
remain recognized by migration tooling, not installed as compatibility aliases.

The class marks its entry before loading the owner. Availability reads the kernel's
`\@raw@classoptionslist`, not inherited class option values, and rejects repeats
before kvoptions can overwrite evidence. Braced metadata remains opaque. Both
Python and TeX reject empty/computed/unknown/duplicate names and require default;
TeX stringifies literal names consistently before sequence membership checks to
avoid letter-versus-other catcode mismatches. This is token validation, not a
general static TeX interpreter; arbitrary conditional execution/catcodes remain
outside the source declaration contract.

Preset application appends directly to the kernel's private
`\@documentclasshook`, after the complete outer class, its end callbacks and its
`class/.../after` hook, before the next author preamble statement. This intentional
private dependency is covered by nested third-party class tests. `AtEndOfClass`
on the base is too early; generic command hooks on this macro are deferred until
begin-document and too late. Without the class, package-only use is default-only,
rejects non-default selectors with a class-declaration diagnostic, and applies its
default at package completion. Neither entry reapplies presets at begin-document.
Early font measurements and optional ocgx2 imports stay at their existing load
sites; the new presets do not retroactively recompute them or change edition setup.
The visibility owner in `ulsbs-visibility.code.tex` keeps independent private
book permission and grouped local requests for chords, melody pitches, beats,
measures, whole scores, alternate sets, key badges, music comments, translations,
explanations, passages, feelers, tags, prelude/TOC phases, prelude
authors/dedications/extra info and chapter artwork.
`\ulShowChords{true|false}`, `\ulShowNotes{true|false}`,
`\ulShowBeats{true|false}`, `\ulShowMeasures{true|false}`,
`\ulShowLilypond{true|false}`, `\ulShowAltChords{true|false}`,
`\ulShowTranslation{true|false}`, `\ulShowExplanation{true|false}`,
`\ulShowPassage{true|false}`, `\ulShowFeeler{true|false}`,
`\ulShowKey{true|false}`, `\ulShowGoodKeys{true|false}`,
`\ulShowMusicComments{true|false}`, `\ulShowAuthors{true|false}`,
`\ulShowOfferedTo{true|false}`, `\ulShowExtraInfo{true|false}`,
`\ulShowTags{true|false}`, `\ulShowPhase{true|false}`,
`\ulShowPhaseInToc{true|false}`, `\ulShowImageInChapterName{true|false}` and
`\ulShowImageOnChapterFrontPage{true|false}` configure permission
only in the preamble; `begindocument/before` freezes it, including before author
`\AtBeginDocument` callbacks. Body setters diagnose without changing permission.
`\ulLocalShow{chords|notes|beats|measures|scores|altchords|translation|explanation|passage|feeler|key|goodkeys|musiccomments|authors|offeredto|extrainfo|tags|phase|phaseintoc|imageinchaptername|imageonchapterfrontpage}{true|false}`,
`\chordson`/`\chordsoff`,
`\noteson`/`\notesoff`, `\beatson`/`\beatsoff`, `\measureson`/`\measuresoff`
and `\translationon`/`\translationoff` change only their feature's request.
Effective `\ifulShowChords`, `\ifulShowNotes`, `\ifulShowBeats`, `\ifulShowMeasures`,
`\ifulShowLilypond`, `\ifulShowAltChords`, `\ifulShowTranslation`,
`\ifulShowExplanation`, `\ifulShowPassage`, `\ifulShowFeeler`, `\ifulShowKey`,
`\ifulShowGoodKeys`, `\ifulShowMusicComments`, `\ifulShowAuthors`,
`\ifulShowOfferedTo`, `\ifulShowExtraInfo`, `\ifulShowTags`, `\ifulShowPhase`,
`\ifulShowPhaseInToc`, `\ifulShowImageInChapterName` and
`\ifulShowImageOnChapterFrontPage` are assigned the genuine
`\iftrue`/`\iffalse` primitive meaning,
never a composite macro.
TeX grouping restores both request and predicate. The generic local dispatcher
currently accepts `chords`, `notes`, `beats`, `measures`, `scores`, `altchords`,
`translation`, `explanation`, `passage`, `feeler`, `key`, `goodkeys`,
`musiccomments`, `authors`, `offeredto`, `extrainfo`, `tags`, `phase`, `phaseintoc`,
`imageinchaptername` and `imageonchapterfrontpage`. Non-default presets initialize
the six notation permissions
and music-comment permission and reset their initial requests to on after the complete
custom class; default preserves source baseline settings. None of these switches
mutate identity, another feature's permission/request, bottom glue or cached font
allocations.

Chapter-name and chapter-front-page artwork have independent permission AND
requests, initially true. All presets preserve both authored layers. Name-art
visibility is chosen at the source `\ulMainChapter` call: its captured short title
contains artwork or no artwork, never a query to reevaluate in delayed marks,
TOC writes or the next pass. Front-page art follows its own effective query at
that call. Hidden image/symbol sources execute no hooks or file reads and leave
no art separator or front-page art spacing. Existing optional-image, symbol,
uppercase, color and repeated visible TOC/header rendering semantics remain.

The other on/off controls are configuration, not independently masked content:
slides (output/leading mode), lyric omission (scanner content mode), capo/alternate
transposition (source operations), index generation/separation, page-prelude
positioning, title case, chapter colors/dashed corner marks and chord-character
typography. Their existing scopes and single purposes remain unchanged. Internal
parser, rendering, repeat, language-skip and layer scratch flags are not additional
feature permissions. Rendering and geometry query immutable identity or effective
features; no mutable book-type state is maintained.

Tags (`tags=`), prelude phase (`ph=`) and phase in the TOC have independent
permission AND grouped request, initially true. All four presets preserve BOTH
authored layers. They never contribute to `\ulIfMusical`, change another feature
or infer policy from identity. There are no short switches or private factory
setters. Hidden tag/phase display is lazy, including natural-width checks and
multikey anchor samples: no display hooks or phantom badge rows. Visible badges
retain their existing title-context natural-width tests, zero-width omission,
tag/phase separator and style measurements. These visible measurements can execute
style hooks more than once, as before; they are not once-only metadata evaluation.
Metadata ingestion, tag indices/export and multikey capture remain independent.
The zero-size multikey header anchor remains available for other transposable ink.

Prelude badge size and default tint are part of the SAME captured registry
presentation policy as cover/imprint/title, not feature policy or mutable legacy
identity. Lyric presentation supplies `\tiny` and gray; default, charango and
bass-clef supply `\scriptsize` and inherit color. Renewable
`\ulPreludeBadgeFont` selects that size plus `\normalfont` for visible rows AND
enabled, nonempty header-anchor samples. The existing `\ulPreludeTagStyle`,
`\ulPreludeKeyLineStyle` and `\ulPreludePhaseStyle` defaults delegate to the
captured tint; pre-load definitions, complete-class renewals and author preamble
renewals remain authoritative. Presets never overwrite those hooks. A style change
does not grant visibility or alter metadata capture. Hidden rows/samples never
call the font hook either. Visible title-context width checks and repeated style
measurements retain their existing semantics; row offsets and early font
allocation are unchanged.

Phase-in-TOC queries only its own effective state at song start. The selected
`\addcontentsline` payload contains either the styled phase or no phase, never a
visibility predicate to reevaluate at shipout or next-pass TOC reading. A later
local change cannot rewrite an earlier song's TOC policy. Writes remain nodes in
retained song boxes, so discarded songs do not enter the TOC and selection retains
its existing shipment semantics. The TOC does not replay prelude badge style hooks;
ordinary multipass reference/TOC convergence remains required.

Prelude authors (`by=`), dedication (`off=`) and extra info (`ex=`) each have
independent permission AND request, initially true. All four presets preserve
both authored layers; none resets requests or infers text policy from identity,
notation, keys or music comments. These fields never make `\ulIfMusical` true.
No short commands or private factory setters remain for them. `\ulExtendPrelude`
lazily guards each complete display operation, including separators and the extra
paragraph, before touching its stored display value. Hidden fields execute no
display hooks or reserve text/paragraph space. The visible attribution still
composes once in a retained horizontal box and unpacks for line wrapping, with
its existing width test and English/Portuguese dedication separators, including
the leading dedication space when authors are absent. Extra info remains a
separate paragraph with authored line breaks. This is not opaque metadata capture:
song setup, public metadata adapters, author indices/export and multikey capture
remain independent and may already have consumed those tokens before display.

Main-key and recommended-key badges have independent effective visibility, with
no chord, musical-aggregate or legacy identity display gate. Lyric denies both
permissions; the other presets preserve authored permission AND request. All
presets preserve these requests, including when lyric denies permission, so an
author's later permission override does not erase scoped suppression. Bass-clef
therefore retains baseline key information despite denied inline chords, without
overriding a class's deliberate key suppression. No short key switches or private
factory setters remain. Hidden badges do not execute display styles/labels or
allocate rows; the multikey anchor also omits its hidden/absent main-key sample.
The zero-size anchor itself remains available for other transposable notation.
Visible multikey anchor samples still measure public style hooks, not source key
payloads. This is display policy only: song metadata capture, key validation,
indices/export, effective-key transposition and OCG eligibility remain independent.
It is not opaque skipping of metadata already consumed by the song/multikey owner.

Music comments are musical prose, not inline pitched `ShowNotes`, chord help or
an inference from `\ulIfMusical`. `\musicnote`, `\musicnoteforprev`,
`\musicnotefornext` (including its trailing star) and `\musicnotemiddle` share
one lazy effective-comment guard in the visibility owner. It suppresses the entire
display operation: hidden balanced arguments, including unmatched conditional
tokens and missing inputs, have no body, font, placement, glue, fill or geometry
effects. Visible helpers delegate once to the same text-note adapters, retaining
their chord color, prose leading and previous/next/middle attachment behavior.
The initial `\musicnote` definition is the sole definition, not overwritten by
shared style. Comments are allowed in charango and bass-clef and denied in lyric;
these presets reset the initial comment request on after complete class setup.
Default preserves the class's permission AND request. Later author permission
overrides preserve requests; local-on cannot bypass denial. No short commands
are added, and comments alone never make `\ulIfMusical` true. Chord-specific help
still needs an explicit effective-chord guard at its call site; instrument-specific
help may additionally need identity. Consumer call-site migration remains separate.
`\capo` is not a general comment: its non-transposing display tests only effective
chords, independently of comment permission. Its transposing branch remains a
source operation even when chords/comments are denied. Diagram rendering itself
is unchanged.

Translations have no second local mask: the environment queries only effective
visibility. All presets preserve the source's translation permission AND request;
this independent prose feature is not reset or inferred from musical identity.
Authors can override permission after the complete custom class, without erasing
an inherited local request. The environment retains verbatim's line-oriented
hidden-source skip, not token-list capture: hidden text may contain unbalanced
braces/conditionals or missing inputs. Its `\end{translation}` terminator must be
on its own source line. Hidden entry performs no language/font/block/verse setup,
end-fill mutation or body evaluation and contributes no geometry. Visible language,
font, stanza and chord-suppression behavior remains unchanged and scoped by the
environment. Translation state does not contribute to `\ulIfMusical`.

Explanations share this permission/request model but remain independent of
translation state and musical identity. All four presets preserve authored
explanation permission AND request; no short explanation switches are added.
The environment retains the same raw line-oriented skip for book/local denial
and `\ulExplanationLanguagesToSkip`, with `\end{explanation}` on its own source
line. The language-hide decision is environment-local, not a global flag or
feature-request mutation. Existing substring matching of the language list is
unchanged. `\ulExplanationOmitLangCodes` only hides displayed codes, never content.
Hidden explanations have no body/font/language/block/counter/end-fill effects or
geometry. Visible explanations preserve prose formatting, the first-block spacing,
the smaller gap for subsequent explanations and song-reset counter behavior.
Their existing end-fill policy remains false, unlike translations' true policy.
Neither explanation visibility nor language selection contributes to `\ulIfMusical`.

Passages use the same owner but remain independent prose, inside or outside songs.
All presets preserve authored passage permission AND request; there are no short
passage switches. Book/local denial and `\ulPassageLanguagesToSkip` retain the raw
line-oriented skip, with `\end{passage}` on its own source line. Language hiding
is environment-local and preserves the existing substring list matching, not a
feature-policy mutation. `\ulPassageOmitLangCodes` suppresses only displayed codes.
Hidden passages have no body/title/font/language/fill effects or geometry. Visible
passages retain their title, alternate starred style, `\obeylines`/`\disobeylines`,
prose leading, indentation and vertical fill, without changing song end-fill state.
Passage visibility never contributes to `\ulIfMusical`.

Feelers also retain independent authored permission AND request in all four presets,
with no short switches or legacy private writable setters. Their effective query
does not contribute to `\ulIfMusical`. Unlike the three raw-skipping prose environments,
`feeler` uses LaTeX `+b` capture: braces and environment delimiters must balance,
but hidden unmatched conditional tokens and missing inputs remain opaque through a
lazy effective-predicate guard. The old `environ` cleanup scanner exposed such tokens.
Hidden bodies have no effects, block spacing, end-fill mutation or geometry. Visible
bodies execute once with the existing small, centered, emphasized prose, block-start
and song-end-fill behavior, both inside songs and in standalone `intersong` blocks.
Environment scope restores font and local visibility requests; the existing in-song
block counter and global end-fill effects intentionally persist until song end.

Alternate-set effective visibility reports only its own permission AND request,
not inline chord state. Standalone `\altchords` and its ID helper lazily require
BOTH effective chords and alternate sets before evaluating payloads, ID numbers or
labels, changing persistent set color, spacing or drawing. Hidden source (including
unmatched conditional tokens) contributes no geometry or layer requests. The chord
owner alone implements the standalone collector; the entry only declares its public
command. Standalone sets stay outside interactive multikey transposition. Inline
`\ac` is a repetition-specific chord reference, not a standalone set: it still
requires only effective chords and participates in stanza PDF layers even when
alternate sets are suppressed. Neither alternate visibility nor its local request
changes `\ulTransposeAltChords`, which remains independent, grouped configuration.
Lyric/bass-clef deny alternate sets; charango permits them and resets inherited
suppression; default preserves class policy and requests. The musical aggregate
does not query alternate-set visibility.

Measure bars no longer have a separate ink mask or legacy-type initialization:
`\ifulShowMeasures` controls both rendered bars and future stanza bar catcodes.
The old `\ulMeasures` / `\ifulMeasures` names are removed, not aliased. The verse
owner installs a private callback for effective-state changes inside live stanzas;
group exit restores both predicate and catcodes. Already-tokenized bars, including
first-token lookahead, still test effective ink. Disabled future bars use ignored
catcodes to preserve source spaces. `\e` and alternate-set dashes use the same
predicate. Non-default presets permit measures; default preserves authored permissions
and requests.
`\meter{top}{bottom}` globally retains unexpanded pending tokens across inner boxes
until an enabled bar measures each once, emits the retained boxes and clears them.
Hidden bars have zero geometry/effects and do not consume pending meter; hidden
`\mbar` also leaves it untouched. Pending tokens do not acquire a second permission
or mask. The naming inventory's historical destinations are unchanged; the v2
semantic planner supersedes supported body assignments in its original-source
plan and diagnoses unsupported measure uses. Old runtime names are not aliases.

The same visibility owner supplies `\ulIfMusical{yes}{no}`: a call-time OR of
effective inline chords, inline melody pitches and whole scores. Beats AND measure
bars are excluded, as are keys, prose, identity and actual score presence. The
braced query does not cache state or change scope; only the chosen branch executes,
once. Its lazy branch selection keeps unchosen tokens opaque even with unmatched
TeX conditionals. Branches may contain paragraphs. Raw `\ifulShow...` predicates
remain genuine TeX conditionals; this aggregate helper is not an annotation gate.
Authored mottos should use this feature aggregate, not a legacy binary book type.

`lilywrap` is the whole-score display boundary after LilyPond preprocessing. Its
LaTeX `+b` body capture and lazy effective-predicate guard keep hidden source opaque,
including unmatched conditional tokens: no body inputs/side effects, score-system
inclusions, layer requests, block spacing or end-fill changes occur. Visible bodies
execute once; retained score-layer boxes preserve effective-original dimensions.
This replaces `environ` body cleanup, whose conditional scanner was unsafe with
unmatched hidden conditionals. Bodies still need balanced braces and environment
delimiters for capture; raw LilyPond still requires preprocessing. Generated
`\ulScoreSystem` inclusions stay downstream of this wrapper, not a second policy
gate or a general-purpose image filter. Printed visibility neither regenerates
scores nor changes recipe clef/tuning/ChordNames, media, cache trust or edition
eligibility. Bass-clef permits scores independently of denied inline notation.

`ulsbs-frontmatter.code.tex` implements the registry's presentation-policy keys in
one dispatch table, resolving the captured reference rather than mutable old flags.
Labels and icon filenames retain public author hooks as unexpanded tokens. Default
preserves authored variable cover icons with or without a star. Non-default policies
replace those slots on each unstarred `\ulCoverPage`, and clear them on a starred
cover; permanent slots and the author's `\ulInsertCoverIcons` output hook are never
changed. The imprint uses the same selected label and current variable icon slots,
including when no cover was emitted. Repeated covers deliberately retain the existing
caller-scope slot mutation contract, not a hidden restore/reset at begin-document.

Shared style applies PDF viewer/color options at load time, but finalizes title,
author, subject, keywords and custom `DocumentVersion` defaults in
`begindocument/before`, after author preamble statements and before hyperref publishes
metadata. Title uses the selected presentation policy: default has no suffix;
other policies append their localized, author-overridable variant label. Presets
do not publish metadata and are not reapplied at this boundary. Explicit preamble
`\hypersetup` keys (including empty values and `pdfinfo` aliases) win per field.
The implementation observes hyperref's existing private `KV@Hyp@pdf...` handlers;
it also preserves nonempty metadata supplied before ULSBS loaded. An explicit
`pdfinfo` `DocumentVersion` wins without discarding unrelated custom fields. These
private hyperref dependencies are covered by generated-PDF tests. `\AtBeginDocument`
and later author metadata calls retain their ordinary ordering after this boundary.

Compiler jobs use this same owned-preset lifecycle. Historical book-type and
mutable variant controls are supported only as migration inputs, not runtime
aliases. Explicit PDF-layer imports retain their early capability setup,
independent of identity and effective ink.

`tests/test_variants.py` covers the reader and data contract, including a standalone
TeX consumer of the same registry, direct/manual/package-only setup, literal errors,
inherited-option rejection, nested outer-class precedence, rendered cover/imprint
policies and finalized localized metadata with author overrides.
`tests/test_modules.py --packaging-smoke` checks source/wheel/sdist byte consistency,
isolated installed Python discovery and manual TeX initialization from installed
assets without checkout-relative runtime access.

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

`ulSongs`, `song`, `\beginsong` and `\endsong` use the same semantic lifecycle.
The inherited three-braced metadata form is removed and migration diagnoses it.
Each `ulSongs` block starts printed
numbering at 1; chapter headings do not reset it. Counter overrides and
`\theulSongNumber` formatting are independent of persistent IDs and occurrences.
Metadata resets execute once before option parsing. Public metadata remains
available after `\endsong` in the surrounding scope; unknown fields and malformed
or nested lifecycles have owned diagnostics. Titles split only on top-level
`\\`; `\ulResetTitles`, `\ulNextTitle` and `\ulForEachTitle` iterate them. Accidental
catcodes change after title scanning, allowing raw `#`/`&` in musical key fields.

Selection activation is distinct from its list: absent selects all; explicitly
empty selects none. A selection declaration matches source IDs (before anchor
suffixing) or printed labels; the first source match claims each key across blocks
and later matches warn once per key. Each block submits its retained boxes in list
order. Source numbering is the default; sequential numbering fills the visible
number panel and navigation metadata slots in each output copy before layout,
and index replay carries the new label and target (keeping explicit index label
overrides). Neither mode reruns source. Index, PSV and TOC writes stay in song
boxes; discarded boxes do not leak records. Intentional repeats get shipout replay
markers without evaluating source or hooks again. ID anchors are
`songid:<id>[-n]`; index targets separately use
`song<block>-<printed-number>.<outline-level>` on the first occurrence of a label
in the block, and `song-repeat-<source-serial>.<outline-level>` on later ones.
ID and number freeze at collection;
physical page and Y resolve at shipout. Only occurrences with transposable ink
enter the multikey manifest.

The body typesets before prelude/postlude, then assembles below the retained
prelude. Attributions compose once in a retained horizontal box and unpack for
paragraph layout; [prelude layout](#prelude-layout) owns title wrapping, badge
space and the save-position marker. Initial public chord-font metrics precede
the shared document font policy. Preserve these boundaries to avoid font-first-use
or anchor changes without replaying source.

Positioning dry-splits copies of completed boxes against actual page contributions
and finite stretch/shrink, then submits real material once. Pending owned
continuations remain distinct from ordinary prose, even after the first page
ships. Empty-page lookahead retains even/odd spread reservations. Song clears use
the saved kernel clear locally, independent of an author's temporary include-clear
override; standard kernel column output stays untouched.

Explicit break commands live in `ulsbs-layout.code.tex`. Inside an active song,
the open-paragraph (horizontal-mode) penalties for `\brk`, `\hardbrk` and
`\forcebrk` are respectively `-5`, `\ulHardBreakPenalty` (default `-500`) and
`-10000`; the last forces a line break, not a page break. At song paragraph/verse
boundaries and outside songs, they request column/page boundaries using
`\ulBreakPenalty` (default `50`), `\ulHardBreakPenalty` and `-10000`, respectively.
All are one-shot: neither stronger command assigns `\ulBreakPenalty` or changes
later requests. Persistent policy requires explicit register assignments.

During selection capture within `ulSongs`, retain in-song break nodes, but suppress
between-song source requests from the `\brk` family. Standalone `intersong` blocks
remain omitted from selection. Selection
configuration alone must not suppress ordinary prose requests outside collection.
The family has no starred forms. Existing `\nextcol` and song-clear stars still
execute at source time; their unstarred forms remain suppressed during selection.
At commit, selection directives `brk`,
`hardbrk` and `forcebrk` use the respective boundary penalties above; `nextcol`
remains forced. Automatic prelude/first-content protection is unchanged and must
not block explicit forced requests.

The shared parity helper first drains pending song/intersong output for both
`\scleardpage` and `\sclearoddpage`. In two-sided mode, a target-parity mismatch
uses the saved kernel physical-page clear symmetrically, including one-column
ordinary prose; there is no legacy spacer exception. Matching parity adds no
extra skip. In one-sided mode, both commands only drain pending owned output.

`\ulColumnBottomGlue` is independent scoped layout policy, initially
`0pt plus .5\textheight` for every named variant and package-only default. It
absorbs unused column space instead of stretching compact lyric lines; visibility
requests never mutate it. Authored renewals (including zero and
infinite-order glue) remain authoritative. `\ulSeparateVerses` locally selects
flush glue and forced stanza breaks. Real break candidates emit positive bottom
glue, the penalty, its separate negative inverse and the retained prior skip.
Combining the latter two in glue arithmetic loses lower orders and can fail to
negate a higher-order stretch. Lua lookahead already models a separate inverse;
both paths now preserve the same authored glue and cancellation contract.

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

### Prelude layout

`ulsbs-song.code.tex` measures each formatted title once and retains its nodes.
Titles that fit keep their horizontal box and existing metrics. Oversized titles
unpack into a paragraph at the actual heading width, after subtracting any song
number panel and reserved badge lane. `\RaggedRight`/`\Centering` permit the active
language's hyphenation; a `vtop` preserves the first baseline, and struts retain
font leading at the ends of wrapped title blocks. Alternate titles remain
separate paragraphs. Explicitly unbreakable content can still overflow.

`\ulTitleBadgeOverlap` defaults to false and uses the ordinary scoped boolean
infrastructure, including `\ifulTitleBadgeOverlap`; it is not a frozen visibility
permission. When false, the widest visible badge row plus `.5em` in the title
font reserves a rectangular right-hand lane. Titles, authors, dedication and
extra info share the remaining width. Attribution/extra text follows the title
immediately, with the caller's font restored and `\hsize`/`\linewidth` set to the
left-lane width. When true, all prelude text has the full heading width. Hidden
badges reserve nothing and execute no display source. Exhausted heading/lane
widths produce an owned warning and a positive fallback width.

Badge rows retain zero advance, height and depth in both modes. Their lower
extent must not push attribution, extra info or verses down; only the text's own
wrapping contributes additional height. Badges keep their existing offsets from
the first title baseline. The PDF UI save-position marker uses that baseline and
the original full heading right edge, independently of title wrapping or lane
width. Measure retained nodes rather than replaying title, badge or style hooks.

The song-number panel keeps the prelude's height and uses trailing `\vss` so
larger number glyphs can extend into the color-box padding without an overfull
vbox warning. This intentional overhang does not enlarge the heading or move
the number, lyrics or anchors.

`ulsbs-multikey.code.tex` pads the key-badge envelope outside its visible frame
to accommodate the transpose arrow, following space and widest tonic/accidental
with a minor suffix in the configured badge font. Ordinary and layered editions
use the same envelope, preserving title wrapping and pagination across keys.
Visible frames and alternative badges remain right-aligned at the original edge;
the alternatives do not add their own layout dimensions. Geometry, source-effect
and anchor regressions live in `test_layout.py`, `test_badge_metrics.py` and
`test_multikey_anchors.py`.

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
that width. Replay stays active and consumes memory even with hidden ink; an empty
hidden anchor consumes following source whitespace without splitting the preceding
interword glue. Disabled measure bars use ignored catcodes. Echo arguments rescan
once while retaining active physical
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
Hidden chord tails (including inline/standalone alternate chord payloads) never
execute, even when pitches or beats remain visible. Stored raw annotations can
therefore replay later under a different local request without losing synchronization.
Hidden pitch voices execute no symbol/tag hooks and contribute no retained boxes.
Hidden beats neither draw their measurement sample nor retain a beat layer; their
extent and drawing both use the effective predicate, not a separate suppression mask.
The renderer measures neutral slots from the base circle dimensions and padding,
without drawing a sample pitch or executing its author hooks. Slots remain nonzero
when pitches are suppressed, so beats after hidden pitches or empty slots keep their
horizontal position. Symbol/tag appearance hooks do not redefine this neutral grid.
The existing circle cache remains font-size keyed; visibility setters do not
recapture early font metrics or alter import allocation. Melody `@` dimensions stay
unexpanded until a visible pitch or beat needs them, then evaluate once per
annotation, never per multikey alternative. Chord ink alone does not activate a
hidden melody's dimension. The raw melody grammar is still validated while hidden.

Source transposition and interactive offsets are separate. `key=` describes the
effective printed original; `t00` preserves that notation and alone supplies
dimensions. Eleven alternatives add visual ink with zero advance. Authored brace
groups remain opaque to transposition. Shared notation-side effects execute once,
not once per layer. Full-score transposition stays in Python/LilyPond.

### Retained geometry and spacing

TeX renders lyric and musical source once. `ulsbs-music.lua`, loaded by the music
module, operates on retained nodes marked with TeX-allocated attributes. Its
paragraph callback resolves physical-line geometry; `finish_verse` applies
stanza-wide minima and repairs interline glue. Interned configuration snapshots
preserve the policy active at collection even after local TeX groups have ended.
Zero-sized multikey overlays do not contribute geometry.

The default-on `\ulLaneAwareAnnotationSpacing` policy marks candidate stacks,
their source-adjacent word links, and independent chord, melody and beat bands.
A pre-linebreak callback compacts complete runs only, retaining already-typeset
lyric, annotation and hyphen nodes. It compares actual vertical bands relative
to the shared annotation baseline, carries earlier reaches until the word ends,
and reserves any remaining overhang there. Synthetic breaks are legal only where
no ink would overhang the break. Authored spacing constructs, unrecognized word
boundaries and runs too wide for the current paragraph keep their legacy widths.
The later geometry passes still own vertical alignment and interline clearance.

`\ulSpace` emits real interword glue, scales its width, stretch and shrink,
and marks it when lane-aware spacing is enabled. A marked space can join two
eligible words in the same pass; ordinary glue remains a boundary. Clearance is
tested at the glue's minimum width. When ink would protrude at a wrap, a
discretionary reserves the missing width only on the broken line, while the real
glue retains its stretch and shrink on an unbroken line.

Unstarred `\ulSpace` also marks its glue as explicit regardless of the lane
policy. The measure renderer checks that marker before removing and restoring
the trailing glue around its break penalty. Consecutive bars use the fallback
`\ulMeasureBarGap` only in the absence of explicit glue; bars themselves still
stop lane-aware runs.

`\ulSpace*` uses the retained lyric advance and intervening lyric-free
annotation stacks to center an authored hyphen. It replaces only a synthetic
hyphen at that boundary and makes the starred discretionary the breakpoint.
Neither marking nor replay is repeated to compute the final width.

Empty annotation runs emit lyrics directly. Beat-only runs use actual ink extents
and the collision gap rather than a full annotation row. Chord/pitch runs keep
their configured annotation baseline and actual box clearance. `\ulChordLineParams`
is the renewable stacking policy; no enabled-but-unused voice or blanket chord
sample reserves height. Hidden melody offsets add no width. The verse `+`
modifier is consumed but has no layout effect, including on `\e`.

TeX stacks annotations at their configured baseline. After line breaking, the
retained walk first tests against the tallest lyric; if clearance is uncertain,
it compares horizontal intervals at their final positions. Only visible chord,
melody and beat ink can request a lift; high circles do not reserve ink down to
the nominal chord baseline. The largest required lift applies to every stack
sharing that physical lyric baseline. Lyrics, horizontal advances and offsets
stay fixed. Explicitly raised/lowered horizontal wrappers form independent
baseline groups; vertical boxes and raw no-lyrics runs retain their placement.
`\ilsl` stacks instead contribute their manually configured TeX clearance.
The stanza pass reuses the resolved geometry without inspecting it again.

`\ulMelodySize` selects the font size for both neutral note slots and rendered
circles. `\ulMelodySymbolStyle` and tag hooks are drawing-only; they are not called
for measurement or hidden pitches. Shared sizing keeps hidden voices, rests and
beats on the same horizontal grid. Circle metrics remain font-size cached, not
the rendered labels. `\ulMelodyAccidentalFit` adjusts only glyph placement for
the four targeted spellings after transposition, without changing the shared
metrics or cache key.

Measure and spanning-repeat policies select by logical occupied level: lyrics or
beats (0), chords or low hints (1), normal melody (2), high melody (3). Hidden
pitches/rests do not create higher levels. `\ulMeasureBarTop{level}{reference}{scale}`
and `\ulRepeatBarTop` choose a reference and scalar for each level. References use
lyric A (0), chord-font A at its annotation baseline (1), or a melody circle's
bottom and diameter (2/3); target top is `reference bottom + base * scale`.
Missing selected melody references use nominal lane positions and retained circle
metrics, not another rendering. `\altchords` bars use level-zero policy.

`\ulUseVerseAnnotationMinimum` can promote zero-level lines of an annotated verse
to a one-level minimum without adding chord labels. Entirely zero-level
verses remain compact. `\ulRepeatBarBottomScale` sets depth in lyric A units.
`\ulRepeatBarMinimumGap` separates completed same-column repeat strokes; it excludes
nested or continuing segments, and zero disables it. `\prep` uses the highest
occupied reference bottom with its authored fallback. Retained meter boxes are
consumed once; geometry repair never re-renders their tokens.

When a lyric paragraph wraps within a repeat, the paragraph callback copies its
retained repeat prefix at the same horizontal position as a zero-width overlay on
each wrapped line. The stanza pass attaches the `\endrep` marker to the last line
before page/column splitting. Shipout coalesces the fragments per physical
segment and adds continuation dashes only where an endpoint is missing.

Inline `\lrep`/`\rrep` signs retain lyric dots and the authored rule width and
depth. On all physical lyric lines, the rule uses the measure-bar target,
including the optional stanza annotation minimum. Visible annotations or a
promotion to that minimum add upper dots at `\ulChordLineBaselineSkip` and a
floor just above them. The WithChords adjustment supplies another minimum when
upper dots are present. Outside stanzas, the standalone height adjustments still
follow chord visibility.
Repeat signs do not re-evaluate source or join transposable alternatives.

`\ulVerseBaseline{natural}{stretch}{shrink}` and `\ulVerseSeparation` evaluate scalar
expressions in the configured lyric font and cache the resulting glue in capital-A
units. Configure them after font customization; presets and later author calls
select policy. Setters validate all arguments before changing state and respect
grouping. Read-only `\ulVerseSpacingScale{baseline|separation}{natural|stretch|shrink}`
supports relative settings. After fitting the line boxes, lyric-line glue is the
nominal baseline minus the preceding depth and next height, clamped to the
larger of `\ulVerseMinimumGap{length}` and the enabled
`\ulVerseBaselineToTopGap{length}` minus preceding depth. This replaces the
ordinary `\lineskip` fallback for lyric verses; finite shrink stops at the same
floor. The ink gap also supplies an additional inter-verse boundary gap.
Implicit final lines finish before stanza scope restores, so they keep their
captured policy.

Translation stanza entry restores `\normalbaselineskip` before stanza hooks;
its small-font selection and `\ulTranslationFont` then select leading, which
`\ulTranslationBaselineMultiplier` scales without stretch or shrink when different
from `1`. The default leaves the hook's leading untouched, including custom
stretch and shrink. Translation line fitting still uses the font-leading fallback
and the verse ink-gap floor.
Explanation, passage and starred passage restore normal leading after selecting
their font, then apply their existing multipliers without baseline stretch/shrink.
The alternate passage style is `\begin{passage}*[LANG]{title} ... \end{passage}`.
These blocks do not install the cached verse baseline. Their language, raw-newline,
wrapping, hook and minimum-gap behavior remains separate from nominal leading.

Early initialization retains its pre-typography chord sample solely for font
allocation and PDF range identities, not as a leading strut. Number/title
measurements, early verse indent and later passage `em` captures retain their
respective font contexts. Feature switches do not reallocate fonts or recapture
unrelated dimensions. Live defaults belong in their phase/subsystem companions
and the selected presets, not duplicated numeric tables here.

### Chord diagrams for guitar

`ulsbs-diagrams.code.tex` owns `\gtab{name}{spec}`, its source-transposition
fallback and deferred chord-annotation insets. `ulChordDiagramGrid` is a reusable
layout environment around ordinary `\gtab` calls. Its sole optional argument is
the dimension used for the row gap and minimum column gap, defaulting to `1.5pt`:
`\begin{ulChordDiagramGrid}[1.5pt] ... \end{ulChordDiagramGrid}`. There is no
author-facing column-count setting.

The environment consumes input incrementally rather than capturing its whole
body. Each `\gtab` must establish its accidental catcode scope before reading
the name, and its colon scope before reading the specification; raw `#` and `&`
therefore retain their ordinary diagram-name meaning inside the grid. Each item
is measured and rendered exactly once, and its finished box is retained for
layout rather than replaying source tokens or invoking the renderer again.
The collection frame uses global assignments so grouped per-item font, fret-count
and transposition settings do not discard collected entries. Nested grids are
rejected. Output clears the frame and retained nodes; register slots are reused
across subsequent grids instead of allocating a new set each time.

Available width is the smaller of the current `\linewidth` and `\hsize`.
The widest retained item determines the minimum cell width; available width and
gap determine how many columns fit. Spare line width is distributed into equal
cells once for the whole grid, rounded down to scaled points to prevent overruns.
Partial rows use the same cells, leaving later columns empty instead of spreading
their entries independently. This horizontal spreading does not change row gaps.
In grids only, titles omit their outer thin spaces. The existing `3pt` bottom
padding remains; standalone diagrams keep their historical metrics. The row gap
and minimum column gap are added once. A diagram
wider than the available line is proportionally reduced and placed alone;
diagrams that fit keep their native size. Plain `\\` forces the following item
onto a new row, preserving authored chord-family boundaries. Leading, repeated
and trailing breaks do not create empty rows. Rows are emitted with page-break
opportunities between them rather than enclosing the whole grid in an unbreakable
box.

Each grid item's baseline is the fretboard's nut/top-fret rule, not its title,
open/mute marks or overall box edge. Row layout preserves that reference across
different fret counts and finger-label/title extents, so neighboring fretboards
do not shift vertically. This alignment is local to the grid; existing
standalone and inline `\gtab` appearance and annotation-inset behavior remain
unchanged.

Source-transposition dispatch is unchanged: offsets congruent to zero modulo
12 retain the diagram; other offsets invoke `\gtabtrans{name}{spec}`, whose
default emits only the transposed name. The fallback's local direct-draw
`\gtab` binding still permits a custom replacement without recursive dispatch.
The grid is layout, not a set of twelve interactive fingerings: diagrams remain
outside multikey PDF switching.

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
category, log path, occurrence count, optional affected-item count and a final
`severity` field defaulting to `warning`. Multiline continuations form one
record; whitespace-normalized identical messages are grouped with their
occurrence counts. Job warning totals sum only `warning`
occurrences, not distinct messages, log lines or raw matches of the word "warning".
Callers with artifact-level knowledge may attach `affected_count` (for example,
eight songs missing IDs); that count is separate from the warning total. Compact output
aggregates by source/category; verbose output shows messages and occurrences.

`pipeline.py:analyze_warnings` collects selected tool logs, including LilyPond,
and only the final LuaLaTeX invocation, not superseded typesetting passes.
Convergence reruns respond to specific recognized requests in the latest TeX log,
not arbitrary warnings. Closing TeX reference/font recaps are suppressed only
when their corresponding specific warnings occur in the same parsed text.
Missing glyphs and overfull boxes retain `warning` severity. Underfull horizontal
and vertical boxes have category `spacing` and severity `advisory`. Advisory
totals also sum occurrences, not distinct grouped records; the computed
`ParallelRunResult.total_advisories` includes successful and failed job diagnostics
without changing the result constructor, warning totals or success status.
Both ordinary and multikey jobs classify their own final typesetting diagnostics
independently. Each job prints an informational spacing-advisory count at either
verbosity, with grouped messages only in verbose output and shared log links
printed once across warning and advisory levels. The CLI reports a separate run
total and links retained reports even for advisory-only runs. Configuration,
resource and cleanup advisories recorded by the run-level UI remain independent
of both per-job classifications and their totals.

Per-job `<book-basename>_DIAGNOSTICS.json` reports retain the existing warning-only
`warnings` array and add a separate `advisories` array with the same record fields,
occurrence counts and host-mapped message/log paths. Reports remain under
`result/diagnostics/` after successful temporary-directory cleanup; full tool logs
still require `--keep-temp`.

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

## Performance Optimizations

On **2026-11-17**, a performance-optimization investigation assessed ten ideas for
reducing compilation time without changing the resulting books or media. One was
implemented; the other nine were not retained because their measured benefit was
too small, their correctness checks failed, or the required complexity outweighed
the likely saving. Compiler timing reports were added separately to support the
investigation; those reports measure performance rather than improve it.

### Implemented: parallel engraving of alternative score keys

MULTIKEY books need additional LilyPond scores for different transpositions.
Previously, each book generated these alternatives sequentially, even when other
compiler workers were idle. Independent score/transposition tasks now use spare
workers in the compiler's existing shared pool. The owning book pauses without
holding a worker, then resumes once its tasks finish. They share the normal worker
and memory limits; there is no nested pool. Fallback attempts for one transposition
remain sequential, results retain their original order, and only the owning book
reports diagnostics. See [Build jobs and publication](#build-jobs-and-publication)
for the scheduling and cancellation contracts.

Repeated alternating before/after CLI measurements on a six-song Unilaiva book
reduced median batch time from about **168 to 101 seconds with an empty score
cache**, and **101 to 87 seconds with a populated score cache**. Output checks and
representative visual inspection passed. The improvement comes from doing more
work at once, using additional CPU and memory within the existing budget, not
from eliminating engraving work. When all workers were already busy, or all
requested alternatives were cache hits, measurements showed only small timing
differences rather than a comparable speedup.

### Not retained

- **Skip repeated checks on cached alternative scores.** The checks cost less than
  a millisecond per hit. Removing them offered too little benefit to justify more
  complicated rules for deciding when a cached result is safe for the current job.
- **Share input/toolchain fingerprints across jobs in one compiler run.** This
  would avoid repeatedly hashing fonts, tools and dependencies, but those inputs
  can change during a run. Safely detecting changes added complexity that was not
  justified by the measured saving.
- **Persistently cache original LilyPond snippets.** The tested lilypond-book cache
  omitted required MIDI and musical-boundary files, and reused stale output after
  an included source changed. Making reuse complete and reliable required more
  cache machinery than the measured benefit justified.
- **Remember rejected transpositions so later builds do not try them again.** Even
  an ideal shortcut saved only about a second on the small parent fixture. A safe
  implementation would also need to distinguish reproducible rejections from
  temporary tool or resource failures; the existing warning alone was not proof.
- **Do not draw alternative keys for songs excluded by a selection.** This had
  useful timing potential, but changed output when notation from an excluded song
  was saved or copied and later printed elsewhere. Excluding a song does not prove
  that every piece of notation constructed inside it will be discarded.
- **Cache repeated numeric key-spelling calculations.** The calculations were
  cheap. Local savings were small, and whole-pass timing differences were too
  variable to establish a worthwhile compilation speedup.
- **Skip chord-fitting work when shrinking is disabled.** Savings were small, and
  the tested shortcut produced incorrect alternative sizes when the shrinking
  policy changed between constructing and fitting the notation.
- **Reuse verse geometry instead of walking the retained layout repeatedly.** The
  repeated walks cost only milliseconds. Tracking when layout nodes had changed
  or been copied would have added more complexity than that saving justified.
- **Extract PDF page ranges in parallel.** Actual qpdf extraction took only about
  7 ms for the generic fixture and 89 ms for the six-song parent fixture. Both
  produced just one range with the normal page limit. Most of the parent's roughly
  16.3-second packaging time was resource/dependency validation, not extraction.
  Even forcing twelve ranges spent only about 1.42 seconds in extraction plus
  qpdf checks, too little to justify additional scheduling and cleanup machinery.
  Extraction remains serial, with all validation intact.

These conclusions apply to the bounded experiments, which used independent
generic fixtures and small Unilaiva cases. They do not establish performance for
every larger book or predict a speedup for the complete collection. None of the
nine rejected shortcuts is active in the engine.

## Multikey Books

### Build jobs and publication

`Job.variant` identifies the default, lyrics-only, or instrument variant;
`Job.multikey` is a separate boolean selecting the multikey edition. Each
selected variant has an ordinary job. Registry edition support controls companion
jobs when `multikey-books` is enabled: default and instrument variants support
multikey; lyric remains ordinary-only. This is a generation restriction, not a
different level in the variant hierarchy. Main-source availability and generic
selection determine the identities, independently of TeX feature visibility.

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

At the supplemental-score boundary, compilation returns a private resumable
handoff and releases its executor worker. The suspended generator retains its
job lock and local files, but no execution-context scope or worker allocation.
The coordinator admits independent score/offset chains to the SAME executor and
`max_parallel`/container-memory budget as normal stages. Each chain keeps its
preferred/octave retries sequential. Chains have private results, diagnostics
and timing collectors; only the resumed parent assembles bindings and reports
actionable warnings/debug information, in original request/offset order. Child
work emits no compiler progress, start, completion or success output.

An ordinary build uses the same handoff only if its draft pass requests a score
for a selected song with a changed key. The initial `lilypond-book` pass is
unchanged. The compiler resolves requests against that run's systems inventory,
captures original breaks on demand for multi-system scores, and binds accepted
replacement graphics directly without layers or changes to the generated
fragments. It clears selection requests and bindings before each build.

Admission is bounded to active capacity, not an eagerly submitted whole-book
backlog. Ready parent resumptions and packaging have FIFO priority, followed by
FIFO children, then FIFO unstarted books. Each parent yields a finite child batch
with finite retries, so started work drains and unstarted books eventually
progress; admission does not preempt already running stages. At one slot, parents
suspend, children run serially, then parents resume without a waiting worker.
Unexpected child errors cancel unadmitted siblings and drain admitted siblings
before the parent unwinds/releases its lock. SIGINT stops admission, cancels queued
work, terminates/reaps scoped command process groups (including descendants), joins
workers, and closes even handoffs returned at the interrupt boundary. Tests live
in `test_supplemental_scheduler.py` and `test_lilypond_scores_staged.py`.

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
Consumer catalog variant identifiers use canonical `lyric`, not `lyrics`;
ordinary song/database `lyrics` fields, consumer view IDs and labels, and the
deliberate `_LYRICS-ONLY` output marker are distinct and need no blanket rename.
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

Deployment preflights package identities before copying the group and can include
the paired ordinary PDF in the same rollback boundary. Result-list records and
ordinary JSON references remain the caller's responsibility. Index-last ordering
and rollback do not provide atomic multi-file visibility to concurrent HTTP
readers. A live site needs an atomic edition-directory deployment for a consistent
ordinary-PDF/index/ranges snapshot. The packager rejects unsupported numeric or
direct-page Link destinations rather than attempting automatic normalization;
the protocol's permitted normalization is not an implemented fallback.

With either strict PDF deployment requirement enabled, the deployer uses a
per-variant inventory. A committed ordinary job records its source/variant
eligibility and PDF/JSON digests; a committed multikey job records the index and
updated ordinary JSON digests. Deployment trusts only records from the selected
run and verifies their content. Incomplete or invalid edition groups are skipped
individually. Required and other advertised edition files share a rollback
operation, with ordinary metadata installed after the index. Independent output
records and the rule against automatic deployment after any build failure are
unchanged.

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
Layers are `true` only for supported multikey jobs and `false` for ordinary
jobs. Manual LaTeX compilation defaults to layers `false` and UI `native`.
Manual builds may define `\newcommand{\ulPdfTranspositionLayers}{true}` before
class/package loading; pipeline-driven sources must not duplicate its definitions.

The explicit load-time value alone enables the renderer and its early `ocgx2`
import, independently of legacy identity, named presets and effective inline or
score visibility. Imports stay before phase-two layer state and font allocation
stays in its existing order. Later preamble/local visibility changes cannot revoke
or retroactively enable this capability. Manual class and package-only default
entry paths share this low-level option; it is not a compiler edition selector or
publication authorization, even with a named lyric preset. Registered edition
eligibility remains the compiler's responsibility: lyric multikey jobs are rejected.

A companion candidate whose source explicitly sets layers `false` before loading
the renderer, or does not load the renderer, reports disabled capability. It is
skipped without publishing an ordinary PDF under a multikey name. An enabled
renderer whose valid songs currently hide all transposable ink instead reports an
enabled manifest with no transposable content; it need not allocate any OCGs.

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

#### Compiler timing diagnostics

`timing.py` provides `measure(name)` as a context manager or decorator and
`collect(Timings())` as an explicit worker-local collection scope. Timers use
`time.perf_counter()`, aggregate call counts, elapsed seconds and escaping
exceptions by stage, and are no-ops outside a collection scope. Nested stages
are **inclusive**: never sum parent and child totals. Exceptions handled inside
a stage (for example a recoverable cache miss) do not imply a failed build.
There are no per-call progress lines, raw event traces, CPU sampling or new
dependencies. Diagnostic write failures do not change compilation outcomes.

Each compiler job writes `<basename>.ulsbs-timings.json` in its compile directory.
MULTIKEY compilation passes the same collector to its later packaging worker;
that worker updates the report, including failed or skipped packaging. The
top-level `elapsed_seconds` and job success duration sum `job.compile` and
`job.packaging`, excluding initial scheduler queue time and dependency/packaging
queue waits. Stage time includes any tool contention or job-lock waits within
that stage. Failed/interrupted workers retain completed and unwound stage data
when their compile directory is writable. A compiled companion blocked by an
ordinary failure can retain status `compiled`: timing status is a phase status,
not the authoritative final run outcome.

Resumable compilation aggregates active parent stages plus the supplemental
handoff interval into `job.compile`; `scores.generate` includes preparation,
the child batch's critical-path wall interval and ordered assembly. This interval
includes supplemental admission/continuation waits, not a blocked parent worker.
Child collectors are merged only after they drain. Their per-candidate/engraving
elapsed totals sum overlapping command wall times and can exceed `scores.generate`;
they are not CPU measurements or additional end-to-end elapsed time. Interrupted
suspended parents retain their timing report when cleanup can write it.

The run report is `<unique-id>.ulsbs-timings.json` in the temp root. It records
`run.jobs` and total compiler-process elapsed time from CLI entry through output
finalization and cleanup, just before the final summary. This includes queue
waits, but excludes host-side container image/startup time and deployment after
the compiler summary. Parallel job durations overlap and must not be summed to
infer run time. The summary rounds to whole seconds with minute carry; job
messages use two decimal places and a locale-independent decimal comma.

These reports are private schema-version-1 JSON diagnostics with `clock`,
`kind`, `status`, `elapsed_seconds` and a `stages` mapping whose entries contain
`calls`, `elapsed_seconds` and `failures`; run reports also record `jobs` when
available. They are never copied into result inventories, caches or published
metadata. Normal successful temp cleanup removes them; use `--keep-temp` to
inspect or compare them. Do not recreate a cleaned temp directory just to write
a run report. Interrupted compiler runs retain a run report where possible.

Instrumented boundaries include original LilyPond processing, each numbered
LuaLaTeX pass (including convergence retries), PDF font optimization, exports,
diagnostic analysis and multikey packaging. Supplemental score stages separate
`scores.generate`, `scores.toolchain`, `scores.source-fingerprint`,
`scores.candidate`, `scores.cache.restore`, `scores.cache.load`,
`scores.cache.publish`, `scores.validate`, `scores.dimensions` and
`scores.engrave`. Restore includes cache load; candidate includes restore or
engraving/validation; dimensions includes calls from variant validation. Read
the existing score-results counters alongside these timings to distinguish
cache hits from newly engraved and rejected candidates.

For an optimization experiment, use a small independent representative fixture,
the same sources/toolchain/parallelism, and equivalent cold or warmed caches.
For a normal parent build, explicitly pass `--plain-output --no-deploy
--keep-temp`; select variants and multikey behavior deliberately (`--quick`
excludes multikey). Compare repeated alternating baseline/candidate runs using
medians and end-to-end cost as well as the affected stage. These wall-time
aggregates locate promising boundaries, not individual TeX/Lua hotspots; add
only narrowly scoped temporary profiling when a candidate requires it. Retain
no benchmark archive by default. Tests for the collector/reporting contract
live in `tests/test_timing.py` and the compiler reporting/scheduler tests.

The renderer uses `ocgx2`/`ocgbase` named `/Properties` resources for marked
content. Every `/OC` marked-content name must resolve to an actual catalog OCG.
An experimental inline OCMD approach with indirect references embedded in content
streams was rejected: PDF.js accepted it, but Poppler reported syntax errors,
and PDF rewriting could not safely renumber those embedded references. A clean
`qpdf --check` alone is not sufficient evidence of correct layer rendering.

### Opt-in score layers

`multikey-lilypond-scores` defaults to `false` and only affects supported multikey
jobs. Eligibility is registry-owned, not inferred from inline chord visibility.
Originals still use the normal LilyPond pipeline. The focused
`lilypond_scores.py` module wraps generated per-system graphics inclusions with
snippet identities while preserving their existing inter-system break tokens.
Repeated references to the same system retain their original placements.

Generated `*-systems.tex` inputs install a scoped graphics adapter through the
LaTeX file hooks in `ulsbs-media.code.tex`. It retains each included system once,
preserving the authored graphics command, star and optional arguments. The shared emitter
shrinks a retained box proportionally only if it exceeds the smaller of
`\linewidth` and `\hsize`; fitting systems remain unchanged. The override ends
with the system file, so unrelated images retain their original behavior. This
also covers bare LilyPond-file output outside `lilywrap` without changing generated
files or relying on graphic filename hashes.

The layered renderer bypasses this adapter while measuring the original and
alternative graphics at natural size. After applying the existing alternative
acceptance policy and assembling all layers, it applies the same display-width
limit to the complete system box. Ordinary and layered editions therefore retain
the same displayed dimensions without weakening the alternative-scale threshold.

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
original notation instead of introducing another alternative-scale policy. The
shared display-width limit applies independently.

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

Full passes overlay each system in its existing occurrence-specific OCGs, keeping
the original box and anchoring the alternate ink at its displayed top left.
After pagination, Lua takes the smallest width/height fit limit of the systems
of each score placement and key on the physical page, then applies that scale
to their drawing matrices. Limits include the original's ordinary line-width
cap. This changes no TeX dimensions, even when a score spans pages or columns.
Score overlays reuse the public OCG names and metadata contract described below.
The original LilyPond justification settings are retained, including per-snippet
overrides; both standard heads explicitly set `ragged-right = ##f` and
`ragged-last = ##f`. A shared scale preserves the relative lengths of the engraved
systems, rather than stretching shorter systems to match longer ones. Height
also constrains the scale so the overlays cannot overlap adjacent content.
If a validated graphic later disappears or no longer fits, the TeX renderer's
last-resort per-system guard substitutes that original system at its displayed
size; it does not constrain the scale of the remaining alternatives. Python
validation normally rejects the entire offset before dispatch. LilyPond spelling
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

**The score cache and the trusted-asset manifest are two different things.**
The cache stores already-engraved **alternate** scores so the next build can
skip that work. The manifest, [`lilypond-score-cache-assets.json`](src/ulsbs/assets/lilypond-score-cache-assets.json),
records which bundled LilyPond files and generated copies have been reviewed
for caching. It does not store scores or list supported LilyPond versions.

For each alternate score, ULSBS asks two questions:

1. **Can this score be cached?** ULSBS checks the score and its includes. The
   manifest supplies SHA-256 hashes for reviewed files, including bundled files
   containing Scheme that the cache would not otherwise accept. An unknown hash
   can make an affected score ineligible for caching. A missing or malformed
   manifest disables score caching. Neither case stops engraving or bypasses
   score validation.
2. **Do we already have the result for these exact inputs?** ULSBS computes a
   cache key from the score, its dependencies, layout and transposition inputs,
   and the LilyPond toolchain. If a keyed input changes, the old entry no longer
   matches. ULSBS engraves the alternate and caches it if it passes validation
   and is eligible. There is no manual refresh step.

##### When to do something

| What changed? | What to do |
| --- | --- |
| You edited a song, its includes, or its layout. | Nothing for ordinary edits. ULSBS uses a new key when a relevant input changes. Custom Scheme or unresolved includes may make a score uncacheable; don't add song code to the bundled manifest just to get a cache hit. |
| You upgraded LilyPond or changed fonts, but the bundled files stayed the same. | Nothing. The toolchain is fingerprinted separately. No new manifest entry and no need to clear the cache. |
| You added, edited, or removed a bundled `.ly` or `.ily` file in `src/ulsbs/assets/ly/`. | Review the change, then rewrite the manifest's `assets` map. No need to clear the cache. |
| A supported workflow now generates a different asset that should be cacheable. | Review the generated file and record its hash in `variants`. Remove obsolete variants after review. No need to clear the cache. |
| You want to test from a cold cache or remove corrupt cache entries. | Run the compiler with `--clear-score-cache`. This clears the container cache by default, or the host cache with `--no-container`. It does not edit the trusted-asset manifest. |

##### Why there is a `convert-ly` entry

The normal compiler container uses LilyPond 2.24 and reads the bundled
`ulsbs-internal-common-tail.ly` as-is. Its hash is already in `assets`.
Some integration tests run against a newer LilyPond on the development machine.
They use `convert-ly` on a temporary copy of the tail because LilyPond 2.26
removed the old `set-global-fonts` API. `common-tail-convert-ly-2.26.0` is the
hash of that **converted file**, not of the `convert-ly` executable. Normal
builds don't run `convert-ly`, and there is no separate Docker 2.24 variant to
record.

The other shipped variant, `midi-disabled`, covers the exact comment-only file
the pipeline substitutes for the MIDI include when MIDI is disabled. Two small
changes to copied assets are already recognized without separate entries:
inserting the standard charango tuning line and appending the score-boundary
include. The trust check ignores those exact changes, but the cache key still
includes the complete modified file contents.

##### Check the manifest without changing it

Run these commands from the engine checkout (`ulsbs/`, the directory containing
`pyproject.toml`):

```bash
# Check the bundled assets.
PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache

# Check the copies used by one job, or a single generated file.
PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache /path/to/job/ulsbs-assets/ly
PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache /path/to/converted-tail.ly
```

Inside a normal compiler shell, `PYTHONPATH` is already configured, so use
`python3 -m ulsbs.lilypond_score_cache` without the prefix.
The audit is a maintainer tool; it does not have a separate console command.

The audit prints `TRUSTED` or `UNTRUSTED`, the SHA-256 hash, and the path for
each file. A directory argument checks the `.ly` and `.ily` files immediately
inside it. The hash may differ from `sha256sum` for job copies because the
audit ignores the two known changes described above. Exit status is 0 if all
checked files match known hashes, 1 if any hash is unknown, and 2 if the audit
could not run (for example, a missing file or an invalid manifest). This is a
hash check, not a proof that a score is cacheable or that its Scheme is safe.

When a job requests score alternatives, it runs this check once on the copied
assets. An unknown file produces one warning for that job, not one per score or
key. Verbose output adds the hash and the audit command. Ordinary editions and
jobs without alternate-score requests don't run the check. Custom song Scheme
is handled separately by the per-score checks and debug diagnostics.

##### Update the manifest after review

Review the file changes and their dependencies first, especially any Scheme
that reads files or environment variables not tracked by the cache. Rewriting
the manifest records approval; it is not a safety check. For changes to the
bundled sources, run from `ulsbs/`:

```bash
PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache --rewrite
```

In the manifest (schema version 1), `assets` lists hashes by bundled filename
and `variants` lists hashes by generated variant name. `--rewrite` replaces the
whole `assets` map in one operation, dropping entries for removed files. It
preserves `variants` unless you explicitly update a named variant. It always
reads the bundled sources next to the Python module, not a job directory.
`--manifest FILE` selects a different manifest to read or write without changing
where the tool finds the bundled sources.

If you changed the common tail and still need to cache the 2.26.0 test fixture,
regenerate that copy too. With `convert-ly` 2.26.0, write the converted output
to a separate file, leaving the bundled source untouched:

```bash
convert-ly -f2.24.4 src/ulsbs/assets/ly/ulsbs-internal-common-tail.ly > /path/to/converted-tail.ly
```

Review the converted file and its dependencies, then record it:

```bash
PYTHONPATH=src python3 -m ulsbs.lilypond_score_cache --rewrite \
  --variant common-tail-convert-ly-2.26.0=/path/to/converted-tail.ly
```

`--variant NAME=FILE` adds or replaces a single named variant. It requires
`--rewrite`, so it also refreshes all bundled source hashes. Review both sets
of changes. Neither audit nor rewrite runs LilyPond, Scheme, or `convert-ly`.
Before committing, audit the files again, review the manifest diff, and run
the cache and relevant score regression tests.

#### Cache Validation

Only successful, validated alternatives are saved. ULSBS writes each entry in
a private staging directory and renames it into place in one operation, so a
concurrent build cannot read a half-written entry. On a cache hit, ULSBS checks
the hashes in the entry, then rechecks the log, PDFs, crop boxes, fit limits,
and musical boundaries. It copies the files into the job so edits to the job
copy cannot change the cache. If an entry is missing or corrupt, ULSBS tries to
engrave the alternate normally. If the cache is unwritable, the job can still
use a freshly engraved result. Failed engraving attempts are not cached.

Original scores are still engraved normally. In the score results file,
`engravings` counts actual engraving runs, `cache_hits` counts reused results,
and `attempts` counts candidates considered, including retries.

##### Original engraving and job files

Even when the alternate-score cache is warm, lilypond-book starts with a fresh
`_lp-source` directory containing the configured main input and engine asset
aliases, not previously processed imports. Source discovery and the LaTeX
geometry probe skip the job's generated root, content, and include search paths
so old output cannot be mistaken for current input. Probe outputs stay inside
the job, and `_lp` is cleared before each invocation. Source directories do not
need to be writable.

Two safeguards keep lilypond-book's output tied to the current sources:

- The private `lilypond_book.py` launcher processes each generated TeX output
  path once. Without this guard, LilyPond 2.24 and 2.26 can append a document's
  contents again when they encounter a repeated input. The launcher preserves
  every TeX input command, so repeated song occurrences stay independent. It
  doesn't change snippets, transformations, or installed toolchain files.
- Each successful run writes `<job>.ulsbs-lilypond-systems.json`, a private list
  of the current systems fragments, relative to the job. Score preparation
  uses this list rather than scanning for old files that no longer correspond
  to a score. Graphics left in the job directory are not cache entries.

Both lilypond-book and its engraving subprocess receive the source include
paths, so `\lilypondfile` references resolve from the original sources.
External snippets use content-hashed filenames just like inline snippets.
This avoids collisions when different external scores share a basename.
`--use-source-file-names` is deliberately omitted: with the shared engraving
and output directory, LilyPond would leave TeX references to files it did not
create.

Warm-build regressions check that source edits, dependency edits, preamble
geometry changes, and removals take effect; that repeated or nested inputs and
engine aliases resolve correctly; and that source trees stay clean. They also
check that failure to engrave an original remains fatal. Other integration
tests cover page-spanning overlays, exact boundary replay, original callbacks,
note-name languages, major/minor/chromatic material, source transposition,
slash chords, both voices, charango tunings, bass clef, tablature retries,
external scores resolved through TeX, and reuse from a fresh job directory.

##### Editor source mapping

SyncTeX is enabled by default for ordinary PDFs in both regular and quick builds.
The effective `synctex` boolean follows project and profile configuration unless
overridden by either mutually exclusive CLI flag, `--synctex` or `--no-synctex`.
The private `lilypond_book.py` launcher observes the resolved input paths and the writer's
actual replacement chunks without changing their output. `synctex.py` maps
copied lines using each chunk's original character offsets, accounts for the
graphics import and the compiler's preamble, and anchors generated snippet
expansions to their opening line. Generated score fragments can be shared by
multiple snippets; their own source positions are not remapped to LilyPond notes.

After the final full LuaLaTeX pass (including convergence retries) and the
geometry-preserving PDF optimizer, the sidecar writer rebases original paths to
the host, coalesces tags for reopened inputs, and recomputes the SyncTeX v1 byte
anchors without touching geometry. A missing or incompatible mapping produces
a warning, not a failed PDF build. The sidecar is placed before the atomic PDF
replacement and is omitted from deployment inventories. A new ordinary PDF
published without SyncTeX invalidates any previous sidecar of the same name.
`tests/test_synctex.py` checks the sidecar format and both directions against a
real multi-file book with LilyPond preprocessing.
The experimental TeXstudio resources in `editor-support/texstudio/` are a
curated authoring subset, not a second language definition. Run
`python3 editor-support/texstudio/check_cwl.py` from the engine checkout to
check the option tables against the TeX registrations.

### Layer protocol

Layers transpose verse chords, inline `\ac` references, pitched melody hints and
the declared `key=` badge. Recommended singing keys (`gk=`), standalone
`\altchords`, prose and chord diagrams do not switch. LilyPond notation switches
only with the separate score opt-in. The stock bass-clef setup hides inline
chords and pitches; enabled key badges or opted-in scores can still supply
transposable ink. Original notation determines layout and
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

The bass-clef preset disables inline chords and pitches but preserves authored
key-badge policy and permits whole scores. Visible key badges or opt-in score
layers can therefore supply transposable ink without inline annotations. An
occurrence with no transposable ink allocates no OCG family and is omitted from
`songs`. More generally, discarded boxes can allocate unused OCGs
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
melody/beat conversion below.
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

### V2 naming and semantics

The [v2 migration instructions](README.md#ulsbs-migrate-syntax-v2) describe the
combined v2 upgrade.
`src/ulsbs/tools/naming_v2.py` is the authoritative naming
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
Visibility permissions are preamble-only and freeze at `begindocument/before`;
proved direct body assignments become grouped local requests. Other supported
boolean settings retain their own scope. Readable effective predicates
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

The semantic planner in `migrate_syntax_v2.py` composes naming, availability,
scope and identity proposals against the ORIGINAL source. `_EditPlan` retains
source offsets; `migrate_text` invokes `_apply_edit_plans` once, after all proposals
and diagnostics. No intermediate renamed source is semantically rescanned.
Conflicts or any review diagnostic reject the whole file, preserving original
file/line/column coordinates and suppressing partial diffs/writes. Other safe
inputs may proceed. Already-v2 inputs use the same transaction and validation.

Bounded semantic conversions are:

- One leading standalone literal `ULSBS-EXTRA-VARIANTS` marker before a proved
  direct main class without existing availability becomes a literal declaration.
  It preserves historical `default,lyric` plus the listed supported instruments;
  `none` removes instruments only. Absence of a marker does not infer companions.
- Direct literal body display setters, in either naming generation, become local
  requests for all 21 canonical visibility features. Execution and body phase need
  positive proof; recognized arguments are consumed according to their supported
  grammar. Closing a group does not repair proof lost to unknown macro arity or
  mutation. Valid current preamble policy setters are not blanket-rejected.
- Supported literal removed body measure assignments become measure requests.
  Removed queries and unsupported preamble assignments remain review-only.
- Balanced instrument-only raw conditional pagination trees become braced
  `\ulIfVariant` calls. Branches may contain only supported zero-argument page
  boundaries, nested instrument tests, whitespace and comments. The planner
  preserves whitespace swallowing with `\relax`, without adding execution groups.

Mutable identity, ambiguous chorded/lyric-only capability tests, broad historical
`\chordsoff`, conflicting/nonleading markers, computed declarations, unsupported
hooks/references/definitions, unknown phase/arity and arbitrary conditional payloads
remain diagnostic-only. Naming's safe reference/definition conversions remain
supported where applicable. This is not arbitrary TeX interpretation: expansion,
custom catcodes and unseen includer/custom-class behavior remain outside the
proof boundary. Manual review must select identity or effective feature semantics.

Repeatable explicit `--config-file FILE` is diagnostic-only in ALL modes, including
`--write`. It reviews root/every-profile selectors, normalized key collisions and
profile composition, with original coordinates; it emits no conversion counts,
partial config diff or writes. Selected config bytes, inode, mtime and mode remain
unchanged, including cross-role aliases with source/tag inputs. It neither follows
book paths nor discovers configs or shell commands. Removed category settings need
manual migration to `variants` after source-availability review; do not guess a
global selector from old booleans.

CLI requires exactly one of `--check`, `--diff`, `--write` and explicit input(s).
Check fails for pending edits or review/I/O failures; diff/write fail for review/I/O
failures. Traversal failures are reported rather than silently skipped. Directory
scans prune generated/VCS paths and structurally recognized nested engine roots;
explicit files/subdirectories are intentional scopes. Source/tag writes preserve
permissions and newlines and use per-file atomic replacement, not a project
transaction. Symlink components and nonregular leaves are refused; nonblocking
opens plus descriptor regularity checks reject substituted FIFOs. These checks
are not a descriptor-anchored filesystem sandbox: hostile concurrent ancestor
replacement remains outside the bounded contract.

## Testing

From the ULSBS source directory, run `./ulsbs-test`. The runner builds the normal
Docker or Podman `ulsbs-compiler` image when needed, runs LuaLaTeX regressions
through `l3build`, and runs compilation/PDF-structure tests through Python's
standard-library `unittest` runner.

The default command runs the whole retained regression suite, not a quick subset.
Python tests run in four worker slots by default; `--jobs 1` runs whole modules
serially on memory-constrained machines. The slowest modules are queued first.
Parallel runs split the independent layout and variant tests across workers
without omitting any cases. Each worker reports its test/skip summary and elapsed
time, followed by total suite wall time. Use `--verbose` to see individual test
names and skip reasons.

On the maintainer's 24-CPU machine the full Docker suite took about 5 minutes
48 seconds with `--jobs 16 --container-memory-gb 16` and an existing compiler
image. This is a measured run, not a timing guarantee for other hardware.

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
Tests target the current implementation, not an old backend or the absence of
nonexistent legacy macros. Historical syntax remains test input where it is part
of a migration tool's supported behavior.

For focused Python work without the wrapper:

```sh
PYTHONPATH=src:tests python3 -m unittest test_song_lifecycle -v
```

External-tool tests report skips on an incomplete host toolchain; a host pass
with skips is not equivalent to a supported-container run. Test products and font
caches live in ignored `build/` or temporary directories and may be deleted when
no tests or builds are running.
