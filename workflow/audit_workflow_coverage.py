#!/usr/bin/env python3
"""Audit per-ID coverage across the NEST workflow and rendered inputs."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_IDS = frozenset(range(1, 415))


@dataclass(frozen=True)
class Stage:
    name: str
    path_template: str
    extensions: tuple[str, ...]
    allowed_nonnumeric: tuple[str, ...] = ()


STAGES = (
    Stage("00_html_template", "workflow/0-html_template/data_{lang}", (".html", ".htm")),
    Stage("01_annotated_json", "workflow/1-annotated_json/data_{lang}", (".json",)),
    Stage("02_filled_json_a", "workflow/2-filled_json-a/data_{lang}", (".json",)),
    Stage("03_filled_html_a", "workflow/3-filled_html-a/data_{lang}", (".html", ".htm")),
    Stage("04_context_a", "workflow/4-context-a/data_{lang}", (".txt",)),
    Stage("05_placeholder_html_a", "workflow/5-ph_html-a/data_{lang}", (".html", ".htm")),
    Stage("06_meta_a", "workflow/6-meta-a/data_{lang}", (".json",)),
    Stage("07_html_b", "workflow/7-html-b/data_{lang}", (".html", ".htm")),
    Stage("08_json_b", "workflow/8-json-b/data_{lang}", (".json",)),
    Stage("09_png_a_empty", "workflow/9-png-a/data_{lang}/empty", (".png",)),
    Stage("09_png_a_filled", "workflow/9-png-a/data_{lang}/filled", (".png",)),
)


@dataclass
class AuditResult:
    stage: str
    lang: str
    directory: str
    expected_count: int
    observed_unique_ids: int
    missing_ids: list[int]
    extra_ids: list[int]
    duplicate_ids: dict[str, list[str]]
    allowed_nonnumeric_files: list[str]
    unexpected_nonnumeric_files: list[str]

    @property
    def ok(self) -> bool:
        return not (
            self.missing_ids
            or self.extra_ids
            or self.duplicate_ids
            or self.unexpected_nonnumeric_files
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report path, relative to the project root unless absolute.",
    )
    return parser.parse_args()


def audit_stage(stage: Stage, lang: str) -> AuditResult:
    directory = PROJECT_ROOT / stage.path_template.format(lang=lang)
    extensions = {suffix.casefold() for suffix in stage.extensions}
    allowed_nonnumeric = {name.casefold() for name in stage.allowed_nonnumeric}
    by_id: dict[int, list[str]] = {}
    allowed_files: list[str] = []
    unexpected_files: list[str] = []

    if directory.exists():
        for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
            if not path.is_file() or path.suffix.casefold() not in extensions:
                continue
            try:
                item_id = int(path.stem)
            except ValueError:
                if path.name.casefold() in allowed_nonnumeric:
                    allowed_files.append(path.name)
                else:
                    unexpected_files.append(path.name)
                continue
            by_id.setdefault(item_id, []).append(path.name)

    observed_ids = set(by_id)
    return AuditResult(
        stage=stage.name,
        lang=lang,
        directory=str(directory.relative_to(PROJECT_ROOT)),
        expected_count=len(EXPECTED_IDS),
        observed_unique_ids=len(observed_ids),
        missing_ids=sorted(EXPECTED_IDS - observed_ids),
        extra_ids=sorted(observed_ids - EXPECTED_IDS),
        duplicate_ids={str(item_id): names for item_id, names in by_id.items() if len(names) > 1},
        allowed_nonnumeric_files=allowed_files,
        unexpected_nonnumeric_files=unexpected_files,
    )


def main() -> int:
    args = parse_args()
    results = [audit_stage(stage, lang) for stage in STAGES for lang in ("en", "zh")]

    print(f"{'Stage':<24} {'Lang':<4} {'IDs':>7}  Status")
    print("-" * 58)
    for result in results:
        details = []
        if result.missing_ids:
            details.append(f"missing={result.missing_ids}")
        if result.extra_ids:
            details.append(f"extra={result.extra_ids}")
        if result.duplicate_ids:
            details.append(f"duplicates={result.duplicate_ids}")
        if result.unexpected_nonnumeric_files:
            details.append(f"unexpected={result.unexpected_nonnumeric_files}")
        status = "OK" if result.ok else "; ".join(details)
        print(f"{result.stage:<24} {result.lang:<4} {result.observed_unique_ids:>3}/414  {status}")

    report = {
        "expected_base_universe": {"en": 414, "zh": 414, "ids": "1-414"},
        "intentional_stage_exclusions": [],
        "allowed_auxiliary_files": {},
        "all_stages_complete": all(result.ok for result in results),
        "results": [{**asdict(result), "ok": result.ok} for result in results],
    }

    if args.output is not None:
        output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nReport: {output}")

    return 0 if report["all_stages_complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
