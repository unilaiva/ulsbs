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
    "ulsbs-variants.code.tex",
    "ulsbs-variant-default.code.tex",
    "ulsbs-package-defaults.code.tex",
    "ulsbs-init.code.tex",
    "ulsbs-book-defaults.code.tex",
    "ulsbs-visibility.code.tex",
    "ulsbs-style.code.tex",
    "ulsbs-pdf-layer-setup.code.tex",
    "ulsbs-utilities.code.tex",
    "ulsbs-typography.code.tex",
    "ulsbs-frontmatter.code.tex",
    "ulsbs-song-helpers.code.tex",
    "ulsbs-prose.code.tex",
    "ulsbs-media.code.tex",
    "ulsbs-melody.code.tex",
    "ulsbs-song-metadata.code.tex",
    "ulsbs-notes.code.tex",
    "ulsbs-repeats.code.tex",
    "ulsbs-repeats.lua",
    "ulsbs-spacing.code.tex",
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
    "ulsbs-music.lua",
    "ulsbs-multikey.code.tex",
    "ulsbs-diagrams.code.tex",
)

REGISTRY = "ulsbs-variants.def.tex"
VARIANT_PRESETS = tuple(f"ulsbs-variant-{name}.code.tex"
                       for name in ("lyric", "charango", "bassclef"))


def assert_package_license(check, names):
    check.assertTrue(any(Path(name).name == "LICENSE" for name in names), names)


class RuntimeIsolationTests(unittest.TestCase):
    def test_companion_inventory_covers_private_tex_and_lua_modules(self):
        # The packaging smoke must exercise every private module, including new
        # extractions, rather than silently omitting an unlisted resource.
        modules = {path.name for path in TEX_ASSETS.iterdir()
                   if path.name.endswith(".code.tex") or path.suffix == ".lua"}
        self.assertEqual(modules, set(COMPANIONS) | set(VARIANT_PRESETS)
                         | {"ulsbs-score-layers.lua"})

    def test_l3build_source_and_install_patterns_cover_companions(self):
        config = (ROOT / "build.lua").read_text()
        companions = [path for path in TEX_ASSETS.iterdir()
                      if path.is_file() and path.suffix in (".tex", ".lua", ".sty", ".cls")]
        self.assertTrue(companions)
        for name in ("sourcefiles", "installfiles"):
            match = re.search(rf"\b{name}\s*=\s*\{{([^}}]*)\}}", config)
            self.assertIsNotNone(match, name)
            patterns = re.findall(r'"([^"\n]+)"', match.group(1))
            for path in companions:
                self.assertTrue(any(path.match(pattern) for pattern in patterns), f"{name}: {path.name}")

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

    def compile_entry(self, engine: str, entry: str):
        with tempfile.TemporaryDirectory(prefix="ulsbs-modules-") as temporary:
            work = Path(temporary)
            preamble = ""
            if entry == "class":
                preamble += "\\documentclass{ulsbs-songbook}\n"
            else:
                preamble += "\\documentclass{book}\n\\usepackage{ulsbs}\n"
            (work / "probe.tex").write_text(preamble + "\\begin{document}Probe\\end{document}\n")
            env = os.environ.copy()
            env["TEXINPUTS"] = f"{TEX_ASSETS}//{os.pathsep}"
            env["LUAINPUTS"] = f"{TEX_ASSETS}//{os.pathsep}"
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
                    self.assertFalse({"fontspec.sty", "polyglossia.sty",
                                      "ulsbs-package-defaults.code.tex",
                                      "ulsbs-init.code.tex"} & loaded, loaded)

    def test_runtime_loads_owned_song_module_on_both_entry_paths(self) -> None:
        for entry in ("class", "package"):
            with self.subTest(entry=entry):
                result, loaded, pdf = self.compile_entry("lualatex", entry)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertTrue(pdf, result.stdout)
                required = {name for name in COMPANIONS if name.endswith(".code.tex")}
                required.update(("expl3.sty", "ulsbs-layout.lua", "ulsbs-repeats.lua"))
                self.assertTrue(required.issubset(loaded), loaded)

    def test_variants_preserve_source_effects(self) -> None:
        for variant in ("default", "lyric"):
            with self.subTest(variant=variant):
                selector = rf"\def\ulBuildVariant{{{variant}}}"
                output, pdf = compile_fixture("source-effects", preamble=selector, multikey=False)
                self.assertEqual(re.findall(r"SOURCE-EFFECTS:(\d+)", output), ["7"])
                self.assertTrue(pdf.startswith(b"%PDF"))

    def test_generated_editions_compile_owned_presets_and_vertical_cover_icons(self) -> None:
        from ulsbs.config import Config
        from ulsbs.jobs import Job
        from ulsbs.pipeline import make_variant_tex

        source = r"""
\documentclass[variants={default,lyric,charango,bassclef},oneside,openany,paper=a5paper]{ulsbs-songbook}
\newcommand\ProbeError[1]{\PackageError{ulsbs-test}{#1}{}}
\ulIfVariant{default}{\typeout{EDITION:default}}{}
\ulIfVariant{lyric}{\typeout{EDITION:lyric}}{}
\ulIfVariant{charango}{\typeout{EDITION:charango}}{}
\ulIfVariant{bassclef}{\typeout{EDITION:bassclef}}{}
\typeout{PRESET:\ifulShowChords on\else off\fi/\ifulShowLilypond on\else off\fi/\ifulShowMusicComments on\else off\fi}
{\chordsoff\ulLocalShow{scores}{false}
 \ifulShowChords\ProbeError{Local chord suppression lost}\fi
 \ifulShowLilypond\ProbeError{Local score suppression lost}\fi}
\typeout{RESTORED:\ifulShowChords on\else off\fi/\ifulShowLilypond on\else off\fi}
\ulShowChords{true}\chordson\ulShowLilypond{true}\ulLocalShow{scores}{true}
\typeout{OVERRIDE:\ifulShowChords on\else off\fi/\ifulShowLilypond on\else off\fi}
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
            for variant in ("default", "lyric", "charango", "bassclef"):
                for multikey in (False, True):
                    if variant == "lyric" and multikey:
                        continue
                    with self.subTest(variant=variant, multikey=multikey):
                        directory = work / (variant + ("-multikey" if multikey else ""))
                        directory.mkdir()
                        job = Job(document, document.stem, variant, directory, multikey=multikey)
                        generated = make_variant_tex(job, Config(multikey_books=True))
                        text = generated.read_text()
                        self.assertTrue(text.endswith(source))
                        selector = rf"\def\ulBuildVariant{{{variant}}}"
                        if variant == "default":
                            self.assertNotIn(r"\ulBuildVariant", text)
                        else:
                            self.assertLess(text.index(selector), text.index(r"\documentclass"))
                        output, pdf = compile_fixture(
                            "source-effects", files={"source-effects.tex": generated.read_bytes()},
                            multikey=None)
                        self.assertEqual(re.findall(r"EDITION:(\w+)", output), [variant])
                        chords = "on" if variant in ("default", "charango") else "off"
                        scores = "off" if variant == "lyric" else "on"
                        self.assertIn(f"PRESET:{chords}/{scores}/{scores}", output)
                        self.assertIn(f"RESTORED:{chords}/{scores}", output)
                        self.assertIn("OVERRIDE:on/on", output)
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
\ulVerseBaseline{2}{.25}{.125}
\ulVerseSeparation{2}{0}{.27}
\begingroup\ulLyricFontStyle\ulVerseFont
\xdef\ConfiguredVerseA{\number\fontcharht\font`A}\endgroup
\AddToHook{ulsbs/stanza/start}{\directlua{
 local nominal = tex.skip['l__ulsbs_verse_nominal_skip']
 local baseline = tex.skip.baselineskip
 local a = (\ConfiguredVerseA)
 assert(baseline.width == nominal.width and baseline.width == 2*a, 'scalar total nominal leading')
 assert(baseline.stretch == nominal.stretch and math.abs(baseline.stretch - .25*a) <= 1)
 assert(baseline.shrink == nominal.shrink and math.abs(baseline.shrink - .125*a) <= 1)
 assert(tex.skip['ulsbs@verse@separation'].width == 2*a, 'scalar separation survives until verse use')
}}
\ulSongPenalty=321\relax
\ulShowTags{true}
\begingroup
  \ulVerseSeparation{3}{0}{.27}
  \ulSongPenalty=123\relax
  \ulShowTags{false}
  \ifulShowTags\ProbeError{Local visibility override lost}\fi
  \ifdim\csname ulsbs@verse@separation\endcsname=\dimexpr\ConfiguredVerseA sp*3\relax\else\ProbeError{Local length override lost}\fi
  \ifnum\ulSongPenalty=123\else\ProbeError{Local penalty override lost}\fi
\endgroup
\ifulShowTags\else\ProbeError{Visibility did not restore}\fi
\ifdim\csname ulsbs@verse@separation\endcsname=\dimexpr\ConfiguredVerseA sp*2\relax\else\ProbeError{Length did not restore}\fi
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

    def test_initial_baseline_is_lyric_only_but_preserves_early_font_allocation(self) -> None:
        # Isolate initialization before shared typography and finalized policy.
        probe = r"""
