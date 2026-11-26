# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test SyncTeX configuration, source mapping, and sidecar publication."""

from contextlib import redirect_stderr
import gzip
import importlib.metadata
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from ulsbs.cli import build_arg_parser
from ulsbs.config import build_config
from ulsbs.synctex import _rewrite
from ulsbs.ui import UI


class SyncTeXConfigTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.parser = build_arg_parser(UI(use_colors=False))

    def build(self, text, *flags):
        path = self.root / "ulsbs-config.toml"
        path.write_text(text, encoding="utf-8")
        args = self.parser.parse_args(["--no-deploy", *flags])
        return build_config(args_ns=args, config_path=path, profile=args.profile, env={},
                            runtime_project_paths=SimpleNamespace(project_root=self.root),
                            runtime_in_container=False, runtime_unique_id="test")

    def test_default_project_profile_and_cli_precedence(self):
        for mode in ((), ("--quick",)):
            with self.subTest(mode=mode):
                self.assertIs(self.build("", *mode).synctex, True)
                text = "synctex = false\n[profiles.on]\nsynctex = true\n"
                self.assertIs(self.build(text, *mode).synctex, False)
                self.assertIs(self.build(text, *mode, "--profile", "on").synctex, True)
                self.assertIs(self.build(text, *mode, "--synctex").synctex, True)
                self.assertIs(self.build(text, *mode, "--profile", "on", "--no-synctex").synctex, False)

    def test_config_requires_boolean(self):
        for prefix in ("", "[profiles.default]\n"):
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, "synctex must be a boolean"):
                self.build(prefix + 'synctex = "false"')

    def test_cli_flags_are_mutually_exclusive(self):
        for flags in (("--synctex", "--no-synctex"), ("--no-synctex", "--synctex")):
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as error:
                    self.parser.parse_args(flags)
                self.assertEqual(error.exception.code, 2)
                self.assertIn("not allowed with argument", stderr.getvalue())


class SyncTeXRewriteTests(unittest.TestCase):
    def test_reopened_sources_share_tag_and_form_and_geometry_are_preserved(self):
        work = Path("/container/build")
        project = Path("/container")
        main = project / "book.lytex"
        output = io.BytesIO()
        before = b"SyncTeX Version:1\nInput:1:./book.tex\nOutput:pdf\nContent:\n"
        body = (b"{1\n(1,7:10,20:30,40,0\n)\n}1\n"
                b"Input:2:/container/build/book.tex\n"
                b"{2\nf2,7:10,20\n?2,7:10,20\n(2,8:10,20:30,40,0\n)\n}2\n")
        anchor = f"!{len(before)}\n".encode()
        data = before + anchor + body + f"!{len(anchor + body)}\nPostamble:\n".encode()
        _rewrite(io.BytesIO(data), output, {work / "book.tex": (main, list(range(-5, 3)))},
                 work, main, project, Path("/host path"))
        rewritten = output.getvalue()
        self.assertEqual(rewritten.count(b"Input:"), 1)
        self.assertIn(b"Input:1:/host path/book.lytex\n", rewritten)
        self.assertIn(b"f2,7:10,20\n?1,1:10,20\n(1,2:10,20:30,40,0\n", rewritten)
        previous = 0
        for anchor in re.finditer(rb"^!([0-9]+)$", rewritten, re.M):
            self.assertEqual(int(anchor[1]), anchor.start() - previous)
            previous = anchor.start()
        with self.assertRaisesRegex(ValueError, "invalid SyncTeX anchor"):
            bad = data.replace(f"!{len(before)}".encode(), b"!0", 1)
            _rewrite(io.BytesIO(bad), io.BytesIO(), {work / "book.tex": (main, [1])},
                     work, main, project, Path("/host"))


@unittest.skipUnless(all(shutil.which(tool) for tool in
                        ("lualatex", "lilypond", "lilypond-book", "synctex", "pdftotext")),
                     "requires LuaLaTeX, LilyPond and SyncTeX/Poppler CLI tools")
