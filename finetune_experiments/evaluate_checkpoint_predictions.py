from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finetune_experiments.checkpoint_utils import (
    DEFAULT_CHECKPOINT_TASKS,
    derive_prediction_model_name,
    expand_checkpoint_langs,
    expand_checkpoint_tasks,
    load_test_records,
    prediction_path_for_record,
)
from finetune_experiments.finetune_data import COMBINED_LANG, DATASET_DIR, FINETUNE_ROOT
from comparative_eval.config import workflow_paths
from comparative_eval.metrics.jedi_cpp import compare_json_similarity_cpp
from comparative_eval.metrics.jedi_py import compare_json_similarity
from comparative_eval.metrics.infill import (
    SOURCE_FAITHFUL_MATCHER,
    SUPPORTED_INFILL_MATCHERS,
)
from comparative_eval.eval_schema import (
    invalid_prediction_ids_from_rows as schema_invalid_prediction_ids_from_rows,
    parse_schema_json,
    result_row as schema_result_row,
    zero_similarity_result,
)
from comparative_eval.utils.eval_cache import CACHE_FIELDNAMES, add_cache_record, cached_row_is_current, prediction_cache_record
from comparative_eval.utils.io_utils import ensure_dir, read_csv, read_json, read_text, write_csv, write_json
from comparative_eval.utils.openai_utils import strip_thinking


RESULTS_DIR = FINETUNE_ROOT / "results"
DETAILS_DIR = RESULTS_DIR / "details"
SUMMARIES_DIR = RESULTS_DIR / "summaries"


def details_dir() -> Path:
    return DETAILS_DIR


def summaries_dir() -> Path:
    return SUMMARIES_DIR


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate saved fine-tuned checkpoint predictions on the "
            "finetune_experiments/datasets test split, then aggregate scores."
        )
    )
    parser.add_argument("--checkpoint_dir", "--checkpoint-dir", dest="checkpoint_dir", type=Path, default=None)
    parser.add_argument("--prediction_model_name", "--prediction-model-name", dest="prediction_model_name", default=None)
    parser.add_argument("--dataset_dir", "--dataset-dir", dest="dataset_dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--tasks", nargs="*", choices=[*DEFAULT_CHECKPOINT_TASKS, "all"], default=["all"])
    parser.add_argument("--lang", default=COMBINED_LANG, choices=[COMBINED_LANG, "en", "zh"])
    parser.add_argument("--schema_metric", "--schema-metric", dest="schema_metric", choices=["py_tree", "py_fast", "cpp"], default="py_tree")
    parser.add_argument(
        "--infill_matcher",
        "--infill-matcher",
        dest="infill_matcher",
        choices=SUPPORTED_INFILL_MATCHERS,
        default=SOURCE_FAITHFUL_MATCHER,
        help="Task 3 metric implementation. source_faithful_v3 is the current default.",
    )
    parser.add_argument(
        "--cpp_timeout",
        "--cpp-timeout",
        dest="cpp_timeout",
        type=float,
        default=10.0,
        help="Maximum seconds to wait for one C++ JEDI schema sample. Use <=0 to disable.",
    )
    parser.add_argument("--output_prefix", "--output-prefix", dest="output_prefix", default=None)
    parser.add_argument("--limit", type=int, default=0, help="Limit records per task after filtering. 0 means no limit.")
    parser.add_argument(
        "--count_missing_as_zero",
        "--count-missing-as-zero",
        dest="count_missing_as_zero",
        action="store_true",
        help=(
            "Count truly missing prediction files as zero instead of excluding them. "
            "Existing empty or invalid prediction files are always scored as zero."
        ),
    )
    parser.add_argument("--skip_aggregate", "--skip-aggregate", dest="skip_aggregate", action="store_true")
    parser.add_argument("--dry_run", "--dry-run", dest="dry_run", action="store_true")
    parser.add_argument(
        "--resume_from_details",
        "--resume-from-details",
        dest="resume_from_details",
        action="store_true",
        help="Reuse current per-sample rows in finetune_experiments/results/details when unchanged.",
    )
    args = parser.parse_args()

    if args.prediction_model_name:
        prediction_model_name = args.prediction_model_name
    elif args.checkpoint_dir:
        prediction_model_name = derive_prediction_model_name(args.checkpoint_dir)
    else:
        parser.error("Provide --prediction_model_name or --checkpoint_dir.")

    tasks = expand_checkpoint_tasks(args.tasks)
    langs = expand_checkpoint_langs(args.lang)
    records_by_task = {
        task: load_test_records(task, args.lang, args.dataset_dir, args.limit)
        for task in tasks
    }

    coverage_rows = coverage_for_records(records_by_task, prediction_model_name, langs)
    print_coverage(coverage_rows)
    if args.dry_run:
        return
    write_coverage(prediction_model_name, args.lang, coverage_rows)

    for task, records in records_by_task.items():
        for lang in langs:
            lang_records = [record for record in records if record.get("lang") == lang]
            if not lang_records:
                continue
            if task == "schema":
                evaluate_schema(
                    lang_records,
                    prediction_model_name,
                    args.schema_metric,
                    args.count_missing_as_zero,
                    args.cpp_timeout,
                    args.resume_from_details,
                )
            elif task == "alignment":
                evaluate_alignment(lang_records, prediction_model_name, args.count_missing_as_zero, args.resume_from_details)
            elif task == "infill":
                evaluate_infill(
                    lang_records,
                    prediction_model_name,
                    args.count_missing_as_zero,
                    args.resume_from_details,
                    args.infill_matcher,
                )
            else:
                raise ValueError(task)

    if not args.skip_aggregate:
        output_prefix = args.output_prefix or f"finetune_{clean_model(prediction_model_name)}_{args.lang}_test"
        cmd = [
            sys.executable,
            "comparative_eval/aggregate_table3.py",
            "--lang",
            args.lang,
            "--schema_metric",
            args.schema_metric,
            "--infill_matcher",
            args.infill_matcher,
            "--output_prefix",
            output_prefix,
            "--summaries_dir",
            str(SUMMARIES_DIR),
            "--output_dir",
            str(RESULTS_DIR),
            "--models",
            prediction_model_name,
        ]
        print(" ".join(cmd), flush=True)
        subprocess.run(cmd, check=True)


