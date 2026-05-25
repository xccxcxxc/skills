#!/usr/bin/env python3
"""Merge translate-result chunks into one comparison markdown file."""

from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path

DEFAULT_TRANSLATE_RESULT_DIRNAME = "translate-result"
OUTPUT_SUFFIX = "(对照翻译).md"
HEADING_RE = re.compile(r"^(\s{0,3})(#{1,6})\s+(.+?)\s*$")
QUOTE_RE = re.compile(r"^(\s*)>\s?(.*)$")


def read_single_path(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            value = line.strip()
            if value:
                return value
    return ""


def collect_ordered_files(translate_result_dir: Path) -> list[Path]:
    numbered_files: list[tuple[int, str, Path]] = []
    pattern = re.compile(r"^(\d+)")

    for item in translate_result_dir.iterdir():
        if not item.is_file() or item.suffix.lower() != ".md":
            continue
        match = pattern.match(item.stem)
        if not match:
            continue
        numbered_files.append((int(match.group(1)), item.name, item))

    numbered_files.sort(key=lambda x: (x[0], x[1]))
    return [item[2] for item in numbered_files]


def merge_files_in_order(files: list[Path]) -> str:
    parts: list[str] = []
    last_index = len(files) - 1

    for idx, path in enumerate(files):
        content = path.read_text(encoding="utf-8")
        parts.append(content)
        if idx == last_index:
            continue
        if not content.endswith("\n"):
            parts.append("\n")

    return "".join(parts)


def swap_heading_and_translation_quote(text: str) -> str:
    """For markdown headings, promote the translated quote to heading and quote the source heading."""
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        return text

    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if i + 1 >= len(lines):
            out.append(line)
            break

        next_line = lines[i + 1]
        line_body = line.rstrip("\r\n")
        next_body = next_line.rstrip("\r\n")
        line_nl = line[len(line_body):]
        next_nl = next_line[len(next_body):]

        heading_match = HEADING_RE.match(line_body)
        quote_match = QUOTE_RE.match(next_body)

        if heading_match and quote_match:
            indent, hashes, source_title = heading_match.groups()
            quote_indent, translated_text = quote_match.groups()

            # Keep heading level, but use translated text as heading content.
            out.append(f"{indent}{hashes} {translated_text}{line_nl}")
            # Quote the original heading text as source line.
            out.append(f"{quote_indent}> {source_title}{next_nl}")
            i += 2
            continue

        out.append(line)
        i += 1

    return "".join(out)


def add_blank_line_between_source_and_translation(text: str) -> str:
    """Insert one blank line before a translation quote line after source text."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return text

    out: list[str] = [lines[0]]
    for line in lines[1:]:
        previous_line = out[-1]
        previous = previous_line.rstrip("\r\n")
        current = line.lstrip()
        is_translation = current.startswith(">")
        previous_is_quote = previous.lstrip().startswith(">")

        if is_translation and previous and not previous_is_quote:
            if not previous_line.endswith(("\n", "\r")):
                out[-1] = previous_line + "\n"
            out.append("\n")

        out.append(line)

    return "".join(out)


def add_blank_line_around_dividers(text: str) -> str:
    """Ensure divider lines (`---`) have one blank line before and after."""
    lines = text.splitlines()
    if not lines:
        return text

    out: list[str] = []
    total = len(lines)

    for idx, line in enumerate(lines):
        is_divider = line.strip() == "---"
        if not is_divider:
            out.append(line)
            continue

        if out and out[-1] != "":
            out.append("")
        out.append(line)
        if idx + 1 >= total or lines[idx + 1] != "":
            out.append("")

    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result


def maybe_backup(output_file: Path, no_backup: bool) -> None:
    if no_backup or not output_file.exists():
        return
    backup_file = output_file.with_suffix(output_file.suffix + ".bak")
    shutil.copy2(output_file, backup_file)
    print(f"Backup created: {backup_file}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Merge numbered markdown files in translate-result/ by numeric order "
            "and write <book-name>(对照翻译).md in base-dir."
        )
    )
    parser.add_argument(
        "--base-dir",
        default=os.getcwd(),
        help="Book root directory (default: current directory).",
    )
    parser.add_argument(
        "--base-dir-from",
        default=None,
        help="UTF-8 text file containing base directory (first non-empty line).",
    )
    parser.add_argument(
        "--book-name",
        default=None,
        help="Book name (defaults to base directory name).",
    )
    parser.add_argument(
        "--book-name-from",
        default=None,
        help="UTF-8 text file containing book name (first non-empty line).",
    )
    parser.add_argument(
        "--translate-result-dir",
        default=None,
        help=f"Input directory (default: <base-dir>/{DEFAULT_TRANSLATE_RESULT_DIRNAME}).",
    )
    parser.add_argument(
        "--translate-result-dir-from",
        default=None,
        help="UTF-8 text file containing input directory (first non-empty line).",
    )
    parser.add_argument(
        "--output-file",
        default=None,
        help="Output file path (default: <base-dir>/<book-name>(对照翻译).md).",
    )
    parser.add_argument(
        "--output-file-from",
        default=None,
        help="UTF-8 text file containing output file path (first non-empty line).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview order and output path without writing file.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create .bak backup when output file already exists.",
    )
    args = parser.parse_args()

    base_dir = args.base_dir
    if args.base_dir_from:
        value = read_single_path(args.base_dir_from)
        if value:
            base_dir = value
    base_dir_path = Path(base_dir).expanduser().resolve()

    book_name = args.book_name or base_dir_path.name
    if args.book_name_from:
        value = read_single_path(args.book_name_from)
        if value:
            book_name = value

    translate_result_dir = (
        Path(args.translate_result_dir).expanduser().resolve()
        if args.translate_result_dir
        else base_dir_path / DEFAULT_TRANSLATE_RESULT_DIRNAME
    )
    if args.translate_result_dir_from:
        value = read_single_path(args.translate_result_dir_from)
        if value:
            translate_result_dir = Path(value).expanduser().resolve()

    output_file = (
        Path(args.output_file).expanduser().resolve()
        if args.output_file
        else base_dir_path / f"{book_name}{OUTPUT_SUFFIX}"
    )
    if args.output_file_from:
        value = read_single_path(args.output_file_from)
        if value:
            output_file = Path(value).expanduser().resolve()

    if not translate_result_dir.is_dir():
        raise FileNotFoundError(f"translate-result directory not found: {translate_result_dir}")

    ordered_files = collect_ordered_files(translate_result_dir)
    if not ordered_files:
        raise FileNotFoundError(
            f"No numbered .md files found in: {translate_result_dir}"
        )

    print(f"Input directory: {translate_result_dir}")
    print(f"Output file: {output_file}")
    print("Merge order:")
    for path in ordered_files:
        print(f"- {path.name}")

    if args.dry_run:
        print("Dry run enabled. No file written.")
        return 0

    merged_content = merge_files_in_order(ordered_files)
    merged_content = swap_heading_and_translation_quote(merged_content)
    merged_content = add_blank_line_between_source_and_translation(merged_content)
    merged_content = add_blank_line_around_dividers(merged_content)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    maybe_backup(output_file, args.no_backup)
    output_file.write_text(merged_content, encoding="utf-8")
    print(f"Merged {len(ordered_files)} files.")
    print(f"Wrote: {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
