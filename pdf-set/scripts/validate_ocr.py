#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate per-page OCR Markdown and optional page metadata."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from table_utils import (
    page_meta_path,
    read_json,
    sha256_file,
    sha256_text,
    validate_page_markdown,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def numeric_files(directory: Path, suffixes: set[str]):
    items = []
    if not directory.is_dir():
        return items
    for path in directory.iterdir():
        if path.is_file() and path.stem.isdigit() and path.suffix.lower() in suffixes:
            items.append(path)
    return sorted(items, key=lambda p: int(p.stem))


def validate_book(images_dir: Path, output_dir: Path, prompt_file: Path | None, allow_placeholders=True):
    images = numeric_files(images_dir, IMAGE_EXTS)
    image_by_stem = {p.stem: p for p in images}
    md_files = numeric_files(output_dir, {".md"})
    md_by_stem = {p.stem: p for p in md_files}
    prompt_hash = sha256_text(prompt_file.read_text(encoding="utf-8")) if prompt_file and prompt_file.is_file() else None

    missing = [stem for stem in image_by_stem if stem not in md_by_stem]
    extras = [stem for stem in md_by_stem if stem not in image_by_stem]
    invalid = {}
    stale = {}
    metadata_missing = []

    for stem, md in md_by_stem.items():
        errors = validate_page_markdown(md.read_text(encoding="utf-8", errors="replace"), allow_placeholders=allow_placeholders)
        if errors:
            invalid[stem] = errors
        meta_path = page_meta_path(output_dir, stem)
        meta = read_json(meta_path, None)
        if meta is None:
            metadata_missing.append(stem)
            continue
        reasons = []
        if meta.get("status") != "ok" or meta.get("validated") is not True:
            reasons.append(f"status={meta.get('status')!r}, validated={meta.get('validated')!r}")
        if stem in image_by_stem and meta.get("image_sha256") != sha256_file(image_by_stem[stem]):
            reasons.append("image hash mismatch")
        if prompt_hash and meta.get("prompt_sha256") != prompt_hash:
            reasons.append("prompt hash mismatch")
        if meta.get("output_sha256") != sha256_file(md):
            reasons.append("output hash mismatch")
        if reasons:
            stale[stem] = reasons

    fail_files = sorted(p.name for p in output_dir.glob("*.fail.json")) if output_dir.is_dir() else []
    partial_files = sorted(p.name for p in output_dir.glob("*.partial.md")) if output_dir.is_dir() else []
    result = {
        "images": len(images),
        "outputs": len(md_files),
        "missing": sorted(missing, key=int),
        "extras": sorted(extras, key=int),
        "invalid": invalid,
        "stale": stale,
        "metadata_missing": sorted(metadata_missing, key=int),
        "failed": fail_files,
        "partial": partial_files,
    }
    result["ok"] = not missing and not extras and not invalid and not stale and not metadata_missing and not fail_files and not partial_files
    return result


def main():
    parser = argparse.ArgumentParser(description="Validate per-page OCR Markdown and metadata.")
    parser.add_argument("--base-dir", default=".", help="Book directory.")
    parser.add_argument("--images-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--prompt-file", default=None)
    parser.add_argument("--strict-placeholders", action="store_true", help="Fail on 🀄/🈳 markers.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    base = Path(args.base_dir).resolve()
    images = Path(args.images_dir).resolve() if args.images_dir else base / "images"
    output = Path(args.output_dir).resolve() if args.output_dir else base / "ocr-result"
    prompt = Path(args.prompt_file).resolve() if args.prompt_file else Path(__file__).resolve().parent.parent / "assets" / "ocr_prompt.md"
    result = validate_book(images, output, prompt, allow_placeholders=not args.strict_placeholders)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"images={result['images']} outputs={result['outputs']} ok={result['ok']}")
        for key in ("missing", "extras", "metadata_missing", "failed", "partial"):
            if result[key]:
                print(f"{key}: {result[key]}")
        for key in ("invalid", "stale"):
            for stem, errors in result[key].items():
                print(f"{key} {stem}: {'; '.join(errors)}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
