# Writing Songbooks with ULSBS

This guide explains how to write songs and organize your own book with ULSBS.
For installation, your first complete project, compiler options, and output
variants and editions, start with the [README](README.md). Engine internals
belong in [Architecture](ARCHITECTURE.md).

ULSBS builds on LaTeX, LilyPond, and Kevin W. Hamlen's `songs` LaTeX package.
The examples below use ULSBS's current syntax. The underlying
[`songs` documentation](https://songs.sourceforge.net/songsdoc/songs.html)
is useful additional reading; its PDF is also bundled at
[`misc/ext_package_songs_distribution/songs.pdf`](misc/ext_package_songs_distribution/songs.pdf).
Where this guide describes ULSBS-specific syntax, use it rather than an older
`songs` example, especially for melody hints and repeat markup.

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
- [Tags and indices](#tags-and-indices)
  - [Defining your own tags](#defining-your-own-tags)
- [Creating song selections](#creating-song-selections)
- [Layout and style reference](#layout-and-style-reference)
  - [`ulsbs-songbook` document class options](#ulsbs-songbook-document-class-options)
  - [Preamble configuration after loading the class](#preamble-configuration-after-loading-the-class)

## Your first song

Put song definitions inside a `songs` environment in the main document, either
directly or through `\input{content/songs_main.tex}`:

```tex
\begin{songs}{titleidx,authidx,tagidx}
\input{content/songs_main.tex}
\end{songs}
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

Compile the main document, not the included song file:

```sh
./ulsbs/ulsbs-compile --quick my-songbook_A5.tex
```

## Verses

Start a verse with `\beginverse` and close it with `\endverse`. The supported
forms are `\beginverse`, `\beginverse[n]`, `\beginverse*`,
`\beginverse*[n]`, `\beginverse+`, `\beginverse+[n]`, `\beginverse*+`,
and `\beginverse*+[n]`. Combined modifiers must appear in the order
`*`, then `+`, then `[n]`.

- `*` makes the verse unnumbered.
- `[n]` indents the whole verse by `n` times `\verseindentwidthbase` (default `1em`).
- `+` increases lyric-line spacing for melody notes beyond the first line when
  chords and melody notes are visible. Normal spacing returns at `\endverse`.

```tex
\beginverse*+[2]
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

The alternatives have superscript repetition numbers. Balanced brace arguments
are required; the former `\ac<1>{Em}` form is not supported.

The `songs` package can memorize and replay chord sequences with `^` in later
verses. ULSBS also replays melody/beat annotations; see
[replay and spacing](#replay-advance-and-whitespace) for the detailed rules.

### Alternate chord sets

Use `\altchords{...}` for a standalone alternate chord set; `\id[<n>]{...}`
labels it, and `\ac{<n>}{<chord>}` identifies a repetition-specific chord:

```tex
\altchords{\id[1]{alt. (C)}|C |\ac{2}{D} |E}
```

Standalone alternate sets do not switch with multikey PDF layers and do not
follow source `\transpose` by default. Enable source transposition explicitly
with `\transposealtchordstrue`; restore the default with
`\transposealtchordsfalse`.

When enabled, plain chords and chord-like content inside `\id` and `\ac` follow
the current interval. Write accidentals as `#` and `&`; `\shrp` and `\flt` are
not part of the supported transposable `\altchords` syntax. Protect content that
must remain unchanged with `\notrans{...}`:

```tex
\transpose{2}
\transposealtchordstrue
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

For a measure with no lyrics at that spot, use `\e`:

```tex
\beginverse
  |\[C]Hold this note |\[G7]\e
\endverse
```

To hide measure bars in the output, use `\measuresoff`.

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

`\prep{<n>}` puts a repeat count on its own line after `\beginrep`.
`\goto{Beginning words of the verse}` marks a jump target by text.
ULSBS does not use the original `songs` package's `\beginchorus` / `\endchorus`
environments for repeat markup.

## Page and line breaks

The `songs` package handles most line and page breaking automatically.
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
| `cr`, `li` | Underlying `songs` copyright and license fields; metadata is not a substitute for permission to publish |

Only add the optional fields relevant to your book. The
[visibility switches](#preamble-configuration-after-loading-the-class) control
which prelude information is displayed. Recommended singing keys (`gk=`) are
recommendations, not transposition instructions, and do not switch with multikey
layers.

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
annotation is needed. `\showtranslationfalse` hides all translations;
`\translationoff` / `\translationon` controls them within a song, subject to
the global switch.

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
note-like style. `\showexplanationfalse` and
`\showpassagefalse` hide their respective environments. The `feeler` environment
provides another short, styled text block inside a song:

```tex
\begin{feeler}
  Quietly, with a steady pulse.
\end{feeler}
```

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

The leading `^` retains its `songs` replay meaning. `\[^<C>Am]` is excluded
from chord memorization; a bare `^` in lyric text later replays the next saved
annotation, including its chord, melody, and beats. Note and beat visibility is
evaluated at replay time.

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
`\melodyPrimaryPosition{normal}` or `low` selects the primary lane (default:
`normal`). `\melodySecondaryPosition{above}`, `below`, or `same` selects the
secondary lane relative to it (default: `above`); `same` is the primary lane.
With a low primary, `above` is the normal lane and `below` may overlap lyrics.

Set styles independently with `\melodyStyleMapping{normal}` (primary uses the
normal style) or `\melodyStyleMapping{swapped}` (primary uses the alternate
style). Neither setting changes which sequence is primary.

`\shownotesfalse` and `\notesoff` hide notes; `\showbeatsfalse` and
`\beatsoff` hide beats. `\noteson` and `\beatson` restore them. Use
`\beginverse+` for looser spacing when melody hints occur throughout a verse;
ordinary `\beginverse` is suitable when they occur only on its first line.

Legacy `\mn*`, `\ma*`, `\bm*`, and `\usealtmnstyle...` authoring commands
are removed. Use the [migration utility](README.md#ulsbs-migrate-syntax-v1) for
older sources, not for new songs.

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
\ulTOC

\ulMainChapter{Morning Songs}{blue}
\begin{songs}{titleidx,authidx,tagidx}
\input{content/songs_morning.tex}
\end{songs}

\ulMainChapter{Evening Songs}{violet}
\begin{songs}{titleidx,authidx,tagidx}
\input{content/songs_evening.tex}
\end{songs}
```

`\ulCoverPage{}` generates a title cover; its argument can instead name a cover
PDF. `\ulMainChapter{Title}{color}` starts a chapter with its colored symbol.
The source input order determines the ordinary book's song order. You may put
multiple songs in one file or use one file per song. Files named `songs_*.tex`
are a useful convention, not a requirement.

## Tags and indices

The `songs` environment's argument selects which index data to collect.
The standard index names are `titleidx`, `authidx`, and `tagidx`.
To display the automatically generated title and tag indices, place these after
the relevant `songs` environments:

```tex
\showindex{Song Title Index}{titleidx}
\showindex{Tag Index}{tagidx}
```

The compiler generates the title index between LaTeX passes. It generates the
tag index when `include/tags.can` exists. `authidx` is declared for author-index
data, but the current compiler does not run its index-generation step; simply
adding `\showindex{Author Index}{authidx}` is not enough to generate an author
index automatically. Author-index processing requires a manual `songs` index
workflow. The table of contents (`\ulTOC`) is separate from these indices.

### Defining your own tags

Create `include/tags.can` in your project. Each tag definition occupies two
lines: the name (optionally followed by `|`-separated aliases), then `1`:

```text
light
1
love|affection
1
peace
1
```

The `1` is required by the underlying scripture-index format; it is not shown
as a tag number. Tags appear in the index in definition-file order, so arrange
the file as you want the index ordered. An alias indexes under the first name.

Use the tag names in song metadata:

```tex
\beginsong{Song name}[id={song-name},tags={love, peace}]
  \beginverse
    Example lyrics.
  \endverse
\endsong
```

Use `\showtagsfalse` in the main preamble to hide tag display/usage. A book
without tags needs no tag-definition file; omit the tag `\showindex` call in
that case. The compiler may report that tag-index generation was skipped.

## Creating song selections

For a reusable selection, create another main document with the same class,
needed preamble settings, and song inputs, and add this in its preamble:

```tex
\includeonlysongs{3,1,7}
```

This selects **song numbers**, not `id=` values, and uses the selection order
within a `songs` environment. The numbers refer to the original numbering from
the included collection; selecting songs does not automatically renumber them
from 1. Keep the input collection and numbering setup consistent with the source
book. The command is allowed in the preamble or between `songs` environments,
not inside one.

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
`\begin{document}`. Most visibility settings are boolean switch pairs, not
commands taking `true` or `false` as an argument:

```tex
\showtagsfalse
\showgoodkeysfalse
\renewcommand{\ulSongEndMark}{*}
```

| Toggle pair | Default | Meaning |
|---|---|---|
| `\showextrue` / `\showexfalse` | `true` | Show extra prelude info (`ex=`) |
| `\showofftrue` / `\showofffalse` | `true` | Show offered-to info (`off=`) |
| `\showkeytrue` / `\showkeyfalse` | `true` | Show the main musical key |
| `\showgoodkeystrue` / `\showgoodkeysfalse` | `true` | Show recommended singing keys |
| `\showphtrue` / `\showphfalse` | `true` | Show phase info in preludes |
| `\showphintoctrue` / `\showphintocfalse` | `true` | Show phases in the TOC |
| `\showtagstrue` / `\showtagsfalse` | `true` | Show tags in preludes / tag index usage |
| `\shownotestrue` / `\shownotesfalse` | `true` | Show melody-note hints |
| `\showbeatstrue` / `\showbeatsfalse` | `true` | Show beat marks |
| `\showauthtrue` / `\showauthfalse` | `true` | Show song authors in preludes |
| `\showlilypondtrue` / `\showlilypondfalse` | `true` | Show LilyPond score blocks |
| `\showpassagetrue` / `\showpassagefalse` | `true` | Show `passage` environments |
| `\showexplanationtrue` / `\showexplanationfalse` | `true` | Show `explanation` environments |
| `\showtranslationtrue` / `\showtranslationfalse` | `true` | Show `translation` environments |
| `\showfeelertrue` / `\showfeelerfalse` | `true` | Show `feeler` environments |
| `\showaltchordstrue` / `\showaltchordsfalse` | `true` | Show alternate chord sets |
| `\showimageinchapternametrue` / `\showimageinchapternamefalse` | `true` | Include chapter symbol/image in TOC and headers |
| `\showimageonchapterfrontpagetrue` / `\showimageonchapterfrontpagefalse` | `true` | Show chapter image/symbol on chapter front pages |
| `\upcaselongchaptertitletrue` / `\upcaselongchaptertitlefalse` | `false` | Uppercase long chapter titles on front pages |
| `\upcaseshortchaptertitletrue` / `\upcaseshortchaptertitlefalse` | `true` | Uppercase short chapter titles in TOC and headers |
| `\upcasesectiontitleinheadertrue` / `\upcasesectiontitleinheaderfalse` | `false` | Uppercase section titles in headers |
| `\upcasebooktitleinheadertrue` / `\upcasebooktitleinheaderfalse` | `true` | Uppercase the book title in headers |
| `\usechaptercolorstrue` / `\usechaptercolorsfalse` | `true` | Enable colored chapter corner marks |
| `\adjustchordcharstrue` / `\adjustchordcharsfalse` | `true` | Apply chord-character typography adjustments |

Other useful settings:

| Setting | Purpose |
|---|---|
| `\verseindentwidthbase` | Length used by `\beginverse[<n>]`; change with `\setlength` |
| `\renewcommand{\ulSongEndMark}{...}` | Mark at the right end of the song-ending line |
| `\renewcommand{\ulLyricFont}{...}` | Default lyric font |
| `\renewcommand{\ulChordFont}{...}` | Default chord font |
| `\renewcommand{\ulChordWhitespaceMinimumWidth}{...}` | Minimum advance for a visible annotation followed by source whitespace; default `.8ex`, `0pt` disables |
| `\renewcommand{\translationfont}{...}` | Translation font |
| `\renewcommand{\explanationfont}{...}` | Explanation font |
| `\renewcommand{\passagefont}{...}` / `\renewcommand{\altpassagefont}{...}` | Passage fonts |
| `\renewcommand{\mnsymbolstyle}{...}` | Melody-note symbol style |
| `\renewcommand{\mntagtext}{...}` / `\renewcommand{\mnalttagtext}{...}` | Melody-note tag text |
| `\renewcommand{\headertitlestyle}{...}` | Header title style |
| `\renewcommand{\pagenumberstyle}{...}` | Page-number style in headers |

For custom class development beyond these settings, see
[developer navigation](ARCHITECTURE.md#developer-navigation). Build-output
choices such as lyrics-only and instrument variants, plus multikey editions
where supported, are configured separately; see
[Variants and editions](README.md#variants-and-editions).
