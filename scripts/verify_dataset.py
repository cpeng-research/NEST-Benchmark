#!/usr/bin/env python3
"""Verify the released NEST benchmark dataset inventory."""

from __future__ import annotations

import hashlib
import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_COUNTS = {"en": 414, "zh": 414}
TEXT_COUNTS = {"en": 420, "zh": 421, "fr": 13, "es": 15}
STAGES = (
    "0-html_template", "1-annotated_json", "2-filled_json-a",
    "3-filled_html-a", "4-context-a", "5-ph_html-a", "6-meta-a",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    errors: list[str] = []
    base_manifest = ROOT / "data/source_provenance_manifest.csv"
    current_manifest = ROOT / "data/source_provenance_manifest_current.csv"
    with base_manifest.open(encoding="utf-8-sig", newline="") as stream:
        base_rows = list(csv.DictReader(stream))
    with current_manifest.open(encoding="utf-8", newline="") as stream:
        current_rows = list(csv.DictReader(stream))
    if len(base_rows) != 828 or len(current_rows) != 869:
        errors.append("expected 828 base and 869 current provenance records")
    elif any(any(row.get(key) != old.get(key) for key in old) for row, old in zip(current_rows, base_rows)):
        errors.append("current manifest changed a base provenance row")
    for row in current_rows[828:]:
        if any(not row.get(key) for key in ("batch", "added_on", "source_sha256", "rights_url")):
            errors.append(f"incomplete extension provenance: {row['language']}/{row['id']}")
    ids = [(row["language"].split(" ", 1)[0], int(row["id"])) for row in current_rows]
    if len(ids) != len(set(ids)):
        errors.append("duplicate provenance identity")
    if {lang: sum(row["language"].split(" ", 1)[0] == lang for row in current_rows)
            for lang in TEXT_COUNTS} != TEXT_COUNTS:
        errors.append("provenance language counts do not match the workflow")

    expected_stage_counts = {
        f"workflow/{stage}/data_{lang}": count
        for stage in STAGES for lang, count in TEXT_COUNTS.items()
    }
    expected_stage_counts.update({
        f"workflow/{stage}/data_{lang}": count
        for stage in ("7-html-b", "8-json-b") for lang, count in CORE_COUNTS.items()
    })
    expected_stage_counts.update({
        f"workflow/9-png-a/data_{lang}/{condition}": count
        for lang, count in TEXT_COUNTS.items() for condition in ("empty", "filled")
    })
    for relative, expected in expected_stage_counts.items():
        path = ROOT / relative
        actual = sum(1 for item in path.iterdir() if item.is_file() and item.stem.isdecimal()) if path.is_dir() else 0
        if actual != expected:
            errors.append(f"{relative}: expected {expected} files, found {actual}")

    checksums = ROOT / "SHA256SUMS"
    if not checksums.is_file():
        errors.append("missing SHA256SUMS")
    else:
        listed = set()
        for line_number, line in enumerate(checksums.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                continue
            try:
                expected, relative = line.split("  ", 1)
            except ValueError:
                errors.append(f"invalid SHA256SUMS line {line_number}")
                continue
            path = ROOT / relative
            listed.add(relative.removeprefix("./"))
            if not path.is_file():
                errors.append(f"missing checksummed file: {relative}")
            elif digest(path) != expected:
                errors.append(f"checksum mismatch: {relative}")
        for relative in expected_stage_counts:
            for item in (ROOT / relative).glob("[0-9]*"):
                if item.is_file() and item.relative_to(ROOT).as_posix() not in listed:
                    errors.append(f"unchecksummed workflow file: {item.relative_to(ROOT)}")

    if errors:
        print("dataset verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("dataset verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
