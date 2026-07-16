#!/usr/bin/env python3
"""Crop embedded figures from mixed text+image page scans.

When OCR marks a figure with 🀄️..., this tool extracts the figure region
(not the whole page) into figures/<page>-<n>.jpg and rewrites the markdown.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

PLACEHOLDER_RE = re.compile(r"🀄️\s*([^\s🀄️]+)")


def dilate_binary(mask: Image.Image, radius: int = 2) -> Image.Image:
    inv = ImageOps.invert(mask.convert("L"))
    inv = inv.filter(ImageFilter.MaxFilter(max(1, 2 * radius + 1)))
    return ImageOps.invert(inv)


def find_figure_boxes(
    image_path: str | Path,
    *,
    thr: int = 200,
    dilate: int = 3,
    min_h_ratio: float = 0.07,
    min_w_ratio: float = 0.18,
    max_area: float = 0.88,
    max_boxes: int = 3,
):
    """Return candidate figure boxes as (x0,y0,x1,y1) in original pixel coords."""
    im = Image.open(image_path).convert("RGB")
    gray = ImageOps.autocontrast(im.convert("L"))
    width, height = gray.size
    scale = max(1, min(width, height) // 900)
    small = gray.resize((width // scale, height // scale), Image.BILINEAR)
    sw, sh = small.size
    mask = small.point(lambda p: 0 if p < thr else 255, "L")
    mask = dilate_binary(mask, radius=max(1, dilate // max(scale, 1)))
    pix = mask.load()
    seen = bytearray(sw * sh)

    def index(x, y):
        return y * sw + x

    comps = []
    for y in range(sh):
        for x in range(sw):
            if seen[index(x, y)] or pix[x, y] != 0:
                continue
            queue = deque([(x, y)])
            seen[index(x, y)] = 1
            minx = maxx = x
            miny = maxy = y
            area = 0
            while queue:
                cx, cy = queue.popleft()
                area += 1
                if cx < minx:
                    minx = cx
                if cx > maxx:
                    maxx = cx
                if cy < miny:
                    miny = cy
                if cy > maxy:
                    maxy = cy
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < sw and 0 <= ny < sh and not seen[index(nx, ny)] and pix[nx, ny] == 0:
                        seen[index(nx, ny)] = 1
                        queue.append((nx, ny))
            bw = maxx - minx + 1
            bh = maxy - miny + 1
            area_ratio = (bw * bh) / float(sw * sh)
            if area_ratio > max_area:
                continue
            if bh / sh < min_h_ratio or bw / sw < min_w_ratio:
                continue
            if bw / sw > 0.92 and bh / sh < 0.06:
                continue
            box = (minx * scale, miny * scale, (maxx + 1) * scale, (maxy + 1) * scale)
            comps.append(
                {
                    "box": box,
                    "area_ratio": area_ratio,
                    "h_ratio": bh / sh,
                    "w_ratio": bw / sw,
                    "area": area,
                    "score": area * (1.0 + bh / sh),
                }
            )
    comps.sort(key=lambda item: item["score"], reverse=True)

    # Rank by adjusted mid-page preference and drop near-duplicates.
    ranked = []
    for item in comps[:20]:
        x0, y0, x1, y1 = item["box"]
        cy = (y0 + y1) / 2.0 / height
        score = item["score"] * (1.25 - abs(cy - 0.42))
        if item["h_ratio"] > 0.72:
            score *= 0.2
        if y0 < height * 0.03 and item["h_ratio"] < 0.12:
            score *= 0.4  # likely header line art
        ranked.append({**item, "score": score, "cy": cy})
    ranked.sort(key=lambda item: item["score"], reverse=True)

    selected = []
    for item in ranked:
        x0, y0, x1, y1 = item["box"]
        overlap = False
        for prev in selected:
            px0, py0, px1, py1 = prev["box"]
            ix0, iy0 = max(x0, px0), max(y0, py0)
            ix1, iy1 = min(x1, px1), min(y1, py1)
            if ix1 > ix0 and iy1 > iy0:
                inter = (ix1 - ix0) * (iy1 - iy0)
                union = (x1 - x0) * (y1 - y0) + (px1 - px0) * (py1 - py0) - inter
                if inter / max(union, 1) > 0.45:
                    overlap = True
                    break
        if not overlap:
            selected.append(item)
        if len(selected) >= max_boxes:
            break
    return selected, (width, height)


def crop_boxes(image_path: str | Path, boxes, out_dir: str | Path, stem: str, pad: int = 12):
    im = Image.open(image_path).convert("RGB")
    width, height = im.size
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, item in enumerate(boxes, start=1):
        x0, y0, x1, y1 = item["box"]
        box = (
            max(0, x0 - pad),
            max(0, y0 - pad),
            min(width, x1 + pad),
            min(height, y1 + pad),
        )
        # Reject near-full-page crops.
        area = (box[2] - box[0]) * (box[3] - box[1]) / float(width * height)
        if area >= 0.9:
            continue
        out_path = out_dir / f"{stem}-{i}.jpg"
        im.crop(box).save(out_path, format="JPEG", quality=92, optimize=True, subsampling=0)
        paths.append(out_path)
    return paths


def rewrite_placeholders(md_text: str, replacements: list[str]) -> str:
    """Replace 🀄️ tokens with cropped figure placeholders in order."""
    if not replacements:
        return md_text
    idx = 0

    def repl(match):
        nonlocal idx
        if idx >= len(replacements):
            return match.group(0)
        value = replacements[idx]
        idx += 1
        return f"🀄️{value}"

    return PLACEHOLDER_RE.sub(repl, md_text)


def process_page_markdown(
    md_path: str | Path,
    image_path: str | Path,
    figures_dir: str | Path,
    *,
    rel_prefix: str = "figures",
):
    md_path = Path(md_path)
    text = md_path.read_text(encoding="utf-8")
    tokens = PLACEHOLDER_RE.findall(text)
    if not tokens:
        return {"changed": False, "figures": []}
    # Only crop when placeholders still point at page-level images / bare names.
    needs = []
    for token in tokens:
        name = token.replace("\\", "/").split("/")[-1]
        if re.fullmatch(r"\d+\.(?:jpg|jpeg|png|webp)", name, re.I) or re.fullmatch(r"\d+", name):
            needs.append(token)
        elif "figures/" not in token.replace("\\", "/"):
            # unknown form still try crop once
            needs.append(token)
    if not needs:
        return {"changed": False, "figures": []}

    stem = md_path.stem if md_path.stem.isdigit() else Path(image_path).stem
    boxes, _ = find_figure_boxes(image_path)
    if not boxes:
        return {"changed": False, "figures": [], "warning": "no-figure-box"}
    crops = crop_boxes(image_path, boxes, figures_dir, stem)
    if not crops:
        return {"changed": False, "figures": [], "warning": "crop-rejected"}
    replacements = [f"{rel_prefix}/{path.name}" for path in crops]
    # If fewer crops than tokens, reuse last crop; if more crops, only first N tokens.
    while len(replacements) < len(PLACEHOLDER_RE.findall(text)):
        replacements.append(replacements[-1])
    new_text = rewrite_placeholders(text, replacements)
    if new_text != text:
        md_path.write_text(new_text if new_text.endswith("\n") else new_text + "\n", encoding="utf-8")
    return {"changed": new_text != text, "figures": [str(p) for p in crops]}


def process_book(base_dir: str | Path, images_dir=None, ocr_dir=None, figures_dir=None):
    base_dir = Path(base_dir)
    images_dir = Path(images_dir or base_dir / "images")
    ocr_dir = Path(ocr_dir or base_dir / "ocr-result")
    figures_dir = Path(figures_dir or base_dir / "figures")
    results = []
    for md in sorted(ocr_dir.glob("*.md"), key=lambda p: int(p.stem) if p.stem.isdigit() else 10**9):
        if not md.stem.isdigit():
            continue
        image = images_dir / f"{md.stem}.jpg"
        if not image.exists():
            for ext in (".jpeg", ".png", ".webp"):
                alt = images_dir / f"{md.stem}{ext}"
                if alt.exists():
                    image = alt
                    break
        if not image.exists():
            continue
        if "🀄️" not in md.read_text(encoding="utf-8", errors="ignore"):
            continue
        info = process_page_markdown(md, image, figures_dir)
        info["page"] = md.stem
        results.append(info)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Crop figure regions for mixed OCR pages")
    parser.add_argument("--base-dir", help="Book directory containing images/ and ocr-result/")
    parser.add_argument("--image", help="Single page image")
    parser.add_argument("--markdown", help="Single page markdown")
    parser.add_argument("--figures-dir", help="Output directory for cropped figures")
    args = parser.parse_args(argv)

    if args.base_dir:
        results = process_book(args.base_dir, figures_dir=args.figures_dir)
        changed = sum(1 for item in results if item.get("changed"))
        print(f"Processed {len(results)} placeholder page(s); updated {changed}.")
        for item in results:
            if item.get("changed") or item.get("warning"):
                print(item)
        return 0 if results is not None else 1

    if not args.image or not args.markdown:
        parser.error("Provide --base-dir or both --image and --markdown")
    figures_dir = args.figures_dir or str(Path(args.markdown).resolve().parent.parent / "figures")
    info = process_page_markdown(args.markdown, args.image, figures_dir)
    print(info)
    return 0 if info.get("changed") or not info.get("warning") else 1


if __name__ == "__main__":
    sys.exit(main())
