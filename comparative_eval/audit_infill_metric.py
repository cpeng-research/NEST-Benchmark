from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comparative_eval.config import ROOT, workflow_paths
from comparative_eval.metrics.infill import (
    InfillCellTarget,
    LegacyTarget,
    build_legacy_targets,
    build_source_faithful_targets,
    evaluate_legacy_targets_from_targets,
    evaluate_source_faithful_targets,
)
from comparative_eval.utils.html_utils import placeholders_by_cell
from comparative_eval.utils.openai_utils import strip_thinking


DEFAULT_OUTPUT_DIR = ROOT / "comparative_eval" / "results" / "p03_infill_metric_audit"
DEFAULT_MANIFEST = ROOT / "comparative_eval" / "results" / "canonical" / "table3_evaluation_manifest.csv"
DEFAULT_TABLE4_DETAILS = (
    ROOT
    / "finetune_experiments"
    / "results"
    / "table4_base_vs_ft_qa_both_test_intersection_details.csv"
)


@dataclass(frozen=True)
class SourceTargets:
    legacy: list[LegacyTarget]
    hardened: list[InfillCellTarget]
    placeholder_count: int


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit legacy and hardened Task 3 metrics.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--table4-details", type=Path, default=DEFAULT_TABLE4_DETAILS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    source_cache: dict[tuple[str, int], SourceTargets] = {}
    source_rows = build_source_inventory(source_cache)
    write_csv(args.output_dir / "source_target_inventory.csv", source_rows)

    table3_rows, false_positive_rows, reorder_rows = audit_table3(
        args.manifest,
        source_cache,
    )
    write_csv(args.output_dir / "table3_prediction_details.csv", table3_rows)
    table3_summary = summarize_rows(
        table3_rows,
        key_fields=("model", "condition", "lang"),
        add_both_language=True,
    )
    write_csv(args.output_dir / "table3_matcher_summary.csv", table3_summary)
    write_csv(args.output_dir / "legacy_reverse_substring_examples.csv", false_positive_rows)
    write_csv(args.output_dir / "multi_value_reorder_candidates.csv", reorder_rows)

    table4_rows: list[dict[str, Any]] = []
    table4_summary: list[dict[str, Any]] = []
    if args.table4_details.exists():
        table4_rows = audit_table4(args.table4_details, source_cache)
        write_csv(args.output_dir / "table4_prediction_details.csv", table4_rows)
        table4_summary = summarize_rows(
            table4_rows,
            key_fields=("model", "ft_model", "comparison_method", "method", "lang"),
            add_both_language=True,
        )
        write_csv(args.output_dir / "table4_matcher_summary.csv", table4_summary)

    report = render_report(source_rows, table3_rows, table3_summary, table4_rows, table4_summary)
    (args.output_dir / "README.md").write_text(report, encoding="utf-8")
    print(f"Wrote Task 3 metric audit artifacts to {args.output_dir}")


