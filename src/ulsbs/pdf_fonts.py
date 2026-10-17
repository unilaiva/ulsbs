# SPDX-FileCopyrightText: 2016-2026 Lari Natri <lari.natri@iki.fi>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Share identical embedded font programs without merging font subsets."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path

import pikepdf


def _check_equivalent(original: pikepdf.Pdf, candidate: pikepdf.Pdf) -> None:
    """Compare the complete logical document, independent of object numbering."""
    if len(original.pages) != len(candidate.pages):
        raise ValueError("PDF page count changed during font sharing")
    # Even visually identical pages are different link destinations.
    page_targets = {a.objgen: b.objgen for a, b in zip(original.pages, candidate.pages, strict=True)}
    # Cross-reference layout and the revision ID describe physical serialization,
    # not document content. All other trailer entries must survive unchanged.
    physical = {
        "/Size", "/Prev", "/XRefStm", "/ID", "/Type", "/W", "/Index",
        "/Length", "/Filter", "/DecodeParms",
    }
    left = pikepdf.Dictionary({k: v for k, v in original.trailer.items() if k not in physical})
    right = pikepdf.Dictionary({k: v for k, v in candidate.trailer.items() if k not in physical})
    pending = [(left, right)]
    seen = set()
    while pending:
        a, b = pending.pop()
        if isinstance(a, pikepdf.Object) and a.is_indirect:
            if not isinstance(b, pikepdf.Object) or not b.is_indirect:
                raise ValueError("PDF object reference changed during font sharing")
            if a.objgen in page_targets and page_targets[a.objgen] != b.objgen:
                raise ValueError("PDF page destination changed during font sharing")
            pair = (a.objgen, b.objgen)
            if pair in seen:
                continue
            seen.add(pair)
        if isinstance(a, pikepdf.Stream):
            if not isinstance(b, pikepdf.Stream):
                raise ValueError("PDF stream changed type during font sharing")
            ignored = {"/Length"}
            try:
                a_data, b_data = a.read_bytes(), b.read_bytes()
                ignored.update(("/Filter", "/DecodeParms"))
            except pikepdf.PdfError:
                # Unsupported image codecs must retain both their encoded bytes
                # and decoding parameters; never rasterize or transcode them.
                a_data, b_data = a.read_raw_bytes(), b.read_raw_bytes()
            if a_data != b_data:
                raise ValueError("PDF stream data changed during font sharing")
            a_keys, b_keys = set(a.keys()) - ignored, set(b.keys()) - ignored
            if a_keys != b_keys:
                raise ValueError("PDF stream dictionary changed during font sharing")
            pending.extend((a[k], b[k]) for k in a_keys)
        elif isinstance(a, pikepdf.Dictionary):
            if not isinstance(b, pikepdf.Dictionary) or set(a.keys()) != set(b.keys()):
                raise ValueError("PDF dictionary changed during font sharing")
            pending.extend((a[k], b[k]) for k in a.keys())
        elif isinstance(a, pikepdf.Array):
            if not isinstance(b, pikepdf.Array) or len(a) != len(b):
                raise ValueError("PDF array changed during font sharing")
            pending.extend(zip(a, b, strict=True))
        elif a != b or isinstance(a, bool) != isinstance(b, bool):
            raise ValueError("PDF value changed during font sharing")


def deduplicate_fonts(path: Path) -> tuple[int, int, int]:
    """Return (original bytes, final bytes, removed font-program objects).

    A failed rewrite raises and leaves the original intact. No-duplicate and
    non-shrinking inputs remain byte-for-byte untouched. Only font descriptor
    references change: distinct subsets, glyph mappings and metrics stay intact.
    """
    before = path.stat().st_size
    with pikepdf.open(path, attempt_recovery=False) as pdf:
        if pdf.is_encrypted:
            raise ValueError("Cannot rewrite an encrypted PDF")
        programs = {}
        replacements = []
        removed = set()
        for descriptor in pdf.objects:
            if not isinstance(descriptor, pikepdf.Dictionary):
                continue
            if descriptor.get("/Type") == pikepdf.Name.FontDescriptor:
                for key in ("/FontFile", "/FontFile2", "/FontFile3"):
                    stream = descriptor.get(key)
                    if stream is None:
                        continue
                    if not isinstance(stream, pikepdf.Stream):
                        raise ValueError("Font program is not a PDF stream")
                    data = stream.read_bytes()
                    dictionary = pikepdf.Dictionary({
                        k: v for k, v in stream.items()
                        if k not in ("/Length", "/Filter", "/DecodeParms")
                    }).unparse()
                    identity = (hashlib.sha256(data).digest(), dictionary)
                    canonical = programs.setdefault(identity, stream)
                    if canonical.objgen != stream.objgen:
                        # Hashes find candidates, but exact equality authorizes sharing.
                        if canonical.read_bytes() != data:
                            raise ValueError("Font-program hash collision")
                        replacements.append((descriptor, key, canonical))
                        removed.add(stream.objgen)
            if descriptor.get("/Type") == pikepdf.Name.Sig or descriptor.get("/FT") == pikepdf.Name.Sig:
                raise ValueError("Cannot rewrite a signed PDF")

        if not replacements:
            return before, before, 0
        # Ubuntu's pikepdf 9.x calls this check(); 10.x renamed the API.
        check_syntax = getattr(pikepdf.Pdf, "check_pdf_syntax", None) or pikepdf.Pdf.check
        if check_syntax(pdf):
            raise ValueError("Input PDF failed syntax validation")
        # Keep the input graph unchanged for validation against the saved candidate.
        with pikepdf.open(path, attempt_recovery=False) as original:
            for descriptor, key, canonical in replacements:
                descriptor[key] = canonical
            fd, filename = tempfile.mkstemp(prefix=f".{path.stem}.fonts-", suffix=".pdf", dir=path.parent)
            os.close(fd)
            temporary = Path(filename)
            try:
                pdf.save(temporary, fix_metadata_version=False)
                after = temporary.stat().st_size
                if after >= before:
                    return before, before, 0
                with pikepdf.open(temporary, attempt_recovery=False) as candidate:
                    if check_syntax(candidate):
                        raise ValueError("Font-sharing candidate failed syntax validation")
                    _check_equivalent(original, candidate)
                os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
                os.replace(temporary, path)
                return before, after, len(removed)
            finally:
                temporary.unlink(missing_ok=True)
