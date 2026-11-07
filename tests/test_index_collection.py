# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""TeX collection, retained passes and invalid-state diagnostics."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from index_records import index_events, read_snapshot
import test_index_lifecycle as lifecycle
from test_song_lifecycle import document


SOURCE = document(r"""
\begin{ulSongs}{titleidx,tagidx}
\beginsong{Index}[id={index},tags={fire}]
\beginverse
Lyrics.
\endverse
\endsong
\end{ulSongs}
\ulShowIndex[1]{Titles}{titleidx}
\ulShowIndex[1]{Tags}{tagidx}
""")


class IndexCollectionTests(unittest.TestCase):
    @classmethod
    def compile(cls, work, *, draft=False, include=None, output=None, jobname="book"):
        env = os.environ.copy()
        env.update(TEXINPUTS=f"{lifecycle.ASSETS}//{os.pathsep}",
                   LUAINPUTS=f"{lifecycle.ASSETS}//{os.pathsep}",
                   TEXMFVAR=str(cls.cache), TEXMFCACHE=str(cls.cache),
                   SOURCE_DATE_EPOCH="1792843200", max_print_line="10000")
        if include is not None:
            env["TEXINPUTS"] = f"{include}{os.pathsep}" + env["TEXINPUTS"]
        return subprocess.run(
            ["lualatex", "-file-line-error", "-halt-on-error",
             "-interaction=nonstopmode", f"-jobname={jobname}"]
            + (["-draftmode"] if draft else [])
            + ([f"-output-directory={output}"] if output is not None else [])
            + ["book.tex"],
            cwd=work, env=env, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120,
            check=False,
        )

    @classmethod
    def setUpClass(cls):
        if shutil.which("lualatex") is None:
            raise unittest.SkipTest("LuaLaTeX is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ulsbs-index-collection-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.cache = cls.root / "cache"
        cls.cache.mkdir()
        cls.seed = cls.root / "seed"
        cls.prepare(cls.seed)
        result = cls.compile(cls.seed, draft=True)
        if result.returncode:
            raise AssertionError(result.stdout)

    @classmethod
    def prepare(cls, work, source=SOURCE):
        work.mkdir()
        (work / "book.tex").write_text(source)
        (work / "include").mkdir()
        shutil.copy2(lifecycle.FIXTURES / "tags.txt", work / "include/tags.txt")

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.root, prefix="case-"))
        shutil.copytree(self.seed, self.work, dirs_exist_ok=True)

    def run_pass(self, *, failure=None, **kwargs):
        result = self.compile(self.work, **kwargs)
        output = " ".join(result.stdout.split())
        if failure:
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn(failure, output)
        else:
            self.assertEqual(result.returncode, 0, output)
            self.assertFalse(list(self.work.glob("*.sxd")))
            self.assertFalse(list(self.work.glob("*.sxc")))
            self.assertIn(b"ULSBS index snapshot 3", self.state.read_bytes())
            read_snapshot(self.state)
        return output

    @property
    def state(self):
        return self.work / "book.ulsbs-index-state"

    def test_manual_draft_full_full_and_retained_records_are_exact(self):
        initial = self.state.read_bytes()
        for _ in range(3):
            output = self.run_pass()
            self.assertNotIn("Package ulsbs-index Warning", output)
            self.assertEqual(self.state.read_bytes(), initial)
        for filename, title in (("idx_title", "Index"), ("idx_tag", "fire")):
            with self.subTest(filename=filename):
                event, = index_events(self.work, filename)
                self.assertEqual(event["type"], "record")
                self.assertEqual(event["title"], title)
                self.assertEqual(event["label"], "1")
                self.assertEqual(event["target"], "song1-1.1")

    def test_first_pass_never_reads_stale_fragments_or_legacy_inputs(self):
        self.state.unlink()
        shadow = self.work / "shadow"
        shadow.mkdir()
        for kind in ("title", "tag"):
            (shadow / f"idx_{kind}.sbx").write_text(r"\UndefinedForeignIndex")
            (self.work / f"idx_{kind}.sbx").write_text(r"\UndefinedStaleIndex")
        output = self.run_pass(include=shadow)
        self.assertIn("No complete previous-pass data", output)
        self.assertNotIn("Undefined", output)
        self.run_pass(include=shadow)
        for kind in ("title", "tag"):
            self.assertIn(b"song1-1.1", (self.work / f"idx_{kind}.sbx").read_bytes())

    def test_empty_unused_resources_are_created_and_stale_fragments_cleared(self):
        (self.work / "include/tags.txt").unlink()
        for directive in ("", r'\directlua{ulsbs_index_state.directive("titleidx", "prefix", "Le")}'):
            with self.subTest(directive=directive):
                self.state.unlink(missing_ok=True)
                (self.work / "book.tex").write_text(document(
                    directive + r"\begin{ulSongs}{}\end{ulSongs}\null"))
                for kind in ("title", "tag", "auth"):
                    (self.work / f"idx_{kind}.sbx").write_bytes(b"stale unused fragment")
                for _ in range(2):
                    self.run_pass()
                    for kind in ("title", "tag", "auth"):
                        self.assertEqual((self.work / f"idx_{kind}.sbx").read_bytes(), b"")
                events = read_snapshot(self.state)["indices"]["titleidx"]["events"]
                self.assertEqual([event["type"] for event in events],
                                 ["directive"] if directive else [])
                for kind in ("title", "tag", "auth"):
                    (self.work / f"idx_{kind}.sbx").unlink()
                self.run_pass()
                for kind in ("title", "tag", "auth"):
                    self.assertEqual((self.work / f"idx_{kind}.sbx").read_bytes(), b"")

    def test_empty_displayed_resources_never_load_stale_first_pass_fragments(self):
        (self.work / "book.tex").write_text(document(
            r"\begin{ulSongs}{}\end{ulSongs}\null" + lifecycle.SHOW
            + r"\ulShowIndex{Authors}{authidx}"))
        self.state.unlink()
        for kind in ("title", "tag", "auth"):
            (self.work / f"idx_{kind}.sbx").write_text(r"\UndefinedStaleIndex")
        for phase in range(3):
            output = self.run_pass()
            self.assertNotIn("Undefined", output)
            if phase == 0:
                self.assertIn("No complete previous-pass data", output)
            else:
                self.assertNotIn("Package ulsbs-index Warning", output)
            for kind in ("title", "tag", "auth"):
                self.assertEqual((self.work / f"idx_{kind}.sbx").read_bytes(), b"")

    def test_unused_empty_resources_follow_cli_jobname_prefix_not_song_selection(self):
        source = document(r"""
\ulIncludeOnlySongs{}
\directlua{ulsbs_index_state.directive("titleidx", "prefix", "Le")}
\begin{ulSongs}{titleidx,tagidx}
\beginsong{Skipped}[id={skipped},tags={fire}]\endsong
\end{ulSongs}\null
""")
        for jobname, selection in (("ul-selection", True), ("ul-selectionFoo", True),
                                   ("ul-selection_new-songs_A5_LYRICS-ONLY", True),
                                   ("book", False), ("ul-selectio", False),
                                   ("UL-selection", False)):
            with self.subTest(jobname=jobname):
                work = self.work / jobname
                self.prepare(work, source)
                (work / "include/tags.txt").unlink()
                for stale in (False, True):
                    if stale:
                        for kind in ("title", "tag", "auth"):
                            (work / f"idx_{kind}.sbx").write_bytes(b"retained fragment")
                    result = self.compile(work, jobname=jobname)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    snapshot = read_snapshot(work / f"{jobname}.ulsbs-index-state")
                    self.assertEqual(snapshot["job"], jobname)
                    for index in snapshot["indices"].values():
                        self.assertFalse(any(event["type"] == "record" for event in index["events"]))
                    for kind in ("title", "tag", "auth"):
                        path = work / f"idx_{kind}.sbx"
                        if selection:
                            if stale:
                                self.assertEqual(path.read_bytes(), b"retained fragment")
                            else:
                                self.assertFalse(path.exists())
                        else:
                            self.assertEqual(path.read_bytes(), b"")

    def test_selection_jobname_still_generates_explicitly_displayed_indices(self):
        for label, source, expected in (
                ("empty", document(r"\begin{ulSongs}{}\end{ulSongs}\null" + lifecycle.SHOW), b""),
                ("nonempty", SOURCE, b"song1-1.1")):
            with self.subTest(label=label):
                work = self.work / label
                self.prepare(work, source)
                jobname = "ul-selectionFoo_LYRICS-ONLY"
                for kind in ("title", "tag"):
                    (work / f"idx_{kind}.sbx").write_text(r"\UndefinedStaleIndex")
                for phase in range(2):
                    result = self.compile(work, jobname=jobname)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertNotIn("Undefined", result.stdout)
                    for kind in ("title", "tag"):
                        path = work / f"idx_{kind}.sbx"
                        if phase == 0 and expected:
                            self.assertFalse(path.exists())
                        elif expected:
                            self.assertIn(expected, path.read_bytes())
                        else:
                            self.assertEqual(path.read_bytes(), b"")
                self.assertFalse((work / "idx_auth.sbx").exists())

    def test_selection_jobname_nofiles_preserves_existing_resources(self):
        (self.work / "book.tex").write_text(r"\nofiles" + document(
            r"\begin{ulSongs}{}\end{ulSongs}\null"))
        for kind in ("title", "tag", "auth"):
            (self.work / f"idx_{kind}.sbx").write_bytes(b"retained fragment")
        jobname = "ul-selectionFoo"
        result = self.compile(self.work, jobname=jobname)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse((self.work / f"{jobname}.ulsbs-index-state").exists())
        for kind in ("title", "tag", "auth"):
            self.assertEqual((self.work / f"idx_{kind}.sbx").read_bytes(), b"retained fragment")

    def test_nonempty_unused_resources_need_neither_definitions_nor_fragments(self):
        (self.work / "include/tags.txt").unlink()
        (self.work / "book.tex").write_text(SOURCE.replace(lifecycle.SHOW.strip(), "")
            .replace("{titleidx,tagidx}", "{titleidx,authidx,tagidx}")
            .replace("tags={fire}", "tags={fire},by={Example Author}"))
        self.state.unlink()
        (self.work / "idx_auth.sbx").unlink(missing_ok=True)
        for _ in range(2):
            self.run_pass()
            for kind in ("title", "tag", "auth"):
                self.assertFalse((self.work / f"idx_{kind}.sbx").exists())
                events = read_snapshot(self.state)["indices"][f"{kind}idx"]["events"]
                self.assertTrue(any(event["type"] == "record" for event in events))

    def test_empty_author_fragment_is_created_and_stale_content_is_cleared(self):
        (self.work / "book.tex").write_text(document(
            r"\begin{ulSongs}{}\end{ulSongs}\null\ulShowIndex{Authors}{authidx}"))
        author = self.work / "idx_auth.sbx"
        self.run_pass()
        self.assertEqual(author.read_bytes(), b"")
        author.write_text(r"\UndefinedStaleAuthorIndex")
        output = self.run_pass()
        self.assertNotIn("Undefined control sequence", output)
        self.assertEqual(author.read_bytes(), b"")

    def test_authors_generate_from_by_across_blocks_and_custom_destinations(self):
        source = document(r"""
\typeout{AUTHORS-FIRST}
\ulShowIndex[1]{Authors before songs}{authidx}
\typeout{AUTHORS-FIRST-END}
\begin{ulSongs}{authidx,writers}
\beginsong{First}[by={Alice Smith, Bob Jones and Alice Smith}]\endsong
\end{ulSongs}
\typeout{AUTHORS-BETWEEN}
\ulShowIndex[1]{Authors between blocks}{authidx}
\typeout{AUTHORS-BETWEEN-END}
\begin{ulSongs}{authidx}
\beginsong{Second}[by={Bob Jones}]\endsong
\end{ulSongs}
\begin{ulSongs}{}
\beginsong{Unlisted}[by={Not collected}]
\ulIndexEntry[writers]{{Collective, Group}}
\endsong
\end{ulSongs}
\typeout{AUTHORS-LAST}
\ulShowIndex[1]{Authors after songs}{authidx}
\typeout{AUTHORS-LAST-END}
\ulShowIndex[1]{Custom authors}{writers}
""", r"""
\ulNewAuthorIndex{writers}{idx_writers}
\ulIndexSongsAs{writers}{A\theulSongNumber}
\let\OriginalAuthorLink\ulSongLink
\renewcommand\ulSongLink[2]{\typeout{AUTHOR-LINK:#1:#2}\OriginalAuthorLink{#1}{#2}}
""")
        (self.work / "book.tex").write_text(source)
        (self.work / "include/tags.txt").unlink()
        self.state.unlink()
        first = self.run_pass()
        self.assertIn("No complete previous-pass data", first)
        output = self.run_pass()
        final = self.run_pass()
        self.assertNotIn("Package ulsbs-index Warning", final)
        author = (self.work / "idx_auth.sbx").read_text()
        self.assertIn(r"\ulIndexDisplayEntry{Alice Smith}{\ulSongLink{song1-1.1}{1}}", author)
        self.assertIn(r"\ulIndexDisplayEntry{Bob Jones}{\ulSongLink{song1-1.1}{1}\\"
                      r"\ulSongLink{song2-1.1}{1}}", author)
        self.assertNotIn("Not collected", author)
        custom = (self.work / "idx_writers.sbx").read_text()
        self.assertIn("Collective, Group", custom)
        self.assertIn(r"\ulSongLink{song3-1.1}{A1}", custom)
        for position in ("FIRST", "BETWEEN", "LAST"):
            section = output.split(f"AUTHORS-{position}", 1)[1].split(f"AUTHORS-{position}-END", 1)[0]
            self.assertIn("AUTHOR-LINK:song1-1.1:1", section)
            self.assertIn("AUTHOR-LINK:song2-1.1:1", section)
            self.assertNotIn("AUTHOR-LINK:song3-1.1", section)

    def test_author_directives_change_only_following_record_events(self):
        (self.work / "book.tex").write_text(document(r"""
\begin{ulSongs}{authidx}
\beginsong{First}[by={Words by Bob Jones and Alice Smith}]\endsong
\end{ulSongs}\clearpage
\ulAuthorSepWord{ja}
\ulAuthorByWord{tekijä}
\ulAuthorIgnoreWord{unknown}
\begin{ulSongs}{authidx}
\beginsong{Second}[by={Sävellys tekijä Clara ja unknown}]\endsong
\beginsong{Third}[by={Bob and Alice}]\endsong
\end{ulSongs}
\ulShowIndex[1]{Authors}{authidx}
"""))
        for _ in range(3):
            self.run_pass()
        author = (self.work / "idx_auth.sbx").read_text()
        for name in ("Alice Smith", "Bob Jones", "Clara", "Bob and Alice"):
            self.assertIn(r"\ulIndexDisplayEntry{" + name + "}", author)
        for ignored in ("Words by", "Sävellys", "unknown"):
            self.assertNotIn(ignored, author)

    def test_author_repeated_selection_preserves_occurrences_without_source_replay(self):
        (self.work / "book.tex").write_text(document(r"""
\ulIncludeOnlySongs{2,1,2}
\begin{ulSongs}{authidx}
\beginsong{First}[by={Alice}]\global\advance\AuthorEffects by 1\endsong
\beginsong{Second}[by={Bob}]\global\advance\AuthorEffects by 1\endsong
\beginsong{Excluded}[by={Not indexed}]\endsong
\end{ulSongs}
\typeout{AUTHOR-EFFECTS:\the\AuthorEffects}
\ulShowIndex[1]{Authors}{authidx}
""", r"\newcount\AuthorEffects"))
        for _ in range(3):
            output = self.run_pass()
            self.assertIn("AUTHOR-EFFECTS:2", output)
        events = [event for event in index_events(self.work, "idx_auth") if event["type"] == "record"]
        self.assertEqual([event["title"] for event in events], ["Bob", "Alice", "Bob"])
        author = (self.work / "idx_auth.sbx").read_text()
        self.assertEqual(author.count(r"\ulSongLink{song1-2.1}{2}"), 2)
        self.assertNotIn("Not indexed", author)

    def test_author_output_is_job_local_and_nofiles_preserves_existing_output(self):
        source = document(r"""
\begin{ulSongs}{authidx}
\beginsong{First}[by={Alice}]\endsong
\end{ulSongs}
\ulShowIndex[1]{Authors}{authidx}
""")
        shadow = self.work / "shadow"
        shadow.mkdir()
        (shadow / "idx_auth.sbx").write_text(r"\UndefinedShadowAuthorIndex")
        (self.work / "book.tex").write_text(source)
        stale = b"\\UndefinedCwdAuthorIndex"
        (self.work / "idx_auth.sbx").write_bytes(stale)
        for absolute in (False, True):
            with self.subTest(absolute=absolute):
                out = self.work / ("absolute author output" if absolute else "relative author output")
                out.mkdir()
                for _ in range(2):
                    result = self.compile(self.work, include=shadow,
                                          output=out if absolute else out.relative_to(self.work))
                    self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn(r"\ulIndexDisplayEntry{Alice}", (out / "idx_auth.sbx").read_text())
                self.assertEqual((self.work / "idx_auth.sbx").read_bytes(), stale)
        initial = self.state.read_bytes()
        (self.work / "book.tex").write_text(r"\nofiles" + source)
        self.run_pass(failure=r"Cannot refresh index authidx with \nofiles")
        self.assertEqual(self.state.read_bytes(), initial)
        self.assertEqual((self.work / "idx_auth.sbx").read_bytes(), stale)

    def test_multiple_blocks_custom_destinations_and_explicit_overrides(self):
        source = document(r"""
\typeout{SHOW-FIRST}
\ulShowIndex[1]{All titles before songs}{titleidx}
\typeout{SHOW-FIRST-END}
\begin{ulSongs}{titleidx,tagidx,authidx}
\beginsong{First block}[tags={fire},by={First author}]\endsong
\end{ulSongs}
\typeout{SHOW-BETWEEN}
\ulShowIndex[1]{All titles between blocks}{titleidx}
\typeout{SHOW-BETWEEN-END}
\begin{ulSongs}{customtitles,customtags}
\beginsong{Second block}[tags={earth},by={Not automatic}]
\ulIndexTitleEntry[titleidx]{Explicit second}
\ulIndexEntry[tagidx]{circle}
\endsong
\end{ulSongs}
\begin{ulSongs}{}
\beginsong{Unlisted block}[tags={fire},by={Not collected}]
\ulIndexTitleEntry[customtitles]{Explicit unlisted}
\ulIndexEntry[customtags]{sound}
\endsong
\end{ulSongs}
\typeout{SHOW-LAST}
\ulShowIndex[1]{All titles after blocks}{titleidx}
\typeout{SHOW-LAST-END}
\ulShowIndex[1]{Custom titles}{customtitles}
\ulShowIndex[1]{Custom tags}{customtags}
\ulShowIndex[1]{Tags}{tagidx}
\ulShowIndex[1]{Authors}{authidx}
""", r"""
\ulNewIndex{customtitles}{custom_title}
\ulNewTagIndex{customtags}{custom_tag}
\ulIndexSongsAs{customtitles}{C\theulSongNumber}
\ulIndexSongsAs{customtags}{T\theulSongNumber}
\let\OriginalSongLink\ulSongLink
\renewcommand\ulSongLink[2]{\typeout{INDEX-LINK:#1:#2}\OriginalSongLink{#1}{#2}}
""")
        (self.work / "book.tex").write_text(source)
        self.state.unlink()
        self.run_pass()
        output = self.run_pass()
        self.run_pass()
        expected = {
            "idx_title": [("First block", "1", "song1-1.1"),
                          ("Explicit second", "1", "song2-1.1")],
            "idx_tag": [("fire", "1", "song1-1.1"), ("circle", "1", "song2-1.1")],
            "custom_title": [("Second block", "C1", "song2-1.1"),
                             ("Explicit unlisted", "C1", "song3-1.1")],
            "custom_tag": [("earth", "T1", "song2-1.1"), ("sound", "T1", "song3-1.1")],
            "idx_auth": [("First author", "1", "song1-1.1")],
        }
        for filename, records in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual([(event["title"], event["label"], event["target"])
                                  for event in index_events(self.work, filename)
                                  if event["type"] == "record"], records)
                fragment = (self.work / f"{filename}.sbx").read_text()
                for _, label, target in records:
                    self.assertIn(r"\ulSongLink{" + target + "}{" + label + "}", fragment)
        for position in ("FIRST", "BETWEEN", "LAST"):
            section = output.split(f"SHOW-{position}", 1)[1].split(f"SHOW-{position}-END", 1)[0]
            self.assertIn("INDEX-LINK:song1-1.1:1", section)
            self.assertIn("INDEX-LINK:song2-1.1:1", section)
            self.assertNotIn("INDEX-LINK:song3-1.1", section)
        self.assertIn(r"\ulIndexDisplayEntry{First author}",
                      (self.work / "idx_auth.sbx").read_text())

    def test_empty_index_list_collects_no_automatic_records(self):
        (self.work / "book.tex").write_text(document(r"""
\begin{ulSongs}{}
\beginsong{Not indexed}[tags={fire},by={Not indexed author}]\endsong
\end{ulSongs}
"""))
        self.state.unlink()
        self.run_pass()
        for entry in read_snapshot(self.state)["indices"].values():
            self.assertFalse(any(event["type"] == "record" for event in entry["events"]))

    def test_empty_unused_resources_honor_nofiles(self):
        empty = document(r"\begin{ulSongs}{}\end{ulSongs}\null")
        for source in (r"\nofiles" + empty,
                       empty.replace(r"\begin{document}", r"\nofiles\begin{document}")):
            for stale in (False, True):
                with self.subTest(source=source[:30], stale=stale):
                    (self.work / "book.tex").write_text(source)
                    initial = self.state.read_bytes()
                    for kind in ("title", "tag", "auth"):
                        path = self.work / f"idx_{kind}.sbx"
                        if stale:
                            path.write_bytes(b"untouched manual fragment")
                        else:
                            path.unlink(missing_ok=True)
                    self.run_pass()
                    self.assertEqual(self.state.read_bytes(), initial)
                    for kind in ("title", "tag", "auth"):
                        path = self.work / f"idx_{kind}.sbx"
                        if stale:
                            self.assertEqual(path.read_bytes(), b"untouched manual fragment")
                        else:
                            self.assertFalse(path.exists())

    def test_empty_unused_resources_belong_to_output_directory(self):
        (self.work / "book.tex").write_text(document(r"\begin{ulSongs}{}\end{ulSongs}\null"))
        (self.work / "include/tags.txt").unlink()
        for kind in ("title", "tag", "auth"):
            (self.work / f"idx_{kind}.sbx").unlink(missing_ok=True)
        initial = self.state.read_bytes()
        for absolute in (False, True):
            with self.subTest(absolute=absolute):
                out = self.work / ("absolute output" if absolute else "relative output")
                out.mkdir()
                result = self.compile(self.work, output=out if absolute else out.relative_to(self.work))
                self.assertEqual(result.returncode, 0, result.stdout)
                read_snapshot(out / self.state.name)
                for kind in ("title", "tag", "auth"):
                    self.assertEqual((out / f"idx_{kind}.sbx").read_bytes(), b"")
                    self.assertFalse((self.work / f"idx_{kind}.sbx").exists())
                self.assertEqual(self.state.read_bytes(), initial)

    def test_corrupt_incomplete_and_wrong_version_snapshots_are_actionable(self):
        valid = self.state.read_bytes()
        payload = valid.split(b"\n", 1)[1]
        bad_version = payload.replace(b"snapshot 3", b"snapshot 2", 1)
        checksummed = hashlib.md5(bad_version).hexdigest().encode() + b"\n" + bad_version
        for data in (b"truncated", valid + b"corrupt", checksummed):
            with self.subTest(data=data[:30]):
                self.state.write_bytes(data)
                output = self.run_pass(failure="book.ulsbs-index-state")
                self.assertIn("remove it and rerun LuaLaTeX twice", output)

    def test_aborted_pass_is_not_a_completed_snapshot(self):
        (self.work / "book.tex").write_text(SOURCE.replace(
            r"\end{ulSongs}", r"\end{ulSongs}\UndefinedAbort"))
        self.run_pass(failure="Undefined control sequence")
        self.assertIn(b"collecting", self.state.read_bytes())
        (self.work / "book.tex").write_text(SOURCE)
        self.run_pass(failure="Aborted earlier index pass")

    def test_nofiles_before_or_after_package_is_actionable(self):
        for source in (r"\nofiles" + SOURCE,
                       SOURCE.replace(r"\begin{document}", r"\nofiles\begin{document}")):
            with self.subTest(source=source[:30]):
                (self.work / "book.tex").write_text(source)
                self.run_pass(failure="enable file writing and rerun LuaLaTeX twice")

    def test_changed_source_recollects_before_display(self):
        (self.work / "book.tex").write_text(SOURCE.replace("{Index}", "{Changed title}"))
        self.assertIn("Source identity changed", self.run_pass())
        self.assertFalse((self.work / "idx_title.sbx").exists())
        self.assertNotIn("Package ulsbs-index Warning", self.run_pass())
        self.assertIn(b"Changed title", (self.work / "idx_title.sbx").read_bytes())
        self.assertNotIn(b"{Index}", (self.work / "idx_title.sbx").read_bytes())

    def test_missing_definitions_and_unknown_tags_do_not_publish(self):
        definitions = self.work / "include/tags.txt"
        definitions.unlink()
        self.run_pass(failure="tags.txt")
        shutil.copy2(self.seed / "book.ulsbs-index-state", self.state)
        definitions.write_text("earth\n")
        self.run_pass(failure="unknown tag 'fire'")

    def test_concurrent_same_jobname_isolated_directories(self):
        other = self.root / "independent"
        self.prepare(other, SOURCE.replace("{Index}", "{Independent index}"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            for _ in range(3):
                results = list(pool.map(lambda work: self.compile(work), (self.work, other)))
                for result in results:
                    self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotEqual((self.work / "idx_title.sbx").read_bytes(),
                            (other / "idx_title.sbx").read_bytes())
        self.assertNotIn(b"Independent index", self.state.read_bytes())
        self.assertNotIn(b"Index", (other / self.state.name).read_bytes())


if __name__ == "__main__":
    unittest.main()
