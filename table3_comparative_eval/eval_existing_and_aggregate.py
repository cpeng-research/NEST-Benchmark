from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from table3_comparative_eval.config import (
    SUPPORTED_CONDITIONS,
    SUPPORTED_MODELS,
    SUPPORTED_TASKS,
    TABLE3_ROOT,
    prediction_dir,
)
from table3_comparative_eval.metrics.infill import SOURCE_FAITHFUL_MATCHER, SUPPORTED_INFILL_MATCHERS
from table3_comparative_eval.utils.io_utils import iter_numeric_files, write_csv, write_json


SUPPORTED_LANGS = ("en", "zh")
COMBINED_LANG = "both"
PAPER_TABLE3_MODELS = (
    "gpt-5",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-3.5-turbo",
    "Llama-3.1-8B-Instruct",
    "Qwen2.5-7B-Instruct",
    "Gemma-2-9B-it",
    "Mistral-7B-Instruct-v0.3",
)
TABLE3_IMAGE_REFERENCE_MODELS = (
    "gpt-5.4-image",
    "gpt-5.4-mini-image",
    "gpt-5.4-nano-image",
)
MODEL_GROUPS = {
    "paper_table3": PAPER_TABLE3_MODELS,
    "paper_table3_with_image_refs": PAPER_TABLE3_MODELS + TABLE3_IMAGE_REFERENCE_MODELS,
    "all_supported": SUPPORTED_MODELS,
}
ALL_EXISTING_MODEL_GROUP = "all_existing"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate only existing Table 3 predictions, then create a partial aggregate table."
    )
    parser.add_argument("--lang", default=COMBINED_LANG, choices=[COMBINED_LANG, *SUPPORTED_LANGS])
    parser.add_argument(
        "--model_group",
        "--model-group",
        choices=sorted([*MODEL_GROUPS, ALL_EXISTING_MODEL_GROUP]),
        default="paper_table3",
        help="Model group to evaluate when --models is not provided.",
    )
    parser.add_argument("--models", nargs="*", default=None, help="Explicit model list. Overrides --model_group.")
    parser.add_argument("--schema_metric", choices=["py_tree", "py_fast", "cpp"], default="py_tree")
    parser.add_argument(
        "--infill_matcher",
        "--infill-matcher",
        dest="infill_matcher",
        choices=SUPPORTED_INFILL_MATCHERS,
        default=SOURCE_FAITHFUL_MATCHER,
    )
    parser.add_argument(
        "--output_prefix",
        default=None,
        help="Output filename prefix under table3_comparative_eval/results. Defaults to table3_<lang>_partial.",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Only report discovered prediction coverage; do not run evaluators or aggregation.",
    )
    parser.add_argument(
        "--resume_from_details",
        "--resume-from-details",
        action="store_true",
        help="Reuse current per-sample rows in results/details when their prediction file fingerprint is unchanged.",
    )
    parser.add_argument(
        "--eval_workers",
        "--eval-workers",
        type=int,
        default=4,
        help="Maximum number of evaluator subprocesses to run in parallel.",
    )
    parser.add_argument(
        "--image_reference_rows",
        "--image-reference-rows",
        action="store_true",
        help="Render image-input models as reference rows and exclude them from aggregate averages.",
    )
    args = parser.parse_args()
    if args.models is not None:
        args.models = list(args.models)
    elif args.model_group == ALL_EXISTING_MODEL_GROUP:
        args.models = discover_existing_models(args.lang)
    else:
        args.models = list(MODEL_GROUPS[args.model_group])

    coverage_rows = discover_coverage(args.lang, args.models)
    write_coverage(args.lang, coverage_rows)
    print_coverage(coverage_rows)

    runnable = [row for row in coverage_rows if int(row["prediction_count"]) > 0]
    if args.dry_run:
        return
    if not runnable:
        print("No existing predictions found. Nothing to evaluate.")
        return

    output_prefix = args.output_prefix or f"table3_{args.lang}_partial"
    scripts = {
        "schema": "table3_comparative_eval/eval_schema.py",
        "alignment": "table3_comparative_eval/eval_alignment.py",
        "infill": "table3_comparative_eval/eval_infill.py",
    }
    failures = run_evaluators(runnable, args, scripts)

    if failures:
        failure_path = TABLE3_ROOT / "results" / f"{output_prefix}_eval_failures.json"
        write_json(failure_path, {"failures": failures})
        print(f"Wrote {failure_path}", flush=True)

    aggregate_cmd = [
        sys.executable,
        "table3_comparative_eval/aggregate_table3.py",
        "--lang",
        args.lang,
        "--schema_metric",
        args.schema_metric,
        "--infill_matcher",
        args.infill_matcher,
        "--output_prefix",
        output_prefix,
        "--models",
        *args.models,
    ]
    if args.image_reference_rows:
        aggregate_cmd.append("--image_reference_rows")
    print(" ".join(aggregate_cmd), flush=True)
    subprocess.run(aggregate_cmd, check=True)


