# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Engine guards and installed companion-resource contracts."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from test_tex_integration import ROOT, TEX_ASSETS, compile_fixture


COMPANIONS = (
    "ulsbs-package-defaults.code.tex",
    "ulsbs-init.code.tex",
    "ulsbs-book-defaults.code.tex",
    "ulsbs-style.code.tex",
    "ulsbs-pdf-layer-setup.code.tex",
    "ulsbs-utilities.code.tex",
    "ulsbs-typography.code.tex",
    "ulsbs-frontmatter.code.tex",
    "ulsbs-boolmap.code.tex",
    "ulsbs-chapter-marks.code.tex",
    "ulsbs-multikey.lua",
    "ulsbs-index.code.tex",
    "ulsbs-index-display.code.tex",
    "ulsbs-index.lua",
    "ulsbs-index-state.lua",
    "ulsbs-index-records.lua",
    "ulsbs-song.code.tex",
    "ulsbs-layout.code.tex",
    "ulsbs-layout.lua",
    "ulsbs-verse.code.tex",
    "ulsbs-chords.code.tex",
    "ulsbs-music.code.tex",
    "ulsbs-multikey.code.tex",
    "ulsbs-diagrams.code.tex",
)


def assert_package(check, names):
    for name in names:
        check.assertNotIn("reference-legacy", name)
        check.assertNotIn("ext_packages/songs", name)
        check.assertNotIn(Path(name).name, ("songs.sty", "songidx.lua"))
        check.assertNotEqual(Path(name).name, "NOTICE")
    check.assertTrue(any(Path(name).name == "LICENSE" for name in names), names)


class RuntimeIsolationTests(unittest.TestCase):
    def test_l3build_source_and_install_patterns_cover_companions(self):
        config = (ROOT / "build.lua").read_text()
        self.assertNotIn("checkinit_hook", config)
        companions = [path for path in TEX_ASSETS.iterdir()
                      if path.is_file() and path.suffix in (".tex", ".lua", ".sty", ".cls")]
        self.assertTrue(companions)
        for name in ("sourcefiles", "installfiles"):
            match = re.search(rf"\b{name}\s*=\s*\{{([^}}]*)\}}", config)
            self.assertIsNotNone(match, name)
            patterns = re.findall(r'"([^"\n]+)"', match.group(1))
            for path in companions:
                self.assertTrue(any(path.match(pattern) for pattern in patterns), f"{name}: {path.name}")

    def test_runtime_contains_no_legacy_implementation_or_switches(self):
        self.assertFalse((TEX_ASSETS / "ext_packages/songs").exists())
        forbidden = ("SB@", "g__ulsbs_backend_tl", "__ulsbs_test_backend:",
                     "ulsbsLegacyOnly", "ulsbsNativeOnly", "ulsbsIfNativeTF",
                     "ext_packages/songs", "songidx.lua")
        for path in TEX_ASSETS.rglob("*"):
            if path.is_file():
                self.assertNotIn(path.name, ("songs.sty", "songidx.lua"))
                source = "\n".join(line for line in path.read_text().splitlines()
                                   if not line.lstrip().startswith(("%", "--")))
                for token in forbidden:
                    self.assertNotIn(token, source, f"{path}: {token}")

class ModuleEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        missing = [tool for tool in ("lualatex", "pdflatex", "xetex", "kpsewhich")
                   if shutil.which(tool) is None]
        if missing:
            raise unittest.SkipTest(f"TeX integration tools are not installed: {', '.join(missing)}")
        result = subprocess.run(
            ["kpsewhich", "-progname=xelatex", "-format=fmt", "xelatex.fmt"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        cls.xelatex = ["xelatex"]
        if shutil.which("xelatex") is None or result.returncode:
            # The compiler image includes XeTeX and LaTeX, but not a prebuilt
            # XeLaTeX format. Generate only that format in a disposable directory.
            temporary = tempfile.TemporaryDirectory(prefix="ulsbs-xelatex-format-")
            cls.addClassCleanup(temporary.cleanup)
            work = Path(temporary.name)
            result = subprocess.run(
                ["xetex", "-ini", "-etex", "-interaction=nonstopmode", "-halt-on-error",
                 "-jobname=xelatex", "-progname=xelatex", "xelatex.ini"],
                cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, check=False, timeout=120,
            )
            if result.returncode:
                raise AssertionError(f"Cannot prepare installed XeTeX for guard tests:\n{result.stdout}")
            cls.xelatex = ["xetex", f"-fmt={work / 'xelatex.fmt'}", "-progname=xelatex"]

    def compile_entry(self, engine: str, entry: str, assets: Path = TEX_ASSETS):
        with tempfile.TemporaryDirectory(prefix="ulsbs-modules-") as temporary:
            work = Path(temporary)
            preamble = ""
            if entry == "class":
                preamble += "\\documentclass{ulsbs-songbook}\n"
            else:
                preamble += "\\documentclass{book}\n\\usepackage{ulsbs}\n"
            if engine == "lualatex":
                preamble += (
                    r"\ExplSyntaxOn\clist_map_inline:nn"
                    r"{SB@dotranspose,SB@boxup,SB@endsong,SB@beginverse,SB@stanzabreak,"
                    r"SB@setchord,SB@mbar,SB@obeylines}"
                    r"{\cs_if_exist:cT{#1}{\PackageError{ulsbs-test}"
                    r"{Legacy~helper~installed:~#1}{Startup~must~be~independent.}}}"
                    r"\ExplSyntaxOff" + "\n"
                )
            (work / "probe.tex").write_text(preamble + "\\begin{document}Probe\\end{document}\n")
            env = os.environ.copy()
            env["TEXINPUTS"] = f"{assets}//{os.pathsep}"
            env["LUAINPUTS"] = f"{assets}//{os.pathsep}"
            cache = work / "cache"
            cache.mkdir()
            env["TEXMFVAR"] = env["TEXMFCACHE"] = str(cache)
            # Do not halt at the first error: the guard itself must stop loading.
            result = subprocess.run(
                (self.xelatex if engine == "xelatex" else [engine])
                + ["-recorder", "-interaction=nonstopmode", "probe.tex"],
                cwd=work, env=env, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=120, check=False,
            )
            recorder = work / "probe.fls"
            inputs = [line[6:] for line in recorder.read_text().splitlines()
                      if line.startswith("INPUT ")] if recorder.exists() else []
            if engine == "lualatex":
                self.assertFalse([path for path in inputs
                                  if "ext_packages/songs/" in Path(path).as_posix()], inputs)
            loaded = {Path(path).name for path in inputs}
            return result, loaded, (work / "probe.pdf").exists()

    def test_unsupported_engines_stop_before_dependencies_on_both_entry_paths(self) -> None:
        for engine in ("pdflatex", "xelatex"):
            for entry in ("class", "package"):
                with self.subTest(engine=engine, entry=entry):
                    result, loaded, pdf = self.compile_entry(engine, entry)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    output = " ".join(result.stdout.split())
                    self.assertIn("LuaLaTeX is required", output)
                    self.assertIn("Class ulsbs-songbook Error" if entry == "class"
                                  else "Package ulsbs Error", output)
                    self.assertFalse(pdf, result.stdout)
                    self.assertFalse({"fontspec.sty", "polyglossia.sty", "songs.sty",
                                      "ulsbs-package-defaults.code.tex",
                                      "ulsbs-init.code.tex"} & loaded, loaded)

    def test_runtime_loads_owned_song_module_on_both_entry_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ulsbs-vendor-absent-") as temporary:
            assets = Path(temporary) / "tex"
            shutil.copytree(TEX_ASSETS, assets, ignore=shutil.ignore_patterns("songs"))
            self.assertFalse((assets / "ext_packages" / "songs").exists())
            for entry in ("class", "package"):
                with self.subTest(entry=entry):
                    result, loaded, pdf = self.compile_entry("lualatex", entry, assets=assets)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertTrue(pdf, result.stdout)
                    required = {name for name in COMPANIONS if name.endswith(".code.tex")}
                    required.update(("expl3.sty", "ulsbs-layout.lua"))
                    self.assertTrue(required.issubset(loaded), loaded)
                    self.assertNotIn("songs.sty", loaded)

    def test_editions_preserve_source_effects_without_backend_variables(self) -> None:
        probe = (r"\ExplSyntaxOn\AddToHook{begindocument/end}"
                 r"{\cs_if_exist:NT\g__ulsbs_backend_tl"
                 r"{\PackageError{ulsbs-test}{Backend~variable~installed}{}}}"
                 r"\ExplSyntaxOff" + "\n")
        for edition in ("", r"\def\ulSongbookType{lyric}"):
            with self.subTest(edition=edition):
                output, pdf = compile_fixture("source-effects", preamble=edition + probe, multikey=False)
                self.assertNotIn("songs.sty", output)
                self.assertEqual(re.findall(r"SOURCE-EFFECTS:(\d+)", output), ["7"])
                self.assertTrue(pdf.startswith(b"%PDF"))

    def test_generated_editions_compile_postsetup_and_vertical_cover_icons(self) -> None:
        from ulsbs.config import Config
        from ulsbs.jobs import Job
        from ulsbs.pipeline import make_variant_tex

        source = r"""
\documentclass[oneside,openany,paper=a5paper]{ulsbs-songbook}
\renewcommand{\ulInsertCoverIcons}{\ulInsertCoverIconsVtl}
\ulSetPermanentCoverIcons[ulsbs-tag-icon-music-generic_512x512px.png]
\begin{document}
\ulCoverPage{}
\begin{ulSongs}{}
\beginsong{Generated edition}[key={C}]
\beginverse
\[C]Edition probe.
\endverse
\endsong
\end{ulSongs}
\ifulLyricOnly\typeout{EDITION:lyrics}\fi
\ifulCharangoBook\typeout{EDITION:charango}\fi
\ifulBassclefBook\typeout{EDITION:bassclef}\fi
\end{document}
"""
        images = TEX_ASSETS.parent / "img"
        source = source.replace(r"\begin{document}",
                                rf"\graphicspath{{{{{images.as_posix()}/}}}}"
                                + "\n" + r"\begin{document}")
        with tempfile.TemporaryDirectory(prefix="ulsbs-editions-") as temporary:
            work = Path(temporary)
            document = work / "book.tex"
            document.write_text(source)
            for variant in ("default", "lyrics", "charango", "bassclef"):
                for multikey in (False, True):
                    if variant == "lyrics" and multikey:
                        continue
                    with self.subTest(variant=variant, multikey=multikey):
                        directory = work / (variant + ("-multikey" if multikey else ""))
                        directory.mkdir()
                        job = Job(document, document.stem, variant, directory, multikey=multikey)
                        generated = make_variant_tex(job, Config(multikey_books=True))
                        output, pdf = compile_fixture(
                            "source-effects", files={"source-effects.tex": generated.read_bytes()},
                            multikey=None)
                        self.assertEqual(re.findall(r"EDITION:(\w+)", output),
                                         [] if variant == "default" else [variant])
                        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_consumer_defaults_and_scoped_overrides_on_both_entry_paths(self) -> None:
        # Explicit settings test override timing, not the default typography.
        before = r"""
\newcommand{\ulTopMargin}{17mm}
\newcommand{\ulSideMargin}{19mm}
\newcommand{\ulBottomMargin}{23mm}
\newcommand{\ulHeadHeight}{8mm}
\newcommand{\ulChordLineBaselineSkip}{16pt}
\newcommand{\ulPreludeTextKey}{CUSTOM-KEY}
\newcommand{\ulPassageBaselineMultiplier}{1.3}
\newcommand{\ulMelodyNormalHeightFactor}{2.2}
"""
        after = r"""
\newcommand{\ProbeError}[1]{\PackageError{ulsbs-test}{#1}{}}
\ifdim\paperwidth=210mm\else\ProbeError{Pre-load paper size lost}\fi
\ifdim\ulTopMargin=17mm\else\ProbeError{Pre-load top margin lost}\fi
\ifdim\ulSideMargin=19mm\else\ProbeError{Pre-load side margin lost}\fi
\ifdim\ulBottomMargin=23mm\else\ProbeError{Pre-load bottom margin lost}\fi
\ifdim\headheight=8mm\else\ProbeError{Pre-load head height lost}\fi
\ifdim\ulChordLineBaselineSkip=16pt\else\ProbeError{Pre-load chord spacing lost}\fi
\newcommand{\ProbeKey}{CUSTOM-KEY}
\ifx\ulPreludeTextKey\ProbeKey\else\ProbeError{Pre-load key label lost}\fi
\newcommand{\ProbeMultiplier}{1.3}
\ifx\ulPassageBaselineMultiplier\ProbeMultiplier\else\ProbeError{Passage setting lost}\fi
\newcommand{\ProbeHeight}{2.2}
\ifx\ulMelodyNormalHeightFactor\ProbeHeight\else\ProbeError{Melody setting lost}\fi
\renewcommand{\ulLyricFontStyle}{\normalfont\fontsize{10}{12}\selectfont}
\setlength{\ulVerseSep}{17pt}
\ulSongPenalty=321\relax
\ulShowTags{true}
\begingroup
  \setlength{\ulVerseSep}{9pt}
  \ulSongPenalty=123\relax
  \ulShowTags{false}
  \ifulShowTags\ProbeError{Local visibility override lost}\fi
  \ifdim\ulVerseSep=9pt\else\ProbeError{Local length override lost}\fi
  \ifnum\ulSongPenalty=123\else\ProbeError{Local penalty override lost}\fi
\endgroup
\ifulShowTags\else\ProbeError{Visibility did not restore}\fi
\ifdim\ulVerseSep=17pt\else\ProbeError{Length did not restore}\fi
\ifnum\ulSongPenalty=321\else\ProbeError{Penalty did not restore}\fi
\ulShowTags{false}\ulShowPhase{false}
\begin{document}
\begin{ulSongs}{}
\beginsong{Configuration phases}[key={C}]
\beginverse*
\[<C> C]Configured lyrics.
\endverse
\endsong
\end{ulSongs}
\typeout{CONSUMER-SETTINGS:OK}
\end{document}
"""
        for size in (10, 11, 12):
            entries = (
                rf"\documentclass[{size}pt,oneside,openany,paper=a4paper]{{ulsbs-songbook}}",
                rf"\documentclass[{size}pt,oneside,openany]{{book}}"
                "\n" + r"\newcommand{\ulPaperSize}{a4paper}\usepackage{ulsbs}",
            )
            for entry in entries:
                with self.subTest(size=size, entry=entry):
                    source = (before + entry + "\n" + after).encode()
                    output, pdf = compile_fixture(
                        "source-effects", files={"source-effects.tex": source}, multikey=None)
                    self.assertIn("CONSUMER-SETTINGS:OK", output)
                    self.assertTrue(pdf.startswith(b"%PDF"))

    def test_initial_baseline_uses_font_size_and_early_chord_metrics(self) -> None:
        # Isolate initialization before shared typography can replace the metrics.
        probe = r"""
\usepackage{etoolbox,expl3,xparse}
\makeatletter
\input{ulsbs-init.code.tex}
\dimen@=\f@size pt\relax
\ifulChorded
  \advance\dimen@\ht\@tempboxa
  \advance\dimen@ 2pt\relax
\fi
\advance\dimen@\ulBaselineAdjustment
\ifdim\baselineskip=\dimen@\else
  \PackageError{ulsbs-test}{Initial baseline lost font or chord metrics}{}
\fi
\dimen@=\f@size pt\relax
\dimen@=\dimexpr\dimen@/10\relax
\ifdim\gluestretch\baselineskip=\dimen@\else
  \PackageError{ulsbs-test}{Initial baseline stretch is not one tenth of font size}{}
\fi
\ifdim\glueshrink\baselineskip=0pt\else
  \PackageError{ulsbs-test}{Unexpected initial baseline shrink}{}
\fi
\makeatother
\begin{document}
\typeout{INITIAL-BASELINE:OK}
Probe
\end{document}
"""
        for size in (10, 11, 12):
            for edition in ("chorded", "lyric"):
                with self.subTest(size=size, edition=edition):
                    source = (rf"\documentclass[{size}pt]{{book}}" + "\n"
                              + rf"\def\ulSongbookType{{{edition}}}" + probe).encode()
                    output, pdf = compile_fixture(
                        "source-effects", files={"source-effects.tex": source}, multikey=None)
                    self.assertIn("INITIAL-BASELINE:OK", output)
                    self.assertTrue(pdf.startswith(b"%PDF"))


class ModulePackagingSmoke:
    """Explicit offline smoke; not part of the dependency-free container suite."""

    check = unittest.TestCase()

    @classmethod
    def build(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="ulsbs-module-package-")
        cls.work = Path(cls.temporary.name)
        source = cls.work / "source"
        source.mkdir()
        # Avoid build products and egg-info in the real checkout.
        shutil.copytree(ROOT / "src", source / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        for name in ("pyproject.toml", "MANIFEST.in", "README.md", "WRITING_SONGBOOKS.md", "LICENSE"):
            shutil.copy2(ROOT / name, source / name)
        cls.dist = cls.work / "dist"
        cls.dist.mkdir()
        result = subprocess.run(
            [sys.executable, "-c", "import setuptools.build_meta as b; "
             "b.build_sdist(" + repr(str(cls.dist)) + "); "
             "b.build_wheel(" + repr(str(cls.dist)) + ")"],
            cwd=source, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False, timeout=120,
        )
        if result.returncode:
            raise AssertionError(f"Offline package build failed:\n{result.stdout}")
        cls.wheel = next(cls.dist.glob("*.whl"))
        cls.sdist = next(cls.dist.glob("*.tar.gz"))

    def test_wheel_and_sdist_include_only_companions(self) -> None:
        expected = COMPANIONS
        with zipfile.ZipFile(self.wheel) as archive:
            assert_package(self.check, archive.namelist())
            for name in expected:
                self.check.assertEqual(archive.read(f"ulsbs/assets/tex/{name}"),
                                       (TEX_ASSETS / name).read_bytes())
        with tarfile.open(self.sdist) as archive:
            assert_package(self.check, archive.getnames())
            prefix = archive.getnames()[0].split("/")[0]
            for name in expected:
                member = archive.extractfile(f"{prefix}/src/ulsbs/assets/tex/{name}")
                self.check.assertIsNotNone(member)
                self.check.assertEqual(member.read(), (TEX_ASSETS / name).read_bytes())

    def test_installed_engine_assets_resolves_companions(self) -> None:
        from installer import install
        from installer.destinations import SchemeDictionaryDestination
        from installer.sources import WheelFile

        installed = self.work / "installed"
        library = installed / "lib"
        scheme = {key: str(installed / key) for key in ("headers", "scripts", "data")}
        scheme.update(purelib=str(library), platlib=str(library))
        destination = SchemeDictionaryDestination(scheme, sys.executable, "posix")
        with WheelFile.open(self.wheel) as wheel:
            install(wheel, destination, additional_metadata={})
        result = subprocess.run(
            [sys.executable, "-I", "-c",
             "import json, sys; from pathlib import Path; "
             "sys.path.insert(0, sys.argv[1]); "
             "from ulsbs.engine_assets import EngineAssets; "
             "\nwith EngineAssets().tex_dir() as tex:\n"
             " print(json.dumps({'root': str(tex), 'files': "
             "{name: (tex / name).read_text() for name in sys.argv[2:]}}))",
             str(library), *COMPANIONS],
            cwd=self.work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False, timeout=30,
        )
        self.check.assertEqual(result.returncode, 0, result.stdout)
        resources = json.loads(result.stdout)
        self.check.assertTrue(Path(resources["root"]).is_relative_to(library))
        self.check.assertEqual(resources["files"],
                               {name: (TEX_ASSETS / name).read_text() for name in COMPANIONS})


if __name__ == "__main__":
    if sys.argv[1:] == ["--packaging-smoke"]:
        smoke = ModulePackagingSmoke()
        try:
            smoke.build()
            smoke.test_wheel_and_sdist_include_only_companions()
            smoke.test_installed_engine_assets_resolves_companions()
        finally:
            smoke.temporary.cleanup()
        print("Offline wheel/sdist/installed EngineAssets smoke passed")
    else:
        unittest.main()
