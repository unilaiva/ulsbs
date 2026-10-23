# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cache successful original-footprint LilyPond engravings and manage asset trust.

Fingerprint inputs and transposition candidates, validate and publish successful
artifacts, and restore reusable results without making engraving depend on cache
availability. Read-only asset audits check reviewed hashes; explicit manifest
rewrites approve reviewed sources and named variants without executing them.
Cache clearing removes completed entries while preserving unrelated contents and
in-progress publications.

Integration sequence: call ``toolchain_fingerprint`` once per generate, then
``source_fingerprint`` once per score. Derive ``candidate_key`` for each signed,
spelled interval and original geometry. Try ``restore`` before engraving; call
``publish(..., success=True)`` only after _engrave's semantic checks succeed.
Both operations validate the PDF, log, geometry and content hashes themselves.
None/False always means an ordinary cache miss, never an engraving failure.

Fingerprints are snapshots: do not reuse them after editing inputs. Custom
Scheme is deliberately ineligible. Only audited bundled assets, their exact
pipeline mutations, and the installed preamble are trusted executable Scheme;
quoted literals are data. Dependencies and full mutated contents remain hashed.
The caller must supply any additional rendering flags/semantics in ``extra``
and bump ``implementation_version`` when its transformation changes.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Mapping, Sequence

import pikepdf

# Storage format and key namespace are owned by this cache implementation, not
# shared build settings. Incompatible changes must invalidate existing entries.
SCHEMA_VERSION = 1
IMPLEMENTATION_VERSION = "ulsbs-score-cache-1"
_LOG = logging.getLogger(__name__)
_HASH = re.compile(r"[0-9a-f]{64}")
_BAD_LOG = re.compile(
    r"No (?:open )?string for pitch|cannot find[^\n]*string|programming error|fatal error", re.I
)
_TOKEN = re.compile(r'%\{|%[^\n]*|"(?:\\.|[^"\\])*"', re.S)
_INCLUDE = re.compile(r'\\include\s+"([^"\\\n]+)"')
_BUNDLED = Path(__file__).parent / "assets" / "ly"
_TRUST_MANIFEST = _BUNDLED.parent / "lilypond-score-cache-assets.json"


def _json(value: object) -> bytes:
    """Serialize cache semantics deterministically, including exact fractions."""
    def encode(item):
        """Encode a fraction as a JSON object; reject other unsupported values."""
        if isinstance(item, Fraction):
            return {"fraction": [item.numerator, item.denominator]}
        raise TypeError("not a cache semantic value")
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=encode).encode()


