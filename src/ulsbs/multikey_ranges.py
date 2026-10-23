# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stage protocol-v1 layered ranges from finalized PDFs and a schema-v2 manifest.

The pipeline checks ordinary/master geometry, metadata, named links and actual
layer dependencies; extracts bounded page ranges with primary-input qpdf; checks
each resulting object graph; then hashes final files and writes the index last.
The ordinary PDF supplies canonical navigation names, the unchanged layered
master supplies content, and the caller supplies compiler-derived JSON metadata.
No manifest is recovered from a PDF. Publication, inventory cleanup, temporary
master disposal and consumer/viewer behavior belong to callers or other modules.

Range endpoints are 1-based inclusive physical pages; manifest, geometry-list and
dependency indices are 0-based. Output filenames append ``_MULTIKEY`` to the
entire ordinary stem, retaining edition suffixes: ``Book_A5_MULTIKEY_*``.

The minimum qpdf version follows the shared toolchain policy. Every output is
independently checked even on newer versions. Direct
Link destinations and retained unselected pages fail rather than losing useful
navigation. Checks enforce this supported structural contract, not authenticity,
a general PDF security audit, or proof of equivalent rendering in every viewer.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import warnings
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import pikepdf

from .constants import MULTIKEY_INDEX_MAX_BYTES, MULTIKEY_MIN_QPDF_VERSION

# Stable layer identity, not a tunable policy: changes must be coordinated with
# the TeX/Lua producer and viewers that interpret these names.
PROTOCOL = "ulsbs:transpose:v1"


def _require(condition, message):
    """Raise ValueError with the contract failure message unless condition holds."""
    if not condition:
        raise ValueError(message)


def _integer(value, minimum=1):
    """Accept only built-in integers at or above minimum, excluding booleans."""
    return type(value) is int and value >= minimum


def _number(value):
    """Recognize finite int/float coordinates, excluding booleans and overflow."""
    try:
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value))
    except OverflowError:
        return False


def _keys(value, keys, label):
    """Require a dictionary with exactly the space-separated field names."""
    _require(isinstance(value, dict) and set(value) == set(keys.split()), f"Invalid {label} fields")


def _basename(name):
    """Reject empty, traversal, path, URL-delimiter and control-character names."""
    _require(isinstance(name, str) and name not in ("", ".", "..")
             and not re.search(r"[\\/:?#%\x00-\x1f\x7f]", name), "Unsafe sibling filename")


def _encoded(value):
    """Return deterministic compact UTF-8 JSON within the protocol byte bound.

    Unsupported values, nonfinite numbers, excessive nesting and oversized
    encodings raise ValueError. The same bound also applies to standalone
    manifest checks, but the complete index must still fit it independently.
    """
    try:
        data = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("Invalid JSON value") from error
    _require(len(data) <= MULTIKEY_INDEX_MAX_BYTES,
             f"Index/manifest exceeds {MULTIKEY_INDEX_MAX_BYTES:,} bytes")
    return data


def _manifest(manifest, count, geometry):
    """Check the exact schema-v2 envelope against global page count and views.

    Occurrences must increase per song ID, not necessarily start at one or be
    contiguous. Header page/anchor may both be null; otherwise their finite
    PDF-user-space coordinates must lie in that 0-based page's effective view.
    Affected indices are sorted/unique and nonempty iff content is transposable.
    This checks shape and bounds, not anchor accuracy against typeset controls;
    actual layer/page agreement is checked separately against the master.
    """
    _encoded(manifest)
    _keys(manifest, "has_multikey_info multikey_info", "manifest envelope")
    _require(manifest["has_multikey_info"] is True, "Manifest must enable multikey")
    info = manifest["multikey_info"]
    _keys(info, "schema_version layer_protocol coordinate_space songs", "multikey manifest")
    _require(type(info["schema_version"]) is int and info["schema_version"] == 2
             and info["layer_protocol"] == PROTOCOL
             and info["coordinate_space"] == "pdf-user-space", "Unsupported manifest schema")
    _require(isinstance(info["songs"], list), "Invalid songs")
    occurrences, prefixes = Counter(), set()
    for song in info["songs"]:
        _keys(song, "song_id occurrence has_transposable_content original_key key_labels "
              "layer_prefix layer_page_indices page_index anchor", "song")
        _require(isinstance(song["song_id"], str) and bool(song["song_id"]), "Invalid song ID")
        _require(_integer(song["occurrence"])
                 and song["occurrence"] > occurrences[song["song_id"]], "Invalid occurrence")
        occurrences[song["song_id"]] = song["occurrence"]
        prefix = song["layer_prefix"]
        _require(isinstance(prefix, str) and prefix.startswith(PROTOCOL + ":id:")
                 and prefix not in prefixes, "Invalid/duplicate layer prefix")
        prefixes.add(prefix)
        _require(type(song["has_transposable_content"]) is bool, "Invalid content flag")
        _require(song["original_key"] is None or isinstance(song["original_key"], str),
                 "Invalid original key")
        labels = song["key_labels"]
        _require(labels is None or (isinstance(labels, list) and len(labels) == 12
                                   and all(isinstance(x, str) and x for x in labels)),
                 "Key labels must be null or twelve strings")
        page = song["page_index"]
        if page is None or song["anchor"] is None:
            _require(page is None and song["anchor"] is None, "Unpaired missing anchor/page")
        else:
            _require(_integer(page, 0) and page < count, "Anchor page out of bounds")
            _keys(song["anchor"], "x y", "anchor")
            x, y = song["anchor"]["x"], song["anchor"]["y"]
            _require(_number(x) and _number(y), "Invalid anchor coordinates")
            view = geometry[page]["view"]
            _require(view[0] <= x <= view[2] and view[1] <= y <= view[3],
                     "Anchor outside effective page view")
        pages = song["layer_page_indices"]
        _require(isinstance(pages, list) and all(_integer(p, 0) and p < count for p in pages)
                 and pages == sorted(set(pages)), "Invalid affected page indices")
        _require(bool(pages) == song["has_transposable_content"], "Content/page-set disagreement")


