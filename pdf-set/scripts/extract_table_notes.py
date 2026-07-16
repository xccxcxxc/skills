#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract footnote bodies that were wrongly OCR'd into table cells.

Printed academic tables usually keep only ①②③ in cells; the note text sits
under the table. Models often expand those notes into the cell, which makes
GFM/HTML tables extremely tall/wide. This post-process:

1. Finds GFM and HTML tables
2. Pulls out <sup>【...】</sup> (and bare 【...】 in cells)
3. Leaves a compact marker (existing ①-⑳, or a newly assigned one)
4. Appends the note bodies immediately after the table

Idempotent for already-correct pages (no cell notes → no change).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from table_utils import atomic_write_text, find_raw_table_blocks, is_gfm_table_line

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
SUP_NOTE_RE = re.compile(r"<sup>\s*【\s*([\s\S]*?)\s*】\s*</sup>", re.I)
BARE_NOTE_RE = re.compile(r"【\s*([^【】]{2,400})\s*】")
CIRCLED_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]")
MARK_NUM_RE = re.compile(r"(?:</?sup\b[^>]*>|【|】|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]|\s)+", re.I)


def next_marker(used: set[str]) -> str:
    for ch in CIRCLED:
        if ch not in used:
            used.add(ch)
            return ch
    # Fallback if more than 20 notes on one page (rare).
    n = len(used) + 1
    mark = f"[{n}]"
    used.add(mark)
    return mark


def collect_used_markers(text: str) -> set[str]:
    return set(CIRCLED_RE.findall(text))


def normalize_note(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Keep sentence punctuation; only trim dangling separators.
    text = text.strip("；;")
    return text


def strip_notes_from_cell(cell: str, used: set[str], notes: list[tuple[str, str]]) -> str:
    """Return cell with note bodies removed; append (marker, note) to notes."""

    def repl_sup(match: re.Match) -> str:
        note = normalize_note(match.group(1))
        if not note:
            return ""
        # Prefer an existing circled marker immediately before the sup.
        prefix = cell[: match.start()]
        m = re.search(r"([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*$", prefix)
        if m:
            mark = m.group(1)
            used.add(mark)
        else:
            mark = next_marker(used)
            notes.append((mark, note))
            return mark
        notes.append((mark, note))
        return ""  # marker already present before sup

    out = SUP_NOTE_RE.sub(repl_sup, cell)

    # Bare 【...】 only when it looks like a definitional note, not data.
    def repl_bare(match: re.Match) -> str:
        note = normalize_note(match.group(1))
        if not note:
            return match.group(0)
        # Skip short parenthetical data like 【略】 / 【—】 that is not a footnote.
        if len(note) < 4 and not re.search(r"[指包括为了其任上现在分成]", note):
            return match.group(0)
        # Skip pure numbers / stats.
        if re.fullmatch(r"[\d.%％\-\s]+", note):
            return match.group(0)
        mark = next_marker(used)
        notes.append((mark, note))
        return mark

    # Only strip bare notes if they were not already handled as sup and still present.
    if "【" in out and "</sup>" not in out.lower():
        # Avoid eating already-good body notes outside tables: this runs only on cells.
        out = BARE_NOTE_RE.sub(repl_bare, out)

    # Collapse leftover empty sup tags / double spaces near markers.
    out = re.sub(r"<sup>\s*</sup>", "", out, flags=re.I)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return out


def process_gfm_table(block_lines: list[str], used: set[str]) -> tuple[list[str], list[tuple[str, str]]]:
    notes: list[tuple[str, str]] = []
    out_lines = []
    for line in block_lines:
        if re.match(r"^\s*\|?\s*:?-{2,}", line.strip()):
            out_lines.append(line)
            continue
        if not is_gfm_table_line(line):
            out_lines.append(line)
            continue
        raw = line.rstrip("\n")
        ends_with_pipe = raw.rstrip().endswith("|")
        starts_with_pipe = raw.lstrip().startswith("|")
        # Keep original pipe structure loosely via split.
        from table_utils import split_gfm_row

        cells = split_gfm_row(raw)
        new_cells = [strip_notes_from_cell(c, used, notes) for c in cells]
        rebuilt = " | ".join(new_cells)
        if starts_with_pipe:
            rebuilt = "| " + rebuilt
        if ends_with_pipe:
            rebuilt = rebuilt + " |"
        # Preserve leading indentation of original line.
        lead = re.match(r"^\s*", raw).group(0)
        out_lines.append(lead + rebuilt if not rebuilt.startswith(lead) else rebuilt)
    # Deduplicate identical notes sharing a marker order.
    return out_lines, notes


def process_html_table(block: str, used: set[str]) -> tuple[str, list[tuple[str, str]]]:
    notes: list[tuple[str, str]] = []

    def repl_cell(match: re.Match) -> str:
        open_tag, body, close = match.group(1), match.group(2), match.group(3)
        new_body = strip_notes_from_cell(body, used, notes)
        return f"{open_tag}{new_body}{close}"

    out = re.sub(
        r"(?is)(<t[dh]\b[^>]*>)([\s\S]*?)(</t[dh]>)",
        repl_cell,
        block,
    )
    return out, notes


def format_note_block(notes: list[tuple[str, str]]) -> str:
    if not notes:
        return ""
    # Deduplicate by marker+text, keep order.
    seen = set()
    lines = []
    for mark, note in notes:
        key = (mark, note)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"  <sup>【{mark}{note}】</sup>")
    return "\n".join(lines)