def _digest(data: bytes) -> str:
    """Return the SHA-256 hexadecimal digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def _asset_digest(data: bytes) -> str:
    """Hash asset bytes after normalizing the two audited pipeline mutations."""
    # Normalize only the two audited pipeline mutations for the trust check.
    # Fingerprints still hash the complete, modified file bytes independently.
    base = data.removesuffix(b'\n\\include "ulsbs-score-boundaries.ily"\n')
    marker = b"%%%ULSBS-PLACEHOLDER-FOR-EXTRA-INSTRUMENT-VARIANT-CODE%%%\n"
    base = base.replace(marker + b"ul-chosen-tuning = #ul-charango-tuning\n", marker, 1)
    return _digest(base)


def load_asset_manifest(path: Path | None = None) -> dict:
    """Validate the packaged review record; missing/corrupt data never grants trust."""
    manifest = json.loads((_TRUST_MANIFEST if path is None else path).read_bytes())
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1 or set(manifest) != {"schema_version", "assets", "variants"}):
        raise ValueError("invalid trusted-asset manifest schema")
    for section in ("assets", "variants"):
        if not isinstance(manifest[section], dict):
            raise ValueError(f"invalid trusted-asset manifest {section}")
        for name, digest in manifest[section].items():
            if (not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", name)
                    or not isinstance(digest, str) or not _HASH.fullmatch(digest)):
                raise ValueError(f"invalid trusted-asset manifest {section} entry")
    return manifest


def _trusted_assets(path: Path | None = None) -> frozenset[str]:
    """Collect approved source and variant hashes from a validated manifest."""
    manifest = load_asset_manifest(path)
    return frozenset((*manifest["assets"].values(), *manifest["variants"].values()))


def _asset_files(paths: Sequence[Path]) -> list[Path]:
    """Expand flat asset directories and deduplicate paths in encounter order."""
    files = []
    for path in paths:
        if path.is_dir():
            children = sorted(child for child in path.iterdir()
                              if child.is_file() and child.suffix in (".ly", ".ily"))
            if not children:
                raise ValueError(f"no LilyPond assets found in {path}")
            files.extend(children)
        else:
            files.append(path)
    return list(dict.fromkeys(files))


def audit_assets(paths: Sequence[Path], *, manifest: Path | None = None) -> list[tuple[Path, str, bool]]:
    """Read-only audit of files or flat .ly/.ily asset directories; execute nothing."""
    trusted_assets = _trusted_assets(manifest)
    records = []
    for path in _asset_files(paths):
        digest = _asset_digest(path.read_bytes())
        records.append((path, digest, digest in trusted_assets))
    return records


def rewrite_asset_manifest(*, path: Path | None = None,
                           variants: Sequence[tuple[str, Path]] = ()) -> dict:
    """Explicit maintainer approval: replace source hashes, preserve named variants.

    Never called by compilation or read-only audit. No LilyPond/Scheme execution.
    All inputs are read and validated before atomic replacement of the manifest.
    """
    path = _TRUST_MANIFEST if path is None else path
    if path.is_symlink():
        raise ValueError("refusing to rewrite a symlinked trusted-asset manifest")
    manifest = (load_asset_manifest(path) if path.exists()
                else {"schema_version": 1, "assets": {}, "variants": {}})
    manifest["assets"] = {source.name: _asset_digest(source.read_bytes())
                          for source in _asset_files([_BUNDLED])}
    for name, source in variants:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", name):
            raise ValueError(f"invalid variant name: {name}")
        manifest["variants"][name] = _asset_digest(source.read_bytes())
    data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="." + path.name + "-",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return manifest


def _file(path: Path) -> str:
    """Stream a file's contents into a SHA-256 hexadecimal digest."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _tree(path: Path) -> str:
    """Hash a directory tree, including symlink targets, and reject cycles."""
    # Distribution font trees use directory symlinks. Hash their targets too,
    # tracking ancestors rather than rejecting ordinary aliases as cycles.
    def visit(directory, ancestors):
        """Hash sorted children while tracking resolved ancestor directories."""
        resolved = directory.resolve(strict=True)
        if resolved in ancestors:
            raise ValueError("asset directory cycle")
        items = []
        for child in sorted(directory.iterdir()):
            target = str(child.readlink()) if child.is_symlink() else None
            if child.is_dir():
                digest = visit(child, ancestors | {resolved})
            elif child.is_file():
                digest = _file(child)
            else:
                raise ValueError("unreadable asset")
            items.append((child.name, target, digest))
        return _digest(_json(items))
    return visit(path, set())


def cache_root(env: Mapping[str, str] | None = None) -> Path | None:
    """Override, else $XDG_CACHE_HOME/ulsbs/lilypond-scores, else ~/.cache."""
    try:
        env = os.environ if env is None else env
        if env.get("ULSBS_SCORE_CACHE_DIR"):
            root = Path(env["ULSBS_SCORE_CACHE_DIR"])
        else:
            home = Path(env["HOME"]) if env.get("HOME") else Path.home()
            root = Path(env.get("XDG_CACHE_HOME") or home / ".cache")
            root = root / "ulsbs" / "lilypond-scores"
        return root if root.is_absolute() else None
    except (OSError, ValueError, RuntimeError):
        return None


