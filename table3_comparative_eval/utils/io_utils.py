from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Iterable


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def numeric_file_id(path: Path) -> int | None:
    try:
        return int(path.stem)
    except ValueError:
        return None


def iter_numeric_files(directory: Path, suffix: str) -> list[Path]:
    if not directory.exists():
        return []
    files = []
    for path in directory.iterdir():
        if path.is_file() and path.suffix.lower() == suffix.lower() and numeric_file_id(path) is not None:
            files.append(path)
    return sorted(files, key=lambda p: int(p.stem))


def id_in_range(sample_id: int, start_id: int | None, end_id: int | None) -> bool:
    if start_id is not None and sample_id < start_id:
        return False
    if end_id is not None and sample_id > end_id:
        return False
    return True

