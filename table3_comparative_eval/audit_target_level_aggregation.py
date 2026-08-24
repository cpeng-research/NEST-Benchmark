from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from table3_comparative_eval.config import TABLE3_ROOT, summaries_dir
from table3_comparative_eval.metrics.infill import SOURCE_FAITHFUL_MATCHER
from table3_comparative_eval.utils.io_utils import read_json, write_csv, write_json


PAPER_MODELS = (
    "gpt-5",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-3.5-turbo",
    "Llama-3.1-8B-Instruct",
    "Qwen2.5-7B-Instruct",
    "Gemma-2-9B-it",
    "Mistral-7B-Instruct-v0.3",
)
TASKS = ("alignment", "infill")
LANGS = ("en", "zh")
CONDITIONS = ("filled", "empty")
TASK_COLUMNS = {
    "alignment": "alignment",
    "infill": "infill",
}
TARGET_DEFINITIONS = {
    "alignment": "field-header alignment relation",
    "infill": "annotation-defined physical filling cell with observable text or control content",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit the target-level aggregation used by the paper's Table 3."
    )
    parser.add_argument("--summaries-dir", type=Path, default=summaries_dir())
    parser.add_argument(
        "--table3-csv",
        type=Path,
        default=TABLE3_ROOT / "results/table3_both_paper_canonical_with_image_refs_cpp_v3.csv",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=TABLE3_ROOT / "results/canonical/target_level_aggregation_inventory.csv",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=TABLE3_ROOT / "results/canonical/target_level_aggregation_audit.json",
    )
    args = parser.parse_args()

    summaries = load_summaries(args.summaries_dir)
    inventory = build_inventory(summaries)
    reconstructed = reconstruct_table3(summaries)
    expected = load_table3_task_average(args.table3_csv)
    comparisons = compare_with_table3(reconstructed, expected)

    write_csv(
        args.output_csv,
        inventory,
        [
            "task",
            "target_definition",
            "language",
            "evaluable_tables_per_condition",
            "targets_per_condition",
            "conditions_verified",
            "models_verified",
            "metric_version",
        ],
    )
    write_json(
        args.output_json,
        {
            "paper_models": list(PAPER_MODELS),
            "aggregation": (
                "For each model and condition, pool correct and total targets across English and Chinese; "
                "then average the eight bilingual model-level accuracies. Delta is Template minus Filled."
            ),
            "target_inventory": inventory,
            "reconstructed_table3": reconstructed,
            "paper_task_average": expected,
            "rounded_comparisons": comparisons,
            "all_rounded_values_match": all(item["matches"] for item in comparisons),
        },
    )

    if not all(item["matches"] for item in comparisons):
        raise SystemExit("Target-level reconstruction does not match the canonical Table 3 CSV.")

    print(f"Wrote {args.output_csv}")
    print(f"Wrote {args.output_json}")
    for item in comparisons:
        print(
            f"{item['task']} {item['measure']}: "
            f"reconstructed={item['reconstructed_percent']:.6f}% "
            f"paper={item['paper_percent']:.1f}%"
        )


def load_summaries(root: Path) -> dict[tuple[str, str, str, str], dict]:
    summaries: dict[tuple[str, str, str, str], dict] = {}
    for task in TASKS:
        for condition in CONDITIONS:
            for lang in LANGS:
                for model in PAPER_MODELS:
                    path = root / f"{task}_{condition}_{lang}_{clean_model(model)}.json"
                    if not path.exists():
                        raise FileNotFoundError(f"Missing summary: {path}")
                    data = read_json(path)
                    if task == "infill" and data.get("metric_version") != SOURCE_FAITHFUL_MATCHER:
                        raise ValueError(
                            f"Expected {SOURCE_FAITHFUL_MATCHER} in {path}, got "
                            f"{data.get('metric_version') or 'unversioned'}"
                        )
                    summaries[(task, condition, lang, model)] = data
    return summaries


def build_inventory(summaries: dict[tuple[str, str, str, str], dict]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for task in TASKS:
        for lang in LANGS:
            totals = {
                int(summaries[(task, condition, lang, model)]["total"])
                for condition in CONDITIONS
                for model in PAPER_MODELS
            }
            sample_counts = {
                int(summaries[(task, condition, lang, model)]["sample_count"])
                for condition in CONDITIONS
                for model in PAPER_MODELS
            }
            if len(totals) != 1 or len(sample_counts) != 1:
                raise ValueError(
                    f"Inconsistent target coverage for task={task}, lang={lang}: "
                    f"totals={sorted(totals)}, sample_counts={sorted(sample_counts)}"
                )
            rows.append(
                {
                    "task": "CHA" if task == "alignment" else "Infilling",
                    "target_definition": TARGET_DEFINITIONS[task],
                    "language": "English" if lang == "en" else "Chinese",
                    "evaluable_tables_per_condition": next(iter(sample_counts)),
                    "targets_per_condition": next(iter(totals)),
                    "conditions_verified": len(CONDITIONS),
                    "models_verified": len(PAPER_MODELS),
                    "metric_version": SOURCE_FAITHFUL_MATCHER if task == "infill" else "CGA",
                }
            )
    return rows


def reconstruct_table3(
    summaries: dict[tuple[str, str, str, str], dict]
) -> dict[str, dict[str, object]]:
    reconstructed: dict[str, dict[str, object]] = {}
    for task in TASKS:
        model_scores: dict[str, dict[str, float]] = {}
        for model in PAPER_MODELS:
            condition_scores: dict[str, float] = {}
            for condition in CONDITIONS:
                correct = sum(
                    int(summaries[(task, condition, lang, model)]["correct"])
                    for lang in LANGS
                )
                total = sum(
                    int(summaries[(task, condition, lang, model)]["total"])
                    for lang in LANGS
                )
                condition_scores[condition] = correct / total
            condition_scores["delta"] = condition_scores["empty"] - condition_scores["filled"]
            model_scores[model] = condition_scores

        task_average = {
            measure: sum(scores[measure] for scores in model_scores.values()) / len(model_scores)
            for measure in ("filled", "empty", "delta")
        }
        reconstructed[task] = {
            "model_scores": model_scores,
            "task_average": task_average,
        }
    return reconstructed


def load_table3_task_average(path: Path) -> dict[str, dict[str, float]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        row = next(item for item in csv.DictReader(handle) if item["model"] == "Task Average")
    result: dict[str, dict[str, float]] = {}
    for task, prefix in TASK_COLUMNS.items():
        result[task] = {
            "filled": parse_percent(row[f"{prefix}_filled"]),
            "empty": parse_percent(row[f"{prefix}_templ"]),
            "delta": parse_percent(row[f"{prefix}_diff"]),
        }
    return result


def compare_with_table3(
    reconstructed: dict[str, dict[str, object]],
    expected: dict[str, dict[str, float]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for task in TASKS:
        task_average = reconstructed[task]["task_average"]
        assert isinstance(task_average, dict)
        for measure in ("filled", "empty", "delta"):
            reconstructed_percent = float(task_average[measure]) * 100
            paper_percent = expected[task][measure]
            rows.append(
                {
                    "task": "CHA" if task == "alignment" else "Infilling",
                    "measure": "template" if measure == "empty" else measure,
                    "reconstructed_percent": reconstructed_percent,
                    "paper_percent": paper_percent,
                    "matches": round(reconstructed_percent, 1) == paper_percent,
                }
            )
    return rows


def parse_percent(value: str) -> float:
    return float(value.strip().replace("%", "").replace("+", ""))


def clean_model(model: str) -> str:
    return model.replace("/", "_").replace("-", "_")


if __name__ == "__main__":
    main()
