from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

try:
    from compute_stage3_iaa import (
        AnnotationFile,
        DEFAULT_EN_ANNOTATORS_XLSX,
        DEFAULT_ZH_GOLD_ANNOTATOR,
        calculate_label_scores,
        calculate_node_scores,
        canonical_json,
        discover_annotation_files,
        discover_annotators,
        ensure_dir,
        extract_node_paths,
        format_float,
        load_json,
        load_stage3_reference_annotators,
        mean,
        numeric_id,
        numeric_path_key,
        pct,
        resolve_stage3_reference_annotator,
        write_json,
    )
except ModuleNotFoundError:
    from IAA.compute_stage3_iaa import (
        AnnotationFile,
        DEFAULT_EN_ANNOTATORS_XLSX,
        DEFAULT_ZH_GOLD_ANNOTATOR,
        calculate_label_scores,
        calculate_node_scores,
        canonical_json,
        discover_annotation_files,
        discover_annotators,
        ensure_dir,
        extract_node_paths,
        format_float,
        load_json,
        load_stage3_reference_annotators,
        mean,
        numeric_id,
        numeric_path_key,
        pct,
        resolve_stage3_reference_annotator,
        write_json,
    )


DEFAULT_STAGE1_2 = ("stage1", "stage2")
DEFAULT_STAGE3 = "stage3"
DEFAULT_LANGS = ("en", "zh")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute IAA for NEST JSON annotation checks. "
            "stage1/2 use pairwise intersections between annotators; "
            "stage3 compares each available annotator file against workflow source JSON."
        )
    )
    parser.add_argument("--iaa_root", "--iaa-root", type=Path, default=Path("IAA"))
    parser.add_argument("--gold_root", "--gold-root", type=Path, default=Path("workflow/1-annotated_json"))
    parser.add_argument("--en_annotators_xlsx", "--en-annotators-xlsx", type=Path, default=DEFAULT_EN_ANNOTATORS_XLSX)
    parser.add_argument("--zh_gold_annotator", "--zh-gold-annotator", default=DEFAULT_ZH_GOLD_ANNOTATOR)
    parser.add_argument("--output_dir", "--output-dir", type=Path, default=Path("IAA/results"))
    parser.add_argument("--stage1_2", "--stage1-2", nargs="*", default=list(DEFAULT_STAGE1_2))
    parser.add_argument("--stage3", default=DEFAULT_STAGE3)
    parser.add_argument("--langs", nargs="*", default=list(DEFAULT_LANGS), choices=list(DEFAULT_LANGS))
    parser.add_argument(
        "--no_leaf_values",
        "--no-leaf-values",
        action="store_true",
        help="Ignore non-empty primitive leaf values when extracting node paths.",
    )
    parser.add_argument("--details_name", "--details-name", default="iaa_details.csv")
    parser.add_argument("--summary_name", "--summary-name", default="iaa_summary.csv")
    parser.add_argument("--json_name", "--json-name", default="iaa_summary.json")
    parser.add_argument("--dry_run", "--dry-run", action="store_true")
    args = parser.parse_args()

    include_leaf_values = not args.no_leaf_values
    detail_rows: list[dict[str, Any]] = []

    for stage in args.stage1_2:
        detail_rows.extend(evaluate_pairwise_stage(args.iaa_root / stage, stage, include_leaf_values))

    stage3_reference_annotators = load_stage3_reference_annotators(
        args.en_annotators_xlsx,
        zh_gold_annotator=args.zh_gold_annotator,
    )
    detail_rows.extend(
        evaluate_gold_stage(
            args.iaa_root / args.stage3,
            args.stage3,
            args.gold_root,
            reference_annotators=stage3_reference_annotators,
            zh_gold_annotator=args.zh_gold_annotator,
            langs=tuple(args.langs),
            include_leaf_values=include_leaf_values,
        )
    )

    summary_rows, summary_json = summarize(detail_rows)
    print_summary(summary_rows, detail_rows)
    if args.dry_run:
        return

    ensure_dir(args.output_dir)
    write_csv(args.output_dir / args.details_name, detail_rows, detail_fieldnames())
    write_csv(args.output_dir / args.summary_name, summary_rows, summary_fieldnames())
    write_json(args.output_dir / args.json_name, summary_json)
    print(f"Wrote {args.output_dir / args.details_name}")
    print(f"Wrote {args.output_dir / args.summary_name}")
    print(f"Wrote {args.output_dir / args.json_name}")


