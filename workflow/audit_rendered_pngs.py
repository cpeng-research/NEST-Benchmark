#!/usr/bin/env python3
"""Validate every rendered Empty/Filled PNG and its layout-audit record."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PNG_ROOT = PROJECT_ROOT / "workflow" / "9-png-a"
EXPECTED_IDS = frozenset(range(1, 415))
GROUPS = tuple(
    (lang, condition, PNG_ROOT / f"data_{lang}" / condition)
    for lang in ("en", "zh")
    for condition in ("empty", "filled")
)


@dataclass(frozen=True)
class ImageCheck:
    path: str
    width: int
    height: int
    nonwhite_fraction: float
    layout_ok: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.layout_ok


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PNG_ROOT / "render_audit_all.json",
        help="Combined JSON report path, relative to the project root unless absolute.",
    )
    return parser.parse_args()


def project_relative(path: Path) -> str:
    return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))


def load_layout_audits() -> dict[str, bool]:
    audit_by_output: dict[str, bool] = {}
    for condition in ("empty", "filled"):
        path = PNG_ROOT / f"render_audit_{condition}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("items", []):
            output = item.get("output")
            if isinstance(output, str):
                audit_by_output[output] = bool(item.get("ok"))
    return audit_by_output


def image_nonwhite_fraction(image: Image.Image) -> float:
    gray = image.convert("L")
    gray.thumbnail((256, 256))
    histogram = gray.histogram()
    total = sum(histogram)
    nonwhite = sum(histogram[:250])
    return nonwhite / total if total else 0.0


def check_image(path: Path, layout_audits: dict[str, bool]) -> ImageCheck:
    relative = project_relative(path)
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            nonwhite_fraction = image_nonwhite_fraction(image)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        return ImageCheck(relative, 0, 0, 0.0, False, f"invalid PNG: {exc}")

    error = None
    if width < 16 or height < 16:
        error = f"implausible dimensions: {width}x{height}"
    elif nonwhite_fraction == 0:
        error = "blank white image"
    layout_ok = layout_audits.get(relative, False)
    if relative not in layout_audits and error is None:
        error = "missing layout-audit record"
    return ImageCheck(relative, width, height, nonwhite_fraction, layout_ok, error)


def numeric_pngs(directory: Path) -> dict[int, Path]:
    result: dict[int, Path] = {}
    if not directory.exists():
        return result
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.casefold() != ".png":
            continue
        try:
            sample_id = int(path.stem)
        except ValueError:
            continue
        result[sample_id] = path
    return result


def main() -> int:
    args = parse_args()
    layout_audits = load_layout_audits()
    checks: list[ImageCheck] = []
    groups: list[dict[str, object]] = []

    for lang, condition, directory in GROUPS:
        by_id = numeric_pngs(directory)
        missing = sorted(EXPECTED_IDS - set(by_id))
        extra = sorted(set(by_id) - EXPECTED_IDS)
        group_checks = [check_image(by_id[sample_id], layout_audits) for sample_id in sorted(by_id)]
        checks.extend(group_checks)
        widths = [item.width for item in group_checks if item.width]
        heights = [item.height for item in group_checks if item.height]
        groups.append(
            {
                "language": lang,
                "condition": condition,
                "directory": project_relative(directory),
                "count": len(by_id),
                "missing_ids": missing,
                "extra_ids": extra,
                "failed_images": sum(not item.ok for item in group_checks),
                "width_range": [min(widths), max(widths)] if widths else None,
                "height_range": [min(heights), max(heights)] if heights else None,
            }
        )

    all_ok = all(
        not group["missing_ids"] and not group["extra_ids"] and group["failed_images"] == 0
        for group in groups
    )
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "expected_ids": "1-414",
        "expected_images": 1656,
        "checked_images": len(checks),
        "all_ok": all_ok,
        "groups": groups,
        "failures": [asdict(item) for item in checks if not item.ok],
        "images": [asdict(item) | {"ok": item.ok} for item in checks],
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Checked {len(checks)}/1656 PNG files")
    for group in groups:
        print(
            f"{group['language']} {group['condition']}: count={group['count']}, "
            f"failed={group['failed_images']}, width={group['width_range']}, height={group['height_range']}"
        )
    print(f"Report: {output}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
