#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strict EPUB integrity validator (stdlib only)."""
from __future__ import annotations

import argparse
from pathlib import PurePosixPath
import re
import sys
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET
from zipfile import ZIP_STORED, ZipFile

MARKERS = ("🀄", "🈳", "__PROHIBITED_CONTENT__")
XML_SUFFIXES = (".xhtml", ".html", ".xml", ".opf", ".ncx", ".svg")


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _resolve(base_name: str, href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("http://", "https://", "data:", "mailto:")):
        return None
    path = unquote(urlsplit(href).path)
    if not path:
        return None
    base = PurePosixPath(base_name).parent
    parts = []
    for part in (base / path).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def validate_epub(path: str, *, strict_markers=True, strict_arrows=False):
    errors, warnings = [], []
    try:
        z = ZipFile(path)
    except Exception as exc:
        return [f"cannot open EPUB: {exc}"], warnings, {}
    with z:
        names = z.namelist()
        name_set = set(names)
        if not names or names[0] != "mimetype":
            errors.append("mimetype must be the first ZIP entry")
        elif z.getinfo("mimetype").compress_type != ZIP_STORED:
            errors.append("mimetype must be stored without compression")
        elif z.read("mimetype") != b"application/epub+zip":
            errors.append("invalid mimetype content")
        bad_crc = z.testzip()
        if bad_crc:
            errors.append(f"ZIP CRC error: {bad_crc}")

        parsed = {}
        all_xhtml = ""
        for name in names:
            if name.lower().endswith(XML_SUFFIXES):
                try:
                    parsed[name] = ET.fromstring(z.read(name))
                except Exception as exc:
                    errors.append(f"malformed XML/XHTML {name}: {exc}")
            if name.lower().endswith((".xhtml", ".html")):
                all_xhtml += z.read(name).decode("utf-8", "ignore")

        if strict_markers:
            for marker in MARKERS:
                count = all_xhtml.count(marker)
                if count:
                    errors.append(f"unresolved marker {marker}: {count}")
        else:
            for marker in MARKERS:
                count = all_xhtml.count(marker)
                if count:
                    warnings.append(f"unresolved marker {marker}: {count}")
        for arrow in ("⬆️", "⬇️"):
            count = all_xhtml.count(arrow)
            if count:
                target = errors if strict_arrows else warnings
                target.append(f"unresolved footnote continuation marker {arrow}: {count}")

        # Generic internal links and resources.
        for name, root in parsed.items():
            for elem in root.iter():
                for attr in ("href", "src"):
                    href = elem.attrib.get(attr)
                    resolved = _resolve(name, href) if href else None
                    if resolved and resolved not in name_set:
                        errors.append(f"missing resource from {name}: {href} -> {resolved}")

        # Find OPF through container.xml.
        opf_name = None
        container = parsed.get("META-INF/container.xml")
        if container is not None:
            for elem in container.iter():
                if _local(elem.tag) == "rootfile":
                    opf_name = elem.attrib.get("full-path")
                    break
        if not opf_name or opf_name not in parsed:
            errors.append("content OPF not found through META-INF/container.xml")
        else:
            opf = parsed[opf_name]
            manifest = {}
            spine = []
            cover_props = []
            for elem in opf.iter():
                tag = _local(elem.tag)
                if tag == "item":
                    item_id, href = elem.attrib.get("id"), elem.attrib.get("href")
                    if item_id and href:
                        resolved = _resolve(opf_name, href)
                        manifest[item_id] = resolved
                        if "cover-image" in elem.attrib.get("properties", "").split():
                            cover_props.append(item_id)
                        if resolved and resolved not in name_set:
                            errors.append(f"manifest item missing: {item_id} -> {resolved}")
                elif tag == "itemref":
                    ref = elem.attrib.get("idref")
                    if ref:
                        spine.append(ref)
            for ref in spine:
                if ref not in manifest:
                    errors.append(f"spine idref not in manifest: {ref}")
            if len(cover_props) > 1:
                errors.append(f"multiple cover-image manifest items: {cover_props}")
            if not spine:
                errors.append("empty spine")

        metrics = {
            "entries": len(names),
            "xml_documents": len(parsed),
            "xhtml_documents": sum(1 for n in names if n.endswith(".xhtml")),
            "tables": all_xhtml.count("<table"),
            "errors": len(errors),
            "warnings": len(warnings),
        }
        return errors, warnings, metrics


def main():
    parser = argparse.ArgumentParser(description="Strictly validate EPUB ZIP/XML/links/markers.")
    parser.add_argument("epub")
    parser.add_argument("--allow-markers", action="store_true")
    parser.add_argument("--strict-footnote-arrows", action="store_true")
    args = parser.parse_args()
    errors, warnings, metrics = validate_epub(
        args.epub,
        strict_markers=not args.allow_markers,
        strict_arrows=args.strict_footnote_arrows,
    )
    print("metrics:", metrics)
    for warning in warnings:
        print("WARNING:", warning)
    for error in errors:
        print("ERROR:", error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
