# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run the ULSBS test suite on the host or in the compiler container."""

from __future__ import annotations

import argparse
import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from .container import (
    _CONTAINER_IMAGE_NAME,
    _HOMECACHE_VOLUME_NAME,
    _pick_container_engine,
    _run_named_container,
    ensure_container_image,
)
from .engine_assets import EngineAssets
from .ui import UI


def _default_memory_gb() -> int:
    try:
        return int(os.environ.get("ULSBS_MAX_CONTAINER_MEM_GB") or 6)
    except ValueError:
        return 6


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ulsbs-test",
        description="Run ULSBS tests in the compiler container by default.",
    )
    parser.add_argument(
        "--no-container",
        action="store_true",
        help="run tests using the host toolchain instead of Docker/Podman",
    )
    parser.add_argument(
        "--container-engine",
        choices=["auto", "docker", "podman"],
        default=os.environ.get("ULSBS_CONTAINER_ENGINE", "auto"),
        help="container engine (default: auto, preferring Docker)",
    )
    parser.add_argument(
        "--container-rebuild",
        action="store_true",
        help="force rebuilding the compiler image before testing",
    )
    parser.add_argument(
        "--container-memory-gb",
        type=int,
        default=_default_memory_gb(),
        metavar="GB",
        help="container memory limit in GiB (default: 6)",
    )
    parser.add_argument(
        "--container-memory-unlimited",
        action="store_true",
        help="do not pass container memory limits",
    )
    parser.add_argument(
        "--skip-l3build",
        action="store_true",
        help="skip normalized TeX regression tests",
    )
    parser.add_argument(
        "--skip-integration",
        action="store_true",
        help="skip unittest compilation and PDF-structure tests",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show individual integration test names",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=4,
        help="parallel Python test workers (default: 4; 1 for serial)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help=argparse.SUPPRESS,
    )
    return parser


def _find_repository_root(explicit: Path | None) -> Path:
    candidates = []
    if explicit is not None:
        candidates.append(explicit)
    candidates.extend([Path.cwd(), Path(__file__).resolve().parents[2]])
    for candidate in candidates:
        root = candidate.resolve()
        if (root / "build.lua").is_file() and (root / "tests" / "run_tests.py").is_file():
            return root
    raise RuntimeError(
        "Could not find the ULSBS source repository containing build.lua and tests/."
    )


def _runner_arguments(args: argparse.Namespace, executable: str = "python3") -> list[str]:
    result = [executable, "tests/run_tests.py", "--jobs", str(args.jobs)]
    if args.skip_l3build:
        result.append("--skip-l3build")
    if args.skip_integration:
        result.append("--skip-integration")
    if args.verbose:
        result.append("--verbose")
    return result


def _run_on_host(root: Path, args: argparse.Namespace) -> int:
    """Run the host suite and stop its workers as a group on interruption."""
    env = os.environ.copy()
    source_dir = str(root / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (source_dir, env.get("PYTHONPATH", "")) if value
    )
    command = _runner_arguments(args, sys.executable)
    if os.name != "posix":
        return subprocess.run(command, cwd=root, env=env, check=False).returncode

    # The parallel runner can otherwise keep waiting for workers, and some
    # tests launch their own TeX subprocesses. Stop the whole group together.
    with subprocess.Popen(command, cwd=root, env=env, start_new_session=True) as process:
        try:
            return process.wait()
        except KeyboardInterrupt:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=1)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            finally:
                # A worker may survive even after the group leader has exited.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            raise


def _run_in_container(root: Path, args: argparse.Namespace) -> int:
    """Run the suite in a named compiler container owned by this invocation."""
    ui = UI()
    cfg = SimpleNamespace(container_engine=args.container_engine)
    engine = _pick_container_engine(cfg)
    ensure_container_image(
        ui,
        EngineAssets(),
        engine,
        force_rebuild=args.container_rebuild,
    )

    source_mount = f"type=bind,src={root},dst=/ulsbs-src"
    if engine == "podman":
        source_mount += ",Z"

    name = f"ulsbs-test-{secrets.token_hex(4)}"
    command = [
        engine,
        "run",
        "--name",
        name,
        # Handle Ctrl-C on the host rather than interrupting Python workers
        # independently inside the container.
        "--sig-proxy=false",
        "--rm",
        "--read-only",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--workdir",
        "/ulsbs-src",
        "--env",
        "HOME=/home/ulsbs",
        "--env",
        "PYTHONPATH=/ulsbs-src/src",
        "--env",
        "NO_COLOR=1",
        "--mount",
        source_mount,
        "--mount",
        f"type=volume,src={_HOMECACHE_VOLUME_NAME},dst=/home/ulsbs",
        "--mount",
        f"type=tmpfs,tmpfs-size={128 * args.jobs}m,dst=/tmp",
        "--mount",
        "type=tmpfs,tmpfs-size=16m,dst=/run",
    ]
    if not args.container_memory_unlimited:
        if args.container_memory_gb < 1:
            raise ValueError("--container-memory-gb must be at least 1")
        memory = f"{args.container_memory_gb}g"
        command.extend(["--memory", memory, "--memory-swap", memory])
    command.append(_CONTAINER_IMAGE_NAME)
    command.extend(_runner_arguments(args))

    ui.container_line(f"Run tests using {engine}")
    return _run_named_container(command, name, cwd=root)


def main(argv: list[str] | None = None) -> int:
    """Run the selected suite and return a shell exit status."""
    args = _parser().parse_args(argv)
    if args.jobs < 1:
        print("ulsbs-test: --jobs must be at least 1", file=sys.stderr)
        return 2
    if args.skip_l3build and args.skip_integration:
        print("ulsbs-test: all test suites were skipped", file=sys.stderr)
        return 2
    try:
        root = _find_repository_root(args.root)
        if args.no_container or os.environ.get("ULSBS_INTERNAL_RUNNING_IN_CONTAINER"):
            status = _run_on_host(root, args)
        else:
            status = _run_in_container(root, args)
        if status != -signal.SIGINT:
            return status
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"ulsbs-test: {error}", file=sys.stderr)
        return 1

    print("ulsbs-test: interrupted", file=sys.stderr)
    return 130


if __name__ == "__main__":
    raise SystemExit(main())
