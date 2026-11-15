# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scoped song layout, retained selections and physical LaTeX column modes."""

import os
from pathlib import Path
import re
import unittest

import test_song_lifecycle as lifecycle
import test_song_order as order
from test_tex_integration import ROOT


def song(name, lines=8):
    body = "\n".join(
        rf"\Effect {name} line {number}: words long enough to distinguish full and half width."
        for number in range(lines))
    return (rf"\beginsong{{{name}}}[id={{{name}}},by={{Scope Author}},tags={{fire}}]"
            + "\n" + r"\beginverse*" + "\n" + body + "\n"
            + r"\endverse\endsong" + "\n")


PREAMBLE = r"""
\newcount\Effects
\def\Effect{\global\advance\Effects1\relax}
"""


class LayoutScopeTests(unittest.TestCase):
    setUp = lifecycle.SongLifecycleTests.setUp
    compile_source = lifecycle.SongLifecycleTests.compile_source
    compile_checked = order.SongOrderTests.compile_checked

    @classmethod
    def setUpClass(cls):
        lifecycle.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_LAYOUT_SCOPE_DIAGNOSTICS", ROOT / "build/layout-scope"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def check(self, body, *, lyrics=False, selection="", effects=24, label="case"):
        preamble = PREAMBLE + selection
        if lyrics:
            preamble += r"\chordsoff"
        source = lifecycle.document(
            r"\begin{ulSongs}{titleidx,authidx,tagidx}" + "\n" + body
            + r"\end{ulSongs}\typeout{EFFECTS:\the\Effects}", preamble)
        outputs = self.compile_checked(source, label)
        for output in outputs.values():
            self.assertEqual(re.findall(r"EFFECTS:(\d+)", output), [str(effects)] * 2)
        return outputs

    def test_title_badge_overlap_is_a_scoped_boolean_not_visibility_policy(self):
        source = lifecycle.document(r"""
\ifulTitleBadgeOverlap\errmessage{Expected default false}\fi
\iffalse\ifulTitleBadgeOverlap\errmessage{Skipped predicate}\fi\fi
{\ulTitleBadgeOverlap{true}
 \ifulTitleBadgeOverlap\else\errmessage{Expected local true}\fi
 {\ulTitleBadgeOverlap{false}
  \ifulTitleBadgeOverlap\errmessage{Expected nested false}\fi}
 \ifulTitleBadgeOverlap\else\errmessage{Lost enclosing true}\fi}
\ifulTitleBadgeOverlap\errmessage{Leaked local true}\fi
\ulTitleBadgeOverlap{true}
\ifulTitleBadgeOverlap\else\errmessage{Body setter was frozen}\fi
\ulTitleBadgeOverlap{false}
\ifulTitleBadgeOverlap\errmessage{Body setter did not reset}\fi
\typeout{TITLE-BADGE-BOOLEAN:OK}
Text.
""")
        self.assertIn("TITLE-BADGE-BOOLEAN:OK", self.compile_source(source))
        for number, value in enumerate(("yes", r"\ComputedBoolean")):
            with self.subTest(value=value):
                source = lifecycle.document(
                    rf"\ulTitleBadgeOverlap{{{value}}}Text.",
                    r"\def\ComputedBoolean{true}")
                self.compile_source(source, failure="Invalid boolean value",
                                    label=f"invalid-{number}")

    def test_bottom_glue_is_independent_scoped_policy_and_matches_break_probes(self):
        probe = r"""
\newskip\ActualGlue\newskip\ExpectedGlue
\newcommand\CheckGlue[1]{%
  \begingroup
  \ActualGlue=\ulColumnBottomGlue\relax\ExpectedGlue=#1\relax
  \edef\Actual{\the\ActualGlue}\edef\Expected{\the\ExpectedGlue}%
  \ifx\Actual\Expected\else\errmessage{Bottom glue changed: \Actual/\Expected}\fi
  \endgroup}
\newbox\BreakBox\newbox\CandidateBox\newbox\ProbeBox
\newcommand\CheckBreaks{%
  \setbox\BreakBox\vbox{\hbox{Before}\vskip7pt plus 3pt minus 1pt
    \csname __ulsbs_layout_break:n\endcsname{317}\hbox{After}}%
  \setbox\CandidateBox\vbox{\hbox{Candidate}}%
  \ActualGlue=\ulColumnBottomGlue\relax
  \directlua{
    local w,s,h,so,ho=tex.getglue('ActualGlue')
    local function same(n,sign)
      assert(n and n.id==node.id('glue'),'Missing bottom glue')
      assert(n.width==sign*w and n.stretch==sign*s and n.shrink==sign*h,
        'Bottom glue dimensions differ: '..table.concat({n.width,n.stretch,n.shrink,w,s,h,sign},','))
      assert(n.stretch_order==so and n.shrink_order==ho,'Glue orders differ')
    end
    local function check(b,previous)
      local found=false
      for n in node.traverse(tex.box[b].head) do
        if n.id==node.id('penalty') and n.penalty==317 then
          same(n.prev,1);same(n.next,-1);found=true
          if previous then
            local p=n.next.next
            assert(p.width==7*65536 and p.stretch==3*65536 and p.shrink==65536
              and p.stretch_order==0 and p.shrink_order==0,'Prior skip lost')
          end
        end
      end
      assert(found,'Missing candidate break')
    end
    check(\number\BreakBox,true)
    ulsbs_layout.combine_page(\number\CandidateBox,\number\ProbeBox,317,0,'ActualGlue')
    check(\number\ProbeBox)
  }%
  \setbox\BreakBox\vbox{\hbox{Forced}\csname __ulsbs_layout_break:\endcsname}%
  \directlua{
    local n=node.tail(tex.box[\number\BreakBox].head)
    assert(n.penalty==-10000,'Missing forced break')
    local w,s,h,so,ho=tex.getglue('ActualGlue');n=n.prev
    assert(n.width==w and n.stretch==s and n.shrink==h
      and n.stretch_order==so and n.shrink_order==ho,'Forced glue differs')
  }}
\CheckGlue{0pt plus .5\textheight}
\begin{document}
\CheckGlue{0pt plus .5\textheight}\CheckBreaks
{\chordsoff\notesoff\beatsoff
 \CheckGlue{0pt plus .5\textheight}
 \chordson\noteson\beatson\measuresoff\ulLocalShow{scores}{false}
 \CheckGlue{0pt plus .5\textheight}}
{\renewcommand\ulColumnBottomGlue{3pt plus 19pt minus 2pt}
 \CheckGlue{3pt plus 19pt minus 2pt}\CheckBreaks
 {\chordsoff\notesoff\beatsoff\CheckGlue{3pt plus 19pt minus 2pt}}
 {\ulSeparateVerses\CheckGlue{0pt plus 1fil}\CheckBreaks}
 \CheckGlue{3pt plus 19pt minus 2pt}}
{\renewcommand\ulColumnBottomGlue{0pt}\CheckGlue{0pt}\CheckBreaks}
\CheckGlue{0pt plus .5\textheight}
\begin{ulSongs}{}\beginsong{Glue requests}[id={glue},key={C}]
\beginverse*
\chordsoff\notesoff\beatsoff\CheckGlue{0pt plus .5\textheight}
Hidden lyric.
\endverse
{\ulSeparateVerses
\beginverse*
\CheckGlue{0pt plus 1fil}Separated lyric.
\endverse}
\CheckGlue{0pt plus .5\textheight}\endsong
\end{ulSongs}\CheckGlue{0pt plus .5\textheight}
\typeout{GLUE-POLICY:OK}\end{document}
"""
        entries = [(name, r"\documentclass[variants={default,lyric,charango,bassclef},"
                    r"oneside,openany]{ulsbs-songbook}")
                   for name in ("default", "lyric", "charango", "bassclef")]
        entries.append(("package", r"\documentclass[oneside,openany]{book}\usepackage{ulsbs}"))
        for name, entry in entries:
            for layers in (False, True):
                with self.subTest(entry=name, layers=layers):
                    source = (r"\def\ulPdfTranspositionLayers{"
                              + str(layers).lower() + "}\n")
                    if name not in ("default", "package"):
                        source += rf"\def\ulBuildVariant{{{name}}}" + "\n"
                    output = self.compile_source(source + entry + probe,
                                                 label=f"{name}-{layers}")
                    self.assertIn("GLUE-POLICY:OK", output)

    def test_authored_bottom_glue_survives_selected_repeated_column_layout(self):
        for columns in (1, 2):
            for layers in (False, True):
                with self.subTest(columns=columns, layers=layers):
                    preamble = PREAMBLE + rf"""
\ulSongColumns{{{columns}}}\ulSongPosition{{3}}
\ulIncludeOnlySongs{{2,1,2}}
\renewcommand\ulColumnBottomGlue{{0pt plus 37pt minus 2pt}}
\AddToHook{{ulsbs/stanza/start}}{{%
  \skip0=\ulColumnBottomGlue\relax
  \ifdim\gluestretch\skip0=37pt\else\errmessage{{Lost authored glue}}\fi}}
"""
                    body = song("First", 14) + "{\n" + r"\chordsoff\notesoff\beatsoff" + "\n"
                    body += song("Second", 14) + "}\n" + song("Excluded", 4)
                    source = lifecycle.document(
                        r"\begin{ulSongs}{titleidx,authidx,tagidx}" + "\n" + body
                        + r"\end{ulSongs}\typeout{EFFECTS:\the\Effects}", preamble)
                    source = (r"\def\ulPdfTranspositionLayers{" + str(layers).lower()
                              + "}\n" + source)
                    output = self.compile_source(source, passes=3,
                                                 label=f"columns-{columns}-layers-{layers}")
                    self.assertEqual(re.findall(r"EFFECTS:(\d+)", output), ["32"] * 3)
                    text = lifecycle.SongLifecycleTests.pdf_text(self)
                    self.assertEqual(text.count("Second line 0:"), 2)
                    self.assertEqual(text.count("First line 0:"), 1)
                    self.assertNotIn("Excluded line", text)
                    rows = [line.split("|")[1] for line in
                            (self.book / "book.ulsbs.psv").read_text().splitlines()
                            if line.startswith("ID-NR-PAGE-Y|")]
                    self.assertEqual(rows, ["Second", "First", "Second"])

    def test_grouped_excluded_columns_do_not_change_selection_commit(self):
        body = song("First") + song("Second") + "{\n" + r"""
\chordsoff\small\ulSongColumns{2}\ulSongPosition{1}
""" + song("Excluded") + "}\n"
        for lyrics in (False, True):
            with self.subTest(lyrics=lyrics):
                self.check(body, lyrics=lyrics, selection=r"\ulIncludeOnlySongs{2,1,2}",
                           label=f"lyrics-{lyrics}")

    def test_mixed_selected_width_groups_and_repeated_labels(self):
        body = song("Wide") + "{\n" + r"\ulSongColumns{2}\ulSongPosition{1}" + "\n"
        body += song("Narrow") + "}\n" + song("Restored")
        self.check(body, selection=r"\ulIncludeOnlySongs{2,1,2,3}")

    def test_nonselection_grouped_columns_restore_before_next_song(self):
        body = song("Before") + "{\n" + r"\ulSongColumns{2}\ulSongPosition{1}" + "\n"
        body += song("Narrow") + "}\n" + song("After")
        self.check(body)

    def test_nonselection_grouped_columns_restore_at_songs_end(self):
        body = song("Before") + "{\n" + r"\ulSongColumns{2}\ulSongPosition{1}" + "\n"
        body += song("Narrow") + "}\n"
        self.check(body, effects=16)

    def test_nonselection_short_and_multipage_pending_column_restoration(self):
        for lines in (3, 24):
            with self.subTest(lines=lines):
                body = song("Before", 4) + "{\n" + r"\ulSongColumns{2}\ulSongPosition{1}" + "\n"
                body += song("Narrow", lines) + "}\n" + song("After", 4)
                self.check(body, effects=lines + 8, label=f"lines-{lines}")

    def test_nonselection_grouped_single_column_returns_to_two(self):
        body = song("Before", 4) + "{\n" + r"\ulSongColumns{1}\ulSongPosition{3}" + "\n"
        body += song("Wide", 8) + "}\n" + song("After", 4)
        self.check(body, effects=16, selection=r"\ulSongColumns{2}\ulSongPosition{1}")

    def test_nonselection_grouped_single_column_restores_at_songs_end(self):
        body = song("Before", 4) + "{\n" + r"\ulSongColumns{1}\ulSongPosition{3}" + "\n"
        body += song("Wide", 8) + "}\n"
        self.check(body, effects=12, selection=r"\ulSongColumns{2}\ulSongPosition{1}")

    def test_mid_environment_two_columns_restore_following_full_width_prose(self):
        source = lifecycle.document(
            r"\begin{ulSongs}{titleidx,authidx,tagidx}\ulSongColumns{2}\ulSongPosition{1}" + "\n"
            + song("BeforeAppendix", 3) + r"""
\end{ulSongs}
\ProbeColumns
\appendix
\chapter{Technical}
\section{Diagram}
\begin{center}\vfill\rule{.8\linewidth}{100pt}\vfill\end{center}
\section{Modes and Chords}
\vfill
\begin{tabular}{|p{.4\linewidth}|p{.4\linewidth}|}
\hline Full width & Unchanged appendix text \\\hline
\end{tabular}
\vfill
\typeout{EFFECTS:\the\Effects}
""", PREAMBLE + r"""
\makeatletter
\newcommand\ProbeColumns{\typeout{COLUMNS-AFTER:\if@twocolumn2\else1\fi}}
\makeatother
""")
        for layers in (False, True):
            with self.subTest(layers=layers):
                selected = r"\def\ulPdfTranspositionLayers{" + str(layers).lower() + "}\n" + source
                outputs = self.compile_checked(selected, f"layers-{layers}")
                for output in outputs.values():
                    self.assertEqual(re.findall(r"COLUMNS-AFTER:(\d+)", output), ["1"] * 2)
                    self.assertEqual(re.findall(r"EFFECTS:(\d+)", output), ["3"] * 2)


if __name__ == "__main__":
    unittest.main()
