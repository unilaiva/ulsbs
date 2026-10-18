# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Source isolation and repeated-import handling for lilypond-book."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ulsbs import lilypond_book, pipeline


class LilyPondBookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ulsbs book ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_launcher_processes_each_output_once_but_retains_input_commands(self):
        executable = self.root / "lilypond-book"
        output = self.root / "output.json"
        executable.write_text('''import json
import sys
from types import SimpleNamespace
global_options = SimpleNamespace(output_dir=sys.argv[1], formatter=SimpleNamespace(default_extension=".tex"))
calls = []
def do_file(filename, included=False):
    calls.append(filename)
    if not included:
        return ["input one", "input two", *do_file("song.tex", True), *do_file("./song", True),
                *do_file("other/song.tex", True)]
    return [filename]
def main():
    chunks = do_file("book.tex")
    with open(sys.argv[2], "w") as output:
        json.dump([calls, chunks], output)
''', encoding="utf-8")
        with patch.object(lilypond_book.shutil, "which", return_value=str(executable)), \
                patch.object(sys, "argv", ["launcher", str(self.root), str(output)]):
            lilypond_book.main()
        calls, chunks = json.loads(output.read_text())
        self.assertEqual(calls, ["book.tex", "song.tex", "other/song.tex"])
        self.assertEqual(chunks, ["input one", "input two", "song.tex", "other/song.tex"])

    def test_launcher_requires_installed_book(self):
        with patch.object(lilypond_book.shutil, "which", return_value=None):
            with self.assertRaisesRegex(SystemExit, "not installed"):
                lilypond_book.main()

    def test_pipeline_ignores_interrupted_output_and_filters_only_generated_search_paths(self):
        directory = self.root / "job"
        directory.mkdir()
        doc = self.root / "book.tex"
        doc.write_text("original", encoding="utf-8")
        input_tex = directory / doc.name
        input_tex.write_text("configured original", encoding="utf-8")
        lp_out = directory / "_lp"
        lp_out.mkdir()
        (lp_out / "stale.tex").write_text("interrupted output", encoding="utf-8")
        job = SimpleNamespace(compile_dir=directory, doc_tex_abs=doc)
        assets = directory / "ulsbs-assets/tex"
        env = {"TEXINPUTS": f"{directory}/content:{assets}:{directory}:{self.root}:",
               "LUAINPUTS": f"{directory}/include:{self.root}:", "KEEP": "value"}
        before = env.copy()

        def process(command, **kwargs):
            self.assertEqual(command[0], sys.executable)
            self.assertTrue(command[1].endswith("lilypond_book.py"))
            self.assertIn(str(self.root), command)
            self.assertNotIn("--use-source-file-names", command)
            aliases = directory / "_lp-source"
            self.assertEqual(command[-1], str(aliases / input_tex.name))
            self.assertEqual((aliases / input_tex.name).read_text(), "configured original")
            self.assertEqual(kwargs["cwd"], aliases)
            self.assertEqual(kwargs["env"], {"TEXINPUTS": f"{aliases}:{assets}:{self.root}:",
                                             "LUAINPUTS": f"{aliases}:{self.root}:", "KEEP": "value"})
            self.assertFalse((lp_out / "stale.tex").exists())
            (lp_out / doc.name).write_text("processed", encoding="utf-8")
            (lp_out / "current-systems.tex").write_text("graphic", encoding="utf-8")

        with patch.object(pipeline, "run_cmd", side_effect=process):
            processed, _, step = pipeline.step_lilypond_book(Mock(), job, input_tex, env, ["-I", str(self.root)], 1)
        self.assertEqual(step, 2)
        self.assertEqual(processed.read_text(), "processed")
        self.assertEqual(doc.read_text(), "original")
        self.assertEqual(env, before)
        self.assertFalse(lp_out.exists())
        self.assertEqual(json.loads((directory / "book.ulsbs-lilypond-systems.json").read_text()),
                         ["current-systems.tex"])

    def test_stale_expected_output_cannot_mask_missing_current_output(self):
        directory = self.root / "job"
        directory.mkdir()
        input_tex = directory / "book.tex"
        input_tex.write_text("source", encoding="utf-8")
        lp_out = directory / "_lp"
        lp_out.mkdir()
        (lp_out / input_tex.name).write_text("stale processed", encoding="utf-8")
        job = SimpleNamespace(compile_dir=directory, doc_tex_abs=self.root / "book.tex")
        with patch.object(pipeline, "run_cmd"):
            with self.assertRaisesRegex(pipeline.CompileError, "did not produce"):
                pipeline.step_lilypond_book(Mock(), job, input_tex, {}, [], 1)
