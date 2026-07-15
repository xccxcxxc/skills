# -*- coding: utf-8 -*-
"""Shared validation and atomic I/O helpers for pdf-set.

Only the standard library is used so OCR/page validation works in minimal
minis/Linux environments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Iterable

ALLOWED_TABLE_TAGS = {"div", "table", "thead", "tbody", "tr", "th", "td", "sup"}
ALLOWED_TABLE_CLASSES = {"table-wrap", "table-dense"}
UNRESOLVED_MARKERS = ("🀄", "🈳", "__PROHIBITED_CONTENT__")


def sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: os.PathLike | str) -> str:
    h = sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: os.PathLike | str, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: os.PathLike | str, text: str) -> None:
    _atomic_write(path, text.encode("utf-8"))


def atomic_write_json(path: os.PathLike | str, value: object) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, payload)


def read_json(path: os.PathLike | str, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def numeric_stem(path_or_name: os.PathLike | str):
    stem = Path(path_or_name).stem
    return int(stem) if stem.isdigit() else None


def natural_path_key(path_or_name: os.PathLike | str):
    name = Path(path_or_name).name
    stem = Path(name).stem
    if stem.isdigit():
        return (0, int(stem), name.lower())
    return (1, name.lower(), name.lower())


def split_gfm_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith(r"\|"):
        s = s[:-1]
    # A pipe escaped by an odd number of backslashes stays inside the cell.
    cells, buf = [], []
    for i, ch in enumerate(s):
        if ch == "|":
            backslashes = 0
            j = i - 1
            while j >= 0 and s[j] == "\\":
                backslashes += 1
                j -= 1
            if backslashes % 2 == 0:
                cells.append("".join(buf).strip())
                buf = []
                continue
        buf.append(ch)
    cells.append("".join(buf).strip())
    return cells


def is_gfm_table_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def iter_gfm_table_blocks(text: str):
    lines = text.splitlines()
    start = None
    block: list[str] = []
    for idx, line in enumerate(lines + [""], start=1):
        if is_gfm_table_line(line):
            if start is None:
                start = idx
            block.append(line)
        elif block:
            yield start, block
            start, block = None, []


def _is_separator_row(cells: Iterable[str]) -> bool:
    cells = list(cells)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in cells)


@dataclass
class ParsedTable:
    rows: list[list[tuple[int, int]]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def validate_grid(self) -> list[str]:
        if not self.rows:
            return ["HTML table has no rows"]
        occupied: dict[int, set[int]] = {}
        row_widths: list[int] = []
        for row_idx, cells in enumerate(self.rows):
            used = set(occupied.get(row_idx, set()))
            col = 0
            for rowspan, colspan in cells:
                while col in used:
                    col += 1
                for rr in range(row_idx, row_idx + rowspan):
                    row_used = occupied.setdefault(rr, set())
                    for cc in range(col, col + colspan):
                        if cc in row_used:
                            self.errors.append(
                                f"HTML table cell overlap at row {row_idx + 1}, column {cc + 1}"
                            )
                        row_used.add(cc)
                used.update(range(col, col + colspan))
                col += colspan
            row_widths.append(max(used) + 1 if used else 0)
        width = max(row_widths + [max((max(v) + 1 for v in occupied.values() if v), default=0)])
        for idx, row_width in enumerate(row_widths, start=1):
            effective = max(occupied.get(idx - 1, {-1})) + 1
            if effective != width:
                self.errors.append(
                    f"HTML table row {idx} has effective width {effective}, expected {width}"
                )
        return self.errors


class TableHTMLValidator(HTMLParser):
    def __init__(self, *, canonicalize: bool = False):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.tables: list[ParsedTable] = []
        self.current: ParsedTable | None = None
        self.current_row: list[tuple[int, int]] | None = None
        self.errors: list[str] = []
        self.canonicalize = canonicalize
        self.output: list[str] = []

    def _attrs(self, tag: str, attrs):
        clean = []
        for key, value in attrs:
            key = (key or "").lower()
            value = value or ""
            if key == "class":
                classes = value.split()
                bad = [c for c in classes if c not in ALLOWED_TABLE_CLASSES]
                if bad:
                    self.errors.append(f"disallowed class on <{tag}>: {' '.join(bad)}")
                keep = [c for c in classes if c in ALLOWED_TABLE_CLASSES]
                if keep:
                    clean.append(("class", " ".join(keep)))
            elif key in {"rowspan", "colspan"} and tag in {"th", "td"}:
                if not re.fullmatch(r"[1-9]\d{0,2}", value):
                    self.errors.append(f"invalid {key}={value!r} on <{tag}>")
                else:
                    clean.append((key, value))
            else:
                self.errors.append(f"disallowed attribute {key!r} on <{tag}>")
        return clean

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in ALLOWED_TABLE_TAGS:
            self.errors.append(f"disallowed HTML tag <{tag}> in table block")
            return
        attrs = self._attrs(tag, attrs)
        self.stack.append(tag)
        if tag == "table":
            if self.current is not None:
                self.errors.append("nested <table> is not allowed")
            self.current = ParsedTable()
            self.tables.append(self.current)
        elif tag == "tr":
            if self.current is None:
                self.errors.append("<tr> outside <table>")
            if self.current_row is not None:
                self.errors.append("nested <tr>")
            self.current_row = []
        elif tag in {"th", "td"}:
            if self.current_row is None:
                self.errors.append(f"<{tag}> outside <tr>")
            else:
                amap = dict(attrs)
                self.current_row.append((int(amap.get("rowspan", 1)), int(amap.get("colspan", 1))))
        if self.canonicalize:
            attrs_text = "".join(f' {k}="{escape(v, quote=True)}"' for k, v in attrs)
            self.output.append(f"<{tag}{attrs_text}>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag not in ALLOWED_TABLE_TAGS:
            self.errors.append(f"disallowed closing tag </{tag}> in table block")
            return
        if not self.stack:
            self.errors.append(f"unexpected closing tag </{tag}>")
        elif self.stack[-1] != tag:
            self.errors.append(f"mismatched closing tag </{tag}>; expected </{self.stack[-1]}>")
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.stack.pop()
                if self.stack:
                    self.stack.pop()
        else:
            self.stack.pop()
        if tag == "tr":
            if self.current is not None and self.current_row is not None:
                self.current.rows.append(self.current_row)
            self.current_row = None
        elif tag == "table":
            if self.current is not None:
                self.current.validate_grid()
                self.errors.extend(self.current.errors)
            self.current = None
        if self.canonicalize:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if self.canonicalize:
            self.output.append(escape(data, quote=False))

    def handle_entityref(self, name):
        if self.canonicalize:
            self.output.append(f"&{name};")

    def handle_charref(self, name):
        if self.canonicalize:
            self.output.append(f"&#{name};")

    def handle_comment(self, data):
        # Comments inside generated tables are unnecessary and are dropped.
        return

    def close(self):
        super().close()
        if self.stack:
            self.errors.append("unclosed HTML tags: " + ", ".join(self.stack))


def find_raw_table_blocks(text: str):
    """Yield (start_offset, end_offset, block) for table/table-wrap raw HTML."""
    pattern = re.compile(
        r"(?is)(?:<div\b[^>]*class=[\"'][^\"']*\btable-wrap\b[^\"']*[\"'][^>]*>\s*)?"
        r"<table\b.*?</table>\s*(?:</div>)?"
    )
    for match in pattern.finditer(text):
        yield match.start(), match.end(), match.group(0)


def validate_html_table_block(block: str) -> list[str]:
    parser = TableHTMLValidator()
    try:
        parser.feed(block)
        parser.close()
    except Exception as exc:
        parser.errors.append(f"HTML parser error: {exc}")
    if not parser.tables:
        parser.errors.append("no <table> found in raw HTML block")
    return parser.errors


def sanitize_html_table_block(block: str) -> str:
    errors = validate_html_table_block(block)
    if errors:
        raise ValueError("; ".join(errors))
    parser = TableHTMLValidator(canonicalize=True)
    parser.feed(block)
    parser.close()
    if parser.errors:
        raise ValueError("; ".join(parser.errors))
    return "".join(parser.output)


def validate_page_markdown(text: str, *, allow_placeholders: bool = True) -> list[str]:
    errors: list[str] = []
    if not text or not text.strip():
        return ["empty OCR output"]
    if text.count("```") % 2:
        errors.append("unbalanced fenced code block")

    # A table opener that was not captured by a complete table block is malformed.
    complete_ranges = [(a, b) for a, b, _ in find_raw_table_blocks(text)]
    for match in re.finditer(r"(?i)<table\b", text):
        if not any(a <= match.start() < b for a, b in complete_ranges):
            line = text.count("\n", 0, match.start()) + 1
            errors.append(f"unclosed or malformed HTML table at line {line}")

    for start, _, block in find_raw_table_blocks(text):
        line = text.count("\n", 0, start) + 1
        for err in validate_html_table_block(block):
            errors.append(f"line {line}: {err}")

    for line_no, lines in iter_gfm_table_blocks(text):
        rows = [split_gfm_row(line) for line in lines]
        counts = [len(row) for row in rows]
        if len(rows) < 2:
            errors.append(f"GFM table at line {line_no} has fewer than 2 rows")
            continue
        if len(set(counts)) != 1:
            errors.append(f"GFM table at line {line_no} has inconsistent columns: {counts}")
        if not _is_separator_row(rows[1]):
            errors.append(f"GFM table at line {line_no} has no valid separator row")

    # Disallow raw active HTML outside approved table blocks/sup tags.
    masked = list(text)
    for start, end in complete_ranges:
        masked[start:end] = " " * (end - start)
    remainder = "".join(masked)
    remainder = re.sub(r"(?is)</?sup\b[^>]*>", "", remainder)
    disallowed = re.search(r"(?is)<\s*(script|iframe|object|embed|style|link|meta)\b|\son\w+\s*=", remainder)
    if disallowed:
        errors.append("disallowed active HTML outside table block")

    if not allow_placeholders:
        for marker in UNRESOLVED_MARKERS:
            if marker in text:
                errors.append(f"unresolved marker: {marker}")
    return errors


def page_meta_path(output_dir: os.PathLike | str, page_stem: str) -> Path:
    return Path(output_dir) / f"{page_stem}.meta.json"


def page_is_valid(
    image_path: os.PathLike | str,
    md_path: os.PathLike | str,
    meta_path: os.PathLike | str,
    *,
    prompt_hash: str,
    trust_existing: bool = False,
) -> bool:
    md_path, meta_path = Path(md_path), Path(meta_path)
    if not md_path.is_file() or md_path.stat().st_size <= 0:
        return False
    if trust_existing and not meta_path.exists():
        return not validate_page_markdown(md_path.read_text(encoding="utf-8", errors="replace"))
    meta = read_json(meta_path, {}) or {}
    if meta.get("status") != "ok" or meta.get("validated") is not True:
        return False
    try:
        if meta.get("image_sha256") != sha256_file(image_path):
            return False
    except OSError:
        return False
    if meta.get("prompt_sha256") != prompt_hash:
        return False
    if meta.get("output_sha256") != sha256_file(md_path):
        return False
    return not validate_page_markdown(md_path.read_text(encoding="utf-8", errors="replace"))