class SyncTeXCompilerTests(unittest.TestCase):
    def test_build_publishes_original_lines_then_retires_stale_sidecar(self):
        try:
            major = int(importlib.metadata.version("pikepdf").split(".", 1)[0])
        except importlib.metadata.PackageNotFoundError:
            major = 0
        if major < 10:
            self.skipTest("requires pikepdf>=10")
        tmp = self.enterContext(tempfile.TemporaryDirectory(prefix="ulsbs sync "))
        root = Path(tmp).resolve()
        (root / "content").mkdir()
        (root / "include").mkdir()
        (root / "texmf-cache").mkdir()
        files = {
            "ulsbs-config.toml": "",
            "book.tex": r"""\documentclass[maintitle={Sync Fixture}]{ulsbs-songbook}
\begin{document}
MainDocumentAnchor\par
\begin{ulSongs}{titleidx}
\input{include/chapter.tex}
\end{ulSongs}
\ulShowIndex{Title Index}{titleidx}
\end{document}
""",
            "include/chapter.tex": r"""% This path is relative to the book root.
\input{content/song.tex}
\input{content/second.tex}
""",
            "content/song.tex": r"""% !TeX root = ../book.tex
\beginsong{First Song}[id={first},key={C}]
\beginverse+
|\[C]FirstLyricAnchor
|\[<C D;E F>G7]MelodyLyricAnchor
\endverse
\begin{lilywrap}
\begin{lilypond}[]
\relative c' { c4 d e f }
\end{lilypond}
\end{lilywrap}
\beginverse
\[C]AfterScoreAnchor
\endverse
\endsong
""",
            "content/second.tex": r"""% !TeX root = ../book.tex
\beginsong{Second Song}[id={second},key={G}]
\beginverse
\[G]SecondLyricAnchor
\endverse
\endsong
""",
        }
        for name, text in files.items():
            (root / name).write_text(text, encoding="utf-8")
        cache = str(root / "texmf-cache")
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
               "ULSBS_USE_SYSTEM_TMP_FOR_TEMP": "false", "TEXMFVAR": cache, "TEXMFCACHE": cache}
        argv = [sys.executable, "-m", "ulsbs", "--plain-output", "--no-deploy", "--no-container"]
        book = str(root / "book.tex")
        pdf = root / "result/book.pdf"
        sidecar = pdf.with_suffix(".synctex.gz")

        def run(args):
            process = subprocess.run(args, cwd=root, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, timeout=100)
            output = process.stdout.decode("utf-8", errors="replace")
            self.assertEqual(process.returncode, 0, output)
            return output

        run([*argv, "--quick", book])
        data = gzip.decompress(sidecar.read_bytes()).decode("utf-8")
        for name, lines in {"book.tex": (3,), "content/song.tex": (4, 5, 13),
                            "content/second.tex": (4,)}.items():
            path = root / name
            self.assertIn(f":{path}\n", data)
            for line in lines:
                forward = run(["synctex", "view", "-i", f"{line}:1:{path}", "-o", str(pdf)])
                self.assertIn("Page:1\n", forward)
        bbox = run(["pdftotext", "-bbox", str(pdf), "-"])
        for anchor, name, line in (
            ("MainDocumentAnchor", "book.tex", 3),
            ("MelodyLyricAnchor", "content/song.tex", 5),
            ("AfterScoreAnchor", "content/song.tex", 13),
            ("SecondLyricAnchor", "content/second.tex", 4),
        ):
            with self.subTest(anchor=anchor):
                word = re.search(r'<word xMin="([0-9.]+)" yMin="([0-9.]+)" '
                                 rf'xMax="([0-9.]+)" yMax="([0-9.]+)">{anchor}</word>', bbox)
                self.assertIsNotNone(word)
                xmin, ymin, xmax, ymax = map(float, word.groups())
                x, y = xmin + (xmax - xmin) / 4, (ymin + ymax) / 2
                reverse = run(["synctex", "edit", "-o", f"1:{x:g}:{y:g}:{pdf}"])
                self.assertIn(f"Input:{root / name}\nLine:{line}\n", reverse)
        self.assertIn("Title Index", run(["pdftotext", "-layout", str(pdf), "-"]))
        self.assertRegex(data, r"Input:\d+:.*-systems\.tex")
        uncompressed = pdf.with_suffix(".synctex")
        uncompressed.write_text("stale", encoding="utf-8")
        run([*argv, "--quick", "--no-synctex", book])
        self.assertTrue(pdf.is_file())
        self.assertFalse(sidecar.exists())
        self.assertFalse(uncompressed.exists())

        (root / "ulsbs-config.toml").write_text("synctex = false\n", encoding="utf-8")
        run([*argv, "--no-printouts", "--no-coverimage", "--no-midi", "--no-audio",
             "--no-json", "--synctex", book])
        self.assertIn(f":{root / 'book.tex'}\n", gzip.decompress(sidecar.read_bytes()).decode("utf-8"))
