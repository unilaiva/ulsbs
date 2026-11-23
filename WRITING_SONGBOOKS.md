# Writing Songbooks with ULSBS

This guide explains how to write songs and organize your own book with ULSBS.
For installation, your first complete project, compiler options, and output
variants and editions, start with the [README](README.md). Engine internals
belong in [Architecture](ARCHITECTURE.md).

Use the [`ulsbs-compile` script](README.md#compiling-songbooks) for everyday edits
and final builds; it manages the required processing and typesetting passes.

For a first book, start with [your first song](#your-first-song) and
[book organization](#book-organization), then learn the notation you need.
The defaults are ready to use: you can leave advanced features and configuration
until you have a specific reason to change them.

## Contents

- [Contents](#contents)
- [Getting started](#getting-started)
  - [Your first song](#your-first-song)
  - [Book organization](#book-organization)
- [Writing songs](#writing-songs)
  - [Verses](#verses)
  - [Chords](#chords)
  - [Melody hints and beat marks](#melody-hints-and-beat-marks)
  - [Measure bars](#measure-bars)
  - [Repeats](#repeats)
  - [Song metadata](#song-metadata)
  - [Translations and other text](#translations-and-other-text)
- [Assembling a collection](#assembling-a-collection)
  - [Tags and indices](#tags-and-indices)
  - [Creating song selections](#creating-song-selections)
  - [Page and line breaks](#page-and-line-breaks)
- [Advanced features and configuration](#advanced-features-and-configuration)
  - [Keys and accidentals](#keys-and-accidentals)
  - [Alternate chord sets](#alternate-chord-sets)
  - [Chord diagrams for guitar](#chord-diagrams-for-guitar)
  - [Full melodies with LilyPond](#full-melodies-with-lilypond)
  - [Variants and visibility](#variants-and-visibility)
  - [Layout and style reference](#layout-and-style-reference)
  - [Extension points](#extension-points)
  - [Manual LuaLaTeX builds](#manual-lualatex-builds)

## Getting started

Start with one song and a simple main document. These examples use the standard
defaults, without additional configuration.

### Your first song

In the main document, `my-songbook_A5.tex`, load the `ulsbs-songbook` document
class (or a derived class) and put songs inside a `ulSongs` environment. This
minimal main document includes the songs from a separate file:

```tex
\documentclass[
  paper={a5paper},
  maintitle={My Songbook},
  author={Songbook Author}
]{ulsbs-songbook}

\begin{document}

\begin{ulSongs}{titleidx,authidx,tagidx}
  \input{content/songs_main.tex}
\end{ulSongs}

\end{document}
```

The included `content/songs_main.tex` file contains songs, not another
`\documentclass` or `\begin{document}`. Each song starts with `\beginsong` and
ends with `\endsong`:

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

Compile the main document, not the included song file, with the normal compile
script:

```sh
./ulsbs/ulsbs-compile --quick my-songbook_A5.tex
```

### Book organization

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

Printed song numbering starts at 1 in each `ulSongs` environment and advances
by one after each song. Chapter headings do not reset it. To give the next song
a specific number, set `ulSongNumber` inside the environment, before that song's
`\beginsong` command. For example, `\setcounter{ulSongNumber}{1}` restarts numbering
at 1.

Printed song numbers and their formatting are independent of stable song IDs
and repeated-song occurrence identities.

## Writing songs

Use the notation you need, starting with verses and chords. Melody hints, beat
marks and the other annotations are optional; ordinary lyric-and-chord songs
need no extra setup.

### Verses

Start a numbered verse with `\beginverse` and close it with `\endverse`.
Use `\beginverse*` for an unnumbered verse. Either form accepts an optional
indentation factor: `\beginverse[n]` or `\beginverse*[n]`.

- `*` makes the verse unnumbered.
- `[n]` indents the whole verse by `n` times `\ulVerseIndentWidth` (default `1em`).

```tex
\beginverse*[2]
  An unnumbered, indented verse.
  Another line of lyrics.
\endverse
```

Use ordinary `\beginverse` for basic lyrics and chords; the other forms are
optional refinements. Visible chords and [melody hints](#melody-hints-and-beat-marks)
determine their required line clearance automatically; no special verse form is
needed for melody hints.

### Chords

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

Standalone [alternate chord sets](#alternate-chord-sets) and
[guitar chord diagrams](#chord-diagrams-for-guitar) are optional additions
covered later.

### Melody hints and beat marks

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

#### Sequences and offsets

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

#### Replay, advance, and whitespace

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

The default placement and appearance need no setup. Optional
[placement, style and visibility controls](#placement-style-and-visibility)
are described in the advanced reference.

### Measure bars

Use `|` at the **beginning** of each measure, not the end. A line ending does
not itself mean the end of a measure. Use one bar marker per measure.

For a measure with no lyrics after it on the same line, use `\e`, a plain end
dash unrelated to vertical spacing:

```tex
\beginverse
  |\[C]Hold this note |\[G7]\e
\endverse
```

To hide measure bars locally, use `\measuresoff`; `\measureson` restores them
where book policy permits. To hide them throughout the book, put
`\ulShowMeasures{false}` in the preamble. Chord visibility does not control bars.

### Repeats

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

### Song metadata

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

### Translations and other text

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

## Assembling a collection

Once the songs are in place, add the indices and selections your book needs.
Let the normal layout handle pagination first; use explicit breaks only where
the musical or chapter structure calls for them.

### Tags and indices

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

#### Author names

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

#### Defining your own tags

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

### Creating song selections

For a reusable selection, create another main document with the same class,
needed preamble settings, and song inputs, and add this in its preamble:

```tex
\ulIncludeOnlySongIds{morning-song,river-song,evening-song}
```

Prefer selecting by the song's `id=`: IDs stay stable when songs are renumbered.
`\ulIncludeOnlySongs{3,1,7}` instead selects by printed number. If multiple source
songs match a requested ID or number, only the first is selected, even across
`ulSongs` blocks, and the compiler reports a warning.

Both commands preserve the source numbering by default (`\ulSelectionNumbering{source}`).
Set `\ulSelectionNumbering{sequential}` in the preamble to number selected songs
from 1 in print order, continuing across blocks. Number-based selection matches
source numbers. Entries are ordered within each `ulSongs` block; repeating an entry
prints the same song again and uses the next sequential number.

Set a selection in the preamble or replace it before the next `ulSongs` block.
For a chaptered selection, put each chapter heading outside its `ulSongs` block
and declare the list for that block before it starts. Each declaration replaces
the previous list and starts a fresh duplicate check. Without a selection, all
songs are included; an empty list selects none. Unselected songs do not appear in
the indices or table of contents, although their source and hooks still run.

To change the printed key of an ID-selected song, add a key override before its
block, for example `\ulSelectionSongKey{morning-song}{D}`. This transposes the
printed chords and melody hints in the ordinary edition and sets the starting
key in MULTIKEY editions. The song must declare a supported `key=`. The override
preserves major/minor mode (for example, a minor song moved to `D` prints in
`Dm`). Use `#` for sharp and `&` for flat. This does not regenerate chord
fingerings. In ordinary ULSBS compiler builds, visible LilyPond scores using
supported ULSBS templates are re-engraved in the requested key. If a score
cannot be transposed, the compiler warns and keeps its original notation.
Standalone LuaLaTeX does not re-engrave scores. In MULTIKEY, a song with a key
override still shows the original score without interactive score alternatives.

For a small independent collection, explicitly inputting just the desired song
files is often simpler than a numbered selection. The Unilaiva repository's
[selection example](https://github.com/unilaiva/unilaiva-songbook/blob/main/include/ul-selection_example.tex)
shows its project-specific selection setup; its child class and helper files
are not bundled ULSBS requirements.

### Page and line breaks

Within a verse, each source newline ends a lyric line; long source lines can wrap.
Braces, spaces and `%` comments affect how the source is read and spaced, so take
care when reformatting lyrics. Chord placement and minimum annotation widths also
affect where lyrics wrap.

Hidden alternate PDF layers in optional MULTIKEY editions never reserve extra
space: the effective original notation alone determines line and page geometry.

#### Suggested and forced breaks

- `\brk` suggests a break.
- `\hardbrk` gives a stronger suggestion.
- `\forcebrk` forces a break.

Within a lyric line, these control line wrapping. On their own line in a verse,
or between verses or songs, they control column/page breaks: the next column in
two-column layout, or the next page otherwise. In a song's prose passages, write
`\par` before the command for a column/page break rather than a line break.

#### Starting a new column or page

Put these commands between songs, after `\endsong` and before the next
`\beginsong`:

| Command | Use |
| --- | --- |
| `\nextcol` | Start the next song in the next column. |
| `\sclearpage` | Start the next song on a new page, skipping any unused columns. |
| `\scleardpage` | Start the next song on an even, left-hand page. |
| `\sclearoddpage` | Start the next song on an odd, right-hand page. |

For example, if a song ends in the left column of a two-column page, `\nextcol`
puts the next song in the right column of that same page. `\sclearpage` leaves
the right column empty and starts the next song on the following page.

In a one-column book, both commands normally start the next page. The left/right
commands avoid adding a blank spread if the next song would already start on
the requested side. In one-sided books, both act like `\sclearpage`.

For a simple page break in ordinary text outside the song sections, use LaTeX's
`\clearpage` instead.

#### Breaks in selection songbooks

With either selection command, breaks inside songs stay with those songs, but
breaks between songs in the original source are ignored. Put those breaks in the
selection list instead, using the command name without its backslash. These names
are reserved in selection lists:

```tex
\ulIncludeOnlySongIds{morning-song,sclearoddpage,evening-song}
```

This prints `morning-song`, then starts `evening-song` on an odd page.

Normally use unstarred commands. `\nextcol` and the three page-clear commands also
accept `*`, such as `\sclearpage*`: this acts while the source is read, even during
selection, rather than between songs in the selected order. The star does not
make a break stronger.

Check the compiled PDF after changing breaks, paper size, fonts, or visible
annotations.

## Advanced features and configuration

The rest of this guide is optional reference. Consult the relevant section
when you need transposition, additional notation, another edition or a deliberate
departure from the standard appearance. Most books do not need to customize the
layout and style settings.

Song-content notation uses short lowercase commands; configuration, book assembly,
fonts and metadata accessors use `ulCamelCase` names. Public boolean settings take
an explicit `{true}` or `{false}` argument. Visibility policy is preamble-only;
local requests respect TeX grouping. Use the
commands documented here when writing new sources; see
[syntax migration](README.md#ulsbs-migrate-syntax-v2) when upgrading existing ones.

### Keys and accidentals

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

### Chord diagrams for guitar

Use `\gtab{name}{spec}` for a guitar chord diagram. The specification lists
strings from lowest to highest: `X` mutes a string, `0` leaves it open, and
digits give frets. An optional colon-separated field supplies finger numbers.
Chord names accept raw `#` for sharps and `&` for flats.

For a collection of diagrams, use `ulChordDiagramGrid`:

```tex
\begin{ulChordDiagramGrid}
  \gtab{C}{X32010:032010}
  \gtab{Am}{X02210:002310}
  \\
  \gtab{F#m}{244222:134111}
  \gtab{B&}{X13331:013331}
\end{ulChordDiagramGrid}
```

The grid chooses equal-width columns automatically to fit the available width;
there is no column-count setting. Plain `\\` starts the next row, useful for
grouping chord families; empty or repeated breaks do not create empty rows.
The default row gap and minimum column gap are `1.5pt`. Change them with, for
example, `\begin{ulChordDiagramGrid}[3pt]`. Columns spread across the available
width. Short rows keep the same column positions, leaving the remaining cells
empty rather than spreading their diagrams farther apart.

Neighboring fretboards align at their nut/top-fret rule even when titles,
open/mute marks, fret counts or finger labels differ. Rows can break across
pages. Diagrams keep their normal size unless a diagram is wider than the
available line, in which case it is proportionally reduced to fit on its own.
Standalone and inline `\gtab` appearance is unchanged.

The grid does not generate alternative fingerings for interactive PDF keys.
Source `\transpose` keeps the existing `\gtab` behavior: octave-equivalent
offsets retain the diagram; other offsets use `\gtabtrans`, which by default
prints only the transposed chord name.

### Full melodies with LilyPond

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

MIDI/audio is synthesized from the score, not from the separate LaTeX lyrics or
chord text. Use the compile script to generate it; see
[media exports](README.md#media-exports) for output controls and variant eligibility,
and [multikey editions](README.md#multikey-pdf-editions) for score-transposition
support and fallback behavior.

`\ulShowLilypond` controls display of whole scores, not their generation or media
export. `\ulShowChords` controls only inline TeX chord symbols: it cannot remove
`ChordNames` already engraved in a score. Use the compile script for
[instrument variants](README.md#instrument-variants) with their matching tuning,
clef and tablature recipes.

Score systems that are wider than the available line are automatically reduced
to fit. Smaller systems keep their original size.

#### Converting LilyPond lyrics

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

### Variants and visibility

Declare supported presets literally in the main source, not in an input, macro
or derived class:

```tex
\documentclass[
  variants={default,lyric,charango,bassclef},
  maintitle={My Songbook}
]{ulsbs-songbook}
\ulShowMeasures{false} % Hide bars even in presets that normally show them.
```

Omission means `{default}` only. An explicit list must be nonempty and include
`default` exactly once. Names must be lowercase, unique and known; repeated
declarations and computed values are errors. These rules also apply when the main
document uses a derived `ulsbs-songbook...` class.
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

### Layout and style reference

Use this reference when you need a specific change to the standard appearance.
Keep collection-specific overrides in your main document or a
shared style/derived class, rather than editing the bundled engine. Song notation,
metadata entry and book-assembly commands are described in the earlier sections.
These are LaTeX book settings; output selection and toolchain options are
[compiler configuration](README.md#configuration).
For source ownership, see the [module map](ARCHITECTURE.md#song-engine). Its
companion files are internal modules, not configuration files to input directly.

#### Choosing the right override

The tables describe the standard `ulsbs-songbook` baseline. A derived class may
replace it, and the selected [variant preset](#variants-and-visibility) applies
before your explicit post-class preamble settings. A displayed baseline is not
necessarily a fixed value: some defaults refer to another hook, use current font
units, or are measured once.

| Kind | Mechanism | When to configure |
|---|---|---|
| Class option | `\documentclass[paper={a5paper},...]{ulsbs-songbook}` | At class loading; use options for the settings the class exposes |
| Load-time macro default | `\newcommand{\ulTopMargin}{8mm}` before the class | Before `\documentclass` (or before `\RequirePackage{ulsbs}` in your own class); not retroactive |
| Text, font or rendering macro | `\renewcommand{\ulLyricFont}{\sffamily\large}` | Normally after the class, before affected material is built |
| Allocated length, dimension or skip | `\setlength{\ulAfterPreludeSkip}{0pt plus 4pt}` | After the class; relative units resolve at assignment, not every later use |
| TeX count register | `\ulVerseVersePenalty=200\relax` | After the class; do not use `\setcounter` or `\renewcommand` |
| LaTeX counter | `\setcounter{ulSongNumber}{1}` | Before the next song in `ulSongs`; that environment initializes numbering |
| Public setter | `\ulShowTags{false}`, `\ulVerseBaseline{1.8}{0}{0}` | Follow the setter's timing and scope contract below |
| Public lifecycle hook | `\AddToHook{ulsbs/song/begin}{...}` | Declare in the preamble; runs at the documented source-processing point |

Only defaults explicitly supplied with `\providecommand` accept a definition
before loading. Do not predefine arbitrary commands: many are created with
`\newcommand`, and some early bootstrap hooks are deliberately replaced by the
final common style. Renew font/render hooks after loading for final policy;
this does not repeat load-time font allocation or measurements.

Most post-load styling obeys ordinary TeX grouping. Keep the group around the
entire affected song, verse, prose block or index. Set visibility requests before
the controlled material; body content can be retained in boxes before the page
is shipped. Header changes can also be observed later when pages are built.
Visibility **permissions** are different: they must be set before
`\begin{document}`, not in `\AtBeginDocument`.

#### `ulsbs-songbook` document class options

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

#### Load-time configuration

For values without a class option, define the macro before loading the class:

```tex
\newcommand{\ulTopMargin}{8mm}
\newcommand{\ulHeadHeight}{6mm}
\documentclass[paper={a5paper},bindingoffset={8mm}]{ulsbs-songbook}
```

Do not also predefine a macro that a supplied class option will create. For
example, choose either `paper={...}` or a predefinition of `\ulPaperSize`.

| Macro | Standard baseline / meaning |
|---|---|
| `\ulPaperSize`, `\ulBindingOffset` | `a5paper`, `8mm`; prefer the class options |
| `\ulSideMargin`, `\ulTopMargin`, `\ulBottomMargin` | A5/fallback: `9mm`, `6.35mm`, `9mm`; A4: `12mm`, `9mm`, `12mm` |
| `\ulHeadHeight`, `\ulHeadSep`, `\ulFootSkip` | 10pt: `5mm`, `4mm`, `3.60004pt`; 11pt: `6mm`, `7mm`, `4.5pt`; 12pt: `7mm`, `8mm`, `5.5pt` |
| `\ulPreliminaryLanguage` | `english`; prefer `language={...}`; selects the initial main language and language-dependent default book strings |
| `\ulPdfTranspositionLayers` | `false`; load PDF-layer support |
| `\ulPdfTranspositionLayerUi` | `native` or `hidden`; layer UI policy |
| `\ulPdfTranspositionRequireSongIds` | `false`; require stable song IDs for multikey output |
| `\ulPdfTranspositionMinimumScale` | `.85`; alternative chord-name shrinking floor; compiler accepts `.5` through `1` |
| `\ulMultikeyLilypondScores` | `false`; enable prepared score alternatives |

The compiler normally supplies the PDF-layer settings. Prefer its validated
[edition configuration](README.md#multikey-pdf-editions) rather than setting
them in canonical book sources. They do not select a variant or generate score
alternatives by themselves.

Geometry consumes its inputs at load time. Renewing a margin macro afterward
does not change the page layout. Likewise, renewing `\ulPreliminaryLanguage`
does not reselect the language or rebuild localized defaults. If you deliberately
use geometry's later reconfiguration facilities, also review the eagerly captured
cover and chapter dimensions below. Keep printable margins large enough for
your printer, binding and font protrusion.

#### Preamble configuration after loading the class

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

Other scoped boolean controls are independent of visibility permissions:

| Setter | Baseline | Purpose |
|---|---|---|
| `\ulTransposeAltChords{true\|false}` | `false` | Make standalone alternate sets follow source transposition |
| `\ulTransposeCapos{true\|false}` | `false` | Interpret `\capo{n}` as source transposition instead of a printed instruction |
| `\ulNoLyrics{true\|false}` | `false` | Suppress lyric payload in chord/lyric processing; not a lyrics-only preset |
| `\ulSlides{true\|false}` | `false` | Select the slide-style song heading/title font behavior; does not configure a slide page size |
| `\ulSeparateIndexes{true\|false}` | `true` | Give index displays separate pages |
| `\ulPagePreludesEnabled{true\|false}` | `false` | Center prelude presentation; does not itself change positioning |
| `\ulChapterCornerMarkDashed{true\|false}` | `false` | Dashed corner marks; main chapters reset this to false |

`\ulPagePreludes` enables its presentation switch **and** calls
`\ulSongPosition{0}`. Turning off `\ulPagePreludesEnabled` does not undo that
positioning change. These controls do not change immutable variant identity.

#### Book text and PDF presentation

Renew these argument-free text macros after the class. Class options initialize
many of them; the macros let a shared style supply richer text or localization.

| Macros | Use and baseline |
|---|---|
| `\ulMainBookTitle`, `\ulSubBookTitle`, `\ulSubSubBookTitle` | Main title and optional subtitles; fallback main title is localized, subtitles empty |
| `\ulThisBookTitle` | Header/default PDF title; derives from main title plus nonempty subtitle unless replaced |
| `\ulBookMotto`, `\ulBookByText` | Imprint motto and byline; motto empty, byline has a localized fallback |
| `\ulBookVersion`, `\ulBookVersionPreText` | Version text and label; version defaults to the current ISO-style date |
| `\ulBookVariantPreText` | Imprint variant label |
| `\ulBookDefaultVariantText`, `\ulBookLyricVariantText`, `\ulBookCharangoVariantText`, `\ulBookBassclefVariantText` | Localized display names; changing labels does not rename registered variants |
| `\ulBookWebsiteLink`, `\ulBookWebsiteLinkQrImage` | Website URL and optional QR image filename; both empty by default |
| `\ulBookWebsiteLinkPreText` | Optional author-defined text shown when neither website URL nor QR image is supplied; use `\newcommand` if not already defined |
| `\ulBookCompiledByText`, `\ulImprintPageFootnote` | Compiled-by text derives from a nonempty `\ulBookAuthor`; footnote empty |
| `\ulBookAuthor`, `\ulBookSubject`, `\ulBookKeywords` | PDF defaults: empty author, `Songbook`, and `songbook, songs, ulsbs` |

PDF metadata defaults expand after the author preamble, before hyperref publishes
them. Explicit `\hypersetup{pdftitle={...},pdfauthor={...},...}` values win,
including explicitly empty values. `DocumentVersion` defaults to
`\ulBookVersion` unless supplied in `pdfinfo`. The default PDF title follows
registered variant presentation; changing visibility does not relabel it.

Use hyperref's `\hypersetup` for viewer presentation, for example
`\hypersetup{pdfpagelayout=SinglePage}`. The baseline is `TwoColumnRight`,
`pdfpagemode=UseNone` and `pdfprintscaling=None`. Link colors are listed below.
The bundled sRGB output intent is not a public CMYK/PDF-A customization switch;
named-color changes alone do not convert imported images or certify a PDF.

#### Fonts and typography

Font **selectors** choose already-installed families. They do not avoid the
load-time requirement for the bundled typography's Noto fonts: Noto Serif, Noto
Sans, Noto Sans Mono, Noto Sans Symbols, Noto Sans Symbols2 and Noto Sans Arabic.
ULSBS selects sans-serif as the document default. Use fontspec's font-configuration
commands to change document families, and the following hooks to choose the
font used for each role. Changing a selector later does not redo early metrics.

| Argument-free hook/selector | Standard policy / role |
|---|---|
| `\ulNotoSerifFont`, `\ulNotoSansFont`, `\ulNotoMonoFont` | Installed regular text-family selectors |
| `\ulSerifHeavyFont`, `\ulSansHeavyFont` | Heavy text-family selectors |
| `\ulSymbolFont`, `\ulSymbolHeavyFont`, `\ulSymbolTwoFont` | Musical and other symbol-family selectors |
| `\persianfont`, `\persianfontsf`, `\persianfonttt` | Persian language font selectors, initially sharing Noto Sans Arabic |
| `\ulNanoSize`, `\ulMicroSize` | Small size declarations derived from the class's 10pt/11pt/12pt size choice |
| `\ulLyricFont` | `\sffamily\large`; shared lyric-font policy |
| `\ulLyricFontStyle` | Delegates to `\ulLyricFont`; distinct low-level lyric hook |
| `\ulVerseFont` | Empty additional verse font declarations |
| `\ulSongTitleFont` | Sans-serif, slanted `\Large`; `\Huge` in slide mode |
| `\ulChordFont` | Sans-serif bold `\small`, in `ulChordColor` |
| `\ulAltChordsStyle` | `\footnotesize\itshape`, added to normal chord styling |
| `\ulMeterFont` | Chord-colored `\scriptsize\sffamily\upshape` |
| `\ulEchoFont` | Selects upright/slanted contrast for echo text |
| `\ulNoteFont` | `\small`; textual/attached/musical prose notes, not melody hints |
| `\ulHeaderTitleStyle`, `\ulPageNumberStyle` | Serif `\small`, italic for header titles |

Use `\renewcommand` for the role hooks, not to reinstall a fontspec family.
Prefer `\ulLyricFont` and `\ulChordFont` for shared policy over replacing their
renderers. After changing lyric/verse fonts, call the font-dependent spacing
setters below again. Symbol
hooks `\ulSharpSymbol` and `\ulFlatSymbol` produce accidental glyphs without
arguments. `\ulDeclareFlatSize{current-size}{flat-size}` globally updates the
flat-size mapping (numeric font sizes, for example `{12}{10.95}`); it is not a
group-local font selection.

#### Prelude and numbering

| Setting | Mechanism and purpose |
|---|---|
| `\ulPreludeBadgeFont` | Renew; shared badge font, normally `\scriptsize\normalfont`, `\tiny\normalfont` for lyric presentation |
| `\ulPreludeTagStyle`, `\ulPreludeKeyLineStyle`, `\ulPreludePhaseStyle` | Renew; field styling, empty normally and gray in lyric presentation; key boxes also impose their own color/weight |
| `\ulPreludeTextKey`, `\ulPreludeTextGoodKeysAlone` | Renew; localized key/recommended-key labels |
| `\ulSongNumberStyle`, `\ulVerseNumberStyle` | Renew with one argument, a LaTeX counter name; initially `\arabic` |
| `\ulPrintSongNumber`, `\ulPrintVerseNumber` | Renew with one argument, the formatted label; change ink, not counter values |
| `\ulSongNumberWidth`, `\ulVerseNumberWidth` | `\setlength`; label space, initially measured before final typography |
| `\ulSongTitleDefaultHeight` | `\setlength` or `\settoheight`; title reference height measured at load time |
| `\ulNoSongNumbers`, `\ulNoVerseNumbers` | No-argument commands; hide the corresponding numbering space/printer in scope |

The shared style already calls `\ulNoVerseNumbers`. To re-enable verse numbers,
restore **both** the printer and a nonzero width. For example, after class loading:

```tex
\renewcommand{\ulPrintVerseNumber}[1]{\ulLyricFontStyle #1.\ }
\settowidth{\ulVerseNumberWidth}{{\ulLyricFontStyle 99.\ }}
```

Changing a number font does not recompute its width. After a large title-font
change, you can explicitly remeasure the public reference:
`\settoheight{\ulSongTitleDefaultHeight}{\ulSongTitleFont Tih}`. Fixed private
badge offsets are not author settings; a substantially different heading design
should use the public renderer hooks instead of patching private box internals.

#### Cover icons, chapters and headers

`\ulSetPermanentCoverIcons[file1][file2]...` and
`\ulSetVariableCoverIcons[file1][file2]...` accept up to eight optional filenames;
omitted slots are cleared. The default variant keeps authored variable icons.
Other presets replace them when `\ulCoverPage{...}` runs, or clear them with
`\ulCoverPage*{...}`. Permanent slots are unchanged. To customize preset icons,
renew `\ulChordsTagIcon`, `\ulTrebleclefTagIcon`, `\ulBassclefTagIcon`,
`\ulLyricsOnlyTagIcon` or `\ulCharangoTagIcon` (each expands to a filename).

Renew `\ulInsertCoverIcons` to choose an arrangement: `\ulInsertCoverIconsVtl`,
`Vtr`, `Vbl`, `Vbr` for vertical corners; `\ulInsertCoverIconsHtl`, `Htr`, `Hbl`,
`Hbr` for horizontal corners; `\ulInsertCoverIconsHtc` or `Hbc` for horizontal
top/bottom center. Each suffix here completes the full command name. The baseline
is `\ulInsertCoverIconsHbc`. `\ulVariantIconsTextSize` is the separate
argument-free imprint icon renderer.

| Allocated dimension | Initial value / use; change with `\setlength` |
|---|---|
| `\ulCoverPermanentIconSize`, `\ulCoverPermanentIconGap` | `.090169\textwidth`, `.021286\textwidth` |
| `\ulCoverVariableIconSize`, `\ulCoverVariableIconGap` | Copies of permanent size/gap, not live aliases |
| `\ulCoverIconLeftOffset` | Captured `-\parindent` |
| `\ulCoverIconTopOffset` | Captured `-\topskip-\headsep-\headheight` |
| `\ulChapterCornerMarkOffset`, `\ulChapterCornerMarkWidth` | `2.5mm`, `.954915mm` |
| `\ulChapterCornerMarkLength` | Captured `\ulTopMargin+\ulHeadHeight-\ulChapterCornerMarkOffset` |

These dimensions are captured eagerly during package loading. Later geometry,
font or permanent-icon changes do not automatically update related dimensions.

`\ulChapterCornerMarkDashCount` is a TeX count, initially `3`, that gives the
number of gaps per leg. Dashed marks keep a filled elbow and divide the space
beyond it equally between dashes and gaps on both legs, using the current mark
length, width and gap count. A count of `0` yields a solid mark.

Renew `\ulChapterSymbol` to replace the no-image chapter symbol. Chapter color
comes from `\ulMainChapter`'s color argument, not a fixed global palette. Main
chapters reset dashed marks to solid, so request dashed output after the chapter
command for following pages. Keep marks clear of printer/cutting margins.

The `ulsbs` and `ulsbstoc` fancyhdr page styles use the header hooks above.
Chapter-opening and other automatically plain pages may need a separate
`\fancypagestyle{plain}{...}` customization. `\ulToc` restores `ulsbs`, not an
arbitrary previously selected page style.

#### Prose and index presentation

Renew the macros in this table before the environment/index is constructed;
language lists are comma-separated uppercase codes, empty by default.

| Macros | Standard policy / purpose |
|---|---|
| `\ulTranslationFont` | Empty extra declarations after the built-in `\small` |
| `\ulPassageFont`, `\ulAltPassageFont` | Lyric font; alternate adds normal-size sans-serif italics |
| `\ulPassageTitleFont` | Delegates to `\ulSongTitleFont` |
| `\ulExplanationFont`, `\ulExplanationTitleFont` | Serif `\footnotesize`; bold title declarations |
| `\ulPassageBaselineMultiplier`, `\ulExplanationBaselineMultiplier` | `1`; multiply the selected prose font's normal leading |
| `\ulPassageLanguagesToSkip`, `\ulExplanationLanguagesToSkip` | Hide entire blocks with listed language codes, without changing visibility permissions |
| `\ulPassageOmitLangCodes`, `\ulExplanationOmitLangCodes` | Hide only the language-code labels, not the text |
| `\ulIndexHeadingFont` | Sans-serif bold `\LARGE` alphabet panels |
| `\ulIndexTitleFont`, `\ulIndexLyricFont` | Sans-serif ordinary entries; slanted alternate/lyric entries |
| `\ulIndexTagFont`, `\ulIndexAuthorFont` | Sans-serif small slanted tag headings; small bold authors |
| `\ulIndexRefsFont` | `\normalfont\normalsize` reference labels |
| `\ulIndexContinuation` | One-argument renderer for a continued index heading |

Use `\setlength` for `\ulPassageLeftSkipAdd` and `\ulPassageRightSkip` (both
initialized to `2em` in the load-time font), `\ulContentIndentWidth` (`7.33pt`,
shared by passage/repeat layout), and `\ulIndexHeadingWidth` (`1.5cm`; zero hides
alphabet panels). Use `\ulTagFile{filename}` in the preamble for the tag
vocabulary. The [author parsing setters](#author-names) configure collection,
not appearance. `\ulTitlePrefixWord{word}` configures title-prefix rotation in
indices; declare indexing policies before collecting songs, not during display.

Hidden `translation`, `passage` and `explanation` blocks use line-oriented source
skipping: keep their `\end{...}` on its own source line, and do not wrap an
entire potentially hidden environment in a captured macro argument.

#### Melody and circle appearance

Use the [lane and style setters](#placement-style-and-visibility) for semantic
placement. Renew these argument-free macros for visual policy:

| Macro | Baseline / meaning |
|---|---|
| `\ulMelodySize` | `\scriptsize`; shared rendering and neutral slot size |
| `\ulMelodySymbolStyle` | Empty appearance-only declarations after the base melody font/color |
| `\ulMelodyTagStyle` | `\fontsize{3.5pt}{4.5pt}\selectfont` |
| `\ulMelodyTagText`, `\ulMelodyAltTagText` | Empty normal/alternate tags; reserve no width |
| `\ulMelodyTagHorizontalAdjustmentFactor`, `\ulMelodyTagVerticalAdjustmentFactor` | `.1`, `.8`; offsets in the melody font's `ex`, not the tag font's |
| `\ulMelodyNormalHeightFactor`, `\ulMelodyLowHeightFactor`, `\ulMelodyHighHeightFactor`, `\ulMelodyLowestHeightFactor` | `1.85`, `.3`, `3.4`, `-1.25`; lane raises in the current chord font's `ex` |
| `\ulCircledWidestSymbol` | Width/height sample for shared circle geometry; default is the widest melody spelling sample |
| `\ulCircledHorizontalPadding`, `\ulCircledCircleExtraDiameter` | `.08ex` side padding; `.05ex` added diameter |
| `\ulCircledCircleVerticalShift` | `.1ex`; shifts the circle only, not its text |
| `\ulCircledCircleLine`, `\ulCircledCircleOpacity` | `.3pt` stroke, `.7` opacity |

Circle diameter/radius are cached globally on **first use per numeric font
size**, not per family, weight, style or TeX group. Set sample, extra diameter
and font policy before the first circle/neutral melody-slot measurement at each
size. Later changes at an already cached size do not remeasure it, even if the
first use occurred inside a group. Padding, shift, stroke and opacity are read
when drawing. There is no public cache-reset API. Prefer a consistent circle
policy throughout a book; do not patch private cache macros.

#### Placement, style, and visibility

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

#### Named colors

After class loading, use xcolor's `\definecolor` or `\colorlet` to replace named
colors. A color name is not a command to renew:

```tex
\definecolor{ulChordColor}{rgb}{.15,.10,.25}
\colorlet{ulLanguageSectionMarkColor}{ulChordColor}
\renewcommand{\ulNoteBackgroundColor}{white}
```

| Color names | Use |
|---|---|
| `ulChordColor` | Chords, meter and chord-colored musical prose |
| `ulTransposedKeyColor` | Non-original multikey prelude keys |
| `ulAltInlineChordColor` | Inline repetition-specific alternate chords |
| `ulAltChordColorA` through `ulAltChordColorF` | Standalone alternate-set palette, selected with `\id[1]` through `[6]` |
| `ulMeasureBarColor`, `ulRepetitionSignColor` | Measure bars; repeat signs/counts |
| `ulMelodyNoteColor`, `ulMelodyNoteAltColor` | Normal/alternate melody styles |
| `ulPlayoutMarkColor` | Playout mark |
| `ulSongNumberBackgroundColor`, `ulNoteBackgroundColor`, `ulIndexBackgroundColor` | Song-number, note and alphabet-panel backgrounds; corresponding same-named macros select the color name |
| `ulInternalLinkColor`, `ulUrlLinkColor`, `ulLinkBoxColor` | Internal/external links and configured link-border color (borders are not normally visible with colored links) |
| `ulLanguageSectionMarkColor` | Raised prose marks; initialized as a copy of `ulChordColor`, not a live alias |
| `ulLanguageEnglishColor`, `ulLanguagePortugueseColor`, `ulLanguageFinnishColor` | Language-specific prose colors |

Replace palette colors before use. Already retained boxes and copied alternate
set colors are not recolored retroactively; redefining `ulChordColor` also does
not update a previously copied `ulLanguageSectionMarkColor`.

#### Layout dimensions and break policy

| Setting | Mechanism / baseline |
|---|---|
| `\ulVerseIndentWidth` | `\setlength`; optional verse/line indent unit, `1em` captured before final typography |
| `\ulAfterPreludeSkip`, `\ulBeforePostludeSkip` | `\setlength`; `0pt plus 8pt minus 6pt`, `0pt plus 0pt minus 12pt` |
| `\ulSongBarHeight` | `\setlength`; song/intersong top and bottom rule thickness, `1pt` |
| `\ulSongEndMark` | Renew; empty mark at the right of that rule |
| `\ulColumnBottomGlue` | Renew; `0pt plus .5\textheight`, finite stretch to absorb unused column space |
| `\ulChordLineBaselineSkip`, `\ulChordLineLineskipLimit`, `\ulChordLineLineskip` | Renew dimension-valued macros, not length registers; 10pt defaults `10.6pt`, `.5pt`, `.5pt`; 11pt `11pt`, `.8pt`, `.8pt`; 12pt `12pt`, `1pt`, `1pt` |
| `\ulChordWhitespaceMinimumWidth` | Renew; `.8ex` in lyric font; zero disables the source-whitespace minimum |
| `\ulRepeatBarWidth`, `\ulRepeatBarGap` | `\setlength`; `1.4pt`, `2.265pt` |
| `\ulRepeatBarDepth` | `\setlength`; `.25pt` inline repeat-sign depth, not the verse-left bottom policy |
| `\ulRepeatBarHeightAdjustmentWithChords`, `\ulRepeatBarHeightAdjustmentNoChords` | `\setlength`; `-2.5pt`, `.5pt`, for inline repeat-sign heights |
| `\ulRepeatBarContinuationDashLength`, `\ulRepeatBarContinuationDashGap` | `\setlength`; `2pt`, `1.25pt` at page/column continuations |
| `\ulRepeatBarContinuingOverlap` | Renew; `.7\baselineskip` resolved at use, for continuous multi-line repeat bars |

Assign penalty counts directly. Lower values encourage a break; values at or
below `-10000` force one. Standard baselines are:

| Count register | Value / boundary |
|---|---|
| `\ulSongPenalty` | `0`, between songs |
| `\ulVerseVersePenalty` | `200`, between verses |
| `\ulBreakPenalty`, `\ulHardBreakPenalty` | `50`, `-500`, for `\brk` / `\hardbrk` |
| `\ulGluePenalty` | `950`, for glued verses |
| `\ulBlockPenalty` | `0`, before/between in-song blocks |
| `\ulTranslationVersePenalty` | `900`, between translation verses |

The common style also sets LaTeX's `\interlinepenalty=1000` and
`\emergencystretch=3em`. `\ulSeparateVerses` forces breaks between verses and
selects infinitely stretchable column-bottom glue; it is not just a font change.
For columns and song-fit policy use `\ulSongColumns` / `\ulSongPosition` as
described under [Extension points](#extension-points).

`\ulEndSongVfill{true|false}` controls the active song's ending fill. Unlike
ordinary grouped style, it updates shared song state through inner groups;
outside a song it has no effect, and song end restores enabled fill for the
next song. Prose/media helpers may update this state too, so set an explicit
override after the blocks whose default you want to replace.

Guitar diagrams use `\ulMinFrets=4\relax` (a count, minimum displayed fret rows).
`\ulBarreDelims{open}{close}` registers an additional scoped delimiter pair;
parentheses and square brackets are already registered, and duplicate openers
are errors. Renew `\gtabtrans` with two arguments, chord name and diagram
specification, to customize non-octave source-transposed diagrams; the default
prints only the transposed name. Grid gaps are environment options, not global
column-count settings; see [Chord diagrams](#chord-diagrams-for-guitar).

#### Optional spacing and bar styling

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

The standard baseline is `\ulVerseBaseline{1.618034}{0}{0}`,
`\ulVerseSeparation{1.618034}{0}{.4}` and `\ulVerseMinimumGap{1.25pt}`.
These scalars are font-relative design choices, not fixed point dimensions.

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

For both measure and verse-left repeat bars, the baseline top policies are
`{0}{0}{1.3}`, `{1}{1}{1.3}`, `{2}{2}{.85}` and `{3}{2}{.85}` for occupied
levels 0 through 3. The verse annotation minimum is enabled, the repeat bottom
scale is `.025`, and the repeat minimum gap is `3pt`. Minimum-gap setters resolve
`em`/`ex` at the call site; they do not track subsequent font changes.

Illustrative overrides only, **not documented defaults**:

```tex
\ulMeasureBarTop{3}{2}{.9}
\ulRepeatBarTop{2}{1}{1.1}
\ulRepeatBarBottomScale{.04}
\ulRepeatBarMinimumGap{2pt}
```

#### Advanced rendering hooks

Prefer the smaller style hooks above. These public renderers are available for
custom classes and substantially different presentation. Renew them after the
class, preserving their argument counts and grouping. They are not alternative
song parsers or output/shipout callbacks.

| Hook | Arguments and responsibility |
|---|---|
| `\ulPrintChord` | One chord-text argument; baseline delegates to `\ulChordFont` |
| `\ulChordLocals` | None; chord-local token/character setup, including common parenthesis typography |
| `\ulChordLineParams` | None; supplies annotation-row baseline/line-skip parameters; common policy reads the three chord-line macros above |
| `\ulTransposedChordFormat` | `{original}{transposed}` visual text formatter; default prints the second argument |
| `\ulVerseJustify`, `\ulNoteJustify` | None; paragraph justification/metrics for verses and textual notes |
| `\ulEveryVerse` | None; extra stanza-start setup after the public start hook |
| `\ulVerseMark`, `\ulSongMark` | None; material emitted at stanza start / before the assembled song prelude |
| `\ulPlaceVerseNumber` | One box-register argument; positions and consumes the rendered verse-number box |
| `\ulExtendPrelude` | None; attribution, dedication and extra text below the title; replacing it replaces their default display guards too |
| `\ulExtendPostlude` | None; default copyright/license text |
| `\ulMakePrelude`, `\ulMakePostlude` | None; whole heading/footer construction, called when the song is assembled after its body source |
| `\ulChapterCornerMark` | `{page-anchor}{x-sign}{y-sign}`; draws one mark inside the caller's TikZ picture; signs are `+` or `-` |
| `\ulChapterCornerMarksOuter` | `{R}` or `{L}`; emits the outer-corner overlay, subject to chapter-color policy |
| `\ulIndexDisplayEntry`, `\ulIndexDisplayAltEntry` | `{entry text}{linked references}`; index entry presentation, not collection |

Rendering hooks may be evaluated for measurement as well as visible output.
Keep them free of external side effects, counter advances and source-consuming
operations. Melody symbol/tag appearance hooks are explicitly excluded from
neutral sizing, while `\ulMelodySize` participates in both sizing and drawing.
The retained line layout may lift neighboring annotation rows to protect visible
ink without rerunning the chord-line hook.

A replacement renderer must preserve the behavior it still needs: effective
visibility guards, title iteration, number widths, metadata badges, anchors and
multikey presentation are not automatically restored inside a replacement
`\ulMakePrelude`. In particular, rendering hooks are not a way to bypass a
variant's book permissions. Use the public accessors and lifecycle hooks below,
not private `ulsbs@...`, `__ulsbs_...` helpers, attributes or caches.

For custom class development beyond these settings, see
[developer navigation](ARCHITECTURE.md#developer-navigation). Build-output
choices such as lyrics-only and instrument variants, plus multikey editions
where supported, are configured separately; see
[Variants and editions](README.md#variants-and-editions).

### Extension points

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

The public LaTeX hooks are argument-free; append code with `\AddToHook`, rather
than replacing internal callbacks:

| Hook | Execution point |
|---|---|
| `ulsbs/song/begin` | After song metadata is parsed and the song layout scope starts, before body source |
| `ulsbs/stanza/start` | During stanza setup, before its lyric source; once per stanza, not per PDF layer |
| `ulsbs/stanza/finish` | At stanza completion, before leaving its scope |
| `ulsbs/song/finish` | At `\endsong`, before final body closure and prelude/postlude assembly |
| `ulsbs/index/record` | When an enabled index record is constructed, not when an index page is printed |
| `ulsbs/song/anchor` | When song anchor nodes are inserted, not when eventual page coordinates become known |

Accessors such as `\ulSongTitle`, `\ulSongAuthors` and `\ulSongId` are available
in the relevant song scope. Hook code must not assume that the final page,
column or selected-output order is already known.
Hooks may run while a song is being boxed, including a song later excluded by a
selection; they are not publication callbacks. Only documented public commands
and hooks are supported extension points.
See [song engine ownership](ARCHITECTURE.md#song-engine) for boundaries.

### Manual LuaLaTeX builds

**Advanced diagnostics, not normal use.** Prefer the
[`ulsbs-compile` script](README.md#compiling-songbooks) for everyday authoring and
final builds. It manages the required tools, passes and output processing. If you
want to use host tools rather than a container, use its `--no-container` option;
that is still the normal compiler workflow.

Direct LuaLaTeX invocation is useful for isolating typesetting problems or checking
the engine in a small standalone fixture. A book containing lyrics, chords and
melody hints can compile this way without Python, LilyPond or an upstream `songs`
install, but raw LilyPond environments require the compiler's preprocessing.
Keep all companion ULSBS assets together, not just `ulsbs.sty`. For these advanced
checks, from the project root with the engine checked out in `ulsbs/`, a POSIX-shell
setup is:

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

Direct compilation uses `default` automatically; select other declared variants
through the [compile script](README.md#variants-and-editions).

These commands produce a TeX PDF and intermediate files, not a complete compiler
build. They do not run LilyPond preprocessing or the compiler's PDF optimization,
multikey range packaging, JSON, printout, media-export or deployment steps. Merely
enabling PDF layers in manual TeX does not produce a validated
`_MULTIKEY_RANGES.json` package. Use `ulsbs-compile` for normal builds and publication.
