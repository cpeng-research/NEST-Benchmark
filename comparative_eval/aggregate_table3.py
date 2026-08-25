from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comparative_eval.config import SUPPORTED_MODELS, summaries_dir, TABLE3_ROOT
from comparative_eval.metrics.infill import SOURCE_FAITHFUL_MATCHER, SUPPORTED_INFILL_MATCHERS
from comparative_eval.utils.io_utils import read_json, write_csv, write_json, write_text


TASK_LABELS = {
    "schema": "Task 1: Schema Parsing",
    "alignment": "Task 2: CH Alignment",
    "infill": "Task 3: Infilling",
}
SUPPORTED_LANGS = ("en", "zh")
COMBINED_LANG = "both"
IMAGE_REFERENCE_SUFFIX = "-image"
IMAGE_REFERENCE_LABEL = "Image-input baselines (reference)"


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate Table 3 summaries.")
    parser.add_argument("--lang", default=COMBINED_LANG, choices=[COMBINED_LANG, *SUPPORTED_LANGS])
    parser.add_argument("--models", nargs="*", default=list(SUPPORTED_MODELS))
    parser.add_argument("--schema_metric", choices=["py_tree", "py_fast", "cpp"], default="py_tree")
    parser.add_argument(
        "--infill_matcher",
        "--infill-matcher",
        choices=SUPPORTED_INFILL_MATCHERS,
        default=SOURCE_FAITHFUL_MATCHER,
    )
    parser.add_argument(
        "--output_prefix",
        default=None,
        help="Output filename prefix under the selected results directory. Defaults to table3_<lang>.",
    )
    parser.add_argument("--summaries_dir", "--summaries-dir", dest="summaries_dir", type=Path, default=summaries_dir())
    parser.add_argument("--output_dir", "--output-dir", dest="output_dir", type=Path, default=TABLE3_ROOT / "results")
    parser.add_argument(
        "--image_reference_rows",
        "--image-reference-rows",
        action="store_true",
        help=(
            "Render models ending in '-image' as an image-input reference block and exclude "
            "them from Task Average / Global Average Drop."
        ),
    )
    args = parser.parse_args()

    validate_infill_summary_versions(args.models, args.lang, args.infill_matcher, args.summaries_dir)

    main_rows = []
    reference_rows = []
    diffs_by_task: dict[str, list[float]] = defaultdict(list)
    values_by_task_condition: dict[tuple[str, str], list[float]] = defaultdict(list)

    for model in args.models:
        row = {"model": model}
        is_reference = args.image_reference_rows and is_image_reference_model(model)
        for task in ("schema", "alignment", "infill"):
            filled = load_score(
                task,
                "filled",
                args.lang,
                model,
                schema_metric=args.schema_metric,
                summaries_root=args.summaries_dir,
            )
            empty = load_score(
                task,
                "empty",
                args.lang,
                model,
                schema_metric=args.schema_metric,
                summaries_root=args.summaries_dir,
            )
            diff = empty - filled if filled is not None and empty is not None else None
            row[f"{task}_filled"] = pct(filled)
            row[f"{task}_templ"] = pct(empty)
            row[f"{task}_diff"] = pct(diff, signed=True)
            if not is_reference and filled is not None:
                values_by_task_condition[(task, "filled")].append(filled)
            if not is_reference and empty is not None:
                values_by_task_condition[(task, "empty")].append(empty)
            if not is_reference and diff is not None:
                diffs_by_task[task].append(diff)
        if is_reference:
            reference_rows.append(row)
        else:
            main_rows.append(row)

    avg_row = {"model": "Task Average"}
    for task in ("schema", "alignment", "infill"):
        avg_filled = mean(values_by_task_condition[(task, "filled")])
        avg_empty = mean(values_by_task_condition[(task, "empty")])
        avg_diff = mean(diffs_by_task[task])
        avg_row[f"{task}_filled"] = pct(avg_filled)
        avg_row[f"{task}_templ"] = pct(avg_empty)
        avg_row[f"{task}_diff"] = pct(avg_diff, signed=True)
    rows = [*main_rows, avg_row, *reference_rows]
    reference_models = {row["model"] for row in reference_rows}

    global_drop = mean([mean(diffs_by_task[task]) for task in ("schema", "alignment", "infill") if diffs_by_task[task]])

    fieldnames = [
        "model",
        "schema_filled", "schema_templ", "schema_diff",
        "alignment_filled", "alignment_templ", "alignment_diff",
        "infill_filled", "infill_templ", "infill_diff",
    ]
    output_prefix = args.output_prefix or f"table3_{args.lang}"
    csv_path = args.output_dir / f"{output_prefix}.csv"
    write_csv(csv_path, rows, fieldnames)
    write_json(
        args.output_dir / f"{output_prefix}.json",
        {
            "rows": rows,
            "global_average_drop": global_drop,
            "schema_metric": args.schema_metric,
            "infill_matcher": args.infill_matcher,
            "image_reference_rows": args.image_reference_rows,
            "reference_models": sorted(reference_models),
        },
    )
    write_text(args.output_dir / f"{output_prefix}.md", markdown_table(rows, global_drop, reference_models))
    write_text(args.output_dir / f"{output_prefix}.tex", latex_table(rows, global_drop, reference_models))
    print(f"Wrote {csv_path}")
    print(f"Global Average Drop: {pct(global_drop, signed=True)}")


