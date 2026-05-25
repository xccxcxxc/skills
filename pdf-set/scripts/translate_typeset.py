import argparse
import os
import re

DEFAULT_INPUT_DIRNAME = "translate-split"
DEFAULT_OUTPUT_DIRNAME = "translate-typeset"
DEFAULT_MAX_CHARS = 250
DEFAULT_BUFFER_CHARS = 200

PUNCTUATION = {
    "。",
    "？",
    "！",
    ".",
    "?",
    "!",
}

TRAILING_CLOSERS = {
    "›",
    "»",
    "”",
    "’",
    "）",
    ")",
    "】",
    "]",
}

SUP_RE = re.compile(r"<sup>(.*?)</sup>", re.DOTALL | re.IGNORECASE)
IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")

ABBREVIATIONS = {
    "M",
    "Mme",
    "Mlle",
    "Dr",
    "Pr",
    "Mr",
    "Ms",
    "St",
    "cf",
    "etc",
    "i.e",
    "e.g",
}


def read_single_path(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            value = line.strip()
            if value:
                return value
    return ""


def split_paragraphs(text, protect_sup=True):
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    spans = []
    if protect_sup:
        spans = [(m.start(), m.end()) for m in SUP_RE.finditer(normalized)]

    parts = []
    last = 0
    for m in re.finditer(r"\n\s*\n", normalized):
        if protect_sup and is_protected(spans, m.start()):
            continue
        part = normalized[last:m.start()].strip()
        if part:
            parts.append(part)
        last = m.end()
    tail = normalized[last:].strip()
    if tail:
        parts.append(tail)
    return parts


def find_protected_spans(text, protect_sup=True):
    spans = []
    if protect_sup:
        for match in SUP_RE.finditer(text):
            spans.append((match.start(), match.end()))
    for match in IMAGE_RE.finditer(text):
        spans.append((match.start(), match.end()))
    spans.sort()
    return spans


def is_protected(spans, index):
    for start, end in spans:
        if start <= index < end:
            return True
    return False


def is_ascii_upper(ch):
    return "A" <= ch <= "Z"


def is_name_initial_dot(text, i):
    if i <= 0:
        return False
    if not is_ascii_upper(text[i - 1]):
        return False

    j = i + 1
    while j < len(text) and text[j].isspace():
        j += 1
    if j >= len(text) or not is_ascii_upper(text[j]):
        return False

    if j + 1 < len(text):
        nxt = text[j + 1]
        if nxt.islower() or nxt in {"-", "'"}:
            return True
    return False


def is_abbreviation_dot(text, i):
    j = i - 1
    while j >= 0 and text[j].isalpha():
        j -= 1
    token = text[j + 1:i]
    if token in ABBREVIATIONS:
        return True
    # U.S. / U.S.A. style: current dot right after single uppercase, with another ".X" nearby.
    if len(token) == 1 and is_ascii_upper(token):
        if i >= 2 and text[i - 2] == ".":
            return True
        if i + 2 < len(text) and text[i + 1].isalpha() and text[i + 2] == ".":
            return True
    return False


def is_lowercase_continuation_dot(text, i):
    """Treat '.' as non-splittable when followed by lowercase continuation."""
    j = i + 1
    while j < len(text) and text[j].isspace():
        j += 1
    if j >= len(text):
        return False
    ch = text[j]
    return ch.isalpha() and ch.islower()


def find_punctuation_positions(text, spans):
    positions = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in {"。", "？", "！", "?", "!"}:
            if not is_protected(spans, i):
                positions.append(i)
        elif ch == ".":
            # Do not split inside ellipsis like "..."
            prev_is_dot = i > 0 and text[i - 1] == "."
            next_is_dot = i + 1 < len(text) and text[i + 1] == "."
            if not (prev_is_dot or next_is_dot):
                if not is_protected(spans, i):
                    if (
                        not is_name_initial_dot(text, i)
                        and not is_abbreviation_dot(text, i)
                        and not is_lowercase_continuation_dot(text, i)
                    ):
                        positions.append(i)
        i += 1
    return positions


def split_once(paragraph, max_chars, buffer_chars, protect_sup=True):
    if len(paragraph) <= max_chars + buffer_chars:
        return [paragraph]

    spans = find_protected_spans(paragraph, protect_sup=protect_sup)
    positions = find_punctuation_positions(paragraph, spans)
    if not positions:
        return [paragraph]

    target = max_chars - 1
    best_pos = min(positions, key=lambda p: abs(p - target))

    cut_pos = best_pos + 1
    while cut_pos < len(paragraph) and paragraph[cut_pos].isspace():
        cut_pos += 1
    while cut_pos < len(paragraph) and paragraph[cut_pos] in TRAILING_CLOSERS:
        cut_pos += 1
    while cut_pos < len(paragraph) and paragraph[cut_pos].isspace():
        cut_pos += 1

    left = paragraph[:cut_pos].rstrip()
    right = paragraph[cut_pos:].lstrip()
    if not right:
        return [paragraph]
    return [left, right]


def split_paragraph(paragraph, max_chars, buffer_chars, protect_sup=True):
    parts = [paragraph]
    changed = True
    while changed:
        changed = False
        new_parts = []
        for part in parts:
            split_parts = split_once(part, max_chars, buffer_chars, protect_sup=protect_sup)
            if len(split_parts) > 1:
                changed = True
            new_parts.extend(split_parts)
        parts = new_parts
    return parts


def split_sup_blocks(text, max_chars, buffer_chars):
    def repl(match):
        inner = match.group(1)
        inner_parts = []
        for para in split_paragraphs(inner, protect_sup=False):
            inner_parts.extend(
                split_paragraph(para, max_chars, buffer_chars, protect_sup=False)
            )
        if len(inner_parts) <= 1:
            return match.group(0)
        return "\n\n".join(f"<sup>{part}</sup>" for part in inner_parts)

    return SUP_RE.sub(repl, text)


def process_text(text, max_chars, buffer_chars):
    text = split_sup_blocks(text, max_chars, buffer_chars)
    paragraphs = split_paragraphs(text, protect_sup=True)
    output_paragraphs = []
    for para in paragraphs:
        if not para:
            continue
        output_paragraphs.extend(
            split_paragraph(para, max_chars, buffer_chars, protect_sup=True)
        )
    return "\n\n".join(output_paragraphs).rstrip() + "\n"


def translate_typeset(input_dir, output_dir, max_chars, buffer_chars):
    os.makedirs(output_dir, exist_ok=True)
    files = sorted([f for f in os.listdir(input_dir) if f.endswith(".md")])
    for filename in files:
        input_path = os.path.join(input_dir, filename)
        output_path = os.path.join(output_dir, filename)
        with open(input_path, "r", encoding="utf-8") as f:
            text = f.read()
        processed = process_text(text, max_chars, buffer_chars)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(processed)
        print(f"Processed: {filename}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Typeset translated markdown by splitting long paragraphs."
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
        "--input-dir",
        default=None,
        help=f"Input folder (default: <base-dir>/{DEFAULT_INPUT_DIRNAME}).",
    )
    parser.add_argument(
        "--input-dir-from",
        default=None,
        help="UTF-8 text file containing input directory (first non-empty line).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"Output folder (default: <base-dir>/{DEFAULT_OUTPUT_DIRNAME}).",
    )
    parser.add_argument(
        "--output-dir-from",
        default=None,
        help="UTF-8 text file containing output directory (first non-empty line).",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help=f"Target max characters per paragraph (default: {DEFAULT_MAX_CHARS}).",
    )
    parser.add_argument(
        "--buffer-chars",
        type=int,
        default=DEFAULT_BUFFER_CHARS,
        help=f"Buffer before splitting (default: {DEFAULT_BUFFER_CHARS}).",
    )
    args = parser.parse_args()

    base_dir = args.base_dir
    if args.base_dir_from:
        base_dir_from = read_single_path(args.base_dir_from)
        if base_dir_from:
            base_dir = base_dir_from

    input_dir = args.input_dir or os.path.join(base_dir, DEFAULT_INPUT_DIRNAME)
    if args.input_dir_from:
        input_dir_from = read_single_path(args.input_dir_from)
        if input_dir_from:
            input_dir = input_dir_from

    output_dir = args.output_dir or os.path.join(base_dir, DEFAULT_OUTPUT_DIRNAME)
    if args.output_dir_from:
        output_dir_from = read_single_path(args.output_dir_from)
        if output_dir_from:
            output_dir = output_dir_from

    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    translate_typeset(input_dir, output_dir, args.max_chars, args.buffer_chars)
