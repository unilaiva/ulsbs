# SPDX-FileCopyrightText: 2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Repeat-box diagnostics are observable even for unselected source songs."""

import json
import os
from pathlib import Path
import re
import unittest

import test_song_lifecycle as lifecycle
import test_song_order as order
from test_tex_integration import ROOT


class RepeatDiagnosticsTests(unittest.TestCase):
    setUp = lifecycle.SongLifecycleTests.setUp
    compile_source = lifecycle.SongLifecycleTests.compile_source
    compile_checked = order.SongOrderTests.compile_checked

    @classmethod
    def setUpClass(cls):
        lifecycle.SongLifecycleTests.setUpClass.__func__(cls)
        cls.diagnostics = Path(os.environ.get(
            "ULSBS_REPEAT_DIAGNOSTICS", ROOT / "build/repeat-diagnostics"))
        cls.diagnostics.mkdir(parents=True, exist_ok=True)

    def check(self, *, selected, mode):
        # Each final source paragraph wraps, so endrep must emit the remaining
        # repeat-bar fragment. Its zero-width box deliberately has positive
        # natural width: content inset plus the optional verse inset.
        body = "\\begin{ulSongs}{titleidx,authidx,tagidx}\n"
        body += "\\beginsong{Wrapped}[id={wrapped},by={Author},tags={fire}]\n"
        for option in ("", "[1]"):
            body += "\\beginverse" + option + "\n\\beginrep\n\\Effect "
            body += "wrapped words " * 18
            body += "\n\\endrep\n\\endverse\n"
        body += r"""\endsong
\beginsong{Visible}[id={visible},by={Author},tags={fire}]
\beginverse*
\Effect Visible line
\endverse
\endsong
\end{ulSongs}\typeout{REPEAT-EFFECTS:\the\Effects}
"""
        preamble = r"""
\newcount\Effects\def\Effect{\global\advance\Effects1\relax}
"""
        preamble += r"\ulIncludeOnlySongs{1}" if selected else r"\ulIncludeOnlySongs{2}"
        if mode == "hidden":
            preamble += r"\chordsoff"
        if mode == "lyrics":
            preamble += r"\input{ulsbs-internal-lyricbook-postsetup.tex}"
        source = lifecycle.document(body, preamble)
        label = f"{mode}-{'selected' if selected else 'excluded'}"
        outputs = self.compile_checked(source, label)
        expected_lines = [n for n, line in enumerate(source.splitlines(), 1)
                          if line.strip() == r"\endrep"] * 2
        report = {}
        for result, output in outputs.items():
            compiled = source
            warnings = re.findall(r"Overfull \\hbox \([^\n]*detected at line \d+", output)
            report[result] = {
                "warnings": warnings,
                "source_lines": [
                    {"line": int(re.search(r"line (\d+)$", message).group(1)),
                     "text": compiled.splitlines()[
                         int(re.search(r"line (\d+)$", message).group(1)) - 1]}
                    for message in warnings
                ],
                "effects": re.findall(r"REPEAT-EFFECTS:(\d+)", output),
            }
        path = self.diagnostics / self._testMethodName / label / "warnings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.assertEqual([row["line"] for row in report["output"]["source_lines"]],
                         expected_lines, str(path))
        widths = [float(re.search(r"\(([\d.]+)pt", warning).group(1))
                  for warning in report["output"]["warnings"]]
        self.assertTrue(all(width > 0 for width in widths), str(path))
        self.assertGreater(widths[1], widths[0], str(path))
        self.assertEqual(report["output"]["effects"], ["3", "3"], str(path))

    def test_excluded_wrapped_repeat_diagnostics(self):
        for mode in ("chorded", "hidden", "lyrics"):
            with self.subTest(mode=mode):
                self.check(selected=False, mode=mode)

    def test_selected_wrapped_repeat_diagnostics(self):
        for mode in ("chorded", "hidden", "lyrics"):
            with self.subTest(mode=mode):
                self.check(selected=True, mode=mode)


if __name__ == "__main__":
    unittest.main()
