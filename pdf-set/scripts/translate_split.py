import argparse
import os
import re

DEFAULT_OUTPUT_DIRNAME = "translate-split"
DEFAULT_MAX_CHARS = 40000


def read_single_path(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            value = line.strip()
            if value:
                return value
    return ""


def split_paragraphs(text):
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    return re.split(r"\n\s*\n", normalized)


def pack_paragraphs(paragraphs, max_chars):
    chunks = []
    current = []
    current_len = 0
    sep_len = 2

    for para in paragraphs:
        if not para:
            continue
        para_len = len(para)

        if not current:
            current = [para]
            current_len = para_len
            if para_len > max_chars:
                chunks.append(current)
                current = []
                current_len = 0
            continue

        new_len = current_len + sep_len + para_len
        if new_len <= max_chars:
            current.append(para)
            current_len = new_len
            continue

        chunks.append(current)
        current = [para]
        current_len = para_len
        if para_len > max_chars:
            chunks.append(current)
            current = []
            current_len = 0

    if current:
        chunks.append(current)

    return chunks


def write_chunks(chunks, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    for idx, chunk in enumerate(chunks, start=1):
        filename = f"{idx}.md"
        output_path = os.path.join(output_dir, filename)
        content = "\n\n".join(chunk).rstrip() + "\n"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Created: {filename} ({len(content)} chars)")


def split_translate(input_file, output_dir, max_chars):
    with open(input_file, "r", encoding="utf-8") as f:
        text = f.read()

    paragraphs = split_paragraphs(text)
    if not paragraphs:
        print("No content to split.")
        return

    chunks = pack_paragraphs(paragraphs, max_chars)
    write_chunks(chunks, output_dir)

    largest_para = max(len(p) for p in paragraphs)
    print(f"Paragraphs: {len(paragraphs)}")
    print(f"Chunks: {len(chunks)}")
    print(f"Max chars per chunk: {max_chars}")
    print(f"Largest paragraph: {largest_para}")
    if largest_para > max_chars:
        print("Warning: at least one paragraph exceeds max-chars; it was kept intact.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Split a book markdown file into translate-split chunks by paragraphs."
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
        "--input-file",
        default=None,
        help="Path to input book markdown file (default: <base-dir>/<book-name>.md).",
    )
    parser.add_argument(
        "--input-file-from",
        default=None,
        help="UTF-8 text file containing input file path (first non-empty line).",
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
        help=f"Max characters per output file (default: {DEFAULT_MAX_CHARS}).",
    )
    args = parser.parse_args()

    base_dir = args.base_dir
    if args.base_dir_from:
        base_dir_from = read_single_path(args.base_dir_from)
        if base_dir_from:
            base_dir = base_dir_from

    book_name = args.book_name or os.path.basename(os.path.normpath(base_dir))
    if args.book_name_from:
        book_name_from = read_single_path(args.book_name_from)
        if book_name_from:
            book_name = book_name_from

    input_file = args.input_file or os.path.join(base_dir, f"{book_name}.md")
    if args.input_file_from:
        input_file_from = read_single_path(args.input_file_from)
        if input_file_from:
            input_file = input_file_from

    output_dir = args.output_dir or os.path.join(base_dir, DEFAULT_OUTPUT_DIRNAME)
    if args.output_dir_from:
        output_dir_from = read_single_path(args.output_dir_from)
        if output_dir_from:
            output_dir = output_dir_from

    if not os.path.isfile(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")

    split_translate(input_file, output_dir, args.max_chars)