def evaluate_pairwise_stage(stage_dir: Path, stage: str, include_leaf_values: bool) -> list[dict[str, Any]]:
    annotators = discover_annotators(stage_dir)
    if len(annotators) < 2:
        return []

    rows: list[dict[str, Any]] = []
    for annotator_a, annotator_b in combinations(annotators, 2):
        files_a = direct_json_files(stage_dir / annotator_a)
        files_b = direct_json_files(stage_dir / annotator_b)
        common_ids = sorted(set(files_a) & set(files_b), key=lambda value: (numeric_id(value), value))
        for sample_id in common_ids:
            annotation_a, error_a = load_json(files_a[sample_id], missing_status="missing_annotation")
            annotation_b, error_b = load_json(files_b[sample_id], missing_status="missing_annotation")
            status = error_a or error_b or "ok"
            row = base_detail_row(
                stage=stage,
                comparison_type="annotator_pair",
                comparison_label=f"{annotator_a}__vs__{annotator_b}",
                annotator=annotator_a,
                reference=annotator_b,
                lang="en",
                sample_id=sample_id,
                annotation_path=files_a[sample_id],
                reference_path=files_b[sample_id],
                status=status,
            )
            if status == "ok":
                row.update(compare_json_annotations(annotation_a, annotation_b, include_leaf_values))
            else:
                row.update(empty_metric_values())
            rows.append(row)
    return rows


def evaluate_gold_stage(
    stage_dir: Path,
    stage: str,
    gold_root: Path,
    *,
    reference_annotators: dict[tuple[str, str], str],
    zh_gold_annotator: str,
    langs: tuple[str, ...],
    include_leaf_values: bool,
) -> list[dict[str, Any]]:
    annotators = discover_annotators(stage_dir)
    if not annotators:
        return []

    files = discover_annotation_files(
        stage_dir,
        annotators=annotators,
        langs=langs,
        allow_flat=False,
        flat_lang="en",
    )
    rows: list[dict[str, Any]] = []
    for item in files:
        rows.append(
            evaluate_stage3_file(
                item,
                stage,
                gold_root,
                reference_annotators,
                zh_gold_annotator,
                include_leaf_values,
            )
        )
    return rows


def evaluate_stage3_file(
    item: AnnotationFile,
    stage: str,
    gold_root: Path,
    reference_annotators: dict[tuple[str, str], str],
    zh_gold_annotator: str,
    include_leaf_values: bool,
) -> dict[str, Any]:
    gold_path = gold_root / f"data_{item.lang}" / f"{item.sample_id}.json"
    reference_annotator = resolve_stage3_reference_annotator(
        item.lang,
        item.sample_id,
        reference_annotators,
        zh_gold_annotator=zh_gold_annotator,
    )
    annotation, annotation_error = load_json(item.path, missing_status="missing_annotation")
    gold, gold_error = load_json(gold_path, missing_status="missing_gold")
    status = annotation_error or gold_error or "ok"
    row = base_detail_row(
        stage=stage,
        comparison_type="source_annotation",
        comparison_label=f"{item.annotator}__vs__{reference_annotator}",
        annotator=item.annotator,
        reference=reference_annotator,
        lang=item.lang,
        sample_id=item.sample_id,
        annotation_path=item.path,
        reference_path=gold_path,
        status=status,
    )
    if status == "ok":
        row.update(compare_json_annotations(annotation, gold, include_leaf_values))
    else:
        row.update(empty_metric_values())
    return row


