from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comparative_eval.config import SUPPORTED_CONDITIONS, details_dir, prediction_dir, summaries_dir, workflow_paths
from comparative_eval.metrics.jedi_cpp import compare_json_similarity_cpp
from comparative_eval.metrics.jedi_py import compare_json_similarity
from comparative_eval.utils.eval_cache import CACHE_FIELDNAMES, add_cache_record, cached_row_is_current, prediction_cache_record
from comparative_eval.utils.io_utils import iter_numeric_files, read_csv, read_json, write_csv, write_json
from comparative_eval.utils.json_utils import parse_json_lenient
from comparative_eval.utils.openai_utils import strip_thinking


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Table 3 schema parsing.")
    parser.add_argument("--condition", required=True, choices=SUPPORTED_CONDITIONS)
    parser.add_argument("--model", required=True)
    parser.add_argument("--lang", default="en", choices=["en", "zh"])
    parser.add_argument("--metric", choices=["py_tree", "py_fast", "cpp"], default="py_tree")
    parser.add_argument(
        "--cpp_timeout",
        "--cpp-timeout",
        dest="cpp_timeout",
        type=float,
        default=10.0,
        help="Maximum seconds to wait for one C++ JEDI sample. Use <=0 to disable.",
    )
    parser.add_argument(
        "--resume_from_details",
        "--resume-from-details",
        action="store_true",
        help="Reuse current per-sample rows in results/details when their prediction file fingerprint is unchanged.",
    )
    args = parser.parse_args()

    paths = workflow_paths(args.lang)
    pred_dir = prediction_dir("schema", args.condition, args.lang, args.model)
    gold_dir = paths.json_filled if args.condition == "filled" else paths.json_empty
    detail_path = details_dir() / f"schema_{args.condition}_{args.lang}_{clean_model(args.model)}_{args.metric}.csv"
    cached_rows = load_existing_rows_by_id(detail_path) if args.resume_from_details else {}
    rows = []
    invalid_prediction_ids: list[int] = []
    timeout_ids: list[int] = []

    for pred_file in iter_numeric_files(pred_dir, ".json"):
        sample_id = int(pred_file.stem)
        cache_record = prediction_cache_record(pred_file)
        cached_row = cached_rows.get(sample_id)
        if cached_row_is_current(cached_row, cache_record):
            rows.append(cached_row)
            continue
        gold_file = gold_dir / f"{sample_id}.json"
        if not gold_file.exists():
            continue
        pred, pred_issue = read_prediction_raw_response(pred_file)
        if pred_issue is not None:
            res = zero_similarity_result(pred_issue, args.metric)
            score = 0.0
            rows.append(add_cache_record(result_row(args.model, args.condition, sample_id, score, res), cache_record))
            invalid_prediction_ids.append(sample_id)
            continue
        gold = read_json(gold_file)
        pred_obj, pred_status = parse_schema_json(pred)
        gold_obj, gold_status = parse_schema_json(gold, source="gold")
        if pred_obj is None or gold_obj is None:
            res = zero_similarity_result(pred_status, args.metric, gold_status=gold_status)
        elif args.metric == "cpp":
            res = compare_json_similarity_cpp(pred_obj, gold_obj, timeout=args.cpp_timeout)
            if res.get("timeout"):
                timeout_ids.append(sample_id)
        else:
            mode = "fast_structural" if args.metric == "py_fast" else "tree_edit"
            res = compare_json_similarity(pred_obj, gold_obj, mode=mode)
        res["pred_status"] = pred_status
        res["gold_status"] = gold_status
        score = float(res["similarity"])
        rows.append(add_cache_record(result_row(args.model, args.condition, sample_id, score, res), cache_record))

    rows = sorted(rows, key=lambda row: safe_int(row.get("sample_id")) or -1)
    scores = [float(row["similarity"]) for row in rows if row.get("similarity") not in (None, "")]
    all_invalid_prediction_ids = invalid_prediction_ids_from_rows(rows)
    if invalid_prediction_ids:
        preview_ids = ", ".join(str(sample_id) for sample_id in invalid_prediction_ids[:20])
        if len(invalid_prediction_ids) > 20:
            preview_ids += f", ... (+{len(invalid_prediction_ids) - 20} more)"
        print(f"Warning: {len(invalid_prediction_ids)} empty or invalid prediction files were scored as 0: {preview_ids}")
    if timeout_ids:
        preview_ids = ", ".join(str(sample_id) for sample_id in timeout_ids[:20])
        if len(timeout_ids) > 20:
            preview_ids += f", ... (+{len(timeout_ids) - 20} more)"
        print(f"Warning: {len(timeout_ids)} C++ JEDI comparisons timed out and were scored as 0: {preview_ids}")
    write_csv(
        detail_path,
        rows,
        ["model", "condition", "sample_id", "similarity", "distance", "metric", "pred_status", "gold_status", *CACHE_FIELDNAMES],
    )
    summary = {
        "task": "schema",
        "condition": args.condition,
        "lang": args.lang,
        "model": args.model,
        "score": sum(scores) / len(scores) if scores else 0.0,
        "sample_count": len(scores),
        "metric": args.metric,
        "invalid_prediction_count": len(all_invalid_prediction_ids),
        "invalid_prediction_ids": all_invalid_prediction_ids,
        "skipped_prediction_count": len(all_invalid_prediction_ids),
        "skipped_prediction_ids": all_invalid_prediction_ids,
        "timeout_count": len(timeout_ids),
        "timeout_ids": timeout_ids,
        "cpp_timeout": args.cpp_timeout if args.metric == "cpp" else None,
    }
    summary_path = summaries_dir() / f"schema_{args.condition}_{args.lang}_{clean_model(args.model)}_{args.metric}.json"
    write_json(summary_path, summary)
    print(f"Wrote {detail_path}")
    print(f"Wrote {summary_path}")


