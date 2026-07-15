#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Report validated OCR progress and ETA as text or JSON."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import statistics
import sys

from table_utils import read_json


def status(base: Path):
    images = sorted(
        [p for p in (base / "images").glob("*") if p.is_file() and p.stem.isdigit()],
        key=lambda p: int(p.stem),
    )
    valid, invalid, times = [], [], []
    for image in images:
        stem = image.stem
        md = base / "ocr-result" / f"{stem}.md"
        meta = read_json(base / "ocr-result" / f"{stem}.meta.json", {}) or {}
        if md.is_file() and meta.get("status") == "ok" and meta.get("validated") is True:
            valid.append(stem)
            times.append(md.stat().st_mtime)
        else:
            invalid.append(stem)
    intervals = [b - a for a, b in zip(times, times[1:]) if 0 < b - a < 3600]
    recent = intervals[-20:]
    sec_per_page = statistics.median(recent) if recent else None
    eta = None
    if sec_per_page and invalid:
        eta = datetime.now() + timedelta(seconds=sec_per_page * len(invalid) * 1.15)
    return {
        "total": len(images),
        "validated": len(valid),
        "remaining": len(invalid),
        "missing_or_invalid": invalid,
        "seconds_per_page_median": round(sec_per_page, 2) if sec_per_page else None,
        "eta_local": eta.isoformat(timespec="minutes") if eta else None,
        "complete": bool(images) and not invalid,
    }


def main():
    parser = argparse.ArgumentParser(description="Report validated OCR status and ETA.")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = status(Path(args.base_dir).resolve())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['validated']}/{result['total']} validated; remaining={result['remaining']}")
        if result["eta_local"]:
            print(f"ETA (15% buffer): {result['eta_local']}")
        if result["missing_or_invalid"]:
            print("missing/invalid:", ",".join(result["missing_or_invalid"][:50]))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
