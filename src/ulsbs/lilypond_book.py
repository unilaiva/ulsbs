# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Launch installed lilypond-book without concatenating repeated TeX imports.

LilyPond 2.24 and 2.26 recursively collect chunks for every input occurrence,
then concatenate all chunks with the same output path. Process each output
document once instead; its original input commands still execute at every
placement in TeX. No installed LilyPond files or musical snippets are modified.
"""

from __future__ import annotations

import os
import runpy
import shutil
import sys


def main() -> None:
    """Run installed lilypond-book with duplicate output processing suppressed."""
    executable = shutil.which("lilypond-book")
    if executable is None:
        raise SystemExit("lilypond-book is not installed")
    sys.argv[0] = executable
    namespace = runpy.run_path(executable)
    entrypoint = namespace["main"]
    state = entrypoint.__globals__
    original = state["do_file"]
    processed = set()

    def do_file(filename, included=False):
        """Process an input only on its first encounter for a given output path."""
        base = os.path.splitext(filename)[0]
        if not included:
            base = os.path.basename(base)
        output = os.path.abspath(os.path.join(
            state["global_options"].output_dir,
            base + state["global_options"].formatter.default_extension,
        ))
        if output in processed:
            return []
        processed.add(output)
        return original(filename, included=included)

    state["do_file"] = do_file
    entrypoint()


if __name__ == "__main__":
    main()