def compare_json_annotations(annotation: Any, reference: Any, include_leaf_values: bool) -> dict[str, Any]:
    table_iaa = 1.0 if canonical_json(annotation, case_insensitive=False) == canonical_json(reference, case_insensitive=False) else 0.0
    table_iaa_ci = 1.0 if canonical_json(annotation, case_insensitive=True) == canonical_json(reference, case_insensitive=True) else 0.0

    node_scores = calculate_label_scores(
        annotation,
        reference,
        include_leaf_values=include_leaf_values,
        case_insensitive=False,
    )
    node_scores_ci = calculate_label_scores(
        annotation,
        reference,
        include_leaf_values=include_leaf_values,
        case_insensitive=True,
    )

    annotation_paths = extract_node_paths(annotation, include_leaf_values=include_leaf_values, case_insensitive=False)
    reference_paths = extract_node_paths(reference, include_leaf_values=include_leaf_values, case_insensitive=False)
    path_scores = calculate_node_scores(annotation_paths, reference_paths)

    annotation_paths_ci = extract_node_paths(annotation, include_leaf_values=include_leaf_values, case_insensitive=True)
    reference_paths_ci = extract_node_paths(reference, include_leaf_values=include_leaf_values, case_insensitive=True)
    path_scores_ci = calculate_node_scores(annotation_paths_ci, reference_paths_ci)

    return {
        "table_iaa": format_float(table_iaa),
        "table_iaa_ci": format_float(table_iaa_ci),
        "node_precision": format_float(node_scores.precision),
        "node_recall": format_float(node_scores.recall),
        "node_iaa": format_float(node_scores.f1),
        "node_tp": node_scores.true_positive,
        "annotation_node_count": node_scores.pred_count,
        "reference_node_count": node_scores.gold_count,
        "node_precision_ci": format_float(node_scores_ci.precision),
        "node_recall_ci": format_float(node_scores_ci.recall),
        "node_iaa_ci": format_float(node_scores_ci.f1),
        "node_tp_ci": node_scores_ci.true_positive,
        "node_path_precision": format_float(path_scores.precision),
        "node_path_recall": format_float(path_scores.recall),
        "node_path_iaa": format_float(path_scores.f1),
        "node_path_tp": path_scores.true_positive,
        "annotation_path_node_count": path_scores.pred_count,
        "reference_path_node_count": path_scores.gold_count,
        "node_path_iaa_ci": format_float(path_scores_ci.f1),
    }


