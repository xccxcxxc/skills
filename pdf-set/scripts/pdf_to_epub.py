#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resumable PDF→EPUB orchestration for pdf-set.

Heading classification remains an explicit gate because it is semantic. The
pipeline prepares rough Markdown, then exits until the user/agent marks it
ready with --headings-ready.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from table_utils import atomic_write_json, sha256_file
from validate_epub import validate_epub
from validate_ocr import validate_book

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent


def run(cmd):
    print("+", " ".join(str(x) for x in cmd))
    subprocess.run([str(x) for x in cmd], check=True)


def load_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "stages": {}}


def mark(state_path, state, stage, status, **extra):
    value = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
    value.update(extra)
    state.setdefault("stages", {})[stage] = value
    atomic_write_json(state_path, state)


def main():
    parser = argparse.ArgumentParser(description="Resumable pdf-set PDF→EPUB pipeline.")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--author", default=None)
    parser.add_argument("--headings-ready", action="store_true", help="Confirm merge-result/0.rough.md headings are classified.")
    parser.add_argument("--cover", default=None)
    parser.add_argument("--allow-markers", action="store_true")
    parser.add_argument("--skip-ocr", action="store_true")
    args = parser.parse_args()

    pdf = Path(args.pdf).resolve()
    work = Path(args.work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    state_path = work / "pipeline-state.json"
    state = load_state(state_path)
    state.update({"pdf": str(pdf), "pdf_sha256": sha256_file(pdf), "work_dir": str(work)})
    atomic_write_json(state_path, state)

    images = work / "images"
    ocr = work / "ocr-result"
    rough = work / "merge-result" / "0.rough.md"
    final_md = work / f"{work.name}.md"
    epub = work / f"{work.name}.epub"
    css = work / "assets" / "上标.css"
    cover = Path(args.cover).resolve() if args.cover else work / "assets" / "cover.jpg"
    work.joinpath("assets").mkdir(exist_ok=True)

    manifest = images / "manifest.json"
    if not manifest.is_file():
        run([sys.executable, HERE / "convert_pdf_to_images.py", pdf, images, "--dpi", "144", "--jpeg-quality", "92"])
    mark(state_path, state, "split", "ok", manifest=str(manifest))

    if not args.skip_ocr:
        cmd = [sys.executable, HERE / "ocr.py", "--base-dir", work]
        if args.profile:
            cmd += ["--profile", args.profile]
        run(cmd)
    result = validate_book(images, ocr, SKILL / "assets" / "ocr_prompt.md", allow_placeholders=True)
    if not result["ok"]:
        mark(state_path, state, "ocr", "failed", validation=result)
        raise RuntimeError("OCR validation failed; see pipeline-state.json")
    mark(state_path, state, "ocr", "ok", validation=result)

    # Mixed text+figure pages: crop figure regions and rewrite 🀄️page.jpg → 🀄️figures/page-n.jpg
    run([sys.executable, HERE / "crop_figures.py", "--base-dir", work])
    mark(state_path, state, "crop-figures", "ok", figures=str(work / "figures"))

    # Table cells must not contain expanded footnote bodies (① stays in cell; note after table).
    run([sys.executable, HERE / "extract_table_notes.py", "--base-dir", work])
    mark(state_path, state, "extract-table-notes", "ok")

    # Preserve an already classified rough file when resuming after the semantic gate.
    if args.headings_ready:
        if not rough.is_file():
            raise RuntimeError("--headings-ready requires existing merge-result/0.rough.md")
    else:
        rough.parent.mkdir(parents=True, exist_ok=True)
        run([sys.executable, HERE / "merge_rough.py", "--base-dir", work])
        mark(state_path, state, "merge", "ok", rough=str(rough))
        mark(state_path, state, "heading-gate", "pending", rough=str(rough))
        print("Heading classification required. Edit merge-result/0.rough.md, then rerun with --headings-ready.")
        return 2

    h1_count = sum(1 for line in rough.read_text(encoding="utf-8").splitlines() if line.startswith("# "))
    if h1_count < 1:
        raise RuntimeError("Heading gate failed: no H1 headings")
    mark(state_path, state, "heading-gate", "ok", h1_count=h1_count)

    run([sys.executable, HERE / "typeset_book.py", "--base-dir", work, "--input-file", rough, "--output-file", final_md])
    mark(state_path, state, "typeset", "ok", markdown=str(final_md))

    shutil.copy2(SKILL / "assets" / "上标.css", css)
    if not cover.is_file():
        shutil.copy2(images / "0.jpg", cover)
    title = args.title or work.name
    cmd = [
        "pandoc", final_md,
        "--from", "markdown+tex_math_dollars+tex_math_single_backslash",
        "--to", "epub3",
        "--css", css,
        "--epub-cover-image", cover,
        "--split-level=1",
        "--toc-depth=1",
        "--resource-path", f"{work}{os.pathsep}{images}{os.pathsep}{work / 'figures'}{os.pathsep}{work / 'assets'}",
        "--metadata", f"title={title}",
        "--output", epub,
    ]
    if args.author:
        cmd += ["--metadata", f"author={args.author}"]
    run(cmd)
    errors, warnings, metrics = validate_epub(epub, strict_markers=not args.allow_markers)
    if errors:
        mark(state_path, state, "epub", "failed", errors=errors, warnings=warnings, metrics=metrics)
        raise RuntimeError("EPUB validation failed:\n- " + "\n- ".join(errors))
    mark(state_path, state, "epub", "ok", epub=str(epub), warnings=warnings, metrics=metrics)
    print(f"EPUB ready: {epub}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"pipeline command failed: {exc}", file=sys.stderr)
        sys.exit(exc.returncode or 1)
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