def run_evaluators(
    runnable: list[dict[str, str | int]],
    args: argparse.Namespace,
    scripts: dict[str, str],
) -> list[dict[str, str | int]]:
    worker_count = max(1, int(args.eval_workers))
    print(f"Running {len(runnable)} evaluator jobs with {worker_count} workers.", flush=True)
    if worker_count == 1:
        return [failure for row in runnable if (failure := run_evaluator(row, args, scripts)) is not None]

    failures: list[dict[str, str | int]] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_row = {executor.submit(run_evaluator, row, args, scripts): row for row in runnable}
        for future in as_completed(future_to_row):
            row = future_to_row[future]
            try:
                failure = future.result()
            except Exception as exc:
                failure = {
                    "model": row["model"],
                    "task": row["task"],
                    "condition": row["condition"],
                    "lang": row["lang"],
                    "returncode": "exception",
                    "error": str(exc),
                }
                print(
                    "Warning: evaluator raised an exception; continuing with remaining combinations: "
                    f"{row['model']} | {row['task']} | {row['condition']} | {row['lang']} ({exc})",
                    flush=True,
                )
            if failure is not None:
                failures.append(failure)
    return failures


def run_evaluator(
    row: dict[str, str | int],
    args: argparse.Namespace,
    scripts: dict[str, str],
) -> dict[str, str | int] | None:
    task = str(row["task"])
    condition = str(row["condition"])
    model = str(row["model"])
    lang = str(row["lang"])
    cmd = [
        sys.executable,
        scripts[task],
        "--condition",
        condition,
        "--model",
        model,
        "--lang",
        lang,
    ]
    if task == "schema":
        cmd += ["--metric", args.schema_metric]
    elif task == "infill":
        cmd += ["--matcher", args.infill_matcher]
    if args.resume_from_details:
        cmd.append("--resume_from_details")

    print(" ".join(cmd), flush=True)
    result = subprocess.run(cmd, check=False)
    if result.returncode == 0:
        return None

    failure = {
        "model": model,
        "task": task,
        "condition": condition,
        "lang": lang,
        "returncode": result.returncode,
    }
    print(
        "Warning: evaluator failed; continuing with remaining combinations: "
        f"{model} | {task} | {condition} | {lang} (exit {result.returncode})",
        flush=True,
    )
    return failure


def discover_coverage(lang: str, models: list[str]) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    langs = SUPPORTED_LANGS if lang == COMBINED_LANG else (lang,)
    for model in models:
        for task in SUPPORTED_TASKS:
            for condition in SUPPORTED_CONDITIONS:
                for current_lang in langs:
                    pred_dir = prediction_dir(task, condition, current_lang, model)
                    files = iter_numeric_files(pred_dir, ".json")
                    ids = [int(path.stem) for path in files]
                    rows.append(
                        {
                            "model": model,
                            "task": task,
                            "condition": condition,
                            "lang": current_lang,
                            "prediction_count": len(files),
                            "first_id": min(ids) if ids else "",
                            "last_id": max(ids) if ids else "",
                            "prediction_dir": str(pred_dir),
                        }
                    )
    return rows


def discover_existing_models(lang: str) -> list[str]:
    prediction_root = TABLE3_ROOT / "predictions"
    langs = SUPPORTED_LANGS if lang == COMBINED_LANG else (lang,)
    discovered_dirs: set[str] = set()
    for task in SUPPORTED_TASKS:
        for condition in SUPPORTED_CONDITIONS:
            for current_lang in langs:
                parent = prediction_root / f"{task}_{condition}" / current_lang
                if not parent.exists():
                    continue
                for child in parent.iterdir():
                    if child.is_dir() and iter_numeric_files(child, ".json"):
                        discovered_dirs.add(child.name)

    known_by_dir = {model_dir_name(model): model for model in SUPPORTED_MODELS}
    ordered: list[str] = []
    for model in SUPPORTED_MODELS:
        if model_dir_name(model) in discovered_dirs:
            ordered.append(model)

    extras = sorted(
        pretty_model_name(model_dir)
        for model_dir in discovered_dirs
        if model_dir not in known_by_dir
    )
    return ordered + extras


def model_dir_name(model: str) -> str:
    return model.replace("/", "_").replace("-", "_")


def pretty_model_name(model_dir: str) -> str:
    if model_dir.startswith("gpt_") and model_dir.endswith("_image"):
        return model_dir.replace("_", "-")
    return model_dir


def write_coverage(lang: str, rows: list[dict[str, str | int]]) -> None:
    results_dir = TABLE3_ROOT / "results"
    fields = ["model", "task", "condition", "lang", "prediction_count", "first_id", "last_id", "prediction_dir"]
    write_csv(results_dir / f"table3_{lang}_prediction_coverage.csv", rows, fields)
    write_json(results_dir / f"table3_{lang}_prediction_coverage.json", {"rows": rows})


def print_coverage(rows: list[dict[str, str | int]]) -> None:
    print("Existing prediction coverage:", flush=True)
    for row in rows:
        count = int(row["prediction_count"])
        if count <= 0:
            continue
        print(
            f"  {row['model']} | {row['task']} | {row['condition']} | "
            f"{row['lang']}: {count} files ({row['first_id']}-{row['last_id']})",
            flush=True,
        )


if __name__ == "__main__":
    main()
