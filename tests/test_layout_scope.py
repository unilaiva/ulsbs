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
