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
from pathlib import Path


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
    map_path = os.environ.get("ULSBS_SYNCTEX_SOURCE_MAP")
    inputs: dict[str, str] = {}
    active: list[str] = []

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
        active.append(output)
        try:
            return original(filename, included=included)
        finally:
            active.pop()

    state["do_file"] = do_file
    if map_path:
        if __package__:
            from .synctex import track_lilypond_sources
        else:
            from synctex import track_lilypond_sources

        track_lilypond_sources(state, active, inputs, Path(map_path))
    entrypoint()


if __name__ == "__main__":
    main()
