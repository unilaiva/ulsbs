# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Song lifecycle, metadata, selection and index semantics."""

from __future__ import annotations

import os
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import test_index_lifecycle as index_helpers
from index_records import index_events
from test_tex_integration import ROOT


def document(body: str, preamble: str = "", *, variant: str = "default") -> str:
    selector = "" if variant == "default" else rf"\def\ulBuildVariant{{{variant}}}" + "\n"
    availability = "" if variant == "default" else f"variants={{default,{variant}}},"
    return (selector + r"\documentclass[" + availability
            + r"oneside,openany,maintitle={Lifecycle}]{ulsbs-songbook}"
            + "\n" + r"\ulShowTags{false}\ulShowPhase{false}" + "\n" + preamble
            + "\n" + r"\begin{document}" + "\n" + body
            + "\n" + r"\end{document}" + "\n")


def index_records(work: Path, filename: str) -> list[tuple[str, str, str]]:
    return [(event["title"], event["label"], event["target"])
            for event in index_events(work, filename) if event["type"] == "record"]


class SongLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [name for name in ("lualatex", "texlua", "pdftotext", "pdfinfo")
                   if shutil.which(name) is None]
        if missing:
            raise unittest.SkipTest("TeX/PDF tools are required: " + ", ".join(missing))
        cls.temporary = tempfile.TemporaryDirectory(prefix="ulsbs-song-lifecycle-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.cache = cls.root / "cache"
        cls.cache.mkdir()
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_SONG_DIAGNOSTICS", ROOT / "build/song-lifecycle"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.work = self.root / self._testMethodName
        self.work.mkdir()
        (self.work / "include").mkdir()
        shutil.copy2(index_helpers.FIXTURES / "tags.txt", self.work / "include/tags.txt")

    def compile_source(self, source: str, *, passes: int = 1, failure: str | None = None,
                       label: str = "probe", output: str | None = None,
                       files: dict[str, bytes] | None = None) -> str:
        work = self.work / label
        work.mkdir()
        shutil.copytree(self.work / "include", work / "include")
        for name, data in (files or {}).items():
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (work / "book.tex").write_text(source, encoding="utf-8")
        self.book = work
        if output is not None:
            location = Path(output)
            (location if location.is_absolute() else work / location).mkdir(parents=True)
        outputs = []
        try:
            for number in range(1, passes + 1):
                result = index_helpers.IndexLifecycleTests.compile.__func__(type(self), work, output=output)
                outputs.append(result.stdout)
                (work / f"pass-{number}.stdout").write_text(result.stdout, encoding="utf-8")
                if failure is not None:
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    # TeX prefixes continuation lines when wrapping package diagnostics.
                    message = re.sub(r"(?m)^\(ulsbs-[^)]+\)[ \t]*", "", result.stdout)
                    self.assertIn(failure.lower(), " ".join(message.split()).lower())
                    break
                self.assertEqual(result.returncode, 0, result.stdout)
            if failure is None:
                locations = {work}
                if output is not None:
                    locations.add(location if location.is_absolute() else work / location)
                for location in locations:
                    for suffix in ("sxd", "sxc"):
                        self.assertEqual(list(location.rglob(f"*.{suffix}")), [],
                                         "Collection must not use legacy index files")
            return "\n".join(outputs)
        finally:
            shutil.copytree(work, self.diagnostics / self._testMethodName / label,
                            dirs_exist_ok=True)

    def pdf_text(self) -> str:
        return subprocess.run(["pdftotext", "-layout", str(self.book / "book.pdf"), "-"],
                              check=True, stdout=subprocess.PIPE, text=True).stdout

    def destinations(self) -> str:
        return subprocess.run(["pdfinfo", "-dests", str(self.book / "book.pdf")],
                              check=True, stdout=subprocess.PIPE, text=True).stdout

    def assert_index_fragment(self, kind: str):
        self.assertTrue((self.book / f"idx_{kind}.sbx").read_text().strip())

    def test_initial_public_typography_preserves_font_resource_allocation(self):
        source = document(r"""
\begin{ulSongs}{}
\beginsong{Font metrics}[key={C}]
\beginverse*
\[C]Metric initialization.
\endverse
\endsong
\end{ulSongs}
\directlua{for id,f in font.each() do
  texio.write_nl('FONT-ALLOCATION:'..id..':'..tostring(f.fullname)..':'..tostring(f.size)) end}
""")
        output = self.compile_source(source)
        self.assertTrue(re.findall(r"FONT-ALLOCATION:\d+:[^:\r\n]*:\d+", output))

    def test_clean_three_pass_book_emits_exact_owned_records_and_indices(self):
        source = document(r"""
\begin{ulSongs}{titleidx,tagidx}
\beginsong{Primary\\Second title}[id={same},tags={fire},key={C},
  index={Alternative},ititle={Ordinary}]
\ulIndexEntry[titleidx]{Explicit alternative}
\ulIndexTitleEntry[titleidx]{Explicit ordinary}
\endsong
\begin{song}{Another}[id={another},tags={earth},key={Dm}]
\end{song}
\end{ulSongs}
\ulShowIndex[1]{Titles}{titleidx}
\ulShowIndex[1]{Tags}{tagidx}
""")
        output = self.compile_source(source, passes=3)
        self.assertIn("No complete previous-pass data", output)
        final = (self.book / "pass-3.stdout").read_text()
        self.assertNotIn("Package ulsbs-index Warning", final)
        title = [(name, "1", "song1-1.1") for name in
                 ("*Alternative", "Ordinary", "Primary", "Second title",
                  "*Explicit alternative", "Explicit ordinary")]
        title += [("Another", "2", "song1-2.1")]
        self.assertEqual(index_records(self.book, "idx_title"), title)
        self.assertEqual(index_records(self.book, "idx_tag"),
                         [("fire", "1", "song1-1.1"), ("earth", "2", "song1-2.1")])
        for kind in ("title", "tag"):
            self.assert_index_fragment(kind)
        self.assertIn(b"complete", (self.book / "book.ulsbs-index-state").read_bytes())
        self.assertFalse((self.book / "book.sxc").exists(), "Collection must not use the old writer")
        text = self.pdf_text()
        for value in ("Primary", "Second title", "Another", "Titles", "Tags"):
            self.assertIn(value, text)

    def test_metadata_all_fields_effective_key_and_custom_key_reset(self):
        preamble = r"""
\newcommand\ProbeCustom{}
\ulNewSongKey{custom}{\def\ProbeCustom{unset}}{\def\ProbeCustom{#1}}
\ExplSyntaxOn
\NewDocumentCommand\ProbeMetadata{}{%
  \clist_map_inline:nn {by,cr,li,id,off,ex,key,gk,ph,tags}
    {\iow_term:x {META-##1=[\prop_item:Nn\l__ulsbs_song_metadata_prop{##1}]}}
  \iow_term:x {CUSTOM=[\ProbeCustom]}
}
\ExplSyntaxOff
"""
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Full}[by={Author},cr={Copyright},li={License},
 id={full},off={Dedication},ex={Explanation},key={F#},gk={B&},
 ph={Morning},tags={fire},custom={custom-value}]
\ProbeMetadata
\typeout{PUBLIC-AUTHOR=[\ulSongAuthors];COPYRIGHT=[\ulSongCopyright];LICENSE=[\ulSongLicense]}
\endsong
\beginsong{Empty}\ProbeMetadata\endsong
\end{ulSongs}
""", preamble))
        expected = {"by": "Author", "cr": "Copyright", "li": "License",
                    "id": "full", "off": "Dedication", "ex": "Explanation", "key": "F#",
                    "gk": "B&", "ph": "Morning", "tags": "fire"}
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(re.findall(r"META-" + key + r"=\[([^\]]*)\]", output),
                                 [value, ""])
        self.assertEqual(re.findall(r"CUSTOM=\[([^\]]*)\]", output), ["custom-value", "unset"])
        self.assertIn("PUBLIC-AUTHOR=[Author];COPYRIGHT=[Copyright];LICENSE=[License]", output)

    def test_title_iteration_consumes_then_reset_restores_primary(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{First\\Second\\Third}
\typeout{TITLE-INITIAL=[\ulSongTitle]}
\ulNextTitle\typeout{TITLE-NEXT=[\ulSongTitle]}
\ulForEachTitle{\typeout{TITLE-ITER=[\ulSongTitle]}}
\ifx\ulSongTitle\relax\typeout{TITLE-EXHAUSTED}\fi
\ulResetTitles\typeout{TITLE-RESET=[\ulSongTitle]}
\endsong
\end{ulSongs}
"""))
        self.assertIn("TITLE-INITIAL=[First]", output)
        self.assertIn("TITLE-NEXT=[Second]", output)
        self.assertEqual(re.findall(r"TITLE-ITER=\[([^\]]*)\]", output), ["Second", "Third"])
        self.assertIn("TITLE-EXHAUSTED", output)
        self.assertIn("TITLE-RESET=[First]", output)

    def test_repeated_ids_export_occurrence_suffix_not_printed_number(self):
        self.compile_source(document(r"""
\begin{ulSongs}{titleidx}
\setcounter{ulSongNumber}{17}
\beginsong{First copy}[id={repeat}]\endsong
\beginsong{Second copy}[id={repeat}]\endsong
\beginsong{Anonymous}\endsong
\end{ulSongs}
"""), passes=3)
        psv = (self.book / "book.ulsbs.psv").read_text().splitlines()
        rows = [row.split("|") for row in psv if row.startswith("ID-NR-PAGE-Y|")]
        self.assertEqual([(row[1], row[2]) for row in rows], [("repeat", "17"), ("repeat-2", "18")])
        self.assertTrue(all(int(row[3]) > 0 and int(row[4]) > 0 for row in rows), rows)
        destinations = self.destinations()
        for name in ("songid:repeat", "songid:repeat-2", "song1-17.1", "song1-18.1"):
            self.assertIn('"' + name + '"', destinations)
        self.assertNotIn('"songid:repeat-17"', destinations)

    def test_selection_uses_printed_numbers_and_skipped_songs_increment_at_end(self):
        output = self.compile_source(document(r"""
\ulIncludeOnlySongs{8}
\begin{ulSongs}{titleidx}
\setcounter{ulSongNumber}{7}
\beginsong{Skipped unique}[id={8}]\typeout{NUMBER-A=\theulSongNumber}\endsong
\typeout{NUMBER-AFTER-A=\theulSongNumber}
\beginsong{Selected unique}[id={7}]\typeout{NUMBER-B=\theulSongNumber}\endsong
\typeout{NUMBER-AFTER-B=\theulSongNumber}
\end{ulSongs}
"""), passes=3)
        for value in ("NUMBER-A=7", "NUMBER-AFTER-A=8", "NUMBER-B=8", "NUMBER-AFTER-B=9"):
            self.assertIn(value, output)
        text = self.pdf_text()
        self.assertIn("Selected unique", text)
        self.assertNotIn("Skipped unique", text)
        self.assertEqual(index_records(self.book, "idx_title"),
                         [("Selected unique", "8", "song1-8.1")])
        rows = (self.book / "book.ulsbs.psv").read_text()
        self.assertIn("ID-NR-PAGE-Y|7|8|", rows)
        self.assertNotIn("ID-NR-PAGE-Y|8|7|", rows)

    def test_multiple_blocks_reset_numbers_but_chapters_do_not(self):
        output = self.compile_source(document(r"""
\tableofcontents
\begin{ulSongs}{titleidx}
\ulSongChapter{First chapter}
\beginsong{One}\typeout{BLOCK-ONE-A=\theulSongNumber}\endsong
\ulSongChapter{Second chapter}
\beginsong{Two}\typeout{BLOCK-ONE-B=\theulSongNumber}\endsong
\end{ulSongs}
\begin{ulSongs}{titleidx}
\beginsong{New block}\typeout{BLOCK-TWO=\theulSongNumber}\endsong
\end{ulSongs}
"""), passes=3)
        for value in ("BLOCK-ONE-A=1", "BLOCK-ONE-B=2", "BLOCK-TWO=1"):
            self.assertIn(value, output)
        destinations = self.destinations()
        for name in ("song1-1.1", "song1-2.1", "song2-1.1"):
            self.assertIn('"' + name + '"', destinations)
        toc = (self.book / "book.toc").read_text() if (self.book / "book.toc").exists() else ""
        self.assertIn("First chapter", toc)
        self.assertIn("Second chapter", toc)

    def test_lifecycle_hooks_fire_once_without_stanza_events(self):
        preamble = "\n".join(
            rf"\AddToHook{{ulsbs/{hook}}}{{\typeout{{HOOK-{hook}:\theulSongNumber}}}}"
            for hook in ("song/begin", "song/finish", "stanza/start", "stanza/finish",
                         "index/record", "song/anchor"))
        output = self.compile_source(document(r"""
\begin{ulSongs}{titleidx}
\beginsong{Hook song}[id={hook}]\endsong
\end{ulSongs}
""", preamble))
        for hook in ("song/begin", "song/finish", "index/record", "song/anchor"):
            self.assertEqual(re.findall("HOOK-" + hook + r":(\d+)", output), ["1"])
        self.assertNotIn("HOOK-stanza/", output)

    def test_annotation_outside_a_stanza_is_actionable(self):
        output = self.compile_source(document(
            r"\begin{ulSongs}{}\beginsong{Invalid}\[C]Text"
            + r"\endsong\end{ulSongs}"), failure="Invalid chord state")
        message = re.sub(r"\(ulsbs-chords\)\s*", "", output)
        self.assertIn("annotation outside a stanza", " ".join(message.split()))
        self.assertNotIn("Undefined control sequence", output)

    def test_misordered_nested_and_unclosed_lifecycle_is_actionable(self):
        cases = (("outside", r"\beginsong{Outside}\endsong", "songs"),
                 ("end", r"\begin{ulSongs}{}\endsong\end{ulSongs}", "song"),
                 ("nested-song", r"\begin{ulSongs}{}\beginsong{One}\beginsong{Two}", "song"),
                 ("nested-block", r"\begin{ulSongs}{}\begin{ulSongs}{}", "songs"),
                 ("unclosed-song", r"\begin{ulSongs}{}\beginsong{Open}\end{ulSongs}", "song"),
                 ("unclosed-block", r"\begin{ulSongs}{}", "songs"))
        for label, body, diagnostic in cases:
            with self.subTest(case=label):
                output = self.compile_source(document(body), failure=diagnostic, label=label)
                self.assertIn("ulsbs", output.lower())
                self.assertNotIn("Undefined control sequence", output)

    def test_ordered_selection_preserves_record_and_export_order(self):
        self.compile_source(document(r"""
\ulIncludeOnlySongs{3,1}
\begin{ulSongs}{titleidx}
\beginsong{First}[id={first}]\endsong
\beginsong{Excluded}[id={excluded}]\endsong
\beginsong{Third}[id={third}]\endsong
\end{ulSongs}
"""), passes=3)
        self.assertEqual(index_records(self.book, "idx_title"),
                         [("Third", "3", "song1-3.1"), ("First", "1", "song1-1.1")])
        text = self.pdf_text()
        self.assertLess(text.index("Third"), text.index("First"))
        psv = (self.book / "book.ulsbs.psv").read_text()
        self.assertLess(psv.index("ID-NR-PAGE-Y|third|3|"), psv.index("ID-NR-PAGE-Y|first|1|"))
        self.assertNotIn("excluded", psv)

    def test_page_index_labels_resolve_at_shipout_and_number_style_is_independent(self):
        self.compile_source(document(r"""
\begin{ulSongs}{titleidx}
\beginsong{Page one}\endsong
\newpage
\beginsong{Page two}\endsong
\end{ulSongs}
""", r"\ulIndexSongsAs{titleidx}{\thepage}\renewcommand\theulSongNumber{N-\arabic{ulSongNumber}}"), passes=3)
        self.assertEqual(index_records(self.book, "idx_title"),
                         [("Page one", "1", "song1-N-1.1"), ("Page two", "2", "song1-N-2.1")])

    def test_hidden_badge_metadata_only_multikey_records_effective_key_without_layers(self):
        source = document(r"""
\begin{ulSongs}{titleidx}
\setcounter{ulSongNumber}{11}
\beginsong{First}[id={repeat},key={F#}]\endsong
\beginsong{Second}[id={repeat},key={B&m}]\endsong
\end{ulSongs}
""", r"""
\ulShowKey{false}
\directlua{
  local original = ulsbs_multikey.begin_song
  ulsbs_multikey.begin_song = function(internal,id,occ,prefix,key,labels)
    texio.write_nl('term and log', 'MULTI|'..id..'|'..occ..'|'..prefix..'|'..key..'|'..table.concat(labels,','))
    original(internal,id,occ,prefix,key,labels)
  end
}
""").replace(r"\documentclass", r"\def\ulPdfTranspositionLayers{true}" + "\n" + r"\documentclass", 1)
        output = self.compile_source(source, passes=3)
        rows = [row.split("|") for row in output.splitlines() if row.startswith("MULTI|")]
        self.assertEqual([(r[1], r[2], r[4]) for r in rows],
                         [("repeat", "1", "F#"), ("repeat", "2", "B&m")] * 3)
        self.assertEqual(rows[0][3], "ulsbs:transpose:v1:id:repeat")
        self.assertEqual(rows[1][3], "ulsbs:transpose:v1:id:repeat:o02")
        self.assertTrue(all(len(r[5].split(",")) == 12 for r in rows))
        data = json.loads((self.book / "book.ulsbs-multikey.json").read_text())
        # Production protocol deliberately exports only transposable occurrences.
        self.assertEqual(data["multikey_info"]["songs"], [])

    def test_optional_metadata_and_index_directives(self):
        self.compile_source(document(r"""
\begin{ulSongs}{titleidx,authidx}
\beginsong{The Song}[by={Example Author},cr={Copyright}]\endsong
\beginsong{New}[ititle={One},ititle={Two},ititle={},by={Another}]\endsong
\end{ulSongs}
\ulShowIndex[1]{Titles}{titleidx}
""", r"\def\Article{The}\def\AuthorSep{and}\ulTitlePrefixWord{\Article}\ulAuthorSepWord{\AuthorSep}"), passes=3)
        title = index_events(self.book, "idx_title")
        self.assertIn({"type": "directive", "name": "prefix", "value": "The"}, title)
        self.assertIn(("One", "2", "song1-2.1"), index_records(self.book, "idx_title"))
        self.assertIn(("Two", "2", "song1-2.1"), index_records(self.book, "idx_title"))
        self.assertIn("Song,~The", (self.book / "idx_title.sbx").read_text())
        self.assertIn({"type": "directive", "name": "sep", "value": "and"},
                      index_events(self.book, "idx_auth"))
        self.assertFalse((self.book / "idx_auth.sbx").exists())
        self.assert_index_fragment("title")

    def test_unknown_metadata_key_is_actionable(self):
        output = self.compile_source(document(
            r"\begin{ulSongs}{}\beginsong{Bad}[typo={value}]\endsong\end{ulSongs}"),
            failure="unknown metadata key")
        self.assertIn("typo", output)

    def test_empty_prelude_fields_and_scoped_index_labels(self):
        self.compile_source(document(r"""
\begin{ulSongs}{titleidx,tagidx}
\beginsong{Empty fields}\endsong
{\ulIndexSongsAs{titleidx}{B\theulSongNumber}\beginsong{Local label}\endsong}
\beginsong{Restored label}\endsong
\end{ulSongs}
""", r"\ulIndexSongsAs{titleidx}{A\theulSongNumber}\ulShowKey{true}\ulShowGoodKeys{true}\ulShowTags{true}\ulShowPhase{true}"), passes=3)
        self.assertEqual(index_records(self.book, "idx_title"),
                         [("Empty fields", "A1", "song1-1.1"),
                          ("Local label", "B2", "song1-2.1"),
                          ("Restored label", "A3", "song1-3.1")])
        self.assertEqual(index_records(self.book, "idx_tag"), [])
        text = self.pdf_text()
        for missing in ("offered to:", "Key:", "Good keys:"):
            self.assertNotIn(missing, text)

    def test_custom_title_index_matches_the_default_title_index(self):
        self.compile_source(document(r"""
\begin{ulSongs}{titleidx,tagidx,customidx}
\beginsong{Owned lifecycle}[id={owned},key={F#},gk={B&},tags={fire}]\endsong
\end{ulSongs}
\ulShowIndex[1]{Titles}{titleidx}
\ulShowIndex[1]{Tags}{tagidx}
\ulShowIndex[1]{Custom titles}{customidx}
""", r"\ulNewIndex{customidx}{custom_title}"), passes=3)
        self.assert_index_fragment("title")
        self.assert_index_fragment("tag")
        self.assertEqual((self.book / "custom_title.sbx").read_bytes(),
                         (self.book / "idx_title.sbx").read_bytes())

    def test_explicit_empty_selection_omits_every_song_across_blocks(self):
        self.compile_source(document(r"""
Outside text.
\ulIncludeOnlySongs{}
\begin{ulSongs}{titleidx}
\beginsong{Should disappear}[id={gone}]\endsong
\end{ulSongs}
\begin{ulSongs}{titleidx}
\beginsong{Also absent}[id={gone-again}]\endsong
\end{ulSongs}
"""), passes=3)
        text = self.pdf_text()
        self.assertIn("Outside text", text)
        self.assertNotIn("Should disappear", text)
        self.assertNotIn("Also absent", text)
        self.assertEqual(index_records(self.book, "idx_title"), [])
        self.assertNotIn("ID-NR-PAGE-Y|gone", (self.book / "book.ulsbs.psv").read_text())

    def test_tags_use_last_assignment_and_reset_between_songs(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{tagidx}
\beginsong{First}[tags={earth},tags={fire}]\endsong
\beginsong{Second}\endsong
\beginsong{Third}[tags={earth},tags={}]\endsong
\beginsong{Fourth}[tags={earth}]\endsong
\ifdefined\ulSongRefs\errmessage{Removed reference accessor exists}\fi
\end{ulSongs}
"""), passes=3)
        self.assertNotIn("Undefined control sequence", output)
        self.assertEqual(index_records(self.book, "idx_tag"),
                          [("fire", "1", "song1-1.1"), ("earth", "4", "song1-4.1")])

    def test_removed_reference_metadata_is_rejected(self):
        cases = (
            ("reference", r"\beginsong{Song}[sr={earth}]", "Unknown metadata key 'sr'"),
            ("empty", r"\beginsong{Song}[sr={}]", "Unknown metadata key 'sr'"),
            ("mixed", r"\beginsong{Song}[tags={fire},sr={earth}]", "Unknown metadata key 'sr'"),
            ("environment", r"\begin{song}{Song}[sr={earth}]", "Unknown metadata key 'sr'"),
            ("braced", r"\beginsong{Song}{earth}{Author}{Copyright}", "song metadata was removed"),
        )
        for label, song, diagnostic in cases:
            with self.subTest(label=label):
                self.compile_source(document(r"\begin{ulSongs}{}" + song
                                             + r"\endsong\end{ulSongs}"),
                                    failure=diagnostic, label=label)

    def test_public_metadata_remains_available_after_endsong(self):
        output = self.compile_source(document(r"""
\begin{ulSongs}{}
\beginsong{Metadata}[id={one},by={Author},key={C}]\endsong
\typeout{AFTER-SONG=[\ulSongId/\ulSongAuthors/\ulSongKey/\ulSongTitle]}
\beginsong{Reset}\endsong
\typeout{AFTER-RESET=[\ulSongId/\ulSongAuthors/\ulSongKey/\ulSongTitle]}
\end{ulSongs}
"""))
        self.assertIn("AFTER-SONG=[one/Author/C/Metadata]", output)
        self.assertIn("AFTER-RESET=[///Reset]", output)

    def test_protected_titles_authors_and_formatted_labels(self):
        source = document(r"""
\begin{ulSongs}{titleidx,authidx}
\beginsong{Styled~\emph{title}}[by={\textit{Author}!},index={\textbf{Alternative}}]\endsong
\end{ulSongs}
\ulShowIndex[1]{Titles}{titleidx}
""", r"\ulIndexSongsAs{titleidx}{\textbf{\theulSongNumber}}\catcode`\!=13\def!{BANG}")
        self.compile_source(source, passes=3)
        title = index_records(self.book, "idx_title")
        self.assertTrue(any(r"\emph {title}" in row[0] for row in title), title)
        self.assertTrue(all(r"\textbf {1}" == row[1] for row in title), title)
        self.assertEqual(index_records(self.book, "idx_auth"),
                         [(r"\textit {Author}!", "1", "song1-1.1")])
        self.assert_index_fragment("title")

    def test_index_streams_follow_relative_and_absolute_output_directories(self):
        source = document(r"""
\begin{ulSongs}{titleidx}
\beginsong{Output directory}\endsong
\end{ulSongs}
\ulShowIndex[1]{Titles}{titleidx}
""")
        for label in ("relative", "absolute"):
            with self.subTest(label=label):
                output = self.work / label / "output dir"
                option = str(output) if label == "absolute" else "output dir"
                self.compile_source(source, passes=3, label=label, output=option)
                self.book = output
                self.assertEqual(index_records(output, "idx_title"),
                                 [("Output directory", "1", "song1-1.1")])
                self.assertIn("Output directory", self.pdf_text())
                self.assertTrue((output / "book.ulsbs-index-state").is_file())
                self.assertFalse((self.work / label / "idx_title.sxd").exists())

    def test_nested_formatting_literal_page_spelling_and_deferred_page_labels(self):
        source = document(r"""
\begin{ulSongs}{titleidx,authidx}
\beginsong{Nested {\emph{title!}}}[by={\textit{Author}!},index={Literal \string\thepage}]
\ulIndexEntry{Unicode \string\Chanté}
\endsong
\sclearpage
\beginsong{Second {\textbf{title}}}[by={Second Author}]\endsong
\end{ulSongs}
""", r"\ulIndexSongsAs{titleidx}{\textbf{\thepage}/\thepage}\catcode`\!=13\def!{BANG}"
            r"\DeclareRobustCommand{\Chanté}{Chant}")
        self.compile_source(source, passes=3)
        title = index_records(self.book, "idx_title")
        self.assertTrue(any(r"\thepage" in row[0] for row in title), title)
        self.assertTrue(any(r"\Chanté" in row[0] for row in title), title)
        self.assertEqual({row[1] for row in title}, {r"\textbf {1}/1", r"\textbf {2}/2"})

    def test_absolute_index_filename_is_not_prefixed_by_output_directory(self):
        output = self.work / "probe" / "output dir"
        filename = output / "custom"
        source = document(r"""
\begin{ulSongs}{absoluteidx}
\beginsong{Absolute index path}\endsong
\end{ulSongs}
\ulShowIndex[1]{Titles}{absoluteidx}
""", r"\ulNewIndex{absoluteidx}{" + str(filename) + "}")
        self.compile_source(source, passes=3, output=str(output))
        self.book = output
        self.assertEqual(index_records(output, str(filename)),
                         [("Absolute index path", "1", "song1-1.1")])
        self.assertIn("Absolute index path", self.pdf_text())


if __name__ == "__main__":
    unittest.main()