def validate_infill_summary_versions(
    models: list[str],
    lang: str,
    expected_matcher: str,
    summaries_root: Path,
) -> None:
    langs = SUPPORTED_LANGS if lang == COMBINED_LANG else (lang,)
    mismatches: list[str] = []
    for model in models:
        for condition in ("filled", "empty"):
            for item_lang in langs:
                summary = load_summary(
                    "infill",
                    condition,
                    item_lang,
                    model,
                    summaries_root=summaries_root,
                )
                if summary is None:
                    continue
                actual = str(summary.get("metric_version") or "")
                if actual != expected_matcher:
                    mismatches.append(f"{model}/{condition}/{item_lang}: {actual or 'unversioned'}")
    if mismatches:
        preview = "; ".join(mismatches[:10])
        if len(mismatches) > 10:
            preview += f"; ... (+{len(mismatches) - 10} more)"
        raise SystemExit(
            f"Infilling summary version mismatch; expected {expected_matcher}: {preview}"
        )


def load_score(
    task: str,
    condition: str,
    lang: str,
    model: str,
    schema_metric: str = "py_tree",
    summaries_root: Path | None = None,
) -> float | None:
    if lang == COMBINED_LANG:
        return load_combined_score(task, condition, model, schema_metric, summaries_root)

    data = load_summary(task, condition, lang, model, schema_metric, summaries_root)
    if data is None or int(data.get("sample_count", 0)) <= 0:
        return None
    return float(data.get("score", 0.0))


def load_combined_score(
    task: str,
    condition: str,
    model: str,
    schema_metric: str = "py_tree",
    summaries_root: Path | None = None,
) -> float | None:
    summaries = [
        data
        for lang in SUPPORTED_LANGS
        if (data := load_summary(task, condition, lang, model, schema_metric, summaries_root)) is not None
        and int(data.get("sample_count", 0)) > 0
    ]
    if not summaries:
        return None

    totals = [float(data.get("total", 0.0)) for data in summaries]
    total = sum(totals)
    if total > 0 and all("correct" in data and "total" in data for data in summaries):
        return sum(float(data.get("correct", 0.0)) for data in summaries) / total

    sample_count = sum(int(data.get("sample_count", 0)) for data in summaries)
    if sample_count <= 0:
        return None
    return sum(float(data.get("score", 0.0)) * int(data.get("sample_count", 0)) for data in summaries) / sample_count


