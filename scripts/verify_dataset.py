#!/usr/bin/env python3
"""Verify the released NEST benchmark dataset inventory."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_STAGE_COUNTS = {
    "workflow/0-html_template/data_en": 414,
    "workflow/0-html_template/data_zh": 414,
    "workflow/1-annotated_json/data_en": 414,
    "workflow/1-annotated_json/data_zh": 414,
    "workflow/2-filled_json-a/data_en": 414,
    "workflow/2-filled_json-a/data_zh": 414,
    "workflow/3-filled_html-a/data_en": 414,
    "workflow/3-filled_html-a/data_zh": 414,
    "workflow/4-context-a/data_en": 414,
    "workflow/4-context-a/data_zh": 414,
    "workflow/5-ph_html-a/data_en": 414,
    "workflow/5-ph_html-a/data_zh": 414,
    "workflow/6-meta-a/data_en": 414,
    "workflow/6-meta-a/data_zh": 414,
    "workflow/7-html-b/data_en": 414,
    "workflow/7-html-b/data_zh": 414,
    "workflow/8-json-b/data_en": 414,
    "workflow/8-json-b/data_zh": 414,
    "workflow/9-png-a/data_en/empty": 414,
    "workflow/9-png-a/data_en/filled": 414,
    "workflow/9-png-a/data_zh/empty": 414,
    "workflow/9-png-a/data_zh/filled": 414,
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    errors: list[str] = []
    manifest = ROOT / "data/source_provenance_manifest.csv"
    if not manifest.is_file() or len(manifest.read_text(encoding="utf-8-sig").splitlines()) != 829:
        errors.append("provenance manifest must contain one header and 828 records")

    for relative, expected in EXPECTED_STAGE_COUNTS.items():
        path = ROOT / relative
        actual = sum(1 for item in path.iterdir() if item.is_file()) if path.is_dir() else 0
        if actual != expected:
            errors.append(f"{relative}: expected {expected} files, found {actual}")

    checksums = ROOT / "SHA256SUMS"
    if not checksums.is_file():
        errors.append("missing SHA256SUMS")
    else:
        for line_number, line in enumerate(checksums.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                expected, relative = line.split("  ", 1)
            except ValueError:
                errors.append(f"invalid SHA256SUMS line {line_number}")
                continue
            path = ROOT / relative
            if not path.is_file():
                errors.append(f"missing checksummed file: {relative}")
            elif digest(path) != expected:
                errors.append(f"checksum mismatch: {relative}")

    if errors:
        print("dataset verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("dataset verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
