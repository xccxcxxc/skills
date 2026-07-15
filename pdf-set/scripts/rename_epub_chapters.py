#!/usr/bin/env python3
"""Optionally rename Pandoc EPUB chapter files; not required for valid EPUB."""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import os
import re
import shutil
import tempfile
from urllib.parse import unquote
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


def safe_name(title, used):
    title = re.sub(r"<[^>]+>", "", title)
    title = re.sub(r'[\\/:*?"<>|]', "", title).strip()
    title = re.sub(r"\s+", "-", title)[:48] or "chapter"
    base, value, n = title, title, 2
    while value in used:
        value = f"{base}-{n}"
        n += 1
    used.add(value)
    return value + ".xhtml"


def local(tag):
    return tag.rsplit("}", 1)[-1]


def rename_epub(src, dst):
    temp = Path(tempfile.mkdtemp(prefix="epub-rename-"))
    try:
        with ZipFile(src) as z:
            z.extractall(temp)
        container = ET.parse(temp / "META-INF" / "container.xml").getroot()
        opf_rel = next(e.attrib["full-path"] for e in container.iter() if local(e.tag) == "rootfile")
        opf_path = temp / PurePosixPath(opf_rel)
        opf_root = ET.parse(opf_path).getroot()
        opf_dir = PurePosixPath(opf_rel).parent
        nav_rel = None
        for item in opf_root.iter():
            if local(item.tag) == "item" and "nav" in item.attrib.get("properties", "").split():
                nav_rel = str(opf_dir / item.attrib["href"])
                break
        if not nav_rel:
            raise RuntimeError("EPUB nav item not found")
        nav_path = temp / PurePosixPath(nav_rel)
        nav_text = nav_path.read_text(encoding="utf-8")
        mapping, used = {}, set()
        for href, label in re.findall(r'href="([^"]*ch\d+\.xhtml)(?:#[^"]*)?"[^>]*>(.*?)</a>', nav_text, re.S):
            old_rel = unquote(str(PurePosixPath(nav_rel).parent / href))
            if old_rel not in mapping:
                new_name = safe_name(re.sub(r"<[^>]+>", "", label), used)
                mapping[old_rel] = str(PurePosixPath(old_rel).with_name(new_name))

        # Rename files, then update every textual EPUB document, not only nav/opf.
        for old, new in mapping.items():
            old_path, new_path = temp / PurePosixPath(old), temp / PurePosixPath(new)
            if old_path.exists():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                os.rename(old_path, new_path)
        for path in temp.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".xhtml", ".html", ".opf", ".ncx", ".xml"}:
                continue
            text = path.read_text(encoding="utf-8")
            rel = PurePosixPath(path.relative_to(temp).as_posix())
            for old, new in mapping.items():
                old_base, new_base = PurePosixPath(old).name, PurePosixPath(new).name
                text = text.replace(old_base, new_base)
            path.write_text(text, encoding="utf-8")

        with ZipFile(dst, "w") as out:
            mimetype = temp / "mimetype"
            out.write(mimetype, "mimetype", compress_type=ZIP_STORED)
            for path in sorted(temp.rglob("*")):
                if path.is_file() and path.name != "mimetype":
                    out.write(path, path.relative_to(temp).as_posix(), compress_type=ZIP_DEFLATED)
        return mapping
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Optionally rename EPUB chapter XHTML files.")
    parser.add_argument("src")
    parser.add_argument("dst")
    args = parser.parse_args()
    mapping = rename_epub(args.src, args.dst)
    for old, new in mapping.items():
        print(f"{old} -> {new}")


if __name__ == "__main__":
    main()