def build_source_inventory(source_cache: dict[tuple[str, int], SourceTargets]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lang in ("en", "zh"):
        paths = workflow_paths(lang)
        for placeholder_path in sorted(paths.placeholder_html.glob("*.html"), key=lambda path: int(path.stem)):
            sample_id = int(placeholder_path.stem)
            source = load_source_targets(lang, sample_id, source_cache)
            placeholder_cells = placeholders_by_cell(placeholder_path.read_text(encoding="utf-8"))
            slot_counts = Counter((item.row, item.col, item.index) for item in placeholder_cells)
            unique_slots = len(slot_counts)
            legacy_coords = {(target.row, target.col) for target in source.legacy}
            hardened_multi = sum(target.marker_count > 1 for target in source.hardened)
            rows.append(
                {
                    "lang": lang,
                    "sample_id": sample_id,
                    "visible_placeholder_occurrences": len(placeholder_cells),
                    "legacy_targets": len(source.legacy),
                    "legacy_unique_cells": len(legacy_coords),
                    "legacy_slot_collision_occurrences": sum(count - 1 for count in slot_counts.values()),
                    "legacy_slot_collision_cells": len(
                        {(row, col) for (row, col, _index), count in slot_counts.items() if count > 1}
                    ),
                    "legacy_empty_gold_slots": max(0, unique_slots - len(source.legacy)),
                    "hardened_evaluable_cells": len(source.hardened),
                    "hardened_marker_occurrences": sum(target.marker_count for target in source.hardened),
                    "hardened_multi_value_cells": hardened_multi,
                    "hardened_text_cells": sum(target.text_required for target in source.hardened),
                    "hardened_control_cells": sum(bool(target.control_targets) for target in source.hardened),
                    "hardened_control_targets": sum(len(target.control_targets) for target in source.hardened),
                }
            )
    return rows


def audit_table3(
    manifest_path: Path,
    source_cache: dict[tuple[str, int], SourceTargets],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    details: list[dict[str, Any]] = []
    false_positives: list[dict[str, Any]] = []
    reorder_candidates: list[dict[str, Any]] = []
    manifest_rows = read_csv(manifest_path)
    infill_rows = [row for row in manifest_rows if row.get("task") == "infill"]

    for index, row in enumerate(infill_rows, start=1):
        lang = str(row["lang"])
        sample_id = int(row["sample_id"])
        source = load_source_targets(lang, sample_id, source_cache)
        pred_html = read_prediction_html(Path(row["prediction_path"]))
        scored, reverse_rows, reorder_rows = score_prediction(
            pred_html,
            source,
            {
                "model": row["model"],
                "condition": row["condition"],
                "lang": lang,
                "sample_id": sample_id,
                "prediction_path": row["prediction_path"],
            },
        )
        details.append(scored)
        false_positives.extend(reverse_rows)
        reorder_candidates.extend(reorder_rows)
        if index % 1000 == 0:
            print(f"Table 3 audit: {index}/{len(infill_rows)} predictions", flush=True)
    return details, false_positives, reorder_candidates


def audit_table4(
    details_path: Path,
    source_cache: dict[tuple[str, int], SourceTargets],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_rows = [row for row in read_csv(details_path) if row.get("task") == "infill"]
    for index, row in enumerate(source_rows, start=1):
        lang = str(row["lang"])
        sample_id = int(row["sample_id"])
        source = load_source_targets(lang, sample_id, source_cache)
        pred_html = read_prediction_html(Path(row["active_prediction_path"]))
        scored, _, _ = score_prediction(
            pred_html,
            source,
            {
                "model": row["model"],
                "ft_model": row["ft_model"],
                "comparison_method": row["comparison_method"],
                "method": row["method"],
                "condition": "empty",
                "lang": lang,
                "sample_id": sample_id,
                "prediction_path": row["active_prediction_path"],
            },
        )
        rows.append(scored)
        if index % 1000 == 0:
            print(f"Table 4 audit: {index}/{len(source_rows)} predictions", flush=True)
    return rows


def score_prediction(
    pred_html: str,
    source: SourceTargets,
    identity: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    legacy_results = evaluate_legacy_targets_from_targets(pred_html, source.legacy)
    hardened_results = evaluate_source_faithful_targets(pred_html, source.hardened)
    multi_coords = {
        (target.row, target.col)
        for target in source.hardened
        if target.marker_count > 1
    }
    reverse_results = [result for result in legacy_results if result.match_kind == "prediction_in_gold"]
    hardened_multi = [result for result in hardened_results if result.marker_count > 1]
    reorder_results = [result for result in hardened_multi if is_reorder_candidate(result)]

    row = {
        **identity,
        "legacy_correct": sum(result.correct for result in legacy_results),
        "legacy_total": len(legacy_results),
        "legacy_score": ratio(sum(result.correct for result in legacy_results), len(legacy_results)),
        "hardened_correct": sum(result.correct for result in hardened_results),
        "hardened_total": len(hardened_results),
        "hardened_score": ratio(sum(result.correct for result in hardened_results), len(hardened_results)),
        "legacy_reverse_substring_correct": len(reverse_results),
        "legacy_reverse_single_char_correct": sum(len(result.prediction) == 1 for result in reverse_results),
        "legacy_reverse_short_fragment_correct": sum(0 < len(result.prediction) <= 3 for result in reverse_results),
        "legacy_reverse_in_multi_value_cell": sum((result.row, result.col) in multi_coords for result in reverse_results),
        "hardened_multi_value_correct": sum(result.correct for result in hardened_multi),
        "hardened_multi_value_total": len(hardened_multi),
        "hardened_reorder_candidates": len(reorder_results),
        "hardened_control_mismatches": sum(result.match_kind == "control_mismatch" for result in hardened_results),
    }
    row["score_delta_pp"] = round(
        100.0 * (float(row["hardened_score"]) - float(row["legacy_score"])),
        6,
    )

    reverse_rows = [
        {
            **identity,
            "row": result.row,
            "col": result.col,
            "placeholder_name": result.name,
            "placeholder_index": result.index,
            "gold_normalized": result.gold,
            "prediction_normalized": result.prediction,
            "prediction_length": len(result.prediction),
            "multi_value_cell": (result.row, result.col) in multi_coords,
        }
        for result in reverse_results
    ]
    reorder_rows = [
        {
            **identity,
            "row": result.row,
            "col": result.col,
            "marker_count": result.marker_count,
            "gold_text": result.gold_raw_text,
            "prediction_text": result.prediction_raw_text,
        }
        for result in reorder_results
    ]
    return row, reverse_rows, reorder_rows


def summarize_rows(
    rows: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
    add_both_language: bool,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(field, "") for field in key_fields)].append(row)

    summaries = [summarize_group(key_fields, key, group) for key, group in grouped.items()]
    if add_both_language and "lang" in key_fields:
        without_lang = tuple(field for field in key_fields if field != "lang")
        combined: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            combined[tuple(row.get(field, "") for field in without_lang)].append(row)
        for key, group in combined.items():
            identity = dict(zip(without_lang, key))
            identity["lang"] = "both"
            summaries.append(summarize_group(tuple(identity), tuple(identity.values()), group))
    return sorted(summaries, key=lambda row: tuple(str(row.get(field, "")) for field in key_fields))


def summarize_group(
    key_fields: tuple[str, ...],
    key: tuple[Any, ...],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    result = dict(zip(key_fields, key))
    additive_fields = (
        "legacy_correct",
        "legacy_total",
        "hardened_correct",
        "hardened_total",
        "legacy_reverse_substring_correct",
        "legacy_reverse_single_char_correct",
        "legacy_reverse_short_fragment_correct",
        "legacy_reverse_in_multi_value_cell",
        "hardened_multi_value_correct",
        "hardened_multi_value_total",
        "hardened_reorder_candidates",
        "hardened_control_mismatches",
    )
    for field in additive_fields:
        result[field] = sum(int(row.get(field, 0)) for row in rows)
    result["prediction_count"] = len(rows)
    result["legacy_score"] = ratio(result["legacy_correct"], result["legacy_total"])
    result["hardened_score"] = ratio(result["hardened_correct"], result["hardened_total"])
    result["score_delta_pp"] = round(
        100.0 * (float(result["hardened_score"]) - float(result["legacy_score"])),
        6,
    )
    return result


def load_source_targets(
    lang: str,
    sample_id: int,
    cache: dict[tuple[str, int], SourceTargets],
) -> SourceTargets:
    key = (lang, sample_id)
    if key in cache:
        return cache[key]
    paths = workflow_paths(lang)
    gold_html = (paths.html_filled / f"{sample_id}.html").read_text(encoding="utf-8")
    placeholder_html = (paths.placeholder_html / f"{sample_id}.html").read_text(encoding="utf-8")
    source = SourceTargets(
        legacy=build_legacy_targets(gold_html, placeholder_html),
        hardened=build_source_faithful_targets(gold_html, placeholder_html),
        placeholder_count=len(placeholders_by_cell(placeholder_html)),
    )
    cache[key] = source
    return source


def read_prediction_html(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return strip_thinking(str(data.get("raw_response") or ""))


def is_reorder_candidate(result: Any) -> bool:
    if result.correct or not result.text_required:
        return False
    gold_tokens = content_tokens(result.gold_raw_text)
    prediction_tokens = content_tokens(result.prediction_raw_text)
    return (
        len(gold_tokens) >= 2
        and gold_tokens != prediction_tokens
        and Counter(gold_tokens) == Counter(prediction_tokens)
    )


def content_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return re.findall(r"[\w%$€£¥]+|[\u3400-\u9fff]", normalized)


def ratio(correct: int, total: int) -> float:
    return round(correct / total, 9) if total else 0.0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    row_list = list(rows)
    if not row_list:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in row_list:
        for field in row:
            if field not in fieldnames:
                fieldnames.append(field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(row_list)


def render_report(
    source_rows: list[dict[str, Any]],
    table3_rows: list[dict[str, Any]],
    table3_summary: list[dict[str, Any]],
    table4_rows: list[dict[str, Any]],
    table4_summary: list[dict[str, Any]],
) -> str:
    source_totals = sum_fields(
        source_rows,
        (
            "visible_placeholder_occurrences",
            "legacy_targets",
            "legacy_slot_collision_occurrences",
            "legacy_slot_collision_cells",
            "legacy_empty_gold_slots",
            "hardened_evaluable_cells",
            "hardened_multi_value_cells",
            "hardened_control_cells",
        ),
    )
    table3_totals = sum_fields(
        table3_rows,
        (
            "legacy_correct",
            "legacy_total",
            "hardened_correct",
            "hardened_total",
            "legacy_reverse_substring_correct",
            "legacy_reverse_single_char_correct",
            "legacy_reverse_short_fragment_correct",
            "legacy_reverse_in_multi_value_cell",
            "hardened_reorder_candidates",
            "hardened_control_mismatches",
        ),
    )
    lines = [
        "# Task 3 Metric Audit",
        "",
        "The audit keeps the submitted bidirectional whole-cell substring matcher as `legacy_v1` and compares it with the source-faithful matcher, which scores each observable filling-cell coordinate once, rejects reverse/partial substring credit, preserves value order through whole-cell text, and evaluates input/selectable control values and states.",
        "",
        "## Adoption decision",
        "",
        "The benchmark adopts `source_faithful_v3` as the canonical Task 3 metric. It retains the v2 matching rule while evaluating all supported logical table/form regions; `source_faithful_v2` preserves the historical first-table coverage, and `legacy_v1` preserves the submitted matcher. Canonical Table 3 and Table 4 outputs record the selected matcher in their JSON metadata, and caches are reused only when their metric version matches.",
        "",
        "## Source target inventory",
        "",
        f"- Visible placeholder occurrences: {source_totals['visible_placeholder_occurrences']:,}",
        f"- Legacy targets after its slot deduplication: {source_totals['legacy_targets']:,}",
        f"- Legacy slot-collision occurrences: {source_totals['legacy_slot_collision_occurrences']:,} across {source_totals['legacy_slot_collision_cells']:,} cells",
        f"- Legacy deduplicated slots skipped because whole-cell gold text was empty: {source_totals['legacy_empty_gold_slots']:,}",
        f"- Hardened observable cell targets: {source_totals['hardened_evaluable_cells']:,}",
        f"- Hardened multi-value cells: {source_totals['hardened_multi_value_cells']:,}",
        f"- Hardened control-bearing cells: {source_totals['hardened_control_cells']:,}",
        "",
        "## Table 3 prediction audit",
        "",
        f"- Predictions audited: {len(table3_rows):,}",
        f"- Legacy reverse-substring credits: {table3_totals['legacy_reverse_substring_correct']:,}",
        f"- Of those, one-character predictions: {table3_totals['legacy_reverse_single_char_correct']:,}",
        f"- Of those, predictions of at most three normalized characters: {table3_totals['legacy_reverse_short_fragment_correct']:,}",
        f"- Reverse-substring credits in multi-value cells: {table3_totals['legacy_reverse_in_multi_value_cell']:,}",
        f"- Candidate reordered multi-value cells rejected by v2: {table3_totals['hardened_reorder_candidates']:,}",
        f"- Control-state/value mismatches exposed by v2: {table3_totals['hardened_control_mismatches']:,}",
        f"- Legacy micro score: {100 * ratio(table3_totals['legacy_correct'], table3_totals['legacy_total']):.2f}%",
        f"- Hardened micro score: {100 * ratio(table3_totals['hardened_correct'], table3_totals['hardened_total']):.2f}%",
        "",
        "### Largest Table 3 model/condition impacts (both languages)",
        "",
        "|Model|Condition|Legacy|Hardened|Delta (pp)|",
        "|---|---:|---:|---:|---:|",
    ]
    both_rows = [row for row in table3_summary if row.get("lang") == "both"]
    for row in sorted(both_rows, key=lambda item: abs(float(item["score_delta_pp"])), reverse=True)[:12]:
        lines.append(
            f"|{row['model']}|{row['condition']}|{100*float(row['legacy_score']):.2f}%|"
            f"{100*float(row['hardened_score']):.2f}%|{float(row['score_delta_pp']):+.2f}|"
        )
    if table4_rows:
        table4_totals = sum_fields(
            table4_rows,
            ("legacy_correct", "legacy_total", "hardened_correct", "hardened_total"),
        )
        lines.extend(
            [
                "",
                "## Table 4 prediction audit",
                "",
                f"- Prediction rows audited: {len(table4_rows):,}",
                f"- Legacy micro score: {100 * ratio(table4_totals['legacy_correct'], table4_totals['legacy_total']):.2f}%",
                f"- Hardened micro score: {100 * ratio(table4_totals['hardened_correct'], table4_totals['hardened_total']):.2f}%",
                "- See `table4_matcher_summary.csv` for each Base/FT/QA comparison.",
            ]
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `source_target_inventory.csv`: target extraction and collision counts per table.",
            "- `table3_prediction_details.csv` / `table3_matcher_summary.csv`: Table 3 comparison.",
            "- `table4_prediction_details.csv` / `table4_matcher_summary.csv`: Table 4 comparison.",
            "- `legacy_reverse_substring_examples.csv`: every legacy reverse-substring credit.",
            "- `multi_value_reorder_candidates.csv`: conservative token-multiset reorder candidates.",
            "",
        ]
    )
    return "\n".join(lines)


def sum_fields(rows: Iterable[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, int]:
    return {field: sum(int(row.get(field, 0)) for row in rows) for field in fields}


if __name__ == "__main__":
    main()
