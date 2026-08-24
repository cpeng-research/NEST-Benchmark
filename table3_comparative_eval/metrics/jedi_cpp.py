from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from table3_comparative_eval.config import old_jedi_root
from table3_comparative_eval.metrics.jedi_py import json_to_bracket_string
from table3_comparative_eval.utils.json_utils import parse_json_lenient


def compare_json_similarity_cpp(
    pred: Any,
    gold: Any,
    *,
    threshold: int = 1000,
    timeout: float = 10.0,
    sort_keys: bool = True,
    normalize_text: bool = False,
    denominator: str = "sum",
) -> dict[str, Any]:
    pred_obj, pred_status = parse_json_lenient(pred)
    gold_obj, gold_status = parse_json_lenient(gold)
    if pred_obj is None or gold_obj is None:
        return {
            "similarity": 0.0,
            "distance": None,
            "size_pred": 0,
            "size_gold": 0,
            "pred_status": pred_status,
            "gold_status": gold_status,
            "metric": "jedi_cpp",
        }

    bracket_gold = json_to_bracket_string(gold_obj, sort_keys=sort_keys, normalize_text=normalize_text)
    bracket_pred = json_to_bracket_string(pred_obj, sort_keys=sort_keys, normalize_text=normalize_text)
    result = calculate_jedi_distance(
        bracket_gold,
        bracket_pred,
        threshold=threshold,
        timeout=timeout,
        denominator=denominator,
    )
    if result is None:
        return {
            "similarity": 0.0,
            "distance": None,
            "size_pred": 0,
            "size_gold": 0,
            "pred_status": pred_status,
            "gold_status": gold_status,
            "metric": "jedi_cpp",
        }
    result.update({"pred_status": pred_status, "gold_status": gold_status, "metric": "jedi_cpp"})
    return result


def calculate_jedi_distance(
    bracket_gold: str,
    bracket_pred: str,
    *,
    threshold: int = 1000,
    timeout: float = 10.0,
    denominator: str = "sum",
) -> dict[str, Any] | None:
    jedi_root = old_jedi_root()
    build_dir = jedi_root / "jedi-experiments" / "build"
    exp_lookup = build_dir / "exp-lookup"
    if not exp_lookup.exists():
        raise RuntimeError(
            "C++ JEDIS executable not found at "
            f"{exp_lookup}. Use the checked-in per-sample evaluation caches to "
            "reproduce the paper aggregates, or build exp-lookup before "
            "recomputing Task 1 scores."
        )

    output_prefix = f"table3_jedi_{os.getpid()}_{time.time_ns()}"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".bracket", delete=False, encoding="utf-8") as f:
        bracket_file = Path(f.name)
        f.write(bracket_gold + "\n")
        f.write(bracket_pred + "\n")

    try:
        rel_path = os.path.relpath(bracket_file, build_dir)
        cmd = [str(exp_lookup), rel_path, str(threshold), output_prefix, "0", "1"]
        try:
            subprocess.run(
                cmd,
                cwd=str(build_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
                timeout=timeout if timeout and timeout > 0 else None,
            )
        except subprocess.TimeoutExpired:
            return {
                "similarity": 0.0,
                "distance": None,
                "lower": -1,
                "upper": -1,
                "size_gold": 0,
                "size_pred": 0,
                "timeout": True,
            }
        except subprocess.CalledProcessError:
            return None
        quality_file = build_dir / f"{output_prefix}-{threshold:.6f}-0-quality.txt"
        for _ in range(10):
            if quality_file.exists():
                break
            time.sleep(0.05)
        if not quality_file.exists():
            return None

        lines = quality_file.read_text(encoding="utf-8").splitlines()
        for line in lines[1:]:
            cols = line.strip().split(",")
            if len(cols) < 7 or cols[0] == cols[1]:
                continue
            size_gold = int(cols[2])
            size_pred = int(cols[3])
            lower = float(cols[4])
            upper = None if cols[5] == "-1" else float(cols[5])
            jedi_value = cols[6]
            if jedi_value != "-1":
                distance = float(jedi_value)
            elif upper is not None:
                distance = (lower + upper) / 2
            else:
                distance = lower
            reference = max(size_gold, size_pred) if denominator == "max" else size_gold + size_pred
            similarity = 1.0 if reference == 0 else max(0.0, min(1.0, 1 - distance / reference))
            return {
                "similarity": similarity,
                "distance": distance,
                "lower": lower,
                "upper": upper if upper is not None else -1,
                "size_gold": size_gold,
                "size_pred": size_pred,
            }
        return None
    finally:
        try:
            bracket_file.unlink(missing_ok=True)
        except Exception:
            pass
        for suffix in ("quality", "meta", "runtime"):
            try:
                (build_dir / f"{output_prefix}-{threshold:.6f}-0-{suffix}.txt").unlink(missing_ok=True)
            except Exception:
                pass
