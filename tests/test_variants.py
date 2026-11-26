# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Named-variant registry and bounded main-source availability contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from importlib.resources import files
import io
from itertools import product
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ulsbs.variants import VARIANTS, available_variants, read_documentclass, validate_variant_names
from test_tex_integration import TEX_ASSETS, compile_fixture


# Expected effective chords, notes, and beats for an unmodified preset.
INLINE_PRESET = {
    "default": ("on", "on", "on"),
    "lyric": ("off", "off", "on"),
    "charango": ("on", "on", "on"),
    "bassclef": ("off", "off", "off"),
}


def book(options: str = "", class_name: str = "ulsbs-songbook") -> str:
    return rf"\documentclass[{options}]{{{class_name}}}"


class VariantRegistryTests(unittest.TestCase):
    def test_registered_contracts_and_assets(self) -> None:
        self.assertEqual(tuple(VARIANTS), ("default", "lyric", "charango", "bassclef"))
        self.assertEqual([v.filename_marker for v in VARIANTS.values()],
                         ["", "_LYRICS-ONLY", "_CHARANGO", "_BASSCLEF"])
        self.assertEqual([v.score_recipe for v in VARIANTS.values()],
                         ["default", "default", "charango", "bassclef"])
        for name, variant in VARIANTS.items():
            self.assertEqual(variant.name, name)
            self.assertEqual(variant.presentation, name)
            self.assertEqual(variant.editions, ("ordinary",) if name == "lyric"
                             else ("ordinary", "multikey"))
            if variant.preset:
                self.assertTrue((files("ulsbs") / "assets/tex" / variant.preset).is_file())

    def test_registry_and_records_are_immutable(self) -> None:
        with self.assertRaises(TypeError):
            VARIANTS["other"] = VARIANTS["default"]
        with self.assertRaises(FrozenInstanceError):
            VARIANTS["default"].name = "other"

    def test_subsets_do_not_require_or_add_default(self) -> None:
        self.assertEqual(validate_variant_names(" bassclef, lyric "), ("bassclef", "lyric"))
        self.assertEqual(validate_variant_names("lyric,default", require_default=True),
                         ("lyric", "default"))

    def test_invalid_lists_are_not_normalized_or_silently_dropped(self) -> None:
        for value in ("", " ", "default,", ",default", "default,,lyric", "lyrics",
                      "LYRIC", "default,other", "default,default", "default,lyric,lyric",
                      r"default,\chosen", "default;lyric", "default lyric", "{default}"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_variant_names(value)
        with self.assertRaisesRegex(ValueError, "include default"):
            validate_variant_names("lyric", require_default=True)

    @unittest.skipUnless(shutil.which("lualatex"), "LuaLaTeX not installed")
    def test_same_literal_records_can_be_consumed_by_tex(self) -> None:
        registry = files("ulsbs") / "assets/tex/ulsbs-variants.def.tex"
        with tempfile.TemporaryDirectory(prefix="ulsbs-variant-registry-") as temporary:
            work = Path(temporary)
            (work / "registry.tex").write_text(registry.read_text())
            (work / "probe.tex").write_text(
                "\\documentclass{article}\n"
                "\\def\\ulsbsVariantRecord#1#2#3#4#5#6{\\typeout{VARIANT:#1/#2/#3/#4/#5/#6}}\n"
                "\\input{registry.tex}\n\\begin{document}Probe\\end{document}\n"
            )
            cache = work / "cache"
            cache.mkdir()
            env = os.environ.copy()
            env["TEXMFVAR"] = env["TEXMFCACHE"] = str(cache)
            result = subprocess.run(
                ["lualatex", "-interaction=nonstopmode", "-halt-on-error", "probe.tex"],
                cwd=work, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                check=False, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            # TeX wraps log lines at max_print_line; the original log is authoritative.
            output = (work / "probe.log").read_text().replace("\n", "")
            for variant in VARIANTS.values():
                record = "/".join((variant.name, variant.preset, variant.score_recipe,
                                   variant.filename_marker, variant.presentation,
                                   ",".join(variant.editions)))
                self.assertIn("VARIANT:" + record, output)


@unittest.skipUnless(shutil.which("lualatex"), "LuaLaTeX not installed")
class TexVariantTests(unittest.TestCase):
    def compile(self, source, *, success=True, files=None, pdf=False):
        """Compile an independent book, never relying on parent consumer files."""
        result = compile_fixture(
            "source-effects", multikey=None, expect_success=success,
            files={"source-effects.tex": source.encode(), **(files or {})},
        )
        return result if pdf else result[0]

    def pdf_info(self, data):
        import pikepdf

        with pikepdf.open(io.BytesIO(data)) as document:
            return {str(key): str(value) for key, value in document.docinfo.items()}

    def test_chord_policy_requests_are_scoped_effective_and_not_identity(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                allowed = variant in ("default", "charango")
                source = (rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{CHORDS-#1:\ifulShowChords on\else off\fi}}
\newcount\ChordInk\def\ChordEffect{\global\advance\ChordInk1 C}
\Probe{preset}
\begin{document}
\Probe{body}
{\chordsoff\Probe{off}
 {\ulLocalShow{chords}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\chordson\Probe{on}
\iffalse\ifulShowChords\else\fi\else\typeout{SKIPPED:balanced}\fi
""" + rf"\ulIfVariant{{{variant}}}{{\typeout{{IDENTITY:unchanged}}}}{{\errmessage{{Changed identity}}}}"
                          + r"""
\typeout{INDEPENDENT:\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi}
\begin{ulSongs}{}\beginsong{Policy}[id={policy}]
\beginverse*
\[\ChordEffect]Scope.
{\chordsoff\[\ChordEffect]Hidden.}
\endverse\endsong\end{ulSongs}
\typeout{CHORD-INK:\the\ChordInk}
\end{document}
""")
                output = self.compile(source)
                for marker in ("preset", "body", "nested", "restored-book", "on"):
                    self.assertIn(f"CHORDS-{marker}:{'on' if allowed else 'off'}", output)
                for marker in ("off", "restored-off"):
                    self.assertIn(f"CHORDS-{marker}:off", output)
                _, notes, beats = INLINE_PRESET[variant]
                self.assertIn(f"INDEPENDENT:{notes}/{beats}/on", output)
                self.assertIn("SKIPPED:balanced", output)
                self.assertIn("IDENTITY:unchanged", output)
                self.assertIn(f"CHORD-INK:{int(allowed)}", output)
        # Book permission remains author-overridable in the preamble, on either
        # entry path; local requests in that preamble do not replace permission.
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            output = self.compile(entry + r"""
\ulShowChords{false}\chordson
\begin{document}
\ifulShowChords\errmessage{Leaked chord permission}\fi
Denied.\end{document}
""")
            self.assertNotIn("Leaked chord permission", output)

    def test_chord_policy_rejects_body_setters_and_invalid_local_inputs(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowChords{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowChords{true}}\begin{document}", "preamble-only"),
            (r"\ulShowChords{yes}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{chords}{yes}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{unknown}{true}\begin{document}", "Unknown local visibility feature"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                self.assertIn(diagnostic, " ".join(output.split()))

    def test_note_policy_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                allowed = variant in ("default", "charango")
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{NOTES-#1:\ifulShowNotes on\else off\fi}}
\Probe{preset}
\begin{document}
\Probe{body}
{\notesoff\Probe{off}
 {\ulLocalShow{notes}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\noteson\Probe{on}
\typeout{PRIMITIVE:\meaning\ifulShowNotes}
\iffalse\ifulShowNotes\else\ifulShowChords\fi\fi\else\typeout{SKIPPED:balanced}\fi
{\notesoff
 \typeout{INDEPENDENT:\ifulShowChords on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi}}
\ulIfVariant{""" + variant + r"""}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
Text.\end{document}
""")
                for marker in ("preset", "body", "nested", "restored-book", "on"):
                    self.assertIn(f"NOTES-{marker}:{'on' if allowed else 'off'}", output)
                for marker in ("off", "restored-off"):
                    self.assertIn(f"NOTES-{marker}:off", output)
                self.assertIn(r"PRIMITIVE:\if" + ("true" if allowed else "false"), output)
                chords, _, beats = INLINE_PRESET[variant]
                self.assertIn(f"INDEPENDENT:{chords}/{beats}/on", output)
                for marker in ("SKIPPED:balanced", "IDENTITY:unchanged"):
                    self.assertIn(marker, output)
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permission in ("true", "false"):
                output = self.compile(entry + rf"\ulShowNotes{{{permission}}}\notesoff" + r"""
\ifulShowNotes\errmessage{Lost preamble request}\fi
\begin{document}
{\noteson\typeout{RESTORE:\ifulShowNotes on\else off\fi}}
\ifulShowNotes\errmessage{Lost grouped restoration}\fi
Denied or restored.\end{document}
""")
                self.assertIn(f"RESTORE:{'on' if permission == 'true' else 'off'}", output)

    def test_note_policy_rejects_body_setters_and_invalid_values(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowNotes{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowNotes{true}}\begin{document}", "preamble-only"),
            (r"\ulShowNotes{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\value{true}\ulShowNotes{\value}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{notes}{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\value{true}\ulLocalShow{notes}{\value}\begin{document}", "Invalid boolean value"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                self.assertIn(diagnostic, " ".join(output.split()))

    def test_rejected_note_setters_do_not_change_permission_or_requests(self):
        for permission in ("true", "false"):
            output = self.compile(book() + rf"\ulShowNotes{{{permission}}}" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\ulShowNotes{invalid}\ulLocalShow{notes}{invalid}
\AtBeginDocument{\ulShowNotes{true}}
\begin{document}
\ulShowNotes{true}\ulShowNotes{false}\noteson
\typeout{UNCHANGED:\ifulShowNotes on\else off\fi;ERRORS:\the\Errors}
Text.\end{document}
""")
            self.assertIn(f"UNCHANGED:{'on' if permission == 'true' else 'off'};ERRORS:5", output)

    def test_beat_policy_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                chords, notes, beats = INLINE_PRESET[variant]
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{BEATS-#1:\ifulShowBeats on\else off\fi}}
\Probe{preset}
\begin{document}
\Probe{body}
{\beatsoff\Probe{off}
 {\ulLocalShow{beats}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\beatson\Probe{on}
\typeout{PRIMITIVE:\meaning\ifulShowBeats}
\iffalse\ifulShowBeats\else\ifulShowNotes\fi\fi\else\typeout{SKIPPED:balanced}\fi
{\beatsoff
 \typeout{INDEPENDENT:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowMeasures on\else off\fi}}
\ulIfVariant{""" + variant + r"""}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
Text.\end{document}
""")
                for marker in ("preset", "body", "nested", "restored-book", "on"):
                    self.assertIn(f"BEATS-{marker}:{beats}", output)
                for marker in ("off", "restored-off"):
                    self.assertIn(f"BEATS-{marker}:off", output)
                self.assertIn(r"PRIMITIVE:\if" + ("true" if beats == "on" else "false"), output)
                self.assertIn(f"INDEPENDENT:{chords}/{notes}/on", output)
                for marker in ("SKIPPED:balanced", "IDENTITY:unchanged"):
                    self.assertIn(marker, output)
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permission in ("true", "false"):
                output = self.compile(entry + rf"\ulShowBeats{{{permission}}}\beatsoff" + r"""
\ifulShowBeats\errmessage{Lost preamble request}\fi
\begin{document}
{\beatson\typeout{RESTORE:\ifulShowBeats on\else off\fi}}
\ifulShowBeats\errmessage{Lost grouped restoration}\fi
Denied or restored.\end{document}
""")
                self.assertIn(f"RESTORE:{'on' if permission == 'true' else 'off'}", output)

    def test_beat_policy_rejects_body_setters_and_invalid_values(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowBeats{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowBeats{true}}\begin{document}", "preamble-only"),
            (r"\ulShowBeats{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\value{true}\ulShowBeats{\value}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{beats}{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\value{true}\ulLocalShow{beats}{\value}\begin{document}", "Invalid boolean value"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                self.assertIn(diagnostic, " ".join(output.split()))

    def test_rejected_beat_setters_do_not_change_permission_or_requests(self):
        for permission in ("true", "false"):
            for request in ("true", "false"):
                output = self.compile(book() + rf"""
\ulShowBeats{{{permission}}}\ulLocalShow{{beats}}{{{request}}}
""" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\ulShowBeats{invalid}\ulLocalShow{beats}{invalid}
\AtBeginDocument{\ulShowBeats{true}}
\begin{document}
\ulShowBeats{true}\ulShowBeats{false}
\typeout{UNCHANGED:\ifulShowBeats on\else off\fi;ERRORS:\the\Errors}
\beatson\typeout{PERMISSION:\ifulShowBeats on\else off\fi}
Text.\end{document}
""")
                effective = "on" if permission == request == "true" else "off"
                self.assertIn(f"UNCHANGED:{effective};ERRORS:5", output)
                self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_measure_policy_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{MEASURES-#1:\ifulShowMeasures on\else off\fi}}
\Probe{preset}
\begin{document}
\Probe{body}
{\measuresoff\Probe{off}
 {\ulLocalShow{measures}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\measureson\Probe{on}
\typeout{PRIMITIVE:\meaning\ifulShowMeasures}
\iffalse\ifulShowMeasures\else\ifulShowNotes\fi\fi\else\typeout{SKIPPED:balanced}\fi
{\measuresoff
 \typeout{INDEPENDENT:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowLilypond on\else off\fi}}
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Local measure request}[key={C}]
\measuresoff\Probe{song-off}
\beginverse*
\measureson\Probe{verse-on}Text.
\endverse\Probe{after-verse}
\endsong\Probe{after-song}
\beginsong{Following song}[key={C}]\Probe{next-song}
\beginverse*Text.\endverse\endsong\end{ulSongs}
\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                for marker in ("preset", "body", "nested", "restored-book", "on",
                               "verse-on", "after-song", "next-song"):
                    self.assertIn(f"MEASURES-{marker}:on", output)
                for marker in ("off", "restored-off", "song-off", "after-verse"):
                    self.assertIn(f"MEASURES-{marker}:off", output)
                inline = "/".join(INLINE_PRESET[variant])
                scores = "off" if variant == "lyric" else "on"
                self.assertIn(f"INDEPENDENT:{inline}/{scores}", output)
                for marker in (r"PRIMITIVE:\iftrue", "SKIPPED:balanced",
                               "IDENTITY:unchanged"):
                    self.assertIn(marker, output)

    def test_measure_policy_denial_and_musical_exclusion_on_both_entry_paths(self):
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permission in ("true", "false"):
                with self.subTest(entry=entry, permission=permission):
                    output = self.compile(entry + rf"\ulShowMeasures{{{permission}}}" + r"""
\measuresoff
\ifulShowMeasures\errmessage{Lost preamble request}\fi
\begin{document}
{\measureson\typeout{RESTORE:\ifulShowMeasures on\else off\fi}}
\ifulShowMeasures\errmessage{Lost grouped restoration}\fi
\measureson
\chordsoff\notesoff\beatsoff\ulLocalShow{scores}{false}
\ulIfMusical{\errmessage{Measures made musical}}{\typeout{MEASURES-ONLY:nonmusical}}
\iffalse\ifulShowMeasures\else\fi\else\typeout{SKIPPED:balanced}\fi
\typeout{PRIMITIVE:\meaning\ifulShowMeasures}
\begin{ulSongs}{}\beginsong{Measure permission}[key={C}]
\beginverse*\measuresoff
{\ulLocalShow{measures}{true}\typeout{VERSE-ON:\ifulShowMeasures on\else off\fi}}
Text.\endverse\endsong\end{ulSongs}
Text.\end{document}
""")
                    state = "on" if permission == "true" else "off"
                    self.assertIn(f"RESTORE:{state}", output)
                    self.assertIn(f"VERSE-ON:{state}", output)
                    self.assertIn(r"PRIMITIVE:\if" + permission, output)
                    self.assertIn("MEASURES-ONLY:nonmusical", output)
                    self.assertIn("SKIPPED:balanced", output)

    def test_measure_policy_rejects_body_setters_and_invalid_values(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowMeasures{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowMeasures{true}}\begin{document}", "preamble-only"),
            (r"\ulShowMeasures{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\value{true}\ulShowMeasures{\value}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{measures}{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\value{true}\ulLocalShow{measures}{\value}\begin{document}", "Invalid boolean value"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                self.assertIn(diagnostic, " ".join(output.split()))

    def test_rejected_measure_setters_do_not_change_permission_or_requests(self):
        for permission, request in product(("true", "false"), repeat=2):
            with self.subTest(permission=permission, request=request):
                output = self.compile(book() + rf"""
\ulShowMeasures{{{permission}}}\ulLocalShow{{measures}}{{{request}}}
""" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
\ulShowMeasures{invalid}\ulLocalShow{measures}{invalid}
\ulShowMeasures{\ComputedBoolean}\ulLocalShow{measures}{\ComputedBoolean}
\AtBeginDocument{\ulShowMeasures{true}}
\begin{document}
\ulShowMeasures{true}\ulShowMeasures{false}
\typeout{UNCHANGED:\ifulShowMeasures on\else off\fi;ERRORS:\the\Errors}
\measureson\typeout{PERMISSION:\ifulShowMeasures on\else off\fi}
Text.\end{document}
""")
                effective = "on" if permission == request == "true" else "off"
                self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_altchord_policy_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{ALT-#1:\ifulShowAltChords on\else off\fi}}
\Probe{preset}
\begin{document}
{\ulLocalShow{altchords}{false}\Probe{off}
 {\ulLocalShow{altchords}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\ulLocalShow{altchords}{true}\Probe{on}
\typeout{PRIMITIVE:\meaning\ifulShowAltChords}
\iffalse\ifulShowAltChords\else\ifulShowChords\fi\fi\else\typeout{SKIPPED:balanced}\fi
{\ulLocalShow{altchords}{false}
 \typeout{INDEPENDENT:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi/\ifulShowLilypond on\else off\fi}}
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Alternate requests}[key={C}]
\ulLocalShow{altchords}{false}\Probe{song-off}
\beginverse*
\ulLocalShow{altchords}{true}\Probe{verse-on}Text.
\endverse\Probe{after-verse}
\endsong\Probe{after-song}
\beginsong{Following song}\Probe{next-song}
\beginverse*Text.\endverse\endsong\end{ulSongs}
\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                state = "on" if variant in ("default", "charango") else "off"
                for marker in ("preset", "nested", "restored-book", "on", "verse-on",
                               "after-song", "next-song"):
                    self.assertIn(f"ALT-{marker}:{state}", output)
                for marker in ("off", "restored-off", "song-off", "after-verse"):
                    self.assertIn(f"ALT-{marker}:off", output)
                inline = "/".join(INLINE_PRESET[variant])
                scores = "off" if variant == "lyric" else "on"
                self.assertIn(f"INDEPENDENT:{inline}/on/{scores}", output)
                for marker in (r"PRIMITIVE:\if" + ("true" if state == "on" else "false"),
                               "SKIPPED:balanced", "IDENTITY:unchanged"):
                    self.assertIn(marker, output)

    def test_altchord_permission_truth_table_on_both_entry_paths(self):
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permission in ("true", "false"):
                cases = []
                expected = []
                for request, chords in product(("true", "false"), repeat=2):
                    label = f"{request}-{chords}"
                    cases.append(r"{" + rf"\ulLocalShow{{altchords}}{{{request}}}"
                                 + rf"\ulLocalShow{{chords}}{{{chords}}}" + rf"""
\typeout{{ALT-{label}:\ifulShowAltChords on\else off\fi}}
\ulIfMusical{{\typeout{{MUSICAL-{label}:on}}}}{{\typeout{{MUSICAL-{label}:off}}}}
}}""")
                    expected.extend((f"ALT-{label}:" + ("on" if permission == request == "true" else "off"),
                                     f"MUSICAL-{label}:" + ("on" if chords == "true" else "off")))
                output = self.compile(entry + rf"\ulShowAltChords{{{permission}}}" + r"""
\ulLocalShow{altchords}{false}\ulShowAltChords{true}
\ifulShowAltChords\errmessage{Book setter erased request}\fi
""" + rf"\ulShowAltChords{{{permission}}}" + r"""
\ulShowNotes{false}\ulShowLilypond{false}
\begin{document}
""" + "\n".join(cases) + r"Text.\end{document}")
                for marker in expected:
                    self.assertIn(marker, output)

    def test_altchord_policy_rejects_invalid_and_frozen_setters(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowAltChords{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowAltChords{true}}\begin{document}", "preamble-only"),
            (r"\ulShowAltChords{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulShowAltChords{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{altchords}{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulLocalShow{altchords}{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                self.assertIn(diagnostic, " ".join(output.split()))
        for permission, request in product(("true", "false"), repeat=2):
            with self.subTest(permission=permission, request=request):
                output = self.compile(book() + rf"""
\ulShowAltChords{{{permission}}}\ulLocalShow{{altchords}}{{{request}}}
""" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
\ulShowAltChords{invalid}\ulLocalShow{altchords}{invalid}
\ulShowAltChords{\ComputedBoolean}\ulLocalShow{altchords}{\ComputedBoolean}
\AtBeginDocument{\ulShowAltChords{true}}
\begin{document}
\ulShowAltChords{true}\ulShowAltChords{false}
\typeout{UNCHANGED:\ifulShowAltChords on\else off\fi;ERRORS:\the\Errors}
\ulLocalShow{altchords}{true}\typeout{PERMISSION:\ifulShowAltChords on\else off\fi}
Text.\end{document}
""")
                effective = "on" if permission == request == "true" else "off"
                self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_chapter_image_policy_truth_tables_and_scope(self):
        features = (("imageinchaptername", "ImageInChapterName"),
                    ("imageonchapterfrontpage", "ImageOnChapterFrontPage"))
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permissions in product(("true", "false"), repeat=2):
                preamble = r"\ulShowChords{false}\ulShowNotes{false}\ulShowLilypond{false}"
                for (key, name), permission in zip(features, permissions, strict=True):
                    preamble += (rf"\ulLocalShow{{{key}}}{{false}}\ulShow{name}{{true}}"
                                 + rf"\ifulShow{name}\errmessage{{Setter erased request}}\fi"
                                 + rf"\ulShow{name}{{{permission}}}")
                cases, expected = [], []
                for number, requests in enumerate(product(("true", "false"), repeat=2)):
                    commands = ""
                    for (key, name), permission, request in zip(features, permissions, requests, strict=True):
                        commands += rf"\ulLocalShow{{{key}}}{{{request}}}"
                        commands += rf"\typeout{{ART-{number}-{key}:\ifulShow{name} on\else off\fi}}"
                        commands += rf"\typeout{{PRIMITIVE-{number}-{key}:\meaning\ifulShow{name}}}"
                        commands += rf"\iffalse\ifulShow{name}\else\fi\else\typeout{{SKIP-{number}-{key}:balanced}}\fi"
                        enabled = permission == request == "true"
                        expected.extend((f"ART-{number}-{key}:" + ("on" if enabled else "off"),
                                         f"PRIMITIVE-{number}-{key}:\\if" + ("true" if enabled else "false"),
                                         f"SKIP-{number}-{key}:balanced"))
                    commands += r"""
\ifulShowTags\else\errmessage{Changed tags}\fi
\ifulShowPhase\else\errmessage{Changed phase}\fi
\ifulShowPhaseInToc\else\errmessage{Changed TOC phase}\fi
\ifulShowMeasures\else\errmessage{Changed measures}\fi
\ifulShowBeats\else\errmessage{Changed beats}\fi
\ifulShowKey\else\errmessage{Changed key}\fi
\ifulShowGoodKeys\else\errmessage{Changed good keys}\fi
\ifulShowMusicComments\else\errmessage{Changed comments}\fi
\ifulShowAuthors\else\errmessage{Changed authors}\fi
\ifulShowOfferedTo\else\errmessage{Changed dedication}\fi
\ifulShowExtraInfo\else\errmessage{Changed extra info}\fi
\ifulShowTranslation\else\errmessage{Changed translation}\fi
\ifulShowExplanation\else\errmessage{Changed explanation}\fi
\ifulShowPassage\else\errmessage{Changed passage}\fi
\ifulShowFeeler\else\errmessage{Changed feeler}\fi
\ulIfMusical{\errmessage{Artwork made musical}}{}
"""
                    cases.append("{" + commands + "}")
                source = entry + preamble + r"\begin{document}" + "\n".join(cases)
                for (key, name), permission in zip(features, permissions, strict=True):
                    source += (rf"\ifulShow{name}\errmessage{{Lost grouped request}}\fi"
                               + "{" + rf"\ulLocalShow{{{key}}}{{true}}"
                               + "{" + rf"\ulLocalShow{{{key}}}{{false}}"
                               + rf"\ifulShow{name}\errmessage{{Nested off failed}}\fi" + "}"
                               + rf"\typeout{{RESTORED-{key}:\ifulShow{name} on\else off\fi}}" + "}")
                    expected.append(f"RESTORED-{key}:" + ("on" if permission == "true" else "off"))
                output = self.compile(source + r"Text.\end{document}")
                for marker in expected:
                    self.assertIn(marker, output.replace("\n", ""))

    def test_chapter_image_presets_preserve_both_authored_layers(self):
        features = (("imageinchaptername", "ImageInChapterName"),
                    ("imageonchapterfrontpage", "ImageOnChapterFrontPage"))
        middle = rb"""\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{art-middle}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{ulsbs-songbook}}
\ProcessOptions\relax
\LoadClass{ulsbs-songbook}
"""
        outer = rb"""\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{art-outer}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{art-middle}}
\ProcessOptions\relax
\LoadClass{art-middle}
\AtEndOfClass{\ulShowImageInChapterName{false}\ulLocalShow{imageinchaptername}{false}}
\AtEndOfClass{\ulShowImageOnChapterFrontPage{false}\ulLocalShow{imageonchapterfrontpage}{false}}
"""
        for variant in VARIANTS:
            selector = rf"\def\ulBuildVariant{{{variant}}}"
            options = "variants={default,lyric,charango,bassclef}"
            with self.subTest(variant=variant, layers="defaults"):
                output = self.compile(selector + book(options) + r"""
\typeout{ART-DEFAULT:\ifulShowImageInChapterName on\else off\fi/\ifulShowImageOnChapterFrontPage on\else off\fi}
\begin{document}\makeatletter
\typeout{ART-BODY:\ifulShowImageInChapterName on\else off\fi/\ifulShowImageOnChapterFrontPage on\else off\fi}
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
Text.\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                for marker in ("ART-DEFAULT:on/on", "ART-BODY:on/on", "IDENTITY:unchanged"):
                    self.assertIn(marker, output)
            source = selector + book(options, "art-outer")
            for key, name in features:
                source += (rf"\ifulShow{name}\errmessage{{Preset erased class denial}}\fi"
                           + "{" + rf"\ulLocalShow{{{key}}}{{true}}"
                           + rf"\ifulShow{name}\errmessage{{Preset erased class permission}}\fi" + "}"
                           + rf"\ulShow{name}{{true}}\ifulShow{name}\errmessage{{Preset erased class request}}\fi"
                           + rf"\ulLocalShow{{{key}}}{{true}}\ifulShow{name}\else\errmessage{{Author restore failed}}\fi")
            source += r"""
\begin{document}
\typeout{AUTHOR-BODY:\ifulShowImageInChapterName on\else off\fi/\ifulShowImageOnChapterFrontPage on\else off\fi}
Text.\end{document}
"""
            with self.subTest(variant=variant, layers="nested-class"):
                output = self.compile(source, files={"art-middle.cls": middle, "art-outer.cls": outer})
                self.assertIn("AUTHOR-BODY:on/on", output)
        output = self.compile(r"\documentclass{book}\usepackage{ulsbs}" + r"""
\begin{document}
\typeout{PACKAGE-DEFAULT:\ifulShowImageInChapterName on\else off\fi/\ifulShowImageOnChapterFrontPage on\else off\fi}
Text.\end{document}
""")
        self.assertIn("PACKAGE-DEFAULT:on/on", output)

    def test_chapter_image_invalid_and_frozen_setter_recoveries(self):
        for key, name in (("imageinchaptername", "ImageInChapterName"),
                          ("imageonchapterfrontpage", "ImageOnChapterFrontPage")):
            setter, local, predicate = rf"\ulShow{name}", rf"\ulLocalShow{{{key}}}", rf"\ifulShow{name}"
            for commands, diagnostic in (
                (r"\begin{document}" + setter + "{false}", "preamble-only"),
                (r"\AtBeginDocument{" + setter + r"{true}}\begin{document}", "preamble-only"),
                (setter + r"{yes}\begin{document}", "Invalid boolean value"),
                (r"\def\ComputedBoolean{true}" + setter + r"{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
                (local + r"{yes}\begin{document}", "Invalid boolean value"),
                (r"\def\ComputedBoolean{true}" + local + r"{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
            ):
                with self.subTest(key=key, commands=commands):
                    output = self.compile(book() + commands + r"Text.\end{document}", success=False)
                    self.assertIn("".join(diagnostic.split()), "".join(output.split()))
            for permission, request in product(("true", "false"), repeat=2):
                with self.subTest(key=key, permission=permission, request=request):
                    output = self.compile(book() + setter + "{" + permission + "}"
                                          + local + "{" + request + "}" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
""" + setter + "{invalid}" + local + "{invalid}"
                        + setter + r"{\ComputedBoolean}" + local + r"{\ComputedBoolean}"
                        + r"\AtBeginDocument{" + setter + r"{true}}\begin{document}"
                        + setter + "{true}" + setter + "{false}"
                        + r"\typeout{UNCHANGED:" + predicate + r" on\else off\fi;ERRORS:\the\Errors}"
                        + local + "{true}" + r"\typeout{PERMISSION:" + predicate + r" on\else off\fi}"
                        + r"Text.\end{document}")
                    effective = "on" if permission == request == "true" else "off"
                    self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                    self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_chapter_image_hidden_sources_are_opaque_and_spacing_free(self):
        source = r"""
\renewcommand\ulChapterSymbol{\input{nonexistent-symbol-source}\iftrue}
\begin{document}\makeatletter
\ulMainChapter[Hidden symbol]{Hidden symbol front}{red}
\ulMainChapter[Hidden image]{Hidden image front}{blue}[nonexistent-chapter-image]
% The short-title box must contain neither the image nor its 1em separator.
\setbox0=\hbox{\ulsbs@shorttitlefull}
\setbox2=\hbox{\MakeUppercase{Hidden image}}
\ifdim\wd0=\wd2\else\errmessage{Phantom chapter-name spacing}\fi
% Isolate the front-page contribution from chapter/clearpage page machinery.
\RenewDocumentCommand\chapter{s o m}{}
\let\clearpage\relax\let\thispagestyle\@gobble
\newcount\SpacingEffects
\renewcommand\vspace{\global\advance\SpacingEffects1 \@ifstar\@gobble\@gobble}
\ulMainChapter*{Hidden front}{red}
\typeout{HIDDEN-FRONT-SPACING:\the\SpacingEffects}
\end{document}
"""
        for permission in (True, False):
            preamble = ""
            for key, name in (("imageinchaptername", "ImageInChapterName"),
                              ("imageonchapterfrontpage", "ImageOnChapterFrontPage")):
                preamble += (rf"\ulShow{name}{{{str(permission).lower()}}}"
                             + rf"\ulLocalShow{{{key}}}{{{str(not permission).lower()}}}")
            with self.subTest(permission=permission):
                output = self.compile(book() + preamble + source)
                self.assertIn("HIDDEN-FRONT-SPACING:0", output)

    def test_chapter_image_optional_image_rendering_and_source_effects(self):
        import pikepdf

        with pikepdf.new() as image:
            page = image.add_blank_page(page_size=(20, 20))
            page.Contents = image.make_stream(b"1 0 0 rg 0 0 20 20 re f\n")
            stream = io.BytesIO()
            image.save(stream)
            image_data = stream.getvalue()
        for name, front in product((True, False), repeat=2):
            with self.subTest(name=name, front=front):
                source = book() + rf"""
\ulLocalShow{{imageinchaptername}}{{{str(name).lower()}}}
\ulLocalShow{{imageonchapterfrontpage}}{{{str(front).lower()}}}
""" + r"""
\newcount\ImageEffects\newcount\FrontEffects\newcount\SymbolEffects
\AddToHook{cmd/includegraphics/before}{\global\advance\ImageEffects1 }
\AddToHook{cmd/imagecc/before}{\global\advance\FrontEffects1 }
\renewcommand\ulChapterSymbol{{\global\advance\SymbolEffects1 WrongSymbol}}
\begin{document}
\ulMainChapter[ImageShort]{ImageLong}{red}[chapter-art.pdf]
% Exercise the captured mark under the opposite current request.
""" + rf"\ulLocalShow{{imageinchaptername}}{{{str(not name).lower()}}}" + r"""
ImageBody.\newpage ImageSecondBody.\clearpage
\tableofcontents\clearpage
\typeout{IMAGE-EFFECTS:\the\ImageEffects}
\typeout{FRONT-EFFECTS:\the\FrontEffects}
\typeout{SYMBOL-EFFECTS:\the\SymbolEffects}
\end{document}
"""
                artifacts = {"source-effects.toc": None}
                output, data = compile_fixture(
                    "source-effects", multikey=None, passes=3,
                    files={"source-effects.tex": source.encode(), "chapter-art.pdf": image_data},
                    artifacts=artifacts,
                )
                toc = artifacts["source-effects.toc"].decode()
                self.assertEqual("chapter-art.pdf" in toc, name)
                self.assertNotIn("ifulShowImage", toc)
                self.assertIn(f"FRONT-EFFECTS:{int(front)}", output)
                self.assertIn("SYMBOL-EFFECTS:0", output)
                if name or front:
                    self.assertNotIn("IMAGE-EFFECTS:0", output)
                else:
                    self.assertIn("IMAGE-EFFECTS:0", output)
                with pikepdf.open(io.BytesIO(data)) as rendered:
                    has_art = any(bool(page.Resources.get("/XObject", {})) for page in rendered.pages)
                self.assertEqual(has_art, name or front)

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
    def test_chapter_image_rendering_captures_source_time_toc_and_headers(self):
        source = book() + r"""
\ulUppercaseShortChapterTitle{false}
\newcount\ArtEffects
\DeclareRobustCommand\ChapterArt[1]{\global\advance\ArtEffects1 Art#1}
\begin{document}
\renewcommand\ulChapterSymbol{{\ChapterArt{Alpha}}}
\ulLocalShow{imageinchaptername}{true}\ulLocalShow{imageonchapterfrontpage}{false}
\ulMainChapter[AlphaShort]{AlphaLong}{red}
\ulLocalShow{imageinchaptername}{false}
AlphaBody.\newpage AlphaSecondBody.\clearpage
\renewcommand\ulChapterSymbol{{\ChapterArt{Beta}}}
\ulLocalShow{imageinchaptername}{false}\ulLocalShow{imageonchapterfrontpage}{true}
\ulMainChapter[BetaShort]{BetaLong}{blue}
\ulLocalShow{imageinchaptername}{true}
BetaBody.\newpage BetaSecondBody.\clearpage
\ulLocalShow{imageinchaptername}{false}\ulLocalShow{imageonchapterfrontpage}{false}
\tableofcontents
\typeout{ART-EFFECTS:\the\ArtEffects}
\end{document}
"""
        artifacts = {"source-effects.toc": None, "source-effects.aux": None}
        output, data = compile_fixture(
            "source-effects", multikey=None, passes=3,
            files={"source-effects.tex": source.encode()}, artifacts=artifacts,
        )
        toc = artifacts["source-effects.toc"].decode()
        aux = artifacts["source-effects.aux"].decode()
        for material in (toc, aux):
            material = " ".join(material.split())
            self.assertNotIn("ifulShowImage", material)
            self.assertNotIn("imageinchaptername", material)
            self.assertIn(r"\ChapterArt {Alpha}", material)
            self.assertNotIn(r"\ChapterArt {Beta}", material)
        with tempfile.TemporaryDirectory(prefix="ulsbs-chapter-art-") as temporary:
            path = Path(temporary) / "chapters.pdf"
            path.write_bytes(data)
            pages = subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True).split("\f")
        alpha_front = next(page for page in pages if "AlphaLong" in page)
        beta_front = next(page for page in pages if "BetaLong" in page)
        self.assertNotIn("ArtAlpha", alpha_front)
        self.assertIn("ArtBeta", beta_front)
        alpha_header = next(page for page in pages if "AlphaSecondBody" in page)
        beta_header = next(page for page in pages if "BetaSecondBody" in page)
        self.assertIn("ArtAlpha", alpha_header)
        self.assertNotIn("ArtBeta", beta_header)
        toc_page = next(page for page in pages if "AlphaShort" in page and "BetaShort" in page)
        self.assertIn("ArtAlpha", toc_page)
        self.assertNotIn("ArtBeta", toc_page)
        self.assertNotIn("ART-EFFECTS:0", output)

    def test_tag_phase_requests_are_scoped_effective_and_independent(self):
        features = (("tags", "Tags"), ("phase", "Phase"), ("phaseintoc", "PhaseInToc"))
        off = "".join(rf"\ulLocalShow{{{key}}}{{false}}" for key, _ in features)
        on = "".join(rf"\ulLocalShow{{{key}}}{{true}}" for key, _ in features)
        probe = r"\newcommand\Probe[1]{\typeout{BADGE-#1:\ifulShowTags on\else off\fi/\ifulShowPhase on\else off\fi/\ifulShowPhaseInToc on\else off\fi}}"
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                source = rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + probe + r"""
\Probe{preset}
\begin{document}\makeatletter
""" + "{" + off + r"\Probe{off}{" + on + r"\Probe{nested}}\Probe{restored-off}}" + r"""
\Probe{restored-book}
\begin{ulSongs}{}
\beginsong{Badge requests}[key={C}]
""" + off + r"\Probe{song-off}\beginverse*" + on + r"""
\Probe{verse-on}Text.\endverse
\Probe{after-verse}\endsong\Probe{after-song}
\beginsong{Following song}\Probe{next-song}\endsong
\end{ulSongs}
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\end{document}
""".replace("{VARIANT}", "{" + variant + "}")
                output = self.compile(source)
                for marker in ("preset", "nested", "restored-book", "verse-on", "after-song", "next-song"):
                    self.assertIn(f"BADGE-{marker}:on/on/on", output)
                for marker in ("off", "restored-off", "song-off", "after-verse"):
                    self.assertIn(f"BADGE-{marker}:off/off/off", output)
                self.assertIn("IDENTITY:unchanged", output)

    def test_tag_phase_truth_tables_on_both_entry_paths(self):
        features = (("tags", "Tags"), ("phase", "Phase"), ("phaseintoc", "PhaseInToc"))
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permissions in product(("true", "false"), repeat=3):
                preamble = r"\ulShowChords{false}\ulShowNotes{false}\ulShowLilypond{false}"
                for (key, name), permission in zip(features, permissions, strict=True):
                    preamble += (rf"\ulLocalShow{{{key}}}{{false}}\ulShow{name}{{true}}"
                                 + rf"\ifulShow{name}\errmessage{{Setter erased request}}\fi"
                                 + rf"\ulShow{name}{{{permission}}}")
                cases, expected = [], []
                for number, requests in enumerate(product(("true", "false"), repeat=3)):
                    commands = ""
                    for (key, name), permission, request in zip(features, permissions, requests, strict=True):
                        commands += rf"\ulLocalShow{{{key}}}{{{request}}}"
                        commands += rf"\typeout{{BADGE-{number}-{key}:\ifulShow{name} on\else off\fi}}"
                        commands += rf"\typeout{{PRIMITIVE-{number}-{key}:\meaning\ifulShow{name}}}"
                        commands += rf"\iffalse\ifulShow{name}\else\fi\else\typeout{{SKIP-{number}-{key}:balanced}}\fi"
                        enabled = permission == request == "true"
                        expected.extend((f"BADGE-{number}-{key}:" + ("on" if enabled else "off"),
                                         f"PRIMITIVE-{number}-{key}:\\if" + ("true" if enabled else "false"),
                                         f"SKIP-{number}-{key}:balanced"))
                    commands += r"""
\ifulShowAuthors\else\errmessage{Changed authors}\fi
\ifulShowOfferedTo\else\errmessage{Changed dedication}\fi
\ifulShowExtraInfo\else\errmessage{Changed extra info}\fi
\ifulShowKey\else\errmessage{Changed key}\fi
\ifulShowGoodKeys\else\errmessage{Changed good keys}\fi
\ifulShowMusicComments\else\errmessage{Changed comments}\fi
\ifulShowTranslation\else\errmessage{Changed translation}\fi
\ifulShowExplanation\else\errmessage{Changed explanation}\fi
\ifulShowPassage\else\errmessage{Changed passage}\fi
\ifulShowFeeler\else\errmessage{Changed feeler}\fi
\ifulShowMeasures\else\errmessage{Changed measures}\fi
\ifulShowBeats\else\errmessage{Changed beats}\fi
\ulIfMusical{\errmessage{Badges made musical}}{}
"""
                    cases.append("{" + commands + "}")
                source = entry + preamble + r"\begin{document}" + "\n".join(cases)
                for _key, name in features:
                    source += rf"\ifulShow{name}\errmessage{{Lost grouped request}}\fi" + "\n"
                output = self.compile(source + r"Text.\end{document}")
                for marker in expected:
                    self.assertIn(marker, output)

    def test_tag_phase_policies_reject_invalid_and_frozen_setters(self):
        for key, name in (("tags", "Tags"), ("phase", "Phase"), ("phaseintoc", "PhaseInToc")):
            setter, local, predicate = rf"\ulShow{name}", rf"\ulLocalShow{{{key}}}", rf"\ifulShow{name}"
            for commands, diagnostic in (
                (r"\begin{document}" + setter + "{false}", "preamble-only"),
                (r"\AtBeginDocument{" + setter + r"{true}}\begin{document}", "preamble-only"),
                (setter + r"{yes}\begin{document}", "Invalid boolean value"),
                (r"\def\ComputedBoolean{true}" + setter + r"{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
                (local + r"{yes}\begin{document}", "Invalid boolean value"),
                (r"\def\ComputedBoolean{true}" + local + r"{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
            ):
                with self.subTest(key=key, commands=commands):
                    output = self.compile(book() + commands + r"Text.\end{document}", success=False)
                    self.assertIn("".join(diagnostic.split()), "".join(output.split()))
            for permission, request in product(("true", "false"), repeat=2):
                with self.subTest(key=key, permission=permission, request=request):
                    output = self.compile(book() + setter + "{" + permission + "}"
                                          + local + "{" + request + "}" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
""" + setter + "{invalid}" + local + "{invalid}"
                        + setter + r"{\ComputedBoolean}" + local + r"{\ComputedBoolean}"
                        + r"\AtBeginDocument{" + setter + r"{true}}\begin{document}"
                        + setter + "{true}" + setter + "{false}"
                        + r"\typeout{UNCHANGED:" + predicate + r" on\else off\fi;ERRORS:\the\Errors}"
                        + local + "{true}" + r"\typeout{PERMISSION:" + predicate + r" on\else off\fi}"
                        + r"Text.\end{document}")
                    effective = "on" if permission == request == "true" else "off"
                    self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                    self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_text_metadata_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{TEXT-#1:\ifulShowAuthors on\else off\fi/\ifulShowOfferedTo on\else off\fi/\ifulShowExtraInfo on\else off\fi}}
\newcommand\TextOff{\ulLocalShow{authors}{false}\ulLocalShow{offeredto}{false}\ulLocalShow{extrainfo}{false}}
\newcommand\TextOn{\ulLocalShow{authors}{true}\ulLocalShow{offeredto}{true}\ulLocalShow{extrainfo}{true}}
\Probe{preset}
\begin{document}\makeatletter
{\TextOff\Probe{off}{\TextOn\Probe{nested}}\Probe{restored-off}}
\Probe{restored-book}
\typeout{PRIMITIVES:\meaning\ifulShowAuthors/\meaning\ifulShowOfferedTo/\meaning\ifulShowExtraInfo}
\iffalse\ifulShowAuthors\else\ifulShowOfferedTo\fi\ifulShowExtraInfo\fi\fi\else\typeout{SKIPPED:balanced}\fi
{\TextOff
 \typeout{INDEPENDENT:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi/\ifulShowLilypond on\else off\fi/\ifulShowMusicComments on\else off\fi/\ifulShowKey on\else off\fi/\ifulShowGoodKeys on\else off\fi}
 \ifulShowTranslation\else\errmessage{Changed translation}\fi
 \ifulShowExplanation\else\errmessage{Changed explanation}\fi
 \ifulShowPassage\else\errmessage{Changed passage}\fi
 \ifulShowFeeler\else\errmessage{Changed feeler}\fi}
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Text requests}[key={C}]
\TextOff\Probe{song-off}
\beginverse*\TextOn\Probe{verse-on}Text.\endverse
\Probe{after-verse}\endsong\Probe{after-song}
\beginsong{Following song}\Probe{next-song}\endsong
\end{ulSongs}\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                for marker in ("preset", "nested", "restored-book", "verse-on",
                               "after-song", "next-song"):
                    self.assertIn(f"TEXT-{marker}:on/on/on", output)
                for marker in ("off", "restored-off", "song-off", "after-verse"):
                    self.assertIn(f"TEXT-{marker}:off/off/off", output)
                inline = "/".join(INLINE_PRESET[variant])
                scores = "off" if variant == "lyric" else "on"
                comments = keys = "off" if variant == "lyric" else "on"
                self.assertIn(f"INDEPENDENT:{inline}/on/{scores}/{comments}/{keys}/{keys}", output)
                for marker in (r"PRIMITIVES:\iftrue/\iftrue/\iftrue",
                               "SKIPPED:balanced", "IDENTITY:unchanged"):
                    self.assertIn(marker, output)

    def test_text_metadata_truth_tables_on_both_entry_paths(self):
        features = (("authors", "Authors"), ("offeredto", "OfferedTo"),
                    ("extrainfo", "ExtraInfo"))
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permissions in product(("true", "false"), repeat=3):
                preamble = ""
                for (key, name), permission in zip(features, permissions, strict=True):
                    preamble += (rf"\ulLocalShow{{{key}}}{{false}}\ulShow{name}{{true}}"
                                 + rf"\ifulShow{name}\errmessage{{Setter erased request}}\fi"
                                 + rf"\ulShow{name}{{{permission}}}")
                cases = []
                expected = []
                for number, requests in enumerate(product(("true", "false"), repeat=3)):
                    commands = ""
                    for (key, name), permission, request in zip(features, permissions, requests, strict=True):
                        commands += rf"\ulLocalShow{{{key}}}{{{request}}}"
                        commands += rf"\typeout{{TEXT-{number}-{key}:\ifulShow{name} on\else off\fi}}"
                        commands += rf"\typeout{{PRIMITIVE-{number}-{key}:\meaning\ifulShow{name}}}"
                        commands += rf"\iffalse\ifulShow{name}\else\fi\else\typeout{{SKIP-{number}-{key}:balanced}}\fi"
                        enabled = permission == request == "true"
                        expected.extend((f"TEXT-{number}-{key}:" + ("on" if enabled else "off"),
                                         f"PRIMITIVE-{number}-{key}:\\if" + ("true" if enabled else "false"),
                                         f"SKIP-{number}-{key}:balanced"))
                    cases.append("{" + commands + r"\ulIfMusical{\errmessage{Text made musical}}{}" + "}")
                source = entry + preamble + r"""
\ulShowChords{false}\ulShowNotes{false}\ulShowLilypond{false}
\begin{document}
""" + "\n".join(cases)
                for _key, name in features:
                    source += rf"\ifulShow{name}\errmessage{{Lost grouped request}}\fi" + "\n"
                output = self.compile(source + r"Text.\end{document}")
                for marker in expected:
                    self.assertIn(marker, output)

    def test_text_metadata_policies_reject_invalid_and_frozen_setters(self):
        for key, name in (("authors", "Authors"), ("offeredto", "OfferedTo"),
                          ("extrainfo", "ExtraInfo")):
            setter = rf"\ulShow{name}"
            local = rf"\ulLocalShow{{{key}}}"
            predicate = rf"\ifulShow{name}"
            for commands, diagnostic in (
                (r"\begin{document}" + setter + "{false}", "preamble-only"),
                (r"\AtBeginDocument{" + setter + r"{true}}\begin{document}", "preamble-only"),
                (setter + r"{yes}\begin{document}", "Invalid boolean value"),
                (r"\def\ComputedBoolean{true}" + setter + r"{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
                (local + r"{yes}\begin{document}", "Invalid boolean value"),
                (r"\def\ComputedBoolean{true}" + local + r"{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
            ):
                with self.subTest(key=key, commands=commands):
                    output = self.compile(book() + commands + r"Text.\end{document}", success=False)
                    self.assertIn("".join(diagnostic.split()), "".join(output.split()))
            for permission, request in product(("true", "false"), repeat=2):
                with self.subTest(key=key, permission=permission, request=request):
                    output = self.compile(book() + setter + "{" + permission + "}"
                                          + local + "{" + request + "}" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
""" + setter + "{invalid}" + local + "{invalid}"
                        + setter + r"{\ComputedBoolean}" + local + r"{\ComputedBoolean}"
                        + r"\AtBeginDocument{" + setter + r"{true}}\begin{document}"
                        + setter + "{true}" + setter + "{false}"
                        + r"\typeout{UNCHANGED:" + predicate + r" on\else off\fi;ERRORS:\the\Errors}"
                        + local + "{true}" + r"\typeout{PERMISSION:" + predicate + r" on\else off\fi}"
                        + r"Text.\end{document}")
                    effective = "on" if permission == request == "true" else "off"
                    self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                    self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_translation_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{TRANSLATION-#1:\ifulShowTranslation on\else off\fi}}
\Probe{preset}
\begin{document}\makeatletter
{\translationoff\Probe{off}
 {\ulLocalShow{translation}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\typeout{PRIMITIVE:\meaning\ifulShowTranslation}
\iffalse\ifulShowTranslation\else\ifulShowChords\fi\fi\else\typeout{SKIPPED:balanced}\fi
{\translationoff
 \typeout{INDEPENDENT:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi/\ifulShowLilypond on\else off\fi/\ifulShowAltChords on\else off\fi}}
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Translation requests}[key={C}]
\translationoff\Probe{song-off}
\beginverse*
\translationon\Probe{verse-on}Text.
\endverse\Probe{after-verse}
\endsong\Probe{after-song}
\beginsong{Following song}\Probe{next-song}
\beginverse*Text.\endverse\endsong\end{ulSongs}
\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                for marker in ("preset", "nested", "restored-book", "verse-on",
                               "after-song", "next-song"):
                    self.assertIn(f"TRANSLATION-{marker}:on", output)
                for marker in ("off", "restored-off", "song-off", "after-verse"):
                    self.assertIn(f"TRANSLATION-{marker}:off", output)
                inline = "/".join(INLINE_PRESET[variant])
                altchords = "on" if variant in ("default", "charango") else "off"
                scores = "off" if variant == "lyric" else "on"
                self.assertIn(f"INDEPENDENT:{inline}/on/{scores}/{altchords}", output)
                for marker in (r"PRIMITIVE:\iftrue", "SKIPPED:balanced",
                               "IDENTITY:unchanged"):
                    self.assertIn(marker, output)

    def test_translation_permission_truth_table_on_both_entry_paths(self):
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permission in ("true", "false"):
                output = self.compile(entry + rf"\ulShowTranslation{{{permission}}}" + r"""
\translationoff\ulShowTranslation{true}
\ifulShowTranslation\errmessage{Book setter erased request}\fi
""" + rf"\ulShowTranslation{{{permission}}}" + r"""
\ulShowChords{false}\ulShowNotes{false}\ulShowLilypond{false}
\begin{document}
{\translationon\typeout{RESTORE:\ifulShowTranslation on\else off\fi}
 \typeout{PRIMITIVE:\meaning\ifulShowTranslation}
 \ulIfMusical{\errmessage{Translation made musical}}{\typeout{MUSICAL:off}}}
\ifulShowTranslation\errmessage{Lost grouped restoration}\fi
\translationon
\typeout{PERMISSION:\ifulShowTranslation on\else off\fi}
Text.\end{document}
""")
                state = "on" if permission == "true" else "off"
                self.assertIn(f"RESTORE:{state}", output)
                self.assertIn(f"PERMISSION:{state}", output)
                self.assertIn(r"PRIMITIVE:\if" + ("true" if permission == "true" else "false"), output)
                self.assertIn("MUSICAL:off", output)

    def test_translation_policy_rejects_invalid_and_frozen_setters(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowTranslation{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowTranslation{true}}\begin{document}", "preamble-only"),
            (r"\ulShowTranslation{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulShowTranslation{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{translation}{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulLocalShow{translation}{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                # TeX can wrap this longer setter's diagnostic within a word.
                self.assertIn("".join(diagnostic.split()), "".join(output.split()))
        for permission, request in product(("true", "false"), repeat=2):
            with self.subTest(permission=permission, request=request):
                output = self.compile(book() + rf"""
\ulShowTranslation{{{permission}}}\ulLocalShow{{translation}}{{{request}}}
""" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
\ulShowTranslation{invalid}\ulLocalShow{translation}{invalid}
\ulShowTranslation{\ComputedBoolean}\ulLocalShow{translation}{\ComputedBoolean}
\AtBeginDocument{\ulShowTranslation{true}}
\begin{document}
\ulShowTranslation{true}\ulShowTranslation{false}
\typeout{UNCHANGED:\ifulShowTranslation on\else off\fi;ERRORS:\the\Errors}
\translationon\typeout{PERMISSION:\ifulShowTranslation on\else off\fi}
Text.\end{document}
""")
                effective = "on" if permission == request == "true" else "off"
                self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_explanation_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{EXPLANATION-#1:\ifulShowExplanation on\else off\fi}}
\Probe{preset}
\begin{document}\makeatletter
{\ulLocalShow{explanation}{false}\Probe{off}
 {\ulLocalShow{explanation}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\typeout{PRIMITIVE:\meaning\ifulShowExplanation}
\iffalse\ifulShowExplanation\else\ifulShowTranslation\fi\fi\else\typeout{SKIPPED:balanced}\fi
{\ulLocalShow{explanation}{false}
 \typeout{INDEPENDENT:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi/\ifulShowLilypond on\else off\fi/\ifulShowAltChords on\else off\fi/\ifulShowTranslation on\else off\fi}}
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Explanation requests}[key={C}]
\ulLocalShow{explanation}{false}\Probe{song-off}
\beginverse*
\ulLocalShow{explanation}{true}\Probe{verse-on}Text.
\endverse\Probe{after-verse}
\endsong\Probe{after-song}
\beginsong{Following song}\Probe{next-song}
\beginverse*Text.\endverse\endsong\end{ulSongs}
\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                for marker in ("preset", "nested", "restored-book", "verse-on",
                               "after-song", "next-song"):
                    self.assertIn(f"EXPLANATION-{marker}:on", output)
                for marker in ("off", "restored-off", "song-off", "after-verse"):
                    self.assertIn(f"EXPLANATION-{marker}:off", output)
                inline = "/".join(INLINE_PRESET[variant])
                altchords = "on" if variant in ("default", "charango") else "off"
                scores = "off" if variant == "lyric" else "on"
                self.assertIn(f"INDEPENDENT:{inline}/on/{scores}/{altchords}/on", output)
                for marker in (r"PRIMITIVE:\iftrue", "SKIPPED:balanced",
                               "IDENTITY:unchanged"):
                    self.assertIn(marker, output)

    def test_explanation_permission_truth_table_on_both_entry_paths(self):
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permission in ("true", "false"):
                output = self.compile(entry + rf"\ulShowExplanation{{{permission}}}" + r"""
\ulLocalShow{explanation}{false}\ulShowExplanation{true}
\ifulShowExplanation\errmessage{Book setter erased request}\fi
""" + rf"\ulShowExplanation{{{permission}}}" + r"""
\ulShowChords{false}\ulShowNotes{false}\ulShowLilypond{false}
\translationoff
\begin{document}
{\ulLocalShow{explanation}{true}\typeout{RESTORE:\ifulShowExplanation on\else off\fi}
 \typeout{PRIMITIVE:\meaning\ifulShowExplanation}
 \ifulShowTranslation\errmessage{Explanation changed translation}\fi
 \ulIfMusical{\errmessage{Explanation made musical}}{\typeout{MUSICAL:off}}}
\ifulShowExplanation\errmessage{Lost grouped restoration}\fi
\ulLocalShow{explanation}{true}
\typeout{PERMISSION:\ifulShowExplanation on\else off\fi}
Text.\end{document}
""")
                state = "on" if permission == "true" else "off"
                self.assertIn(f"RESTORE:{state}", output)
                self.assertIn(f"PERMISSION:{state}", output)
                self.assertIn(r"PRIMITIVE:\if" + ("true" if permission == "true" else "false"), output)
                self.assertIn("MUSICAL:off", output)

    def test_explanation_policy_rejects_invalid_and_frozen_setters(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowExplanation{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowExplanation{true}}\begin{document}", "preamble-only"),
            (r"\ulShowExplanation{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulShowExplanation{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{explanation}{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulLocalShow{explanation}{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                self.assertIn("".join(diagnostic.split()), "".join(output.split()))
        for permission, request in product(("true", "false"), repeat=2):
            with self.subTest(permission=permission, request=request):
                output = self.compile(book() + rf"""
\ulShowExplanation{{{permission}}}\ulLocalShow{{explanation}}{{{request}}}
""" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
\ulShowExplanation{invalid}\ulLocalShow{explanation}{invalid}
\ulShowExplanation{\ComputedBoolean}\ulLocalShow{explanation}{\ComputedBoolean}
\AtBeginDocument{\ulShowExplanation{true}}
\begin{document}
\ulShowExplanation{true}\ulShowExplanation{false}
\typeout{UNCHANGED:\ifulShowExplanation on\else off\fi;ERRORS:\the\Errors}
\ulLocalShow{explanation}{true}\typeout{PERMISSION:\ifulShowExplanation on\else off\fi}
Text.\end{document}
""")
                effective = "on" if permission == request == "true" else "off"
                self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_passage_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{PASSAGE-#1:\ifulShowPassage on\else off\fi}}
\Probe{preset}
\begin{document}\makeatletter
{\ulLocalShow{passage}{false}\Probe{off}
 {\ulLocalShow{passage}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\typeout{PRIMITIVE:\meaning\ifulShowPassage}
\iffalse\ifulShowPassage\else\ifulShowExplanation\fi\fi\else\typeout{SKIPPED:balanced}\fi
{\ulLocalShow{passage}{false}
 \typeout{INDEPENDENT:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi/\ifulShowLilypond on\else off\fi/\ifulShowAltChords on\else off\fi/\ifulShowTranslation on\else off\fi/\ifulShowExplanation on\else off\fi}}
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Passage requests}[key={C}]
\ulLocalShow{passage}{false}\Probe{song-off}
\beginverse*
\ulLocalShow{passage}{true}\Probe{verse-on}Text.
\endverse\Probe{after-verse}
\endsong\Probe{after-song}
\beginsong{Following song}\Probe{next-song}
\beginverse*Text.\endverse\endsong\end{ulSongs}
\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                for marker in ("preset", "nested", "restored-book", "verse-on",
                               "after-song", "next-song"):
                    self.assertIn(f"PASSAGE-{marker}:on", output)
                for marker in ("off", "restored-off", "song-off", "after-verse"):
                    self.assertIn(f"PASSAGE-{marker}:off", output)
                inline = "/".join(INLINE_PRESET[variant])
                altchords = "on" if variant in ("default", "charango") else "off"
                scores = "off" if variant == "lyric" else "on"
                self.assertIn(f"INDEPENDENT:{inline}/on/{scores}/{altchords}/on/on", output)
                for marker in (r"PRIMITIVE:\iftrue", "SKIPPED:balanced",
                               "IDENTITY:unchanged"):
                    self.assertIn(marker, output)

    def test_passage_permission_truth_table_on_both_entry_paths(self):
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permission in ("true", "false"):
                output = self.compile(entry + rf"\ulShowPassage{{{permission}}}" + r"""
\ulLocalShow{passage}{false}\ulShowPassage{true}
\ifulShowPassage\errmessage{Book setter erased request}\fi
""" + rf"\ulShowPassage{{{permission}}}" + r"""
\ulShowChords{false}\ulShowNotes{false}\ulShowLilypond{false}
\translationoff\ulLocalShow{explanation}{false}
\begin{document}
{\ulLocalShow{passage}{true}\typeout{RESTORE:\ifulShowPassage on\else off\fi}
 \typeout{PRIMITIVE:\meaning\ifulShowPassage}
 \ifulShowTranslation\errmessage{Passage changed translation}\fi
 \ifulShowExplanation\errmessage{Passage changed explanation}\fi
 \ulIfMusical{\errmessage{Passage made musical}}{\typeout{MUSICAL:off}}}
\ifulShowPassage\errmessage{Lost grouped restoration}\fi
\ulLocalShow{passage}{true}
\typeout{PERMISSION:\ifulShowPassage on\else off\fi}
Text.\end{document}
""")
                state = "on" if permission == "true" else "off"
                self.assertIn(f"RESTORE:{state}", output)
                self.assertIn(f"PERMISSION:{state}", output)
                self.assertIn(r"PRIMITIVE:\if" + permission, output)
                self.assertIn("MUSICAL:off", output)

    def test_passage_policy_rejects_invalid_and_frozen_setters(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowPassage{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowPassage{true}}\begin{document}", "preamble-only"),
            (r"\ulShowPassage{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulShowPassage{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{passage}{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulLocalShow{passage}{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                self.assertIn("".join(diagnostic.split()), "".join(output.split()))
        for permission, request in product(("true", "false"), repeat=2):
            with self.subTest(permission=permission, request=request):
                output = self.compile(book() + rf"""
\ulShowPassage{{{permission}}}\ulLocalShow{{passage}}{{{request}}}
""" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
\ulShowPassage{invalid}\ulLocalShow{passage}{invalid}
\ulShowPassage{\ComputedBoolean}\ulLocalShow{passage}{\ComputedBoolean}
\AtBeginDocument{\ulShowPassage{true}}
\begin{document}
\ulShowPassage{true}\ulShowPassage{false}
\typeout{UNCHANGED:\ifulShowPassage on\else off\fi;ERRORS:\the\Errors}
\ulLocalShow{passage}{true}\typeout{PERMISSION:\ifulShowPassage on\else off\fi}
Text.\end{document}
""")
                effective = "on" if permission == request == "true" else "off"
                self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_feeler_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{FEELER-#1:\ifulShowFeeler on\else off\fi}}
\Probe{preset}
\begin{document}\makeatletter
{\ulLocalShow{feeler}{false}\Probe{off}
 {\ulLocalShow{feeler}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\typeout{PRIMITIVE:\meaning\ifulShowFeeler}
\iffalse\ifulShowFeeler\else\ifulShowPassage\fi\fi\else\typeout{SKIPPED:balanced}\fi
{\ulLocalShow{feeler}{false}
 \typeout{INDEPENDENT:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi/\ifulShowLilypond on\else off\fi/\ifulShowAltChords on\else off\fi/\ifulShowTranslation on\else off\fi/\ifulShowExplanation on\else off\fi/\ifulShowPassage on\else off\fi}}
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Feeler requests}[key={C}]
\ulLocalShow{feeler}{false}\Probe{song-off}
\beginverse*
\ulLocalShow{feeler}{true}\Probe{verse-on}Text.
\endverse\Probe{after-verse}
\endsong\Probe{after-song}
\begin{intersong}
\ulLocalShow{feeler}{false}\Probe{inter-off}
\end{intersong}\Probe{after-inter}
\beginsong{Following song}\Probe{next-song}
\beginverse*Text.\endverse\endsong\end{ulSongs}
\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                for marker in ("preset", "nested", "restored-book", "verse-on",
                               "after-song", "after-inter", "next-song"):
                    self.assertIn(f"FEELER-{marker}:on", output)
                for marker in ("off", "restored-off", "song-off", "after-verse", "inter-off"):
                    self.assertIn(f"FEELER-{marker}:off", output)
                inline = "/".join(INLINE_PRESET[variant])
                altchords = "on" if variant in ("default", "charango") else "off"
                scores = "off" if variant == "lyric" else "on"
                self.assertIn(f"INDEPENDENT:{inline}/on/{scores}/{altchords}/on/on/on", output)
                for marker in (r"PRIMITIVE:\iftrue", "SKIPPED:balanced",
                               "IDENTITY:unchanged"):
                    self.assertIn(marker, output)

    def test_feeler_permission_truth_table_on_both_entry_paths(self):
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permission in ("true", "false"):
                output = self.compile(entry + rf"\ulShowFeeler{{{permission}}}" + r"""
\ulLocalShow{feeler}{false}\ulShowFeeler{true}
\ifulShowFeeler\errmessage{Book setter erased request}\fi
""" + rf"\ulShowFeeler{{{permission}}}" + r"""
\ulShowChords{false}\ulShowNotes{false}\ulShowLilypond{false}
\translationoff\ulLocalShow{explanation}{false}\ulLocalShow{passage}{false}
\begin{document}
{\ulLocalShow{feeler}{true}\typeout{RESTORE:\ifulShowFeeler on\else off\fi}
 \typeout{PRIMITIVE:\meaning\ifulShowFeeler}
 \ifulShowTranslation\errmessage{Feeler changed translation}\fi
 \ifulShowExplanation\errmessage{Feeler changed explanation}\fi
 \ifulShowPassage\errmessage{Feeler changed passage}\fi
 \ulIfMusical{\errmessage{Feeler made musical}}{\typeout{MUSICAL:off}}}
\ifulShowFeeler\errmessage{Lost grouped restoration}\fi
\ulLocalShow{feeler}{true}
\typeout{PERMISSION:\ifulShowFeeler on\else off\fi}
Text.\end{document}
""")
                state = "on" if permission == "true" else "off"
                self.assertIn(f"RESTORE:{state}", output)
                self.assertIn(f"PERMISSION:{state}", output)
                self.assertIn(r"PRIMITIVE:\if" + permission, output)
                self.assertIn("MUSICAL:off", output)

    def test_feeler_policy_rejects_invalid_and_frozen_setters(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowFeeler{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowFeeler{true}}\begin{document}", "preamble-only"),
            (r"\ulShowFeeler{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulShowFeeler{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{feeler}{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulLocalShow{feeler}{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                self.assertIn("".join(diagnostic.split()), "".join(output.split()))
        for permission, request in product(("true", "false"), repeat=2):
            with self.subTest(permission=permission, request=request):
                output = self.compile(book() + rf"""
\ulShowFeeler{{{permission}}}\ulLocalShow{{feeler}}{{{request}}}
""" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
\ulShowFeeler{invalid}\ulLocalShow{feeler}{invalid}
\ulShowFeeler{\ComputedBoolean}\ulLocalShow{feeler}{\ComputedBoolean}
\AtBeginDocument{\ulShowFeeler{true}}
\begin{document}
\ulShowFeeler{true}\ulShowFeeler{false}
\typeout{UNCHANGED:\ifulShowFeeler on\else off\fi;ERRORS:\the\Errors}
\ulLocalShow{feeler}{true}\typeout{PERMISSION:\ifulShowFeeler on\else off\fi}
Text.\end{document}
""")
                effective = "on" if permission == request == "true" else "off"
                self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_musiccomment_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{COMMENTS-#1:\ifulShowMusicComments on\else off\fi}}
\Probe{preset}
\begin{document}
{\ulLocalShow{musiccomments}{false}\Probe{off}
 {\ulLocalShow{musiccomments}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\typeout{PRIMITIVE:\meaning\ifulShowMusicComments}
\iffalse\ifulShowMusicComments\else\ifulShowNotes\fi\fi\else\typeout{SKIPPED:balanced}\fi
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Comment requests}[key={C}]
\ulLocalShow{musiccomments}{false}\Probe{song-off}
\beginverse*
\ulLocalShow{musiccomments}{true}\Probe{verse-on}Text.
\endverse\Probe{after-verse}
\endsong\Probe{after-song}
\begin{intersong}\ulLocalShow{musiccomments}{false}\Probe{inter-off}\end{intersong}
\Probe{after-inter}
\beginsong{Following song}\Probe{next-song}
\beginverse*Text.\endverse\endsong\end{ulSongs}
\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                state = "off" if variant == "lyric" else "on"
                for marker in ("preset", "nested", "restored-book", "verse-on",
                               "after-song", "after-inter", "next-song"):
                    self.assertIn(f"COMMENTS-{marker}:{state}", output)
                for marker in ("off", "restored-off", "song-off", "after-verse", "inter-off"):
                    self.assertIn(f"COMMENTS-{marker}:off", output)
                for marker in (r"PRIMITIVE:\if" + ("false" if variant == "lyric" else "true"),
                               "SKIPPED:balanced", "IDENTITY:unchanged"):
                    self.assertIn(marker, output)

    def test_musiccomment_permission_truth_table_on_both_entry_paths(self):
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permission in ("true", "false"):
                output = self.compile(entry + r"""
\ulLocalShow{musiccomments}{false}\ulShowMusicComments{true}
\ifulShowMusicComments\errmessage{Book setter erased request}\fi
""" + rf"\ulShowMusicComments{{{permission}}}" + r"""
\ulShowChords{false}\ulShowNotes{false}\ulShowLilypond{false}
\begin{document}
{\ulLocalShow{musiccomments}{true}
 \typeout{RESTORE:\ifulShowMusicComments on\else off\fi}
 \typeout{PRIMITIVE:\meaning\ifulShowMusicComments}
 \ulIfMusical{\errmessage{Comments made musical}}{\typeout{MUSICAL:off}}
 \ifulShowChords\errmessage{Comments changed chords}\fi
 \ifulShowNotes\errmessage{Comments changed pitches}\fi
 \ifulShowLilypond\errmessage{Comments changed scores}\fi
 \ifulShowBeats\else\errmessage{Comments changed beats}\fi
 \ifulShowMeasures\else\errmessage{Comments changed measures}\fi
 \ifulShowAltChords\else\errmessage{Comments changed alternate sets}\fi
 \ifulShowKey\else\errmessage{Comments changed key}\fi
 \ifulShowGoodKeys\else\errmessage{Comments changed goodkeys}\fi
 \ifulShowTranslation\else\errmessage{Comments changed translation}\fi
 \ifulShowExplanation\else\errmessage{Comments changed explanation}\fi
 \ifulShowPassage\else\errmessage{Comments changed passage}\fi
 \ifulShowFeeler\else\errmessage{Comments changed feeler}\fi}
\ifulShowMusicComments\errmessage{Lost grouped restoration}\fi
Text.\end{document}
""")
                self.assertIn(f"RESTORE:{'on' if permission == 'true' else 'off'}", output)
                self.assertIn(r"PRIMITIVE:\if" + permission, output)
                self.assertIn("MUSICAL:off", output)

    def test_musiccomment_policy_rejects_invalid_and_frozen_setters(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowMusicComments{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowMusicComments{true}}\begin{document}", "preamble-only"),
            (r"\ulShowMusicComments{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulShowMusicComments{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{musiccomments}{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\ComputedBoolean{true}\ulLocalShow{musiccomments}{\ComputedBoolean}\begin{document}", "Invalid boolean value"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                self.assertIn("".join(diagnostic.split()), "".join(output.split()))
        for permission, request in product(("true", "false"), repeat=2):
            with self.subTest(permission=permission, request=request):
                output = self.compile(book() + rf"""
\ulShowMusicComments{{{permission}}}\ulLocalShow{{musiccomments}}{{{request}}}
""" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
\ulShowMusicComments{invalid}\ulLocalShow{musiccomments}{invalid}
\ulShowMusicComments{\ComputedBoolean}\ulLocalShow{musiccomments}{\ComputedBoolean}
\AtBeginDocument{\ulShowMusicComments{true}}
\begin{document}
\ulShowMusicComments{true}\ulShowMusicComments{false}
\typeout{UNCHANGED:\ifulShowMusicComments on\else off\fi;ERRORS:\the\Errors}
\ulLocalShow{musiccomments}{true}\typeout{PERMISSION:\ifulShowMusicComments on\else off\fi}
Text.\end{document}
""")
                effective = "on" if permission == request == "true" else "off"
                self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_capo_source_transposition_is_independent_of_display(self):
        for variant in VARIANTS:
            output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                "variants={default,lyric,charango,bassclef}") + r"""
\ulShowMusicComments{false}
\newcount\CapoEffects
\begin{document}
\renewcommand\transpose[1]{\global\advance\CapoEffects1\typeout{CAPO-TRANSPOSE:#1}}
\RenewDocumentCommand\attachednote{s o o m s}{\global\advance\CapoEffects10}
\ulTransposeCapos{true}\chordsoff\capo{3}
\ulTransposeCapos{false}\capo{\input{must-not-be-read.tex}\iftrue}
\chordson\capo{2}
\typeout{CAPO-EFFECTS:\the\CapoEffects}
Text.\end{document}
""")
            self.assertIn("CAPO-TRANSPOSE:3", output)
            self.assertIn(f"CAPO-EFFECTS:{11 if variant in ('default', 'charango') else 1}", output)

    def test_key_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{KEYS-#1:\ifulShowKey on\else off\fi/\ifulShowGoodKeys on\else off\fi}}
\Probe{preset}
\begin{document}\makeatletter
{\ulLocalShow{key}{false}\Probe{key-off}
 {\ulLocalShow{goodkeys}{false}\Probe{both-off}
  \ulLocalShow{key}{true}\Probe{key-on}}
 \Probe{restored-key-off}}
\Probe{restored-book}
{\ulLocalShow{goodkeys}{false}\Probe{goodkeys-off}}
\typeout{PRIMITIVE-KEY:\meaning\ifulShowKey}
\typeout{PRIMITIVE-GOODKEYS:\meaning\ifulShowGoodKeys}
\iffalse\ifulShowKey\else\ifulShowGoodKeys\fi\fi\else\typeout{SKIPPED:balanced}\fi
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Key requests}[key={C},gk={D}]
\ulLocalShow{key}{false}\ulLocalShow{goodkeys}{false}\Probe{song-off}
\beginverse*
\ulLocalShow{key}{true}\ulLocalShow{goodkeys}{true}\Probe{verse-on}Text.
\endverse\Probe{after-verse}
\endsong\Probe{after-song}
\beginsong{Following song}[key={C},gk={D}]\Probe{next-song}
\beginverse*Text.\endverse\endsong\end{ulSongs}
\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                state = "off" if variant == "lyric" else "on"
                for marker in ("preset", "restored-book", "verse-on", "after-song", "next-song"):
                    self.assertIn(f"KEYS-{marker}:{state}/{state}", output)
                for marker in ("key-off", "restored-key-off"):
                    self.assertIn(f"KEYS-{marker}:off/{state}", output)
                for marker in ("both-off", "song-off", "after-verse"):
                    self.assertIn(f"KEYS-{marker}:off/off", output)
                for marker in ("key-on", "goodkeys-off"):
                    self.assertIn(f"KEYS-{marker}:{state}/off", output)
                for feature in ("KEY", "GOODKEYS"):
                    self.assertIn(f"PRIMITIVE-{feature}:\\if{'false' if variant == 'lyric' else 'true'}", output)
                for marker in ("SKIPPED:balanced", "IDENTITY:unchanged"):
                    self.assertIn(marker, output)

    def test_key_permission_truth_tables_on_both_entry_paths(self):
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for key, goodkeys in product(("true", "false"), repeat=2):
                output = self.compile(entry + rf"""
\ulLocalShow{{key}}{{false}}\ulLocalShow{{goodkeys}}{{false}}
\ulShowKey{{true}}\ulShowGoodKeys{{true}}
\ifulShowKey\errmessage{{Key setter erased request}}\fi
\ifulShowGoodKeys\errmessage{{Goodkeys setter erased request}}\fi
\ulShowKey{{{key}}}\ulShowGoodKeys{{{goodkeys}}}
""" + r"""
\ulShowChords{false}\ulShowNotes{false}\ulShowLilypond{false}
\begin{document}
\ulLocalShow{key}{true}\ulLocalShow{goodkeys}{true}
\typeout{PERMISSION:\ifulShowKey on\else off\fi/\ifulShowGoodKeys on\else off\fi}
{\ulLocalShow{key}{false}\ulLocalShow{goodkeys}{false}
 \ifulShowChords\errmessage{Badges changed chords}\fi
 \ifulShowNotes\errmessage{Badges changed pitches}\fi
 \ifulShowLilypond\errmessage{Badges changed scores}\fi
 \ifulShowBeats\else\errmessage{Badges changed beats}\fi
 \ifulShowMeasures\else\errmessage{Badges changed measures}\fi
 \ifulShowTranslation\else\errmessage{Badges changed translation}\fi
 \ifulShowExplanation\else\errmessage{Badges changed explanation}\fi
 \ifulShowPassage\else\errmessage{Badges changed passage}\fi
 \ifulShowFeeler\else\errmessage{Badges changed feeler}\fi}
\ulIfMusical{\errmessage{Keys made musical}}{\typeout{MUSICAL:off}}
Text.\end{document}
""")
                self.assertIn(f"PERMISSION:{'on' if key == 'true' else 'off'}/"
                              f"{'on' if goodkeys == 'true' else 'off'}", output)
                self.assertIn("MUSICAL:off", output)

    def test_key_policies_reject_invalid_and_frozen_setters(self):
        for feature, setter, predicate in (("key", "ulShowKey", "ifulShowKey"),
                                           ("goodkeys", "ulShowGoodKeys", "ifulShowGoodKeys")):
            for commands, diagnostic in (
                (rf"\begin{{document}}\{setter}{{false}}", "preamble-only"),
                (rf"\AtBeginDocument{{\{setter}{{true}}}}\begin{{document}}", "preamble-only"),
                (rf"\{setter}{{yes}}\begin{{document}}", "Invalid boolean value"),
                (rf"\def\ComputedBoolean{{true}}\{setter}{{\ComputedBoolean}}\begin{{document}}", "Invalid boolean value"),
                (rf"\ulLocalShow{{{feature}}}{{yes}}\begin{{document}}", "Invalid boolean value"),
                (rf"\def\ComputedBoolean{{true}}\ulLocalShow{{{feature}}}{{\ComputedBoolean}}\begin{{document}}", "Invalid boolean value"),
            ):
                with self.subTest(feature=feature, commands=commands):
                    output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                    self.assertIn("".join(diagnostic.split()), "".join(output.split()))
            for permission, request in product(("true", "false"), repeat=2):
                with self.subTest(feature=feature, permission=permission, request=request):
                    output = self.compile(book() + rf"""
\{setter}{{{permission}}}\ulLocalShow{{{feature}}}{{{request}}}
\newcount\Errors
\renewcommand\PackageError[3]{{\global\advance\Errors1 }}
\def\ComputedBoolean{{true}}
\{setter}{{invalid}}\ulLocalShow{{{feature}}}{{invalid}}
\{setter}{{\ComputedBoolean}}\ulLocalShow{{{feature}}}{{\ComputedBoolean}}
\AtBeginDocument{{\{setter}{{true}}}}
\begin{{document}}
\{setter}{{true}}\{setter}{{false}}
\typeout{{UNCHANGED:\{predicate} on\else off\fi;ERRORS:\the\Errors}}
\ulLocalShow{{{feature}}}{{true}}\typeout{{PERMISSION:\{predicate} on\else off\fi}}
Text.\end{{document}}
""")
                    effective = "on" if permission == request == "true" else "off"
                    self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                    self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_score_policy_requests_are_scoped_effective_and_independent(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                allowed = variant != "lyric"
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\typeout{SCORES-#1:\ifulShowLilypond on\else off\fi}}
\Probe{preset}
\begin{document}
\Probe{body}
{\ulLocalShow{scores}{false}\Probe{off}
 {\ulLocalShow{scores}{true}\Probe{nested}}
 \Probe{restored-off}}
\Probe{restored-book}
\ulLocalShow{scores}{true}\Probe{on}
\typeout{PRIMITIVE:\meaning\ifulShowLilypond}
\iffalse\ifulShowLilypond\else\ifulShowNotes\fi\fi\else\typeout{SKIPPED:balanced}\fi
{\ulLocalShow{scores}{false}
 \typeout{INDEPENDENT:\ifulShowChords on\else off\fi/\ifulShowNotes on\else off\fi/\ifulShowBeats on\else off\fi/\ifulShowMeasures on\else off\fi}}
\ulIfVariant{""" + variant + r"""}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Local score request}[key={C}]
\ulLocalShow{scores}{false}\Probe{song-off}
\beginverse*
\ulLocalShow{scores}{true}\Probe{verse-on}
Text.
\endverse\Probe{after-verse}
\endsong
\Probe{after-song}
\beginsong{Following song}[key={C}]\Probe{next-song}
\beginverse*Text.\endverse\endsong\end{ulSongs}
\end{document}
""")
                for marker in ("preset", "body", "nested", "restored-book", "on",
                               "verse-on", "after-song", "next-song"):
                    self.assertIn(f"SCORES-{marker}:{'on' if allowed else 'off'}", output)
                for marker in ("off", "restored-off", "song-off", "after-verse"):
                    self.assertIn(f"SCORES-{marker}:off", output)
                self.assertIn(r"PRIMITIVE:\if" + ("true" if allowed else "false"), output)
                inline = "/".join(INLINE_PRESET[variant])
                self.assertIn(f"INDEPENDENT:{inline}/on", output)
                for marker in ("SKIPPED:balanced", "IDENTITY:unchanged"):
                    self.assertIn(marker, output)
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permission in ("true", "false"):
                output = self.compile(entry + rf"\ulShowLilypond{{{permission}}}" + r"""
\ulLocalShow{scores}{false}
\ifulShowLilypond\errmessage{Lost preamble request}\fi
\begin{document}
{\ulLocalShow{scores}{true}\typeout{RESTORE:\ifulShowLilypond on\else off\fi}}
\ifulShowLilypond\errmessage{Lost grouped restoration}\fi
Denied or restored.\end{document}
""")
                self.assertIn(f"RESTORE:{'on' if permission == 'true' else 'off'}", output)

    def test_score_policy_rejects_body_setters_and_invalid_values(self):
        for commands, diagnostic in (
            (r"\begin{document}\ulShowLilypond{false}", "preamble-only"),
            (r"\AtBeginDocument{\ulShowLilypond{true}}\begin{document}", "preamble-only"),
            (r"\ulShowLilypond{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\value{true}\ulShowLilypond{\value}\begin{document}", "Invalid boolean value"),
            (r"\ulLocalShow{scores}{yes}\begin{document}", "Invalid boolean value"),
            (r"\def\value{true}\ulLocalShow{scores}{\value}\begin{document}", "Invalid boolean value"),
        ):
            with self.subTest(commands=commands):
                output = self.compile(book() + commands + r"Invalid.\end{document}", success=False)
                self.assertIn(diagnostic, " ".join(output.split()))

    def test_rejected_score_setters_do_not_change_permission_or_requests(self):
        for permission in ("true", "false"):
            for request in ("true", "false"):
                output = self.compile(book() + rf"""
\ulShowLilypond{{{permission}}}\ulLocalShow{{scores}}{{{request}}}
""" + r"""
\newcount\Errors
\renewcommand\PackageError[3]{\global\advance\Errors1 }
\def\ComputedBoolean{true}
\ulShowLilypond{invalid}\ulLocalShow{scores}{invalid}
\ulShowLilypond{\ComputedBoolean}\ulLocalShow{scores}{\ComputedBoolean}
\AtBeginDocument{\ulShowLilypond{true}}
\begin{document}
\ulShowLilypond{true}\ulShowLilypond{false}
\typeout{UNCHANGED:\ifulShowLilypond on\else off\fi;ERRORS:\the\Errors}
\ulLocalShow{scores}{true}\typeout{PERMISSION:\ifulShowLilypond on\else off\fi}
Text.\end{document}
""")
                effective = "on" if permission == request == "true" else "off"
                self.assertIn(f"UNCHANGED:{effective};ERRORS:7", output)
                self.assertIn(f"PERMISSION:{'on' if permission == 'true' else 'off'}", output)

    def test_musical_helper_uses_effective_truth_table_on_both_entry_paths(self):
        features = ("chords", "notes", "scores")
        setters = ("ulShowChords", "ulShowNotes", "ulShowLilypond")
        combinations = list(product((False, True), repeat=3))
        for entry in (book(), r"\documentclass{book}\usepackage{ulsbs}"):
            for permissions in combinations:
                with self.subTest(entry=entry, permissions=permissions):
                    source = entry + "\n" + "".join(
                        rf"\{setter}{{{str(allowed).lower()}}}"
                        for setter, allowed in zip(setters, permissions, strict=True))
                    source += r"""
\newcommand\Probe[1]{\ulIfMusical{\typeout{MUSICAL-#1:on}}{\typeout{MUSICAL-#1:off}}}
\Probe{preamble}
\begin{document}
"""
                    expected = {"preamble": any(permissions)}
                    # Sweep permission AND request, with every independent beat/bar
                    # combination. No actual annotation or score is needed for true.
                    for index, requests in enumerate(combinations):
                        source += "{" + "".join(
                            rf"\ulLocalShow{{{feature}}}{{{str(request).lower()}}}"
                            for feature, request in zip(features, requests, strict=True))
                        for beats, measures in product((False, True), repeat=2):
                            marker = f"{index}-{int(beats)}-{int(measures)}"
                            source += (rf"\ulLocalShow{{beats}}{{{str(beats).lower()}}}"
                                       + (r"\measureson" if measures else r"\measuresoff")
                                       + rf"\Probe{{{marker}}}" + "\n")
                            expected[marker] = any(p and r for p, r in zip(
                                permissions, requests, strict=True))
                        source += "}\n"
                    source += r"\Probe{restored}Text.\end{document}"
                    expected["restored"] = any(permissions)
                    output = self.compile(source)
                    for marker, musical in expected.items():
                        self.assertIn(f"MUSICAL-{marker}:{'on' if musical else 'off'}", output)

    def test_musical_helper_tracks_presets_and_group_song_verse_restoration(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                output = self.compile(rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef}") + r"""
\newcommand\Probe[1]{\ulIfMusical{\typeout{MUSICAL-#1:on}}{\typeout{MUSICAL-#1:off}}}
\Probe{preset}
\begin{document}
\Probe{body}
{\chordsoff\notesoff\ulLocalShow{scores}{false}\Probe{off}
 {\ulLocalShow{scores}{true}\Probe{score-only}}
 \Probe{restored-off}}
\Probe{restored-book}
\chordson\noteson\ulLocalShow{scores}{true}\Probe{local-on}
\ulIfVariant{VARIANT}{\typeout{IDENTITY:unchanged}}{\errmessage{Changed identity}}
\begin{ulSongs}{}
\beginsong{Musical scope}[key={C}]
\chordsoff\notesoff\ulLocalShow{scores}{false}\Probe{song-off}
\beginverse*
\ulLocalShow{scores}{true}\Probe{verse-on}Text.
\endverse\Probe{after-verse}
\endsong\Probe{after-song}
\beginsong{Following song}[key={C}]\Probe{next-song}
\beginverse*Text.\endverse\endsong\end{ulSongs}
\end{document}
""".replace("{VARIANT}", "{" + variant + "}"))
                for marker in ("preset", "body", "score-only", "restored-book", "local-on",
                               "verse-on", "after-song", "next-song"):
                    self.assertIn(f"MUSICAL-{marker}:{'off' if variant == 'lyric' else 'on'}", output)
                for marker in ("off", "restored-off", "song-off", "after-verse"):
                    self.assertIn(f"MUSICAL-{marker}:off", output)
                self.assertIn("IDENTITY:unchanged", output)

    def test_musical_helper_branches_are_lazy_once_only_and_in_caller_scope(self):
        source = book() + r"""
\newcount\YesEffects\newcount\NoEffects
\newcommand\Probe[1]{\ulIfMusical{\typeout{MUSICAL-#1:on}}{\typeout{MUSICAL-#1:off}}}
\begin{document}
"""
        for chords, notes, scores in product((False, True), repeat=3):
            source += "".join(rf"\ulLocalShow{{{feature}}}{{{str(request).lower()}}}"
                              for feature, request in zip(("chords", "notes", "scores"),
                                                         (chords, notes, scores), strict=True))
            if chords or notes or scores:
                source += r"\ulIfMusical{\advance\YesEffects1 }{\input{missing.tex}\iftrue}"
            else:
                source += r"\ulIfMusical{\input{missing.tex}\iffalse}{\advance\NoEffects1 }"
            source += "\n"
        source += r"""
\typeout{EFFECTS:\the\YesEffects/\the\NoEffects}
\ulIfMusical{\chordsoff\notesoff\ulLocalShow{scores}{false}
 \ulIfMusical{\errmessage{Stale true state}}{\noteson\Probe{nested-on}}}
 {\errmessage{Lost true branch}}
\Probe{caller-on}
\notesoff\Probe{caller-off}
\ulIfMusical{\errmessage{Stale false state}}{\chordson\Probe{false-branch-on}}
\ifulShowChords
 \ulIfMusical{\ifulShowNotes\errmessage{Changed notes}\else Text.\fi}{\errmessage{Lost chords}}
\else\errmessage{Changed chords}\fi
\ulIfVariant{default}{\ulIfMusical{Text.}{\errmessage{Lost nested query}}}{}
\iffalse\ulIfMusical{\ifulShowChords\else\fi}{\ifulShowLilypond\fi}
 \else\typeout{SKIPPED:balanced}\fi
\ulIfMusical{First paragraph.\par Second paragraph.}{\errmessage{Lost long branch}}
\chordsoff
\ulIfMusical{\errmessage{Lost false branch}}{Third paragraph.\par Fourth paragraph.}
\end{document}
"""
        output = self.compile(source)
        self.assertIn("EFFECTS:7/1", output)
        for marker in ("nested-on", "caller-on", "false-branch-on"):
            self.assertIn(f"MUSICAL-{marker}:on", output)
        self.assertIn("MUSICAL-caller-off:off", output)
        self.assertIn("SKIPPED:balanced", output)

    def test_registered_cover_and_imprint_policies_and_author_icons(self):
        # Use real graphics and emitted imprint text, not just private dispatch
        # probes. The wrapper logs each filename without changing its rendering.
        images = TEX_ASSETS.parent / "img"
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                source = (rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef},oneside,openany") + rf"""
\graphicspath{{{{{images.as_posix()}/}}}}
""" + r"""
\renewcommand\ulMainBookTitle{Final title}
\renewcommand\ulBookDefaultVariantText{LABEL-default}
\renewcommand\ulBookLyricVariantText{LABEL-lyric}
\renewcommand\ulBookCharangoVariantText{LABEL-charango}
\renewcommand\ulBookBassclefVariantText{LABEL-bassclef}
\renewcommand\ulChordsTagIcon{ulsbs-tag-icon-chords_PT_512x512px.png}
\renewcommand\ulLyricsOnlyTagIcon{ulsbs-tag-icon-lyrics-only_PT_512x512px.png}
\renewcommand\ulInsertCoverIcons{\ulInsertCoverIconsVtl}
\ulSetPermanentCoverIcons[ulsbs-tag-icon-music-generic_512x512px.png]
\ulSetVariableCoverIcons[ulsbs-tag-icon-sheetmusic_512x512px]
\let\OriginalGraphics\includegraphics
\RenewDocumentCommand\includegraphics{o m}{%
  \typeout{DRAW:#2}\OriginalGraphics[#1]{#2}}
\begin{document}
\typeout{COVER-NORMAL}
\ulCoverPage{}
\typeout{IMPRINT-NORMAL}
\ulImprintPage\clearpage
\typeout{COVER-STAR}
\ulCoverPage*{}
\typeout{IMPRINT-STAR}
\ulImprintPage\clearpage
\typeout{COVER-RESTORED}
\ulCoverPage{}
\typeout{PRESENTATION-END}
\end{document}
""")
                output, data = self.compile(source, pdf=True)
                normal = {
                    "default": ["ulsbs-tag-icon-sheetmusic_512x512px"],
                    "lyric": ["ulsbs-tag-icon-lyrics-only_PT_512x512px.png"],
                    "charango": ["ulsbs-tag-icon-chords_PT_512x512px.png",
                                 "ulsbs-tag-icon-sheetmusic_512x512px",
                                 "ulsbs-tag-icon-charango_512x512px.png"],
                    "bassclef": ["ulsbs-tag-icon-sheetmusic-bass_512x512px.png"],
                }[variant]
                permanent = ["ulsbs-tag-icon-music-generic_512x512px.png"]
                markers = ("COVER-NORMAL", "IMPRINT-NORMAL", "COVER-STAR",
                           "IMPRINT-STAR", "COVER-RESTORED", "PRESENTATION-END")
                expected = (permanent + normal, normal,
                            permanent + (normal if variant == "default" else []),
                            normal if variant == "default" else [], permanent + normal)
                for start, end, icons in zip(markers[:-1], markers[1:], expected, strict=True):
                    section = output.split(start, 1)[1].split(end, 1)[0]
                    self.assertEqual([line[5:] for line in section.splitlines()
                                      if line.startswith("DRAW:")], icons)
                title = "Final title" + ("" if variant == "default" else f" (LABEL-{variant})")
                self.assertEqual(self.pdf_info(data)["/Title"], title)
                with tempfile.TemporaryDirectory(prefix="ulsbs-imprint-text-") as temporary:
                    path = Path(temporary) / "book.pdf"
                    path.write_bytes(data)
                    text = subprocess.check_output(["pdftotext", str(path), "-"], text=True)
                self.assertEqual(text.count(f"LABEL-{variant}"), 2)
                for other in set(VARIANTS) - {variant}:
                    self.assertNotIn(f"LABEL-{other}", text)

    def test_final_metadata_uses_preamble_strings_and_localized_labels(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                source = (rf"\def\ulBuildVariant{{{variant}}}" + book(
                    "variants={default,lyric,charango,bassclef},language=portuguese") + r"""
\renewcommand\ulMainBookTitle{Author title}
\renewcommand\ulSubBookTitle{Author subtitle}
\renewcommand\ulBookAuthor{Final author}
\renewcommand\ulBookSubject{Final subject}
\renewcommand\ulBookKeywords{final, keywords}
\renewcommand\ulBookVersion{FINAL-VERSION}
\hypersetup{pdfinfo={CustomField={Retained}}}
\begin{document}Metadata.\end{document}
""")
                _, data = self.compile(source, pdf=True)
                suffix = {"default": "", "lyric": " (somente letras)",
                          "charango": " (por charango)", "bassclef": " (com clave de f\u00e1)"}[variant]
                info = self.pdf_info(data)
                self.assertEqual(info["/Title"], "Author title: Author subtitle" + suffix)
                self.assertEqual(info["/Author"], "Final author")
                self.assertEqual(info["/Subject"], "Final subject")
                self.assertEqual(info["/Keywords"], "final, keywords")
                self.assertEqual(info["/DocumentVersion"], "FINAL-VERSION")
                self.assertEqual(info["/CustomField"], "Retained")

    def test_explicit_hypersetup_wins_including_empty_and_pdfinfo_keys(self):
        for entry in (book(), "\\documentclass{book}\n\\usepackage{ulsbs}",
                      r"\def\ulBuildVariant{lyric}" + book("variants={default,lyric}")):
            for title in ("Explicit title", ""):
                with self.subTest(entry=entry, title=title):
                    source = entry + rf"\hypersetup{{pdfinfo={{Title={{{title}}}}}," + r"""
pdfauthor={Explicit author},pdfsubject={},pdfkeywords={Explicit keywords},
pdfinfo={DocumentVersion={EXPLICIT-VERSION}}}
\renewcommand\ulMainBookTitle{Not the PDF title}
\renewcommand\ulBookAuthor{Not the PDF author}
\renewcommand\ulBookVersion{Not the PDF version}
\begin{document}Overrides.\end{document}
"""
                    _, data = self.compile(source, pdf=True)
                    info = self.pdf_info(data)
                    self.assertEqual(info.get("/Title", ""), title)
                    self.assertEqual(info["/Author"], "Explicit author")
                    self.assertEqual(info.get("/Subject", ""), "")
                    self.assertEqual(info["/Keywords"], "Explicit keywords")
                    self.assertEqual(info["/DocumentVersion"], "EXPLICIT-VERSION")

    def test_presentation_dispatch_uses_registry_reference_not_variant_name(self):
        with tempfile.TemporaryDirectory(prefix="ulsbs-presentation-registry-") as temporary:
            assets = Path(temporary) / "tex"
            shutil.copytree(TEX_ASSETS, assets)
            registry = assets / "ulsbs-variants.def.tex"
            registry.write_bytes(registry.read_bytes().replace(
                b"{_BASSCLEF}{bassclef}{ordinary,multikey}",
                b"{_BASSCLEF}{lyric}{ordinary,multikey}",
            ))
            with patch("test_tex_integration.TEX_ASSETS", assets):
                output, data = self.compile(
                    r"\def\ulBuildVariant{bassclef}" + book("variants={default,bassclef}") + r"""
\ulIfVariant{bassclef}{\typeout{IDENTITY:bassclef}}{\errmessage{Wrong identity}}
\begin{document}\makeatletter
\typeout{POLICY-LABEL:\ulsbs@variantlabel}
\begingroup\tiny\edef\ExpectedSize{\f@size}\color{gray}\edef\ExpectedColor{\current@color}
\color{black}\ulPreludeBadgeFont\ulPreludePhaseStyle
\ifx\ExpectedSize\f@size\else\errmessage{Badge size ignored registry reference}\fi
\ifx\ExpectedColor\current@color\else\errmessage{Badge tint ignored registry reference}\fi
\endgroup
Registry reference.\end{document}
""", pdf=True)
        self.assertIn("IDENTITY:bassclef", output)
        self.assertIn("POLICY-LABEL:lyrics only", output)
        self.assertTrue(self.pdf_info(data)["/Title"].endswith(" (lyrics only)"))

    def test_package_only_default_finalizes_preamble_title_without_suffix(self):
        _, data = self.compile(r"""
\documentclass{book}\usepackage{ulsbs}
\renewcommand\ulThisBookTitle{Package-only title}
\renewcommand\ulBookDefaultVariantText{Not a title suffix}
\begin{document}Default package.\end{document}
""", pdf=True)
        self.assertEqual(self.pdf_info(data)["/Title"], "Package-only title")

    def test_direct_default_and_package_only_default(self):
        for entry in (r"\documentclass{ulsbs-songbook}",
                      "\\documentclass{book}\n\\usepackage{ulsbs}"):
            with self.subTest(entry=entry):
                output = self.compile(entry + r"""
\ulIfVariant{default}{\typeout{IDENTITY:default}}{\errmessage{Wrong identity}}
\def\ulBuildVariant{lyric}
\chordsoff\chordson
\ulIfVariant{default}{\typeout{IDENTITY:still-default}}{\errmessage{Mutable identity}}
\begin{document}Independent book.\end{document}
""")
                self.assertIn("IDENTITY:default", output)
                self.assertIn("IDENTITY:still-default", output)
                self.assertEqual(output.replace("\n", "").count("/ulsbs-variant-default.code.tex)"), 1)

    def test_all_presets_at_nested_outer_class_boundary_with_author_overrides(self):
        middle = rb"""\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{ulsbs-songbook-middle}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{ulsbs-songbook}}
\ProcessOptions\relax
\LoadClass{ulsbs-songbook}
\ulShowNotes{true}\ulShowBeats{true}\ulShowLilypond{false}
"""
        outer = rb"""\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{ulsbs-songbook-independent}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{ulsbs-songbook-middle}}
\ProcessOptions\relax
\LoadClass{ulsbs-songbook-middle}
\AtEndOfClass{\ulShowNotes{true}\notesoff\ulShowBeats{true}\beatsoff\ulShowLilypond{false}\ulLocalShow{scores}{false}\ulShowChords{false}\chordsoff}
\AtEndOfClass{\ulShowMeasures{false}\measuresoff}
\AtEndOfClass{\ulShowAltChords{false}\ulLocalShow{altchords}{false}}
\AtEndOfClass{\ulShowTranslation{false}\translationoff}
\AtEndOfClass{\ulShowExplanation{false}\ulLocalShow{explanation}{false}}
\AtEndOfClass{\ulShowPassage{false}\ulLocalShow{passage}{false}}
\AtEndOfClass{\ulShowFeeler{false}\ulLocalShow{feeler}{false}}
\AtEndOfClass{\ulShowKey{true}\ulLocalShow{key}{false}}
\AtEndOfClass{\ulShowGoodKeys{false}\ulLocalShow{goodkeys}{true}}
\AtEndOfClass{\ulShowMusicComments{false}\ulLocalShow{musiccomments}{false}}
\AtEndOfClass{\ulShowAuthors{false}\ulLocalShow{authors}{false}}
\AtEndOfClass{\ulShowOfferedTo{false}\ulLocalShow{offeredto}{false}}
\AtEndOfClass{\ulShowExtraInfo{false}\ulLocalShow{extrainfo}{false}}
\AtEndOfClass{\ulShowTags{false}\ulLocalShow{tags}{false}}
\AtEndOfClass{\ulShowPhase{false}\ulLocalShow{phase}{false}}
\AtEndOfClass{\ulShowPhaseInToc{false}\ulLocalShow{phaseintoc}{false}}
\AddToHook{class/ulsbs-songbook-independent/after}{\ulShowNotes{true}}
\AtEndOfClass{\renewcommand\ulMainBookTitle{Complete outer class}}
"""
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                expected = {
                    "default": ("off", "off", "off"), "lyric": ("off", "on", "off"),
                    "charango": ("on", "on", "on"), "bassclef": ("off", "off", "on"),
                }[variant]
                source = (rf"\def\ulBuildVariant{{{variant}}}" + "\n" + r"""
\documentclass[variants={ default, lyric, charango, bassclef },subtitle={A, {B]C}}]
  {ulsbs-songbook-independent}
\begingroup\ulLyricFontStyle\ulVerseFont
\directlua{
 local a = \number\fontcharht\font`A;
 for _,kind in ipairs({'baseline','separation'}) do
  local skip = tex.skip[kind == 'baseline' and 'l__ulsbs_verse_nominal_skip' or 'ulsbs@verse@separation']
  for i,field in ipairs({'natural','stretch','shrink'}) do
   local scale = tonumber(token.get_macro('ulsbs@verse@'..kind..'@'..field))
   assert(scale and scale >= 0 and scale < math.huge)
   assert(math.abs(skip[({'width','stretch','shrink'})[i]] - a*scale) <= 1,
    'complete outer class preset resolves against selected lyric A')
  end
  assert(skip.stretch_order == 0 and skip.shrink_order == 0)
 end
}
\endgroup
\ulVerseBaseline{2}{.25}{.125}
\begingroup\ulLyricFontStyle\ulVerseFont
\xdef\AuthorVerseA{\number\fontcharht\font`A}\endgroup
\AddToHook{ulsbs/stanza/start}{\directlua{
 local b = tex.skip.baselineskip
 assert(b.width == tex.skip['l__ulsbs_verse_nominal_skip'].width and b.width == 2*\AuthorVerseA,
  'author scalar override survives')
 assert(math.abs(b.stretch - .25*\AuthorVerseA) <= 1 and math.abs(b.shrink - .125*\AuthorVerseA) <= 1)
}}
\typeout{FIRST-NOTES:\ifulShowNotes on\else off\fi}
\typeout{FIRST-BEATS:\ifulShowBeats on\else off\fi}
\typeout{FIRST-SCORES:\ifulShowLilypond on\else off\fi}
\typeout{FIRST-CHORDS:\ifulShowChords on\else off\fi}
\typeout{FIRST-MEASURES:\ifulShowMeasures on\else off\fi}
\typeout{FIRST-ALT:\ifulShowAltChords on\else off\fi}
\ulLocalShow{altchords}{true}\typeout{CLASS-ALT-PERMISSION:\ifulShowAltChords on\else off\fi}
\ulShowAltChords{true}\typeout{AUTHOR-ALT-ALLOW:\ifulShowAltChords on\else off\fi}
\ulShowAltChords{false}\typeout{AUTHOR-ALT-DENIAL:\ifulShowAltChords on\else off\fi}
\ulShowAltChords{true}
\typeout{FIRST-TRANSLATION:\ifulShowTranslation on\else off\fi}
\ulShowTranslation{true}\typeout{AUTHOR-TRANSLATION-REQUEST:\ifulShowTranslation on\else off\fi}
\translationon\typeout{AUTHOR-TRANSLATION-ALLOW:\ifulShowTranslation on\else off\fi}
\ulShowTranslation{false}\translationon
\typeout{AUTHOR-TRANSLATION-DENIAL:\ifulShowTranslation on\else off\fi}
\ulShowTranslation{true}
\typeout{FIRST-EXPLANATION:\ifulShowExplanation on\else off\fi}
\ulLocalShow{explanation}{true}\typeout{CLASS-EXPLANATION-PERMISSION:\ifulShowExplanation on\else off\fi}
\ulLocalShow{explanation}{false}\ulShowExplanation{true}
\typeout{AUTHOR-EXPLANATION-REQUEST:\ifulShowExplanation on\else off\fi}
\ulLocalShow{explanation}{true}\typeout{AUTHOR-EXPLANATION-ALLOW:\ifulShowExplanation on\else off\fi}
\ulShowExplanation{false}\typeout{AUTHOR-EXPLANATION-DENIAL:\ifulShowExplanation on\else off\fi}
\ulShowExplanation{true}
\typeout{FIRST-PASSAGE:\ifulShowPassage on\else off\fi}
\ulLocalShow{passage}{true}\typeout{CLASS-PASSAGE-PERMISSION:\ifulShowPassage on\else off\fi}
\ulLocalShow{passage}{false}\ulShowPassage{true}
\typeout{AUTHOR-PASSAGE-REQUEST:\ifulShowPassage on\else off\fi}
\ulLocalShow{passage}{true}\typeout{AUTHOR-PASSAGE-ALLOW:\ifulShowPassage on\else off\fi}
\ulShowPassage{false}\typeout{AUTHOR-PASSAGE-DENIAL:\ifulShowPassage on\else off\fi}
\ulShowPassage{true}
\typeout{FIRST-FEELER:\ifulShowFeeler on\else off\fi}
\ulLocalShow{feeler}{true}\typeout{CLASS-FEELER-PERMISSION:\ifulShowFeeler on\else off\fi}
\ulLocalShow{feeler}{false}\ulShowFeeler{true}
\typeout{AUTHOR-FEELER-REQUEST:\ifulShowFeeler on\else off\fi}
\ulLocalShow{feeler}{true}\typeout{AUTHOR-FEELER-ALLOW:\ifulShowFeeler on\else off\fi}
\ulShowFeeler{false}\typeout{AUTHOR-FEELER-DENIAL:\ifulShowFeeler on\else off\fi}
\ulShowFeeler{true}
\typeout{FIRST-KEY:\ifulShowKey on\else off\fi}
\ulLocalShow{key}{true}\typeout{CLASS-KEY-PERMISSION:\ifulShowKey on\else off\fi}
\ulLocalShow{key}{false}\ulShowKey{true}
\typeout{AUTHOR-KEY-REQUEST:\ifulShowKey on\else off\fi}
\ulLocalShow{key}{true}\typeout{AUTHOR-KEY-ALLOW:\ifulShowKey on\else off\fi}
\ulShowKey{false}\typeout{AUTHOR-KEY-DENIAL:\ifulShowKey on\else off\fi}
\ulShowKey{true}
\typeout{FIRST-GOODKEYS:\ifulShowGoodKeys on\else off\fi}
\ulShowGoodKeys{true}\typeout{CLASS-GOODKEYS-REQUEST:\ifulShowGoodKeys on\else off\fi}
\ulLocalShow{goodkeys}{false}\ulShowGoodKeys{true}
\typeout{AUTHOR-GOODKEYS-REQUEST:\ifulShowGoodKeys on\else off\fi}
\ulLocalShow{goodkeys}{true}\typeout{AUTHOR-GOODKEYS-ALLOW:\ifulShowGoodKeys on\else off\fi}
\ulShowGoodKeys{false}\typeout{AUTHOR-GOODKEYS-DENIAL:\ifulShowGoodKeys on\else off\fi}
\ulShowGoodKeys{true}
\typeout{FIRST-COMMENTS:\ifulShowMusicComments on\else off\fi}
\ulLocalShow{musiccomments}{true}\typeout{CLASS-COMMENT-PERMISSION:\ifulShowMusicComments on\else off\fi}
\ulLocalShow{musiccomments}{false}\ulShowMusicComments{true}
\typeout{AUTHOR-COMMENT-REQUEST:\ifulShowMusicComments on\else off\fi}
\ulLocalShow{musiccomments}{true}\typeout{AUTHOR-COMMENT-ALLOW:\ifulShowMusicComments on\else off\fi}
\ulShowMusicComments{false}\typeout{AUTHOR-COMMENT-DENIAL:\ifulShowMusicComments on\else off\fi}
\ulShowMusicComments{true}
""" + "\n".join(rf"""
\typeout{{FIRST-{key}:\ifulShow{name} on\else off\fi}}
\ulLocalShow{{{key}}}{{true}}\typeout{{CLASS-{key}-PERMISSION:\ifulShow{name} on\else off\fi}}
\ulLocalShow{{{key}}}{{false}}\ulShow{name}{{true}}
\typeout{{AUTHOR-{key}-REQUEST:\ifulShow{name} on\else off\fi}}
\ulLocalShow{{{key}}}{{true}}\typeout{{AUTHOR-{key}-ALLOW:\ifulShow{name} on\else off\fi}}
\ulShow{name}{{false}}\typeout{{AUTHOR-{key}-DENIAL:\ifulShow{name} on\else off\fi}}
\ulShow{name}{{true}}
""" for key, name in (("authors", "Authors"), ("offeredto", "OfferedTo"), ("extrainfo", "ExtraInfo"),
                     ("tags", "Tags"), ("phase", "Phase"), ("phaseintoc", "PhaseInToc"))) + r"""
\measureson\typeout{CLASS-MEASURE-PERMISSION:\ifulShowMeasures on\else off\fi}
\ulShowMeasures{false}\typeout{AUTHOR-MEASURE-DENIAL:\ifulShowMeasures on\else off\fi}
\ulShowMeasures{true}\ulLocalShow{measures}{true}
\chordson\ulShowChords{true}
\noteson\ulShowNotes{true}\beatson\ulShowBeats{true}\ulShowLilypond{true}\ulLocalShow{scores}{true}
\renewcommand\ulMainBookTitle{Final author title}
\renewcommand\ulBookLyricVariantText{Final lyric label}
\def\ulBuildVariant{not-a-variant}
""" + rf"\ulIfVariant{{{variant}}}{{\typeout{{IDENTITY:{variant}}}}}{{\errmessage{{Wrong identity}}}}"
                          + r"""
\begin{document}
\typeout{BODY-NOTES:\ifulShowNotes on\else off\fi}
\typeout{BODY-BEATS:\ifulShowBeats on\else off\fi}
\typeout{BODY-SCORES:\ifulShowLilypond on\else off\fi}
\typeout{BODY-CHORDS:\ifulShowChords on\else off\fi}
\typeout{BODY-MEASURES:\ifulShowMeasures on\else off\fi}
\typeout{BODY-ALT:\ifulShowAltChords on\else off\fi}
\typeout{BODY-TRANSLATION:\ifulShowTranslation on\else off\fi}
\typeout{BODY-EXPLANATION:\ifulShowExplanation on\else off\fi}
\typeout{BODY-PASSAGE:\ifulShowPassage on\else off\fi}
\typeout{BODY-FEELER:\ifulShowFeeler on\else off\fi}
\typeout{BODY-KEY:\ifulShowKey on\else off\fi}
\typeout{BODY-GOODKEYS:\ifulShowGoodKeys on\else off\fi}
\typeout{BODY-COMMENTS:\ifulShowMusicComments on\else off\fi}
\typeout{BODY-authors:\ifulShowAuthors on\else off\fi}
\typeout{BODY-offeredto:\ifulShowOfferedTo on\else off\fi}
\typeout{BODY-extrainfo:\ifulShowExtraInfo on\else off\fi}
\typeout{BODY-tags:\ifulShowTags on\else off\fi}
\typeout{BODY-phase:\ifulShowPhase on\else off\fi}
\typeout{BODY-phaseintoc:\ifulShowPhaseInToc on\else off\fi}
\begin{ulSongs}{}\beginsong{Independent book}
\beginverse*Independent lyrics.\endverse\endsong\end{ulSongs}
\end{document}
""")
                output, data = self.compile(source, files={"ulsbs-songbook-middle.cls": middle,
                                                          "ulsbs-songbook-independent.cls": outer},
                                            pdf=True)
                for feature, state in zip(("NOTES", "BEATS", "SCORES"), expected, strict=True):
                    self.assertIn(f"FIRST-{feature}:{state}", output)
                self.assertIn(f"IDENTITY:{variant}", output)
                self.assertIn("BODY-NOTES:on", output)
                self.assertIn("BODY-BEATS:on", output)
                self.assertIn("BODY-SCORES:on", output)
                self.assertIn("FIRST-CHORDS:" + ("on" if variant == "charango" else "off"), output)
                self.assertIn("BODY-CHORDS:on", output)
                measures = "off" if variant == "default" else "on"
                self.assertIn(f"FIRST-MEASURES:{measures}", output)
                self.assertIn(f"CLASS-MEASURE-PERMISSION:{measures}", output)
                self.assertIn("AUTHOR-MEASURE-DENIAL:off", output)
                self.assertIn("BODY-MEASURES:on", output)
                alt = "on" if variant == "charango" else "off"
                self.assertIn(f"FIRST-ALT:{alt}", output)
                self.assertIn(f"CLASS-ALT-PERMISSION:{alt}", output)
                self.assertIn("AUTHOR-ALT-ALLOW:on", output)
                self.assertIn("AUTHOR-ALT-DENIAL:off", output)
                self.assertIn("BODY-ALT:on", output)
                for marker in ("FIRST-TRANSLATION:off", "AUTHOR-TRANSLATION-REQUEST:off",
                               "AUTHOR-TRANSLATION-ALLOW:on", "AUTHOR-TRANSLATION-DENIAL:off",
                                "BODY-TRANSLATION:on"):
                    self.assertIn(marker, output)
                for marker in ("FIRST-EXPLANATION:off", "CLASS-EXPLANATION-PERMISSION:off",
                               "AUTHOR-EXPLANATION-REQUEST:off", "AUTHOR-EXPLANATION-ALLOW:on",
                               "AUTHOR-EXPLANATION-DENIAL:off", "BODY-EXPLANATION:on"):
                    self.assertIn(marker, output)
                for marker in ("FIRST-PASSAGE:off", "CLASS-PASSAGE-PERMISSION:off",
                               "AUTHOR-PASSAGE-REQUEST:off", "AUTHOR-PASSAGE-ALLOW:on",
                               "AUTHOR-PASSAGE-DENIAL:off", "BODY-PASSAGE:on"):
                    self.assertIn(marker, output)
                for marker in ("FIRST-FEELER:off", "CLASS-FEELER-PERMISSION:off",
                               "AUTHOR-FEELER-REQUEST:off", "AUTHOR-FEELER-ALLOW:on",
                               "AUTHOR-FEELER-DENIAL:off", "BODY-FEELER:on"):
                    self.assertIn(marker, output)
                self.assertIn("CLASS-KEY-PERMISSION:" + ("off" if variant == "lyric" else "on"), output)
                for feature in ("KEY", "GOODKEYS"):
                    for marker in (f"FIRST-{feature}:off", f"AUTHOR-{feature}-REQUEST:off",
                                   f"AUTHOR-{feature}-ALLOW:on", f"AUTHOR-{feature}-DENIAL:off",
                                   f"BODY-{feature}:on"):
                        self.assertIn(marker, output)
                self.assertIn("CLASS-GOODKEYS-REQUEST:on", output)
                for key in ("authors", "offeredto", "extrainfo", "tags", "phase", "phaseintoc"):
                    for marker in (f"FIRST-{key}:off", f"CLASS-{key}-PERMISSION:off",
                                   f"AUTHOR-{key}-REQUEST:off", f"AUTHOR-{key}-ALLOW:on",
                                   f"AUTHOR-{key}-DENIAL:off", f"BODY-{key}:on"):
                        self.assertIn(marker, output)
                comments = "on" if variant in ("charango", "bassclef") else "off"
                self.assertIn(f"FIRST-COMMENTS:{comments}", output)
                self.assertIn(f"CLASS-COMMENT-PERMISSION:{comments}", output)
                for marker in ("AUTHOR-COMMENT-REQUEST:off", "AUTHOR-COMMENT-ALLOW:on",
                               "AUTHOR-COMMENT-DENIAL:off", "BODY-COMMENTS:on"):
                    self.assertIn(marker, output)
                self.assertEqual(output.replace("\n", "").count(f"/ulsbs-variant-{variant}.code.tex"), 1)
                title = self.pdf_info(data)["/Title"]
                self.assertTrue(title.startswith("Final author title: A, B]C"), title)
                if variant == "lyric":
                    self.assertTrue(title.endswith(" (Final lyric label)"), title)

    def test_direct_selectors_and_literal_availability_match_python(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                source = (rf"\def\ulBuildVariant{{{variant}}}" + "\n"
                          + book("variants % key comment\n= {def% joined identifier\n"
                                 "ault,\nlyric, charango, bassclef},subtitle={variants={wrong}, A}")
                          + rf"\ulIfVariant{{{variant}}}{{\typeout{{DIRECT:{variant}}}}}{{\errmessage{{Wrong identity}}}}"
                          + r"\begin{document}Direct book.\end{document}")
                self.assertEqual(available_variants(source), tuple(VARIANTS))
                self.assertIn(f"DIRECT:{variant}", self.compile(source))
        options = ("variants={}", "variants={ }", "variants={lyric}", "variants={default,lyrics}",
                   "variants={default,LYRIC}", "variants={default;lyric}",
                   "variants={default,default}", "variants={default,}",
                   "variants={default,,lyric}", r"variants={default,\chosen}",
                   "variants={{default,lyric}}", "variants", "variants=", "variants=default",
                   r"variants=\chosen", "variants={default}extra",
                   "variants={default},variants={default}",
                   "variants={default},variants={default,lyric}")
        for option in options:
            with self.subTest(option=option):
                source = r"\def\chosen{lyric}" + book(option)
                with self.assertRaises(ValueError):
                    available_variants(source)
                output = self.compile(source + r"\begin{document}Bad.\end{document}", success=False)
                self.assertIn("Fatal Package ulsbs Error", output.replace("\n", ""))

    def test_disallowed_unknown_computed_and_package_only_selectors_fail(self):
        cases = (
            (r"\def\ulBuildVariant{lyric}" + book(), "not available"),
            (r"\def\ulBuildVariant{unknown}" + book(), "Unknown variant"),
            (r"\def\chosen{lyric}\def\ulBuildVariant{\chosen}" + book(), "Invalid literal"),
            (r"\def\ulBuildVariant{lyric}\documentclass{book}\usepackage{ulsbs}", "Non-default variants require"),
            (book() + r"\ulIfVariant{unknown}{}{}", "Unknown variant"),
        )
        for source, diagnostic in cases:
            with self.subTest(source=source):
                output = self.compile(source + r"\begin{document}Bad.\end{document}", success=False)
                self.assertIn(diagnostic, " ".join(output.split()))

    def test_inherited_options_cannot_declare_main_source_availability(self):
        derived = rb"""\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{ulsbs-songbook-inherited}
\PassOptionsToClass{variants={default,lyric}}{ulsbs-songbook}
\LoadClass{ulsbs-songbook}
"""
        source = (r"\def\ulBuildVariant{lyric}\documentclass{ulsbs-songbook-inherited}"
                  r"\begin{document}Bad.\end{document}")
        output = self.compile(source, success=False, files={"ulsbs-songbook-inherited.cls": derived})
        self.assertIn("not available", " ".join(output.split()))


class AvailabilityTests(unittest.TestCase):
    def test_omission_and_unrelated_documents_mean_only_default(self) -> None:
        for source in ("", r"\documentclass{ulsbs-songbook}", book("subtitle={Lyrics, music}"),
                       book("variants={nonsense}", "article"),
                       book("variants={nonsense}", "../include/custom.v1"), r"\usepackage{ulsbs}"):
            with self.subTest(source=source):
                self.assertEqual(available_variants(source), ("default",))

    def test_registered_lists_and_declaration_order(self) -> None:
        for value in ("default", "default,lyric", "bassclef,default,charango,lyric"):
            with self.subTest(value=value):
                self.assertEqual(available_variants(book(f"variants={{{value}}}")),
                                 tuple(value.split(",")))

    def test_braces_comments_newlines_and_derived_class_names(self) -> None:
        source = (
            "\\documentclass % class comment\r\n[\n"
            "subtitle={A, {B]C}, \\% still metadata},\n"
            "variants % key comment\n= { def% joined identifier\nault,\n"
            "lyric, % list comment\n charango, bassclef },\n"
            "maintitle={\\textbf{Some, title}}\n] % options end\n"
            "{ % class name\nulsbs-songbook-third-party % trailing comment\n}\n"
        )
        self.assertEqual(available_variants(source), tuple(VARIANTS))
        declaration = read_documentclass(source)
        self.assertEqual(declaration.name, "ulsbs-songbook-third-party")
        self.assertEqual(declaration.start, 0)
        self.assertEqual(source[declaration.end:], "\n")

    def test_other_option_values_do_not_declare_availability(self) -> None:
        source = book(r"subtitle={variants={default,lyric}},subject={a=b,c},oneside")
        self.assertEqual(available_variants(source), ("default",))

    def test_commented_examples_and_escape_parity(self) -> None:
        example = book("variants={default,lyric}")
        for prefix in ("% " + example + "\n", "\\\\% " + example + "\n"):
            with self.subTest(prefix=prefix):
                self.assertEqual(available_variants(prefix + book()), ("default",))
        self.assertEqual(available_variants(r"\%" + example), ("default", "lyric"))

    def test_opaque_literals_and_definition_bodies_do_not_declare_variants(self) -> None:
        example = book("variants={default,lyric}")
        wrappers = (
            r"\verb|%s|", r"\verb*+%s+", r"\verb%%%s%%", r"\Verb!%s!",
            r"\lstinline[language=TeX]|%s|", r"\lstinline[language=TeX]%%%s%%",
            r"\url{https://example.test/100%%/%s}", r"\detokenize{%s}",
            r"\url|https://example.test/100%%/%s|", r"\path!%s!", r"\nolinkurl+%s+",
            r"\href{https://example.test/100%%/%s}{Example}",
            r"\newcommand{\example}{%s}", r"\def\example{%s}",
            r"\begin{verbatim}%s\end{verbatim}", r"\begin{minted}{tex}%s\end{minted}",
            r"\begin{comment}%s\end{comment}", r"\begin{filecontents*}{a.tex}%s\end{filecontents*}",
            r"\begin{lilypond}%s\end{lilypond}",
        )
        for wrapper in wrappers:
            with self.subTest(wrapper=wrapper):
                self.assertEqual(available_variants(wrapper % example + "\n" + book()),
                                 ("default",))
        self.assertEqual(available_variants(r"\string\documentclass{ulsbs-songbook}"),
                         ("default",))
        self.assertIsNone(read_documentclass(r"\string\documentclass{ulsbs-songbook}"))

    def test_body_is_not_scanned_for_class_examples_or_unbalanced_song_text(self) -> None:
        source = book() + r"\begin{document}" + book("variants={default,lyric}") + "{"
        self.assertEqual(available_variants(source), ("default",))

    def test_multiple_class_or_option_declarations_are_rejected(self) -> None:
        for source in (book() + book(), book() + book(class_name="article"),
                       book("variants={default},variants={default}"),
                       book("variants={default},variants={default,lyric}")):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "Multiple"):
                available_variants(source)

    def test_bad_or_computed_availability_is_rejected(self) -> None:
        for value in ("", " ", "lyric", "default,lyrics", "default,LYRIC", "default,unknown",
                      "default,default", "default,", "default,,lyric", r"default,\chosen",
                      "{default,lyric}", "default;lyric"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                available_variants(book(f"variants={{{value}}}"))
        for option in ("variants", "variants=", "variants=default", r"variants=\chosen",
                       "variants={default}extra", "variants={default}={lyric}"):
            with self.subTest(option=option), self.assertRaises(ValueError):
                available_variants(book(option))

    def test_malformed_class_and_opaque_input_fails_closed(self) -> None:
        for source in (r"\documentclass", r"\documentclass[variants={default]",
                       r"\documentclass[subtitle=oops}]{ulsbs-songbook}",
                       r"\documentclass{\chosen}", r"\documentclass{ulsbs-songbook",
                       r"\verb|unterminated", r"\url|unterminated",
                       "\\verb\n" + book(),
                       r"\begin{verbatim}unterminated"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                available_variants(source)

    def test_source_offsets_preserve_raw_declaration_for_migrator(self) -> None:
        prefix = "% A comment\n\\newcommand{\\example}{example}\n"
        statement = book("variants = { default , lyric },subtitle={A, B}")
        source = prefix + statement + "\n\\ulShowNotes{false}\n"
        declaration = read_documentclass(source)
        self.assertEqual(source[declaration.start:declaration.end], statement)
        self.assertEqual(declaration.options, "variants = { default , lyric },subtitle={A, B}")
        self.assertEqual(available_variants(source), ("default", "lyric"))
        self.assertEqual(source, prefix + statement + "\n\\ulShowNotes{false}\n")


if __name__ == "__main__":
    unittest.main()
