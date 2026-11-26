# ULSBS in TeXstudio (Experimental)

[VS Code with ULSBS TeX Tools](../vscode-extension/ulsbs-tex-tools/README.md) is
the recommended editor. [TeXstudio](https://texstudio.org/) support is
experimental. It uses the normal ULSBS compiler and TeXstudio's embedded PDF
viewer; the dedicated-profile setup below was checked on TeXstudio 4.9.10.

## Dedicated Profile

1. Install TeXstudio and the [ULSBS compiler prerequisites](../../README.md#requirements).
   Make sure `ulsbs-compile --quick --plain-output --no-deploy` works in a terminal
   with your main `.tex` file before configuring the editor.
2. Start TeXstudio with a separate settings directory so other LaTeX projects
   keep their existing settings. Use the same command each time you open this profile:

   ```sh
   texstudio --start-always --config "$HOME/.config/texstudio-ulsbs"
   ```

3. Open **Options > Configure TeXstudio > Build** and enable **Show advanced options**.
   Add a user command (for example, `user0:ULSBS Quick`, or use an unused ID):

   ```text
   ./ulsbs/ulsbs-compile --plain-output --no-deploy --quick --synctex ?ame"
   ```

   Replace `./ulsbs/ulsbs-compile` with `./ulsbs-compile` for a project-level
   wrapper or `ulsbs-compile` if installed on TeXstudio's `PATH`. A quoted absolute
   path also works. `?ame"` supplies the absolute path of the main `.tex` file
   as one argument, even if its path contains spaces. TeXstudio runs commands in
   the selected main document's directory. Add `--no-container` only if the
   normal compiler already works with your host toolchain.
4. Set these **Build** options, replacing `user0` if you chose a different ID:

   | Setting | Value |
   | --- | --- |
   | Default Compiler | `txs:///user0` |
   | Build & View | `txs:///compile \| txs:///view` |
   | Default Viewer | `txs:///view-pdf` |
   | PDF Viewer | `txs:///view-pdf-internal --embedded "?a)result/?m).pdf"` |

   The explicit PDF path avoids opening an old PDF beside the source. It assumes
   the main file is beside `ulsbs-config.toml`. If the main file is deeper in the
   project, adjust the executable path and the path to the project-level `result/`
   (for example, use `?a)../result/`).
5. Open the main `.tex` file and use **Build & View** (normally **F5**). Rebuilding
   refreshes the open pane. **Compile** (**F6**) and **View** (**F7**) work separately.
   Close any existing windowed preview once to switch to embedded. If a build fails,
   check **Messages**; the pane can still show the last successful PDF. The compiler
   output identifies detailed logs under `temp/`.

See the [TeXstudio build-system reference](https://texstudio-org.github.io/configuration.html#advanced-configuration-of-the-build-system)
for command and filename placeholder details. TeXstudio also supports
per-document `TXS-program` headers, but ULSBS documents only the dedicated profile
for builds. Existing headers can override the profile's commands.

### Included Song Files

Open the main document first. For a song file with just one main document, a
root directive can also identify it when opening the song directly:

```latex
% !TeX root = ../my-songbook_A5.tex
```

For songs shared by several books, switch to the intended main tab and use
**Options > Root Document > Set Current Document As Explicit Root**. Switch or
clear the explicit root when changing books. F5 then builds the selected main
document even while the cursor is in an included song.

### Editor-Only File Warnings

The compiler sets its own TeX search paths; TeXstudio does not use them to
follow `\input` in the editor. Use literal paths relative to the book root,
such as `\input{include/chapter.tex}`, even when the compiler also accepts the
bare filename. With **Editor > Automatically load included files** enabled,
reopen the main document so TeXstudio can discover its chapters and songs.

Custom classes such as `ulsbs-songbook-unilaiva-default` can still be marked
missing because TeXstudio's package index does not know about the checkout's
classes. If the build works, leave `\documentclass` unchanged. The `.cwl` files
provide completion independently of that index. To hide the underline, turn
off only **Editor > Inline Checking > Package** in the ULSBS profile. The class
hover can still say “not found”; this does not affect compilation or completion.

## Completion And Highlighting

Install the `.cwl` files in this directory into the dedicated profile's
`completion/user/` subdirectory (create it if it does not exist). With the command
above, that is `$HOME/.config/texstudio-ulsbs/completion/user/`. If the project
provides class-specific CWLs, install those in the same place.

Restart TeXstudio or reopen the book. The root's `\documentclass{ulsbs-songbook}`
or `\usepackage{ulsbs}` loads the metadata. For a custom class, put a CWL file
named exactly like the class (for example, `my-book.cwl` for `my-book.cls`) in
the same directory, with this line:

```text
#include:ulsbs-songbook
```

Leave ULSBS CWLs unselected in the global **Completion** list so they don't
affect unrelated LaTeX documents. The [CWL tables](https://texstudio-org.github.io/background.html#description-of-the-cwl-format)
provide command and metadata completion, song and chapter title highlighting,
outline entries, and recognition of ULSBS environments. The inner LilyPond
block is treated as verbatim, not as TeX. Add custom song metadata keys to your
class CWL if TeXstudio reports them as unknown. Class-option completion may be
unavailable when the class name is on a different line from its options.

TeXstudio does **not** understand all ULSBS syntax. In particular, its built-in LaTeX
parser treats `\[` as display math, so `\[<C;E>Am]lyric` can receive math coloring
or false syntax warnings. There is no shared language override: normal LaTeX
math keeps working, and LilyPond syntax and ULSBS notation are checked at build
time. In a dedicated profile, you can turn off **Editor > Inline Checking > Syntax**
if the false positives are distracting.

## Two-Way SyncTeX

By default, the compiler rebuilds `result/<book>.synctex.gz` alongside the
ordinary PDF. In TeXstudio, use **Go to PDF** from the editor or **Jump to Source**
from the embedded viewer (Ctrl-click on Linux/Windows, or use the context menus).
The PDF and sidecar must come from the same build. Builds with `--no-synctex`
or `synctex = false` remove any old sidecar for their output. The sidecar contains local source
paths and is not a deployment artifact.

Main and included TeX source lines are mapped through the compiler's staging and
LilyPond preprocessing. Lyrics before and after scores and lines containing chord
or melody annotations are useful jump targets. Navigation is line-based, not
pixel-exact: if clicking a lyric jumps to the enclosing input instead, try
closer to the start of the line. A chord, beat, or annotation may have the same
target as the lyric on that line. TeX may attribute a title, index
entry, or boxed content to the enclosing command. A click on an engraved
LilyPond system can land in generated `*-systems.tex`. Notes and `.ily` imports
are not mapped back to authored LilyPond lines; use the surrounding TeX to navigate.
Printouts and split multikey PDFs have no sidecar. If a build reports **SyncTeX
unavailable**, the ordinary PDF is still usable.

### Other Editors

The sidecar is standard SyncTeX, not a TeXstudio format. Build with
`ulsbs-compile --quick --no-deploy --synctex BOOK.tex` and configure your editor
or viewer to use `result/BOOK.pdf` on the same filesystem as the source paths
recorded in the sidecar.

- **VS Code:** [ULSBS TeX Tools](../vscode-extension/ulsbs-tex-tools/README.md)
  has a PDF preview and supports jumps in both directions. Alternatively, use
  [LaTeX Workshop's viewer and SyncTeX](https://github.com/James-Yu/LaTeX-Workshop/wiki/View#synctex)
  with `"latex-workshop.latex.outDir": "%DIR%/result"` for a book root at the
  project root. If you use it only as a viewer, set
  `"latex-workshop.latex.autoBuild.run": "never"` and build with ULSBS from a
  terminal. A custom recipe that invokes ULSBS with `--synctex` can also work.
- **Other editors:** Use a SyncTeX-enabled viewer such as [Zathura](https://pwmt.org/projects/zathura/documentation/#synctex-support)
  with an inverse-search command for your editor. For example, VS Code accepts
  `code --reuse-window --goto "FILE:LINE"` using the viewer's file and line placeholders.

For debugging, the same sidecar can be queried with TeX Live's
`synctex view -i 'LINE:1:/absolute/path/to/source.tex' -o result/BOOK.pdf` and
`synctex edit -o 'PAGE:X:Y:result/BOOK.pdf'`. Direct LuaLaTeX also supports
`-synctex=1` on the full passes described in the [manual build guide](../../WRITING_SONGBOOKS.md#manual-lualatex-builds)
and records original inputs directly. Use it only for advanced diagnostics:
it does not preprocess LilyPond or perform other compiler output steps.

## Platform Notes

| Platform | Notes |
| --- | --- |
| Linux | A native TeXstudio package can run the normal compiler directly. With a sandboxed package, verify access to the checkout and host compiler/container runtime; use the native package if needed. |
| macOS | The GUI may not inherit terminal `PATH` entries for Python, MacTeX (`/Library/TeX/texbin`), or Docker/Podman. Start TeXstudio from a configured shell or give the compiler and its tools an appropriate `PATH`. |
| Windows | Use WSL2 with TeXstudio running in the same Linux distribution (for example, via WSLg) for one consistent set of source paths. Use Podman or Docker Engine in WSL, or an already working host-toolchain setup. Native Windows TeXstudio can open the finished PDF; invoking the POSIX compiler from it or mixing Windows and WSL paths for SyncTeX is not covered by this setup. |

The workflow was exercised on Linux. The macOS and Windows setups above were
not runtime-tested.
