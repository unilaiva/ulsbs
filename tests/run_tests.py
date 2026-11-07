#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run all ULSBS source-tree test suites."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, capture: bool = False) -> int:
    print(f"+ {' '.join(command)}", flush=True)
    cache = ROOT / "build" / "texmf-cache"
    cache.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TEXMFVAR"] = str(cache)
    env["TEXMFCACHE"] = str(cache)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), str(ROOT / "tests"), env.get("PYTHONPATH", "")]
    )
    started = time.monotonic()
    result = subprocess.run(
        command, cwd=ROOT, env=env, check=False,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
    )
    if capture:
        # Keep each worker's output together, including skipped-test summaries.
        print(f"\n{' '.join(command)} ({time.monotonic() - started:.1f}s)\n"
              f"{result.stdout}", flush=True)
    return result.returncode


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-l3build", action="store_true")
    parser.add_argument("--skip-integration", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--jobs", type=positive_int, default=4,
                        help="parallel Python test modules (default: 4; 1 for serial)")
    args = parser.parse_args(argv)
    if args.skip_l3build and args.skip_integration:
        parser.error("all test suites were skipped")
    started = time.monotonic()

    if not args.skip_l3build:
        result = _run(["l3build", "check", "--halt-on-error", "--show-log-on-error"])
        if result:
            return result

    if not args.skip_integration:
        modules = sorted((ROOT / "tests").glob("test_*.py"))
        if not modules:
            parser.error("no Python test modules found")
        failed = []
        with ThreadPoolExecutor(max_workers=args.jobs) as workers:
            futures = {}
            for module in modules:
                command = [sys.executable, "-m", "unittest", module.stem]
                if args.verbose:
                    command.append("-v")
                futures[workers.submit(_run, command, capture=True)] = module.stem
            for future in as_completed(futures):
                if future.result():
                    failed.append(futures[future])
        print(f"Python modules: {len(modules)}, failed: {len(failed)}", flush=True)
        if failed:
            print("Failed: " + ", ".join(sorted(failed)), file=sys.stderr)
            print(f"Suite wall time: {time.monotonic() - started:.1f}s", flush=True)
            return 1

    print(f"Suite wall time: {time.monotonic() - started:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
