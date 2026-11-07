# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manual LuaLaTeX pass lifecycle and resource isolation."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from index_records import read_snapshot


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src/ulsbs/assets/tex"
FIXTURES = ROOT / "tests/fixtures/index"
SHOW = "\\ulShowIndex[1]{Titles}{titleidx}\n\\ulShowIndex[1]{Tags}{tagidx}\n"
SOURCE = (FIXTURES / "collection.tex").read_text(encoding="utf-8").replace(
    r"\end{document}", SHOW + r"\end{document}"
)


class IndexLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("lualatex") is None:
            raise unittest.SkipTest("LuaLaTeX is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ulsbs-index-lifecycle-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.cache = cls.root / "cache"
        cls.cache.mkdir()
        cls.seed = cls.root / "seed"
        cls.prepare(cls.seed)
        cls.draft = cls.compile(cls.seed, draft=True)
        if cls.draft.returncode:
            raise AssertionError(cls.draft.stdout)

    @classmethod
    def prepare(cls, work, source=SOURCE):
        work.mkdir()
        (work / "book.tex").write_text(source, encoding="utf-8")
        (work / "include").mkdir()
        shutil.copy2(FIXTURES / "tags.txt", work / "include/tags.txt")

    @classmethod
    def compile(cls, work, *, draft=False, include=None, output=None):
        env = os.environ.copy()
        env.update(TEXINPUTS=f"{ASSETS}//{os.pathsep}", LUAINPUTS=f"{ASSETS}//{os.pathsep}",
                   TEXMFVAR=str(cls.cache), TEXMFCACHE=str(cls.cache),
                   SOURCE_DATE_EPOCH="1792843200", max_print_line="10000")
        if include is not None:
            env["TEXINPUTS"] = f"{include}{os.pathsep}" + env["TEXINPUTS"]
        return subprocess.run(
            ["lualatex", "-file-line-error", "-halt-on-error",
             "-interaction=nonstopmode", "-jobname=book"]
            + (["-draftmode"] if draft else [])
            + ([f"-output-directory={output}"] if output is not None else [])
             + ["book.tex"],
            cwd=work, env=env, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120,
            check=False,
        )

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.root, prefix="case-"))
        shutil.copytree(self.seed, self.work, dirs_exist_ok=True)

    def success(self, work=None, *, draft=False):
        result = self.compile(work or self.work, draft=draft)
        self.assertEqual(result.returncode, 0, result.stdout)
        return " ".join(result.stdout.split())

    def failure(self, diagnostic, work=None):
        result = self.compile(work or self.work)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        output = " ".join(result.stdout.split())
        self.assertIn(diagnostic, output)
        return output

    def assert_indices(self, work=None):
        work = work or self.work
        snapshot = read_snapshot(work / "book.ulsbs-index-state")
        for kind in ("title", "tag"):
            with self.subTest(kind=kind):
                rendered = (work / f"idx_{kind}.sbx").read_text()
                events = snapshot["indices"][f"{kind}idx"]["events"]
                records = [event for event in events if event["type"] == "record"]
                self.assertTrue(records)
                for record in records:
                    self.assertIn(r"\ulSongLink{" + record["target"] + "}{" + record["label"] + "}", rendered)
                self.assertIn(r"\begin{ulIndexBlock}", rendered)
        self.assertIn(b"fire", (work / "idx_tag.sbx").read_bytes())

    def write_source(self, source, work=None):
        ((work or self.work) / "book.tex").write_text(source, encoding="utf-8")

    def test_manual_draft_full_full_uses_completed_records(self):
        self.assertIn("No complete previous-pass data", self.draft.stdout)
        for kind in ("title", "tag", "auth"):
            self.assertFalse((self.work / f"idx_{kind}.sxd").exists())
        read_snapshot(self.work / "book.ulsbs-index-state")
        for phase in ("first full", "second full"):
            with self.subTest(phase=phase):
                output = self.success()
                self.assertNotIn("Package ulsbs-index Warning", output)
                self.assert_indices()
        self.assertTrue((self.work / "book.pdf").is_file())

    def test_missing_state_never_consumes_poisoned_generic_sbx_or_sxd(self):
        (self.work / "book.ulsbs-index-state").unlink()
        for kind in ("title", "tag"):
            (self.work / f"idx_{kind}.sbx").write_text(r"\PoisonedOldIndex")
            (self.work / f"idx_{kind}.sxd").write_text("POISONED OLD RECORDS\n")
        output = self.success()
        self.assertIn("No complete previous-pass data for titleidx", output)
        self.assertIn("No complete previous-pass data for tagidx", output)
        for kind in ("title", "tag"):
            path = self.work / f"idx_{kind}.sbx"
            self.assertTrue(not path.exists() or not path.read_bytes())
        self.success()
        self.assert_indices()

    def test_generated_fragments_override_search_path_shadows(self):
        search = self.work / "shadow"
        search.mkdir()
        shadow = (b"\\typeout{UNRELATED-INDEX-SHADOW-LOADED}\n"
                  b"\\begin{ulIndexBlock}{X}\n"
                  b"\\ulIndexDisplayEntry{Wrong unrelated book}{999}\n"
                  b"\\end{ulIndexBlock}\n")
        for kind in ("title", "tag"):
            (search / f"idx_{kind}.sbx").write_bytes(shadow)
        for _ in range(2):
            result = self.compile(self.work, include=search)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertNotIn("UNRELATED-INDEX-SHADOW-LOADED", result.stdout)
            self.assertNotIn("Package ulsbs-index Warning", result.stdout)
            for kind in ("title", "tag"):
                self.assertIn(str(self.work / f"idx_{kind}.sbx"),
                              result.stdout.replace("/./", "/"))
                self.assertEqual((search / f"idx_{kind}.sbx").read_bytes(), shadow)
            self.assert_indices()

    def test_first_pass_does_not_input_search_path_shadow(self):
        (self.work / "book.ulsbs-index-state").unlink()
        search = self.work / "shadow"
        search.mkdir()
        for kind in ("title", "tag"):
            (search / f"idx_{kind}.sbx").write_text(r"\UndefinedStaleShadow")
        result = self.compile(self.work, include=search)
        self.assertEqual(result.returncode, 0, result.stdout)
        for kind, identifier in (("title", "titleidx"), ("tag", "tagidx")):
            self.assertIn(f"No complete previous-pass data for {identifier}", result.stdout)
            self.assertNotIn(str(search / f"idx_{kind}.sbx"), result.stdout)
            path = self.work / f"idx_{kind}.sbx"
            self.assertTrue(not path.exists() or not path.read_bytes())
        result = self.compile(self.work, include=search)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assert_indices()

    def test_output_directory_owns_snapshot_fragments_and_collected_inputs(self):
        state = self.work / "book.ulsbs-index-state"
        state.write_bytes(b"Unrelated working-directory snapshot must not be read")
        original = state.read_bytes()
        for absolute in (False, True):
            with self.subTest(absolute=absolute):
                out = self.work / ("out absolute" if absolute else "out relative")
                out.mkdir()
                output = out if absolute else out.relative_to(self.work)
                for phase in range(3):
                    result = self.compile(self.work, draft=phase == 0, output=output)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    if phase == 0:
                        self.assertIn("No complete previous-pass data", result.stdout)
                    else:
                        self.assertNotIn("Package ulsbs-index Warning", result.stdout)
                        self.assert_indices(out)
                        for kind in ("title", "tag"):
                            self.assertIn(str(out / f"idx_{kind}.sbx"), result.stdout)
                self.assertIn(b"complete", (out / "book.ulsbs-index-state").read_bytes())
                self.assertTrue((out / "book.pdf").is_file())
                self.assertFalse(list(out.glob("*.sxd")))
                self.assertFalse((out / "idx_auth.sbx").exists())
                self.assertEqual(state.read_bytes(), original)
                for kind in ("title", "tag"):
                    self.assertFalse((self.work / f"idx_{kind}.sbx").exists())

    def test_changed_source_and_order_require_rerun_then_stabilize(self):
        original = SOURCE[SOURCE.index(r"\beginsong"):SOURCE.index(r"\end{ulSongs}")]
        other = original.replace("Index observation", "Another observation").replace(
            "index-observation", "another-observation")
        for songs in (original + other, other + original):
            with self.subTest(order=songs[:80]):
                self.write_source(SOURCE.replace(original, songs))
                output = self.success()
                self.assertIn("Rerun LuaLaTeX", output)
                for kind in ("title", "tag"):
                    path = self.work / f"idx_{kind}.sbx"
                    self.assertTrue(not path.exists() or not path.read_bytes(),
                                    "Changed source must not publish the old snapshot")
                for _ in range(2):
                    output = self.success()
                    self.assertNotIn("Package ulsbs-index Warning", output)
                    self.assert_indices()

    def test_malformed_and_checksum_corrupt_state_are_actionable(self):
        path = self.work / "book.ulsbs-index-state"
        valid = path.read_bytes()
        for state in (b"not a snapshot\n", valid + b"corruption"):
            with self.subTest(state=state[:40]):
                path.write_bytes(state)
                output = self.failure("book.ulsbs-index-state")
                self.assertIn("remove it and rerun LuaLaTeX twice", output)

    def test_checksummed_malformed_payload_is_not_silently_accepted(self):
        path = self.work / "book.ulsbs-index-state"
        payload = path.read_bytes().split(b"\n", 1)[1] + b"999:truncated"
        path.write_bytes(hashlib.md5(payload).hexdigest().encode() + b"\n" + payload)
        output = self.failure("book.ulsbs-index-state")
        self.assertRegex(output, "[Mm]alformed|[Tt]runcated")
        self.assertIn("remove it and rerun LuaLaTeX twice", output)

    def test_aborted_pass_leaves_collecting_state_and_blocks_reuse(self):
        self.write_source(SOURCE.replace(r"\end{ulSongs}",
                                        r"\end{ulSongs}\UndefinedAbortProbe"))
        self.failure("Undefined control sequence")
        self.assertIn(b"collecting", (self.work / "book.ulsbs-index-state").read_bytes())
        self.write_source(SOURCE)
        output = self.failure("Aborted earlier index pass")
        self.assertIn("remove it and rerun LuaLaTeX twice", output)

    def test_nofiles_fails_for_requested_indices_before_or_after_package_load(self):
        for source in (r"\nofiles" + SOURCE,
                       SOURCE.replace(r"\begin{document}", r"\nofiles\begin{document}")):
            with self.subTest(source=source[:50]):
                self.write_source(source)
                output = self.failure(r"\nofiles")
                self.assertIn("enable file writing", output)

    def test_missing_definitions_and_unknown_tags_are_errors(self):
        definitions = self.work / "include/tags.txt"
        definitions.unlink()
        self.failure("tags.txt")
        # Failed passes mark collecting; restore the known completed draft.
        shutil.copy2(self.seed / "book.ulsbs-index-state",
                     self.work / "book.ulsbs-index-state")
        definitions.write_text("earth\n", encoding="utf-8")
        output = self.failure("unknown tag")
        self.assertIn("fire", output)

    def test_project_definitions_resolve_through_tex_search_path(self):
        definitions = self.work / "include/tags.txt"
        project = self.work / "project-include"
        project.mkdir()
        definitions.rename(project / "tags.txt")
        result = self.compile(self.work, include=project)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assert_indices()

    def test_default_include_definitions_take_precedence_over_search_path(self):
        search = self.work / "shadow-tags"
        search.mkdir()
        (search / "tags.txt").write_text("not-fire\n", encoding="utf-8")
        result = self.compile(self.work, include=search)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assert_indices()

    def test_explicit_tag_file_search_filename_and_relative_path_with_spaces(self):
        for filename, search_path in (("custom-tags.txt", True),
                                      ("tag definitions/custom tags.txt", False)):
            with self.subTest(filename=filename):
                work = self.work / ("search" if search_path else "relative")
                source = SOURCE.replace(r"\begin{document}",
                                        r"\ulTagFile{" + filename + r"}\begin{document}")
                self.prepare(work, source)
                (work / "include/tags.txt").write_text("not-fire\n", encoding="utf-8")
                search = work / "tex-search"
                search.mkdir()
                path = (search if search_path else work) / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fire & light|fire\n", encoding="utf-8")
                for _ in range(3):
                    result = self.compile(work, include=search)
                    self.assertEqual(result.returncode, 0, result.stdout)
                fragment = (work / "idx_tag.sbx").read_text()
                self.assertIn(r"\begin{ulIndexBlock}{fire \& light}", fragment)
                self.assertIn(r"\ulIndexDisplayEntry{}{", fragment)
                self.assertNotIn("not-fire", fragment)

    def test_explicit_default_filename_uses_standard_search_not_include_preference(self):
        search = self.work / "explicit-search"
        search.mkdir()
        (search / "tags.txt").write_text("search fire|fire\n", encoding="utf-8")
        (self.work / "include/tags.txt").write_text("not-fire\n", encoding="utf-8")
        self.write_source(SOURCE.replace(r"\begin{document}",
                                        r"\ulTagFile{tags.txt}\begin{document}"))
        for _ in range(3):
            result = self.compile(self.work, include=search)
            self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(r"\begin{ulIndexBlock}{search fire}",
                      (self.work / "idx_tag.sbx").read_text())

    def test_missing_explicit_tag_file_does_not_fall_back_to_default(self):
        self.write_source(SOURCE.replace(r"\begin{document}",
                                        r"\ulTagFile{missing-custom-tags.txt}\begin{document}"))
        self.success(draft=True)
        output = self.failure("missing-custom-tags.txt")
        self.assertIn("Missing tag definitions", output)
        self.assertIn(r"\ulTagFile", output)

    def test_tag_file_setter_is_preamble_only(self):
        self.write_source(SOURCE.replace(r"\begin{document}",
                                        r"\begin{document}\ulTagFile{tags.txt}"))
        self.failure("Can be used only in preamble")

    def test_author_fragment_is_generated_from_completed_records(self):
        author = self.work / "idx_auth.sbx"
        self.assertFalse(author.exists())
        author.write_text(r"\UndefinedStaleAuthorIndex")
        self.write_source(SOURCE.replace(SHOW, SHOW + r"\ulShowIndex{Authors}{authidx}"))
        output = self.success()
        self.assertIn("No complete previous-pass data", output)
        self.assertNotIn("Undefined control sequence", output)
        self.assertFalse(author.exists())
        self.success()
        self.assertIn(r"\ulIndexDisplayEntry{Example Author}{\ulSongLink{song1-1.1}{1}}",
                      author.read_text())
        before = author.read_bytes()
        output = self.success()
        self.assertNotIn("Package ulsbs-index Warning", output)
        self.assertEqual(author.read_bytes(), before)

    def test_showtags_visibility_does_not_change_collection(self):
        expected = read_snapshot(self.seed / "book.ulsbs-index-state")["indices"]
        self.write_source(r"\def\ProbeShowTags{1}" + SOURCE)
        self.success(draft=True)
        self.assertEqual(read_snapshot(self.work / "book.ulsbs-index-state")["indices"], expected)
        self.success()
        self.assert_indices()

    def test_concurrent_same_jobname_in_isolated_directories(self):
        other = self.root / "concurrent-other"
        self.prepare(other, SOURCE.replace("Index observation", "Independent book"))
        (self.work / "book.ulsbs-index-state").unlink()
        with ThreadPoolExecutor(max_workers=2) as pool:
            for draft in (True, False, False):
                results = list(pool.map(lambda work, draft=draft: self.compile(work, draft=draft),
                                        (self.work, other)))
                for result in results:
                    self.assertEqual(result.returncode, 0, result.stdout)
        for work in (self.work, other):
            self.assert_indices(work)
        self.assertNotEqual((self.work / "idx_title.sbx").read_bytes(),
                            (other / "idx_title.sbx").read_bytes())
        self.assertNotIn(b"Independent book", (self.work / "book.ulsbs-index-state").read_bytes())
        self.assertNotIn(b"Index observation", (other / "book.ulsbs-index-state").read_bytes())


if __name__ == "__main__":
    unittest.main()