def clean_model(model: str) -> str:
    return model.replace("/", "_").replace("-", "_")


def read_prediction_raw_response(pred_file: Path) -> tuple[str, str | None]:
    text = pred_file.read_text(encoding="utf-8")
    if not text.strip():
        return "", "skip"

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return "", "skip"
    if not isinstance(data, dict):
        return "", "skip"

    raw_response = data.get("raw_response", "")
    if raw_response is None:
        raw_response = ""
    elif not isinstance(raw_response, str):
        raw_response = str(raw_response)
    pred = strip_thinking(raw_response)
    if not pred.strip():
        return "", "skip"
    return pred, None


def parse_schema_json(value: object, source: str = "pred") -> tuple[dict | None, str]:
    parsed, status = parse_json_lenient(value)
    if parsed is None:
        return None, status
    if not isinstance(parsed, dict):
        return None, f"{source}_non_dict:{type(parsed).__name__}"
    return parsed, status


def zero_similarity_result(pred_status: str, metric: str, gold_status: str = "ok") -> dict[str, object]:
    metric_name = {
        "cpp": "jedi_cpp",
        "py_tree": "jedi_py:tree_edit",
        "py_fast": "jedi_py:fast_structural",
    }[metric]
    return {
        "similarity": 0.0,
        "distance": None,
        "size_pred": 0,
        "size_gold": 0,
        "pred_status": pred_status,
        "gold_status": gold_status,
        "metric": metric_name,
    }


def result_row(model: str, condition: str, sample_id: int, score: float, res: dict) -> dict[str, object]:
    return {
        "model": model,
        "condition": condition,
        "sample_id": sample_id,
        "similarity": f"{score:.6f}",
        "distance": res.get("distance"),
        "metric": res.get("metric"),
        "pred_status": res.get("pred_status"),
        "gold_status": res.get("gold_status"),
    }


def invalid_prediction_ids_from_rows(rows: list[dict]) -> list[int]:
    ids: list[int] = []
    valid_statuses = {"ok", "repaired"}
    for row in rows:
        status = str(row.get("pred_status") or "").strip()
        if status and status not in valid_statuses:
            sample_id = safe_int(row.get("sample_id"))
            if sample_id is not None:
                ids.append(sample_id)
    return ids


def load_existing_rows_by_id(path: Path) -> dict[int, dict[str, str]]:
    if not path.exists():
        return {}
    rows_by_id: dict[int, dict[str, str]] = {}
    for row in read_csv(path):
        sample_id = safe_int(row.get("sample_id"))
        if sample_id is None:
            continue
        rows_by_id[sample_id] = row
    return rows_by_id


def safe_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