def _identity(path):
    """Stream-hash exact file bytes and return sibling name, size and SHA-256.

    Files must remain stable during inspection; filesystem errors propagate.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"file": path.name, "byte_length": path.stat().st_size, "sha256": digest.hexdigest()}


def validate_index(index: dict, index_path: Path | None = None,
                   canonical_path: Path | None = None) -> None:
    """Validate an in-memory protocol-v1 index, returning None on success.

    Always check compact UTF-8 size, exact fields, manifest/geometry bounds,
    tool declaration, safe filenames, identities and ordered coverage of 1..N.
    Range endpoints are 1-based inclusive; manifest page indices remain 0-based.
    Multi-page ranges must meet both declared sizing limits; an oversized single
    page is permitted. This mode trusts declared file sizes and hashes.

    With ``index_path``, also check its expected basename and hash/measure every
    range beside it. The JSON location need not exist: its bytes are not read.
    With ``canonical_path``, independently verify that file's full identity,
    including basename. Either optional check can be used without the other;
    the canonical file need not be in the staging directory. No files are written.

    Contract failures raise ValueError; file access failures raise OSError.
    No PDFs are opened or qpdf invoked here. Matching hashes establish integrity
    relative to this index, not authenticity or semantic/render equivalence.
    ``package_ranges`` additionally checks extracted PDF structure against its
    source, but neither API verifies compiler-derived anchor accuracy visually.
    """
    _encoded(index)
    _keys(index, "format schema_version page_count max_pages_per_range target_max_range_bytes "
          "link_policy canonical geometry manifest ranges packaging", "index")
    _require(index["format"] == "ulsbs:multikey-ranges"
             and type(index["schema_version"]) is int and index["schema_version"] == 1
             and index["link_policy"] == "canonical-names-v1", "Unsupported index protocol")
    for key in ("page_count", "max_pages_per_range", "target_max_range_bytes"):
        _require(_integer(index[key]), f"Invalid {key}")
    count = index["page_count"]
    _keys(index["canonical"], "file byte_length sha256", "canonical")
    canonical = index["canonical"]
    _basename(canonical["file"])
    _require(canonical["file"].endswith(".pdf"), "Canonical must be a PDF filename")
    stem = canonical["file"][:-4] + "_MULTIKEY"
    if index_path is not None:
        index_path = Path(index_path)
        _require(index_path.name == stem + "_RANGES.json", "Index filename does not match canonical")
    geometry = index["geometry"]
    _require(isinstance(geometry, list) and len(geometry) == count, "Invalid geometry count")
    for entry in geometry:
        _keys(entry, "view rotation user_unit", "geometry")
        view = entry["view"]
        _require(isinstance(view, list) and len(view) == 4 and all(_number(x) for x in view)
                 and view[0] < view[2] and view[1] < view[3], "Invalid effective view")
        _require(type(entry["rotation"]) is int and entry["rotation"] in (0, 90, 180, 270)
                 and _number(entry["user_unit"]) and entry["user_unit"] > 0,
                 "Invalid rotation/UserUnit")
    _manifest(index["manifest"], count, geometry)
    _keys(index["packaging"], "tool tool_version", "packaging")
    version = index["packaging"]["tool_version"]
    _require(index["packaging"]["tool"] == "qpdf" and isinstance(version, str)
             and re.fullmatch(r"\d+\.\d+\.\d+", version) is not None
             and tuple(map(int, version.split("."))) >= MULTIKEY_MIN_QPDF_VERSION,
             "Unqualified packaging tool version")
    ranges = index["ranges"]
    _require(isinstance(ranges, list) and bool(ranges), "Empty range list")
    next_page = 1
    for part in ranges:
        _keys(part, "file first_page last_page page_count byte_length sha256", "range")
        first, last = part["first_page"], part["last_page"]
        _require(_integer(first) and _integer(last) and first == next_page and first <= last <= count
                 and _integer(part["page_count"]) and part["page_count"] == last - first + 1
                 and part["page_count"] <= index["max_pages_per_range"], "Invalid range coverage")
        _basename(part["file"])
        _require(part["file"] == f"{stem}_RANGE_{first}-{last}.pdf", "Range filename mismatch")
        _require(_integer(part["byte_length"]), "Invalid range byte length")
        _require(part["byte_length"] <= index["target_max_range_bytes"] or first == last,
                 "Oversized multi-page range")
        next_page = last + 1
    _require(next_page == count + 1, "Incomplete range coverage")
    for descriptor in [canonical, *ranges]:
        _require(_integer(descriptor["byte_length"]) and isinstance(descriptor["sha256"], str)
                 and re.fullmatch(r"[0-9a-f]{64}", descriptor["sha256"]) is not None,
                 "Invalid file identity")
    if index_path is not None:
        for part in ranges:
            actual = _identity(index_path.parent / part["file"])
            _require(all(actual[k] == part[k] for k in actual), "Range size/hash mismatch")
    if canonical_path is not None:
        _require(_identity(Path(canonical_path)) == canonical, "Canonical size/hash mismatch")


def _inherited(page, key, default=None):
    """Resolve the nearest page-tree value, rejecting cyclic parent chains."""
    obj, seen = page.obj, set()
    while obj is not None:
        _require(obj.objgen not in seen, "Cyclic page inheritance")
        seen.add(obj.objgen)
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
    return default


def _geometry(page):
    """Return (public geometry, all effective boxes) for pairwise comparisons.

    MediaBox/CropBox and rotation follow page inheritance; CropBox defaults to
    MediaBox. Page-local BleedBox/TrimBox/ArtBox default to CropBox. All five
    boxes must be finite and ordered. The public view is the nonempty media/crop
    intersection in unscaled PDF user space, with normalized rotation and positive
    page-local UserUnit (default one). Returning boxes too prevents equal views
    from hiding differences in ordinary/master or source/range page boxes.
    """
    media = _inherited(page, "/MediaBox")
    crop = _inherited(page, "/CropBox", media)
    boxes = {}
    for key, value in [("/MediaBox", media), ("/CropBox", crop)] + [
            (key, page.obj.get(key, crop)) for key in ("/BleedBox", "/TrimBox", "/ArtBox")]:
        _require(isinstance(value, pikepdf.Array) and len(value) == 4, "Invalid page box")
        box = [float(x) for x in value]
        _require(all(math.isfinite(x) for x in box) and box[0] < box[2] and box[1] < box[3],
                 "Invalid page box coordinates")
        boxes[key] = box
    media, crop = boxes["/MediaBox"], boxes["/CropBox"]
    view = [max(media[0], crop[0]), max(media[1], crop[1]),
            min(media[2], crop[2]), min(media[3], crop[3])]
    rotation, unit = _inherited(page, "/Rotate", 0), float(page.obj.get("/UserUnit", 1))
    _require(not isinstance(rotation, bool) and int(rotation) == rotation and int(rotation) % 90 == 0
             and math.isfinite(unit) and unit > 0 and view[0] < view[2] and view[1] < view[3],
             "Invalid effective geometry")
    return {"view": view, "rotation": int(rotation) % 360, "user_unit": unit}, boxes


def _walk(root):
    """Yield the reachable dictionary/stream/array graph without decoding streams.

    Indirect object IDs are visited once to close cycles such as page parents;
    direct values may repeat. This follows references, not just the page tree,
    so metadata checks also reach attached objects and resource dictionaries.
    """
    pending, seen = [root], set()
    while pending:
        obj = pending.pop()
        if isinstance(obj, pikepdf.Object) and obj.is_indirect:
            if obj.objgen in seen:
                continue
            seen.add(obj.objgen)
        yield obj
        if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
            pending.extend(value for _, value in obj.items())
        elif isinstance(obj, pikepdf.Array):
            pending.extend(obj)


def _readonly_pgf_button(obj):
    """Recognize only PGF's read-only ARFix button with a bare ResetForm action.

    The exact widget type, flags, name prefix and action shape are the narrow
    exception to rejecting editable forms, not permission for general buttons.
    """
    action = obj.get("/A", {})
    return (obj.get("/Subtype") == pikepdf.Name.Widget and obj.get("/FT") == pikepdf.Name.Btn
            and obj.get("/Ff") == 65537 and str(obj.get("/T", "")).startswith("pbs@ARFix@")
            and isinstance(action, pikepdf.Dictionary) and set(action.keys()) == {"/S"}
            and action.S == pikepdf.Name.ResetForm)


def _layer_action(action, pdf):
    """Require supported SetOCGState fields and operations on declared OCGs."""
    _require(set(action.keys()) <= {"/Type", "/S", "/State", "/PreserveRB"},
             "Unsupported layer action fields")
    state = action.get("/State")
    _require(isinstance(state, pikepdf.Array) and len(state) > 0
             and type(action.get("/PreserveRB", True)) is bool, "Invalid layer action")
    declared = {group.objgen for group in pdf.Root.get("/OCProperties", {}).get("/OCGs", [])}
    have_operator = False
    for value in state:
        if isinstance(value, pikepdf.Name):
            _require(value in (pikepdf.Name.ON, pikepdf.Name.OFF, pikepdf.Name.Toggle),
                     "Invalid layer state operation")
            have_operator = True
        else:
            _require(have_operator and isinstance(value, pikepdf.Dictionary)
                     and value.get("/Type") == pikepdf.Name.OCG and value.objgen in declared,
                     "Layer action refers to undeclared OCG")


def _check_metadata(pdf):
    """Reject unsupported active/form semantics and known ULSBS JSON channels.

    Walk reachable objects for action restrictions, allowing named navigation,
    URI and validated layer actions, plus the narrow read-only PGF workaround.
    Startup views must be unchained GoTo actions. Scan information, XML metadata,
    piece information and attachment channels for known payload markers, decoding
    XML/JSON to expose escaped spellings. Ordinary attribution metadata is kept.
    This is neither arbitrary content-stream scanning nor a general sanitizer;
    malformed XML and unsupported semantics fail rather than being rewritten.
    """
    _require(not pdf.is_encrypted, "Encrypted PDFs are unsupported")
    markers = ("ulsbs:multikey", "urn:ulsbs:multikey", "has_multikey_info", "multikey_info",
               "layer_page_indices", "layer_protocol")
    def contains_payload(text):
        """Detect known ULSBS markers, including punctuation-obfuscated spelling."""
        text = text.lower()
        compact = re.sub(r"[^a-z0-9]", "", text)
        return any(marker in text for marker in markers) or "ulsbsmultikey" in compact
    for obj in _walk(pdf.trailer):
        if not isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
            continue
        _require(not any(key in obj for key in ("/AA", "/JavaScript")),
                 "Unsupported active/form semantics")
        if "/FT" in obj or obj.get("/Subtype") == pikepdf.Name.Widget:
            _require(_readonly_pgf_button(obj), "Unsupported editable/form annotation")
        if "/AcroForm" in obj:
            form = obj.AcroForm
            _require(isinstance(form, pikepdf.Dictionary)
                     and set(form.keys()) <= {"/Fields", "/NeedAppearances", "/DR", "/DA"}
                     and all(_readonly_pgf_button(field) for field in form.get("/Fields", [])),
                     "Unsupported editable AcroForm")
        initial = obj.get("/OpenAction")
        if initial is not None:
            _require(isinstance(initial, pikepdf.Dictionary)
                     and initial.get("/S") == pikepdf.Name.GoTo and "/Next" not in initial,
                     "Unsupported initial-view action")
        action = obj.get("/A")
        if isinstance(action, pikepdf.Dictionary):
            if action.get("/S") == pikepdf.Name.ResetForm:
                _require(_readonly_pgf_button(obj), "Unsupported ResetForm action")
            else:
                _require(action.get("/S") in (pikepdf.Name.GoTo, pikepdf.Name.URI,
                                             pikepdf.Name.SetOCGState)
                         and "/Next" not in action, "Unsupported PDF action")
                if action.get("/S") == pikepdf.Name.SetOCGState:
                    _layer_action(action, pdf)
        if obj.get("/Type") == pikepdf.Name.Action:
            _require(obj.get("/S") in (pikepdf.Name.GoTo, pikepdf.Name.URI,
                                      pikepdf.Name.SetOCGState)
                     and "/Next" not in obj, "Unsupported PDF action")
        channels = []
        for key, value in obj.items():
            _require(not contains_payload(key), "ULSBS JSON metadata key")
            if key in ("/Info", "/Metadata", "/PieceInfo", "/AF", "/EmbeddedFiles"):
                channels.append(value)
        if obj.get("/Type") in (pikepdf.Name.Filespec, pikepdf.Name.EmbeddedFile):
            channels.append(obj)
        for channel in channels:
            for value in _walk(channel):
                if isinstance(value, pikepdf.Stream):
                    text = value.read_bytes().decode("utf-8", errors="replace")
                    if value.get("/Subtype") == pikepdf.Name.XML:
                        try:
                            xml = ET.fromstring(text)
                            text += " ".join(str(part) for node in xml.iter()
                                             for part in [node.tag, node.text or "",
                                                          *node.attrib.keys(), *node.attrib.values()])
                        except ET.ParseError as error:
                            raise ValueError("Malformed XML metadata") from error
                elif isinstance(value, (pikepdf.String, pikepdf.Name)):
                    text = str(value)
                else:
                    continue
                try:
                    payload = json.loads(text)
                    text += json.dumps(payload, ensure_ascii=False)
                except (ValueError, RecursionError):
                    pass
                _require(not contains_payload(text),
                         "ULSBS JSON in metadata/attachment channel")


def _destinations(pdf):
    """Map legacy and name-tree destinations to (0-based page, mode/coordinates).

    Normalize PDF name/string spellings, unwrap /D dictionaries and validate
    supported Fit/XYZ modes and finite coordinates (nulls except in FitR).
    Duplicate names must resolve identically. Retaining the full destination
    tail lets pairing checks catch changed coordinates, not merely changed pages.
    """
    result = {}
    def add(name, target):
        """Validate and merge one destination into the normalized name mapping."""
        name = str(name).removeprefix("/") if isinstance(name, pikepdf.Name) else str(name)
        if isinstance(target, pikepdf.Dictionary):
            target = target.get("/D")
        _require(isinstance(target, pikepdf.Array) and len(target) >= 2, "Invalid named destination")
        pages = {page.objgen: i for i, page in enumerate(pdf.pages)}
        _require(isinstance(target[0], pikepdf.Dictionary) and target[0].objgen in pages,
                 "Named destination is not a document page")
        lengths = {"/Fit": 2, "/FitB": 2, "/FitH": 3, "/FitBH": 3, "/FitV": 3,
                   "/FitBV": 3, "/XYZ": 5, "/FitR": 6}
        mode = str(target[1])
        _require(isinstance(target[1], pikepdf.Name) and mode in lengths
                 and len(target) == lengths[mode], "Unsupported named destination mode")
        tail = []
        tail.append(mode)
        for value in list(target)[2:]:
            _require((value is None and mode != "/FitR") or (
                not isinstance(value, bool) and (isinstance(value, (int, float))
                                                or type(value).__name__ == "Decimal")
                and math.isfinite(float(value))), "Unsupported destination coordinate")
            tail.append(value)
        resolved = (pages[target[0].objgen], tail)
        _require(name not in result or result[name] == resolved, "Conflicting named destinations")
        result[name] = resolved
    for name, target in pdf.Root.get("/Dests", {}).items():
        add(pikepdf.Name(name), target)
    tree = pdf.Root.get("/Names", {}).get("/Dests")
    if tree is not None:
        for name, target in pikepdf.NameTree(tree).items():
            add(name, target)
    return result


def _links(pdf, canonical_names, master_names=None):
    """Check Link annotations without changing targets, actions or coordinates.

    Internal targets must be names present in the ordinary PDF's mapping; when
    master_names is supplied, their global page and full coordinate tail must
    also match. Range-local destination trees need not resolve off-range names.
    Allow unchained layer actions and control-free http/https/mailto URI actions;
    reject direct/missing destinations. Extracted annotation geometry and exact
    action preservation are checked separately by object-graph equivalence.
    """
    for page in pdf.pages:
        for annotation in page.obj.get("/Annots", []):
            if annotation.get("/Subtype") != pikepdf.Name.Link:
                continue
            action, target = annotation.get("/A"), annotation.get("/Dest")
            _require(not (action is not None and target is not None), "Ambiguous Link destination")
            if action is not None:
                _require("/Next" not in action, "Chained Link action")
                if action.get("/S") == pikepdf.Name.SetOCGState:
                    _layer_action(action, pdf)
                    continue
                if action.get("/S") == pikepdf.Name.URI:
                    uri = str(action.get("/URI", ""))
                    _require(not re.search(r"[\x00-\x20\x7f]", uri)
                             and urlsplit(uri).scheme.lower() in ("https", "http", "mailto"),
                             "Unsafe URI Link")
                    continue
                _require(action.get("/S") == pikepdf.Name.GoTo, "Unsupported Link action")
                target = action.get("/D")
            _require(isinstance(target, (pikepdf.Name, pikepdf.String)),
                     "Unsupported direct or missing Link destination; canonical names required")
            name = str(target).removeprefix("/") if isinstance(target, pikepdf.Name) else str(target)
            _require(name in canonical_names, "Link name missing from ordinary PDF")
            if master_names is not None:
                _require(name in master_names and master_names[name] == canonical_names[name],
                         f"Master/canonical named target coordinates differ for {name!r}: "
                         f"master={master_names.get(name)!r}, canonical={canonical_names[name]!r} "
                         "(zero-based page indices)")


def check_pdf_property_resources(path: Path) -> None:
    """Reject invalid marked-content property dictionaries without reading ink.

    Legacy pdfbase writes page-property references through the previous pass's
    auxiliary file. Changed PDF object allocation can therefore leave a property
    pointing to an image/Form stream until another LuaLaTeX pass settles it.
    Check pages and nested Form resources cheaply, without decoding their drawing
    streams or font programs. A property list must be a dictionary, never a
    stream, scalar, or null. Raise ``ValueError`` with its page/resource context.

    This is only a producer convergence check, not OCG semantic qualification:
    valid dictionaries may still name the wrong groups, and full layer/content
    validation remains mandatory during range packaging. No PDF is modified.
    """
    with pikepdf.open(path) as pdf:
        pending = [(_inherited(page, "/Resources", pikepdf.Dictionary()), f"page {index}")
                   for index, page in enumerate(pdf.pages, 1)]
        visited = set()
        while pending:
            resources, context = pending.pop()
            properties = resources.get("/Properties", pikepdf.Dictionary())
            _require(isinstance(properties, pikepdf.Dictionary),
                     f"Invalid marked-content Properties dictionary on {context}")
            for name, value in properties.items():
                kind = "stream" if isinstance(value, pikepdf.Stream) else type(value).__name__
                _require(isinstance(value, pikepdf.Dictionary),
                         f"Invalid marked-content property {name} on {context}: expected dictionary, got {kind}")
            for name, graphic in resources.get("/XObject", {}).items():
                if (isinstance(graphic, pikepdf.Stream) and graphic.get("/Subtype") == pikepdf.Name.Form
                        and graphic.objgen not in visited):
                    visited.add(graphic.objgen)
                    if "/Resources" in graphic:
                        pending.append((graphic.Resources, f"{context}, Form {name}"))


def _dependencies(pdf):
    """Map used transpose OCG names to sets of 0-based physical page indices.

    Follow actual /OC BDC uses, invoked XObjects (including nested Forms), their
    /OC entries, and annotation /OC entries, rather than counting unused resource
    declarations. Resolve named properties in the active resources; Forms use
    their own resources when present, otherwise the caller's. OCMD group lists
    and visibility expressions also contribute dependencies. Referenced groups
    must be declared; fixed layers are validated but omitted from the result.
    Recursive Form invocation fails instead of looping. This is dependency
    analysis of supported constructs, not evaluation of rendered visibility.
    """
    dependencies = {}
    declared = {group.objgen for group in pdf.Root.get("/OCProperties", {}).get("/OCGs", [])}
    def record(group, index):
        """Record a declared OCG/OCMD and any visibility-expression groups."""
        _require(isinstance(group, pikepdf.Dictionary), "Invalid optional content resource")
        groups = group.get("/OCGs", []) if group.get("/Type") == pikepdf.Name.OCMD else [group]
        if isinstance(groups, pikepdf.Dictionary):
            groups = [groups]
        for ocg in groups:
            _require(isinstance(ocg, pikepdf.Dictionary)
                     and ocg.get("/Type") == pikepdf.Name.OCG and ocg.objgen in declared,
                     "Content refers to undeclared optional content group")
            name = str(ocg.get("/Name", ""))
            if name.startswith(PROTOCOL + ":"):
                _require(re.fullmatch(r".+:t(?:0\d|1[01])", name) is not None,
                         "Invalid transpose OCG name")
                dependencies.setdefault(name, set()).add(index)
        # Visibility expressions can refer to additional groups.
        if "/VE" in group:
            for value in _walk(group.VE):
                if isinstance(value, pikepdf.Dictionary) and value.get("/Type") == pikepdf.Name.OCG:
                    record(value, index)
    def visit(stream, resources, index, active):
        """Parse one page/Form with a path-local recursion guard and resources."""
        identity = stream.obj.objgen if isinstance(stream, pikepdf.Page) else stream.objgen
        _require(identity not in active, "Recursive Form content")
        active = active | {identity}
        for operands, operator in pikepdf.parse_content_stream(stream):
            if str(operator) == "BDC" and str(operands[0]) == "/OC":
                group = operands[1]
                record(resources["/Properties"][group] if isinstance(group, pikepdf.Name) else group,
                       index)
            elif str(operator) == "Do":
                graphic = resources["/XObject"][operands[0]]
                if "/OC" in graphic:
                    record(graphic.OC, index)
                if graphic.get("/Subtype") == pikepdf.Name.Form:
                    visit(graphic, graphic.get("/Resources", resources), index, active)
    for index, page in enumerate(pdf.pages):
        visit(page, _inherited(page, "/Resources", pikepdf.Dictionary()), index, set())
        for annotation in page.obj.get("/Annots", []):
            if "/OC" in annotation:
                record(annotation.OC, index)
    return dependencies


def _check_manifest_layers(pdf, manifest):
    """Require twelve declared alternatives per song and matching page-set unions.

    Dependencies are unioned across alternatives, not required on every page for
    every key. Unused global declarations are allowed; used transpose prefixes
    must agree exactly with nonempty manifest affected-page sets.
    """
    declarations = pdf.Root.get("/OCProperties", {}).get("/OCGs", [])
    names = [str(group.get("/Name", "")) for group in declarations]
    transpose_names = [name for name in names if name.startswith(PROTOCOL + ":")]
    _require(len(transpose_names) == len(set(transpose_names)), "Duplicate transpose OCG names")
    expected, dependencies = {}, _dependencies(pdf)
    for song in manifest["multikey_info"]["songs"]:
        for offset in range(12):
            name = f"{song['layer_prefix']}:t{offset:02d}"
            _require(name in names, "Missing manifest OCG alternative")
        expected[song["layer_prefix"]] = set(song["layer_page_indices"])
    actual = {}
    for name, indices in dependencies.items():
        actual.setdefault(name.rsplit(":t", 1)[0], set()).update(indices)
    _require({k: v for k, v in expected.items() if v} == actual,
             "Manifest affected pages disagree with actual optional content")


def _equivalent(left, right, page_targets):
    """Require supported graph equality while allowing extraction serialization.

    Compare dictionary keys, arrays and scalar values (including bool distinction),
    closing cycles by pairs of indirect IDs. Source page references listed in
    page_targets must resolve to the mapped candidate page. Ignore page /Parent
    because extraction rebuilds the page tree. Compare decoded stream bytes while
    ignoring /Length, /Filter and /DecodeParms; if decoding raises PdfError, compare
    raw bytes and retain filter/parameter checks. Object numbering and stream
    compression may differ, but content rewriting is not normalized. ValueError
    reports a mismatch; this is strict structural comparison, not a renderer.
    """
    pending, seen = [(left, right)], set()
    while pending:
        a, b = pending.pop()
        if isinstance(a, pikepdf.Object) and a.is_indirect:
            _require(isinstance(b, pikepdf.Object), "Changed PDF reference")
            if a.objgen in page_targets:
                _require(b.objgen == page_targets[a.objgen], "Changed page reference")
            pair = (a.objgen, b.objgen)
            if pair in seen:
                continue
            seen.add(pair)
        ignored = set()
        if isinstance(a, pikepdf.Stream):
            _require(isinstance(b, pikepdf.Stream), "Changed stream type")
            ignored.add("/Length")
            try:
                a_data, b_data = a.read_bytes(), b.read_bytes()
                ignored.update(("/Filter", "/DecodeParms"))
            except pikepdf.PdfError:
                a_data, b_data = a.read_raw_bytes(), b.read_raw_bytes()
            _require(a_data == b_data, "Changed decoded page/resource stream")
        if isinstance(a, (pikepdf.Dictionary, pikepdf.Stream)):
            _require(isinstance(b, (pikepdf.Dictionary, pikepdf.Stream)), "Changed dictionary type")
            if a.get("/Type") == pikepdf.Name.Page:
                ignored.add("/Parent")
            _require(set(a.keys()) - ignored == set(b.keys()) - ignored, "Changed PDF dictionary")
            pending.extend((a[k], b[k]) for k in set(a.keys()) - ignored)
        elif isinstance(a, pikepdf.Array):
            _require(isinstance(b, pikepdf.Array) and len(a) == len(b), "Changed PDF array")
            pending.extend(zip(a, b, strict=True))
        else:
            _require(a == b and isinstance(a, bool) == isinstance(b, bool), "Changed PDF value")


def _outside_initial_view(source, first, last):
    """Test whether a direct startup page lies outside 1-based inclusive bounds.

    Other destination shapes return False; unknown direct page objects fail.
    """
    action = source.Root.get("/OpenAction", {})
    if not isinstance(action, pikepdf.Dictionary):
        return False
    target = action.get("/D")
    if not isinstance(target, pikepdf.Array) or not len(target):
        return False
    page = target[0]
    if not isinstance(page, pikepdf.Dictionary) or page.get("/Type") != pikepdf.Name.Page:
        return False
    indices = {p.objgen: i for i, p in enumerate(source.pages, 1)}
    _require(page.objgen in indices, "Initial view targets an unknown page")
    return not first <= indices[page.objgen] <= last


def _cleanup_initial_view(source, candidate, first, last):
    """Remove only a GoTo startup view that qpdf made invalid (null page).

    For 1-based inclusive first/last, require the original unchained GoTo to
    target an excluded page and the candidate action to match exactly except
    for that page becoming null. Delete the candidate catalog entry and return
    True only in that case; otherwise leave it unchanged and return False.
    This is not a Link annotation or outline. Keeping it would leave an invalid
    initial-view action or import a page outside the requested range. This is
    expected range normalization, not a warning; all annotations/outlines still
    require exact equivalence, and unexpected action changes remain errors.
    """
    if not _outside_initial_view(source, first, last):
        return False
    original = source.Root.OpenAction
    _require(original.get("/S") == pikepdf.Name.GoTo and "/Next" not in original,
             "Unsupported initial-view action")
    actual = candidate.Root.get("/OpenAction")
    expected = pikepdf.Dictionary({key: value for key, value in original.items()})
    expected.D = pikepdf.Array([None, *list(original.D)[1:]])
    _equivalent(expected, actual, {})
    del candidate.Root["/OpenAction"]
    return True


def _check_range(source, candidate, first, last, canonical_names, source_dependencies=None, *,
                 removed_initial_view=False):
    """Validate an extracted candidate against source pages first..last (1-based).

    Require the exact page count and no extra /Page dictionaries anywhere in the
    candidate object table, supported metadata/actions and canonical named links.
    Compare the full OCG catalog, other catalog/trailer information, non-destination
    name trees, selected page graphs/resources and all effective geometry. Allowed
    extraction differences are rebuilt page/destination trees, rebased page-label
    storage with identical effective labels, pruned off-range PGF form fields,
    and the separately proven startup-view removal when explicitly flagged.

    Recompute actual candidate dependencies and compare with the selected source
    subset rebased to 0-based local indices. source_dependencies may cache the
    unchanged master's traversal. These structural checks do not render pages or
    establish the provenance of either PDF; contract mismatches raise ValueError.
    """
    _require(len(candidate.pages) == last - first + 1, "Extracted page count mismatch")
    page_objects = [obj for obj in candidate.objects if isinstance(obj, pikepdf.Dictionary)
                    and obj.get("/Type") == pikepdf.Name.Page]
    _require(len(page_objects) == len(candidate.pages), "Retained unrequested page graph")
    _check_metadata(candidate)
    _links(candidate, canonical_names)
    mapping = {source.pages[i].objgen: candidate.pages[i - first + 1].objgen
               for i in range(first - 1, last)}
    _equivalent(source.Root.get("/OCProperties"), candidate.Root.get("/OCProperties"), mapping)
    # Destination trees may drop unavailable definitions: annotation names are
    # global canonical identities, and must remain untouched on selected pages.
    for key in set(source.Root.keys()) | set(candidate.Root.keys()):
        if key == "/PageLabels":
            # qpdf rebases the number tree and starting counters. Preserve the
            # effective global label of each selected page, not tree offsets.
            for index, page in enumerate(candidate.pages, first - 1):
                _require(source.pages[index].label == page.label, "Changed page label")
            continue
        if key == "/OpenAction" and removed_initial_view:
            _require(_outside_initial_view(source, first, last) and key not in candidate.Root,
                     "Invalid initial-view cleanup")
            continue
        if key not in ("/Pages", "/OCProperties", "/Names", "/Dests"):
            original, extracted = source.Root.get(key), candidate.Root.get(key)
            if key == "/AcroForm" and original is not None:
                # qpdf prunes off-range PGF read-only workaround widgets from
                # Fields. These are not editable fields or useful navigation;
                # selected widgets and their appearance graphs must be exact.
                selected = {annotation.objgen for i in range(first - 1, last)
                            for annotation in source.pages[i].obj.get("/Annots", [])}
                fields = [field for field in original.get("/Fields", []) if field.objgen in selected]
                original = pikepdf.Dictionary({k: v for k, v in original.items()})
                original.Fields = pikepdf.Array(fields)
                if not fields and extracted is None:
                    continue
            try:
                _equivalent(original, extracted, mapping)
            except ValueError as error:
                raise ValueError(f"Catalog {key}: {error}") from error
    for key in ("/Info",):
        _equivalent(source.trailer.get(key), candidate.trailer.get(key), mapping)
    source_names, candidate_names = source.Root.get("/Names", {}), candidate.Root.get("/Names", {})
    for key in set(source_names.keys()) | set(candidate_names.keys()):
        if key != "/Dests":
            _equivalent(source_names.get(key), candidate_names.get(key), mapping)
    for i, page in enumerate(candidate.pages, first - 1):
        original = source.pages[i]
        _require(_geometry(original) == _geometry(page), "Extracted page geometry changed")
        _equivalent(original.obj, page.obj, mapping)
    original_dependencies = (_dependencies(source) if source_dependencies is None
                             else source_dependencies)
    expected = {name: {i - first + 1 for i in indices if first - 1 <= i < last}
                for name, indices in original_dependencies.items()}
    _require(_dependencies(candidate) == {k: v for k, v in expected.items() if v},
             "Extracted content dependencies changed")


def _run(argv):
    """Run captured argv without a shell; return stdout or fail on nonzero status.

    qpdf diagnostics become ValueError; process-launch OSError propagates.
    """
    result = subprocess.run(argv, check=False, capture_output=True, text=True)
    _require(result.returncode == 0, f"qpdf failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def qpdf_version() -> str:
    """Run qpdf from PATH and return its accepted major.minor.patch version.

    This optional early preflight writes no files. ValueError reports command
    failure, unrecognized output or a version below the shared toolchain policy;
    launch failures such as a missing executable raise OSError. Passing the gate
    does not replace per-output qpdf and structural checks during packaging.
    """
    version_text = _run(["qpdf", "--version"])
    match = re.search(r"qpdf version (\d+)\.(\d+)\.(\d+)", version_text)
    minimum = ".".join(map(str, MULTIKEY_MIN_QPDF_VERSION))
    _require(match is not None and tuple(map(int, match.groups())) >= MULTIKEY_MIN_QPDF_VERSION,
             f"qpdf >= {minimum} required")
    return ".".join(match.groups())


def package_ranges(master: Path, canonical: Path, manifest: dict, staging_dir: Path, *,
                   max_pages: int = 50, target_bytes: int = 33554432,
                   warn: Callable = warnings.warn) -> Path:
    """Return the staged index Path after extracting and checking a complete book.

    master and canonical are distinct finalized, JSON-free layered/ordinary PDFs;
    manifest is the compiler-derived schema-v2 envelope, not embedded metadata.
    They must share a nonzero page count and all effective geometry. Internal
    Links must already use equivalent canonical names: no link normalization,
    flattening or re-engraving is performed. Anchor bounds and actual layer page
    sets are checked, not visual anchor placement or master/ordinary rendering.

    Positive integer max_pages (default 50) bounds initial 1-based physical page
    ranges. target_bytes (default 32 MiB) applies to measured extracted bytes:
    oversized multi-page candidates are bisected and re-extracted from master.
    A single oversized page is kept, with a message to warn (default warnings.warn).
    Neither option promises viewer memory use or limits the master PDF's size.

    Create staging_dir as needed, write validated range PDFs there, then write
    the bounded compact UTF-8 index last. No canonical copy is staged. The output
    name appends MULTIKEY to the *ordinary* stem, including editions:
    Book_A5_MULTIKEY_RANGES.json and Book_A5_MULTIKEY_RANGE_1-50.pdf.
    Staging must not already contain this package family; failed invocations
    remove only tracked outputs they created (the directory may remain). Inputs
    must remain stable and staging must not have concurrent writers. Sources are
    never modified; publication and inventory cleanup are caller responsibilities.
    An initial-view GoTo pointing outside a range is removed quietly,
    after proving qpdf changed only its unavailable page reference to null.
    Useful Link annotations and outlines are never removed or normalized.

    Contract/unsupported-input and qpdf command failures raise ValueError;
    filesystem/process-launch OSError, pikepdf parsing errors and warn callback
    exceptions propagate. Cleanup is attempted even on interruption. Successful
    structural validation and file hashes do not authenticate the book or prove
    equivalent rendering across PDF implementations.
    """
    master, canonical, staging_dir = Path(master).resolve(), Path(canonical).resolve(), Path(staging_dir)
    _require(master != canonical, "Master and ordinary PDF must be distinct")
    _require(_integer(max_pages) and _integer(target_bytes), "Invalid range sizing options")
    _basename(canonical.name)
    _require(canonical.suffix == ".pdf", "Canonical filename must end in .pdf")
    version = qpdf_version()
    stem = canonical.stem + "_MULTIKEY"
    staging_dir.mkdir(parents=True, exist_ok=True)
    index_path = staging_dir / (stem + "_RANGES.json")
    _require(not index_path.exists() and not any(staging_dir.glob(stem + "_RANGE_*.pdf")),
             "Staging already contains this package family")
    created = []
    try:
        with pikepdf.open(master, attempt_recovery=False) as source, pikepdf.open(
                canonical, attempt_recovery=False) as ordinary:
            count = len(source.pages)
            _require(count > 0 and len(ordinary.pages) == count, "Master/ordinary page count mismatch")
            _check_metadata(source)
            _check_metadata(ordinary)
            geometry = []
            for a, b in zip(source.pages, ordinary.pages, strict=True):
                _require(_geometry(a) == _geometry(b), "Master/ordinary page geometry mismatch")
                geometry.append(_geometry(a)[0])
            _manifest(manifest, count, geometry)
            _check_manifest_layers(source, manifest)
            source_dependencies = _dependencies(source)
            canonical_names, master_names = _destinations(ordinary), _destinations(source)
            _links(ordinary, canonical_names)
            _links(source, canonical_names, master_names)
            ranges = []
            def extract(first, last):
                """Check a 1-based inclusive candidate, bisecting oversized outputs.

                Append only accepted leaf descriptors, in physical page order;
                measure/hash after any proven startup-view cleanup and checks.
                """
                output = staging_dir / f"{stem}_RANGE_{first}-{last}.pdf"
                _require(output.resolve() not in (master, canonical), "Output would overwrite an input")
                created.append(output)
                _run(["qpdf", str(master), "--deterministic-id", "--pages", ".",
                      f"{first}-{last}", "--", str(output.resolve())])
                with pikepdf.open(output, attempt_recovery=False, allow_overwriting_input=True) as pdf:
                    removed_initial_view = _cleanup_initial_view(source, pdf, first, last)
                    if removed_initial_view:
                        pdf.save(output, deterministic_id=True, fix_metadata_version=False)
                _run(["qpdf", "--check", str(output.resolve())])
                with pikepdf.open(output, attempt_recovery=False) as candidate:
                    _check_range(source, candidate, first, last, canonical_names, source_dependencies,
                                 removed_initial_view=removed_initial_view)
                size = output.stat().st_size
                if size > target_bytes and first != last:
                    output.unlink()
                    midpoint = (first + last) // 2
                    extract(first, midpoint)
                    extract(midpoint + 1, last)
                    return
                if size > target_bytes:
                    warn(f"Single-page range {output.name} is {size} bytes, exceeding {target_bytes}")
                ranges.append({**_identity(output), "first_page": first, "last_page": last,
                               "page_count": last - first + 1})
            for first in range(1, count + 1, max_pages):
                extract(first, min(first + max_pages - 1, count))
            index = {"format": "ulsbs:multikey-ranges", "schema_version": 1,
                     "page_count": count, "max_pages_per_range": max_pages,
                     "target_max_range_bytes": target_bytes, "link_policy": "canonical-names-v1",
                     "canonical": _identity(canonical), "geometry": geometry, "manifest": manifest,
                     "ranges": ranges, "packaging": {"tool": "qpdf", "tool_version": version}}
            validate_index(index, index_path, canonical)
            data = _encoded(index)
            with index_path.open("xb") as stream:
                created.append(index_path)
                stream.write(data)
        return index_path
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
