#!/usr/bin/env python3
"""
Check HTML files for multiple <table> tags.

By default, this scans the directory containing this script and all of its
subdirectories. Pass one or more paths to scan other directories or files.

Usage:
  python workflow/0-html_template/check_multiple_tables.py
  python workflow/0-html_template/check_multiple_tables.py workflow/0-html_template/data_en
  python workflow/0-html_template/check_multiple_tables.py --min-tables 3
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


HTML_SUFFIXES = {".html", ".htm"}
TABLE_TAG_RE = re.compile(r"<\s*table(?:\s|>|/)", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List HTML files that contain multiple <table> tags.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to scan. Defaults to this script's directory.",
    )
    parser.add_argument(
        "--min-tables",
        type=int,
        default=2,
        help="Minimum number of <table> tags required to report a file.",
    )
    return parser.parse_args()


def iter_html_files(paths: list[Path]) -> list[Path]:
    html_files: list[Path] = []
    for path in paths:
        if path.is_file():
            if path.suffix.lower() in HTML_SUFFIXES:
                html_files.append(path)
            continue

        if path.is_dir():
            for candidate in path.rglob("*"):
                if candidate.is_file() and candidate.suffix.lower() in HTML_SUFFIXES:
                    html_files.append(candidate)
            continue

        print(f"[Warning] Path not found or unsupported: {path}", file=sys.stderr)

    return sorted(set(html_files), key=lambda p: str(p))


def count_table_tags(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return len(TABLE_TAG_RE.findall(text))


def main() -> int:
    args = parse_args()
    scan_paths = args.paths or [Path(__file__).resolve().parent]
    scan_paths = [path.resolve() for path in scan_paths]

    html_files = iter_html_files(scan_paths)
    matches: list[tuple[Path, int]] = []

    for html_file in html_files:
        count = count_table_tags(html_file)
        if count >= args.min_tables:
            matches.append((html_file, count))

    print(f"Scanned HTML files: {len(html_files)}")
    print(f"Files with at least {args.min_tables} <table> tags: {len(matches)}")

    for path, count in matches:
        try:
            display_path = path.relative_to(Path.cwd())
        except ValueError:
            display_path = path
        print(f"{count}\t{display_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
