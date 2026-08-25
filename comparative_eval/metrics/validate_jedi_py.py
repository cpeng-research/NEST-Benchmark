from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comparative_eval.config import workflow_paths
from comparative_eval.metrics.jedi_cpp import compare_json_similarity_cpp
from comparative_eval.metrics.jedi_py import compare_json_similarity
from comparative_eval.utils.io_utils import id_in_range, iter_numeric_files, read_json, write_csv
from comparative_eval.config import details_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Python JEDI-like similarity against old C++ JEDI.")
    parser.add_argument("--lang", default="en", choices=["en", "zh"])
    parser.add_argument("--start_id", type=int, default=None)
    parser.add_argument("--end_id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--mode", choices=["tree_edit", "fast_structural"], default="tree_edit")
    args = parser.parse_args()

    paths = workflow_paths(args.lang)
    rows = []
    for gold_file in iter_numeric_files(paths.json_empty, ".json"):
        sample_id = int(gold_file.stem)
        if not id_in_range(sample_id, args.start_id, args.end_id):
            continue
        pred_file = paths.json_filled / f"{sample_id}.json"
        if not pred_file.exists():
            continue
        gold = read_json(gold_file)
        pred = read_json(pred_file)

        t0 = time.perf_counter()
        py = compare_json_similarity(pred, gold, mode=args.mode)
        py_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        cpp = compare_json_similarity_cpp(pred, gold)
        cpp_ms = (time.perf_counter() - t0) * 1000
        rows.append({
            "sample_id": sample_id,
            "py_similarity": f"{py['similarity']:.6f}",
            "cpp_similarity": f"{cpp['similarity']:.6f}",
            "abs_error": f"{abs(py['similarity'] - cpp['similarity']):.6f}",
            "py_ms": f"{py_ms:.2f}",
            "cpp_ms": f"{cpp_ms:.2f}",
            "py_distance": py.get("distance"),
            "cpp_distance": cpp.get("distance"),
        })
        if args.limit and len(rows) >= args.limit:
            break

    out = details_dir() / f"jedi_py_validation_{args.lang}_{args.mode}.csv"
    write_csv(out, rows, ["sample_id", "py_similarity", "cpp_similarity", "abs_error", "py_ms", "cpp_ms", "py_distance", "cpp_distance"])
    errors = [float(row["abs_error"]) for row in rows]
    if errors:
        print(f"Wrote {out}")
        print(f"n={len(errors)} mean_abs_error={statistics.mean(errors):.6f} max_abs_error={max(errors):.6f}")
    else:
        print("No comparable samples found.")


if __name__ == "__main__":
    main()
