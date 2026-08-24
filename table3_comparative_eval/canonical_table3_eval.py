from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from table3_comparative_eval.config import (
    SUPPORTED_CONDITIONS,
    SUPPORTED_TASKS,
    TABLE3_ROOT,
    details_dir,
    prediction_dir,
    rendered_image_dir,
    workflow_paths,
)
from table3_comparative_eval.eval_alignment import expand_meta
from table3_comparative_eval.eval_existing_and_aggregate import (
    PAPER_TABLE3_MODELS,
    TABLE3_IMAGE_REFERENCE_MODELS,
    discover_coverage,
    run_evaluators,
)
from table3_comparative_eval.eval_infill import count_expected_fill_slots
from table3_comparative_eval.metrics.infill import SOURCE_FAITHFUL_MATCHER, SUPPORTED_INFILL_MATCHERS
from table3_comparative_eval.utils.io_utils import (
    ensure_dir,
    iter_numeric_files,
    read_csv,
    read_json,
    read_text,
    write_csv,
    write_json,
)


LANGS = ("en", "zh")
CANONICAL_DIR = TABLE3_ROOT / "results" / "canonical"
MANIFEST_FIELDS = [
    "model",
    "task",
    "lang",
    "condition",
    "sample_id",
    "target_count",
    "input_path",
    "prediction_path",
    "prediction_status",
    "raw_response_nonempty",
    "retry_recommended",
]
SOURCE_FIELDS = [
    "task",
    "lang",
    "sample_id",
    "eligible",
    "target_count",
    "source_status",
    "source_issue",
]


