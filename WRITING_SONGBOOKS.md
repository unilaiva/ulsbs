# Writing Songbooks with ULSBS

This guide explains how to write songs and organize your own book with ULSBS.
For installation, your first complete project, compiler options, and output
variants and editions, start with the [README](README.md). Engine internals
belong in [Architecture](ARCHITECTURE.md).

Song-content notation uses short lowercase commands; configuration, book assembly,
fonts and metadata accessors use `ulCamelCase` names. Public boolean settings take
an explicit `{true}` or `{false}` argument. Visibility policy is preamble-only;
local requests respect TeX grouping. Use the
commands documented here when writing new sources; see
[syntax migration](README.md#ulsbs-migrate-syntax-v2) when upgrading existing ones.

## Contents

- [Contents](#contents)
- [Your first song](#your-first-song)
- [Verses](#verses)
- [Chords](#chords)
  - [Alternate chord sets](#alternate-chord-sets)
- [Measure bars](#measure-bars)
- [Repeats](#repeats)
- [Page and line breaks](#page-and-line-breaks)
- [Keys and accidentals](#keys-and-accidentals)
- [Song metadata](#song-metadata)
- [Translations and other text](#translations-and-other-text)
- [Melody hints and beat marks](#melody-hints-and-beat-marks)
  - [Sequences and offsets](#sequences-and-offsets)
  - [Replay, advance, and whitespace](#replay-advance-and-whitespace)
  - [Placement, style, and visibility](#placement-style-and-visibility)
- [Full melodies with LilyPond](#full-melodies-with-lilypond)
  - [Converting LilyPond lyrics](#converting-lilypond-lyrics)
- [Book organization](#book-organization)
- [Variants and visibility](#variants-and-visibility)
- [Tags and indices](#tags-and-indices)
  - [Author names](#author-names)
  - [Defining your own tags](#defining-your-own-tags)
- [Manual LuaLaTeX builds](#manual-lualatex-builds)
- [Creating song selections](#creating-song-selections)
- [Layout and style reference](#layout-and-style-reference)
  - [`ulsbs-songbook` document class options](#ulsbs-songbook-document-class-options)
  - [Preamble configuration after loading the class](#preamble-configuration-after-loading-the-class)
  - [Optional spacing and bar styling](#optional-spacing-and-bar-styling)
- [Extension points](#extension-points)

## Your first song

Put song definitions inside a `ulSongs` environment in the main document, either
directly or through an input file like `\input{content/songs_main.tex}`:

```tex
\begin{ulSongs}{titleidx,authidx,tagidx}
  \input{content/songs_main.tex}
\end{ulSongs}
```

The included file contains songs, not another `\documentclass` or
`\begin{document}`. Each song starts with `\beginsong` and ends with `\endsong`:

```tex
\beginsong{Example Song}[id={example-song},by={Example Author},key={C}]
  \beginverse
    |\[C]This is an example |song line.
    Another |\[G7]line of |\[C]lyrics.
  \endverse
\endsong
```

The title is the mandatory argument. The bracketed fields supply metadata.
Use a stable `id=` made from lowercase letters, digits, and dashes; choose
distinct IDs for distinct songs. IDs are not printed song numbers. The `key=`
field describes the effective printed key, not necessarily the untransposed
key of the source chords.

`\[C]` places a chord above the following lyrics. `|` marks a measure's
beginning. In verses, source line endings produce lyric line breaks; indentation
is for source readability. Separate verses with `\endverse` and `\beginverse`,
not blank lines alone.

Ordinary LaTeX text rules still apply: `%` starts a comment, and literal text
characters such as an ampersand must be escaped (`\&`). Musical accidental
contexts have special `#` and `&` rules described below.

Printed song numbering starts at 1 in each `ulSongs` environment and advances
by one after each song. Chapter headings do not reset it. To give the next song
a specific number, set `ulSongNumber` inside the environment, before that song's
`\beginsong` command. For example, `\setcounter{ulSongNumber}{1}` restarts numbering
at 1.

Printed song numbers and their formatting are independent of stable song IDs
and repeated-song occurrence identities.

Compile the main document, not the included song file:

```sh
./ulsbs/ulsbs-compile --quick my-songbook_A5.tex
```

## Verses

Start a numbered verse with `\beginverse` and close it with `\endverse`.
Use `\beginverse*` for an unnumbered verse. Either form accepts an optional
indentation factor: `\beginverse[n]` or `\beginverse*[n]`.

- `*` makes the verse unnumbered.
- `[n]` indents the whole verse by `n` times `\ulVerseIndentWidth` (default `1em`).

Visible chords and melody hints determine their required line clearance
automatically; no special verse form is needed for melody hints.

```tex
\beginverse*[2]
  |\[<C>Am]First line with a melody note.
  |\[<D>G]Second line with a melody note.
\endverse
```

Use ordinary `\beginverse` for basic lyrics and chords; the other forms are
optional refinements.

## Chords

Write chords inline with lyrics, immediately before the syllable they belong to:

```tex
\beginverse
  |\[Am]Here is a |\[F]song,
  |\[C]Sing it |\[G7]along.
\endverse
```

Chord qualities and extensions are part of the chord text, for example `Am`,
`G7`, or `Cmaj7`. Slash basses such as `C/E` are supported. Use uppercase
note letters and `#` for sharps or `&` for flats, for example `F#m` or `B&`.

Use `\ac{<repetition>}{<chord>}` for repetition-specific alternatives:

```tex
\[\ac{1}{Em} \ac{2}{E}]Same lyric, different ending.
```

The alternatives have superscript repetition numbers. Use balanced brace
arguments for both the number and chord.

ULSBS can memorize and replay chord sequences with `^` in later
verses, including melody/beat annotations; see
[replay and spacing](#replay-advance-and-whitespace) for the detailed rules.
The first stanza records the default chord register and later stanzas replay it;
the default resets at each song. `\memorize` explicitly clears and records a
register, and `\replay` rewinds the current one. For named sequences, declare
`\newchords{bridge}`, then use `\memorize[bridge]` and `\replay[bridge]`.
Memory stores raw annotations, so replay uses the current transposition and
visibility/style settings. An unknown register or exhausted replay is an error.
Each stanza starts with the default register; select a named register again in
each stanza that needs it.

Annotations are TeX tokens, not plain strings. The first ungrouped `]` closes
the annotation; balanced groups, slash basses, typography commands and explicit
spacing remain intact. `\[C]\[G]word` places sequential adjacent annotations;
`sylla\[Am]ble` anchors within a word, and `\[C]{grouped words}` retains the
group. Use separate adjacent annotations for separate melody blocks, not multiple
blocks within one annotation.

### Alternate chord sets

Use `\altchords{...}` for a standalone alternate chord set; `\id[<n>]{...}`
labels it, and `\ac{<n>}{<chord>}` identifies a repetition-specific chord:

```tex
\altchords{\id[1]{alt. (C)}|C |\ac{2}{D} |E}
```

Standalone alternate sets do not switch with multikey PDF layers and do not
follow source `\transpose` by default. Enable source transposition explicitly
with `\ulTransposeAltChords{true}`; restore the default with
`\ulTransposeAltChords{false}`.

Displaying a standalone set requires both `chords` and `altchords` visibility.
Hiding `altchords` alone does not hide repetition-specific `\ac` chords inside
ordinary inline annotations.

When enabled, plain chords and chord-like content inside `\id` and `\ac` follow
the current interval. Write accidentals as `#` and `&`; `\shrp` and `\flt` are
not part of the supported transposable `\altchords` syntax. Protect content that
must remain unchanged with `\notrans{...}`:

```tex
\transpose{2}
\ulTransposeAltChords{true}
\altchords{\id[1]{alt. (C)}|C |\ac{2}{D} |\notrans{E}}
```

The alternate `C` and `D`, including the key in `\id`, follow the two-semitone
transposition; `E` stays unchanged. Put descriptive text in `\notrans{...}` when
an uppercase `A`--`G` could be read as a note. Do not put ordinary `\[ ... ]`
blocks inside `\altchords`: they participate in chord placement, memorization,
and replay rather than forming a standalone set.

## Measure bars

Use `|` at the **beginning** of each measure, not the end. A line ending does
not itself mean the end of a measure. Use one bar marker per measure.

For a measure with no lyrics at that spot, use `\e`, a plain end dash unrelated
to vertical spacing:

```tex
\beginverse
  |\[C]Hold this note |\[G7]\e
\endverse
```

To hide measure bars locally, use `\measuresoff`; `\measureson` restores them
where book policy permits. To hide them throughout the book, put
`\ulShowMeasures{false}` in the preamble. Chord visibility does not control bars.

## Repeats

Inline repeat marks are `\lrep`, `\rrep`, and `\rep{<n>}`. Put the repeat count
after the right repeat mark:

```tex
\beginverse
  \lrep |\[C]Sing this |\[G7]again. \rrep\rep{2}
\endverse
```

Use `\beginrep` and `\endrep` for repeat bars down the left of lyric lines.
They can be nested:

```tex
\beginsong{My Song}[id={my-song}]
  \beginverse
    \beginrep
      Here are lyrics for the verse
      That is completely repeated.
    \endrep
  \endverse
  \beginverse
    This lyric line has no repeats
    \beginrep
      These two lines have
      one repeat bar sign
      \beginrep
        This line has two levels of repeats
      \endrep
    \endrep
  \endverse
\endsong
```

`\prep{<n>}` is a raised repeat-count marker used after `\beginrep`. Put it on the
same source line as the lyrics when it should follow their annotation height.
Its position follows the highest occupied reference on its physical line, with
a fallback when no higher reference exists. A marker on its own source line uses
that fallback rather than looking ahead to the next lyric line.
`\goto{Beginning words of the verse}` marks a jump target by text.

Use verses for all lyric stanzas and explicit repeat regions within them for
repeat markup.

## Page and line breaks

Within a verse, each source newline ends a lyric line; long source lines can wrap.
Braces, spaces and `%` comments affect how the source is read and spaced, so take
care when reformatting lyrics. Chord placement and minimum annotation widths also
affect where lyrics wrap.
Hidden alternate PDF layers in optional MULTIKEY editions never reserve extra
space: the effective original notation alone determines line and page geometry.

Use `\brk` within a lyric line to suggest a line break. Between verses or
songs, it suggests a page or column break.

To force breaks between songs:

- `\sclearpage` jumps to the next page.
- `\scleardpage` jumps to the next spread / even page.

For long songs, `\brk`, `\hardbrk`, or `\forcebrk` may be needed immediately
before the song so that the preceding song ends cleanly. Check the compiled
PDF after changing breaks, paper size, fonts, or visible annotations.

## Keys and accidentals

The song's `key=` describes its already-effective printed key, **after** any
user `\transpose` offset. Do not give the untransposed source key when the song
is printed in another key. To print source C-major notation in F:

```tex
\beginsong{Example}[id={transposed-example},key={F}]
  \transpose{5}
  \beginverse
    |\[C]Home |\[F]fourth |\[G#]raised fifth.
  \endverse
\endsong
```

The offset is in semitones. Printed chords are F, B-flat, and C-sharp. The
prelude says F and is not transposed again. This chord/melody-hint transposition
does not automatically transpose a full LilyPond source block; write its music
in the intended key or use LilyPond's own transposition facilities.

Ordinary source transposition and multikey selection preserve scale degree and
chromatic alteration, not just pitch class. Major and natural minor are the
reference scales; raised harmonic/melodic-minor degrees retain their alterations.
This applies to roots, slash basses, and pitched melody hints even without PDF
layers. Double-accidental results use a pitch-equivalent single-accidental
spelling. Missing keys use the current `\preferflats` or `\prefersharps`
setting without inferring a key from the first chord. Unsupported keys use that
fallback and issue a warning. [Architecture](ARCHITECTURE.md#key-spelling)
explains the full spelling policy.

Write a sharp as `#` and a flat as `&` in musical contexts. This shorthand
works in ordinary chord and melody blocks, `\altchords`, `\beginsong`'s
`key`/`gk` values, and `\audio`'s `key` value:

```tex
\beginsong{Example}[id={key-example},key={C#m},gk={B&m, Am--C#m}]
  \audio[key={F#m}]{https://example.test/recording}
  \beginverse
    |\[C#m]Example line \altchords{\id[1]{alt. (B&m)}|B&m |F#7}
  \endverse
\endsong
```

Outside these contexts, use `\shrp` and `\flt` to print musical accidentals.
Use `\#` and `\&` only for a literal hash sign or ampersand in text.

Supported transposition keys have an A--G tonic, an optional accidental, and
an optional `m`, for example `F`, `B&`, or `C#m`. Existing `\shrp` and `\flt`
macros also work in key metadata. Lowercase `b` is not a flat alias: write
`B&`, not `Bb`.

For reader-selectable transposition, see [multikey editions](README.md#multikey-pdf-editions).
Major/minor key metadata is required for supported score transposition; modal
suffixes are not interpreted as a different major/minor key.

## Song metadata

Place metadata inside the optional brackets after the title. Braces around each
value keep commas inside that value from being read as field separators:

```tex
\beginsong{Example Song}[
  id={example-song},
  by={Example Author},
  key={C},
  gk={C, B&--D},
  ex={Traditional},
  off={A friend},
  ph={I, II}
]
  \beginverse
    |\[C]Example lyrics.
  \endverse
\endsong
```

| Field | Purpose |
|---|---|
| `id` | Stable identity for metadata and multikey layers; lowercase letters, digits, and dashes |
| `by` | Song author or attribution |
| `key` | Effective printed musical key |
| `gk` | Recommended singing key(s), for example a preferred key followed by a range |
| `ex` | Extra information in the song prelude |
| `off` | Offered-to / dedication text in the prelude |
| `ph` | Phase information, if useful for your collection |
| `tags` | Comma-separated tags; see [Tags and indices](#tags-and-indices) |
| `cr`, `li` | Copyright and license fields; metadata is not a substitute for permission to publish |
| `index`, `ititle` | Additional index entries; repeat the field to add multiple entries |

Only add the optional fields relevant to your book. The
[visibility switches](#preamble-configuration-after-loading-the-class) control
which prelude information is displayed. Recommended singing keys (`gk=`) are
recommendations, not transposition instructions, and do not switch with multikey
layers.

Unknown metadata keys are errors; declare custom fields with
[`\ulNewSongKey`](#extension-points). Public metadata values remain available after
`\endsong` within the surrounding scope, until the next song resets them.

You can associate an external recording with a song using:

```tex
\audio[title={Example recording},key={C},pitch={440}]{https://example.test/recording}
```

Place it inside the song, outside a verse. Multiple recordings are allowed;
the first is primary. The optional `pitch` is the tuning frequency of A.
This records metadata for export; it does not download audio or insert an audio
player into the PDF. Escape ordinary TeX-special characters in URLs as needed.

Use `./ulsbs/ulsbs-bookmeta --check-song-ids my-songbook_A5.tex` to check IDs.
The [metadata utility](README.md#ulsbs-bookmeta) can also help assign them
interactively. Compilation does not rewrite your sources to add IDs.

## Translations and other text

Put translations inside a song, outside its lyric verses. The environment
handles its own verse layout; use `\nextverse` between translated verses:

```tex
\begin{translation}[EN]
  Translation of the first verse.
  Another translated line.
  \nextverse
  Translation of the second verse.
\end{translation}
```

The optional language code is uppercase. `EN`, `PT`, and `FI` have explicit
English, Portuguese, and Finnish handling. Omit the code when no language
annotation is needed. Preamble `\ulShowTranslation{false}` hides all translations;
`\translationoff` / `\translationon` controls them within a song, subject to
the book permission. Local requests follow grouping, not an independent global
translation switch.

Use an explanation block for prose associated with a song:

```tex
\begin{explanation}[EN]
  Background, performance notes, or an explanation of the lyrics.
\end{explanation}
```

Use a passage for a titled prose section, such as material between songs:

```tex
\begin{passage}[EN]{Background}
  Introductory text for this part of the collection.
\end{passage}
```

Use `\begin{passage}*{Title}` (with the same `\end{passage}`) for the alternate,
note-like style. Preamble `\ulShowExplanation{false}` and
`\ulShowPassage{false}` hide their respective environments. The `feeler` environment
provides another short, styled text block inside a song:

```tex
\begin{feeler}
  Quietly, with a steady pulse.
\end{feeler}
```

For a note attached to a stanza boundary, use
`\attachednote[<skip before>][<skip after>]{Text}`. Both skips default to zero.
A leading star attaches it to preceding material; without that star it attaches
to following material. Normally a forward-attached note removes the next verse's
usual separating space. A trailing star keeps that space instead, for example
`\attachednote{Before the first verse}*`. Inside a verse, the note uses small
surrounding gaps rather than these attachment skips. This is distinct from the
shorter `\textnote{Text}` command, not an alias for it.

Use `\musicnote{Text}`, `\musicnoteforprev{Text}`, `\musicnotefornext{Text}`,
or `\musicnotemiddle{Text}` for general musical instructions. Their independent
`\ulShowMusicComments` permission
is not pitched-note visibility. Chord-specific help should additionally test
`\ifulShowChords`; instrument-specific help can test `\ulIfVariant`.

## Melody hints and beat marks

Melody hints are compact pitched annotations above lyrics, not full staff
notation. Add one leading melody block inside a chord annotation:

```tex
\[<C>Am]Love
\[<C D E>F]move
\[<C;E>Am]two voices
\[<C>]melody without a chord
```

The block begins immediately after `\[` or its one optional leading `^`.
The complete form is:

```tex
\[<[!]primary[;secondary][ @offset]>chord]lyric
\[^<[!]primary[;secondary][ @offset]>chord]lyric
```

Here square brackets inside the syntax illustration indicate optional parts;
they are not literal characters to type.

### Sequences and offsets

The first sequence is primary. It may be empty for a secondary-only block; use
`;` before the optional secondary sequence. Pitches are uppercase and may have
`#` or `&` accidentals.

| Token | Meaning |
|---|---|
| `C`, `D#`, `B&` | One transposition-aware pitched slot |
| `_` | One empty slot with normal slot advance |
| `*` | Beat mark at the current sequence position; no slot advance of its own |
| `/` | Circled, unpitched one-slot marker |

Whitespace is optional between tokens and around `;` and `@`, so
`\[<*A_/C;EF_G>Am]` equals `\[<* A _ / C;E F _ G>Am]`. Use `@` with a TeX
dimension to offset the whole block, for example `\[<CD@-.25em>Am]`.
Relative units such as `em` and `ex` are evaluated in the lyric font.

An optional leading `!` makes the melody block zero-advance. Its notes and beats
still render, but the melody contributes no width and the whitespace minimum
is disabled for that annotation. A chord in the same annotation keeps its
natural width:

```tex
\[<!C>]          % visible note, zero advance
\[<!*>]          % visible beat, zero advance
\[<!C@1em>Am]    % shifted zero-advance melody; Am keeps its width
```

### Replay, advance, and whitespace

The leading `^` retains its chord-replay meaning. `\[^<C>Am]` is excluded
from chord memorization; a bare `^` in lyric text later replays the next saved
annotation, including its chord, melody, and beats. Note and beat visibility is
evaluated at replay time.
While replaying, a leading `^` inside an annotation consumes the next saved
annotation in the same box. Its saved melody takes precedence over a newly
written melody prefix; additional chord text still renders in that box.

Layers within one annotation overlay. Its advance is the widest rendered
layer: a chord can determine it, and a melody-only block reserves its own width.
Negative offsets can draw left of the anchor without reducing normal advance;
positive offsets reserve their added extent. Consecutive annotations remain
sequential: `\[Am]\[<*>]` puts the beat after the chord, while `\[<*>Am]`
overlays them.

Only one melody block is accepted per annotation. Use adjacent annotations for
multiple blocks; a zero-advance first block shares the next block's anchor:
`\[<!A>]\[<B>Am]`.

When a visible chord-line annotation or replay is followed by literal source
whitespace, its advance is at least `\ulChordWhitespaceMinimumWidth` (default
`.8ex` in the lyric font). Wider annotations stay unchanged; hidden chords,
notes, and beats do not trigger the minimum. Set it to `0pt` to disable it.

### Placement, style, and visibility

Primary and secondary are semantic roles. Scoped
`\ulMelodyPrimaryPosition{normal}` or `low` selects the primary lane (default:
`normal`). `\ulMelodySecondaryPosition{above}`, `below`, or `same` selects the
secondary lane relative to it (default: `above`); `same` is the primary lane.
With a low primary, `above` is the normal lane and `below` may overlap lyrics.

Set styles independently with `\ulMelodyStyleMapping{normal}` (primary uses the
normal style) or `\ulMelodyStyleMapping{swapped}` (primary uses the alternate
style). Neither setting changes which sequence is primary.

Preamble `\ulShowNotes{false}` denies inline pitches; `\ulShowBeats{false}`
denies beats. Local `\notesoff` and `\beatsoff` suppress their respective features;
`\noteson` and `\beatson` restore requests only within book permission. Neither
depends on chords: `\chordsoff` hides chord symbols alone. Ordinary
`\beginverse` handles melody hints on any line.

Annotation spacing follows visible ink: beats-only lines use compact clearance,
and fully hidden annotations reserve no phantom width or height. Visible pitches
and authored offsets still get their required clearance. Replay stays synchronized
across local visibility changes. Recheck pagination after changing visible features.

## Full melodies with LilyPond

Full scores are optional. Put a `lilypond` environment inside `lilywrap`, inside
the song but **outside** any verse. The normal compiler runs LilyPond before
LaTeX; running LaTeX alone does not process raw score environments.

This complete song uses the bundled head and tail helpers:

```tex
\beginsong{Score Example}[id={score-example},key={C}]
  \beginverse
    |\[C]I am full of |\[G7]joy.
  \endverse

  \begin{lilywrap}
  \begin{lilypond}[]
    \include "ulsbs-include-head.ly"
    theMelody = \relative c'' {
      \key c \major
      \time 4/4
      c4 e d f | c1
    }
    theChords = \chordmode { c2 g2:7 | c1 }
    theLyricsOne = \lyricmode { I am full of joy }
    \include "ulsbs-include-tail.ly"
  \end{lilypond}
  \end{lilywrap}
\endsong
```

The compiler supplies these include files; do not copy or edit them in your
project for an ordinary score. Include the head first, define the music, then
include the tail. `theMelody` contains the main melody. `theChords` and
`theLyricsOne` are optional; the helpers also support additional named lyrics.
LilyPond has its own note syntax (`c`, `fis`, etc.), distinct from the uppercase
ULSBS chord/melody-hint syntax.

The standard tail creates a staff, guitar tablature, and MIDI. Replace it with
`ulsbs-include-tail-notab.ly` to omit tablature, or
`ulsbs-include-tail-notab-nolyrics.ly` to omit both tablature and lyrics.
`ulsbs-include-tail-lyricsbelow.ly` places lyrics below the tablature.
`ulsbs-include-head-spacious.ly` provides a more spacious head for larger pages.
`ulsbs-include-tail-multivoice-notab.ly` supports a second voice defined as
`theMelodyTwo`.

The standard helpers use an octave convention: write the main melody an octave
above the intended common female singing range. The normal MIDI helper lowers
it one octave and the standard guitar tablature lowers it two. These are helper
conventions, not automatic detection of a singer's range.

Normal builds can export the generated MIDI and encode MP3 audio. Quick builds
omit those exports. MIDI/audio is synthesized from the score, not from the
separate LaTeX lyrics or chord text. See [variants and editions](README.md#variants-and-editions)
for variant and multikey behavior. With multikey score transposition enabled,
unsupported score structures or unsafe alternatives retain the original score
with a warning.

`\ulShowLilypond` controls display of whole scores, not their generation or media
export. `\ulShowChords` controls only inline TeX chord symbols: it cannot remove
`ChordNames` already engraved in a score. Compiler score recipes independently
select tuning, clef and tablature; bass-clef scores retain chord names even though
their preset hides inline chords. Use the compiler to build instrument variants
with their matching scores.

Score systems that are wider than the available line are automatically reduced
to fit. Smaller systems keep their original size.

### Converting LilyPond lyrics

The [`ulsbs-ly2tex` utility](README.md#ulsbs-ly2tex) helps convert ULSBS-style
LilyPond lyric output into songbook text. For manual conversion, these
replacements are often useful, in this order:

1. ` -- | ` -> `|`
2. ` -- _ ` -> remove
3. ` -- ` -> remove
4. ` | ` -> ` |`
5. ` __` -> remove
6. ` _` -> remove
7. `__ ` -> remove
8. `|_` -> `|`
9. `\skip 1 ` -> remove
10. `"" ` -> remove
11. `~` -> `\jw `
12. `\altcol ` -> remove

Here "remove" means delete that text. Check whitespace and syllable
joins, and compare the result against the score. This is not a general-purpose
LilyPond parser.

## Book organization

Use `ulsbs-songbook` or a derived class for the main document. For compiler
auto-detection, derived class names should also start with `ulsbs-songbook`.

The [minimal main document](README.md#minimal-main-document) shows the full
structure. Inside `\begin{document}` ... `\end{document}`, these commands
provide the usual front matter and chapters:

```tex
\ulCoverPage{}
\ulImprintPage
\ulToc

\ulMainChapter{Morning Songs}{blue}
\begin{ulSongs}{titleidx,authidx,tagidx}
\input{content/songs_morning.tex}
\end{ulSongs}

\ulMainChapter{Evening Songs}{violet}
\begin{ulSongs}{titleidx,authidx,tagidx}
\input{content/songs_evening.tex}
\end{ulSongs}
```

`\ulCoverPage{}` generates a title cover; its argument can instead name a cover
PDF. `\ulMainChapter{Title}{color}` starts a chapter with its colored symbol.
The source input order determines the ordinary book's song order. You may put
multiple songs in one file or use one file per song. Files named `songs_*.tex`
are a useful convention, not a requirement.

## Variants and visibility

Declare supported presets literally in the main source, not in an input, macro
or derived class:

```tex
\documentclass[
  variants={default,lyric,charango,bassclef},
  maintitle={My Songbook}
]{ulsbs-songbook}
\ulShowMeasures{false} % Hide bars even in presets that normally show them.
```

Omission means `{default}` only. The list must include `default`; names are
lowercase, unique and known, with no repeated declaration or computed values.
Availability is not selection: see [compiler selection](README.md#variants-and-editions)
for `variants = "all"`, TOML lists and CLI subsets. Keep the canonical source
free of build selectors. Choose the variant with the compiler; the selected
identity stays fixed throughout that build.

The selected preset applies after the class's settings and before your explicit
preamble configuration. Your preamble can override preset defaults.
`default` preserves the source baseline rather than imposing a musical type.
The standard baseline permits all features below. The non-default presets supply
these notation defaults:

| Feature | `lyric` | `charango` | `bassclef` |
|---|---|---|---|
| Inline chords, pitches and beats | Off | On | Off |
| Measure bars | On | On | On |
| Whole scores | Off | On | On |
| Alternate chord sets | Off | On | Off |
| Music comments | Off | On | On |

Lyric also denies main/recommended key badges; other presets preserve authored
key policy. All presets preserve independent prose, tags, phases, attribution and
chapter artwork. Editions and media permissions are separate from these display
defaults; enabling a feature does not change identity or edition eligibility.

**Book policy and local requests.** Set `\ulShow...{true|false}` in the preamble
after class loading. Policy freezes at document start, before `\AtBeginDocument`
callbacks; body setters are errors, not local overrides. In songs or verses use
`\ulLocalShow{feature}{true|false}`, or the short pairs `\chordsoff`/`\chordson`,
`\notesoff`/`\noteson`, `\beatsoff`/`\beatson`, `\measuresoff`/`\measureson` and
`\translationoff`/`\translationon`. Each changes only its own request.

Effective visibility is **book permission AND local request**. Local `true`
cannot defeat book `false`; for example, a song's `\noteson` cannot leak pitches
into a lyric variant whose preamble still denies notes. Requests last until the
enclosing group ends; song and verse groups restore enclosing state. Use an
explicit group for a narrower scope:

```tex
{\chordsoff
 \ulLocalShow{translation}{false}
 % This scope can still show permitted pitches, beats, measures and scores.
}
```

Set a local request before the material it controls. For example, put a grouped
`\ulLocalShow{authors}{false}` before `\beginsong` to hide that song's author
badge, not after its prelude has already been printed. Likewise set chapter
artwork requests before `\ulMainChapter`. Hiding badges does not remove their
metadata from exports or indices.

Canonical feature keys are `chords`, `notes`, `beats`, `measures`, `scores`,
`altchords`, `key`, `goodkeys`, `musiccomments`, `translation`, `explanation`,
`passage`, `feeler`, `authors`, `offeredto`, `extrainfo`, `tags`, `phase`,
`phaseintoc`, `imageinchaptername` and `imageonchapterfrontpage`. Unknown keys or
nonliteral boolean values are errors. `scores` corresponds to `\ulShowLilypond`;
the other keys correspond to the preamble setters in the
[settings table](#preamble-configuration-after-loading-the-class).

**Feature and identity tests.** `\ifulShowChords`, `\ifulShowNotes`,
`\ifulShowLilypond` and the other `\ifulShow...` predicates query effective
visibility in the current scope. They are genuine TeX conditionals, including
inside skipped branches; do not assign or redefine them:

```tex
\ifulShowChords Chord-specific playing help.\else Other guidance.\fi
\ulIfMusical{Musical-information motto}{Words-only motto}
\ulIfVariant{bassclef}{\sclearpage}{}
```

`\ulIfMusical{yes}{no}` tests effective **inline chords OR inline pitches OR
whole scores**, at the time of the call. Beats, measures, keys and music comments
do not make it true; it does not inspect whether the current song contains music.
`\ulIfVariant{name}{yes}{no}` validates a registered name and tests immutable
identity, unaffected by visibility changes. Use it for genuinely variant-specific
pagination or instrument help, not as a substitute for a capability test.

## Tags and indices

The `ulSongs` environment requires a comma-separated list of declared index
identifiers. It actively routes automatic records within that block, not just
describes which indices to display. The package declares `titleidx`, `authidx`,
and `tagidx`; these are index names, not filenames or fixed keywords.
Use `{titleidx,authidx,tagidx}` to collect all three kinds, or omit any destination
you do not need. `{}` collects no automatic records. An explicit entry can
override the block's routing, for example `\ulIndexEntry[titleidx]{Other title}`
inside a song, including one in an empty-list block.

To generate and display all three indices:

```tex
\ulShowIndex{Song Title Index}{titleidx}
\ulShowIndex{Author Index}{authidx}
\ulShowIndex{Tag Index}{tagidx}
```

For title, author and tag indices, `\ulShowIndex{Heading}{identifier}` displays
the **whole destination from the previous pass**, regardless of its location
before, between, or after song blocks. It is not a partial index of only preceding
songs. Reusing an identifier across blocks accumulates records into the same
index. For separate chapter or volume indices, declare separate identifiers and
output names in the preamble, then route each block to its own destinations:

```tex
\ulNewIndex{morningtitles}{idx_morning_titles}
\ulNewAuthorIndex{morningauthors}{idx_morning_authors}
\ulNewTagIndex{morningtags}{idx_morning_tags}
% In the document:
\begin{ulSongs}{morningtitles,morningauthors,morningtags}
  \input{content/songs_morning.tex}
\end{ulSongs}
\ulShowIndex{Morning Titles}{morningtitles}
\ulShowIndex{Morning Authors}{morningauthors}
\ulShowIndex{Morning Tags}{morningtags}
```

The constructors take `{identifier}{output-name}`; choose a distinct output name
without an extension for each custom index. `\ulNewIndex` declares a
title index, `\ulNewAuthorIndex` declares an author index, and
`\ulNewTagIndex` declares a tag index. The package-declared destinations are:

| Identifier | Kind |
|---|---|
| `titleidx` | Title |
| `authidx` | Author |
| `tagidx` | Tag |

Printed song numbering restarts at 1 in each `ulSongs` block, independently of
index accumulation. Set `ulSongNumber` to override the next number, or use
`\ulIndexSongsAs{titleidx}{A-\theulSongNumber}` within the block to override that
index's reference labels without changing printed song numbers or stable IDs.
`\ulSongIndexes{false}` disables both index collection and index display globally;
`\ulShowTags{false}` only hides prelude tag badges.

Separate alternate song titles with top-level `\\` in the title argument;
grouped `\\` remains part of the group. Repeated `index={...}` and
`ititle={...}` metadata fields add separate index entries in input order.

The compiler generates the requested title, author and tag indices automatically;
no separate indexing command is needed.
For manual builds, follow the [pass sequence below](#manual-lualatex-builds)
and repeat if an index or reference rerun warning remains. A requested
tag index requires tag definitions; missing definitions and unknown/malformed
tags are errors rather than silently omitted entries.
The table of contents (`\ulToc`) is separate from these indices.

### Author names

Use `by=` for one or more names, written exactly as you want them displayed:

```tex
\beginsong{Shared Song}[by={Alice Smith, Bob Jones; {Family, Given} and Carol Lee}]
  \beginverse
    Example lyrics.
  \endverse
\endsong
```

This indexes `Alice Smith`, `Bob Jones`, `Family, Given` (one name), and `Carol Lee`.
Top-level commas, semicolons and standalone case-insensitive `and` separate names;
braced groups and TeX arguments protect their contents, and TeX control symbols
are not separators. Names are preserved **as written**: ULSBS does not guess
surnames or roles. By default a standalone case-insensitive `by` marker keeps
only text after its last occurrence in each attribution segment, so
`Words by Alice; Music by Bob` indexes Alice and Bob. Hyphenated and apostrophe-joined
words are not standalone markers.
Empty fields add no entries. Repeated names within one `by=` value are listed once;
separate uses retain their links, including repeated song selections.
Identical display names are grouped with their song links, using the same
deterministic Finnish-compatible/natural sorting as titles. TeX formatting is
preserved and `\ulIndexAuthorFont` styles entries; author indices have no letter
heading panels.

Configure author-parsing settings in the preamble. They apply globally, not just
within the current TeX group. Mid-document changes can affect songs differently
from what their source order suggests.
Separator and attribution markers must be single alphabetic words, or empty
values; ignore settings may name a whole cleaned author. For example:

```tex
\ulAuthorSepWord{ja}      % First call replaces default "and"; later calls add words.
\ulAuthorByWord{von}      % First call replaces default "by"; later calls add words.
\ulAuthorIgnoreWord{Traditional} % Ignore this whole cleaned name, case-insensitively.
```

An empty first `\ulAuthorSepWord{}` or `\ulAuthorByWord{}` clears its respective
default; commas and semicolons still separate names. Ignore words match whole
cleaned candidates, never arbitrary substrings. Custom author indices work the
same way: declare `\ulNewAuthorIndex{writers}{idx_writers}`, route a block to
`writers`, then request `\ulShowIndex{Authors}{writers}`. Explicit
`\ulIndexEntry[authidx]{...}` / `\ulIndexTitleEntry[authidx]{...}` and
`\ulIndexSongsAs` also work with author destinations.

Title and author sorting is consistent across machines and Finnish-compatible:
A to Z precede ring-A, umlaut-A and umlaut-O. Case, accents, punctuation and numeric
prefixes also affect ordering. Supported characters include ASCII, selected
precomposed accented Latin letters, Sanskrit transliteration characters and
Persian title letters; not all Unicode characters are supported. An unsupported
character causes an error identifying its Unicode code point; installing a locale
will not fix it. Tag groups follow their definition order rather than title
sorting. Printed index reference labels, persistent song IDs and multikey
range-page numbers are different concepts.

### Defining your own tags

Create `include/tags.txt` in your project. This is ordered UTF-8 plain text,
not TeX source. Each non-comment line defines a canonical tag, optionally followed
by `|`-separated aliases:

```text
# Tags are displayed in this order.
light
love|affection
% Full-line percent comments are allowed too.
peace
```

Surrounding whitespace is trimmed from names and aliases. Blank lines and full-line
`#` or `%` comments are ignored. There are no count lines: do not put `1` after
definitions or append numbered references to tag names. Tags appear in
definition-file order, so arrange the file as you want the index ordered. An alias
indexes under the first (canonical) name.

Names are literal text, not TeX code; special characters are escaped when printed
in the index. Names and aliases cannot contain the list separators `,` or `;`,
and a definition cannot consist only of numbers. Matching remains case-insensitive;
the first definition wins when aliases overlap. An inline `#` or `%` is literal,
not the start of an inline comment.

By default, lookup checks `include/tags.txt` first, then asks TeX's file lookup
for `tags.txt`. To choose another filename, put this **preamble-only** setter
after class loading and before `\begin{document}`:

```tex
\ulTagFile{my-tags.txt}
```

An explicit filename is resolved through TeX lookup. If it is missing, the build
fails; it does not fall back to `include/tags.txt` or `tags.txt`. Legacy `.can`
parsing is migration-only, not a runtime option. Use the
[v2 migrator's explicit `--tags-file` option](README.md#ulsbs-migrate-syntax-v2)
to convert old definitions and rename them to `.txt`.

Use the tag names in song metadata:

```tex
\beginsong{Song name}[id={song-name},tags={love, peace}]
  \beginverse
    Example lyrics.
  \endverse
\endsong
```

Use `\ulShowTags{false}` in the main preamble to hide tags in song preludes. It does
not disable tag collection or the tag index. A book without a tag index needs no
tag-definition file; omit the tag `\ulShowIndex` call in that case.

Indices need multiple LuaLaTeX passes: a first-pass PDF is not final. The normal
compiler handles reruns before publication. For manual builds, follow the pass
sequence below and any recovery instructions reported after an interrupted build.
Do not use `\nofiles` when displaying indices. Concurrent builds require separate
compile directories.

## Manual LuaLaTeX builds

A standalone book containing lyrics, chords and melody hints can compile
directly with LuaLaTeX, without Python, LilyPond or an upstream `songs` install.
Keep all companion ULSBS assets together, not just `ulsbs.sty`. From the project
root, with the engine checked out in `ulsbs/`, a POSIX-shell setup is:

```sh
export TEXINPUTS="$(pwd)/ulsbs/src/ulsbs/assets/tex//:$(pwd)/ulsbs/src/ulsbs/assets/img//:$(pwd)/include//:${TEXINPUTS:-}"
export LUAINPUTS="$(pwd)/ulsbs/src/ulsbs/assets/tex//:${LUAINPUTS:-}"
lualatex -interaction=nonstopmode -halt-on-error -draftmode my-songbook_A5.tex
lualatex -interaction=nonstopmode -halt-on-error my-songbook_A5.tex
lualatex -interaction=nonstopmode -halt-on-error my-songbook_A5.tex
```

The trailing search-path separator preserves the TeX distribution's default
package lookup. Use absolute paths and adjust the engine location for another
checkout; ensure included project sources and images are also discoverable.
The draft collects index data; the first full pass displays the indices,
and the second full pass settles references and PDF resources. Repeat full
passes until rerun warnings disappear. A first-pass PDF is not final; follow any
reported recovery instructions if a build is interrupted.

Direct compilation uses `default` automatically. For other declared variants,
use the compiler, for example:

```sh
./ulsbs/ulsbs-compile --variants bassclef my-songbook_A5.tex
```

This is a TeX build, not a replacement for the Python publication pipeline:
LilyPond source processing, optional score alternatives, PDF optimization, range
packaging, JSON, printouts and media exports are compiler responsibilities. Use
`ulsbs-compile` for those products. Merely enabling PDF layers in manual TeX does
not produce a validated `_MULTIKEY_RANGES.json` package.

## Creating song selections

For a reusable selection, create another main document with the same class,
needed preamble settings, and song inputs, and add this in its preamble:

```tex
\ulIncludeOnlySongs{3,1,7}
```

This selects **song numbers**, not `id=` values, and uses the selection order
within a `ulSongs` environment. The numbers refer to the original numbering from
the included collection; selecting songs does not automatically renumber them
from 1. Keep the input collection and numbering setup consistent with the source
book. The command is allowed in the preamble or between `ulSongs` environments,
not inside one.
Omitting `\ulIncludeOnlySongs` includes all songs; `\ulIncludeOnlySongs{}` explicitly
selects none. Unselected song boxes do not contribute shipped index/TOC records,
although source processing and hooks may already have run.

For a small independent collection, explicitly inputting just the desired song
files is often simpler than a numbered selection. The Unilaiva repository's
[selection example](https://github.com/unilaiva/unilaiva-songbook/blob/main/include/ul-selection_example.tex)
shows its project-specific selection setup; its child class and helper files
are not bundled ULSBS requirements.

## Layout and style reference

Use this section after the basic song syntax. The class options set up the
document; preamble commands customize the loaded styles.

### `ulsbs-songbook` document class options

```tex
\documentclass[
  paper={a5paper},
  maintitle={My Songbook},
  author={Songbook Author},
  bindingoffset={8mm}
]{ulsbs-songbook}
```

| Option | Meaning |
|---|---|
| `variants={default,...}` | Literal main-source availability; omission is default only; see [Variants and visibility](#variants-and-visibility) |
| `paper={...}` | Paper size, for example `a5paper` or `a4paper` |
| `maintitle={...}` | Main book title |
| `subtitle={...}` | Subtitle / sub-book title |
| `subsubtitle={...}` | Secondary subtitle |
| `motto={...}` | Imprint-page motto |
| `wwwlink={...}` | Website link on the imprint page |
| `wwwqr={...}` | QR image filename for the website |
| `imprintnote={...}` | Imprint-page footnote text |
| `author={...}` | PDF metadata author and default compiled-by text source |
| `subject={...}` | PDF metadata subject |
| `keywords={...}` | PDF metadata keywords |
| `language={...}` | Preliminary main language, default `english` |
| `bindingoffset={...}` | Binding offset, default `8mm` |

Supported standard options forwarded to the underlying `book` class are
`10pt`, `11pt`, `12pt`, `openright`, `openany`, `oneside`, `twoside`, `draft`,
`final`, `titlepage`, `notitlepage`, `onecolumn`, `twocolumn`, `fleqn`, and `leqno`.

Always use `paper={a5paper}` or similar. Bare options such as `a5paper` and
`a4paper` are intentionally swallowed by this class and do not control the
ULSBS layout. See the [filename conventions](README.md#main-document-filename-conventions)
for the separate `_A5` printout convention.

### Preamble configuration after loading the class

Put these commands after `\documentclass{ulsbs-songbook}` and before
`\begin{document}`. Boolean settings take exactly `true` or `false` as an
argument. Visibility permissions freeze at document start; use grouped local
requests in the body, as described in [Variants and visibility](#variants-and-visibility):

```tex
\ulShowTags{false}
\ulShowGoodKeys{false}
\renewcommand{\ulSongEndMark}{*}
```

| Setter (`{true}` or `{false}`) | Standard baseline | Meaning |
|---|---|---|
| `\ulShowExtraInfo` | `true` | Show extra prelude info (`ex=`) |
| `\ulShowOfferedTo` | `true` | Show offered-to info (`off=`) |
| `\ulShowKey` | `true` | Show the main musical key |
| `\ulShowGoodKeys` | `true` | Show recommended singing keys |
| `\ulShowPhase` | `true` | Show phase info in preludes |
| `\ulShowPhaseInToc` | `true` | Show phases in the TOC |
| `\ulShowTags` | `true` | Show/hide tags in preludes; collection and index membership are unchanged |
| `\ulSongIndexes` | `true` | Enable both index collection and display; false disables both |
| `\ulTitleBadgeOverlap` | `false` | Allow prelude text to overlap the key, tag and phase badges |
| `\ulShowChords` | `true` | Show inline chord symbols, not score ChordNames |
| `\ulShowMeasures` | `true` | Show measure bars independently of chords |
| `\ulShowNotes` | `true` | Show melody-note hints |
| `\ulShowBeats` | `true` | Show beat marks |
| `\ulShowMusicComments` | `true` | Show musical prose helpers, not pitched notes |
| `\ulShowAuthors` | `true` | Show song authors in preludes |
| `\ulShowLilypond` | `true` | Show LilyPond score blocks |
| `\ulShowPassage` | `true` | Show `passage` environments |
| `\ulShowExplanation` | `true` | Show `explanation` environments |
| `\ulShowTranslation` | `true` | Show `translation` environments |
| `\ulShowFeeler` | `true` | Show `feeler` environments |
| `\ulShowAltChords` | `true` | Show alternate chord sets |
| `\ulShowImageInChapterName` | `true` | Include chapter symbol/image in TOC and headers |
| `\ulShowImageOnChapterFrontPage` | `true` | Show chapter image/symbol on chapter front pages |
| `\ulUppercaseLongChapterTitle` | `false` | Uppercase long chapter titles on front pages |
| `\ulUppercaseShortChapterTitle` | `true` | Uppercase short chapter titles in TOC and headers |
| `\ulUppercaseSectionTitleInHeader` | `false` | Uppercase section titles in headers |
| `\ulUppercaseBookTitleInHeader` | `true` | Uppercase the book title in headers |
| `\ulUseChapterColors` | `true` | Enable colored chapter corner marks |
| `\ulAdjustChordChars` | `true` | Apply chord-character typography adjustments |

Preset changes are listed above; these baseline values are not a guarantee for a
custom class. `\ulSongIndexes`, title casing, chapter colors and chord typography
are ordinary configuration, not `\ulLocalShow` features.

Song titles wrap automatically when space is limited, for example in a
two-column section. By default, titles and the author, dedication and extra text
below them leave room for the badges on the right.

To let this text use the full width instead, allowing it to overlap the badges:

```tex
\ulTitleBadgeOverlap{true}
```

Set this in the preamble for the whole book, or inside a group for a particular
section. Use `\ulTitleBadgeOverlap{false}` to restore the default.

Other useful settings:

| Setting | Purpose |
|---|---|
| `\ulTagFile{filename}` | Preamble-only tag-definition filename; default `tags.txt` with the lookup order documented above |
| `\renewcommand{\ulIndexTagFont}{...}` | Tag-index heading font |
| `\ulVerseIndentWidth` | Length used by `\beginverse[<n>]`; change with `\setlength` |
| `\renewcommand{\ulSongEndMark}{...}` | Mark at the right end of the song-ending line |
| `\renewcommand{\ulLyricFont}{...}` | Default lyric font |
| `\renewcommand{\ulChordFont}{...}` | Default chord font |
| `\renewcommand{\ulAltChordsStyle}{...}` | Standalone alternate-chord style |
| `\renewcommand{\ulChordLineBaselineSkip}{...}` / `\ulChordLineLineskipLimit` / `\ulChordLineLineskip` | Annotation-row clearance; neighboring anchors on a physical line share the required baseline |
| `\renewcommand{\ulChordWhitespaceMinimumWidth}{...}` | Minimum advance for a visible annotation followed by source whitespace; zero disables |
| `\renewcommand{\ulTranslationFont}{...}` | Translation font |
| `\renewcommand{\ulNoteFont}{...}` | Font for text notes, attached notes and musical prose notes; not melody hints |
| `\renewcommand{\ulExplanationFont}{...}` | Explanation font |
| `\renewcommand{\ulPassageFont}{...}` / `\renewcommand{\ulAltPassageFont}{...}` | Passage fonts |
| `\renewcommand{\ulMelodySize}{...}` | Melody size for both spacing and rendering; use a font-size declaration such as `\scriptsize` |
| `\renewcommand{\ulMelodySymbolStyle}{...}` | Appearance-only melody-note symbol hook; not called for sizing |
| `\renewcommand{\ulMelodyTagText}{...}` / `\renewcommand{\ulMelodyAltTagText}{...}` | Appearance-only melody-note tag hooks; not called for sizing |
| `\renewcommand{\ulHeaderTitleStyle}{...}` | Header title style |
| `\renewcommand{\ulPageNumberStyle}{...}` | Page-number style in headers |

### Optional spacing and bar styling

The default styling usually works well; most authors need none of these changes.
The examples below are optional overrides, not default values.

Use `\ulMelodySize` for note-size changes rather than a font-size command inside
`\ulMelodySymbolStyle`: the size setting keeps circles and their shared spacing
grid in agreement. The symbol/tag hooks are for appearance and are not run during
measurement. An annotation row shares its required baseline across a physical line,
so a deep chord label does not leave just one melody hint floating above its neighbors.

`\ulVerseBaseline{natural}{stretch}{shrink}` sets nominal lyric-line baseline
glue; `\ulVerseSeparation{natural}{stretch}{shrink}` sets inter-verse glue.
All three arguments are finite, nonnegative scalars multiplying the configured
lyric font's capital-`A` height. The baseline is the **total nominal baseline
distance**, not an amount added to the font size. Actual ink clearance and minimum
gaps can require more space. `\ulVerseMinimumGap{dimension}` sets the minimum
clearance between lyric lines.

Call the scalar setters after font customization: they resolve dimensions when
called and do not automatically rescale after later font changes. Settings obey
TeX grouping; keep a local override's group around the affected verses.

These scalar settings control lyric verses, not prose line leading. Translations
use their selected font's normal line spacing (`\small` before
`\ulTranslationFont`). Passages and explanations likewise use their selected
font's normal line spacing, multiplied by `\ulPassageBaselineMultiplier` or
`\ulExplanationBaselineMultiplier` (both default to `1`). For example:

```tex
\renewcommand{\ulTranslationFont}{\small\itshape}
\renewcommand{\ulExplanationFont}{\rmfamily\small}
\renewcommand{\ulExplanationBaselineMultiplier}{1.1}
```

Illustrative overrides only, **not documented defaults**, after font setup:

```tex
\ulVerseBaseline{1.8}{0}{0}
\ulVerseSeparation{1.7}{0}{.2}
\ulVerseMinimumGap{1pt}
```

For advanced relative calculations, the read-only, expandable
`\ulVerseSpacingScale{baseline|separation}{natural|stretch|shrink}` returns the
stored scalar (choose one key from each pair of braces). Use it in numeric
expressions with these setters rather than accessing private registers.

`\ulMeasureBarTop{occupied logical level}{reference level}{scale}` and
`\ulRepeatBarTop{occupied logical level}{reference level}{scale}` independently
choose bar tops. Occupied levels are `0` for lyrics/beats, `1` for chords or low
melody hints, `2` for normal hints, and `3` for higher hints. Hidden annotations
and rests do not increase the occupied level. Choose a reference level from `0`
through the occupied level, including a lower one for a deliberately shorter bar.

The target top is `reference bottom + BASE * scale`, with a finite, nonnegative
scale. Reference `0` uses the lyric capital-`A` height at the lyric baseline;
reference `1` uses the chord capital-`A` height at the chord-row base. References
`2` and `3` use the actual melody circle's bottom and diameter as `BASE`.
If the selected melody lane is empty, its usual position uses circle dimensions
from the nearest visible hint; this does not print a phantom annotation.
`\ulUseVerseAnnotationMinimum{true}` enables a one-level minimum for otherwise
plain or beat-only lines in a verse containing visible chords or melody hints;
`{false}` disables it. It never reserves multiple absent melody rows, and a wholly
beat-only verse stays compact. Meter labels and actual ink bounds remain protected
even when a shorter bar top is requested.

`\ulRepeatBarBottomScale{scale}` controls the repeat bar's extension below the
lyric baseline in multiples of the lyric capital-`A` height.
`\ulRepeatBarMinimumGap{dimension}` limits how closely separate, complete repeat
bars in the same column can approach; `0pt` disables it. It does not separate
nested bars or fragments continuing the same repeat. These bar settings are
scoped too.

Illustrative overrides only, **not documented defaults**:

```tex
\ulMeasureBarTop{3}{2}{.9}
\ulRepeatBarTop{2}{1}{1.1}
\ulRepeatBarBottomScale{.04}
\ulRepeatBarMinimumGap{2pt}
```

For custom class development beyond these settings, see
[developer navigation](ARCHITECTURE.md#developer-navigation). Build-output
choices such as lyrics-only and instrument variants, plus multikey editions
where supported, are configured separately; see
[Variants and editions](README.md#variants-and-editions).

## Extension points

Use the documented class options, preamble settings and scoped local requests.
Build declared variants through the [compiler](README.md#variants-and-editions).
`\ulSongColumns{0}`, `{1}` and `{2}` select unpositioned flow, one column and two
columns respectively; set columns outside an individual song. `\ulSongPosition{0}`
through `{3}` control song-positioning lookahead, not the number of columns.
Zero disables lookahead; 1 considers spreads in two-sided books (pages otherwise),
2 considers pages, and the default 3 first tries to keep a song within one column
before trying page/spread placement. LaTeX still breaks material that cannot fit.

Custom metadata keys retain the conventional reset/set callback interface:

```tex
\newcommand{\songregion}{}
\ulNewSongKey{region}{\renewcommand{\songregion}{}}{\renewcommand{\songregion}{#1}}
\AddToHook{ulsbs/song/begin}{\typeout{Song region: \songregion}}
```

Put declarations in the preamble, then use `region={...}` in `\beginsong`.
The reset runs before each song's option list, and the set callback receives
the field value as `#1`. A custom field does not automatically become a printed
badge or an exported JSON field.

The argument-free LaTeX hooks are `ulsbs/song/begin`, `ulsbs/stanza/start`,
`ulsbs/stanza/finish`, `ulsbs/song/finish`, `ulsbs/index/record` and
`ulsbs/song/anchor`. Accessors such as `\ulSongTitle`, `\ulSongAuthors`
and `\ulSongId` are available in the relevant song scope. Stanza hooks run once
per stanza, not once per transposition layer. The anchor hook runs when anchor
nodes are inserted, not when their eventual page coordinates become known.
Hooks may run while a song is being boxed, including a song later excluded by a
selection; they are not publication callbacks. Only documented public commands
and hooks are supported extension points.
See [song engine ownership](ARCHITECTURE.md#song-engine) for boundaries.