def clear_cache(*, env: Mapping[str, str] | None = None) -> tuple[Path, int]:
    """Remove completed cache entries only, never the root or unrelated contents.

    Unlike ordinary cache misses, a requested clear must report failure. Preserve
    in-progress .publish-* directories; concurrent builds may repopulate entries.
    """
    root = cache_root(env)
    if root is None:
        raise ValueError("score cache path must be absolute")
    if root.is_symlink():
        raise ValueError(f"refusing to clear a symlinked score cache root: {root}")
    if not root.exists():
        return root, 0
    if not root.is_dir():
        raise ValueError(f"score cache root is not a directory: {root}")
    entries = sorted(entry for entry in root.iterdir() if _HASH.fullmatch(entry.name))
    # Preflight before deleting anything, including corrupt entries whose normal
    # flat cache filenames remain recognizable. Never recursively erase user data
    # just because an override points at an overly broad directory.
    for entry in entries:
        if entry.is_symlink():
            continue
        if not entry.is_dir():
            raise ValueError(f"refusing to remove a non-directory cache entry: {entry}")
        for child in entry.iterdir():
            if (not re.fullmatch(r"manifest\.json|artifact(?:\.log|\.ulsbs-boundaries|-\d+\.pdf)", child.name)
                    or not (child.is_file() or child.is_symlink())):
                raise ValueError(f"refusing to remove unrecognized cache contents: {child}")
    for entry in entries:
        if entry.is_symlink():
            entry.unlink()
        else:
            shutil.rmtree(entry)
    return root, len(entries)


@dataclass(frozen=True)
class ToolchainFingerprint:
    """Hold a toolchain digest and its installed LilyPond data directory."""

    digest: str
    datadir: Path


def toolchain_fingerprint(*, env: Mapping[str, str] | None = None,
                          cwd: Path | None = None,
                          asset_paths: Sequence[Path] = ()) -> ToolchainFingerprint | None:
    """Probe once per generate, not per candidate; never executes source text.

    Hash installed LilyPond data, executable, fontconfig/fonts and explicit
    extra asset paths. The fixed -e expression is needed because LilyPond has
    no portable --print-datadir option. No shell or user Scheme is evaluated.
    """
    try:
        env = dict(os.environ if env is None else env)
        executable = shutil.which("lilypond", path=env.get("PATH", os.defpath))
        if not executable:
            return None
        def probe(*args):
            """Run a bounded LilyPond probe and return its stripped stdout."""
            result = subprocess.run([executable, *args], cwd=cwd, env=env,
                                    capture_output=True, text=True, timeout=15, check=True)
            return result.stdout.strip()
        version = probe("--version")
        datadir = Path(probe("-e", '(display (ly:get-option (quote datadir))) (exit 0)'))
        if not version or not datadir.is_absolute() or not datadir.is_dir():
            return None
        home = Path(env.get("HOME") or Path.home())
        paths = [datadir, Path("/etc/fonts"), Path("/usr/share/fonts"),
                 Path("/usr/local/share/fonts"), home / ".fonts",
                 home / ".local/share/fonts", home / ".config/fontconfig", *asset_paths]
        for name in ("FONTCONFIG_FILE", "FONTCONFIG_PATH", "GS_LIB", "GUILE_LOAD_PATH",
                     "GUILE_LOAD_COMPILED_PATH"):
            for value in env.get(name, "").split(os.pathsep):
                if value:
                    paths.append(Path(value))
        assets = []
        for path in dict.fromkeys(paths):
            if not path.is_absolute():
                path = (cwd or Path.cwd()) / path
            assets.append((str(path), _tree(path) if path.is_dir() else
                           _file(path) if path.is_file() else None))
        digest = _digest(_json([version, str(executable), _file(Path(executable)), assets]))
        return ToolchainFingerprint(digest, datadir)
    except (OSError, ValueError, RuntimeError, RecursionError, subprocess.SubprocessError) as error:
        _LOG.debug("LilyPond score cache toolchain unavailable: %s", error)
        return None


def _clean(text: str) -> str:
    """Remove LilyPond comments without interpreting strings or executing code."""
    result, position = [], 0
    while match := _TOKEN.search(text, position):
        result.append(text[position:match.start()])
        token = match[0]
        if token == "%{":
            depth, end = 1, match.end()
            while depth:
                nested = re.search(r"%\{|%\}", text[end:])
                if nested is None:
                    raise ValueError("unterminated comment")
                end += nested.end()
                depth += 1 if nested[0] == "%{" else -1
            result.append(" ")
            position = end
        else:
            result.append(token if token.startswith('"') else "\n")
            position = match.end()
    result.append(text[position:])
    return "".join(result)