@dataclass(frozen=True)
class SourceEligibility:
    sample_id: int
    eligible: bool
    target_count: int
    status: str
    issue: str = ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the canonical Table 3 evaluation universe, audit prediction coverage, "
            "and optionally recompute all metrics on the complete paired ID sets."
        )
    )
    parser.add_argument("--lang", default="both", choices=["both", *LANGS])
    parser.add_argument("--models", nargs="*", default=None)
    parser.add_argument("--include_image_references", "--include-image-references", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--require_complete", "--require-complete", action="store_true")
    parser.add_argument("--schema_metric", "--schema-metric", choices=["py_tree", "py_fast", "cpp"], default="py_tree")
    parser.add_argument(
        "--infill_matcher",
        "--infill-matcher",
        dest="infill_matcher",
        choices=SUPPORTED_INFILL_MATCHERS,
        default=SOURCE_FAITHFUL_MATCHER,
    )
    parser.add_argument("--eval_workers", "--eval-workers", type=int, default=4)
    parser.add_argument("--resume_from_details", "--resume-from-details", action="store_true")
    parser.add_argument(
        "--output_prefix",
        "--output-prefix",
        default="table3_both_paper_canonical_with_image_refs",
    )
    args = parser.parse_args()

    if args.eval_workers < 1:
        parser.error("--eval_workers must be at least 1")

    models = list(args.models) if args.models else list(PAPER_TABLE3_MODELS)
    if args.include_image_references:
        for model in TABLE3_IMAGE_REFERENCE_MODELS:
            if model not in models:
                models.append(model)
    langs = LANGS if args.lang == "both" else (args.lang,)

    report = build_and_write_manifest(models, langs, infill_matcher=args.infill_matcher)
    print_manifest_report(report)

    must_be_complete = args.require_complete or args.evaluate
    if must_be_complete and not report["complete"]:
        raise SystemExit(
            "Canonical coverage is incomplete. Rerun only the rows in "
            f"{CANONICAL_DIR / 'table3_missing_predictions.csv'} before evaluation."
        )

    if not args.evaluate:
        return

    run_canonical_evaluation(args, models)


def build_and_write_manifest(
    models: list[str],
    langs: Iterable[str],
    infill_matcher: str = SOURCE_FAITHFUL_MATCHER,
) -> dict[str, Any]:
    ensure_dir(CANONICAL_DIR)
    source_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    source_errors: list[dict[str, Any]] = []

    eligibility_by_task_lang: dict[tuple[str, str], list[SourceEligibility]] = {}
    for lang in langs:
        for task in SUPPORTED_TASKS:
            eligibility = build_source_eligibility(task, lang, infill_matcher=infill_matcher)
            eligibility_by_task_lang[(task, lang)] = eligibility
            for item in eligibility:
                row = {
                    "task": task,
                    "lang": lang,
                    "sample_id": item.sample_id,
                    "eligible": item.eligible,
                    "target_count": item.target_count,
                    "source_status": item.status,
                    "source_issue": item.issue,
                }
                source_rows.append(row)
                if item.status == "source_error":
                    source_errors.append(row)

    for model in models:
        for lang in langs:
            for task in SUPPORTED_TASKS:
                eligible = [item for item in eligibility_by_task_lang[(task, lang)] if item.eligible]
                for condition in SUPPORTED_CONDITIONS:
                    for item in eligible:
                        input_path = model_input_path(model, task, condition, lang, item.sample_id)
                        pred_path = prediction_dir(task, condition, lang, model) / f"{item.sample_id}.json"
                        status, raw_nonempty = prediction_status(pred_path)
                        if not input_path.exists():
                            status = "missing_input"
                        manifest_rows.append(
                            {
                                "model": model,
                                "task": task,
                                "lang": lang,
                                "condition": condition,
                                "sample_id": item.sample_id,
                                "target_count": item.target_count,
                                "input_path": str(input_path),
                                "prediction_path": str(pred_path),
                                "prediction_status": status,
                                "raw_response_nonempty": raw_nonempty,
                                "retry_recommended": status != "ready",
                            }
                        )

    missing_rows = [row for row in manifest_rows if row["retry_recommended"]]
    coverage_rows = summarize_manifest(manifest_rows)
    pair_rows = summarize_pairs(manifest_rows)

    write_csv(CANONICAL_DIR / "table3_source_eligibility.csv", source_rows, SOURCE_FIELDS)
    write_json(CANONICAL_DIR / "table3_source_eligibility.json", source_rows)
    write_csv(CANONICAL_DIR / "table3_evaluation_manifest.csv", manifest_rows, MANIFEST_FIELDS)
    write_json(CANONICAL_DIR / "table3_evaluation_manifest.json", manifest_rows)
    write_csv(CANONICAL_DIR / "table3_missing_predictions.csv", missing_rows, MANIFEST_FIELDS)
    write_json(CANONICAL_DIR / "table3_missing_predictions.json", missing_rows)
    write_csv(
        CANONICAL_DIR / "table3_coverage_summary.csv",
        coverage_rows,
        [
            "model",
            "task",
            "lang",
            "condition",
            "eligible_count",
            "ready_count",
            "missing_count",
            "complete",
        ],
    )
    write_json(CANONICAL_DIR / "table3_coverage_summary.json", coverage_rows)
    write_csv(
        CANONICAL_DIR / "table3_pair_coverage_summary.csv",
        pair_rows,
        [
            "model",
            "task",
            "lang",
            "eligible_count",
            "filled_ready_count",
            "template_ready_count",
            "paired_ready_count",
            "filled_only_count",
            "template_only_count",
            "complete",
        ],
    )
    write_json(CANONICAL_DIR / "table3_pair_coverage_summary.json", pair_rows)
    write_json(CANONICAL_DIR / "table3_source_errors.json", source_errors)

    return {
        "source_error_count": len(source_errors),
        "missing_prediction_count": len(missing_rows),
        "manifest_row_count": len(manifest_rows),
        "complete": not source_errors and not missing_rows,
    }


def build_source_eligibility(
    task: str,
    lang: str,
    infill_matcher: str = SOURCE_FAITHFUL_MATCHER,
) -> list[SourceEligibility]:
    paths = workflow_paths(lang)
    base_ids = [int(path.stem) for path in iter_numeric_files(paths.html_empty, ".html")]
    results: list[SourceEligibility] = []

    for sample_id in base_ids:
        common = [
            paths.html_empty / f"{sample_id}.html",
            paths.html_filled / f"{sample_id}.html",
        ]
        if task == "schema":
            required = common + [
                paths.json_empty / f"{sample_id}.json",
                paths.json_filled / f"{sample_id}.json",
            ]
            missing = missing_paths(required)
            if missing:
                results.append(SourceEligibility(sample_id, False, 0, "source_error", format_missing(missing)))
            else:
                results.append(SourceEligibility(sample_id, True, 1, "eligible"))
            continue

        if task == "alignment":
            meta_path = paths.meta / f"{sample_id}.json"
            placeholder_path = paths.placeholder_html / f"{sample_id}.html"
            missing = missing_paths(common + [meta_path, placeholder_path])
            if missing:
                results.append(SourceEligibility(sample_id, False, 0, "source_error", format_missing(missing)))
                continue
            try:
                target_count = len(expand_meta(read_json(meta_path)))
            except Exception as exc:
                results.append(SourceEligibility(sample_id, False, 0, "source_error", f"invalid meta: {exc}"))
                continue
            status = "eligible" if target_count else "ineligible_no_targets"
            results.append(SourceEligibility(sample_id, bool(target_count), target_count, status))
            continue

        if task == "infill":
            context_path = paths.context / f"{sample_id}.txt"
            placeholder_path = paths.placeholder_html / f"{sample_id}.html"
            required = common + [context_path, placeholder_path]
            missing = missing_paths(required)
            if missing:
                results.append(SourceEligibility(sample_id, False, 0, "source_error", format_missing(missing)))
                continue
            try:
                target_count = count_expected_fill_slots(
                    read_text(paths.html_filled / f"{sample_id}.html"),
                    read_text(placeholder_path),
                    matcher=infill_matcher,
                )
            except Exception as exc:
                results.append(SourceEligibility(sample_id, False, 0, "source_error", f"invalid infill source: {exc}"))
                continue
            status = "eligible" if target_count else "ineligible_no_targets"
            results.append(SourceEligibility(sample_id, bool(target_count), target_count, status))
            continue

        raise ValueError(f"Unsupported task: {task}")

    return results


def model_input_path(model: str, task: str, condition: str, lang: str, sample_id: int) -> Path:
    if model in TABLE3_IMAGE_REFERENCE_MODELS:
        return rendered_image_dir(condition, lang) / f"{sample_id}.png"
    paths = workflow_paths(lang)
    return (paths.html_filled if condition == "filled" else paths.html_empty) / f"{sample_id}.html"


def prediction_status(path: Path) -> tuple[str, bool]:
    if not path.exists():
        return "missing", False
    try:
        value = read_json(path)
    except Exception:
        return "invalid_json", False
    if not isinstance(value, dict):
        return "non_object_json", False
    raw_response = value.get("raw_response", "")
    if raw_response is None:
        return "empty_response", False
    if not str(raw_response).strip():
        return "empty_response", False
    return "ready", True


def summarize_manifest(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["model"], row["task"], row["lang"], row["condition"])].append(row)

    result = []
    for key, group in grouped.items():
        ready = sum(row["prediction_status"] == "ready" for row in group)
        result.append(
            {
                "model": key[0],
                "task": key[1],
                "lang": key[2],
                "condition": key[3],
                "eligible_count": len(group),
                "ready_count": ready,
                "missing_count": len(group) - ready,
                "complete": ready == len(group),
            }
        )
    return sorted(result, key=lambda row: (row["model"], row["task"], row["lang"], row["condition"]))