def coverage_for_records(
    records_by_task: dict[str, list[dict[str, Any]]],
    prediction_model_name: str,
    langs: tuple[str, ...],
) -> list[dict[str, str | int]]:
    rows = []
    for task, records in records_by_task.items():
        for lang in langs:
            lang_records = [record for record in records if record.get("lang") == lang]
            prediction_count = 0
            missing_ids = []
            ids = []
            for record in lang_records:
                sample_id = int(record["sample_id"])
                ids.append(sample_id)
                path = prediction_path_for_record(record, prediction_model_name)
                if read_prediction_text(path):
                    prediction_count += 1
                else:
                    missing_ids.append(sample_id)
            rows.append(
                {
                    "model": prediction_model_name,
                    "task": task,
                    "condition": "empty",
                    "lang": lang,
                    "expected_count": len(lang_records),
                    "prediction_count": prediction_count,
                    "missing_count": len(missing_ids),
                    "first_id": min(ids) if ids else "",
                    "last_id": max(ids) if ids else "",
                    "missing_ids": " ".join(str(item) for item in missing_ids[:50]),
                }
            )
    return rows


def write_coverage(prediction_model_name: str, lang: str, rows: list[dict[str, str | int]]) -> None:
    ensure_dir(RESULTS_DIR)
    fields = [
        "model",
        "task",
        "condition",
        "lang",
        "expected_count",
        "prediction_count",
        "missing_count",
        "first_id",
        "last_id",
        "missing_ids",
    ]
    prefix = f"finetune_{clean_model(prediction_model_name)}_{lang}_test_prediction_coverage"
    write_csv(RESULTS_DIR / f"{prefix}.csv", rows, fields)
    write_json(RESULTS_DIR / f"{prefix}.json", {"rows": rows})


def print_coverage(rows: list[dict[str, str | int]]) -> None:
    print("Fine-tuned checkpoint test prediction coverage:", flush=True)
    for row in rows:
        print(
            f"  {row['model']} | {row['task']} | {row['lang']}: "
            f"{row['prediction_count']}/{row['expected_count']} predictions, "
            f"missing={row['missing_count']}",
            flush=True,
        )


