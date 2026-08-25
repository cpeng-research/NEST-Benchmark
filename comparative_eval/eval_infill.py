from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comparative_eval.config import SUPPORTED_CONDITIONS, details_dir, prediction_dir, summaries_dir, workflow_paths
from comparative_eval.utils.eval_cache import CACHE_FIELDNAMES, add_cache_record, cached_row_is_current, prediction_cache_record
from comparative_eval.metrics.infill import (
    SOURCE_FAITHFUL_MATCHER,
    SUPPORTED_INFILL_MATCHERS,
    compare_infill,
)
from comparative_eval.utils.io_utils import iter_numeric_files, read_csv, read_text, write_csv, write_json
from comparative_eval.utils.openai_utils import strip_thinking


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Table 3 generative infilling.")
    parser.add_argument("--condition", required=True, choices=SUPPORTED_CONDITIONS)
    parser.add_argument("--model", required=True)
    parser.add_argument("--lang", default="en", choices=["en", "zh"])
    parser.add_argument(
        "--matcher",
        choices=SUPPORTED_INFILL_MATCHERS,
        default=SOURCE_FAITHFUL_MATCHER,
        help="Infilling metric implementation. source_faithful_v3 is the hardened default.",
    )
    parser.add_argument(
        "--resume_from_details",
        "--resume-from-details",
        action="store_true",
        help="Reuse current per-sample rows in results/details when their prediction file fingerprint is unchanged.",
    )
    args = parser.parse_args()

    paths = workflow_paths(args.lang)
    pred_dir = prediction_dir("infill", args.condition, args.lang, args.model)
    detail_path = details_dir() / f"infill_{args.condition}_{args.lang}_{clean_model(args.model)}.csv"
    cached_rows = load_existing_rows_by_id(detail_path) if args.resume_from_details else {}
    rows = []
    for pred_file in iter_numeric_files(pred_dir, ".json"):
        sample_id = int(pred_file.stem)
        cache_record = prediction_cache_record(pred_file)
        cached_row = cached_rows.get(sample_id)
        if (
            cached_row_is_current(cached_row, cache_record)
            and str(cached_row.get("metric_version", "")) == args.matcher
        ):
            rows.append(cached_row)
            continue
        gold_file = paths.html_filled / f"{sample_id}.html"
        ph_file = paths.placeholder_html / f"{sample_id}.html"
        if not gold_file.exists() or not ph_file.exists():
            continue
        gold_html = read_text(gold_file)
        placeholder_html = read_text(ph_file)
        pred_html, pred_issue = read_prediction_html(pred_file)
        if pred_issue is not None:
            total = count_expected_fill_slots(gold_html, placeholder_html, matcher=args.matcher)
            rows.append(
                add_cache_record(
                    infill_row(
                        args.model,
                        args.condition,
                        sample_id,
                        correct=0,
                        total=total,
                        pred_status=pred_issue,
                        metric_version=args.matcher,
                    ),
                    cache_record,
                )
            )
            continue
        correct, total = compare_infill(pred_html, gold_html, placeholder_html, matcher=args.matcher)
        rows.append(
            add_cache_record(
                infill_row(
                    args.model,
                    args.condition,
                    sample_id,
                    correct=correct,
                    total=total,
                    pred_status="ok",
                    metric_version=args.matcher,
                ),
                cache_record,
            )
        )

    rows = sorted(filter_evaluable_rows(rows), key=lambda row: safe_int(row.get("sample_id"), -1))
    total_correct, total_count = summarize_rows(rows)
    all_invalid_prediction_ids = invalid_prediction_ids_from_rows(rows)
    if all_invalid_prediction_ids:
        preview_ids = ", ".join(str(sample_id) for sample_id in all_invalid_prediction_ids[:20])
        if len(all_invalid_prediction_ids) > 20:
            preview_ids += f", ... (+{len(all_invalid_prediction_ids) - 20} more)"
        print(
            f"Warning: {len(all_invalid_prediction_ids)} empty or invalid prediction files were scored as 0: "
            f"{preview_ids}"
        )

    write_csv(
        detail_path,
        rows,
        [
            "model",
            "condition",
            "sample_id",
            "correct",
            "total",
            "accuracy",
            "pred_status",
            "metric_version",
            *CACHE_FIELDNAMES,
        ],
    )
    summary = {
        "task": "infill",
        "condition": args.condition,
        "lang": args.lang,
        "model": args.model,
        "score": total_correct / total_count if total_count else 0.0,
        "correct": total_correct,
        "total": total_count,
        "sample_count": len(rows),
        "metric": "anchored_semantic_cell_accuracy",
        "metric_version": args.matcher,
        "invalid_prediction_count": len(all_invalid_prediction_ids),
        "invalid_prediction_ids": all_invalid_prediction_ids,
        "skipped_prediction_count": len(all_invalid_prediction_ids),
        "skipped_prediction_ids": all_invalid_prediction_ids,
    }
    summary_path = summaries_dir() / f"infill_{args.condition}_{args.lang}_{clean_model(args.model)}.json"
    write_json(summary_path, summary)
    print(f"Wrote {detail_path}")
    print(f"Wrote {summary_path}")


def clean_model(model: str) -> str:
    return model.replace("/", "_").replace("-", "_")


def read_prediction_html(pred_file: Path) -> tuple[str, str | None]:
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
    pred_html = strip_thinking(raw_response)
    if not pred_html.strip():
        return "", "skip"
    return pred_html, None


def count_expected_fill_slots(
    gold_html: str,
    placeholder_html: str,
    matcher: str = SOURCE_FAITHFUL_MATCHER,
) -> int:
    return compare_infill("", gold_html, placeholder_html, matcher=matcher)[1]


def infill_row(
    model: str,
    condition: str,
    sample_id: int,
    correct: int,
    total: int,
    pred_status: str,
    metric_version: str,
) -> dict[str, object]:
    acc = correct / total if total else 0.0
    return {
        "model": model,
        "condition": condition,
        "sample_id": sample_id,
        "correct": correct,
        "total": total,
        "accuracy": f"{acc:.6f}",
        "pred_status": pred_status,
        "metric_version": metric_version,
    }


def invalid_prediction_ids_from_rows(rows: list[dict]) -> list[int]:
    ids: list[int] = []
    for row in rows:
        status = str(row.get("pred_status") or "").strip()
        if status and status != "ok":
            ids.append(safe_int(row.get("sample_id"), -1))
    return [sample_id for sample_id in ids if sample_id >= 0]


def load_existing_rows_by_id(path: Path) -> dict[int, dict[str, str]]:
    if not path.exists():
        return {}
    rows_by_id: dict[int, dict[str, str]] = {}
    for row in read_csv(path):
        sample_id = safe_int(row.get("sample_id"), -1)
        if sample_id < 0:
            continue
        rows_by_id[sample_id] = row
    return rows_by_id


def summarize_rows(rows: list[dict]) -> tuple[int, int]:
    total_correct = 0
    total_count = 0
    for row in rows:
        total_correct += safe_int(row.get("correct"))
        total_count += safe_int(row.get("total"))
    return total_correct, total_count


def filter_evaluable_rows(rows: list[dict]) -> list[dict]:
    """Exclude tables with no annotated infilling targets from detail outputs."""
    return [row for row in rows if safe_int(row.get("total")) > 0]


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    main()