def load_summary(
    task: str,
    condition: str,
    lang: str,
    model: str,
    schema_metric: str = "py_tree",
    summaries_root: Path | None = None,
) -> dict | None:
    root = summaries_root or summaries_dir()
    if task == "schema":
        path = root / f"{task}_{condition}_{lang}_{clean_model(model)}_{schema_metric}.json"
    else:
        path = root / f"{task}_{condition}_{lang}_{clean_model(model)}.json"
    if not path.exists():
        return None
    data = read_json(path)
    return data


def clean_model(model: str) -> str:
    return model.replace("/", "_").replace("-", "_")


def is_image_reference_model(model: str) -> bool:
    return model.endswith(IMAGE_REFERENCE_SUFFIX)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def pct(value: float | None, signed: bool = False) -> str:
    if value is None:
        return ""
    number = value * 100
    if signed and number > 0:
        return f"+{number:.1f}%"
    return f"{number:.1f}%"


def markdown_table(rows: list[dict[str, str]], global_drop: float | None, reference_models: set[str] | None = None) -> str:
    reference_models = reference_models or set()
    headers = [
        "Model",
        "Schema Filled", "Schema Templ.", "Schema Diff.",
        "Align Filled", "Align Templ.", "Align Diff.",
        "Infill Filled", "Infill Templ.", "Infill Diff.",
    ]
    keys = [
        "model",
        "schema_filled", "schema_templ", "schema_diff",
        "alignment_filled", "alignment_templ", "alignment_diff",
        "infill_filled", "infill_templ", "infill_diff",
    ]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    inserted_reference_label = False
    inserted_global_drop = False
    for row in rows:
        if row.get("model", "") in reference_models and not inserted_reference_label:
            suffix = " (main rows only)" if reference_models else ""
            lines.append("")
            lines.append(f"Global Average Drop{suffix}: {pct(global_drop, signed=True)}")
            lines.append("")
            inserted_global_drop = True
            lines.append("| " + IMAGE_REFERENCE_LABEL + " | " + " | ".join([""] * (len(headers) - 1)) + " |")
            inserted_reference_label = True
        lines.append("| " + " | ".join(str(row.get(key, "")) for key in keys) + " |")
    if not inserted_global_drop:
        lines.append("")
        lines.append(f"Global Average Drop: {pct(global_drop, signed=True)}")
    return "\n".join(lines) + "\n"


def latex_table(rows: list[dict[str, str]], global_drop: float | None, reference_models: set[str] | None = None) -> str:
    reference_models = reference_models or set()
    lines = [
        r"\begin{tabular}{lrrrrrrrrr}",
        r"\toprule",
        r"Model & \multicolumn{3}{c}{Task 1} & \multicolumn{3}{c}{Task 2} & \multicolumn{3}{c}{Task 3} \\",
        r" & Filled & Templ. & Diff. & Filled & Templ. & Diff. & Filled & Templ. & Diff. \\",
        r"\midrule",
    ]
    inserted_reference_label = False
    inserted_global_drop = False
    for row in rows:
        if row.get("model", "") in reference_models and not inserted_reference_label:
            global_label = "Global Average Drop (main rows only)" if reference_models else "Global Average Drop (across all tasks)"
            lines.extend([
                r"\midrule",
                rf"\multicolumn{{10}}{{c}}{{{global_label}: {pct(global_drop, signed=True)}}} \\",
                r"\midrule",
                rf"\multicolumn{{10}}{{l}}{{\textit{{{IMAGE_REFERENCE_LABEL}}}}} \\",
            ])
            inserted_global_drop = True
            inserted_reference_label = True
        lines.append(
            f"{row.get('model','')} & {row.get('schema_filled','')} & {row.get('schema_templ','')} & {row.get('schema_diff','')} "
            f"& {row.get('alignment_filled','')} & {row.get('alignment_templ','')} & {row.get('alignment_diff','')} "
            f"& {row.get('infill_filled','')} & {row.get('infill_templ','')} & {row.get('infill_diff','')} \\\\"
        )
    if not inserted_global_drop:
        lines.extend([
            r"\midrule",
            rf"\multicolumn{{10}}{{c}}{{Global Average Drop (across all tasks): {pct(global_drop, signed=True)}}} \\",
        ])
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    main()