def summarize_pairs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    eligible: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for row in rows:
        key = (row["model"], row["task"], row["lang"])
        sample_id = int(row["sample_id"])
        eligible[key].add(sample_id)
        if row["prediction_status"] == "ready":
            grouped[key][row["condition"]].add(sample_id)

    result = []
    for key in sorted(eligible):
        filled = grouped[key]["filled"]
        template = grouped[key]["empty"]
        expected = eligible[key]
        result.append(
            {
                "model": key[0],
                "task": key[1],
                "lang": key[2],
                "eligible_count": len(expected),
                "filled_ready_count": len(filled),
                "template_ready_count": len(template),
                "paired_ready_count": len(filled & template),
                "filled_only_count": len(filled - template),
                "template_only_count": len(template - filled),
                "complete": filled == expected and template == expected,
            }
        )
    return result


def run_canonical_evaluation(args: argparse.Namespace, models: list[str]) -> None:
    coverage = discover_coverage(args.lang, models)
    runnable = [row for row in coverage if int(row["prediction_count"]) > 0]
    evaluator_args = SimpleNamespace(
        eval_workers=args.eval_workers,
        schema_metric=args.schema_metric,
        infill_matcher=args.infill_matcher,
        resume_from_details=args.resume_from_details,
    )
    scripts = {
        "schema": "table3_comparative_eval/eval_schema.py",
        "alignment": "table3_comparative_eval/eval_alignment.py",
        "infill": "table3_comparative_eval/eval_infill.py",
    }
    failures = run_evaluators(runnable, evaluator_args, scripts)
    if failures:
        path = CANONICAL_DIR / "table3_canonical_eval_failures.json"
        write_json(path, {"failures": failures})
        raise SystemExit(f"Canonical evaluation failed; see {path}")

    audit_rows = audit_detail_coverage(
        models,
        LANGS if args.lang == "both" else (args.lang,),
        args.schema_metric,
        args.infill_matcher,
    )
    audit_path = CANONICAL_DIR / "table3_detail_pair_audit.csv"
    write_csv(
        audit_path,
        audit_rows,
        [
            "model",
            "task",
            "lang",
            "expected_count",
            "filled_count",
            "template_count",
            "paired_count",
            "filled_missing_ids",
            "template_missing_ids",
            "filled_extra_ids",
            "template_extra_ids",
            "filled_duplicate_ids",
            "template_duplicate_ids",
            "complete",
        ],
    )
    write_json(CANONICAL_DIR / "table3_detail_pair_audit.json", audit_rows)
    if not all(row["complete"] for row in audit_rows):
        raise SystemExit(f"Evaluator detail coverage is not canonical; see {audit_path}")

    cmd = [
        sys.executable,
        "table3_comparative_eval/aggregate_table3.py",
        "--lang",
        args.lang,
        "--schema_metric",
        args.schema_metric,
        "--infill_matcher",
        args.infill_matcher,
        "--output_prefix",
        args.output_prefix,
        "--models",
        *models,
    ]
    if any(model in TABLE3_IMAGE_REFERENCE_MODELS for model in models):
        cmd.append("--image_reference_rows")
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def audit_detail_coverage(
    models: list[str],
    langs: Iterable[str],
    schema_metric: str,
    infill_matcher: str = SOURCE_FAITHFUL_MATCHER,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model in models:
        for task in SUPPORTED_TASKS:
            for lang in langs:
                expected = {
                    item.sample_id
                    for item in build_source_eligibility(task, lang, infill_matcher=infill_matcher)
                    if item.eligible
                }
                by_condition: dict[str, tuple[set[int], list[int]]] = {}
                for condition in SUPPORTED_CONDITIONS:
                    detail_path = detail_file(task, condition, lang, model, schema_metric)
                    ids = detail_ids(detail_path)
                    counts = Counter(ids)
                    by_condition[condition] = (set(ids), sorted(sample_id for sample_id, count in counts.items() if count > 1))

                template, template_duplicates = by_condition["empty"]
                filled, filled_duplicates = by_condition["filled"]
                complete = (
                    template == expected
                    and filled == expected
                    and not template_duplicates
                    and not filled_duplicates
                )
                rows.append(
                    {
                        "model": model,
                        "task": task,
                        "lang": lang,
                        "expected_count": len(expected),
                        "filled_count": len(filled),
                        "template_count": len(template),
                        "paired_count": len(filled & template),
                        "filled_missing_ids": format_ids(expected - filled),
                        "template_missing_ids": format_ids(expected - template),
                        "filled_extra_ids": format_ids(filled - expected),
                        "template_extra_ids": format_ids(template - expected),
                        "filled_duplicate_ids": format_ids(filled_duplicates),
                        "template_duplicate_ids": format_ids(template_duplicates),
                        "complete": complete,
                    }
                )
    return rows


def detail_file(task: str, condition: str, lang: str, model: str, schema_metric: str) -> Path:
    model_name = model.replace("/", "_").replace("-", "_")
    suffix = f"_{schema_metric}" if task == "schema" else ""
    return details_dir() / f"{task}_{condition}_{lang}_{model_name}{suffix}.csv"


def detail_ids(path: Path) -> list[int]:
    if not path.exists():
        return []
    ids: list[int] = []
    for row in read_csv(path):
        try:
            ids.append(int(row["sample_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return ids


def missing_paths(paths: Iterable[Path]) -> list[Path]:
    return [path for path in paths if not path.exists()]


def format_missing(paths: Iterable[Path]) -> str:
    return "; ".join(str(path) for path in paths)


def format_ids(ids: Iterable[int]) -> str:
    return ",".join(str(sample_id) for sample_id in sorted(ids))


def print_manifest_report(report: dict[str, Any]) -> None:
    print(
        "canonical manifest "
        f"rows={report['manifest_row_count']} "
        f"source_errors={report['source_error_count']} "
        f"missing_predictions={report['missing_prediction_count']} "
        f"complete={report['complete']}"
    )
    print(f"Manifest: {CANONICAL_DIR / 'table3_evaluation_manifest.csv'}")
    print(f"Retry queue: {CANONICAL_DIR / 'table3_missing_predictions.csv'}")


if __name__ == "__main__":
    main()