def source_fingerprint(source: Path, include_args: Sequence[str], *, cwd: Path,
                       env: Mapping[str, str] | None = None,
                       toolchain: ToolchainFingerprint | None) -> str | None:
    """Hash exact source/layout and resolved recursive literal includes once.

    Only -I DIR, -IDIR and --include=DIR are accepted. Ambiguous resolutions
    (different files in search locations) disable caching rather than guessing
    LilyPond's version-dependent precedence. Job-local paths are normalized to
    $JOB so equivalent relocated jobs can share entries. External paths remain
    significant. Rendering-related environment is keyed, not container IDs,
    build IDs or TeX search paths (the engraved source already embeds geometry).
    """
    try:
        if toolchain is None:
            return None
        trusted_assets = _trusted_assets()
        env = dict(os.environ if env is None else env)
        cwd = cwd.resolve(strict=True)
        source = source if source.is_absolute() else cwd / source
        directories = []
        args = iter(include_args)
        for arg in args:
            if arg in ("-I", "--include"):
                value = next(args)
            elif arg.startswith("-I") and len(arg) > 2:
                value = arg[2:]
            elif arg.startswith("--include="):
                value = arg[len("--include="):]
            else:
                return None
            path = Path(value)
            directories.append((path if path.is_absolute() else cwd / path).resolve())

        def location(path):
            """Normalize job-local paths while retaining external absolute paths."""
            path = path.absolute()
            return "$JOB/" + path.relative_to(cwd).as_posix() if path.is_relative_to(cwd) else str(path)

        visited, active, dependencies = set(), set(), []
        def visit(path, trusted=False):
            """Validate and record recursive includes, rejecting unsafe sources."""
            resolved = path.resolve(strict=True)
            if resolved in active:
                raise ValueError("include cycle")
            if resolved in visited:
                return
            active.add(resolved)
            data = path.read_bytes()
            clean = _clean(data.decode("utf-8"))
            trusted = trusted or _asset_digest(data) in trusted_assets
            includes = list(_INCLUDE.finditer(clean))
            remaining = _INCLUDE.sub("", clean)
            if re.search(r"\\include\b|\\(?:epsfile|load|image|open)\b", remaining):
                raise ValueError("dynamic dependency")
            if not trusted:
                # A deliberately small safe subset, not a Scheme denylist.
                number = r'-?\d+(?:\.\d+)?'
                patterns = (
                    rf'#\(set-global-staff-size\s+{number}\s*\)',
                    rf"#\(ly:set-option\s+'eps-box-padding\s+{number}\s*\)",
                    rf'#\(-\s+line-width\s+\(\*\s+mm\s+{number}\)\s+\(\*\s+mm\s+1\)\s*\)',
                    r'#\(set-paper-size\s+"[a-zA-Z0-9-]+"\s*\)',
                    rf"#\(set-paper-size\s+'\(cons\s+\(\*\s+{number}\s+pt\)"
                    rf"\s+\(\*\s+{number}\s+pt\)\)\s*\)",
                )
                for pattern in patterns:
                    remaining = re.sub(pattern, '', remaining)
                # Quote suppresses evaluation. Accept only flat proper lists
                # of simple atoms, or a symbol: no reader extensions, dotted
                # pairs, quasiquote/unquote, nested forms or evaluated inputs.
                symbol = r'[A-Za-z][A-Za-z0-9_:-]*'
                atom = rf'(?:{symbol}|{number}|#[tf]|"(?:\\.|[^"\\])*")'
                quoted = rf"#'\(\s*(?:{atom}(?:\s+{atom})*)?\s*\)|#'{symbol}\b"
                remaining = re.sub(quoted, '', remaining)
                remaining = re.sub(r'"(?:\\.|[^"\\])*"', '', remaining)
                remaining = re.sub(r'##[tf]|#-?\d+(?:\.\d+)?\b', '', remaining)
                if "#" in remaining or "$" in remaining:
                    raise ValueError(f"custom Scheme in {path}")
            edges = []
            for match in includes:
                name = Path(match[1])
                search = [*directories, path.parent, source.parent, cwd,
                          toolchain.datadir / "ly", toolchain.datadir]
                candidates = [name] if name.is_absolute() else [directory / name for directory in search]
                found = {candidate.resolve(strict=True) for candidate in candidates if candidate.is_file()}
                if len(found) != 1:
                    raise ValueError("unresolved or ambiguous include")
                child = found.pop()
                edges.append((match[1], location(child)))
                preamble = toolchain.datadir / "ly" / "lilypond-book-preamble.ly"
                visit(child, trusted=child == preamble.resolve())
            dependencies.append([location(path), _digest(data), edges])
            active.remove(resolved)
            visited.add(resolved)
        visit(source)
        environment = {name: value.replace(str(cwd), "$JOB") for name, value in env.items()
                       if name in ("PATH", "HOME", "LANG", "LANGUAGE", "TZ", "SOURCE_DATE_EPOCH",
                                   "XDG_DATA_HOME", "XDG_CONFIG_HOME", "LD_LIBRARY_PATH", "LD_PRELOAD")
                       or name.startswith(("LC_", "LILYPOND_", "GUILE_", "GS_", "FONTCONFIG_"))}
        return _digest(_json([SCHEMA_VERSION, toolchain.digest, location(source),
                              [location(p) for p in directories],
                              sorted(dependencies), environment]))
    except (OSError, ValueError, TypeError, RuntimeError, StopIteration, RecursionError) as error:
        _LOG.debug("LilyPond score cache source ineligible (%s): %s", source, error)
        return None


