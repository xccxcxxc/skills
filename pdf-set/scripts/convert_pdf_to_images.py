#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render PDF pages to OCR-friendly images with a reproducible manifest."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from hashlib import sha256

import pypdfium2 as pdfium
from PIL import Image


def sha256_file(path):
    h = sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def convert(
    pdf_path,
    output_dir,
    dpi=144,
    start_index=0,
    image_format="jpg",
    max_dim=None,
    first_page=0,
    last_page=None,
    jpeg_quality=92,
    overwrite=False,
):
    pdf_path, output_dir = Path(pdf_path), Path(output_dir)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    page_count = len(pdf)
    if last_page is None:
        last_page = page_count - 1
    if first_page < 0 or last_page < first_page or last_page >= page_count:
        pdf.close()
        raise ValueError(f"Invalid PDF page range: {first_page}-{last_page}; total={page_count}")
    scale = dpi / 72.0
    expected_names = set()
    pages = []

    for offset, page_no in enumerate(range(first_page, last_page + 1)):
        output_index = start_index + offset
        filename = f"{output_index}.{image_format}"
        expected_names.add(filename)
        image_path = output_dir / filename
        page = pdf[page_no]
        image = page.render(scale=scale).to_pil()
        page.close()

        if max_dim:
            width, height = image.size
            if width > max_dim or height > max_dim:
                factor = min(max_dim / width, max_dim / height)
                image = image.resize(
                    (max(1, int(width * factor)), max(1, int(height * factor))),
                    resample=Image.Resampling.LANCZOS,
                )

        save_format = "JPEG" if image_format.lower() in {"jpg", "jpeg"} else image_format.upper()
        if overwrite or not image_path.exists():
            options = {}
            if save_format == "JPEG":
                image = image.convert("RGB")
                options = {"quality": jpeg_quality, "subsampling": 0, "optimize": True}
            image.save(image_path, format=save_format, **options)
        pages.append(
            {
                "pdf_page": page_no,
                "output_index": output_index,
                "file": filename,
                "width": image.size[0],
                "height": image.size[1],
                "sha256": sha256_file(image_path),
            }
        )
        print(f"Saved PDF page {page_no} as {image_path} (size: {image.size})")

    pdf.close()
    # Do not silently retain stale numeric images when producing the full book.
    stale = []
    if first_page == 0 and last_page == page_count - 1:
        for path in output_dir.iterdir():
            if path.is_file() and path.stem.isdigit() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                if path.name not in expected_names:
                    stale.append(path.name)
        if stale:
            raise RuntimeError(
                "Stale numeric images exist outside current full PDF range: " + ", ".join(sorted(stale))
            )

    manifest = {
        "version": 1,
        "source_pdf": str(pdf_path.resolve()),
        "source_pdf_sha256": sha256_file(pdf_path),
        "source_pages": page_count,
        "first_page": first_page,
        "last_page": last_page,
        "dpi": dpi,
        "format": image_format,
        "jpeg_quality": jpeg_quality if image_format.lower() in {"jpg", "jpeg"} else None,
        "max_dim": max_dim,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pages": pages,
    }
    tmp = output_dir / ".manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, output_dir / "manifest.json")
    print(f"Converted {len(pages)} pages; manifest: {output_dir / 'manifest.json'}")


def main():
    parser = argparse.ArgumentParser(description="Convert PDF pages to OCR-friendly images.")
    parser.add_argument("input_pdf")
    parser.add_argument("output_dir")
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--start-index", type=int, default=0, help="Output filename index (default: 0).")
    parser.add_argument("--start", type=int, dest="legacy_start", default=None, help="Deprecated alias for --start-index.")
    parser.add_argument("--first-page", type=int, default=0, help="First zero-based PDF page to render.")
    parser.add_argument("--last-page", type=int, default=None, help="Last zero-based PDF page to render (inclusive).")
    parser.add_argument("--format", default="jpg", choices=["jpg", "jpeg", "png"])
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--max-dim", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    start_index = args.legacy_start if args.legacy_start is not None else args.start_index
    if not (1 <= args.jpeg_quality <= 100):
        parser.error("--jpeg-quality must be 1-100")
    convert(
        args.input_pdf,
        args.output_dir,
        dpi=args.dpi,
        start_index=start_index,
        image_format=args.format,
        max_dim=args.max_dim,
        first_page=args.first_page,
        last_page=args.last_page,
        jpeg_quality=args.jpeg_quality,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
