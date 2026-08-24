from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


CACHE_FIELDNAMES = [
    "prediction_path",
    "prediction_mtime_ns",
    "prediction_size",
    "prediction_sha1",
]


def prediction_cache_record(path: Path) -> dict[str, str]:
    data = path.read_bytes()
    stat = path.stat()
    return {
        "prediction_path": str(path),
        "prediction_mtime_ns": str(stat.st_mtime_ns),
        "prediction_size": str(stat.st_size),
        "prediction_sha1": hashlib.sha1(data).hexdigest(),
    }


def cached_row_is_current(row: dict[str, Any] | None, cache_record: dict[str, str]) -> bool:
    if not row:
        return False
    return str(row.get("prediction_sha1", "")) == cache_record["prediction_sha1"]


def add_cache_record(row: dict[str, Any], cache_record: dict[str, str]) -> dict[str, Any]:
    out = dict(row)
    out.update(cache_record)
    return out