def evaluate_schema(
    records: list[dict[str, Any]],
    prediction_model_name: str,
    schema_metric: str,
    count_missing_as_zero: bool,
    cpp_timeout: float,
    resume_from_details: bool,
) -> None:
    rows = []
    missing_count = 0
    timeout_ids: list[int] = []
    condition = "empty"
    lang = str(records[0]["lang"])
    detail_path = details_dir() / f"schema_{condition}_{lang}_{clean_model(prediction_model_name)}_{schema_metric}.csv"
    cached_rows = load_existing_rows_by_id(detail_path) if resume_from_details else {}
    for record in records:
        sample_id = int(record["sample_id"])
        pred_path = prediction_path_for_record(record, prediction_model_name)
        cached_row, cache_record = cached_row_for_prediction(pred_path, cached_rows, sample_id)
        if cached_row is not None:
            rows.append(cached_row)
            continue

        pred_text, pred_issue = read_prediction_text_with_status(pred_path)
        if pred_issue is not None:
            if pred_issue == "missing":
                missing_count += 1
            if pred_issue == "missing" and not count_missing_as_zero:
                continue
            res = zero_similarity_result(pred_issue, schema_metric)
        else:
            gold = read_json(gold_file_for_record(record, "schema"))
            pred_obj, pred_status = parse_schema_json(pred_text)
            gold_obj, gold_status = parse_schema_json(gold, source="gold")
            if pred_obj is None or gold_obj is None:
                res = zero_similarity_result(pred_status, schema_metric, gold_status=gold_status)
            elif schema_metric == "cpp":
                res = compare_json_similarity_cpp(pred_obj, gold_obj, timeout=cpp_timeout)
                if res.get("timeout"):
                    timeout_ids.append(sample_id)
            else:
                mode = "fast_structural" if schema_metric == "py_fast" else "tree_edit"
                res = compare_json_similarity(pred_obj, gold_obj, mode=mode)
            res["pred_status"] = pred_status
            res["gold_status"] = gold_status

        score = float(res["similarity"])
        rows.append(row_with_cache(schema_result_row(prediction_model_name, condition, sample_id, score, res), cache_record))

    rows = sorted(rows, key=lambda row: int(row["sample_id"]))
    scores = [float(row["similarity"]) for row in rows if row.get("similarity") not in (None, "")]
    all_invalid_prediction_ids = schema_invalid_prediction_ids_from_rows(rows)
    write_csv(
        detail_path,
        rows,
        ["model", "condition", "sample_id", "similarity", "distance", "metric", "pred_status", "gold_status", *CACHE_FIELDNAMES],
    )
    write_json(
        summaries_dir() / f"schema_{condition}_{lang}_{clean_model(prediction_model_name)}_{schema_metric}.json",
        {
            "task": "schema",
            "condition": condition,
            "lang": lang,
            "model": prediction_model_name,
            "score": sum(scores) / len(scores) if scores else 0.0,
            "sample_count": len(scores),
            "expected_count": len(records),
            "missing_count": missing_count,
            "invalid_prediction_count": len(all_invalid_prediction_ids),
            "invalid_prediction_ids": all_invalid_prediction_ids,
            "timeout_count": len(timeout_ids),
            "timeout_ids": timeout_ids,
            "cpp_timeout": cpp_timeout if schema_metric == "cpp" else None,
            "metric": schema_metric,
        },
    )
    print(f"Wrote {detail_path}")