def insert_notes_after_table(text_after: str, note_block: str) -> str:
    """Insert note block after table; keep 资料来源 etc. after notes when adjacent."""
    if not note_block:
        return text_after
    # Skip immediate blank lines, then insert.
    m = re.match(r"(\n*)", text_after)
    blanks = m.group(1) if m else ""
    rest = text_after[len(blanks) :]
    return f"\n\n{note_block}\n\n{rest.lstrip('\n')}"


def process_markdown(text: str) -> tuple[str, int]:
    used = collect_used_markers(text)
    total_notes = 0
    pieces: list[str] = []
    cursor = 0

    # Build ordered table spans: HTML first via offsets, then GFM by lines mapped to offsets.
    spans: list[tuple[int, int, str, str]] = []  # start, end, kind, content
    for start, end, block in find_raw_table_blocks(text):
        spans.append((start, end, "html", block))

    # GFM tables by character offsets
    lines = text.splitlines(keepends=True)
    pos = 0
    line_starts = []
    for line in lines:
        line_starts.append(pos)
        pos += len(line)
    i = 0
    while i < len(lines):
        if is_gfm_table_line(lines[i]):
            j = i
            while j < len(lines) and is_gfm_table_line(lines[j]):
                j += 1
            if j - i >= 2:
                start = line_starts[i]
                end = line_starts[j - 1] + len(lines[j - 1])
                # Avoid overlapping HTML spans
                if not any(s <= start < e or s < end <= e for s, e, _, _ in spans):
                    spans.append((start, end, "gfm", "".join(lines[i:j])))
            i = j
        else:
            i += 1

    spans.sort(key=lambda x: x[0])
    # Drop nested/overlapping (keep first)
    filtered = []
    last_end = -1
    for span in spans:
        if span[0] >= last_end:
            filtered.append(span)
            last_end = span[1]

    for start, end, kind, block in filtered:
        pieces.append(text[cursor:start])
        if kind == "html":
            new_block, notes = process_html_table(block, used)
        else:
            block_lines = block.splitlines(keepends=True)
            # strip keepends for processor then restore
            plain = [ln.rstrip("\n") for ln in block_lines]
            new_lines, notes = process_gfm_table(plain, used)
            # restore newlines
            new_block = "\n".join(new_lines)
            if block.endswith("\n"):
                new_block += "\n"
        note_block = format_note_block(notes)
        total_notes += len(notes)
        pieces.append(new_block)
        # Insert notes after this table using the following text segment temporarily
        # Defer insertion into the next "gap" by prefixing next piece later.
        if note_block:
            # Peek remaining text to insert notes right after table.
            # We'll append note_block now, and consume leading newlines of following text later.
            pieces.append("\n\n" + note_block + "\n")
        cursor = end

    pieces.append(text[cursor:])
    out = "".join(pieces)
    # Normalize excessive blank lines (max 2).
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out, total_notes


def process_file(path: Path, *, dry_run: bool = False) -> dict:
    original = path.read_text(encoding="utf-8")
    updated, n = process_markdown(original)
    changed = updated != original
    if changed and not dry_run:
        atomic_write_text(path, updated if updated.endswith("\n") else updated + "\n")
    return {"path": str(path), "changed": changed, "notes_extracted": n}


def process_book(base_dir: Path, *, dry_run: bool = False) -> list[dict]:
    ocr = Path(base_dir) / "ocr-result"
    results = []
    if not ocr.is_dir():
        return results
    for path in sorted(ocr.glob("*.md"), key=lambda p: int(p.stem) if p.stem.isdigit() else 10**9):
        if not path.stem.isdigit():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "<sup>" not in text and "【" not in text:
            continue
        # Only process pages that still have notes inside tables.
        if not re.search(r"(?is)(\|[^\n]*<sup>\s*【|<t[dh][^>]*>[\s\S]*?<sup>\s*【)", text):
            # also bare 【 in table lines
            if not re.search(r"\|[^\n]*【", text):
                continue
        results.append(process_file(path, dry_run=dry_run))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract footnote bodies from table cells.")
    parser.add_argument("--base-dir", type=Path, help="Book directory containing ocr-result/")
    parser.add_argument("--input-file", type=Path, help="Single markdown file")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.input_file:
        info = process_file(args.input_file, dry_run=args.dry_run)
        print(info)
        return 0
    if not args.base_dir:
        parser.error("provide --base-dir or --input-file")
    results = process_book(args.base_dir, dry_run=args.dry_run)
    changed = sum(1 for r in results if r["changed"])
    notes = sum(r["notes_extracted"] for r in results)
    print(f"Processed {len(results)} page(s); updated {changed}; notes extracted {notes}.")
    for r in results:
        if r["changed"] or r["notes_extracted"]:
            print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
