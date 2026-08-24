#!/usr/bin/env python3
"""
Find nested wrapper tables in HTML files.

A nested wrapper table is a <table> that contains one or more descendant
<table> tags, but has no meaningful content of its own after those descendant
tables are removed. This catches cases like <table><tr><td><table>...</table>
</td></tr></table>, where the outer table is only a layout wrapper.

By default, this scans the current working directory recursively. Pass one or
more files/directories to scan a narrower set.

Usage:
  python workflow/0-html_template/check_nested_wrapper_tables.py
  python workflow/0-html_template/check_nested_wrapper_tables.py en/html
  python workflow/0-html_template/check_nested_wrapper_tables.py en/html/87.HTML
  python workflow/0-html_template/check_nested_wrapper_tables.py en/html --show-all-nested
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


HTML_SUFFIXES = {".html", ".htm"}
MEANINGFUL_TAGS = {"input", "select", "textarea", "button", "img", "svg", "canvas"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "List HTML files containing nested <table> structures, especially outer "
            "tables that appear to be layout-only wrappers."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to scan. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--show-all-nested",
        action="store_true",
        help="Also report nested tables whose outer table has its own meaningful content.",
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


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def table_depth(table: Any) -> int:
    depth = 1
    parent = table.parent
    while parent is not None:
        if getattr(parent, "name", None) == "table":
            depth += 1
        parent = parent.parent
    return depth


def direct_content_after_removing_nested_tables(table: Any) -> tuple[str, list[str]]:
    table_copy = copy.copy(table)
    for nested in table_copy.find_all("table"):
        nested.decompose()

    text = normalize_text(table_copy.get_text(" ", strip=True))
    meaningful_tags = sorted({tag.name for tag in table_copy.find_all(MEANINGFUL_TAGS)})
    return text, meaningful_tags


def analyze_html(path: Path) -> dict[str, Any]:
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    nested_tables = []
    wrapper_tables = []
    max_depth = 0

    for index, table in enumerate(tables, start=1):
        depth = table_depth(table)
        max_depth = max(max_depth, depth)
        nested_count = len(table.find_all("table"))
        if nested_count == 0:
            continue

        direct_text, meaningful_tags = direct_content_after_removing_nested_tables(table)
        entry = {
            "index": index,
            "depth": depth,
            "nested_count": nested_count,
            "direct_text": direct_text,
            "meaningful_tags": meaningful_tags,
        }
        nested_tables.append(entry)

        if not direct_text and not meaningful_tags:
            wrapper_tables.append(entry)

    return {
        "total_tables": len(tables),
        "max_depth": max_depth,
        "nested_tables": nested_tables,
        "wrapper_tables": wrapper_tables,
    }


def display_path(path: Path) -> Path:
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def main() -> int:
    args = parse_args()
    scan_paths = [path.resolve() for path in (args.paths or [Path.cwd()])]
    html_files = iter_html_files(scan_paths)

    matches = []
    for html_file in html_files:
        result = analyze_html(html_file)
        reported = result["nested_tables"] if args.show_all_nested else result["wrapper_tables"]
        if reported:
            matches.append((html_file, result, reported))

    mode = "nested table structures" if args.show_all_nested else "nested wrapper tables"
    print(f"Scanned HTML files: {len(html_files)}")
    print(f"Files with {mode}: {len(matches)}")

    for path, result, reported in matches:
        print(
            f"{display_path(path)}\t"
            f"total_tables={result['total_tables']}\t"
            f"max_depth={result['max_depth']}\t"
            f"reported_tables={len(reported)}"
        )
        for entry in reported:
            extra = ""
            if entry["direct_text"]:
                extra += f"\tdirect_text={entry['direct_text'][:80]!r}"
            if entry["meaningful_tags"]:
                extra += f"\tmeaningful_tags={','.join(entry['meaningful_tags'])}"
            print(
                f"  table#{entry['index']}: "
                f"depth={entry['depth']}, nested_tables={entry['nested_count']}{extra}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