def _sizes(original: Sequence) -> list[list[float]]:
    """Normalize one or more dimension pairs and require positive finite values."""
    sizes = [list(original)] if original and isinstance(original[0], (int, float)) else [
        list(size) for size in original]
    if not sizes or any(len(size) != 2 or not all(math.isfinite(n) and n > 0 for n in size)
                        for size in sizes):
        raise ValueError("invalid original dimensions")
    return sizes


def candidate_key(fingerprint: str | None, *, signed: int, spelled: Sequence[str],
                  original_dimensions: Sequence, original_boundaries: object,
                  extra: object = None, implementation_version: str = IMPLEMENTATION_VERSION
                  ) -> str | None:
    """Cheap candidate hash; include mode, keys, insertion point, flags in extra."""
    try:
        if (fingerprint is None or not _HASH.fullmatch(fingerprint) or type(signed) is not int
                or len(spelled) != 2 or not all(isinstance(s, str) and s for s in spelled)
                or not _sizes(original_dimensions)):
            return None
        return _digest(_json([SCHEMA_VERSION, implementation_version, fingerprint, signed,
                              spelled, original_dimensions, original_boundaries, extra]))
    except (ValueError, TypeError, OverflowError):
        return None


def _artifacts(files: dict[str, bytes], original: Sequence, minimum_scale: float) -> dict:
    """Validate logs, PDF footprints and musical boundaries; return their metadata."""
    sizes = _sizes(original)
    if not math.isfinite(minimum_scale) or not 0 < minimum_scale <= 1:
        raise ValueError("invalid validation bounds")
    pdfs = [suffix for suffix in files if re.fullmatch(r"-\d+\.pdf", suffix)]
    expected = [f"-{index}.pdf" for index in range(1, len(sizes) + 1)]
    if set(pdfs) != set(expected) or ".log" not in files or _BAD_LOG.search(files[".log"].decode("utf-8")):
        raise ValueError("unsuccessful engraving artifacts")
    boxes = []
    for suffix, size in zip(expected, sizes, strict=True):
        with pikepdf.Pdf.open(io.BytesIO(files[suffix])) as pdf:
            if len(pdf.pages) != 1:
                raise ValueError("not a single system")
            page = pdf.pages[0]
            box = [float(n) for n in page.get("/CropBox", page.MediaBox)]
            if len(box) != 4 or not all(math.isfinite(n) for n in box):
                raise ValueError("invalid PDF boundary")
            width, height = box[2] - box[0], box[3] - box[1]
            if width <= 0 or height <= 0 or min(1, size[0] / width, size[1] / height) < minimum_scale:
                raise ValueError("invalid PDF footprint")
            boxes.append(box)
    boundaries = []
    if ".ulsbs-boundaries" in files:
        rows = sorted(tuple(Fraction(value) for value in line.split())
                      for line in files[".ulsbs-boundaries"].decode("utf-8").splitlines() if line.strip())
        if (len(rows) != len(sizes) or any(len(row) != 4 or row[:2] >= row[2:] for row in rows)
                or any(a[2:] != b[:2] for a, b in zip(rows, rows[1:], strict=False))):
            raise ValueError("invalid musical boundaries")
        boundaries = [[str(value) for value in row] for row in rows]
    elif len(sizes) > 1:
        raise ValueError("missing musical boundaries")
    return {"pdfs": expected, "boundaries": boxes, "original_dimensions": sizes,
            "musical_boundaries": boundaries, "minimum_scale": minimum_scale}