\usepackage{etoolbox,expl3,xparse}
\makeatletter
\input{ulsbs-init.code.tex}
\dimen@=\f@size pt\relax
\ifdim\baselineskip=\dimen@\else
  \PackageError{ulsbs-test}{Initial baseline is not lyric-only}{}
\fi
\ifdim\ht\@tempboxa>0pt\else
  \PackageError{ulsbs-test}{Early chord sample allocation lost}{}
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
            with self.subTest(size=size):
                source = (rf"\documentclass[{size}pt]{{book}}" + "\n" + probe).encode()
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

    def test_wheel_and_sdist_include_companions_and_license(self) -> None:
        expected = (*COMPANIONS, REGISTRY, *VARIANT_PRESETS)
        with zipfile.ZipFile(self.wheel) as archive:
            assert_package_license(self.check, archive.namelist())
            for name in expected:
                self.check.assertEqual(archive.read(f"ulsbs/assets/tex/{name}"),
                                       (TEX_ASSETS / name).read_bytes())
        with tarfile.open(self.sdist) as archive:
            assert_package_license(self.check, archive.getnames())
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
             "from ulsbs.variants import VARIANTS, available_variants; "
             "assert available_variants(r'\\documentclass[variants={default,lyric}]"
             "{ulsbs-songbook-independent}') == ('default', 'lyric'); "
             "\nwith EngineAssets().tex_dir() as tex:\n"
             " print(json.dumps({'root': str(tex), 'variants': list(VARIANTS), 'files': "
             "{name: (tex / name).read_text() for name in sys.argv[2:]}}))",
             str(library), *COMPANIONS, REGISTRY, *VARIANT_PRESETS],
            cwd=self.work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False, timeout=30,
        )
        self.check.assertEqual(result.returncode, 0, result.stdout)
        resources = json.loads(result.stdout)
        self.check.assertEqual(resources["variants"], ["default", "lyric", "charango", "bassclef"])
        self.check.assertTrue(Path(resources["root"]).is_relative_to(library))
        self.check.assertEqual(resources["files"],
                               {name: (TEX_ASSETS / name).read_text()
                                for name in (*COMPANIONS, REGISTRY, *VARIANT_PRESETS)})

        # Run outside the checkout with only installed TeX/Lua assets in lookup.
        # Use installed planning/generation, not the checkout or a manual selector.
        assets = Path(resources["root"])
        work = self.work / "independent-book"
        work.mkdir()
        env = os.environ.copy()
        env["TEXINPUTS"] = env["LUAINPUTS"] = f"{assets}//{os.pathsep}"
        cache = work / "cache"
        cache.mkdir()
        env["TEXMFVAR"] = env["TEXMFCACHE"] = str(cache)
        (work / "installed-systems.tex").write_text(
            r"\global\advance\InstalledScoreEffects1 \noindent\rule{60pt}{20pt}\par")
        for variant in resources["variants"]:
            (work / "independent.tex").write_text(
                r"""
\documentclass[variants={default,lyric,charango,bassclef}]{ulsbs-songbook}
""" + rf"\ulIfVariant{{{variant}}}{{\typeout{{INSTALLED:{variant}}}}}{{\errmessage{{Wrong identity}}}}"
                + r"""
\renewcommand\ulThisBookTitle{Installed final title}
\renewcommand\ulBookLyricVariantText{Installed lyric label}
\newcount\InstalledScoreEffects
\newcount\InstalledTranslationEffects
\newcount\InstalledExplanationEffects
\newcount\InstalledPassageEffects
\newcount\InstalledFeelerEffects
\newcount\InstalledKeyEffects
\newcount\InstalledGoodKeysEffects
\newcount\InstalledCommentEffects
\newcount\InstalledAuthorEffects
\newcount\InstalledOfferedEffects
\newcount\InstalledExtraEffects
\newskip\InstalledGlue
\newskip\InstalledExpectedGlue
\newcommand\InstalledCheckGlue[1]{%
  \begingroup
  \InstalledGlue=\ulColumnBottomGlue\relax\InstalledExpectedGlue=#1\relax
  \edef\Actual{\the\InstalledGlue}\edef\Expected{\the\InstalledExpectedGlue}%
  \ifx\Actual\Expected\else\errmessage{Installed bottom glue}\fi\endgroup}
\InstalledCheckGlue{0pt plus .5\textheight}
\AddToHook{ulsbs/stanza/start}{%
  \csname ifulsbs@intranslation\endcsname
    \InstalledExpectedGlue=\normalbaselineskip
  \else\InstalledExpectedGlue=\csname l__ulsbs_verse_nominal_skip\endcsname\fi
  \ifdim\baselineskip=\InstalledExpectedGlue
  \else\errmessage{Installed lyric-only leading}\fi}
\newcommand\InstalledRepeatProbe{%
 \setbox0=\hbox{\lrep\rrep}%
 \directlua{
  local colons = 0
  local function walk(head)
   for n in node.traverse(head) do
    if n.id == node.id('glyph') and n.char == 58 then colons = colons + 1 end
    if n.id == node.id('hlist') or n.id == node.id('vlist') then walk(n.list) end
   end
  end
  walk(tex.box[0].list)
  assert(colons == \ifulShowChords 4\else 2\fi, 'installed effective repeat dots')
 }}
\renewcommand\ulPreludeTextKey{\global\advance\InstalledKeyEffects1 Key:}
\renewcommand\ulPreludeTextGoodKeysAlone{\global\advance\InstalledGoodKeysEffects1 Good:}
\let\InstalledMakePrelude\ulMakePrelude
\renewcommand\ulMakePrelude{%
  % Instrument display after metadata/index/multikey capture, outside the body box.
  \ifnum\value{ulSongNumber}=1
    \def\ulSongAuthors{\global\advance\InstalledAuthorEffects1 Installed author}%
    \def\ulOfferedTo{\global\advance\InstalledOfferedEffects1 Installed recipient}%
    \def\ulExtraInfo{\global\advance\InstalledExtraEffects1 Installed extra info}%
  \fi
  \InstalledMakePrelude}
% The bass-clef selector also exercises author denial of independent prose.
\ulIfVariant{bassclef}{\ulShowTranslation{false}\ulShowExplanation{false}\ulShowPassage{false}\ulShowFeeler{false}}{}
\ulIfVariant{bassclef}{\ulShowAuthors{false}\ulShowOfferedTo{false}\ulShowExtraInfo{false}}{}
\ulIfVariant{bassclef}{\ulShowTags{false}\ulShowPhase{false}\ulShowPhaseInToc{false}}{}
\ulIfVariant{bassclef}{\ulShowImageInChapterName{false}\ulShowImageOnChapterFrontPage{false}}{}
\begin{document}\makeatletter
\typeout{INSTALLED-LABEL:\ulsbs@variantlabel}
\InstalledCheckGlue{0pt plus .5\textheight}
{\chordsoff\notesoff\beatsoff
 \InstalledCheckGlue{0pt plus .5\textheight}}
{\renewcommand\ulColumnBottomGlue{3pt plus 19pt minus 2pt}
 \chordsoff\InstalledCheckGlue{3pt plus 19pt minus 2pt}
 {\ulSeparateVerses\InstalledCheckGlue{0pt plus 1fil}}
 \InstalledCheckGlue{3pt plus 19pt minus 2pt}}
\InstalledCheckGlue{0pt plus .5\textheight}
\ulLocalShow{imageinchaptername}{true}\ulLocalShow{imageonchapterfrontpage}{true}
\typeout{INSTALLED-CHAPTER-ART:\ifulShowImageInChapterName on\else off\fi/\ifulShowImageOnChapterFrontPage on\else off\fi}
{\ulLocalShow{imageinchaptername}{false}\ulLocalShow{imageonchapterfrontpage}{false}
 \ulMainChapter{Installed hidden art}{blue}[must-not-be-read.png]}
\typeout{INSTALLED-CHAPTER-RESTORED:\ifulShowImageInChapterName on\else off\fi/\ifulShowImageOnChapterFrontPage on\else off\fi}
\iffalse\ifulShowImageInChapterName\else\ifulShowImageOnChapterFrontPage\fi\fi\else\typeout{INSTALLED-CHAPTER-SKIPPED:balanced}\fi
{\ulIfVariant{lyric}{\tiny}{\scriptsize}\edef\ExpectedBadgeSize{\f@size}%
 \color{black}\ulIfVariant{lyric}{\color{gray}}{}\edef\ExpectedBadgeColor{\current@color}%
 \color{black}\ulPreludeBadgeFont\ulPreludePhaseStyle
 \ifx\ExpectedBadgeSize\f@size\else\errmessage{Installed badge size}\fi
 \ifx\ExpectedBadgeColor\current@color\else\errmessage{Installed badge color}\fi}
\ulLocalShow{tags}{true}\ulLocalShow{phase}{true}\ulLocalShow{phaseintoc}{true}
\typeout{INSTALLED-BADGES:\ifulShowTags on\else off\fi/\ifulShowPhase on\else off\fi/\ifulShowPhaseInToc on\else off\fi}
{\ulLocalShow{tags}{false}\ulLocalShow{phase}{false}\ulLocalShow{phaseintoc}{false}
 \ifulShowPhaseInToc\errmessage{Lost TOC suppression}\fi
 % Bypass metadata ingestion; only display adapters promise opaque hiding.
 \def\ulTagList{\input{must-not-be-read.tex}\iftrue}
 \def\ulPhaseList{\input{must-not-be-read.tex}\iffalse}
  \ulLocalShow{key}{false}\ulLocalShow{goodkeys}{false}
  \renewcommand\ulPreludeBadgeFont{\errmessage{Hidden installed badge font executed}}
 \ExplSyntaxOn
 \setbox0=\hbox{\__ulsbs_song_badges:}
 \ExplSyntaxOff
 \ifdim\wd0=0pt\else\errmessage{Hidden badge width}\fi
 \ifdim\ht0=0pt\else\errmessage{Hidden badge height}\fi
 \ifdim\dp0=0pt\else\errmessage{Hidden badge depth}\fi}
\typeout{INSTALLED-BADGES-RESTORED:\ifulShowTags on\else off\fi/\ifulShowPhase on\else off\fi/\ifulShowPhaseInToc on\else off\fi}
\iffalse\ifulShowTags\else\ifulShowPhase\fi\ifulShowPhaseInToc\fi\fi\else\typeout{INSTALLED-BADGES-SKIPPED:balanced}\fi
\ulLocalShow{authors}{true}\ulLocalShow{offeredto}{true}\ulLocalShow{extrainfo}{true}
\typeout{INSTALLED-TEXT:\ifulShowAuthors on\else off\fi/\ifulShowOfferedTo on\else off\fi/\ifulShowExtraInfo on\else off\fi}
{\ulLocalShow{authors}{false}\ulLocalShow{offeredto}{false}\ulLocalShow{extrainfo}{false}
 \def\ulSongAuthors{\input{must-not-be-read.tex}\iftrue}
 \renewcommand\ulOfferedTo{\iftrue}\renewcommand\ulExtraInfo{\iffalse}
 \setbox0=\vbox{\ulExtendPrelude}
 \ifdim\wd0=0pt\else\errmessage{Hidden text width}\fi
 \ifdim\ht0=0pt\else\errmessage{Hidden text height}\fi
 \ifdim\dp0=0pt\else\errmessage{Hidden text depth}\fi}
\typeout{INSTALLED-TEXT-RESTORED:\ifulShowAuthors on\else off\fi/\ifulShowOfferedTo on\else off\fi/\ifulShowExtraInfo on\else off\fi}
\iffalse\ifulShowAuthors\else\ifulShowOfferedTo\fi\ifulShowExtraInfo\fi\fi\else\typeout{INSTALLED-TEXT-SKIPPED:balanced}\fi
\ulLocalShow{musiccomments}{true}
\typeout{INSTALLED-COMMENTS:\ifulShowMusicComments on\else off\fi}
{\ulLocalShow{musiccomments}{false}
 \setbox0=\vbox{%
  \musicnote{\input{must-not-be-read.tex}\iftrue}%
  \musicnoteforprev{\iftrue}%
  \musicnotefornext{\iftrue}*%
  \musicnotefornext{\iffalse}%
  \musicnotemiddle{\iffalse}}%
 \ifdim\wd0=0pt\else\errmessage{Hidden comment width}\fi
 \ifdim\ht0=0pt\else\errmessage{Hidden comment height}\fi
 \ifdim\dp0=0pt\else\errmessage{Hidden comment depth}\fi}
\typeout{INSTALLED-COMMENTS-RESTORED:\ifulShowMusicComments on\else off\fi}
\iffalse\ifulShowMusicComments\else\fi\else\typeout{INSTALLED-COMMENTS-SKIPPED:balanced}\fi
\ulLocalShow{key}{true}\ulLocalShow{goodkeys}{true}
\typeout{INSTALLED-KEYS:\ifulShowKey on\else off\fi/\ifulShowGoodKeys on\else off\fi}
{\ulLocalShow{key}{false}\ulLocalShow{goodkeys}{false}
 \ifulShowKey\errmessage{Lost local key suppression}\fi
 \ifulShowGoodKeys\errmessage{Lost local goodkeys suppression}\fi}
\typeout{INSTALLED-KEYS-RESTORED:\ifulShowKey on\else off\fi/\ifulShowGoodKeys on\else off\fi}
\iffalse\ifulShowKey\else\ifulShowGoodKeys\fi\fi\else\typeout{INSTALLED-KEYS-SKIPPED:balanced}\fi
\chordson\noteson\beatson
{\InstalledRepeatProbe
 {\chordsoff\InstalledRepeatProbe\notesoff\InstalledRepeatProbe\beatsoff\InstalledRepeatProbe}
 \InstalledRepeatProbe}
\typeout{INSTALLED-CHORDS:\ifulShowChords on\else off\fi}
\typeout{INSTALLED-NOTES:\ifulShowNotes on\else off\fi}
{\notesoff\ifulShowNotes\errmessage{Lost local pitch suppression}\fi}
\typeout{INSTALLED-NOTES-RESTORED:\ifulShowNotes on\else off\fi}
\typeout{INSTALLED-BEATS:\ifulShowBeats on\else off\fi}
{\beatsoff\ifulShowBeats\errmessage{Lost local beat suppression}\fi}
\typeout{INSTALLED-BEATS-RESTORED:\ifulShowBeats on\else off\fi}
\measureson
\typeout{INSTALLED-MEASURES:\ifulShowMeasures on\else off\fi}
{\ulLocalShow{measures}{false}\ifulShowMeasures\errmessage{Lost local measure suppression}\fi
 {\measureson\ifulShowMeasures\else\errmessage{Lost nested measure request}\fi}
 \ifulShowMeasures\errmessage{Lost nested measure restoration}\fi}
\typeout{INSTALLED-MEASURES-RESTORED:\ifulShowMeasures on\else off\fi}
\ulLocalShow{altchords}{true}
\typeout{INSTALLED-ALT:\ifulShowAltChords on\else off\fi}
{\ulLocalShow{altchords}{false}\ifulShowAltChords\errmessage{Lost alternate suppression}\fi
 \setbox0=\hbox{\altchords{\input{must-not-be-read.tex}\iftrue}%
   \ulsbs@altchordsid[\input{must-not-be-read.tex}\iftrue]{\iffalse}}
 \ifdim\wd0=0pt\else\errmessage{Hidden alternate width}\fi
 \ifdim\ht0=0pt\else\errmessage{Hidden alternate height}\fi
 \ifdim\dp0=0pt\else\errmessage{Hidden alternate depth}\fi}
\typeout{INSTALLED-ALT-RESTORED:\ifulShowAltChords on\else off\fi}
\iffalse\ifulShowAltChords\else\fi\else\typeout{INSTALLED-ALT-SKIPPED:balanced}\fi
\iffalse\ifulShowMeasures\else\fi\else\typeout{INSTALLED-MEASURES-SKIPPED:balanced}\fi
\ulLocalShow{scores}{true}
\typeout{INSTALLED-SCORES:\ifulShowLilypond on\else off\fi}
{\ulLocalShow{scores}{false}\ifulShowLilypond\errmessage{Lost local score suppression}\fi
 \begin{lilywrap}\input{must-not-be-read.tex}\iftrue\end{lilywrap}}
\typeout{INSTALLED-SCORES-RESTORED:\ifulShowLilypond on\else off\fi}
\ulIfMusical{\typeout{INSTALLED-MUSICAL:on}}{\typeout{INSTALLED-MUSICAL:off}}
{\chordsoff\notesoff\ulLocalShow{scores}{false}
 \ulIfMusical{\input{must-not-be-read.tex}\iftrue}{\typeout{INSTALLED-MUSICAL-MASKED:off}}
 {\ulLocalShow{scores}{true}
  \ulIfMusical{\typeout{INSTALLED-MUSICAL-SCORE:on}}{\typeout{INSTALLED-MUSICAL-SCORE:off}}}}
\ulIfMusical{\typeout{INSTALLED-MUSICAL-RESTORED:on}}{\typeout{INSTALLED-MUSICAL-RESTORED:off}}
\begin{ulSongs}{}\beginsong{Independent installed book}[id={installed},key={C},gk={D},tags={Installed tag},ph={Installed phase},by={Installed author},off={Installed recipient},ex={Installed extra info}]
\musicnotefornext{\global\advance\InstalledCommentEffects1 Installed next comment.}*
\beginverse*
{\measuresoff\meter{\input{must-not-be-read.tex}\iftrue}{\iffalse}\measurebar}
\meter{}{}
\lrep \[<* E>C]Installed annotation. \rrep
\altchords{\id[1]{Installed alternate}|C |\ac{2}{G}}
\endverse
\musicnote{\global\advance\InstalledCommentEffects1 Installed general comment.}
\musicnoteforprev{\global\advance\InstalledCommentEffects1 Installed previous comment.}
\musicnotemiddle{\global\advance\InstalledCommentEffects1 Installed middle comment.}
\begin{lilywrap}\input{installed-systems.tex}\end{lilywrap}
{\ulLocalShow{feeler}{false}
 \ifulShowFeeler\errmessage{Lost feeler suppression}\fi
 \setbox0=\vbox{\begin{feeler}
   \global\advance\InstalledFeelerEffects100
   \ulLocalShow{feeler}{true}\input{must-not-be-read.tex}\iftrue
 \end{feeler}}
 \ifdim\wd0=0pt\else\errmessage{Hidden feeler width}\fi
 \ifdim\ht0=0pt\else\errmessage{Hidden feeler height}\fi
 \ifdim\dp0=0pt\else\errmessage{Hidden feeler depth}\fi}
\ulLocalShow{feeler}{true}
\typeout{INSTALLED-FEELER:\ifulShowFeeler on\else off\fi}
\iffalse\ifulShowFeeler\else\fi\else\typeout{INSTALLED-FEELER-SKIPPED:balanced}\fi
\begin{feeler}\global\advance\InstalledFeelerEffects1 Installed inside feeler.\end{feeler}
{\translationoff
 \ifulShowTranslation\errmessage{Lost translation suppression}\fi
 \setbox0=\vbox{
\begin{translation}[PT]
\global\advance\InstalledTranslationEffects100
\translationon\input{must-not-be-read.tex}\iftrue } } {
\end{translation}
 }
 \ifdim\wd0=0pt\else\errmessage{Hidden translation width}\fi
 \ifdim\ht0=0pt\else\errmessage{Hidden translation height}\fi
 \ifdim\dp0=0pt\else\errmessage{Hidden translation depth}\fi}
\translationon
\typeout{INSTALLED-TRANSLATION:\ifulShowTranslation on\else off\fi}
\iffalse\ifulShowTranslation\else\fi\else\typeout{INSTALLED-TRANSLATION-SKIPPED:balanced}\fi
\begin{translation}[EN]
\global\advance\InstalledTranslationEffects1
Installed translation.
\end{translation}
{\ulLocalShow{explanation}{false}
 \ifulShowExplanation\errmessage{Lost explanation suppression}\fi
 \setbox0=\vbox{
\begin{explanation}[PT]
\global\advance\InstalledExplanationEffects100
\ulLocalShow{explanation}{true}\input{must-not-be-read.tex}\iftrue } } {
\end{explanation}
 }
 \ifdim\wd0=0pt\else\errmessage{Hidden explanation width}\fi
 \ifdim\ht0=0pt\else\errmessage{Hidden explanation height}\fi
 \ifdim\dp0=0pt\else\errmessage{Hidden explanation depth}\fi}
\ulLocalShow{explanation}{true}
\typeout{INSTALLED-EXPLANATION:\ifulShowExplanation on\else off\fi}
\iffalse\ifulShowExplanation\else\fi\else\typeout{INSTALLED-EXPLANATION-SKIPPED:balanced}\fi
{\renewcommand\ulExplanationLanguagesToSkip{PT}
\begin{explanation}[PT]
\input{must-not-be-read.tex}\iftrue } } {
\end{explanation}
}
\begin{explanation}[EN]
\global\advance\InstalledExplanationEffects1
Installed explanation.
\end{explanation}
{\ulLocalShow{passage}{false}
 \ifulShowPassage\errmessage{Lost passage suppression}\fi
 \setbox0=\vbox{
\begin{passage}*[PT]{Hidden title}
\global\advance\InstalledPassageEffects100
\ulLocalShow{passage}{true}\input{must-not-be-read.tex}\iftrue } } {
\end{passage}
 }
 \ifdim\wd0=0pt\else\errmessage{Hidden passage width}\fi
 \ifdim\ht0=0pt\else\errmessage{Hidden passage height}\fi
 \ifdim\dp0=0pt\else\errmessage{Hidden passage depth}\fi}
\ulLocalShow{passage}{true}
\typeout{INSTALLED-PASSAGE:\ifulShowPassage on\else off\fi}
\iffalse\ifulShowPassage\else\fi\else\typeout{INSTALLED-PASSAGE-SKIPPED:balanced}\fi
{\renewcommand\ulPassageLanguagesToSkip{PT}
\begin{passage}[PT]{Hidden language}
\input{must-not-be-read.tex}\iftrue } } {
\end{passage}
}
\begin{passage}[EN]{Inside passage}
\global\advance\InstalledPassageEffects1 Installed inside passage.
\end{passage}
\endsong
\begin{intersong}
\begin{feeler}\global\advance\InstalledFeelerEffects1 Installed intersong feeler.\end{feeler}
\end{intersong}
{\ulLocalShow{key}{false}\ulLocalShow{goodkeys}{false}
 \beginsong{Installed hidden badges}[id={hidden-keys},key={C},gk={D}]
 \beginverse*No badges.\endverse\endsong}
\end{ulSongs}
\typeout{INSTALLED-KEY-EFFECTS:\the\InstalledKeyEffects}
\typeout{INSTALLED-GOODKEYS-EFFECTS:\the\InstalledGoodKeysEffects}
\typeout{INSTALLED-TEXT-EFFECTS:\the\InstalledAuthorEffects/\the\InstalledOfferedEffects/\the\InstalledExtraEffects}
\begin{passage}*{Outside passage}
\global\advance\InstalledPassageEffects1 Installed outside passage.
\end{passage}
\typeout{INSTALLED-SCORE-EFFECTS:\the\InstalledScoreEffects}
\typeout{INSTALLED-TRANSLATION-EFFECTS:\the\InstalledTranslationEffects}
\typeout{INSTALLED-EXPLANATION-EFFECTS:\the\InstalledExplanationEffects}
\typeout{INSTALLED-PASSAGE-EFFECTS:\the\InstalledPassageEffects}
\typeout{INSTALLED-FEELER-EFFECTS:\the\InstalledFeelerEffects}
\typeout{INSTALLED-COMMENT-EFFECTS:\the\InstalledCommentEffects}
\end{document}
"""
            )
            generated = subprocess.run(
                [sys.executable, "-I", "-c", r"""
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from ulsbs import variants
from ulsbs.config import Config
from ulsbs.engine_assets import EngineAssets
from ulsbs.jobs import build_job_queue
from ulsbs.lilypond_score_cache import audit_assets
from ulsbs.pipeline import make_variant_tex, prepare_compile_dir
from ulsbs.variants import available_variants
source = Path(sys.argv[2])
variant = sys.argv[3]
assert available_variants(source.read_text()) == ('default', 'lyric', 'charango', 'bassclef')
cfg = Config(songbooks=(source,), variants=(variant,),
             runtime=SimpleNamespace(project_paths=SimpleNamespace(project_root=source.parent), in_container=False))
jobs = build_job_queue(cfg)
assert [(job.variant, job.multikey) for job in jobs] == [(variant, False)]
job = jobs[0]
prepare_compile_dir(None, EngineAssets(), cfg, job)
output = make_variant_tex(job, cfg)
ly = job.compile_dir / 'ulsbs-assets/ly'
assert all(trusted for _, _, trusted in audit_assets([ly]))
head = (ly / 'ulsbs-internal-common-head.ly').read_text()
assert ('ul-chosen-tuning = #ul-charango-tuning' in head) == (variants.VARIANTS[variant].score_recipe == 'charango')
with EngineAssets().ly_dir() as original:
    for tail in original.glob('ulsbs-include-tail*_bassclef.ly'):
        plain = tail.name.replace('_bassclef', '')
        expected = tail if variants.VARIANTS[variant].score_recipe == 'bassclef' else original / plain
        assert (ly / plain).read_bytes() == expected.read_bytes()
if variant == 'default':
    registry = dict(variants.VARIANTS)
    registry[variant] = replace(registry[variant], score_recipe='charango')
    with patch.object(variants, 'VARIANTS', registry):
        prepare_compile_dir(None, EngineAssets(), cfg, job)
        make_variant_tex(job, cfg)
        assert 'ul-chosen-tuning = #ul-charango-tuning' in (ly / 'ulsbs-internal-common-head.ly').read_text()
        assert all(trusted for _, _, trusted in audit_assets([ly]))
    prepare_compile_dir(None, EngineAssets(), cfg, job)
    output = make_variant_tex(job, cfg)
text = output.read_text()
assert text.endswith(source.read_text())
if variant == 'default':
    assert r'\ulBuildVariant' not in text
else:
    assert text.index(r'\def\ulBuildVariant{' + variant + '}') < text.index(r'\documentclass')
print(output)
""", str(library), str(work / "independent.tex"), variant],
                cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=False, timeout=30,
            )
            self.check.assertEqual(generated.returncode, 0, generated.stdout)
            entry = Path(generated.stdout.strip())
            result = subprocess.run(
                ["lualatex", "-interaction=nonstopmode", "-halt-on-error", str(entry)],
                cwd=work, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=False, timeout=120,
            )
            self.check.assertEqual(result.returncode, 0, result.stdout)
            self.check.assertIn(f"INSTALLED:{variant}", result.stdout)
            art = "off/off" if variant == "bassclef" else "on/on"
            self.check.assertIn(f"INSTALLED-CHAPTER-ART:{art}", result.stdout)
            self.check.assertIn(f"INSTALLED-CHAPTER-RESTORED:{art}", result.stdout)
            self.check.assertIn("INSTALLED-CHAPTER-SKIPPED:balanced", result.stdout)
            text = "off/off/off" if variant == "bassclef" else "on/on/on"
            self.check.assertIn(f"INSTALLED-BADGES:{text}", result.stdout)
            self.check.assertIn(f"INSTALLED-BADGES-RESTORED:{text}", result.stdout)
            self.check.assertIn("INSTALLED-BADGES-SKIPPED:balanced", result.stdout)
            self.check.assertIn(f"INSTALLED-TEXT:{text}", result.stdout)
            self.check.assertIn(f"INSTALLED-TEXT-RESTORED:{text}", result.stdout)
            self.check.assertIn("INSTALLED-TEXT-SKIPPED:balanced", result.stdout)
            effects = "0/0/0" if variant == "bassclef" else "1/1/1"
            self.check.assertIn(f"INSTALLED-TEXT-EFFECTS:{effects}", result.stdout)
            comments = "off" if variant == "lyric" else "on"
            self.check.assertIn(f"INSTALLED-COMMENTS:{comments}", result.stdout)
            self.check.assertIn(f"INSTALLED-COMMENTS-RESTORED:{comments}", result.stdout)
            self.check.assertIn("INSTALLED-COMMENTS-SKIPPED:balanced", result.stdout)
            self.check.assertIn(f"INSTALLED-COMMENT-EFFECTS:{4 * int(comments == 'on')}", result.stdout)
            keys = "off" if variant == "lyric" else "on"
            self.check.assertIn(f"INSTALLED-KEYS:{keys}/{keys}", result.stdout)
            self.check.assertIn(f"INSTALLED-KEYS-RESTORED:{keys}/{keys}", result.stdout)
            self.check.assertIn("INSTALLED-KEYS-SKIPPED:balanced", result.stdout)
            self.check.assertIn(f"INSTALLED-KEY-EFFECTS:{int(keys == 'on')}", result.stdout)
            self.check.assertIn(f"INSTALLED-GOODKEYS-EFFECTS:{int(keys == 'on')}", result.stdout)
            chords = "on" if variant in ("default", "charango") else "off"
            self.check.assertIn(f"INSTALLED-CHORDS:{chords}", result.stdout)
            self.check.assertIn(f"INSTALLED-NOTES:{chords}", result.stdout)
            self.check.assertIn(f"INSTALLED-NOTES-RESTORED:{chords}", result.stdout)
            self.check.assertIn(f"INSTALLED-BEATS:{chords}", result.stdout)
            self.check.assertIn(f"INSTALLED-BEATS-RESTORED:{chords}", result.stdout)
            self.check.assertIn("INSTALLED-MEASURES:on", result.stdout)
            self.check.assertIn("INSTALLED-MEASURES-RESTORED:on", result.stdout)
            self.check.assertIn(f"INSTALLED-ALT:{chords}", result.stdout)
            self.check.assertIn(f"INSTALLED-ALT-RESTORED:{chords}", result.stdout)
            self.check.assertIn("INSTALLED-ALT-SKIPPED:balanced", result.stdout)
            self.check.assertIn("INSTALLED-MEASURES-SKIPPED:balanced", result.stdout)
            scores = "off" if variant == "lyric" else "on"
            self.check.assertIn(f"INSTALLED-SCORES:{scores}", result.stdout)
            self.check.assertIn(f"INSTALLED-SCORES-RESTORED:{scores}", result.stdout)
            self.check.assertIn(f"INSTALLED-SCORE-EFFECTS:{int(scores == 'on')}", result.stdout)
            self.check.assertIn(f"INSTALLED-TRANSLATION:{'off' if variant == 'bassclef' else 'on'}", result.stdout)
            self.check.assertIn("INSTALLED-TRANSLATION-SKIPPED:balanced", result.stdout)
            self.check.assertIn(f"INSTALLED-TRANSLATION-EFFECTS:{int(variant != 'bassclef')}", result.stdout)
            self.check.assertIn(f"INSTALLED-EXPLANATION:{'off' if variant == 'bassclef' else 'on'}", result.stdout)
            self.check.assertIn("INSTALLED-EXPLANATION-SKIPPED:balanced", result.stdout)
            self.check.assertIn(f"INSTALLED-EXPLANATION-EFFECTS:{int(variant != 'bassclef')}", result.stdout)
            self.check.assertIn(f"INSTALLED-PASSAGE:{'off' if variant == 'bassclef' else 'on'}", result.stdout)
            self.check.assertIn("INSTALLED-PASSAGE-SKIPPED:balanced", result.stdout)
            self.check.assertIn(f"INSTALLED-PASSAGE-EFFECTS:{2 * int(variant != 'bassclef')}", result.stdout)
            self.check.assertIn(f"INSTALLED-FEELER:{'off' if variant == 'bassclef' else 'on'}", result.stdout)
            self.check.assertIn("INSTALLED-FEELER-SKIPPED:balanced", result.stdout)
            self.check.assertIn(f"INSTALLED-FEELER-EFFECTS:{2 * int(variant != 'bassclef')}", result.stdout)
            self.check.assertIn(f"INSTALLED-MUSICAL:{scores}", result.stdout)
            self.check.assertIn("INSTALLED-MUSICAL-MASKED:off", result.stdout)
            self.check.assertIn(f"INSTALLED-MUSICAL-SCORE:{scores}", result.stdout)
            self.check.assertIn(f"INSTALLED-MUSICAL-RESTORED:{scores}", result.stdout)
            import io
            import pikepdf

            with pikepdf.open(io.BytesIO((work / (entry.stem + ".pdf")).read_bytes())) as pdf:
                suffix = {"default": "", "lyric": " (Installed lyric label)",
                          "charango": " (for charango)", "bassclef": " (with bass clef)"}[variant]
                self.check.assertEqual(str(pdf.docinfo.Title), "Installed final title" + suffix)

        # Installed compiler + score-only bass layers.
        # These prepared vector systems test inclusion, not external engraving.
        with pikepdf.Pdf.new() as graphic:
            page = graphic.add_blank_page(page_size=(60, 20))
            page.Contents = pikepdf.Stream(graphic, b"0 0 60 20 re f\n")
            graphic.save(work / "installed-score.pdf")
        for enabled in (True, False):
            source = work / "layer-book.tex"
            source.write_text(
                ("" if enabled else r"\def\ulPdfTranspositionLayers{false}") + r"""
\documentclass[variants={default,lyric,bassclef}]{ulsbs-songbook}
\ulShowKey{false}
\begin{document}\makeatletter
\typeout{INSTALLED-LAYERS:\ifulsbs@pdflayers on\else off\fi}
\ifulShowChords\errmessage{Unexpected bass chord ink}\fi
\ifulShowNotes\errmessage{Unexpected bass pitch ink}\fi
\ulSongColumns{1}\ulSongPosition{0}
\begin{ulSongs}{}\beginsong{Installed score only}[id={installed-score},key={C}]
\begin{lilywrap}\ulScoreSystem{abcdef}{1}{installed-score.pdf}\end{lilywrap}
\endsong\end{ulSongs}\end{document}
""")
            generated = subprocess.run(
                [sys.executable, "-I", "-c", r"""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from ulsbs.config import Config
from ulsbs.engine_assets import EngineAssets
from ulsbs.jobs import build_job_queue, Job
from ulsbs.pipeline import make_variant_tex, prepare_compile_dir
source = Path(sys.argv[2])
cfg = Config(songbooks=(source,), variants=('bassclef',), multikey_books=True,
             multikey_lilypond_scores=True,
             runtime=SimpleNamespace(project_paths=SimpleNamespace(project_root=source.parent), in_container=False))
jobs = build_job_queue(cfg)
assert [(job.variant, job.multikey) for job in jobs] == [('bassclef', False), ('bassclef', True)]
job = jobs[1]
prepare_compile_dir(None, EngineAssets(), cfg, job)
output = make_variant_tex(job, cfg)
try:
    make_variant_tex(Job(source, source.stem, 'lyric', job.compile_dir, multikey=True), cfg)
except ValueError as error:
    assert 'does not support multikey' in str(error)
else:
    raise AssertionError('Installed compiler accepted lyric multikey')
print(output)
""", str(library), str(source)],
                cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=False, timeout=30,
            )
            self.check.assertEqual(generated.returncode, 0, generated.stdout)
            entry = Path(generated.stdout.strip())
            for pass_number in range(3):
                result = subprocess.run(
                    ["lualatex", *(["-draftmode"] if pass_number == 0 else []),
                     "-interaction=nonstopmode", "-halt-on-error", str(entry)],
                    cwd=work, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    check=False, timeout=120,
                )
                self.check.assertEqual(result.returncode, 0, result.stdout)
            self.check.assertIn(f"INSTALLED-LAYERS:{'on' if enabled else 'off'}", result.stdout)
            self.check.assertEqual("ocgx2.sty" in result.stdout, enabled)
            envelope = json.loads((work / f"{entry.stem}.ulsbs-multikey.json").read_text())
            self.check.assertIs(envelope["has_multikey_info"], enabled)
            if enabled:
                self.check.assertEqual(len(envelope["multikey_info"]["songs"]), 1)
            else:
                self.check.assertIsNone(envelope["multikey_info"])
            with pikepdf.open(work / f"{entry.stem}.pdf") as pdf:
                layers = pdf.Root.get("/OCProperties", {}).get("/OCGs", [])
                self.check.assertEqual({str(layer.Name) for layer in layers}, {
                    f"ulsbs:transpose:v1:id:installed-score:t{offset:02d}"
                    for offset in range(12)
                } if enabled else set())


if __name__ == "__main__":
    if sys.argv[1:] == ["--packaging-smoke"]:
        smoke = ModulePackagingSmoke()
        try:
            smoke.build()
            smoke.test_wheel_and_sdist_include_companions_and_license()
            smoke.test_installed_engine_assets_resolves_companions()
        finally:
            smoke.temporary.cleanup()
        print("Offline wheel/sdist/installed EngineAssets smoke passed")
    else:
        unittest.main()