def summarize(detail_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ok_rows = [row for row in detail_rows if row.get("status") == "ok"]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in ok_rows:
        stage = str(row["stage"])
        label = str(row["comparison_label"])
        lang = str(row["lang"])
        groups[(stage, label, lang)].append(row)
        groups[(stage, label, "both")].append(row)
        groups[(stage, "ALL", lang)].append(row)
        groups[(stage, "ALL", "both")].append(row)
        groups[("ALL", "ALL", "both")].append(row)

    summary_rows = [
        summarize_group(stage, label, lang, rows)
        for (stage, label, lang), rows in sorted(groups.items(), key=summary_sort_key)
        if rows
    ]
    status_counts: dict[str, int] = defaultdict(int)
    for row in detail_rows:
        status_counts[str(row.get("status", ""))] += 1
    summary_json = {
        "detail_count": len(detail_rows),
        "valid_count": len(ok_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "stage3_duplicate_ids": stage3_duplicate_ids(detail_rows),
        "summary": summary_rows,
    }
    return summary_rows, summary_json


def summarize_group(stage: str, label: str, lang: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    node_tp = sum(int(row["node_tp"]) for row in rows)
    node_pred = sum(int(row["annotation_node_count"]) for row in rows)
    node_ref = sum(int(row["reference_node_count"]) for row in rows)
    node_micro_precision = node_tp / node_pred if node_pred else 0.0
    node_micro_recall = node_tp / node_ref if node_ref else 0.0
    node_micro_f1 = (
        2 * node_micro_precision * node_micro_recall / (node_micro_precision + node_micro_recall)
        if node_micro_precision + node_micro_recall
        else 0.0
    )
    path_tp = sum(int(row["node_path_tp"]) for row in rows)
    path_pred = sum(int(row["annotation_path_node_count"]) for row in rows)
    path_ref = sum(int(row["reference_path_node_count"]) for row in rows)
    path_micro_precision = path_tp / path_pred if path_pred else 0.0
    path_micro_recall = path_tp / path_ref if path_ref else 0.0
    path_micro_f1 = (
        2 * path_micro_precision * path_micro_recall / (path_micro_precision + path_micro_recall)
        if path_micro_precision + path_micro_recall
        else 0.0
    )
    return {
        "stage": stage,
        "comparison_label": label,
        "lang": lang,
        "file_count": len(rows),
        "unique_table_count": len({(row["lang"], row["sample_id"]) for row in rows}),
        "table_iaa": format_float(mean(float(row["table_iaa"]) for row in rows)),
        "table_iaa_ci": format_float(mean(float(row["table_iaa_ci"]) for row in rows)),
        "node_iaa_macro": format_float(mean(float(row["node_iaa"]) for row in rows)),
        "node_precision_macro": format_float(mean(float(row["node_precision"]) for row in rows)),
        "node_recall_macro": format_float(mean(float(row["node_recall"]) for row in rows)),
        "node_iaa_micro": format_float(node_micro_f1),
        "node_precision_micro": format_float(node_micro_precision),
        "node_recall_micro": format_float(node_micro_recall),
        "node_iaa_ci_macro": format_float(mean(float(row["node_iaa_ci"]) for row in rows)),
        "node_path_iaa_macro": format_float(mean(float(row["node_path_iaa"]) for row in rows)),
        "node_path_iaa_micro": format_float(path_micro_f1),
        "node_path_iaa_ci_macro": format_float(mean(float(row["node_path_iaa_ci"]) for row in rows)),
    }


def stage3_duplicate_ids(detail_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    seen: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in detail_rows:
        if row.get("stage") != "stage3":
            continue
        seen[(str(row["lang"]), str(row["sample_id"]))].append(str(row["annotator"]))
    duplicates = {
        f"{lang}/{sample_id}": annotators
        for (lang, sample_id), annotators in seen.items()
        if len(annotators) > 1
    }
    return dict(sorted(duplicates.items()))


def print_summary(summary_rows: list[dict[str, Any]], detail_rows: list[dict[str, Any]]) -> None:
    if not summary_rows:
        print("No valid IAA rows found.")
        return
    print("IAA summary:")
    for row in summary_rows:
        if row["comparison_label"] != "ALL" or row["lang"] != "both":
            continue
        print(
            f"  {row['stage']} | files={row['file_count']} unique_tables={row['unique_table_count']} "
            f"table={pct(row['table_iaa'])} node_macro={pct(row['node_iaa_macro'])} "
            f"node_micro={pct(row['node_iaa_micro'])}"
        )
    duplicates = stage3_duplicate_ids(detail_rows)
    if duplicates:
        print(f"  stage3 duplicate table IDs across annotators: {len(duplicates)}")


def direct_json_files(directory: Path) -> dict[str, Path]:
    if not directory.exists():
        return {}
    return {
        path.stem: path
        for path in sorted(
            (item for item in directory.iterdir() if item.is_file() and item.suffix.lower() == ".json"),
            key=numeric_path_key,
        )
    }


def base_detail_row(
    *,
    stage: str,
    comparison_type: str,
    comparison_label: str,
    annotator: str,
    reference: str,
    lang: str,
    sample_id: str,
    annotation_path: Path,
    reference_path: Path,
    status: str,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "comparison_type": comparison_type,
        "comparison_label": comparison_label,
        "annotator": annotator,
        "reference": reference,
        "lang": lang,
        "sample_id": sample_id,
        "status": status,
        "annotation_path": str(annotation_path),
        "reference_path": str(reference_path),
    }


def empty_metric_values() -> dict[str, Any]:
    return {
        "table_iaa": "",
        "table_iaa_ci": "",
        "node_precision": "",
        "node_recall": "",
        "node_iaa": "",
        "node_tp": "",
        "annotation_node_count": "",
        "reference_node_count": "",
        "node_precision_ci": "",
        "node_recall_ci": "",
        "node_iaa_ci": "",
        "node_tp_ci": "",
        "node_path_precision": "",
        "node_path_recall": "",
        "node_path_iaa": "",
        "node_path_tp": "",
        "annotation_path_node_count": "",
        "reference_path_node_count": "",
        "node_path_iaa_ci": "",
    }


def detail_fieldnames() -> list[str]:
    return [
        "stage",
        "comparison_type",
        "comparison_label",
        "annotator",
        "reference",
        "lang",
        "sample_id",
        "status",
        "table_iaa",
        "table_iaa_ci",
        "node_precision",
        "node_recall",
        "node_iaa",
        "node_tp",
        "annotation_node_count",
        "reference_node_count",
        "node_precision_ci",
        "node_recall_ci",
        "node_iaa_ci",
        "node_tp_ci",
        "node_path_precision",
        "node_path_recall",
        "node_path_iaa",
        "node_path_tp",
        "annotation_path_node_count",
        "reference_path_node_count",
        "node_path_iaa_ci",
        "annotation_path",
        "reference_path",
    ]


def summary_fieldnames() -> list[str]:
    return [
        "stage",
        "comparison_label",
        "lang",
        "file_count",
        "unique_table_count",
        "table_iaa",
        "table_iaa_ci",
        "node_iaa_macro",
        "node_precision_macro",
        "node_recall_macro",
        "node_iaa_micro",
        "node_precision_micro",
        "node_recall_micro",
        "node_iaa_ci_macro",
        "node_path_iaa_macro",
        "node_path_iaa_micro",
        "node_path_iaa_ci_macro",
    ]


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summary_sort_key(item: tuple[tuple[str, str, str], list[dict[str, Any]]]) -> tuple[int, str, int, str, int, str]:
    stage, label, lang = item[0]
    return (
        1 if stage == "ALL" else 0,
        stage,
        1 if label == "ALL" else 0,
        label,
        1 if lang == "both" else 0,
        lang,
    )


if __name__ == "__main__":
    main()