def _load(root: Path, key: str) -> tuple[dict, dict[str, bytes]]:
    """Load an entry after checking its manifest, artifact hashes and geometry."""
    entry = root / key
    if entry.is_symlink() or (entry / "manifest.json").is_symlink():
        raise ValueError("symlink cache entry")
    envelope = json.loads((entry / "manifest.json").read_bytes())
    manifest = envelope["manifest"]
    if envelope["sha256"] != _digest(_json(manifest)):
        raise ValueError("manifest hash mismatch")
    if manifest["schema"] != SCHEMA_VERSION or manifest["key"] != key or manifest["success"] is not True:
        raise ValueError("invalid manifest")
    files = {}
    for suffix, expected in manifest["files"].items():
        if not re.fullmatch(r"\.log|\.ulsbs-boundaries|-\d+\.pdf", suffix):
            raise ValueError("unsafe artifact suffix")
        path = entry / ("artifact" + suffix)
        if path.is_symlink():
            raise ValueError("symlink artifact")
        data = path.read_bytes()
        if expected != {"sha256": _digest(data), "size": len(data)}:
            raise ValueError("artifact hash mismatch")
        files[suffix] = data
    validation = _artifacts(files, manifest["validation"]["original_dimensions"],
                            manifest["validation"]["minimum_scale"])
    if validation != manifest["validation"]:
        raise ValueError("artifact geometry mismatch")
    return manifest, files


def publish(key: str | None, stem: Path, *, success: bool,
            original_dimensions: Sequence, minimum_scale: float,
            metadata: object = None, env: Mapping[str, str] | None = None) -> bool:
    """Atomically publish validated system PDFs, log, boundaries and metadata.

    Explicit success is mandatory: a zero subprocess exit alone is insufficient.
    Dimensions may be a single (width, height) pair or one pair per system.
    The caller must supply its minimum fitting scale explicitly; the cache has
    no independent default policy. Include that scale in candidate-key semantics
    so changing it cannot reuse an entry accepted under another threshold.
    Multiple systems require a contiguous .ulsbs-boundaries sidecar. The caller
    confirms its equality to the original musical boundaries before publishing.
    Concurrent publishers use private staging directories; the first wins.
    Corrupt existing entries are misses and are never overwritten in place.
    """
    temporary = None
    try:
        root = cache_root(env)
        if key is None or not _HASH.fullmatch(key) or root is None or success is not True:
            return False
        if stem.with_suffix(".log").is_symlink():
            return False
        files = {".log": stem.with_suffix(".log").read_bytes()}
        boundary_file = stem.with_suffix(".ulsbs-boundaries")
        if boundary_file.is_symlink():
            return False
        if boundary_file.exists():
            files[".ulsbs-boundaries"] = boundary_file.read_bytes()
        for path in stem.parent.glob(stem.name + "-*.pdf"):
            if path.is_symlink():
                return False
            files[path.name[len(stem.name):]] = path.read_bytes()
        if any(not re.fullmatch(r"\.log|\.ulsbs-boundaries|-\d+\.pdf", s) for s in files):
            return False
        validation = _artifacts(files, original_dimensions, minimum_scale)
        manifest = {"schema": SCHEMA_VERSION, "key": key, "success": True,
                    "validation": validation, "metadata": metadata,
                    "files": {s: {"sha256": _digest(b), "size": len(b)} for s, b in files.items()}}
        envelope = _json({"manifest": manifest, "sha256": _digest(_json(manifest))})
        root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".publish-", dir=root))
        for suffix, data in files.items():
            (temporary / ("artifact" + suffix)).write_bytes(data)
        (temporary / "manifest.json").write_bytes(envelope)
        try:
            temporary.rename(root / key)
        except FileExistsError:
            _load(root, key)
        except OSError:
            # POSIX may report ENOTEMPTY instead of EEXIST for a directory.
            if not (root / key).exists():
                raise
            _load(root, key)
        return True
    except Exception as error:
        # The cache is optional, including on malformed data or PDF library errors.
        _LOG.debug("LilyPond score cache publication failed (%s): %s", key, error)
        return False
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