def evaluate_alignment(
    records: list[dict[str, Any]],
    prediction_model_name: str,
    count_missing_as_zero: bool,
    resume_from_details: bool,
) -> None:
    from comparative_eval.eval_alignment import (
        FIELD_TYPES,
        alignment_row,
        choose_coordinate_strategy,
        compare_alignment,
        expand_meta,
        invalid_prediction_ids_from_rows,
        resolve_expected_names_from_gold,
        summarize_rows,
        zero_alignment_results,
    )

    rows = []
    missing_count = 0
    condition = "empty"
    lang = str(records[0]["lang"])
    detail_path = details_dir() / f"alignment_{condition}_{lang}_{clean_model(prediction_model_name)}.csv"
    cached_rows = load_existing_rows_by_id(detail_path) if resume_from_details else {}

    for record in records:
        sample_id = int(record["sample_id"])
        paths = workflow_paths(lang)
        meta_file = paths.meta / f"{sample_id}.json"
        gold_file = gold_file_for_record(record, "alignment")
        if not meta_file.exists() or not gold_file.exists():
            continue

        expected = expand_meta(read_json(meta_file))
        if not expected:
            continue
        gold_html = read_text(gold_file)
        strategy = choose_coordinate_strategy(gold_html, expected)
        expected = resolve_expected_names_from_gold(gold_html, expected, strategy)

        pred_path = prediction_path_for_record(record, prediction_model_name)
        cached_row, cache_record = cached_row_for_prediction(pred_path, cached_rows, sample_id)
        if cached_row is not None:
            rows.append(cached_row)
            continue

        pred_html, pred_issue = read_prediction_text_with_status(pred_path)
        if pred_issue is not None:
            if pred_issue == "missing":
                missing_count += 1
            if pred_issue == "missing" and not count_missing_as_zero:
                continue
            results = zero_alignment_results(expected)
            pred_status = pred_issue
        else:
            results, _records = compare_alignment(pred_html, expected, strategy)
            pred_status = "ok"

        row = alignment_row(prediction_model_name, condition, sample_id, results, strategy, pred_status=pred_status)
        rows.append(row_with_cache(row, cache_record))

    rows = sorted(rows, key=lambda row: int(row["sample_id"]))
    total_correct, total_count, type_totals = summarize_rows(rows)
    invalid_prediction_ids = invalid_prediction_ids_from_rows(rows)
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
            "strategy",
            "pred_status",
            "LI_correct",
            "LI_total",
            "GI_correct",
            "GI_total",
            "SI_correct",
            "SI_total",
            "GO_correct",
            "GO_total",
            "SO_correct",
            "SO_total",
            *CACHE_FIELDNAMES,
        ],
    )
    write_json(
        summaries_dir() / f"alignment_{condition}_{lang}_{clean_model(prediction_model_name)}.json",
        {
            "task": "alignment",
            "condition": condition,
            "lang": lang,
            "model": prediction_model_name,
            "score": total_correct / total_count if total_count else 0.0,
            "correct": total_correct,
            "total": total_count,
            "sample_count": len(rows),
            "expected_count": len(records),
            "missing_count": missing_count,
            "invalid_prediction_count": len(invalid_prediction_ids),
            "invalid_prediction_ids": invalid_prediction_ids,
            "metric": "meta_target_cell_input_name_accuracy",
            "by_type": {
                field_type: {
                    "correct": type_totals[field_type]["correct"],
                    "total": type_totals[field_type]["total"],
                    "accuracy": (
                        type_totals[field_type]["correct"] / type_totals[field_type]["total"]
                        if type_totals[field_type]["total"]
                        else 0.0
                    ),
                }
                for field_type in FIELD_TYPES
            },
        },
    )
    print(f"Wrote {detail_path}")


