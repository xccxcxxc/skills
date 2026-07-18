# -*- coding: utf-8 -*-
import argparse
import os
import re
import tempfile
import unicodedata


DEFAULT_MERGE_DIRNAME = "merge-result"
DEFAULT_TYPESET_DIRNAME = "typeset-result"
DEFAULT_INPUT_FILENAME = "0.rough.md"

TOKEN_MAP = {
    "and": "和",
    "or": "或",
    "he": "他",
    "of": "的",
}
TOKEN_RE = re.compile(r"\b(and|or|he|of)\b", re.IGNORECASE)
SPACE_CHARS = {" ", "\t", "\u3000"}


def natural_number(filename):
    match = re.match(r"^(\d+)\.", filename)
    return int(match.group(1)) if match else 10**9


def numbered_md_files(directory):
    if not os.path.isdir(directory):
        return []
    return sorted(
        [
            name
            for name in os.listdir(directory)
            if re.match(r"^[1-9]\d*\..*\.md$", name)
        ],
        key=natural_number,
    )


def remove_numbered_md(directory):
    for name in numbered_md_files(directory):
        os.remove(os.path.join(directory, name))


def safe_filename(title):
    title = re.sub(r'[\\/*?:"<>|]', "_", title).strip()
    return title or "untitled"


def split_by_h1(input_file, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    remove_numbered_md(output_dir)

    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    parts = re.split(r"^#\s+", content, flags=re.MULTILINE)
    if len(parts) <= 1:
        raise RuntimeError(f"No H1 headings found in {input_file}")

    preamble = parts[0]
    created = []
    for index, section in enumerate(parts[1:], start=1):
        lines = section.split("\n", 1)
        title = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ""
        filename = f"{index}.{safe_filename(title)}.md"
        path = os.path.join(output_dir, filename)
        section_text = f"# {title}\n{body}".rstrip() + "\n"
        if index == 1 and preamble.strip():
            section_text = preamble.rstrip() + "\n\n" + section_text
        with open(path, "w", encoding="utf-8") as f:
            f.write(section_text)
        created.append(filename)
    return created


# Printed page numbers from scan footers/headers, e.g. ·12· •6• ・64・ · 1 ·
_PAGE_MARK_INLINE_RE = re.compile(
    r"[·•‧・．][ \t\u3000]*[0-9０-９]{1,4}[ \t\u3000]*[·•‧・．]"
)
_PAGE_MARK_LINE_RE = re.compile(
    r"^[ \t\u3000]*[·•‧・．][ \t\u3000]*[0-9０-９]{1,4}"
    r"[ \t\u3000]*[·•‧・．][ \t\u3000]*$"
)


def strip_page_number_markers(text: str) -> str:
    """Remove scan page marks like ·12· / •6•; drop marker-only lines; collapse blanks."""
    lines = text.splitlines()
    kept = []
    for line in lines:
        stripped = line.strip()
        if _PAGE_MARK_LINE_RE.match(stripped):
            continue
        cleaned = _PAGE_MARK_INLINE_RE.sub("", line)
        lead_m = re.match(r"^[ \t\u3000]*", cleaned)
        lead = lead_m.group(0) if lead_m else ""
        body = cleaned[len(lead) :]
        body = re.sub(r"[ \t\u3000]{2,}", " ", body)
        cleaned = lead + body
        if cleaned.strip() == "":
            if stripped == "":
                kept.append("")
            continue
        kept.append(cleaned.rstrip())

    text2 = "\n".join(kept)
    text2 = re.sub(r"\n{3,}", "\n\n", text2)
    return text2


def cleanup_text(text):
    """Normalize footnotes; strip scan page numbers; never delete repeated OCR prose."""
    def clean_footnote(match):
        return "".join(line.strip() for line in match.group(0).splitlines())

    text = re.compile(r"<sup>.*?</sup>", re.DOTALL).sub(clean_footnote, text)
    text = strip_page_number_markers(text)
    return text


def is_halfwidth_char(ch):
    if not ch or ch.isspace():
        return False
    return unicodedata.east_asian_width(ch) not in ("F", "W")


def is_md_table_line(text):
    """Detect GFM pipe-table rows / separator rows so layout won't glue them."""
    s = (text or "").strip()
    if not s or s.count("|") < 1:
        return False
    if s.startswith("|") and s.count("|") >= 2:
        return True
    if re.match(r"^:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+$", s):
        return True
    if s.count("|") >= 2 and not re.search(r"[\u4e00-\u9fff]{8,}", s.split("|")[0]):
        cells = [c.strip() for c in s.split("|")]
        if all(len(c) <= 40 for c in cells if c):
            return True
    return False


def is_html_table_markup_line(text):
    s = (text or "").strip().lower()
    if not s:
        return False
    return bool(
        re.search(
            r"</?(?:table\b|thead\b|tbody\b|tr\b|th\b|td\b)|"
            r"<div\b[^>]*class\s*=\s*[\"'][^\"']*\btable-wrap\b|"
            r"</div\s*>",
            s,
        )
    )


def process_layout(input_path, output_path, is_index=False):
    with open(input_path, "r", encoding="utf-8") as f:
        source = f.read()

    front_matter = ""
    match = re.match(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", source, flags=re.DOTALL)
    if match:
        front_matter = match.group(0).rstrip()
        source = source[match.end():]
    lines = source.splitlines()

    blocks = []
    current_block = ""
    prev_block_is_heading = False
    in_pipe_table = False
    in_html_table = False

    def flush_block():
        nonlocal current_block, prev_block_is_heading, in_pipe_table, in_html_table
        if current_block:
            blocks.append(current_block.rstrip())
            prev_block_is_heading = current_block.lstrip().startswith("#")
        current_block = ""
        in_pipe_table = False
        in_html_table = False

    def append_raw(line):
        nonlocal current_block
        if current_block:
            current_block = current_block.rstrip() + "\n" + line
        else:
            current_block = line

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Drop scan page-number lines early so they don't create empty blocks.
        if _PAGE_MARK_LINE_RE.match(stripped):
            continue
        if _PAGE_MARK_INLINE_RE.fullmatch(stripped):
            continue
        # Strip inline page marks before layout decisions.
        if _PAGE_MARK_INLINE_RE.search(line):
            lead_m = re.match(r"^[ \t\u3000]*", line)
            lead = lead_m.group(0) if lead_m else ""
            body = _PAGE_MARK_INLINE_RE.sub("", line[len(lead) :])
            body = re.sub(r"[ \t\u3000]{2,}", " ", body).strip()
            if not body:
                continue
            line = lead + body if (lead.startswith("  ") or lead.startswith("\u3000")) else (
                ("  " + body) if line.startswith("  ") else body
            )
            stripped = line.strip()

        starts_html = bool(re.search(r"<div\b[^>]*table-wrap|<table\b", stripped, re.I))
        if in_html_table or (not in_pipe_table and (starts_html or (is_html_table_markup_line(stripped) and "<" in stripped))):
            if not in_html_table:
                if current_block:
                    flush_block()
                in_html_table = True
            append_raw(stripped)
            low = current_block.lower()
            if "</table>" in low:
                after = low.rsplit("</table>", 1)[-1]
                if "table-wrap" in low:
                    if "</div>" in after:
                        flush_block()
                elif low.rstrip().endswith("</table>"):
                    flush_block()
            continue

        if is_md_table_line(stripped):
            if not in_pipe_table:
                if current_block:
                    flush_block()
                in_pipe_table = True
            append_raw(stripped)
            continue

        if in_pipe_table:
            flush_block()

        starts_with_two_spaces = line.startswith("  ")
        is_heading = line.startswith("#")
        is_marker = "🀄" in line
        is_footnote_start = line.startswith("<sup>")
        is_bracket_title = line.startswith("【") or line.startswith("（")
        is_date_line = re.match(r"^\d{4}(\.\.\.)?\s+", stripped)

        is_new_block = (
            is_heading
            or starts_with_two_spaces
            or is_marker
            or is_footnote_start
            or is_bracket_title
            or is_date_line
        )

        if current_block and current_block.lstrip().startswith("#"):
            is_new_block = True

        if not is_new_block:
            if is_index:
                is_new_block = True
            elif len(stripped) < 50 and not any(c in stripped for c in "。！？.!?！？．。"):
                is_new_block = True

        if is_new_block:
            if current_block:
                blocks.append(current_block.rstrip())
                prev_block_is_heading = current_block.lstrip().startswith("#")
            if prev_block_is_heading and not (
                is_heading or is_marker or is_footnote_start or is_bracket_title or is_date_line
            ) and not starts_with_two_spaces:
                line = "  " + stripped
            current_block = line
        elif current_block:
            prev = current_block.rstrip()
            if prev.endswith("-"):
                current_block = prev[:-1] + stripped
            elif prev and stripped and is_halfwidth_char(prev[-1]) and is_halfwidth_char(stripped[0]):
                current_block = prev + " " + stripped
            else:
                current_block = prev + stripped
        else:
            current_block = line

    if current_block:
        blocks.append(current_block.rstrip())

    final_text = cleanup_text("\n\n".join(blocks))
    if front_matter:
        final_text = front_matter + "\n\n" + final_text.lstrip()
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_text.rstrip() + "\n")



def typeset_files(input_dir, output_dir, filenames):
    os.makedirs(output_dir, exist_ok=True)
    remove_numbered_md(output_dir)
    for filename in filenames:
        process_layout(
            os.path.join(input_dir, filename),
            os.path.join(output_dir, filename),
            is_index=("目录" in filename or "目錄" in filename),
        )


def is_space(ch):
    return ch in SPACE_CHARS


def is_fullwidth(ch):
    return unicodedata.east_asian_width(ch) in {"W", "F"}


def find_left_nonspace(text, idx):
    j = idx - 1
    while j >= 0 and is_space(text[j]):
        j -= 1
    return j


def find_right_nonspace(text, idx):
    j = idx
    while j < len(text) and is_space(text[j]):
        j += 1
    return j


def replace_inline_tokens(text):
    out = []
    start = 0
    count = 0

    for match in TOKEN_RE.finditer(text):
        if match.start() < start:
            continue
        left = find_left_nonspace(text, match.start())
        right = find_right_nonspace(text, match.end())
        if left < 0 or right >= len(text):
            continue
        if not (is_fullwidth(text[left]) and is_fullwidth(text[right])):
            continue

        out.append(text[start:match.start()].rstrip(" \t\u3000"))
        out.append(TOKEN_MAP[match.group(1).lower()])
        count += 1

        start = match.end()
        while start < len(text) and is_space(text[start]):
            start += 1

    out.append(text[start:])
    return "".join(out), count


def merge_final(input_dir, filenames, output_file, repair_inline_tokens=False):
    merged = []
    for filename in sorted(filenames, key=natural_number):
        with open(os.path.join(input_dir, filename), "r", encoding="utf-8") as f:
            merged.append(f.read().strip())
    text = "\n\n".join(merged).rstrip() + "\n"
    replaced = 0
    if repair_inline_tokens:
        text, replaced = replace_inline_tokens(text)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Successfully merged into: {output_file}")
    print(f"Inline token replacements: {replaced}")


def main():
    parser = argparse.ArgumentParser(
        description="Typeset 0.rough.md into a final book Markdown file."
    )
    parser.add_argument("--base-dir", default=os.getcwd(), help="Book root directory.")
    parser.add_argument("--input-file", default=None, help="Input rough Markdown file.")
    parser.add_argument("--merge-dir", default=None, help="Intermediate split directory when --keep-intermediate is set.")
    parser.add_argument("--typeset-dir", default=None, help="Intermediate typeset directory when --keep-intermediate is set.")
    parser.add_argument("--book-name", default=None, help="Output book name.")
    parser.add_argument("--output-file", default=None, help="Final output Markdown file.")
    parser.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="Keep numbered split files in merge-result and typeset-result for debugging.",
    )
    parser.add_argument(
        "--repair-inline-tokens",
        action="store_true",
        help="Opt in to legacy and/or/he/of replacement between CJK characters.",
    )
    args = parser.parse_args()

    base_dir = args.base_dir
    default_merge_dir = os.path.join(base_dir, DEFAULT_MERGE_DIRNAME)
    input_file = args.input_file or os.path.join(default_merge_dir, DEFAULT_INPUT_FILENAME)
    book_name = args.book_name or os.path.basename(os.path.normpath(base_dir))
    output_file = args.output_file or os.path.join(base_dir, f"{book_name}.md")

    if args.keep_intermediate:
        split_dir = args.merge_dir or default_merge_dir
        typeset_dir = args.typeset_dir or os.path.join(base_dir, DEFAULT_TYPESET_DIRNAME)
        split_files = split_by_h1(input_file, split_dir)
        print(f"Sections detected: {len(split_files)}")
        typeset_files(split_dir, typeset_dir, split_files)
        merge_final(
            typeset_dir,
            split_files,
            output_file,
            repair_inline_tokens=args.repair_inline_tokens,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="pdf-set-split-") as split_dir:
            with tempfile.TemporaryDirectory(prefix="pdf-set-typeset-") as typeset_dir:
                split_files = split_by_h1(input_file, split_dir)
                print(f"Sections detected: {len(split_files)}")
                typeset_files(split_dir, typeset_dir, split_files)
                merge_final(
            typeset_dir,
            split_files,
            output_file,
            repair_inline_tokens=args.repair_inline_tokens,
        )

    print(f"Done. Files processed: {len(split_files)}.")


if __name__ == "__main__":
    main()