def restore(key: str | None, stem: Path, *, env: Mapping[str, str] | None = None) -> dict | None:
    """Copy validated artifacts to a job-local stem; return validation/metadata.

    Validation completes before any destination changes. Files are copied, not
    linked, so editing a job artifact cannot poison the shared cache. The caller
    should use a dedicated variant directory, just as _engrave does.
    """
    temporary = None
    try:
        root = cache_root(env)
        if key is None or not _HASH.fullmatch(key) or root is None:
            return None
        manifest, files = _load(root, key)
        stem.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".restore-", dir=stem.parent))
        for suffix, data in files.items():
            (temporary / (stem.name + suffix)).write_bytes(data)
        for stale in stem.parent.glob(stem.name + "-*.pdf"):
            stale.unlink()
        stem.with_suffix(".ulsbs-boundaries").unlink(missing_ok=True)
        for path in temporary.iterdir():
            os.replace(path, stem.parent / path.name)
        return {"validation": manifest["validation"], "metadata": manifest["metadata"]}
    except Exception as error:
        _LOG.debug("LilyPond score cache restore miss (%s): %s", key, error)
        return None
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Read-only audit by default; --rewrite explicitly approves reviewed sources."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Audit LilyPond score-cache asset hashes without executing LilyPond or Scheme.",
        epilog="Review changed files and their dependencies before --rewrite. "
               "Known pipeline mutations are normalized. Rewriting is explicit approval, "
               "not a code-safety check; ordinary audit never changes files.")
    parser.add_argument("paths", nargs="*", type=Path,
                        help="Files or asset directories (default: installed bundled assets)")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="Trusted-asset manifest (default: packaged assets/lilypond-score-cache-assets.json)")
    parser.add_argument("--rewrite", action="store_true",
                        help="Approve reviewed bundled sources by atomically rewriting their manifest hashes")
    parser.add_argument("--variant", action="append", default=[], metavar="NAME=FILE",
                        help="With --rewrite, approve a reviewed generated variant; other variants are preserved")
    args = parser.parse_args(argv)
    if args.rewrite and args.paths:
        parser.error("--rewrite hashes bundled sources only; use --variant NAME=FILE for generated variants")
    if args.variant and not args.rewrite:
        parser.error("--variant requires --rewrite")
    try:
        if args.rewrite:
            variants = []
            for value in args.variant:
                name, separator, filename = value.partition("=")
                if not separator or not filename:
                    raise ValueError("variant must be NAME=FILE")
                variants.append((name, Path(filename)))
            manifest = rewrite_asset_manifest(path=args.manifest, variants=variants)
            target = _TRUST_MANIFEST if args.manifest is None else args.manifest
            print(f"Rewrote {target}: {len(manifest['assets'])} source hashes, "
                  f"{len(manifest['variants'])} named variants. Review the manifest diff.")
            return 0
        records = audit_assets(args.paths or [_BUNDLED], manifest=args.manifest)
    except (OSError, ValueError) as error:
        print(f"Asset audit failed: {error}", file=sys.stderr)
        return 2
    for path, digest, trusted in records:
        print(f"{'TRUSTED' if trusted else 'UNTRUSTED'} {digest} {path}")
    if any(not trusted for _, _, trusted in records):
        print("Review changed files and their dependencies before rewriting the trusted-asset manifest "
              "with --rewrite; unknown hashes may disable score caching, not engraving.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
