#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge validated numeric OCR pages into one rough Markdown document."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from merge_tables import merge_page_sequence
from table_utils import atomic_write_json, atomic_write_text, validate_page_markdown


def clean_page_content(content):
    lines, previous_blank = [], False
    for line in content.splitlines():
        if "🈳" in line:
            continue
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        lines.append(line)
        previous_blank = is_blank
    return "\n".join(lines).strip()


def collect_numeric_pages(input_dir: Path):
    pages = []
    for path in input_dir.iterdir() if input_dir.is_dir() else []:
        if path.is_file() and path.suffix.lower() == ".md" and path.stem.isdigit():
            pages.append(path)
    return sorted(pages, key=lambda p: int(p.stem))


def check_contiguous(pages):
    if not pages:
        return ["no numeric OCR pages found"]
    nums = [int(p.stem) for p in pages]
    expected = list(range(nums[0], nums[-1] + 1))
    missing = sorted(set(expected) - set(nums))
    errors = []
    if missing:
        errors.append(f"missing page indexes: {missing}")
    return errors


def merge_ocr_results(input_dir, output_file, *, allow_missing=False, merge_tables=True):
    input_dir, output_file = Path(input_dir), Path(output_file)
    pages = collect_numeric_pages(input_dir)
    errors = check_contiguous(pages)
    fail_files = sorted(input_dir.glob("*.fail.json")) if input_dir.is_dir() else []
    if fail_files:
        errors.append("failed pages present: " + ", ".join(p.name for p in fail_files))
    page_data = []
    invalid = {}
    for path in pages:
        text = path.read_text(encoding="utf-8", errors="replace")
        page_errors = validate_page_markdown(text, allow_placeholders=True)
        if page_errors:
            invalid[path.name] = page_errors
        page_data.append((path.name, clean_page_content(text)))
    if invalid:
        errors.extend(f"{name}: {'; '.join(values)}" for name, values in invalid.items())
    if errors and not allow_missing:
        raise RuntimeError("OCR merge gate failed:\n- " + "\n- ".join(errors))

    table_report = []
    if merge_tables:
        page_data, table_report = merge_page_sequence(page_data)
    all_content = [content for _, content in page_data if content]
    merged_content = "\n\n".join(all_content).rstrip() + "\n"
    atomic_write_text(output_file, merged_content)
    report_path = output_file.with_suffix(output_file.suffix + ".report.json")
    atomic_write_json(
        report_path,
        {
            "input_pages": len(pages),
            "first_page": int(pages[0].stem) if pages else None,
            "last_page": int(pages[-1].stem) if pages else None,
            "warnings": errors if allow_missing else [],
            "continued_tables_merged": table_report,
        },
    )
    print(f"Successfully merged {len(pages)} validated pages into {output_file}")
    print(f"Continued tables merged: {len(table_report)}")
    return output_file


def read_single_path(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            value = line.strip()
            if value:
                return value
    return ""


def main():
    parser = argparse.ArgumentParser(description="Merge validated numeric OCR Markdown pages.")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--base-dir-from", default=None)
    parser.add_argument("--input-dir", default=None)
    parser.add_argument("--input-dir-from", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--output-dir-from", default=None)
    parser.add_argument("--output-file", default=None)
    parser.add_argument("--output-file-from", default=None)
    parser.add_argument("--allow-missing", action="store_true", help="Continue with warnings (not recommended).")
    parser.add_argument("--no-merge-continued-tables", action="store_true")
    args = parser.parse_args()

    base_dir = Path(read_single_path(args.base_dir_from) if args.base_dir_from else args.base_dir)
    input_dir = Path(read_single_path(args.input_dir_from) if args.input_dir_from else (args.input_dir or base_dir / "ocr-result"))
    output_dir = Path(read_single_path(args.output_dir_from) if args.output_dir_from else (args.output_dir or base_dir / "merge-result"))
    output_value = read_single_path(args.output_file_from) if args.output_file_from else (args.output_file or "0.rough.md")
    output_file = Path(output_value)
    if not output_file.is_absolute():
        output_file = output_dir / output_file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    merge_ocr_results(
        input_dir,
        output_file,
        allow_missing=args.allow_missing,
        merge_tables=not args.no_merge_continued_tables,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
