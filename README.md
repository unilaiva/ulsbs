# ULSBS

ULSBS (**Unilaiva Songbook System**) turns LaTeX song sources, with optional
LilyPond scores, into printable PDF songbooks. Write your songs once, organize
them into books or smaller selections, and generate different variants from the
same sources.

- Place **chords above lyrics**, with **measure bars** and repeat markings.
- Add compact melody-note hints and beat marks, or full LilyPond music notation.
- Transpose chords and melody hints with key-aware accidental spelling.
- Organize books with chapters, tables of contents, and title and tag indices.
- Generate lyrics-only and supported instrument variants, plus A5 home-printing layouts.
- Optionally create multikey editions with independently selectable keys for each
  song in compatible PDF viewers or websites.
- Export song metadata as JSON and generate MIDI and MP3 files from LilyPond scores.
- Edit plain-text sources with your preferred editor; a bundled VS Code extension
  provides ULSBS-aware snippets and navigation.

ULSBS is a text-based toolchain, not a visual score editor. Basic LaTeX familiarity
is useful; LilyPond knowledge is only needed when writing full scores. Docker or
Podman supplies the recommended build environment, including the music and
typesetting tools. Lyrics-and-chords books do not need full scores.

See a real example: the [published Unilaiva Songbook](https://unilaiva.aavalla.net)
and its [source repository](https://github.com/unilaiva/unilaiva-songbook).
ULSBS can also be used with your own independent repository or local directory.

**Start here:** follow [Quick start](#quick-start) to build your first book, then
use [Writing Songbooks](WRITING_SONGBOOKS.md) for song syntax and customization.

## Contents

- [Contents](#contents)
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
- [Variants and editions](#variants-and-editions)
  - [Default variant](#default-variant)
  - [Lyrics-only variant](#lyrics-only-variant)
  - [Instrument variants](#instrument-variants)
  - [Media exports](#media-exports)
  - [Multikey PDF editions](#multikey-pdf-editions)
- [Requirements](#requirements)
  - [Recommended: container build](#recommended-container-build)
  - [Host build (`--no-container`)](#host-build---no-container)
  - [Platform-specific setup examples](#platform-specific-setup-examples)
- [Configuration](#configuration)
- [Writing songbooks](#writing-songbooks)
- [Utilities](#utilities)
  - [`ulsbs-bookmeta`](#ulsbs-bookmeta)
  - [`ulsbs-midi2audio`](#ulsbs-midi2audio)
  - [`ulsbs-ly2tex`](#ulsbs-ly2tex)
  - [`ulsbs-migrate-syntax-v1`](#ulsbs-migrate-syntax-v1)
- [Editor support](#editor-support)
- [Troubleshooting](#troubleshooting)
- [Contact](#contact)
- [Developer documentation](#developer-documentation)
- [Acknowledgements](#acknowledgements)
- [License](#license)

## Status and compatibility

ULSBS is under active development. When upgrading, review the
[changelog](CHANGELOG.md) for release notes and changes that may require updates
to your song sources or configuration. A stable 1.0 release is planned, after
which backward-compatibility guarantees will follow semantic versioning.

## Quick start

### Recommended setup: use ULSBS as a git submodule

First install Git, Python 3.11+, and Docker or Podman; see
[platform-specific setup](#platform-specific-setup-examples) if needed. Start
Docker Desktop first if using it.

1. Create a project and add ULSBS. For an existing Git repository, run only the
   `git submodule` commands from its root.

```sh
mkdir my-songbook
cd my-songbook
git init
git submodule add https://github.com/unilaiva/ulsbs.git ulsbs
git submodule update --init --recursive
```

2. Copy the self-contained example book:

```sh
cp ulsbs/vscode-extension/ulsbs-tex-tools/assets/songbook-template_A5.tex my-songbook_A5.tex
```

3. Create `ulsbs-config.toml` in the project root:

```toml
songbooks = ["my-songbook_A5.tex"]
```

4. Compile from the project root:

```sh
./ulsbs/ulsbs-compile --quick my-songbook_A5.tex
```

The first run builds the compiler image and can take considerably longer than
later runs. Open `result/my-songbook_A5.pdf`. The `--quick` option builds only
the default variant's ordinary PDF, disables extra outputs and deployment, and
keeps temporary files. Run `./ulsbs/ulsbs-compile` without it for the normal
configured outputs.

The [minimal project below](#minimal-songbook-project) shows how to separate
songs from the main document. Continue with [Writing Songbooks](WRITING_SONGBOOKS.md)
to add songs, notation, chapters, and indices.

All compiler examples here use `./ulsbs/ulsbs-compile` from your project root.
Optionally create a root-level shortcut:

```sh
ln -s ulsbs/ulsbs-compile ulsbs-compile
```

You can then use `./ulsbs-compile` instead. The wrapper detects the engine in
`./ulsbs`; copying the wrapper into the project root also works.

### Use ULSBS with an arbitrary local songbook directory

If the engine is checked out elsewhere, point it at your project directory:

```sh
/path/to/ulsbs/ulsbs-compile /path/to/my-songbook
```

If your project has a copy of the wrapper, you can explicitly select the engine:

```sh
export ULSBS_ENGINE=/path/to/ulsbs
./ulsbs-compile
```

### Use a pip-installed engine

ULSBS can also be installed from a checkout into a Python virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install /path/to/ulsbs
ulsbs-compile /path/to/my-songbook
```

For this setup, replace `./ulsbs/ulsbs-compile` in the examples with
`ulsbs-compile`. Installation supplies the Python package and engine assets;
you still need Docker/Podman or the [host toolchain](#host-build---no-container).

## Minimal songbook project

For a book that keeps its songs in a separate file, use this layout:

```text
my-songbook/
  my-songbook_A5.tex
  ulsbs-config.toml
  content/
    songs_main.tex
  ulsbs/                 # engine, if using the submodule setup
```

Main documents normally live in the project root, song collections in `content/`,
shared includes or child classes in `include/`, and images in `content/img/` or
`include/img/`. These are conventions, not mandatory directory names.

### Minimal main document

Put this in `my-songbook_A5.tex`:

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

Put the song in `content/songs_main.tex`:

```tex
\beginsong{Example Song}[id={example-song},by={Example Author},key={C}]
  \beginverse
    |\[C]This is an example |song line.
    Another |\[G7]line of |\[C]lyrics.
  \endverse
\endsong
```

Here `\[C]` places a chord above the following lyrics, and `|` marks the
beginning of a measure. Songs must be inside a `songs` environment. The cover,
imprint, and table of contents are optional.

### Minimal `ulsbs-config.toml`

The only setting needed to select this book is:

```toml
songbooks = ["my-songbook_A5.tex"]
```

Other settings retain their defaults. Normal builds enable lyrics-only variants,
printouts, JSON, cover images, MIDI/audio where available, and deployment to
`deploy/`. Multikey editions are off by default.

For a normal build with only the main PDF, use:

```toml
songbooks = ["my-songbook_A5.tex"]
lyricbooks = false
extrainstrumentbooks = false
create-printouts = false
coverimage = false
json = false
midifiles = false
audiofiles = false
deploy = false
```

Use [`ulsbs-config-example.toml`](ulsbs-config-example.toml) as the full annotated
reference. You may copy it instead, but must set its `songbooks` list and review
which outputs you want.

## Compiling songbooks

Run these commands from your songbook project root:

| Task | Command |
|---|---|
| Build the configured books | `./ulsbs/ulsbs-compile` |
| Build one document | `./ulsbs/ulsbs-compile my-songbook_A5.tex` |
| Use a configured profile | `./ulsbs/ulsbs-compile --profile dev` |
| Quick main-PDF build | `./ulsbs/ulsbs-compile --quick my-songbook_A5.tex` |
| Omit multikey companions | `./ulsbs/ulsbs-compile --no-multikey my-songbook_A5.tex` |
| Compile on the host | `./ulsbs/ulsbs-compile --no-container` |
| Open a compiler-container shell | `./ulsbs/ulsbs-compile --shell` |
| Limit memory pressure | `./ulsbs/ulsbs-compile --sequential` |

You can also supply a single project directory or a single existing
`ulsbs-config.toml` path instead of individual `.tex` files. Explicit `.tex`
arguments override the configured book selection. Run
`./ulsbs/ulsbs-compile --help` for all flags.

### Main document filename conventions

- `_NODEPLOY`: outputs from a main document containing this marker are never deployed.
- `_A5`: enables the usual A5-on-A4 printouts when printouts and their tools are available.

The filename does not set the paper size. For A5, use
`\documentclass[paper={a5paper},maintitle={My Songbook}]{ulsbs-songbook}`.
For another size, change `paper={...}` and remove `_A5` from the filename.

The `EASY` printout puts an A5 spread side by side on A4. The `BOOKLET` printout
is arranged for double-sided A4 printing and cutting. Use the generated printout
at its intended paper size without an additional fit-to-page transformation.

### Output locations

Compiled files go into `result/`. Ordinary PDFs are at its root; extra outputs
use subdirectories such as `printouts/`, `json/`, and `multikey/`.
MIDI/MP3 output requires music notation that generates MIDI; chord-and-lyric text
alone does not generate accompaniment or recordings.

Deployment is a local copy of selected build outputs and configured extra files
to `deploy/` by default, not an upload to a web server. Disable it with
`deploy = false` or `--no-deploy`. An explicitly configured `deploy-dir` or
`--deploy-dir` must already exist on the host.

ULSBS automatically reduces PDF size by sharing identical embedded font data,
including in quick builds, while preserving appearance and multikey controls.

### Warnings and partial builds

Each job is one book, variant, and ordinary or multikey edition. Successful jobs
remain `SUCCESS` even with warnings. Their completion block prints a compact
warning breakdown and `SEE` paths before `SUCCESS ... with N warnings` and the
output path. Related lines print together, without interleaving other jobs.
Use `--verbose` for individual diagnostics and detailed score-fallback information.

Warning counts represent diagnostic records, not lines, logs, or occurrences of
the word "warning". Multiline warnings count once; repeated records display
together with their occurrence count, and closing TeX recaps are not counted
again when their specific warnings are available. Native aggregate warnings
retain an affected-item count, such as eight songs missing IDs. Only the **last
LuaLaTeX invocation** contributes displayed or counted warnings, including after
convergence reruns; intermediate rerun requests are progress, not final warnings.
Missing glyphs and overfull boxes are warnings; underfull boxes are informational.
Configuration, resource, and cleanup advisories are separate from job counts.
Unfamiliar messages with recognized warning headers are still counted, without
requiring a message whitelist. Those without a specialized category appear as
`unclassified warnings`; `--verbose` shows their messages, and `SEE` links their
logs. Entirely unfamiliar warning header formats may require parser support.

The final summary identifies warned jobs, failures, blocked companions, and
intentionally skipped outputs. Per-job JSON diagnostic reports remain under
`result/diagnostics/`, even when temporary files are cleaned. Full raw tool logs
require `--keep-temp`; warning-bearing logs are linked as jobs finish so they can
be inspected while other jobs continue.

A failed job does not abort independent jobs. A multikey companion whose ordinary
edition failed is blocked from publication. Any failure or dependency block
prevents automatic deployment and gives the command a nonzero exit status;
warnings alone do not block deployment. Partial files may remain in `result/`
for inspection, but only finally successful jobs enter the deployable result list.

To explicitly deploy successful jobs from an incomplete run, use:

```sh
./ulsbs/ulsbs-compile --deploy-last
```

This selects the newest retained run inventory, reports partial deployment, and
does not deploy artifacts from failed or blocked jobs. Obsolete inventories are
retired rather than replayed against newer files. The result directory itself is
not an all-or-nothing snapshot and can still contain older or partial files.

## Variants and editions

A **variant** is a version of a source book: default, lyrics-only, or an
instrument-specific version. They are peers, generated from the same source.
An **edition** determines how that variant is published: an ordinary PDF or an
optional multikey package with reader-selectable keys.

| Variant | Ordinary edition | Multikey edition |
|---|---|---|
| Default | Always generated for a selected source | Available when enabled |
| Lyrics-only | Enabled by default | Not currently generated |
| Instrument (charango or bass clef) | Generated when selected and enabled | Available when enabled |

The edition axis is separate from the variant, but the compiler currently
generates multikey editions only for default and instrument variants.
Lyrics-only variants currently have ordinary editions only.

### Default variant

Every selected source produces its default variant's ordinary PDF. Other
variants and multikey editions are additional outputs; they do not replace it.
`--quick` builds only the default variant's ordinary edition.

### Lyrics-only variant

Normal builds enable an additional lyrics-only variant. Use `lyricbooks = false`
or `--no-lyric` to omit it. This reuses the same song sources; no separate copy
of each song is needed.

### Instrument variants

Enable supported instrument variants with a comment in the main `.tex` file:

```tex
%% ULSBS-EXTRA-VARIANTS: bassclef, charango
```

Use `extrainstrumentbooks = false` or `--no-extrainstr` to omit them. These
variants apply the bundled instrument setups to supported notation; they do not
automatically arrange arbitrary music for another instrument.

Each selected instrument variant also gets a multikey edition when
`multikey-books` is enabled.

### Media exports

MIDI and audio exports normally come only from the default variant's ordinary
edition. Other variants' ordinary editions support
`--midifiles-allow-for-optional-variants` and
`--audiofiles-allow-for-optional-variants` (or the corresponding TOML keys).
These opt-ins use each variant's own generated MIDI. MIDI export must still be
enabled for the MIDI opt-in, and audio export for the audio opt-in:
`--no-midi` and `--no-audio` independently disable their respective exports.
Audio can be generated with MIDI or JSON export disabled. Multikey editions
never generate MIDI or audio, regardless of opt-ins.

### Multikey PDF editions

Optional `_MULTIKEY` editions include all twelve keys as PDF layers, so readers
can choose a key independently for each song in a compatible viewer. Chords,
melody hints, and key labels switch together; supported LilyPond notation can
switch too. Ordinary PDFs remain unchanged.

Enable these editions in `ulsbs-config.toml`. Both settings default to `false`:

```toml
multikey-books = true
multikey-lilypond-scores = true  # optional: also transpose supported full scores
```

Each selected default or instrument variant gets a JSON index and one or more
layered page-range PDFs in `result/multikey/` and, when deployment is enabled,
`deploy/multikey/`. For example:

```text
Book_A5.pdf
multikey/Book_A5_MULTIKEY_RANGES.json
multikey/Book_A5_MULTIKEY_RANGE_1-50.pdf
multikey/Book_A5_MULTIKEY_RANGE_51-100.pdf
multikey/Book_A5_MULTIKEY_RANGE_101-137.pdf
Book_CHARANGO_A5.pdf
multikey/Book_CHARANGO_A5_MULTIKEY_RANGES.json
multikey/Book_CHARANGO_A5_MULTIKEY_RANGE_1-50.pdf
```

Share the index and all its range PDFs together, keeping their filenames and
relative locations unchanged. There is no single full-book multikey PDF; even
a small book has an index and one range. The index is created even with
`json = false` or `--no-json`. Multikey jobs create no extra MIDI, audio,
printouts, or covers.

Use a viewer with PDF-layer support to open individual ranges, or a website
that understands the index and provides multikey controls. Viewer support varies;
use the ordinary PDF for conventional printing and maximum compatibility. Hidden
alternatives may still appear in search, copied text, or accessibility output.
When updating a live website, publish the matching ordinary PDF, index, and
ranges together. Consistent live updates require an atomic edition-directory
deployment; see the [deployment contract](ARCHITECTURE.md#build-jobs-and-publication).

Give songs stable `id=` values (lowercase letters, digits, and dashes) and
accurate `key=` metadata. Missing or invalid IDs skip that song's interactive
layers with a warning. Major and minor keys are supported; modal suffixes such
as `lyd.`, `dor.`, or `mix.` leave scores original-only, without guessing a key.
Unsupported scores or alternatives that cannot be engraved safely retain the
original notation with a warning. Score transposition supports standard ULSBS
snippets and selected named-variable score layouts, not arbitrary LilyPond code.
Recommended singing keys (`gk=`), standalone `\altchords`, prose, and chord
diagrams do not switch. See the [writing guide](WRITING_SONGBOOKS.md#keys-and-accidentals)
for key metadata and source transposition.

Multikey builds take longer, especially with score transposition. Successful
score alternatives are cached for later builds. `--clear-score-cache` clears
that cache in the actual build environment (container or host). Use
`--no-multikey` or `--quick` to skip multikey editions for one build.

Other optional settings:

- `multikey-layer-ui = "native"` (default) requests the viewer's layer list;
  `"hidden"` requests hiding it for viewers with their own controls. Some viewers
  still expose the list.
- `multikey-min-chordname-scale = 0.85` limits alternative chord-name shrinking
  (range `0.5` to `1`); use `1` to disable shrinking. Long names may then overhang.
  This does not control full-score image fitting.
- `multikey-require-song-ids = true` (default `false`) or `--require-song-ids`
  makes missing or invalid song IDs an error in multikey editions.
- `multikey-max-pages-per-range = 50` is the nominal maximum physical pages per range.
- `multikey-target-max-range-bytes = 33554432` targets 32 MiB per extracted file.

Both sizing options require positive TOML integers and follow normal profile
inheritance; dashed and snake_case names are accepted. Smaller ranges may be
created to meet the byte target. A single page over the target is kept with a
warning. Range numbers refer to physical PDF pages, including covers, not printed
page labels; use the index rather than assuming fixed 50-page ranges.

If packaging fails validation, the build reports an error rather than publishing
an incomplete multikey edition. [Architecture](ARCHITECTURE.md#multikey-books)
documents viewer integration, package contracts, and cache maintenance.

## Requirements

### Recommended: container build

By default ULSBS compiles inside Docker or Podman. You need:

- `bash` 3.0+ and Python 3.11+ on the host.
- Git for the recommended submodule setup.
- Docker or Podman, installed and runnable by your user.
- Enough disk space for the image (roughly 2.5 GiB), generated books, and caches.

The container supplies the typesetting tools, fonts, and compiler dependencies;
you do not need to install LaTeX or LilyPond separately on the host. The first
image build is slower. Builds may run in parallel; use `--sequential` on
low-memory systems. Select Podman explicitly with `--container-engine podman`
if both engines are installed.

After an engine update that changes container dependencies, rebuild with
`./ulsbs/ulsbs-compile --container-rebuild`. Rebuilding also attempts to clear the
container's persistent home-cache volume, including cached score alternatives.

### Host build (`--no-container`)

Host mode requires a compatible toolchain, including:

- A recent LaTeX distribution with `lualatex` and `texlua`.
- LilyPond with `lilypond-book`.
- `bash` and Python 3.11+.
- Python package `pikepdf` 8+ (mandatory for automatic PDF font sharing).
- `qpdf` 12.2.0+ when multikey generation is enabled.
- Noto fonts (`Noto Sans`, `Noto Serif`, with needed weights).
- Locale `fi_FI.utf8`.

Additional tools depend on the outputs you want:

| Output | Tools | Disable with |
|---|---|---|
| A5-on-A4 printouts | `context` or `contextjit` | `--no-printouts` / `create-printouts = false` |
| MP3 audio from MIDI | `ffmpeg`, `fluidsynth`, and a General MIDI soundfont | `--no-audio` / `audiofiles = false` |
| Cover PNGs | `pdftoppm`; ImageMagick `magick` for modified covers | `--no-coverimage` / `coverimage = false` |

These outputs are enabled by default, but depend on suitable input and available
tools. Disabling them does not remove the core LaTeX/LilyPond requirements.
ULSBS vendors a compatible copy of the `songs` LaTeX package; the other LaTeX
packages must be provided by your TeX installation.

### Platform-specific setup examples

After installing your platform's prerequisites, follow the
[quick start](#quick-start) to create and compile a project.

#### Ubuntu or Debian with Docker

```sh
sudo apt update
sudo apt install docker.io git python3
sudo usermod -aG docker "$USER"
newgrp docker
```

If you prefer Podman, install `podman` instead of `docker.io` and omit the
Docker group commands.

#### macOS with Docker Desktop

1. Install [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/).
2. Install [Python 3.11+](https://www.python.org/downloads/macos/).
3. If Git is missing, install Xcode Command Line Tools with `xcode-select --install`.
4. Start Docker Desktop before compiling.

#### Windows with WSL2 and Docker Desktop

1. In PowerShell, run `wsl --install -d Ubuntu`.
2. Install Docker Desktop and enable
   [WSL integration for Ubuntu](https://docs.docker.com/desktop/setup/install/windows-install/).
3. In the Ubuntu shell, run `sudo apt update` and `sudo apt install git python3`.
4. Follow the quick start inside Ubuntu. Keep the project in the Linux home
   directory rather than `/mnt/c` for better filesystem performance.

If `docker` is unavailable inside WSL, start Docker Desktop and verify its WSL
integration settings.

#### Ubuntu 24.04 host build (`--no-container`)

Ubuntu 24.04 is a reference host setup. Install the toolchain:

```sh
sudo apt update
sudo apt install bash locales git python3 python3-pikepdf qpdf context context-modules ffmpeg fluidsynth fluid-soundfont-gm fonts-noto-core fonts-noto-extra fonts-noto-mono imagemagick lilypond poppler-utils texlive texlive-font-utils texlive-lang-arabic texlive-lang-english texlive-lang-european texlive-lang-portuguese texlive-lang-spanish texlive-latex-base texlive-latex-extra texlive-luatex texlive-music texlive-plain-generic
sudo locale-gen fi_FI.utf8
sudo mtxrun --generate
```

Then follow the quick start, adding `--no-container` to compilation commands.
Check qpdf's version against the multikey requirement above if enabling multikey
editions; the distribution's default package may be older. Modified cover images
require the `magick` executable, which older ImageMagick packages may not supply.

## Configuration

ULSBS reads `ulsbs-config.toml` in your songbook project root. Start with the
minimal configuration, then add settings as needed. The
[annotated example](ulsbs-config-example.toml) lists all public settings, profile
inheritance, array merging, and deployment options.

Dashed and snake_case setting names are equivalent. File patterns in the config
are resolved relative to its directory. Precedence, from lowest to highest, is:
built-ins, flat configuration, selected profile, environment variables, CLI flags.

For example, keep normal outputs for releases and use a smaller development profile:

```toml
songbooks = ["my-songbook_A5.tex"]

[profiles.dev]
deploy = false
lyricbooks = false
create-printouts = false
coverimage = false
audiofiles = false
multikey-books = false
```

Select it with `./ulsbs/ulsbs-compile --profile dev`. Profiles inherit root
settings unless they override them; `inherit-from` selects another parent
profile. Arrays replace their parent's value unless listed in `merge-keys`.

Common settings include `deploy`, `deploy-dir`, `create-printouts`, `coverimage`,
`json`, `midifiles`, `audiofiles`, `lyricbooks`, and `multikey-books`.
The `common-deploy-icons`, `common-deploy-social-images`, `common-deploy-metadata`,
and `common-deploy-other` lists add project files to deployment.

Useful environment variables:

| Variable | Purpose |
|---|---|
| `ULSBS_ENGINE` | Explicit path to an engine checkout for the wrapper |
| `ULSBS_CONTAINER_ENGINE` | `auto`, `docker`, or `podman` |
| `ULSBS_MAX_PARALLEL` | Upper bound for parallel jobs; unset or `0` means automatic |
| `ULSBS_MAX_CONTAINER_MEM_GB` | Container memory limit in GiB; `0` means no limit |
| `ULSBS_USE_SYSTEM_TMP_FOR_TEMP` | `true` uses system `/tmp` for intermediate files |

If raising parallelism, also provide enough container memory. Roughly 1-2 GiB
per job is a starting point, not a guarantee. A memory-backed `/tmp` can improve
I/O performance but can increase memory pressure.

## Writing songbooks

The [Writing Songbooks guide](WRITING_SONGBOOKS.md) covers basic songs and verses,
chords, measure bars, repeats, keys and transposition, melody hints, full LilyPond
scores, metadata, chapters, indices, selections, and layout customization.

The main document must use `ulsbs-songbook` or a derived class. You do not need
to develop a custom class to make your own book; start with the standard class
and the guide's documented settings.

## Utilities

The source checkout provides wrappers under `ulsbs/`; a pip installation makes
the same tools available by name. Each tool accepts `--help`.

### `ulsbs-bookmeta`

Extract songbook metadata as JSON, plain text, or Markdown, or check stable song
IDs. From the songbook project root:

```sh
./ulsbs/ulsbs-bookmeta --json my-songbook_A5.tex > songbook.json
./ulsbs/ulsbs-bookmeta --check-song-ids my-songbook_A5.tex
```

`--create-song-ids` interactively creates or fixes IDs in source files; review
the source diff afterwards. Normal compilation does not assign IDs for you.

### `ulsbs-midi2audio`

Convert MIDI files to audio using `ffmpeg` and `fluidsynth`. This is also used
by the compiler's audio export.

### `ulsbs-ly2tex`

Convert ULSBS-style LilyPond lyric output into songbook text. See the
[lyric-conversion notes](WRITING_SONGBOOKS.md#converting-lilypond-lyrics).

### `ulsbs-migrate-syntax-v1`

For existing projects with legacy syntax, migrate `\mn*`, `\ma*`, beat-mark,
and `\ac<n>{Chord}` forms to melody blocks and `\ac{n}{Chord}`. It also replaces
`\shrp` and `\flt` with `#` and `&` inside `\altchords`, `\beginsong`'s
`key`/`gk` values, and `\audio`'s `key` value; accidental macros elsewhere stay
unchanged. New projects should use the writing guide's current syntax.

```sh
./ulsbs/ulsbs-migrate-syntax-v1 --check content/
./ulsbs/ulsbs-migrate-syntax-v1 --diff content/songs_main.tex
./ulsbs/ulsbs-migrate-syntax-v1 --write content/
```

The version identifies the destination syntax. `ulsbs-migrate-melody-syntax` is
retained as a compatibility alias. `--check` never writes and exits nonzero while
legacy syntax remains. `--diff` previews safe conversions; `--write` updates only
files without diagnostics, although it may change other safe files in a directory.

Malformed arguments, compound pitches, incompatible offsets, ambiguous
secondary placement, and low `\mnd`/`\mad` forms need review. Use `--normalize-low`
only after review; it normalizes those slots but never changes verse environments.
The migrator does not infer missing secondary-note slots. Review diagnostics
and converted notation before committing. See
[migration details](ARCHITECTURE.md#syntax-migration) for preservation rules.

## Editor support

The [ULSBS TeX Tools extension](vscode-extension/ulsbs-tex-tools/README.md) for
VS Code adds snippets, folding, navigation, structural outlines, and syntax help.
Its README includes installation instructions. Other text editors also work.

## Troubleshooting

- **No books selected:** set `songbooks` in the project config or supply a main
  `.tex` file on the command line. Compile from the project root.
- **Container engine unavailable:** start Docker Desktop or verify that your
  user can run Docker/Podman. Use `--container-engine podman` to select Podman.
- **Too much memory use:** try `--sequential`, or lower `ULSBS_MAX_PARALLEL`.
- **Need more error detail:** use `--verbose`, `--max-log-lines 100`, and
  `--keep-temp` to retain intermediate files and the numbered logs.
- **Missing optional outputs:** check their feature flags, required tools, and
  source content. Lyrics and chords alone do not produce MIDI or MP3 audio.
- **Multikey song does not switch:** check its stable ID and key, viewer layer
  support, and whether full-score transposition was separately enabled.

## Contact

For help getting started, questions about writing or compiling songbooks, or
feedback on ULSBS, you are welcome to contact **Lari Natri** by email. You can
find the address in the copyright header at the top of e.g.
[`ulsbs.sty`](src/ulsbs/assets/tex/ulsbs.sty).
You do not need to open a GitHub issue to ask for help; email is welcome too.

## Developer documentation

[Architecture](ARCHITECTURE.md) covers engine internals, PDF/viewer contracts,
cache maintenance, and testing. From the engine source directory, `./ulsbs-test`
runs the supported containerized regression suite. Authors do not need to run
that suite to compile their books.

[MAINTAINERS.md](MAINTAINERS.md) documents release procedures.

## Acknowledgements

ULSBS uses a bundled copy of the [`songs` LaTeX package](https://songs.sourceforge.net/)
by **Kevin W. Hamlen**. Its song-layout and indexing facilities form an important
foundation of ULSBS, which extensively customizes and extends their behavior.
The [writing guide](WRITING_SONGBOOKS.md) links to the original package's
documentation as well as explaining ULSBS-specific syntax.

## License

GNU General Public License version 3 or later (GPL 3.0+).

Documents generated using ULSBS are not considered derivative works of the
ULSBS code. You remain responsible for the rights to the songs, images, and
other content you publish.