def evaluate_infill(
    records: list[dict[str, Any]],
    prediction_model_name: str,
    count_missing_as_zero: bool,
    resume_from_details: bool,
    infill_matcher: str = SOURCE_FAITHFUL_MATCHER,
) -> None:
    from comparative_eval.eval_infill import (
        compare_infill,
        count_expected_fill_slots,
        infill_row,
        invalid_prediction_ids_from_rows,
        summarize_rows,
    )

    rows = []
    missing_count = 0
    condition = "empty"
    lang = str(records[0]["lang"])
    paths = workflow_paths(lang)
    detail_path = details_dir() / f"infill_{condition}_{lang}_{clean_model(prediction_model_name)}.csv"
    cached_rows = load_existing_rows_by_id(detail_path) if resume_from_details else {}

    for record in records:
        sample_id = int(record["sample_id"])
        gold_file = gold_file_for_record(record, "infill")
        ph_file = paths.placeholder_html / f"{sample_id}.html"
        if not gold_file.exists() or not ph_file.exists():
            continue

        gold_html = read_text(gold_file)
        placeholder_html = read_text(ph_file)
        pred_path = prediction_path_for_record(record, prediction_model_name)
        cached_row, cache_record = cached_row_for_prediction(pred_path, cached_rows, sample_id)
        if cached_row is not None and str(cached_row.get("metric_version", "")) != infill_matcher:
            cached_row = None
        if cached_row is not None:
            rows.append(cached_row)
            continue

        pred_html, pred_issue = read_prediction_text_with_status(pred_path)
        if pred_issue is not None:
            if pred_issue == "missing":
                missing_count += 1
            if pred_issue == "missing" and not count_missing_as_zero:
                continue
            correct = 0
            total = count_expected_fill_slots(gold_html, placeholder_html, matcher=infill_matcher)
            pred_status = pred_issue
        else:
            correct, total = compare_infill(pred_html, gold_html, placeholder_html, matcher=infill_matcher)
            pred_status = "ok"

        rows.append(
            row_with_cache(
                infill_row(
                    prediction_model_name,
                    condition,
                    sample_id,
                    correct,
                    total,
                    pred_status=pred_status,
                    metric_version=infill_matcher,
                ),
                cache_record,
            )
        )

    rows = sorted(rows, key=lambda row: int(row["sample_id"]))
    total_correct, total_count = summarize_rows(rows)
    invalid_prediction_ids = invalid_prediction_ids_from_rows(rows)
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
    write_json(
        summaries_dir() / f"infill_{condition}_{lang}_{clean_model(prediction_model_name)}.json",
        {
            "task": "infill",
            "condition": condition,
            "lang": lang,
            "model": prediction_model_name,
            "score": total_correct / total_count if total_count else 0.0,
            "correct": total_correct,
            "total": total_count,
            "sample_count": len(rows),
            "expected_count": len(records),
            "missing_count": missing_count,
            "invalid_prediction_count": len(invalid_prediction_ids),
            "invalid_prediction_ids": invalid_prediction_ids,
            "metric": "anchored_semantic_cell_accuracy",
            "metric_version": infill_matcher,
        },
    )
    print(f"Wrote {detail_path}")


def read_prediction_text(path: Path) -> str:
    text, issue = read_prediction_text_with_status(path)
    return text if issue is None else ""


def read_prediction_text_with_status(path: Path) -> tuple[str, str | None]:
    if not path.exists():
        return "", "missing"
    if not path.read_text(encoding="utf-8").strip():
        return "", "empty_file"
    try:
        data = read_json(path)
    except Exception:
        return "", "invalid_json"
    if not isinstance(data, dict):
        return "", "invalid_prediction_json"
    raw_response = data.get("raw_response", "")
    if raw_response is None:
        raw_response = ""
    elif not isinstance(raw_response, str):
        raw_response = str(raw_response)
    text = strip_thinking(raw_response)
    if not text.strip():
        return "", "empty_response"
    return text, None


def gold_file_for_record(record: dict[str, Any], task: str) -> Path:
    source_files = record.get("source_files")
    if isinstance(source_files, dict):
        gold = source_files.get("gold")
        if isinstance(gold, str) and gold:
            path = Path(gold)
            if path.exists():
                return path

    paths = workflow_paths(str(record["lang"]))
    sample_id = int(record["sample_id"])
    if task == "schema":
        return paths.json_empty / f"{sample_id}.json"
    if task == "alignment":
        return paths.placeholder_html / f"{sample_id}.html"
    if task == "infill":
        return paths.html_filled / f"{sample_id}.html"
    raise ValueError(task)


def cached_row_for_prediction(
    pred_path: Path,
    cached_rows: dict[int, dict[str, str]],
    sample_id: int,
) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    if not pred_path.exists():
        return None, None
    cache_record = prediction_cache_record(pred_path)
    cached_row = cached_rows.get(sample_id)
    if cached_row_is_current(cached_row, cache_record):
        return cached_row, cache_record
    return None, cache_record


def row_with_cache(row: dict[str, Any], cache_record: dict[str, str] | None) -> dict[str, Any]:
    if cache_record is None:
        return row
    return add_cache_record(row, cache_record)


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


def clean_model(model: str) -> str:
    return model.replace("/", "_").replace("-", "_")


if __name__ == "__main__":
    main()
