# ULSBS

ULSBS (**Unilaiva Songbook System**) is a reusable engine for building songbooks
from LaTeX and Lilypond sources.

It provides:

- the `ulsbs-compile` CLI for compiling songbooks
- the base LaTeX classes and styles used by songbook documents
- helper tools such as `ulsbs-bookmeta`, `ulsbs-midi2audio`, and `ulsbs-ly2tex`
- `ulsbs-migrate-melody-syntax` for safe legacy melody-hint migration
- a VS Code extension for editing ULSBS song files

ULSBS is intended to be used not only by the Unilaiva Songbook repository, but
also by other songbook repositories or local songbook directories.

For a real-world example of a repository using ULSBS, see:

- <https://github.com/unilaiva/unilaiva-songbook>

...and for a songbook produced from that repository:

- <https://unilaiva.aavalla.net>

---

- [Status and compatibility](#status-and-compatibility)
- [Quick start](#quick-start)
  - [Recommended setup: use ULSBS as a git submodule](#recommended-setup-use-ulsbs-as-a-git-submodule)
  - [Use ULSBS with an arbitrary local songbook directory](#use-ulsbs-with-an-arbitrary-local-songbook-directory)
  - [Use a pip-installed engine](#use-a-pip-installed-engine)
- [Minimal songbook project](#minimal-songbook-project)
  - [Minimal main document](#minimal-main-document)
  - [Minimal `ulsbs-config.toml`](#minimal-ulsbs-configtoml)
- [Compiling songbooks](#compiling-songbooks)
  - [Main document filename conventions](#main-document-filename-conventions)
  - [Output locations](#output-locations)
- [Requirements](#requirements)
  - [Recommended: container build](#recommended-container-build)
  - [Host build (`--no-container`)](#host-build---no-container)
  - [Platform-specific setup examples](#platform-specific-setup-examples)
- [Configuration](#configuration)
- [Writing songbooks](#writing-songbooks)
  - [General structure](#general-structure)
  - [`ulsbs-songbook` document class options](#ulsbs-songbook-document-class-options)
  - [Preamble configuration after loading the class](#preamble-configuration-after-loading-the-class)
  - [Page and line breaks](#page-and-line-breaks)
  - [Repeats](#repeats)
  - [Measure bars](#measure-bars)
  - [Chords and melody blocks inside `\[ ... ]`](#chords-and-melody-blocks-inside---)
  - [Full melodies with Lilypond](#full-melodies-with-lilypond)
  - [Tags](#tags)
  - [Extra variants](#extra-variants)
  - [Creating song selections](#creating-song-selections)
- [Utilities](#utilities)
  - [`ulsbs-bookmeta`](#ulsbs-bookmeta)
  - [`ulsbs-midi2audio`](#ulsbs-midi2audio)
  - [`ulsbs-ly2tex`](#ulsbs-ly2tex)
  - [`ulsbs-migrate-melody-syntax`](#ulsbs-migrate-melody-syntax)
- [Editor support](#editor-support)
- [Testing](#testing)
- [More information](#more-information)
- [License](#license)

---


## Status and compatibility

ULSBS is under active development and its schemas, APIs, and processing rules
may still change between releases. If you use ULSBS outside the main
Unilaiva Songbook repository, you are responsible for reviewing and updating
your songbook sources when upgrading ULSBS.

A stable 1.0 release is planned, after which backward-compatibility guarantees
will follow semantic versioning.

See the [changelog](CHANGELOG.md) for notable changes, breaking migrations, and
release notes.

## Quick start

### Recommended setup: use ULSBS as a git submodule

For a reusable songbook repository, the recommended layout is to vendor ULSBS as
`ulsbs/`.

1. Add the submodule:

```sh
git submodule add https://github.com/unilaiva/ulsbs.git ulsbs
git submodule update --init --recursive
```

2. Copy the example config into your songbook project root:

```sh
cp ulsbs/ulsbs-config-example.toml ulsbs-config.toml
```

3. Create at least one main `.tex` file for your book.

4. Compile from the project root with either of these:

```sh
./ulsbs/ulsbs-compile .
```

or, if you place a copy or symlink of `ulsbs/ulsbs-compile` in the project
root as `ulsbs-compile`:

```sh
./ulsbs-compile
```

The root-level wrapper auto-detects a vendored engine in `./ulsbs`.

### Use ULSBS with an arbitrary local songbook directory

If the engine is checked out somewhere else, you can point it at a separate
project directory:

```sh
/path/to/ulsbs/ulsbs-compile /path/to/my-songbook
```

Alternatively, if your project has a wrapper script in its root, set
`ULSBS_ENGINE`:

```sh
export ULSBS_ENGINE=/path/to/ulsbs
./ulsbs-compile
```

### Use a pip-installed engine

ULSBS can also be installed as a Python package:

```sh
python3 -m pip install /path/to/ulsbs
ulsbs-compile /path/to/my-songbook
```

## Minimal songbook project

A minimal project can look like this:

```text
my-songbook/
├── my-songbook_A5.tex
├── ulsbs-config.toml
├── content/
│   └── songs_main.tex
└── ulsbs/              # optional if using submodule/vendor setup
```

Typical conventions:

- put main songbook documents in the project root
- put song collections in `content/`
- put shared include files or project-specific child classes in `include/`
- keep images under `content/img/` or `include/img/`

These are conventions, not strict technical requirements, except that the main
songbook documents must use a ULSBS songbook class or one derived from it.

### Minimal main document

```tex
\documentclass[
  paper={a5paper},
  maintitle={My Songbook},
  author={Songbook Author},
  subject={Songbook}
]{ulsbs-songbook}

\begin{document}

\ulCoverPage{}
\ulImprintPage
\ulTOC

\ulMainChapter{Main Chapter}{blue}

\begin{songs}{titleidx,authidx,tagidx}
\input{content/songs_main.tex}
\end{songs}

\end{document}
```

And the included song file:

```tex
\beginsong{Example Song}[by={Example Author}, key={C}]
  \beginverse
    |\[C]This is an example |song line.
    Another |\[G7]line of |\[C]lyrics.
  \endverse
\endsong
```

A ready-made template is also available at:

- `vscode-extension/ulsbs-tex-tools/assets/songbook-template_A5.tex`

### Minimal `ulsbs-config.toml`

```toml
songbooks = ["my-songbook_A5.tex"]
```

For a full documented example, copy and edit:

- `ulsbs-config-example.toml`

## Compiling songbooks

From the songbook project root:

- compile everything configured in `ulsbs-config.toml`
  - `./ulsbs-compile`
- compile one document only
  - `./ulsbs-compile my-songbook_A5.tex`
- compile using a profile
  - `./ulsbs-compile --profile dev`
- quick local dev build
  - `./ulsbs-compile --quick my-songbook_A5.tex`
- compile on the host instead of in a container
  - `./ulsbs-compile --no-container`
- open a shell in the build container
  - `./ulsbs-compile --shell`

You can also give a single project directory or a single `ulsbs-config.toml`
path instead of individual `.tex` files.

Run `ulsbs-compile --help` for the full CLI help.

### Main document filename conventions

ULSBS also uses some filename conventions for main songbook documents:

- `_NODEPLOY`
  - if the main document filename contains `_NODEPLOY`, its outputs are never
    deployed, meaning they are not copied to the deploy directory even if
    deployment is otherwise enabled
- `_A5`
  - if the main document filename contains `_A5`, ULSBS will by default create
    extra home-printing printouts for fitting two A5 pages on A4 paper, when
    printouts are enabled and the required tools are available

For `_A5` books, the two main printout styles are:

- `EASY`
  - an A4 layout that places one A5 spread side by side in a simple format
- `BOOKLET`
  - an A4 layout intended for booklet-style home printing and cutting

For these `_A5` printouts to behave as expected, the document itself should use:

- `paper={a5paper}`

Example:

```tex
\documentclass[
  paper={a5paper},
  maintitle={My Songbook}
]{ulsbs-songbook}
```

### Output locations

By default, compilation writes generated files under:

- `result/`

Depending on configuration and available tools, ULSBS can also produce:

- lyrics-only variants
- extra instrument variants
- printout PDFs
- JSON exports
- MIDI files
- MP3 audio files
- cover PNGs

If deployment is enabled, files are also copied under `deploy/`.

## Requirements

### Recommended: container build

By default ULSBS compiles inside a container.

Supported container engines:

- Docker
- Podman

General requirements for container mode:

- `bash` 3.0+
- `python3` 3.11+
- Docker or Podman
- enough disk space for the image (roughly 2.5 GiB)

Container mode is recommended because it avoids host toolchain mismatches.

Notes:

- the first build is much slower because the image must be built
- by default ULSBS may run several compilations in parallel
- on low-memory systems, use `--sequential`

### Host build (`--no-container`)

Host mode is available, but your system toolchain must match what ULSBS
expects.

Important host dependencies include:

- a recent LaTeX distribution with `lualatex` and `texlua`
- Lilypond with `lilypond-book`
- `bash`
- `python3` 3.11+
- Noto fonts (`Noto Sans`, `Noto Serif`, with needed weights)
- locale `fi_FI.utf8`

Optional but useful dependencies:

- `context` or `contextjit` for printout PDFs
- `ffmpeg` and `fluidsynth` for MP3 generation
- `pdftoppm` and ImageMagick `magick` for cover PNG extraction

Most LaTeX package dependencies are pulled in by the style files themselves.
ULSBS also vendors a specific compatible copy of the `songs` LaTeX package.

### Platform-specific setup examples

The examples below create a minimal reusable songbook project using the bundled
A5 template. They assume the recommended submodule-based setup.

#### Ubuntu or Debian with Docker

```sh
sudo apt update
sudo apt install docker.io git python3
sudo usermod -aG docker "$USER"
newgrp docker

mkdir -p ~/src/my-songbook
cd ~/src/my-songbook
git init
git submodule add https://github.com/unilaiva/ulsbs.git ulsbs
printf 'songbooks = ["my-songbook_A5.tex"]\n' > ulsbs-config.toml
cp ulsbs/vscode-extension/ulsbs-tex-tools/assets/songbook-template_A5.tex my-songbook_A5.tex
./ulsbs/ulsbs-compile .
```

If you prefer Podman, install `podman` instead of `docker.io`.

#### macOS with Docker Desktop

Install first:

1. Docker Desktop: <https://docs.docker.com/desktop/setup/install/mac-install/>
2. Python 3.11+: <https://www.python.org/downloads/macos/>
3. If `git` is missing, Xcode Command Line Tools:

```sh
xcode-select --install
```

Then create and build a minimal project:

```sh
mkdir -p ~/src/my-songbook
cd ~/src/my-songbook
git init
git submodule add https://github.com/unilaiva/ulsbs.git ulsbs
printf 'songbooks = ["my-songbook_A5.tex"]\n' > ulsbs-config.toml
cp ulsbs/vscode-extension/ulsbs-tex-tools/assets/songbook-template_A5.tex my-songbook_A5.tex
./ulsbs/ulsbs-compile .
```

Start Docker Desktop once before the first build.

#### Windows with WSL2 and Docker Desktop

Use Ubuntu inside WSL2, and keep the project inside the Linux home directory.

1. In PowerShell:

```sh
wsl --install -d Ubuntu
```

2. Install Docker Desktop for Windows and enable WSL integration for Ubuntu:
   <https://docs.docker.com/desktop/setup/install/windows-install/>
3. In the Ubuntu shell:

```sh
sudo apt update
sudo apt install git python3

mkdir -p ~/src/my-songbook
cd ~/src/my-songbook
git init
git submodule add https://github.com/unilaiva/ulsbs.git ulsbs
printf 'songbooks = ["my-songbook_A5.tex"]\n' > ulsbs-config.toml
cp ulsbs/vscode-extension/ulsbs-tex-tools/assets/songbook-template_A5.tex my-songbook_A5.tex
./ulsbs/ulsbs-compile .
```

If the `docker` command is not available inside WSL, start Docker Desktop and
verify that WSL integration is enabled for your Ubuntu distro.

#### Ubuntu 24.04 host build (`--no-container`)

If you specifically want host mode, Ubuntu 24.04 is a known-good reference
setup:

```sh
sudo apt update
sudo apt install bash locales git python3 context context-modules ffmpeg fluidsynth fluid-soundfont-gm fonts-noto-core fonts-noto-extra fonts-noto-mono imagemagick lilypond poppler-utils texlive texlive-font-utils texlive-lang-arabic texlive-lang-english texlive-lang-european texlive-lang-portuguese texlive-lang-spanish texlive-latex-base texlive-latex-extra texlive-luatex texlive-music texlive-plain-generic
sudo locale-gen fi_FI.utf8
sudo mtxrun --generate

mkdir -p ~/src/my-songbook
cd ~/src/my-songbook
git init
git submodule add https://github.com/unilaiva/ulsbs.git ulsbs
printf 'songbooks = ["my-songbook_A5.tex"]\n' > ulsbs-config.toml
cp ulsbs/vscode-extension/ulsbs-tex-tools/assets/songbook-template_A5.tex my-songbook_A5.tex
./ulsbs/ulsbs-compile --no-container .
```

Most LaTeX package dependencies are standard TeX Live packages, and some of the
Ubuntu packages above may already be installed on your system.

## Configuration

ULSBS reads configuration from `ulsbs-config.toml` in the songbook project
root.

Recommended workflow:

1. copy `ulsbs-config-example.toml` into your project root
2. set `songbooks = [...]`
3. optionally add profiles under `[profiles.<name>]`

Useful configuration features:

- `songbooks`
  - main documents to compile
- `deploy`, `deploy-dir`
  - deployment behavior
- `create-printouts`, `coverimage`, `json`, `midifiles`, `audiofiles`
  - enable or disable extra outputs
- `common-deploy-icons`, `common-deploy-social-images`, `common-deploy-metadata`, `common-deploy-other`
  - extra files to copy during deploy
- profile inheritance with `inherit-from`
- array merging with `merge-keys`

Precedence is, from lowest to highest:

- built-ins
- flat config
- profile config
- environment variables
- CLI flags

Some useful environment variables:

- `ULSBS_ENGINE`
  - explicit path to the engine checkout
- `ULSBS_CONTAINER_ENGINE`
  - `auto`, `docker`, or `podman`
- `ULSBS_MAX_PARALLEL`
  - Sets the maximum number of parallel compile jobs, overriding ULSBS's
    automatic job-count heuristics. If you raise this, also make sure
    `ULSBS_MAX_CONTAINER_MEM_GB` is high enough for the extra jobs. A good
    rule of thumb is roughly 1–2 GiB of memory per job.
- `ULSBS_MAX_CONTAINER_MEM_GB`
  - Sets the container's memory limit in GiB, overriding ULSBS's automatic
    memory-limit heuristics. Set this high enough for your chosen parallelism.
    If set to `0`, no memory limit is applied.
- `ULSBS_USE_SYSTEM_TMP_FOR_TEMP`
  - If set to `true`, ULSBS uses a temporary directory under the system `/tmp`
    for intermediate build files. This can help if `/tmp` is backed by `tmpfs`
    and you have enough RAM, because it may reduce disk I/O during builds.
    On low-memory systems, however, this may make memory pressure worse.

## Writing songbooks

ULSBS is based on LaTeX, Lilypond, and especially the `songs` LaTeX package by
Kevin W. Hamlen. The `songs` package is a key part of ULSBS, not just a minor
helper dependency: ULSBS builds on top of it extensively, extends it, and
redefines parts of its behavior for songbook-oriented output, metadata,
indexing, variants, and workflow automation.

If you are new to the underlying `songs` package, it is very much worth reading
its documentation too:

- bundled PDF: `misc/ext_package_songs_distribution/songs.pdf`
- online: <https://songs.sourceforge.net/songsdoc/songs.html>

### General structure

The main document must use `\documentclass{ulsbs-songbook}` or a project-
specific child class derived from it.

For automatic detection by the compiler, the class name should start with
`ulsbs-songbook`.

Within `\begin{document}` ... `\end{document}`, books are typically structured
with `\ulMainChapter`, and songs live inside a `songs` environment.

Each song starts with `\beginsong` and ends with `\endsong`.

Files named `songs_*.tex` under `content/` are a good convention for song
collections, but not a requirement.

### `ulsbs-songbook` document class options

The base ULSBS class is:

- `ulsbs-songbook`

Its key=value options are:

- `paper={...}`
  - paper size passed on to the ULSBS layout machinery, for example
    `paper={a5paper}` or `paper={a4paper}`
- `maintitle={...}`
  - main book title
- `subtitle={...}`
  - subtitle / sub-book title
- `subsubtitle={...}`
  - secondary subtitle
- `motto={...}`
  - imprint-page motto text
- `wwwlink={...}`
  - website link shown on the imprint page
- `wwwqr={...}`
  - QR image filename for the website
- `imprintnote={...}`
  - imprint-page footnote text
- `author={...}`
  - PDF metadata author and default compiled-by text source
- `subject={...}`
  - PDF metadata subject
- `keywords={...}`
  - PDF metadata keywords
- `language={...}`
  - preliminary main language, default `english`
- `bindingoffset={...}`
  - binding offset passed to page geometry, default `8mm`

Supported standard class options forwarded to the underlying `book` class are:

- `10pt`, `11pt`, `12pt`
- `openright`, `openany`
- `oneside`, `twoside`
- `draft`, `final`
- `titlepage`, `notitlepage`
- `onecolumn`, `twocolumn`
- `fleqn`, `leqno`

Important note about paper size options:

- use `paper={a5paper}` or similar
- do **not** rely on bare class options like `a5paper` or `a4paper` with
  `ulsbs-songbook`; those are intentionally swallowed by the class, and the ULSBS
  `paper={...}` option is the one that controls the layout

### Preamble configuration after loading the class

After `\documentclass{ulsbs-songbook}` has loaded ULSBS, many document-wide
features can be configured in the preamble.

The most important switches are boolean toggles created with `\newif`. They are
used like this:

- `\showtagstrue`
- `\showtagsfalse`

Available toggle pairs are below. The default state from `ulsbs.sty` is shown
for each one.

| Toggle pair | Default | Meaning |
|---|---:|---|
| `\showextrue` / `\showexfalse` | `true` | show extra song prelude info (`ex=`) |
| `\showofftrue` / `\showofffalse` | `true` | show offered-to info (`off=`) |
| `\showkeytrue` / `\showkeyfalse` | `true` | show the main musical key in song preludes |
| `\showgoodkeystrue` / `\showgoodkeysfalse` | `true` | show good singing keys in song preludes |
| `\showphtrue` / `\showphfalse` | `true` | show song phases in preludes |
| `\showphintoctrue` / `\showphintocfalse` | `true` | show phases also in the TOC |
| `\showtagstrue` / `\showtagsfalse` | `true` | show tags in preludes / tag index usage |
| `\shownotestrue` / `\shownotesfalse` | `true` | show melody note hints |
| `\showbeatstrue` / `\showbeatsfalse` | `true` | show beat marks |
| `\showauthtrue` / `\showauthfalse` | `true` | show song authors in preludes |
| `\showlilypondtrue` / `\showlilypondfalse` | `true` | show Lilypond music-score blocks |
| `\showpassagetrue` / `\showpassagefalse` | `true` | show `passage` environments |
| `\showexplanationtrue` / `\showexplanationfalse` | `true` | show `explanation` environments |
| `\showtranslationtrue` / `\showtranslationfalse` | `true` | show `translation` environments |
| `\showfeelertrue` / `\showfeelerfalse` | `true` | show `feeler` environments |
| `\showaltchordstrue` / `\showaltchordsfalse` | `true` | show alternate chord sets |
| `\showimageinchapternametrue` / `\showimageinchapternamefalse` | `true` | include chapter symbol/image in TOC and headers |
| `\showimageonchapterfrontpagetrue` / `\showimageonchapterfrontpagefalse` | `true` | show chapter image/symbol on chapter front pages |
| `\upcaselongchaptertitletrue` / `\upcaselongchaptertitlefalse` | `false` | uppercase long chapter titles on chapter front pages |
| `\upcaseshortchaptertitletrue` / `\upcaseshortchaptertitlefalse` | `true` | uppercase short chapter titles in TOC and headers |
| `\upcasesectiontitleinheadertrue` / `\upcasesectiontitleinheaderfalse` | `false` | uppercase section titles in headers |
| `\upcasebooktitleinheadertrue` / `\upcasebooktitleinheaderfalse` | `true` | uppercase the book title in headers |
| `\usechaptercolorstrue` / `\usechaptercolorsfalse` | `true` | enable colored chapter corner marks |
| `\adjustchordcharstrue` / `\adjustchordcharsfalse` | `true` | apply chord-character adjustments such as smaller raised parentheses |

Other useful preamble settings include:

- `\verseindentwidthbase`
  - base width used by `\beginverse[<n>]` indentation
- `\renewcommand{\ulSongEndMark}{...}`
  - mark shown at the right end of the song-ending line
- `\renewcommand{\ulLyricFont}{...}`
  - default lyric font
- `\renewcommand{\ulChordFont}{...}`
  - default chord font
- `\renewcommand{\ulChordWhitespaceMinimumWidth}{...}`
  - minimum advance for a visible chord-line annotation followed by source whitespace; default `.8ex` in the lyric font, or `0pt` to disable
- `\renewcommand{\translationfont}{...}`
  - translation block font
- `\renewcommand{\explanationfont}{...}`
  - explanation block font
- `\renewcommand{\passagefont}{...}` / `\renewcommand{\altpassagefont}{...}`
  - passage fonts
- `\renewcommand{\mnsymbolstyle}{...}`
  - melody-note symbol style
- `\renewcommand{\mntagtext}{...}` / `\renewcommand{\mnalttagtext}{...}`
  - melody-note tag text
- `\renewcommand{\headertitlestyle}{...}`
  - header title style
- `\renewcommand{\pagenumberstyle}{...}`
  - page-number style in headers

There are many more rewritable settings in `src/ulsbs/assets/tex/ulsbs.sty`,
but the toggle list above is the most important document-level configuration
surface.

### Page and line breaks

The `songs` package already does most line and page breaking well, but sometimes
it needs help.

Use `\brk` in a lyric line to suggest a line break point.

`\brk` can also be used between verses and songs to suggest a page or column
break.

To force breaks between songs:

- `\sclearpage`
  - jump to the next page
- `\scleardpage`
  - jump to the next spread / even page

In some situations `\brk`, `\hardbrk`, or `\forcebrk` are needed right before
long songs so the previous song ends cleanly.

### Repeats

ULSBS supports two main repeat styles.

Inline repeat marks:

- `\lrep`
- `\rrep`
- `\rep{<n>}` (meant to put after \rrep to signify the repeat count)

Block repeat bars on the left side of lyric lines:

```tex
\beginsong{My Song}
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

Useful related macros:

- `\prep{<n>}`
  - put the repeat count on its own line after `\beginrep`
- `\goto{Beginning words of the verse}`
  - mark a jump target by text

`\beginchorus` / `\endchorus` from the original `songs` package are not used in
ULSBS for repeat markup.

### Measure bars

Use the pipe character `|` to mark the **beginning** of each measure, never the
end.

If a line ends on a measure with no lyrics at that spot, use `\e` to mark that
there really is a measure there.

So the rule of thumb is:

- one bar line per bar

To hide measure bars in the final document, use `\measuresoff`.

### Chords and melody blocks inside `\[ ... ]`

Write chords inline with lyrics, for example `\[C]`, `\[Am]`, or `\[G7]`; the
chord is placed above the following lyric text. Add melody hints and beat marks
in one leading melody block:

Use `\ac{<repetition>}{<chord>}` for an alternate chord associated with a
numbered repetition. For example, `\[\ac{1}{Em} \ac{2}{E}]` prints two
alternatives with superscript repetition numbers. Balanced brace arguments are
required; the former `\ac<1>{Em}` syntax is removed because its angle brackets
conflict with melody blocks.

```tex
\[<[!]primary[;secondary][ @offset]>chord]lyric
\[^<[!]primary[;secondary][ @offset]>chord]lyric
```

The block must begin immediately after `\[` or after its one optional leading
`^`. `\[<C>Am]Love`, `\[<C D E>F]move`, and `\[<C;E>Am]two voices` overlay
their melody content and chord at one anchor. The chord is optional, so
`\[<C>]Love` is a melody-only annotation.

#### Sequences and offsets

The first sequence is primary. It may be empty for a secondary-only block; use
`;` before the optional secondary sequence. Pitches are uppercase and may use
`#` or `&` accidentals. Tokens are:

| Token | Meaning |
|---|---|
| `C`, `D#`, `B&` | one transposition-aware pitched slot |
| `_` | one empty slot with normal slot advance |
| `*` | beat mark attached at the current sequence position; no slot advance of its own |
| `/` | circled, unpitched one-slot marker |

Whitespace is optional between tokens and around `;` and `@`, so
`\[<*A_/C;EF_G>Am]` equals `\[<* A _ / C;E F _ G>Am]`. Use `@` with a TeX
dimension to offset the complete block, for example `\[<CD@-.25em>Am]`.
Relative units such as `em` and `ex` are evaluated in the lyric font.

An optional leading `!` makes the melody block zero-advance. Its notes and beats
still render, but the melody contributes no width and the whitespace minimum is
disabled for that annotation. A chord in the same annotation keeps its natural
width:

```tex
\[<!C>]          % visible note, zero advance
\[<!*>]          % visible beat, zero advance
\[<!C@1em>Am]    % shifted zero-advance melody; Am keeps its width
```

#### Replay, advance, and whitespace

The leading `^` retains its `songs` replay meaning. `\[^<C>Am]` is excluded
from chord memorization; a bare `^` in lyric text later replays the next saved
annotation, including its chord, melody, and beats. Note and beat visibility is
evaluated at replay time.

Layers in one annotation overlay. Its advance is the widest rendered layer: a
chord can determine it, and a melody-only block reserves its own width. Negative
offsets can draw left of the anchor without reducing normal advance; positive
offsets reserve their added extent. Consecutive annotations remain sequential:
`\[Am]\[<*>]` puts the beat after the chord, whereas `\[<*>Am]` overlays them.
Only one melody block is accepted per annotation. Use adjacent annotations for
multiple blocks; a zero-advance first block shares the next block's anchor:
`\[<!A>]\[<B>Am]`.

When a visible chord-line annotation or replay is followed by literal source
whitespace, it advances by at least `\ulChordWhitespaceMinimumWidth` (default
`.8ex` in the lyric font). Wider annotations are unchanged; hidden chords,
notes, and beats do not trigger the minimum. Set it to `0pt` to disable this.

#### Placement, style, and visibility

Primary and secondary are semantic roles. Scoped
`\melodyPrimaryPosition{normal}` or `low` selects the primary lane (default:
`normal`); `\melodySecondaryPosition{above}`, `below`, or `same` selects the
secondary lane relative to it (default: `above`). `same` is the primary lane.
With a low primary, `above` is the normal lane and `below` may overlap lyrics.

Set styles independently with `\melodyStyleMapping{normal}` (primary uses the
normal style) or `\melodyStyleMapping{swapped}` (primary uses the alternate
style). Neither setting changes which sequence is primary.

`\shownotesfalse` and `\notesoff` hide melody notes; `\showbeatsfalse` and
`\beatsoff` hide beats. `\noteson` and `\beatson` restore them. Use
`\mnbeginverse` for looser spacing when a verse has melody hints throughout;
ordinary `\beginverse` is suitable when they occur only on its first line.

Legacy `\mn*`, `\ma*`, `\bm*`, and `\usealtmnstyle...` authoring commands are
removed. Do not use them in new sources.

### Full melodies with Lilypond

Full melodies are written in Lilypond syntax and wrapped inside `lilywrap`
environments inside a song, but outside verses.

This allows ULSBS to generate sheet music and MIDI output.

If you use ULSBS-specific Lilypond lyric helpers such as `theLyricsOne`, the
`ulsbs-ly2tex` helper can help convert lyrics into the songbook text format.

#### Converting lyrics from Lilypond to songbook format

When converting Lilypond lyrics manually, these replacements are often useful,
in this order:

1. ` -- | ` -> `|`
2. ` -- _ ` -> ``
3. ` -- ` -> ``
4. ` | ` -> ` |`
5. ` __` -> ``
6. ` _` -> ``
7. `__ ` -> ``
8. `|_` -> `|`
9. `\skip 1 ` -> ``
10. `"" ` -> ``
11. `~` -> `\jw `
12. `\altcol ` -> ``

Be careful with whitespace.

### Tags

Tags are attached with the `tags=` key in `\beginsong`:

```tex
\beginsong{Song name}[tags={love, smile}]
```

In the Unilaiva repository, allowed tags are listed in `include/tags.can`.
In your own repository, you can use your own tag list and indexing setup.

To disable tag display entirely, set `\showtagsfalse` in the main document.

### Extra variants

ULSBS can build optional extra instrument variants for a main document.

Those are enabled by a special comment in the main `.tex` file, for example:

```tex
%% ULSBS-EXTRA-VARIANTS: bassclef, charango
```

The exact post-setup files for such variants live under:

- `src/ulsbs/assets/tex/`

### Creating song selections

A selection booklet can be made by creating another main document that includes
only chosen songs with `\includeonlysongs{...}` before the main inputs.

In the Unilaiva repository, a concrete example exists at:

- `../include/ul-selection_example.tex`

## Utilities

ULSBS ships with a few helper tools in addition to the main compiler.

### `ulsbs-bookmeta`

Extract songbook data as JSON.

Typical use:

```sh
./ulsbs-bookmeta my-songbook_A5.tex > songbook.json
```

### `ulsbs-midi2audio`

Convert MIDI files to audio using `ffmpeg` and `fluidsynth`.

### `ulsbs-ly2tex`

Helper for converting ULSBS-style Lilypond lyric output into songbook text.

### `ulsbs-migrate-melody-syntax`

Migrate legacy `\mn*`, `\ma*`, beat-mark, and `\ac<n>{Chord}` syntax to the
new melody-block and `\ac{n}{Chord}` forms. Run it against a `.tex` file or a
directory tree:

```sh
ulsbs-migrate-melody-syntax --check content/
ulsbs-migrate-melody-syntax --diff content/songs.tex
ulsbs-migrate-melody-syntax --write content/
```

`--check` never writes and exits nonzero while legacy syntax remains. `--diff`
and `--write` are file-atomic: they process only files with no diagnostics,
although `--write` may still change other safe files in a directory. `--diff`
prints only safe conversions. Comments and verbatim-like regions are ignored.
The tool reports
malformed arguments, compound pitches, incompatible offsets, ambiguous secondary
placement, and low `\mnd`/`\mad` forms. Use `--normalize-low` only after review;
it normalizes those slots but never changes verse environments. The migrator does
not infer missing secondary-note slots. Baseline alternate-only `\ma`/`\mac`
forms become secondary notes under `\melodySecondaryPosition{same}`. A uniform
verse receives one scoped setting; mixed placement receives a local TeX group.

The melody-block grammar also accepts `/` as a rendered, one-slot unpitched
marker. This preserves the legacy circled `/` marker; it is deliberately not
converted to `_`, which is an empty slot. Legacy commands are migrated only from
the leading melody/beat layer. A leading replay caret is preserved before the
generated block, for example `\[^\mnc{C}]` becomes `\[^<C>]`. Alternate chords
remain after it while their selector syntax is converted, for example
`\ac<1>{Em}` becomes `\ac{1}{Em}`. A legacy melody command after chord content
is reported instead of being hoisted across that content.

## Editor support

The bundled VS Code extension lives in:

- `vscode-extension/ulsbs-tex-tools/`

It adds ULSBS-aware snippets, folding, navigation, structural outline support,
and syntax help for songbook files.

Installation instructions are in:

- `vscode-extension/ulsbs-tex-tools/README.md`

## Testing

Run the complete test suite from the ULSBS source directory with:

```sh
./ulsbs-test
```

Tests use the same Docker or Podman `ulsbs-compiler` image as normal songbook
compilation. The command builds the image when necessary, runs LuaLaTeX
regression tests through `l3build`, and runs compilation/PDF-structure tests
through Python's standard-library `unittest` runner.

Useful options:

```sh
./ulsbs-test --container-rebuild
./ulsbs-test --container-engine podman
./ulsbs-test --no-container
./ulsbs-test --verbose
```

Host testing is intended for development only; the containerized suite is the
canonical result because it uses the supported ULSBS toolchain and fonts.

## More information

The most important source files to inspect when extending or debugging ULSBS
are:

- `src/ulsbs/assets/tex/ulsbs-songbook.cls`
- `src/ulsbs/assets/tex/ulsbs.sty`
- `src/ulsbs/cli.py`
- `src/ulsbs/pipeline.py`
- `ulsbs-config-example.toml`

The main wrapper scripts are:

- `ulsbs-compile`
- `ulsbs-bookmeta`
- `ulsbs-midi2audio`
- `ulsbs-ly2tex`
- `ulsbs-test`

Release steps for the repository maintainer are documented in
[`MAINTAINERS.md`](MAINTAINERS.md).


## License

GNU General Public License version 3 or later (GPL 3.0+)

Documents generated using ULSBS are not considered derivative works of the
ULSBS code.
