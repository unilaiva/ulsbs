# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Index display inputs, public controls and measurement effects."""

import os
from pathlib import Path
import re
import unittest

import test_song_lifecycle as lifecycle
from test_tex_integration import ROOT


class IndexDisplayTests(unittest.TestCase):
    setUp = lifecycle.SongLifecycleTests.setUp
    compile_source = lifecycle.SongLifecycleTests.compile_source

    @classmethod
    def setUpClass(cls):
        lifecycle.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_INDEX_DISPLAY_DIAGNOSTICS", ROOT / "build/index-display"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def compile_fragment(self, fragment, kind="title", columns="[2]", preamble="", label="case",
                missing=False):
        identifier = {"title": "titleidx", "tag": "tagidx", "author": "authidx"}[kind]
        # A test-only state adapter isolates the display from producer/schema
        # evolution while still exercising showindex's absolute-path contract.
        source = r"""
\documentclass{book}
\usepackage{fontspec,xcolor,hyperref}
\usepackage[paperwidth=148mm,paperheight=210mm,margin=15mm]{geometry}
BACKEND
\renewcommand\ulIndexTitleFont{\sffamily}
\renewcommand\ulIndexLyricFont{\sffamily\slshape}
\renewcommand\ulIndexTagFont{\sffamily\small\slshape}
\renewcommand\ulSongChapter[1]{\section*{#1}}
""" + preamble + r"""
\begin{document}
\hypertarget{display-target}{}
""" + rf"\ulShowIndex{columns}{{Index typography}}{{{identifier}}}" + r"""
\ifcsname ProbeEffects\endcsname\ProbeEffects\fi
\end{document}
"""
        setup = r"""
% Minimal public-configuration adapters for this isolated display-module test.
\newif\ifulSongIndexes\ulSongIndexestrue
\newcommand\ulSongIndexes[1]{\csname ulSongIndexes#1\endcsname}
\newif\ifulSeparateIndexes\ulSeparateIndexestrue
\newcommand\ulSeparateIndexes[1]{\csname ulSeparateIndexes#1\endcsname}
\newlength\ulIndexHeadingWidth\setlength\ulIndexHeadingWidth{1.5cm}
\newcommand\ulIndexHeadingFont{\sffamily\bfseries\LARGE}
\newcommand\ulIndexTitleFont{}
\newcommand\ulIndexLyricFont{}
\newcommand\ulIndexTagFont{}
\newcommand\ulIndexAuthorFont{\small\bfseries}
\newcommand\ulIndexRefsFont{\normalfont\normalsize}
\newcommand\ulIndexContinuation[1]{\small\textbf{#1} (continued)}
\definecolor{SongbookShade}{gray}{.80}
\newcommand\ulIndexBackgroundColor{SongbookShade}
\newcommand\ulSongChapter[1]{}
\newcommand\ulSongLink[2]{\hyperlink{#1}{#2}}
\directlua{ulsbs_index_state={show=function(id)
  local p=lfs.currentdir().."/display.sbx"; return "display.sbx",p end}}
\ExplSyntaxOn
\prop_new:N \g__ulsbs_index_kinds_prop
\prop_new:N \g__ulsbs_index_filenames_prop
\prop_gput:Nnn \g__ulsbs_index_kinds_prop {titleidx}{title}
\prop_gput:Nnn \g__ulsbs_index_kinds_prop {tagidx}{tag}
\prop_gput:Nnn \g__ulsbs_index_kinds_prop {authidx}{author}
\prop_gput:Nnn \g__ulsbs_index_filenames_prop {authidx}{idx_auth}
\ExplSyntaxOff
\input{ulsbs-index-display.code.tex}
"""
        candidate = source.replace("BACKEND", setup)
        files = {"display.sbx": fragment.encode(),
                 **{f"idx_{name}.sbx": fragment.encode() for name in ("title", "tag", "auth")}}
        if missing:
            files = {}
        output = self.compile_source(candidate, passes=2, files=files, label=label)
        if not missing and r"\ulSongIndexes{false}" not in preamble:
            text = lifecycle.SongLifecycleTests.pdf_text(self)
            self.assertIn("Index typography", text)
            if "Entry 0-000" in fragment and kind != "tag":
                self.assertIn("Entry 0-000", text)
        return {"output": output}

    @staticmethod
    def fragment(count=8, *, alternate=False, long=False):
        rows = []
        for group in range(2):
            rows.append(r"\begin{ulIndexBlock}{" + ("A" if group == 0 else "B") + "}")
            for number in range(count):
                command = "ulIndexDisplayAltEntry" if alternate and number % 2 else "ulIndexDisplayEntry"
                title = f"Entry {group}-{number:03d}"
                if long:
                    title += " with an unusually long descriptive title spanning several lines"
                refs = r"\ulSongLink{display-target}{" + str(number + 1) + "}"
                rows.append("\\" + command + "{" + title + "}{" + refs + "}")
            rows.append(r"\end{ulIndexBlock}")
        return "\n".join(rows) + "\n"

    def test_compact_title_tag_and_author(self):
        for kind in ("title", "tag", "author"):
            with self.subTest(kind=kind):
                self.compile_fragment(self.fragment(), kind=kind, label=kind)

    def test_large_two_column_titles_and_alternate_typography(self):
        self.compile_fragment(self.fragment(100, alternate=True))

    def test_large_two_column_tags(self):
        self.compile_fragment(self.fragment(110), kind="tag")

    def test_unicode_duplicate_and_empty_field_fragments(self):
        for kind, name in (("title", "titles"), ("tag", "tags"), ("author", "authors")):
            with self.subTest(kind=kind):
                fragment = (ROOT / "tests/fixtures/index" / f"{name}.sbx").read_text(
                    encoding="utf-8")
                self.compile_fragment(fragment, kind=kind, label=kind,
                             preamble=r"\ulSeparateIndexes{false}")

    def test_kind_defaults_and_nonseparate_headings(self):
        for kind in ("title", "tag", "author"):
            with self.subTest(kind=kind):
                self.compile_fragment(self.fragment(35), kind=kind, columns="",
                             preamble=r"\ulSeparateIndexes{false}", label=kind)

    def test_explicit_single_column_and_hidden_title_headings(self):
        self.compile_fragment(self.fragment(55, alternate=True), columns="[1]",
                     preamble=r"\ulSeparateIndexes{false}\setlength\ulIndexHeadingWidth{0pt}")

    def test_missing_and_disabled_indices(self):
        for kind in ("title", "tag", "author"):
            with self.subTest(kind=kind):
                self.compile_fragment("", kind=kind, missing=True, label=kind)
        self.compile_fragment("", missing=True, label="no-prior-snapshot", preamble=r"""
\directlua{if ulsbs_index_state then
  ulsbs_index_state.show=function() return nil,nil end end}
""")
        self.compile_fragment(self.fragment(), label="disabled",
                     preamble=r"\ulSongIndexes{false}\AtBeginDocument{\null}")

    def test_nonpositive_column_arguments_choose_kind_defaults(self):
        for kind, columns in (("title", "[-1]"), ("tag", "[0]"), ("author", "[-2]")):
            with self.subTest(kind=kind):
                self.compile_fragment(self.fragment(40), kind=kind, columns=columns,
                             preamble=r"\ulSeparateIndexes{false}", label=kind)

    def test_long_titles_and_wrapped_reference_lists(self):
        fragment = self.fragment(35, long=True).replace(
            r"\ulSongLink{display-target}{1}",
            r"\ulSongLink{display-target}{1}\\\ulSongLink{display-target}{25}"
            r"\\\ulSongLink{display-target}{378}\\\ulSongLink{display-target}{1050}")
        self.compile_fragment(fragment)

    def test_grouped_reference_measurement_and_trial_diagnostics(self):
        fragment = []
        for title, count in (("Air", 9), ("Forgiveness and compassion", 17), ("Water", 5)):
            refs = r"\\".join(r"\ProbeReference\ulSongLink{display-target}{" + str(100 + number) + "}"
                                for number in range(count))
            fragment.append(r"\begin{ulIndexBlock}{" + title + "}\n"
                            + r"\ulIndexDisplayEntry{}{" + refs + "}\n" + r"\end{ulIndexBlock}")
        outputs = self.compile_fragment("\n".join(fragment), kind="tag", preamble=r"""
\newcount\ReferenceEffects
\newcommand\ProbeReference{\global\advance\ReferenceEffects1\relax}
\newcommand\ProbeEffects{%
  \typeout{REFERENCE-EFFECTS:\the\ReferenceEffects}%
  \hbox to10pt{\rule{20pt}{1pt}}}
""")
        effects = {result: re.findall(r"REFERENCE-EFFECTS:(\d+)", output)
                   for result, output in outputs.items()}
        self.assertEqual(len(effects["output"]), 2)
        self.assertTrue(all(int(count) >= 31 for count in effects["output"]))
        warnings = {result: re.findall(r"(?:Overfull|Underfull) \\[hv]box \([^)]+\)", output)
                    for result, output in outputs.items()}
        self.assertIn(r"Overfull \hbox (10.0pt too wide)", warnings["output"])

    def test_public_fonts_lengths_and_customized_headings(self):
        self.compile_fragment(self.fragment(40, alternate=True), preamble=r"""
\ulSeparateIndexes{false}
\setlength\ulIndexHeadingWidth{2cm}
\setlength\columnsep{18pt}
\renewcommand\ulIndexBackgroundColor{yellow}
\renewcommand\ulIndexHeadingFont{\rmfamily\bfseries\Large}
\renewcommand\ulIndexTitleFont{\rmfamily\itshape}
\renewcommand\ulIndexLyricFont{\sffamily\bfseries}
\renewcommand\ulIndexRefsFont{\normalfont\small}
""")

    def test_public_tag_font_is_used_for_tag_headings(self):
        outputs = self.compile_fragment(self.fragment(), kind="tag", preamble=r"""
\renewcommand\ulIndexTagFont{\typeout{CUSTOM-TAG-FONT}\rmfamily\itshape}
""")
        self.assertIn("CUSTOM-TAG-FONT", outputs["output"])

    def test_integrated_ulsbs_public_entry_point_and_navigation(self):
        fragment = self.fragment(60)
        source = lifecycle.document(r"""
\hypertarget{display-target}{}
\ulShowIndex[2]{Title index}{titleidx}
\ulShowIndex[2]{Tag index}{tagidx}
\ulShowIndex[2]{Author index}{authidx}
""", r"""
\directlua{ulsbs_index_state.show=function(id)
  return id..".sbx",lfs.currentdir().."/display.sbx" end}
""")
        self.compile_source(source, passes=2, files={"display.sbx": fragment.encode()})
        text = lifecycle.SongLifecycleTests.pdf_text(self)
        for title in ("Title index", "Tag index", "Author index"):
            self.assertIn(title, text)
        self.assertIn('"display-target"', lifecycle.SongLifecycleTests.destinations(self))

    def test_display_effect_counts_preserve_measurement_contract(self):
        # Display trials can measure rows more than once, unlike collection.
        preamble = r"""
\newcount\TitleEffects\newcount\ReferenceEffects
\newcommand\ProbeTitle{\global\advance\TitleEffects1\relax}
\newcommand\ProbeReference{\global\advance\ReferenceEffects1\relax}
\newcommand\ProbeEffects{\typeout{DISPLAY-EFFECTS:\the\TitleEffects/\the\ReferenceEffects}}
"""
        for label, count, long in (("compact", 8, False), ("large", 100, False),
                                   ("wrapped", 3, True)):
            with self.subTest(label=label):
                fragment = self.fragment(count, long=long).replace(
                    "{Entry", r"{\ProbeTitle Entry").replace(
                    r"\ulSongLink", r"\ProbeReference\ulSongLink")
                outputs = self.compile_fragment(fragment, preamble=preamble, label=label)
                counts = {result: re.findall(r"DISPLAY-EFFECTS:(\d+)/(\d+)", output)
                          for result, output in outputs.items()}
                self.assertEqual(len(counts["output"]), 2)
                expected = count * 2 * (2 if label == "large" else 1)
                if not long:
                    self.assertEqual(counts["output"], [(str(expected), str(expected))] * 2)


if __name__ == "__main__":
    unittest.main()
