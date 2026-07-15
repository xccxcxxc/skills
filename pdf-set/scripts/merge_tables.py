# -*- coding: utf-8 -*-
"""Conservatively merge continued tables across adjacent OCR pages."""
from __future__ import annotations

import re

from table_utils import find_raw_table_blocks, iter_gfm_table_blocks, split_gfm_row


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _html_header_signature(block: str):
    match = re.search(r"(?is)<thead\b[^>]*>(.*?)</thead>", block)
    return _compact(match.group(1)) if match else None


def _html_tbody(block: str):
    match = re.search(r"(?is)<tbody\b[^>]*>(.*?)</tbody>", block)
    return match.group(1).strip() if match else None


def _replace_tbody(block: str, body: str):
    return re.sub(
        r"(?is)(<tbody\b[^>]*>).*?(</tbody>)",
        lambda m: m.group(1) + "\n" + body.strip() + "\n" + m.group(2),
        block,
        count=1,
    )


def _edge_html_table(text: str, *, first: bool):
    matches = list(find_raw_table_blocks(text))
    if not matches:
        return None
    item = matches[0] if first else matches[-1]
    start, end, block = item
    outside = text[:start] if first else text[end:]
    # Continuation must begin/end at page edge; allow a short explicit "续表" title.
    stripped = outside.strip()
    if not stripped:
        return item, ""
    if first and len(stripped) <= 80 and re.search(r"续表|表\s*\d.*续|（续）|\(续\)", stripped):
        return item, outside
    return None


def merge_adjacent_html_tables(previous: str, current: str):
    left_info = _edge_html_table(previous, first=False)
    right_info = _edge_html_table(current, first=True)
    if not left_info or not right_info:
        return None
    (ls, le, lb), _ = left_info
    (rs, re_, rb), prefix = right_info
    lsig, rsig = _html_header_signature(lb), _html_header_signature(rb)
    lbody, rbody = _html_tbody(lb), _html_tbody(rb)
    if not lsig or lsig != rsig or lbody is None or rbody is None:
        return None
    merged_block = _replace_tbody(lb, lbody + "\n" + rbody)
    new_previous = previous[:ls] + merged_block + previous[le:]
    # Drop only the recognized continuation title before the duplicate table.
    new_current = current[re_:] if prefix else current[re_:]
    return new_previous.rstrip(), new_current.lstrip(), "html"


def _gfm_edge_block(text: str, *, first: bool):
    blocks = list(iter_gfm_table_blocks(text))
    if not blocks:
        return None
    line_list = text.splitlines(keepends=True)
    line_no, rows = blocks[0] if first else blocks[-1]
    start_idx = line_no - 1
    end_idx = start_idx + len(rows)
    prefix = "".join(line_list[:start_idx])
    suffix = "".join(line_list[end_idx:])
    outside = prefix if first else suffix
    stripped = outside.strip()
    if not stripped:
        return start_idx, end_idx, rows, line_list
    if first and len(stripped) <= 80 and re.search(r"续表|表\s*\d.*续|（续）|\(续\)", stripped):
        return start_idx, end_idx, rows, line_list
    return None


def _gfm_signature(rows):
    if len(rows) < 2:
        return None
    return tuple(_compact(cell) for cell in split_gfm_row(rows[0])), tuple(
        _compact(cell) for cell in split_gfm_row(rows[1])
    )


def merge_adjacent_gfm_tables(previous: str, current: str):
    left = _gfm_edge_block(previous, first=False)
    right = _gfm_edge_block(current, first=True)
    if not left or not right:
        return None
    lstart, lend, lrows, llines = left
    rstart, rend, rrows, rlines = right
    if _gfm_signature(lrows) != _gfm_signature(rrows):
        return None
    if len(lrows) < 2 or len(rrows) < 2:
        return None
    merged_rows = [row.rstrip("\r\n") for row in lrows + rrows[2:]]
    new_previous = "".join(llines[:lstart]) + "\n".join(merged_rows) + "\n" + "".join(llines[lend:])
    new_current = "".join(rlines[rend:])
    return new_previous.rstrip(), new_current.lstrip(), "gfm"


def merge_adjacent_footnote(previous: str, current: str):
    """Join an explicit leading ⬆️ continuation to the prior page's last <sup>."""
    continuation = re.match(r"(?is)^\s*<sup>\s*⬆️\s*(.*?)</sup>\s*", current)
    if not continuation:
        return None
    notes = list(re.finditer(r"(?is)<sup>(.*?)</sup>", previous))
    if not notes:
        return None
    last = notes[-1]
    left = re.sub(r"\s*⬇️\s*", "", last.group(1).rstrip())
    right = re.sub(r"^\s*⬆️\s*", "", continuation.group(1).lstrip())
    # OCR footnote containers often close 【】 on both page fragments. Keep one pair.
    if left.startswith("【") and left.endswith("】"):
        left = left[:-1]
        if right.startswith("【"):
            right = right[1:]
        if not right.endswith("】"):
            right += "】"
    joined = f"<sup>{left}{right}</sup>"
    new_previous = previous[:last.start()] + joined + previous[last.end():]
    new_current = current[continuation.end():]
    return new_previous.rstrip(), new_current.lstrip(), "footnote"


def merge_page_sequence(pages: list[tuple[str, str]]):
    """Return adjusted pages and a report; merge only explicit/safe continuations."""
    adjusted = [[name, text] for name, text in pages]
    report = []
    for idx in range(1, len(adjusted)):
        prev_name, previous = adjusted[idx - 1]
        cur_name, current = adjusted[idx]
        footnote = merge_adjacent_footnote(previous, current)
        if footnote is not None:
            previous, current, kind = footnote
            adjusted[idx - 1][1], adjusted[idx][1] = previous, current
            report.append({"from": prev_name, "to": cur_name, "kind": kind})
        result = merge_adjacent_html_tables(previous, current)
        if result is None:
            result = merge_adjacent_gfm_tables(previous, current)
        if result is None:
            continue
        adjusted[idx - 1][1], adjusted[idx][1], kind = result
        report.append({"from": prev_name, "to": cur_name, "kind": kind})
    return [(name, text) for name, text in adjusted], report
