# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Badge visibility, measurement effects and PDF font identities are contracts."""

import itertools
import json
import re
import shutil
import unittest
import xml.etree.ElementTree as ET

import test_song_lifecycle as lifecycle
from test_pdf_transposition_layers import PdfStructure, pdf_command, words_and_geometry


class BadgeMetricTests(unittest.TestCase):
    setUpClass = classmethod(lifecycle.SongLifecycleTests.setUpClass.__func__)
    setUp = lifecycle.SongLifecycleTests.setUp
    compile_source = lifecycle.SongLifecycleTests.compile_source

    def compile_checked(self, source, effects):
        import pikepdf

        output = self.compile_source(source)
        self.assertEqual(re.findall(r"BADGE-EFFECTS:(\d+)", output), [str(effects)])
        self.assertTrue(re.findall(r"BADGE-FONT:\d+:[^:\r\n]*:\d+", output))
        with pikepdf.Pdf.open(self.book / "book.pdf") as pdf:
            self.assertTrue(any(page.Resources.get("/Font", {}) for page in pdf.pages))

    def test_badge_defaults_follow_named_presentation(self):
        for entry in ("default", "lyric", "charango", "bassclef", "package"):
            with self.subTest(entry=entry):
                variant = "default" if entry == "package" else entry
                header = (r"\documentclass{book}\usepackage{ulsbs}" if entry == "package" else
                          r"\def\ulBuildVariant{" + variant + "}\n"
                          + r"\documentclass[variants={default,lyric,charango,bassclef}]{ulsbs-songbook}")
                source = header + r"""
\makeatletter
\newcommand\ExpectedSize{SIZE}
\newcommand\ExpectedTint{TINT}
\newcommand\CheckBadgeDefaults{%
  \begingroup\ExpectedSize\normalfont\color{black}\ExpectedTint
  \edef\ExpectedFontSize{\f@size}\edef\ExpectedColor{\current@color}%
  \def\CheckStyle##1{\begingroup\color{black}\ulPreludeBadgeFont##1
    \ifx\f@size\ExpectedFontSize\else\errmessage{Wrong badge size}\fi
    \ifx\current@color\ExpectedColor\else\errmessage{Wrong badge tint}\fi\endgroup}%
  \CheckStyle\ulPreludeTagStyle\CheckStyle\ulPreludeKeyLineStyle
  \CheckStyle\ulPreludePhaseStyle\endgroup}
\CheckBadgeDefaults
\begin{document}
\CheckBadgeDefaults
\begingroup\ExpectedSize\edef\ExpectedFontSize{\f@size}
\ExplSyntaxOn
\hbox_set:Nn\l_tmpa_box{\__ulsbs_song_badge:n
  {\ifx\f@size\ExpectedFontSize\else\errmessage{Row font differs}\fi}}
\ExplSyntaxOff
\endgroup
\typeout{BADGE-DEFAULTS:correct}
Named badge defaults.
\end{document}
""".replace("SIZE", r"\tiny" if variant == "lyric" else r"\scriptsize").replace(
                    "TINT", r"\color{gray}" if variant == "lyric" else "")
                output = self.compile_source(source, label=entry)
                self.assertIn("BADGE-DEFAULTS:correct", output)

    def test_badge_hooks_preserve_preload_class_and_author_precedence(self):
        wrapper = rb"""
\ProvidesClass{ulsbs-songbook-badge-test}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{ulsbs-songbook}}
\ProcessOptions\relax
\newcommand\ulPreludeBadgeFont{\footnotesize\normalfont}
\newcommand\ulPreludeTagStyle{\bfseries}
\newcommand\ulPreludeKeyLineStyle{\color{blue}}
\newcommand\ulPreludePhaseStyle{\itshape}
\LoadClass{ulsbs-songbook}
\newcommand\PreloadFont{\footnotesize\normalfont}
\ifx\ulPreludeBadgeFont\PreloadFont\else\errmessage{Preload font lost}\fi
\renewcommand\ulPreludeBadgeFont{\small\normalfont}
\AtEndOfClass{\renewcommand\ulPreludeKeyLineStyle{\color{red}}}
"""
        for variant in ("default", "lyric", "charango", "bassclef"):
            with self.subTest(variant=variant):
                source = r"\def\ulBuildVariant{" + variant + "}\n" + r"""
\documentclass[variants={default,lyric,charango,bassclef}]{ulsbs-songbook-badge-test}
\newcommand\ClassFont{\small\normalfont}
\newcommand\ClassTag{\bfseries}\newcommand\ClassKey{\color{red}}
\newcommand\ClassPhase{\itshape}
\ifx\ulPreludeBadgeFont\ClassFont\else\errmessage{Class font lost}\fi
\ifx\ulPreludeTagStyle\ClassTag\else\errmessage{Class tag style lost}\fi
\ifx\ulPreludeKeyLineStyle\ClassKey\else\errmessage{Class key style lost}\fi
\ifx\ulPreludePhaseStyle\ClassPhase\else\errmessage{Class phase style lost}\fi
\renewcommand\ulPreludeBadgeFont{\large\normalfont}
\renewcommand\ulPreludeTagStyle{\color{green}}
\ulShowKey{true}\ulShowGoodKeys{true}
\ulShowTags{true}\ulShowPhase{true}
\begin{document}
\newcommand\AuthorFont{\large\normalfont}\newcommand\AuthorTag{\color{green}}
\ifx\ulPreludeBadgeFont\AuthorFont\else\errmessage{Author font lost}\fi
\ifx\ulPreludeTagStyle\AuthorTag\else\errmessage{Author tag style lost}\fi
\begin{ulSongs}{}
\beginsong{Authored badges}[key={C},gk={D},tags={fire},ph={I}]
\beginverse*AuthoredAnchor\endverse\endsong
\end{ulSongs}
\end{document}
"""
                self.compile_source(source, label=variant,
                                    files={"ulsbs-songbook-badge-test.cls": wrapper})
                self.assertIn("AuthoredAnchor", lifecycle.SongLifecycleTests.pdf_text(self))

    def test_rows_and_enabled_anchor_samples_share_authored_font_lazily(self):
        source = lifecycle.document(r"""
\begin{ulSongs}{}
\beginsong{Shared font}[id={shared-font},key={C},gk={D},tags={fire},ph={I}]
\beginverse*\[C]FontAnchor\endverse\endsong
{\ulLocalShow{key}{false}\ulLocalShow{goodkeys}{false}
 \ulLocalShow{tags}{false}\ulLocalShow{phase}{false}
 \beginsong{Hidden font}[id={hidden-font},key={C},gk={D},tags={fire},ph={I}]
 \beginverse*\[C]HiddenFontAnchor\endverse\endsong}
\end{ulSongs}
""", r"""
\ulShowKey{true}\ulShowGoodKeys{true}\ulShowTags{true}\ulShowPhase{true}
\ulShowChords{true}\ulShowNotes{false}\ulShowBeats{false}
\newcount\BadgeFontEffects
\renewcommand\ulPreludeBadgeFont{\fontsize{9}{11}\selectfont\normalfont
  \global\advance\BadgeFontEffects1\relax}
\let\OriginalPrelude\ulMakePrelude
\renewcommand\ulMakePrelude{\global\BadgeFontEffects=0\OriginalPrelude
  \typeout{SHARED-FONT:\theulSongNumber:\the\BadgeFontEffects}}
""").replace("oneside,openany,", "oneside,openany,variants={default,lyric,charango,bassclef},", 1)
        for variant in ("default", "lyric", "charango", "bassclef"):
            snapshots = []
            for layers in (False, True):
                with self.subTest(variant=variant, layers=layers):
                    prefix = r"\def\ulBuildVariant{" + variant + "}\n"
                    if layers:
                        prefix += r"\def\ulPdfTranspositionLayers{true}"
                    self.compile_source(prefix + source, passes=3, label=f"font-{variant}-{layers}")
                    final = (self.book / "pass-3.stdout").read_text()
                    self.assertEqual(re.findall(r"SHARED-FONT:(\d+):(\d+)", final),
                                     [("1", "6" if layers else "3"), ("2", "0")])
                    data = (self.book / "book.pdf").read_bytes()
                    snapshots.append(words_and_geometry(data))
                    if layers:
                        manifest = json.loads((self.book / "book.ulsbs-multikey.json").read_text())
                        songs = manifest["multikey_info"]["songs"]
                        self.assertEqual([s["song_id"] for s in songs], ["shared-font", "hidden-font"])
                        self.assertEqual([s["original_key"] for s in songs], ["C", "C"])
                        self.assertTrue(all(s["anchor"] for s in songs))
            self.assertEqual(snapshots[0], snapshots[1])

    def test_title_context_badge_measurements_preserve_effects_and_font_resources(self):
        self.compile_checked(lifecycle.document(r"""
\begin{ulSongs}{}
\beginsong{Badge metrics}[tags={nature},ph={I},key={Am},gk={Bm,Am--C\shrp m}]
\beginverse*
\[Am]A measured lyric.
\endverse
\endsong
\beginsong{Tag-only metrics}[tags={fire}]
\beginverse*
Another measured lyric.
\endverse
\endsong
\end{ulSongs}
\typeout{BADGE-EFFECTS:\the\BadgeEffects}
\directlua{for id,f in font.each() do
 texio.write_nl('BADGE-FONT:'..id..':'..tostring(f.fullname)..':'..tostring(f.size)) end}
""", r"""
\ulShowTags{true}\ulShowPhase{true}
\newcount\BadgeEffects
\renewcommand\ulPreludeTagStyle{\global\advance\BadgeEffects1\relax}
"""), 5)

    def test_zero_width_metadata_is_not_a_visible_badge(self):
        self.compile_checked(lifecycle.document(r"""
\begin{ulSongs}{}
\beginsong{Zero width}[tags={\ZeroText},ph={\ZeroText}]
\beginverse*
No tag or phase badge.
\endverse
\endsong
\beginsong{Visible width}[tags={fire}]
\beginverse*
A visible tag badge.
\endverse
\endsong
\end{ulSongs}
\typeout{BADGE-EFFECTS:\the\BadgeEffects}
\directlua{for id,f in font.each() do
 texio.write_nl('BADGE-FONT:'..id..':'..tostring(f.fullname)..':'..tostring(f.size)) end}
""", r"""
\ulShowTags{true}\ulShowPhase{true}
\newcommand\ZeroText{\relax}
\newcount\BadgeEffects
\renewcommand\ulPreludeTagStyle{\global\advance\BadgeEffects1\relax}
"""), 2)

    def test_key_badges_use_independent_requests_before_real_preludes(self):
        if shutil.which("qpdf") is None:
            self.skipTest("qpdf is required for optional-content inspection")
        preamble = r"""
\ulShowKey{true}\ulShowGoodKeys{true}
\ulShowChords{false}\ulShowNotes{false}\ulShowBeats{false}
\newcount\MainEffects\newcount\GoodEffects\newcount\StyleEffects
\newcount\SourceEffects
\renewcommand\ulPreludeTextKey{\global\advance\MainEffects1 MAINBADGE:}
\renewcommand\ulPreludeTextGoodKeysAlone{\global\advance\GoodEffects1 GOODBADGE:}
\renewcommand\ulPreludeKeyLineStyle{\global\advance\StyleEffects1\relax}
\AddToHook{ulsbs/song/begin}{%
  \ifnum\value{ulSongNumber}=1 \ulLocalShow{goodkeys}{false}\fi
  \ifnum\value{ulSongNumber}=2 \ulLocalShow{key}{false}\fi
  \ifnum\value{ulSongNumber}=3
    \ulLocalShow{key}{false}\ulLocalShow{goodkeys}{false}\fi}
\let\OriginalPrelude\ulMakePrelude
\renewcommand\ulMakePrelude{%
  \global\MainEffects=0 \global\GoodEffects=0 \global\StyleEffects=0
  \OriginalPrelude
  \typeout{KEY-HOOKS:\theulSongNumber:\the\MainEffects/\the\GoodEffects/\the\StyleEffects}}
\ExplSyntaxOn
\cs_new_eq:NN \OriginalBadges \__ulsbs_song_badges:
\cs_set_protected:Npn \__ulsbs_song_badges:
  {\hbox_set:Nn \l_tmpa_box {\OriginalBadges}
   \iow_term:x {KEY-DIMS:\theulSongNumber :
     \dim_eval:n{\box_wd:N\l_tmpa_box},
     \dim_eval:n{\box_ht:N\l_tmpa_box},
     \dim_eval:n{\box_dp:N\l_tmpa_box}}
   \box_use_drop:N\l_tmpa_box}
\NewDocumentCommand\KeyMetadata{}{
  \iow_term:x {KEY-META:\theulSongNumber :
    \prop_item:Nn\l__ulsbs_song_metadata_prop{key}/
    \prop_item:Nn\l__ulsbs_song_metadata_prop{gk}}
}
\ExplSyntaxOff
"""
        body = r"\begin{ulSongs}{}" + "\n"
        for number in range(1, 6):
            body += rf"""
\beginsong{{BadgeSong{number}}}[id={{badge-{number}}},key={{Am}},gk={{Bm}}]
\global\advance\SourceEffects1
\KeyMetadata
\beginverse*
BadgeAnchor{number}
\endverse
\endsong
"""
        body += r"\end{ulSongs}\typeout{KEY-SOURCE:\the\SourceEffects}"
        snapshots = []
        for layers in (False, True):
            with self.subTest(layers=layers):
                prefix = r"\def\ulPdfTranspositionLayers{true}" if layers else ""
                output = self.compile_source(prefix + lifecycle.document(body, preamble),
                                             passes=3, label=f"requests-{layers}")
                final = (self.book / "pass-3.stdout").read_text()
                hooks = {int(number): tuple(map(int, values.split("/")))
                         for number, values in re.findall(r"KEY-HOOKS:(\d+):(\d+/\d+/\d+)", final)}
                self.assertEqual(set(hooks), {1, 2, 3, 4, 5})
                for number, main, good in ((1, True, False), (2, False, True),
                                           (3, False, False), (4, True, True),
                                           (5, True, True)):
                    self.assertEqual(hooks[number][0] > 0, main)
                    self.assertEqual(hooks[number][1], int(good))
                    self.assertEqual(hooks[number][2] > 0, main or good)
                dimensions = dict(re.findall(r"KEY-DIMS:(\d+):([^\r\n]+)", final))
                self.assertEqual(dimensions["3"], "0.0pt,0.0pt,0.0pt")
                # Metadata is consumed upstream even when its badge is hidden.
                self.assertEqual(re.findall(r"KEY-META:(\d+):([^\r\n]+)", final),
                                 [(str(number), "Am/Bm") for number in range(1, 6)])
                self.assertEqual(re.findall(r"KEY-SOURCE:(\d+)", output), ["5"] * 3)
                data = (self.book / "book.pdf").read_bytes()
                words = words_and_geometry(data)
                self.assertEqual(sum(row[1] == "MAINBADGE:" for row in words), 3)
                self.assertEqual(sum(row[1] == "GOODBADGE:" for row in words), 3)
                snapshots.append([row for row in words if row[1].startswith(
                    ("BadgeSong", "BadgeAnchor", "MAINBADGE:", "GOODBADGE:"))])
                structure = PdfStructure(data)
                if layers:
                    self.assertEqual(set(structure.names.values()), {
                        f"ulsbs:transpose:v1:id:badge-{number}:t{offset:02d}"
                        for number in (1, 4, 5) for offset in range(12)})
                    info = json.loads((self.book / "book.ulsbs-multikey.json").read_text())
                    songs = info["multikey_info"]["songs"]
                    self.assertEqual([song["song_id"] for song in songs],
                                     [f"badge-{number}" for number in (1, 4, 5)])
                    self.assertEqual([song["original_key"] for song in songs], ["Am"] * 3)
                    self.assertTrue(all(song["has_transposable_content"] for song in songs))
                    selected = structure.selected_pdf(data, {1: 2, 2: 2, 3: 2})
                    selected_words = words_and_geometry(selected)
                    self.assertEqual(sum(row[1] == "Bm" for row in selected_words), 6)
                else:
                    self.assertFalse(structure.layers)
        self.assertEqual(snapshots[0], snapshots[1])

    def test_denied_key_badges_do_not_execute_display_hooks_or_reserve_space(self):
        source = lifecycle.document(r"""
\begin{ulSongs}{}
\beginsong{Hidden key information}[id={denied},key={Am},gk={Bm}]
\beginverse*
HiddenBadgeAnchor
\endverse
\endsong
\end{ulSongs}
""", r"""
\ulShowKey{false}\ulShowGoodKeys{false}
\ulLocalShow{key}{true}\ulLocalShow{goodkeys}{true}
\renewcommand\ulPreludeKeyLineStyle{\errmessage{Hidden key style executed}}
\renewcommand\ulPreludeTextKey{\errmessage{Hidden main key executed}}
\renewcommand\ulPreludeTextGoodKeysAlone{\errmessage{Hidden good keys executed}}
\renewcommand\ulPreludeBadgeFont{\errmessage{Hidden badge font executed}}
\ExplSyntaxOn
\cs_new_eq:NN \OriginalBadges \__ulsbs_song_badges:
\cs_set_protected:Npn \__ulsbs_song_badges:
  {\hbox_set:Nn \l_tmpa_box {\OriginalBadges}
   \iow_term:x {HIDDEN-BADGES:
     \dim_eval:n{\box_wd:N\l_tmpa_box},
     \dim_eval:n{\box_ht:N\l_tmpa_box},
     \dim_eval:n{\box_dp:N\l_tmpa_box}}
   \box_use_drop:N\l_tmpa_box}
\ExplSyntaxOff
""")
        for layers in (False, True):
            with self.subTest(layers=layers):
                prefix = r"\def\ulPdfTranspositionLayers{true}" if layers else ""
                output = self.compile_source(prefix + source, label=f"denied-{layers}")
                self.assertEqual(re.findall(r"HIDDEN-BADGES:([^\r\n]+)", output),
                                 ["0.0pt,0.0pt,0.0pt"])
                self.assertIn("HiddenBadgeAnchor", lifecycle.SongLifecycleTests.pdf_text(self))

    def test_hidden_direct_tag_phase_adapters_are_opaque_and_allocate_no_badge_rows(self):
        for denied in (False, True):
            permission = str(not denied).lower()
            request = str(denied).lower()
            source = lifecycle.document(r"""
\begingroup
\ulLocalShow{tags}{REQUEST}\ulLocalShow{phase}{REQUEST}
% Bypass ingestion: tag indexing and multikey metadata capture remain eager.
\def\ulTagList{\input{missing-hidden-tags}\iftrue}
\def\ulPhaseList{\input{missing-hidden-phase}\iffalse}
\renewcommand\ulPreludeTagStyle{\errmessage{Hidden tag style executed}}
\renewcommand\ulPreludePhaseStyle{\errmessage{Hidden phase style executed}}
\renewcommand\ulPreludeBadgeFont{\errmessage{Hidden badge font executed}}
\ExplSyntaxOn
\hbox_set:Nn \l_tmpa_box {\__ulsbs_song_badges:
  \iow_term:x {HIDDEN-ROWS:\int_use:N\l__ulsbs_song_badge_row_int}}
\iow_term:x {HIDDEN-DIMS:\dim_eval:n{\box_wd:N\l_tmpa_box},
  \dim_eval:n{\box_ht:N\l_tmpa_box},\dim_eval:n{\box_dp:N\l_tmpa_box}}
\vbox_set:Nn \l_tmpa_box {\__ulsbs_song_badges:
  \iow_term:x {HIDDEN-ROWS:\int_use:N\l__ulsbs_song_badge_row_int}}
\iow_term:x {HIDDEN-DIMS:\dim_eval:n{\box_wd:N\l_tmpa_box},
  \dim_eval:n{\box_ht:N\l_tmpa_box},\dim_eval:n{\box_dp:N\l_tmpa_box}}
\ExplSyntaxOff
\endgroup
HiddenBadgeAnchor
""".replace("REQUEST", request), r"""
\ulShowTags{PERMISSION}\ulShowPhase{PERMISSION}
\ulShowPhaseInToc{false}\ulShowKey{false}\ulShowGoodKeys{false}
""".replace("PERMISSION", permission))
            for layers in (False, True):
                with self.subTest(denied=denied, layers=layers):
                    prefix = r"\def\ulPdfTranspositionLayers{true}" if layers else ""
                    output = self.compile_source(prefix + source, label=f"opaque-{denied}-{layers}")
                    self.assertEqual(re.findall(r"HIDDEN-ROWS:(\d+)", output), ["0", "0"])
                    self.assertEqual(re.findall(r"HIDDEN-DIMS:([^\r\n]+)", output),
                                     ["0.0pt,0.0pt,0.0pt"] * 2)
                    self.assertIn("HiddenBadgeAnchor", lifecycle.SongLifecycleTests.pdf_text(self))

    def test_independent_hidden_badges_and_natural_zero_width_rows(self):
        body = ""
        for name, tags, phase in (("hidden-tags", False, True),
                                  ("hidden-phase", True, False),
                                  ("zero-width", True, True)):
            tag_text = (r"\vrule width0pt height17pt depth9pt" if name == "zero-width"
                        else "VisibleTag" if tags else r"\input{missing-hidden-tags}\iftrue")
            phase_text = (r"\vrule width0pt height19pt depth7pt" if name == "zero-width"
                          else "VisiblePhase" if phase else r"\input{missing-hidden-phase}\iffalse")
            body += rf"""
\begingroup
\ulLocalShow{{tags}}{{{str(tags).lower()}}}\ulLocalShow{{phase}}{{{str(phase).lower()}}}
\def\ulTagList{{{tag_text}}}\def\ulPhaseList{{{phase_text}}}
\global\TagEffects=0 \global\PhaseEffects=0
\ExplSyntaxOn
\hbox_set:Nn \l_tmpa_box {{\__ulsbs_song_badges:
  \iow_term:x {{NATURAL-ROWS:{name}:\int_use:N\l__ulsbs_song_badge_row_int}}}}
\iow_term:x {{NATURAL-DIMS:{name}:\dim_eval:n{{\box_wd:N\l_tmpa_box}},
  \dim_eval:n{{\box_ht:N\l_tmpa_box}},\dim_eval:n{{\box_dp:N\l_tmpa_box}}}}
\ExplSyntaxOff
\typeout{{NATURAL-HOOKS:{name}:\the\TagEffects/\the\PhaseEffects}}
\endgroup
"""
        source = lifecycle.document(body + "NaturalWidthAnchor", r"""
\ulShowTags{true}\ulShowPhase{true}\ulShowPhaseInToc{false}
\ulShowKey{false}\ulShowGoodKeys{false}
\newcount\TagEffects\newcount\PhaseEffects
\renewcommand\ulPreludeTagStyle{\global\advance\TagEffects1\relax}
\renewcommand\ulPreludePhaseStyle{\global\advance\PhaseEffects1\relax}
""")
        for layers in (False, True):
            with self.subTest(layers=layers):
                prefix = r"\def\ulPdfTranspositionLayers{true}" if layers else ""
                output = self.compile_source(prefix + source, label=f"natural-{layers}")
                self.assertEqual(re.findall(r"NATURAL-ROWS:([^:]+):(\d+)", output),
                                 [("hidden-tags", "1"), ("hidden-phase", "1"), ("zero-width", "0")])
                self.assertEqual(re.findall(r"NATURAL-DIMS:[^:]+:([^\r\n]+)", output),
                                 ["0.0pt,0.0pt,0.0pt"] * 3)
                self.assertEqual([(name, tuple(int(v) > 0 for v in effects.split("/")))
                                  for name, effects in re.findall(
                                      r"NATURAL-HOOKS:([^:]+):(\d+/\d+)", output)],
                                 [("hidden-tags", (False, True)),
                                  ("hidden-phase", (True, False)),
                                  ("zero-width", (False, False))])

    def test_tag_phase_requests_preserve_metadata_indices_exports_and_geometry(self):
        combinations = list(itertools.product((False, True), repeat=3))
        preamble = r"""
\ulShowTags{true}\ulShowPhase{true}\ulShowPhaseInToc{true}
\ulShowKey{false}\ulShowGoodKeys{false}
\newcount\TagEffects\newcount\PhaseEffects\newcount\BadgeSourceEffects
\renewcommand\ulPreludeTagStyle{\global\advance\TagEffects1\relax}
\renewcommand\ulPreludePhaseStyle{\global\advance\PhaseEffects1\relax}
\let\OriginalPrelude\ulMakePrelude
\renewcommand\ulMakePrelude{%
  \global\TagEffects=0 \global\PhaseEffects=0
  \OriginalPrelude
  \typeout{TAG-PHASE-HOOKS:\theulSongNumber:\the\TagEffects/\the\PhaseEffects}}
\ExplSyntaxOn
\cs_new_eq:NN \OriginalBadges \__ulsbs_song_badges:
\cs_set_protected:Npn \__ulsbs_song_badges:
  {\OriginalBadges
   \iow_term:x {TAG-PHASE-ROWS:\theulSongNumber :
     \int_use:N\l__ulsbs_song_badge_row_int}}
\NewDocumentCommand\BadgeMetadata{}{
  \iow_term:x {TAG-PHASE-META:\theulSongNumber :
    \prop_item:Nn\l__ulsbs_song_metadata_prop{tags}/
    \prop_item:Nn\l__ulsbs_song_metadata_prop{ph}}}
\ExplSyntaxOff
"""
        body = r"\tableofcontents\begin{ulSongs}{titleidx,tagidx}" + "\n"
        for number, requests in enumerate(combinations, 1):
            body += "\\begingroup\n" + "".join(
                r"\ulLocalShow{" + key + "}{" + str(value).lower() + "}"
                for key, value in zip(("tags", "phase", "phaseintoc"), requests, strict=True))
            body += rf"""
\beginsong{{PhaseSong{number}}}[id={{phase-{number}}},key={{Am}},tags={{fire}},ph={{PhaseMark{number}}}]
\global\advance\BadgeSourceEffects1
\BadgeMetadata
\beginverse*
\[Am]PhaseAnchor{number}
\endverse
\endsong
\endgroup
"""
        body += (r"\end{ulSongs}\ulLocalShow{phaseintoc}{false}"
                 r"\typeout{BADGE-SOURCE:\the\BadgeSourceEffects}")
        for variant in ("default", "lyric", "charango", "bassclef"):
            snapshots = []
            exports = []
            for layers in (False, True):
                with self.subTest(variant=variant, layers=layers):
                    source = lifecycle.document(body, preamble).replace(
                        "oneside,openany,",
                        "oneside,openany,variants={default,lyric,charango,bassclef},", 1)
                    prefix = r"\def\ulBuildVariant{" + variant + "}\n"
                    if layers:
                        prefix += r"\def\ulPdfTranspositionLayers{true}"
                    output = self.compile_source(prefix + source, passes=3,
                                                 label=f"phase-{variant}-{layers}")
                    final = (self.book / "pass-3.stdout").read_text()
                    self.assertEqual(re.findall(r"TAG-PHASE-META:(\d+):([^\r\n]+)", final),
                                     [(str(n), f"fire/PhaseMark{n}") for n in range(1, 9)])
                    self.assertEqual(re.findall(r"BADGE-SOURCE:(\d+)", output), ["8"] * 3)
                    hooks = dict(re.findall(r"TAG-PHASE-HOOKS:(\d+):(\d+/\d+)", final))
                    rows = dict(re.findall(r"TAG-PHASE-ROWS:(\d+):(\d+)", final))
                    toc = (self.book / "book.toc").read_text()
                    self.assertNotIn("ifulShowPhaseInToc", toc)
                    self.assertNotIn("phaseintoc", toc)
                    for n, (tags, phase, phaseintoc) in enumerate(combinations, 1):
                        # Visible measurement can execute styles repeatedly. Only
                        # hidden hooks promise zero effects, not once-only display.
                        self.assertEqual(tuple(int(v) > 0 for v in hooks[str(n)].split("/")),
                                         (tags, phase))
                        self.assertEqual(rows[str(n)], str(int(tags or phase)))
                        self.assertEqual(f"PhaseMark{n}" in toc, phaseintoc)
                    self.assertEqual(lifecycle.index_records(self.book, "idx_tag"),
                                     [("fire", str(n), f"song1-{n}.1") for n in range(1, 9)])
                    exports.append([line.split("|")[1:3] for line in
                                    (self.book / "book.ulsbs.psv").read_text().splitlines()
                                    if line.startswith("ID-NR-PAGE-Y|")])
                    self.assertEqual(exports[-1], [[f"phase-{n}", str(n)] for n in range(1, 9)])
                    data = (self.book / "book.pdf").read_bytes()
                    words = words_and_geometry(data)
                    self.assertEqual(sum(row[1] == "fire" for row in words), 4)
                    for n, (_, phase, phaseintoc) in enumerate(combinations, 1):
                        self.assertEqual(sum(row[1] == f"PhaseMark{n}" for row in words),
                                         int(phase) + int(phaseintoc))
                    snapshots.append([row for row in words if row[1].startswith(
                        ("PhaseSong", "PhaseAnchor", "PhaseMark", "fire"))])
                    if layers:
                        info = json.loads((self.book / "book.ulsbs-multikey.json").read_text())
                        songs = info["multikey_info"]["songs"]
                        transposable = range(1, 9) if variant in ("default", "charango") else ()
                        self.assertEqual([song["song_id"] for song in songs],
                                         [f"phase-{n}" for n in transposable])
                        self.assertEqual([song["original_key"] for song in songs],
                                         ["Am"] * len(transposable))
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(exports[0], exports[1])

    def test_phase_toc_choice_is_source_scoped_for_selected_retained_writes(self):
        body = r"""
\directlua{for _,suffix in ipairs({'aux','toc'}) do
  local f=io.open(tex.jobname..'.'..suffix,'rb')
  if f then texio.write_nl('TOC-STATE:'..suffix..':'..md5.sumhexa(f:read('*a'))) f:close() end
end}
\tableofcontents
\ulIncludeOnlySongs{3,1}
\begin{ulSongs}{titleidx,tagidx}
"""
        for n, visible in enumerate((True, True, False, False), 1):
            body += rf"""
\begingroup
\ulLocalShow{{phaseintoc}}{{{str(visible).lower()}}}
\beginsong{{RetainedSong{n}}}[id={{retained-{n}}},tags={{fire}},ph={{RetainedPhase{n}}}]
% Invert the request after the source-time TOC decision, before retained shipout.
\ulLocalShow{{phaseintoc}}{{{str(not visible).lower()}}}
\beginverse*
RetainedAnchor{n}
\endverse
\endsong
\endgroup
"""
        body += r"\end{ulSongs}\ulLocalShow{phaseintoc}{false}"
        for layers in (False, True):
            with self.subTest(layers=layers):
                prefix = r"\def\ulPdfTranspositionLayers{true}" if layers else ""
                self.compile_source(prefix + lifecycle.document(body, r"""
\ulShowPhaseInToc{true}\ulShowKey{false}\ulShowGoodKeys{false}
"""), passes=4, label=f"toc-retained-{layers}")
                states = [re.findall(r"TOC-STATE:(aux|toc):([a-f0-9]+)",
                                     (self.book / f"pass-{n}.stdout").read_text()) for n in (3, 4)]
                self.assertEqual(len(states[0]), 2)
                self.assertEqual(states[0], states[1], "Auxiliary and TOC data must converge")
                for suffix in ("aux", "toc"):
                    text = (self.book / f"book.{suffix}").read_text()
                    self.assertIn("RetainedPhase1", text)
                    for n in (2, 3, 4):
                        self.assertNotIn(f"RetainedPhase{n}", text)
                    self.assertLess(text.index("RetainedSong3"), text.index("RetainedSong1"))
                    self.assertNotIn("ifulShowPhaseInToc", text)
                    self.assertNotIn("phaseintoc", text)
                self.assertEqual(lifecycle.index_records(self.book, "idx_tag"),
                                 [("fire", str(n), f"song1-{n}.1") for n in (3, 1)])

    def test_author_and_offered_to_separators_match_in_both_languages_and_editions(self):
        source = lifecycle.document(r"""
\begin{ulSongs}{}
\beginsong{Author and dedication}[by={Author},off={Recipient}]
\beginverse*
A dedication with its author.
\endverse
\endsong
\beginsong{Author only}[by={Author}]
\endsong
\beginsong{Dedication only}[off={Recipient}]
\endsong
\ulLocalShow{authors}{false}
\beginsong{Hidden author}[by={Author},off={Recipient}]
\endsong
\ulLocalShow{authors}{true}\ulLocalShow{offeredto}{false}
\beginsong{Hidden dedication}[by={Author},off={Recipient}]
\endsong
\end{ulSongs}
""", r"\ulShowAuthors{true}\ulShowOfferedTo{true}")
        for language in ("english", "portuguese"):
            for edition in ("default", "lyric"):
                name = language + "-" + edition
                selected = (r"\def\ulBuildVariant{" + edition + "}\n"
                             + source.replace("oneside,openany,",
                                              "oneside,openany,variants={default,lyric},language="
                                              + language + ",", 1))
                self.compile_source(selected, label=name)
                text = lifecycle.SongLifecycleTests.pdf_text(self)
                self.assertIn("Recipient", text)
                self.assertIn("Author", text)

    def test_textual_prelude_permission_request_matrix_retains_visible_layout_once(self):
        features = ("authors", "offeredto", "extrainfo")
        setters = ("Authors", "OfferedTo", "ExtraInfo")
        preamble = r"""
\newcount\AuthorEffects\newcount\OfferedEffects\newcount\ExtraEffects
\newbox\Actual\newbox\Expected
\newcommand\ReportTextBox[1]{\typeout{TEXT-DIMS:#1:\the\wd\Actual,\the\ht\Actual,\the\dp\Actual}}
"""
        for permissions in itertools.product((False, True), repeat=3):
            policy = "".join(r"\ulShow" + setter + "{" + str(value).lower() + "}"
                             for setter, value in zip(setters, permissions, strict=True))
            body = ""
            expected_effects = []
            for number, requests in enumerate(itertools.product((False, True), repeat=3)):
                effective = tuple(p and r for p, r in zip(permissions, requests, strict=True))
                expected_effects.append((str(number), "/".join(str(int(v)) for v in effective)))
                body += "\\begingroup\n" + "".join(
                    r"\ulLocalShow{" + feature + "}{" + str(value).lower() + "}"
                    for feature, value in zip(features, requests, strict=True))
                # The reference spells out the established separator/font/paragraph
                # contract independently of the visibility implementation.
                attribution = (r"{\bfseries\sfcode`\.=1000\relax Author words that wrap}~"
                               if effective[0] else "")
                if effective[1]:
                    attribution += r"~(\textit{offered~to:}~Recipient words that wrap)"
                extra = r"Extra first line\\Extra second line\par" if effective[2] else ""
                paragraph = r"\par " if attribution else ""
                body += rf"""
\AuthorEffects=0 \OfferedEffects=0 \ExtraEffects=0
\def\ulSongAuthors{{\global\advance\AuthorEffects1 Author words that wrap}}
\def\ulOfferedTo{{\global\advance\OfferedEffects1 Recipient words that wrap}}
\def\ulExtraInfo{{\global\advance\ExtraEffects1 Extra first line\\Extra second line}}
\setbox\Actual=\vbox{{\hsize=95pt\parindent=0pt\parskip=1pt\ulExtendPrelude}}
\typeout{{TEXT-EFFECTS:{number}:\the\AuthorEffects/\the\OfferedEffects/\the\ExtraEffects}}
\setbox\Expected=\vbox{{\hsize=95pt\parindent=0pt\parskip=1pt
  {attribution}{paragraph}{extra}}}
\ifdim\wd\Actual=\wd\Expected\else\errmessage{{Prelude width changed}}\fi
\ifdim\ht\Actual=\ht\Expected\else\errmessage{{Prelude height changed}}\fi
\ifdim\dp\Actual=\dp\Expected\else\errmessage{{Prelude depth changed}}\fi
\ReportTextBox{{{number}}}
\box\Actual\endgroup
"""
            with self.subTest(permissions=permissions):
                output = self.compile_source(lifecycle.document(body, preamble + policy),
                                             label="policy-" + "".join(str(int(p)) for p in permissions))
                self.assertEqual(re.findall(r"TEXT-EFFECTS:(\d+):(\d/\d/\d)", output),
                                 expected_effects)
                dimensions = dict(re.findall(r"TEXT-DIMS:(\d+):([^\r\n]+)", output))
                for number, effects in expected_effects:
                    if effects == "0/0/0":
                        self.assertEqual(dimensions[number], "0.0pt,0.0pt,0.0pt")

    def test_hidden_direct_text_adapters_are_opaque_and_zero_width_attribution_is_dropped(self):
        source = lifecycle.document(r"""
\begingroup
\ulLocalShow{authors}{false}\ulLocalShow{offeredto}{false}\ulLocalShow{extrainfo}{false}
% Deliberately bypass ingestion: author indexing/multikey capture is not opaque.
\def\ulSongAuthors{\input{missing-hidden-author}\iftrue}
\def\ulOfferedTo{\input{missing-hidden-offered}\iffalse}
\def\ulExtraInfo{\input{missing-hidden-extra}\iftrue}
\def\bfseries{\errmessage{Hidden author style executed}}
\def\ulIfLanguage#1#2#3{\errmessage{Hidden dedication label executed}}
\setbox\Actual=\hbox{\ulExtendPrelude}
\ReportTextBox{hidden-horizontal}
\setbox\Actual=\vbox{\ulExtendPrelude}
\ReportTextBox{hidden-vertical}
\endgroup
\begingroup
\ulLocalShow{offeredto}{false}\ulLocalShow{extrainfo}{false}
\def\ulSongAuthors{\relax}
\setbox\Actual=\hbox{\ulExtendPrelude}
\edef\CancelSpace{\the\wd\Actual}
% A zero-width source still runs once, but the retained box must not be
% unpacked into a phantom paragraph even if it contains tall invisible ink.
\def\ulSongAuthors{\global\advance\AuthorEffects1
  \vrule width0pt height12pt\kern-\CancelSpace}
\AuthorEffects=0
\setbox\Actual=\vbox{\ulExtendPrelude}
\ReportTextBox{zero-width}
\typeout{ZERO-EFFECTS:\the\AuthorEffects}
\endgroup
VisibleAnchor
""", r"""
\ulShowAuthors{true}\ulShowOfferedTo{true}\ulShowExtraInfo{true}
\newcount\AuthorEffects\newbox\Actual
\newcommand\ReportTextBox[1]{\typeout{TEXT-DIMS:#1:\the\wd\Actual,\the\ht\Actual,\the\dp\Actual}}
""")
        output = self.compile_source(source)
        self.assertEqual(re.findall(r"TEXT-DIMS:([^:]+):([^\r\n]+)", output), [
            (name, "0.0pt,0.0pt,0.0pt")
            for name in ("hidden-horizontal", "hidden-vertical", "zero-width")])
        self.assertEqual(re.findall(r"ZERO-EFFECTS:(\d+)", output), ["1"])
        self.assertIn("VisibleAnchor", lifecycle.SongLifecycleTests.pdf_text(self))

    def test_textual_prelude_song_combinations_preserve_metadata_indices_and_editions(self):
        combinations = list(itertools.product((False, True), repeat=3))
        preamble = r"""
\ulShowAuthors{true}\ulShowOfferedTo{true}\ulShowExtraInfo{true}
\ulShowKey{false}\ulShowGoodKeys{false}
\newbox\TextPrelude
\let\OriginalExtendPrelude\ulExtendPrelude
\renewcommand\ulExtendPrelude{%
  \setbox\TextPrelude=\vbox{\OriginalExtendPrelude}%
  \typeout{SONG-TEXT-DIMS:\theulSongNumber:\the\wd\TextPrelude,\the\ht\TextPrelude,\the\dp\TextPrelude}%
  \box\TextPrelude}
\ExplSyntaxOn
\NewDocumentCommand\TextMetadata{}{%
  \iow_term:x {TEXT-META:\theulSongNumber :
    \prop_item:Nn\l__ulsbs_song_metadata_prop{by}/
    \prop_item:Nn\l__ulsbs_song_metadata_prop{off}/
    \prop_item:Nn\l__ulsbs_song_metadata_prop{ex}}}
\ExplSyntaxOff
"""
        body = r"\begin{ulSongs}{titleidx,authidx}" + "\n"
        for number, visible in enumerate(combinations, 1):
            body += "\\begingroup\n" + "".join(
                r"\ulLocalShow{" + key + "}{" + str(value).lower() + "}"
                for key, value in zip(("authors", "offeredto", "extrainfo"), visible, strict=True))
            body += rf"""
\beginsong{{TextSong{number}}}[id={{text-{number}}},key={{Am}},
 by={{Author{number}}},off={{Recipient{number}}},ex={{Extra{number}}}]
\TextMetadata
\beginverse*
\[Am]TextAnchor{number}
\endverse
\endsong
\endgroup
"""
        body += r"\end{ulSongs}"
        for language in ("english", "portuguese"):
            for variant in ("default", "lyric"):
                snapshots = []
                dimensions = []
                exports = []
                for layers in (False, True):
                    with self.subTest(language=language, variant=variant, layers=layers):
                        source = lifecycle.document(body, preamble).replace(
                            "oneside,openany,", "oneside,openany,variants={default,lyric},language="
                            + language + ",", 1)
                        prefix = r"\def\ulBuildVariant{" + variant + "}\n"
                        if layers:
                            prefix += r"\def\ulPdfTranspositionLayers{true}"
                        self.compile_source(prefix + source, passes=3,
                                            label=f"text-{language}-{variant}-{layers}")
                        final = (self.book / "pass-3.stdout").read_text()
                        self.assertEqual(re.findall(r"TEXT-META:(\d+):([^\r\n]+)", final), [
                            (str(n), f"Author{n}/Recipient{n}/Extra{n}") for n in range(1, 9)])
                        measured = dict(re.findall(r"SONG-TEXT-DIMS:(\d+):([^\r\n]+)", final))
                        self.assertEqual(measured["1"], "0.0pt,0.0pt,0.0pt")
                        dimensions.append(measured)
                        text = lifecycle.SongLifecycleTests.pdf_text(self)
                        for n, (author, offered, extra) in enumerate(combinations, 1):
                            self.assertEqual(f"Author{n}" in text, author)
                            self.assertEqual(f"Recipient{n}" in text, offered)
                            self.assertEqual(f"Extra{n}" in text, extra)
                        self.assertEqual(text.count("offered to:" if language == "english"
                                                    else "ofert. para:"), 4)
                        # These words are outside OCG alternatives, so raw bbox
                        # extraction needs no optional-content PDF rewriting.
                        xml = ET.fromstring(pdf_command((self.book / "book.pdf").read_bytes(),
                                                        ["pdftotext", "-bbox", "{pdf}", "-"]))
                        snapshots.append([
                            (page_number, word.text, *(round(float(word.get(key)), 2)
                              for key in ("xMin", "yMin", "xMax", "yMax")))
                            for page_number, page in enumerate(xml.iter(
                                "{http://www.w3.org/1999/xhtml}page"))
                            for word in page.iter("{http://www.w3.org/1999/xhtml}word")
                            if (word.text or "").startswith(
                                ("TextSong", "TextAnchor", "Author", "Recipient", "Extra"))])
                        self.assertEqual([row[0] for row in lifecycle.index_records(
                            self.book, "idx_auth")], [f"Author{n}" for n in range(1, 9)])
                        exports.append([line.split("|")[1:3] for line in
                                        (self.book / "book.ulsbs.psv").read_text().splitlines()
                                        if line.startswith("ID-NR-PAGE-Y|")])
                        self.assertEqual(exports[-1], [[f"text-{n}", str(n)] for n in range(1, 9)])
                        if layers:
                            info = json.loads((self.book / "book.ulsbs-multikey.json").read_text())
                            # Hidden text must not remove unrelated chord families;
                            # lyric has neither visible chords nor a key-badge anchor.
                            transposable = range(1, 9) if variant == "default" else ()
                            self.assertEqual([song["song_id"] for song in info["multikey_info"]["songs"]],
                                             [f"text-{n}" for n in transposable])
                            self.assertEqual([song["original_key"] for song in info["multikey_info"]["songs"]],
                                             ["Am"] * len(transposable))
                self.assertEqual(snapshots[0], snapshots[1])
                self.assertEqual(dimensions[0], dimensions[1])
                self.assertEqual(exports[0], exports[1])


if __name__ == "__main__":
    unittest.main()
