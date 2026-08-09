#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run all ULSBS source-tree test suites."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str]) -> int:
    print(f"+ {' '.join(command)}", flush=True)
    cache = ROOT / "build" / "texmf-cache"
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TEXMFVAR"] = str(cache)
    env["TEXMFCACHE"] = str(cache)
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-l3build", action="store_true")
    parser.add_argument("--skip-integration", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if not args.skip_l3build:
        result = _run(["l3build", "check", "--halt-on-error", "--show-log-on-error"])
        if result:
            return result

    if not args.skip_integration:
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
        ]
        if args.verbose:
            command.append("-v")
        result = _run(command)
        if result:
            return result

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
