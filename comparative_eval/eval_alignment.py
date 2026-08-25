from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable

from bs4 import BeautifulSoup

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comparative_eval.config import SUPPORTED_CONDITIONS, details_dir, prediction_dir, summaries_dir, workflow_paths
from comparative_eval.utils.eval_cache import CACHE_FIELDNAMES, add_cache_record, cached_row_is_current, prediction_cache_record
from comparative_eval.utils.io_utils import iter_numeric_files, read_csv, read_json, read_text, write_csv, write_json
from comparative_eval.utils.openai_utils import strip_thinking


FIELD_TYPES = ("LI", "GI", "SI", "GO", "SO")
STRATEGY_ORDER = ("analysis", "leaf", "recursive")


@dataclass(frozen=True)
class ExpectedPlaceholder:
    key: str
    field_type: str
    target_row: int
    target_col: int
    label_row: int
    label_col: int
    offset_rows: int
    offset_cols: int
    index: int


@dataclass(frozen=True)
class InputOccurrence:
    row: int
    col: int
    name: str
    index: int
    occurrence_id: tuple[str, int, int, str, int]


@dataclass(frozen=True)
class BracketOccurrence:
    row: int
    col: int
    name: str
    index: int


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Table 3 cell-header alignment.")
    parser.add_argument("--condition", required=True, choices=SUPPORTED_CONDITIONS)
    parser.add_argument("--model", required=True)
    parser.add_argument("--lang", default="en", choices=["en", "zh"])
    parser.add_argument(
        "--resume_from_details",
        "--resume-from-details",
        action="store_true",
        help="Reuse current per-sample rows in results/details when their prediction file fingerprint is unchanged.",
    )
    args = parser.parse_args()

    paths = workflow_paths(args.lang)
    pred_dir = prediction_dir("alignment", args.condition, args.lang, args.model)
    detail_path = details_dir() / f"alignment_{args.condition}_{args.lang}_{clean_model(args.model)}.csv"
    cached_rows = load_existing_rows_by_id(detail_path) if args.resume_from_details else {}
    rows = []
    invalid_prediction_ids: list[int] = []

    for pred_file in iter_numeric_files(pred_dir, ".json"):
        sample_id = int(pred_file.stem)
        cache_record = prediction_cache_record(pred_file)
        cached_row = cached_rows.get(sample_id)
        if cached_row_is_current(cached_row, cache_record):
            rows.append(cached_row)
            continue
        meta_file = paths.meta / f"{sample_id}.json"
        gold_file = paths.placeholder_html / f"{sample_id}.html"
        if not meta_file.exists() or not gold_file.exists():
            continue

        expected = expand_meta(read_json(meta_file))
        if not expected:
            continue

        gold_html = read_text(gold_file)
        strategy = choose_coordinate_strategy(gold_html, expected)
        expected = resolve_expected_names_from_gold(gold_html, expected, strategy)
        pred_html, pred_issue = read_prediction_html(pred_file)
        if pred_issue is not None:
            results = zero_alignment_results(expected)
            rows.append(
                add_cache_record(
                    alignment_row(args.model, args.condition, sample_id, results, strategy, pred_status=pred_issue),
                    cache_record,
                )
            )
            invalid_prediction_ids.append(sample_id)
            continue
        results, _records = compare_alignment(pred_html, expected, strategy)
        rows.append(
            add_cache_record(
                alignment_row(args.model, args.condition, sample_id, results, strategy, pred_status="ok"),
                cache_record,
            )
        )

    rows = sorted(rows, key=lambda row: safe_int(row.get("sample_id"), -1))
    total_correct, total_count, type_totals = summarize_rows(rows)
    all_invalid_prediction_ids = invalid_prediction_ids_from_rows(rows)
    if invalid_prediction_ids:
        preview_ids = ", ".join(str(sample_id) for sample_id in invalid_prediction_ids[:20])
        if len(invalid_prediction_ids) > 20:
            preview_ids += f", ... (+{len(invalid_prediction_ids) - 20} more)"
        print(f"Warning: {len(invalid_prediction_ids)} empty or invalid prediction files were scored as 0: {preview_ids}")
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
    summary = {
        "task": "alignment",
        "condition": args.condition,
        "lang": args.lang,
        "model": args.model,
        "score": total_correct / total_count if total_count else 0.0,
        "correct": total_correct,
        "total": total_count,
        "sample_count": len(rows),
        "metric": "meta_target_cell_input_name_accuracy",
        "invalid_prediction_count": len(all_invalid_prediction_ids),
        "invalid_prediction_ids": all_invalid_prediction_ids,
        "skipped_prediction_count": len(all_invalid_prediction_ids),
        "skipped_prediction_ids": all_invalid_prediction_ids,
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
    }
    summary_path = summaries_dir() / f"alignment_{args.condition}_{args.lang}_{clean_model(args.model)}.json"
    write_json(summary_path, summary)
    print(f"Wrote {detail_path}")
    print(f"Wrote {summary_path}")


def expand_meta(meta_data: Any) -> list[ExpectedPlaceholder]:
    if isinstance(meta_data, dict):
        raw_items = meta_data.get("structured_analysis", [])
    elif isinstance(meta_data, list):
        raw_items = meta_data
    else:
        return []

    expected: list[ExpectedPlaceholder] = []
    for item in flatten_items(raw_items):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("display_key") or item.get("parent_key") or "").strip()
        field_type = str(item.get("type") or "")
        label_info = item.get("label_info") or {}
        if not key or field_type not in FIELD_TYPES or not isinstance(label_info, dict):
            continue

        label_row = safe_int(label_info.get("row"), -1)
        label_col = safe_int(label_info.get("col"), -1)
        if label_row < 0 or label_col < 0:
            continue

        offsets = item.get("placeholder_offset", item.get("position_offset", {}))
        if isinstance(offsets, list):
            offset_list = [offset for offset in offsets if isinstance(offset, dict)]
        elif isinstance(offsets, dict):
            offset_list = [offsets]
        else:
            offset_list = []

        for idx, offset in enumerate(offset_list):
            offset_rows = safe_int(offset.get("rows"), 0)
            offset_cols = safe_int(offset.get("cols"), 0)
            expected.append(
                ExpectedPlaceholder(
                    key=key,
                    field_type=field_type,
                    target_row=label_row + offset_rows,
                    target_col=label_col + offset_cols,
                    label_row=label_row,
                    label_col=label_col,
                    offset_rows=offset_rows,
                    offset_cols=offset_cols,
                    index=idx,
                )
            )
    return expected


def compare_alignment(
    html: str,
    expected: list[ExpectedPlaceholder],
    strategy: str,
) -> tuple[dict[str, dict[str, int]], list[dict[str, Any]]]:
    results = {field_type: {"correct": 0, "total": 0} for field_type in FIELD_TYPES}
    input_occurrences = extract_input_occurrences(html, strategy)
    inputs_by_cell: dict[tuple[int, int], list[InputOccurrence]] = defaultdict(list)
    for occurrence in input_occurrences:
        inputs_by_cell[(occurrence.row, occurrence.col)].append(occurrence)

    cell_texts = extract_cell_texts(html, strategy)
    used_inputs: set[tuple[str, int, int, str, int]] = set()
    records: list[dict[str, Any]] = []

    for item in expected:
        results[item.field_type]["total"] += 1
        matched = match_in_cell(inputs_by_cell, used_inputs, item.target_row, item.target_col, item.key)
        match_method = "label_offset" if matched else ""

        if not matched:
            for label_row, label_col in find_label_positions(cell_texts, item.key):
                fallback_row = label_row + item.offset_rows
                fallback_col = label_col + item.offset_cols
                matched = match_in_cell(inputs_by_cell, used_inputs, fallback_row, fallback_col, item.key)
                if matched:
                    match_method = "key_fallback"
                    break

        if matched:
            results[item.field_type]["correct"] += 1

        records.append(
            {
                "key": item.key,
                "type": item.field_type,
                "label_row": item.label_row,
                "label_col": item.label_col,
                "offset_rows": item.offset_rows,
                "offset_cols": item.offset_cols,
                "target_row": item.target_row,
                "target_col": item.target_col,
                "matched": matched,
                "match_method": match_method,
            }
        )

    return results, records


def zero_alignment_results(expected: list[ExpectedPlaceholder]) -> dict[str, dict[str, int]]:
    results = {field_type: {"correct": 0, "total": 0} for field_type in FIELD_TYPES}
    for item in expected:
        results[item.field_type]["total"] += 1
    return results


def alignment_row(
    model: str,
    condition: str,
    sample_id: int,
    results: dict[str, dict[str, int]],
    strategy: str,
    pred_status: str,
) -> dict[str, object]:
    correct = sum(results[field_type]["correct"] for field_type in FIELD_TYPES)
    total = sum(results[field_type]["total"] for field_type in FIELD_TYPES)
    acc = correct / total if total else 0.0
    row: dict[str, object] = {
        "model": model,
        "condition": condition,
        "sample_id": sample_id,
        "correct": correct,
        "total": total,
        "accuracy": f"{acc:.6f}",
        "strategy": strategy,
        "pred_status": pred_status,
    }
    for field_type in FIELD_TYPES:
        row[f"{field_type}_correct"] = results[field_type]["correct"]
        row[f"{field_type}_total"] = results[field_type]["total"]
    return row


def invalid_prediction_ids_from_rows(rows: list[dict]) -> list[int]:
    ids: list[int] = []
    for row in rows:
        status = str(row.get("pred_status") or "").strip()
        if status and status != "ok":
            ids.append(safe_int(row.get("sample_id"), -1))
    return [sample_id for sample_id in ids if sample_id >= 0]


def choose_coordinate_strategy(gold_html: str, expected: list[ExpectedPlaceholder]) -> str:
    best_strategy = STRATEGY_ORDER[0]
    best_score = -1
    for strategy in STRATEGY_ORDER:
        occurrences = extract_bracket_occurrences(gold_html, strategy)
        by_cell: dict[tuple[int, int], list[BracketOccurrence]] = defaultdict(list)
        for occurrence in occurrences:
            by_cell[(occurrence.row, occurrence.col)].append(occurrence)

        used: set[tuple[int, int, str, int]] = set()
        score = 0
        for item in expected:
            for occurrence in by_cell.get((item.target_row, item.target_col), []):
                occurrence_id = (occurrence.row, occurrence.col, occurrence.name, occurrence.index)
                if occurrence_id in used:
                    continue
                if text_match(occurrence.name, item.key):
                    used.add(occurrence_id)
                    score += 1
                    break

        if score > best_score:
            best_score = score
            best_strategy = strategy
    return best_strategy


def resolve_expected_names_from_gold(
    gold_html: str,
    expected: list[ExpectedPlaceholder],
    strategy: str,
) -> list[ExpectedPlaceholder]:
    """Recover the exact gold placeholder text missing from compact Step 6 meta."""
    occurrences = extract_bracket_occurrences(gold_html, strategy)
    by_cell: dict[tuple[int, int], list[BracketOccurrence]] = defaultdict(list)
    for occurrence in occurrences:
        by_cell[(occurrence.row, occurrence.col)].append(occurrence)

    used: set[tuple[int, int, str, int]] = set()
    resolved = []
    for item in expected:
        cell_occurrences = by_cell.get((item.target_row, item.target_col), [])
        chosen = None
        for occurrence in cell_occurrences:
            occurrence_id = (occurrence.row, occurrence.col, occurrence.name, occurrence.index)
            if occurrence_id in used:
                continue
            if text_match(occurrence.name, item.key):
                chosen = occurrence
                break
        if chosen is None:
            for occurrence in cell_occurrences:
                occurrence_id = (occurrence.row, occurrence.col, occurrence.name, occurrence.index)
                if occurrence_id not in used:
                    chosen = occurrence
                    break

        if chosen is not None:
            used.add((chosen.row, chosen.col, chosen.name, chosen.index))
            resolved.append(replace(item, key=chosen.name))
        else:
            resolved.append(item)
    return resolved


def match_in_cell(
    inputs_by_cell: dict[tuple[int, int], list[InputOccurrence]],
    used_inputs: set[tuple[str, int, int, str, int]],
    row: int,
    col: int,
    key: str,
) -> bool:
    for occurrence in inputs_by_cell.get((row, col), []):
        if occurrence.occurrence_id in used_inputs:
            continue
        if text_match(occurrence.name, key):
            used_inputs.add(occurrence.occurrence_id)
            return True
    return False


def extract_input_occurrences(html: str, strategy: str) -> list[InputOccurrence]:
    def from_cell(row: int, col: int, cell: Any, source: str) -> Iterable[InputOccurrence]:
        name_counts: dict[str, int] = defaultdict(int)
        for input_tag in cell.find_all("input"):
            name = str(input_tag.get("name") or "").strip()
            if not name:
                continue
            index = name_counts[name]
            name_counts[name] += 1
            yield InputOccurrence(
                row=row,
                col=col,
                name=name,
                index=index,
                occurrence_id=(source, row, col, name, index),
            )

    return [
        occurrence
        for source, row, col, cell in iter_cells(html, strategy, input_table_marker)
        for occurrence in from_cell(row, col, cell, source)
    ]


def extract_bracket_occurrences(html: str, strategy: str) -> list[BracketOccurrence]:
    occurrences: list[BracketOccurrence] = []
    for _source, row, col, cell in iter_cells(html, strategy, bracket_table_marker):
        text = cell.get_text(" ", strip=True)
        name_counts: dict[str, int] = defaultdict(int)
        for match in re.finditer(r"\[([^\[\]]+)\]", text):
            name = match.group(1).strip()
            index = name_counts[normalize_text(name)]
            name_counts[normalize_text(name)] += 1
            occurrences.append(BracketOccurrence(row=row, col=col, name=name, index=index))
    return occurrences


def extract_cell_texts(html: str, strategy: str) -> dict[tuple[int, int], str]:
    texts: dict[tuple[int, int], str] = {}
    for _source, row, col, cell in iter_cells(html, strategy, input_table_marker):
        texts.setdefault((row, col), cell.get_text(" ", strip=True))
    return texts


def iter_cells(
    html: str,
    strategy: str,
    marker: Callable[[Any], bool],
) -> list[tuple[str, int, int, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    if strategy == "leaf":
        tables = select_leaf_tables(soup, marker)
        return direct_cells_for_tables(tables, source_prefix="leaf")
    if strategy == "recursive":
        table = soup.find("table")
        return recursive_cells_for_table(table, source="recursive") if table else []
    tables = select_analysis_tables(soup, marker)
    return direct_cells_for_tables(tables, source_prefix="analysis")


def direct_cells_for_tables(tables: list[Any], source_prefix: str) -> list[tuple[str, int, int, Any]]:
    out: list[tuple[str, int, int, Any]] = []
    row_base = 0
    for table_index, table in enumerate(tables):
        rows = direct_rows(table)
        grid = build_grid(rows, recursive_cells=False)
        for row, col, cell in first_cell_positions(grid):
            out.append((f"{source_prefix}:{table_index}", row_base + row, col, cell))
        row_base += len(rows)
    return out


def recursive_cells_for_table(table: Any, source: str) -> list[tuple[str, int, int, Any]]:
    rows = table.find_all("tr")
    grid = build_grid(rows, recursive_cells=True)
    return [(source, row, col, cell) for row, col, cell in first_cell_positions(grid)]


def build_grid(rows: list[Any], recursive_cells: bool, max_cols: int = 100) -> dict[tuple[int, int], Any]:
    grid: dict[tuple[int, int], Any] = {}
    for row_index, row in enumerate(rows):
        col_index = 0
        cells = row.find_all(["td", "th"], recursive=recursive_cells)
        for cell in cells:
            while (row_index, col_index) in grid and col_index < max_cols:
                col_index += 1
            if col_index >= max_cols:
                break
            rowspan = safe_span(cell.get("rowspan"))
            colspan = safe_span(cell.get("colspan"))
            for r in range(row_index, row_index + rowspan):
                for c in range(col_index, col_index + colspan):
                    if c < max_cols:
                        grid[(r, c)] = cell
            col_index += colspan
    return grid


def first_cell_positions(grid: dict[tuple[int, int], Any]) -> list[tuple[int, int, Any]]:
    first_positions: dict[int, tuple[int, int]] = {}
    for pos, cell in grid.items():
        cell_id = id(cell)
        if cell_id not in first_positions or pos < first_positions[cell_id]:
            first_positions[cell_id] = pos

    out = []
    for row, col in sorted(first_positions.values()):
        cell = grid.get((row, col))
        if cell is not None:
            out.append((row, col, cell))
    return out


def select_leaf_tables(soup: BeautifulSoup, marker: Callable[[Any], bool]) -> list[Any]:
    leaf_tables = []
    for table in soup.find_all("table"):
        if not marker(table):
            continue
        nested_marker_tables = [
            child_table
            for child_table in table.find_all("table")
            if child_table is not table and marker(child_table)
        ]
        if not nested_marker_tables:
            leaf_tables.append(table)
    return leaf_tables


def select_analysis_tables(soup: BeautifulSoup, marker: Callable[[Any], bool]) -> list[Any]:
    analysis_tables = []

    def visit(table: Any) -> None:
        if not marker(table):
            return
        if is_layout_wrapper_table(table, marker):
            rows = direct_rows(table)
            cell = rows[0].find_all(["td", "th"], recursive=False)[0]
            for nested_table in direct_nested_marker_tables(table, cell, marker):
                visit(nested_table)
            return
        analysis_tables.append(table)

    for table in soup.find_all("table"):
        if table.find_parent("table") is None:
            visit(table)
    return analysis_tables


def is_layout_wrapper_table(table: Any, marker: Callable[[Any], bool]) -> bool:
    rows = direct_rows(table)
    if len(rows) != 1:
        return False
    cells = rows[0].find_all(["td", "th"], recursive=False)
    if len(cells) != 1:
        return False
    cell = cells[0]
    if not direct_nested_marker_tables(table, cell, marker):
        return False
    return normalize_text(cell_text_without_nested_tables(cell)) == ""


def direct_nested_marker_tables(table: Any, cell: Any, marker: Callable[[Any], bool]) -> list[Any]:
    return [
        child_table
        for child_table in cell.find_all("table")
        if child_table.find_parent("table") is table and marker(child_table)
    ]


def direct_rows(table: Any) -> list[Any]:
    rows = []
    for child in table.children:
        if getattr(child, "name", None) == "tr":
            rows.append(child)
        elif getattr(child, "name", None) in {"thead", "tbody", "tfoot"}:
            rows.extend(child.find_all("tr", recursive=False))
    return rows


def cell_text_without_nested_tables(cell: Any) -> str:
    cell_copy_soup = BeautifulSoup(str(cell), "html.parser")
    cell_copy = cell_copy_soup.find(cell.name)
    if cell_copy is None:
        return cell.get_text()
    for nested_table in cell_copy.find_all("table"):
        nested_table.decompose()
    return cell_copy.get_text()


def bracket_table_marker(table: Any) -> bool:
    return bool(re.search(r"\[[^\[\]]+\]", table.get_text()))


def input_table_marker(table: Any) -> bool:
    return bool(table.find("input", attrs={"name": True}))


def find_label_positions(cell_texts: dict[tuple[int, int], str], key: str) -> list[tuple[int, int]]:
    normalized_key = normalize_text(key)
    if not normalized_key:
        return []
    return [
        pos
        for pos, text in cell_texts.items()
        if normalized_key in normalize_text(text)
    ]


def text_match(target1: str, target2: str) -> bool:
    norm1 = normalize_text(target1)
    norm2 = normalize_text(target2)
    if not norm1 or not norm2:
        return False
    return norm1 in norm2 or norm2 in norm1


def normalize_text(text: str | None) -> str:
    if text is None:
        return ""
    text = str(text).lower()
    text = re.sub(r"[\s\[\]{}()<>:：,，.;；。!?！？'\"`_\-/\\|~·]", "", text)
    text = re.sub(r"^\d+", "", text)
    text = re.sub(r"\d+$", "", text)
    return text.strip()


def flatten_items(items: Any) -> Iterable[Any]:
    if isinstance(items, list):
        for item in items:
            yield from flatten_items(item)
    else:
        yield items


def safe_span(value: Any) -> int:
    match = re.search(r"\d+", str(value or ""))
    return max(1, int(match.group(0))) if match else 1


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def summarize_rows(rows: list[dict]) -> tuple[int, int, dict[str, dict[str, int]]]:
    type_totals = {field_type: {"correct": 0, "total": 0} for field_type in FIELD_TYPES}
    total_correct = 0
    total_count = 0
    for row in rows:
        total_correct += safe_int(row.get("correct"))
        total_count += safe_int(row.get("total"))
        for field_type in FIELD_TYPES:
            type_totals[field_type]["correct"] += safe_int(row.get(f"{field_type}_correct"))
            type_totals[field_type]["total"] += safe_int(row.get(f"{field_type}_total"))
    return total_correct, total_count, type_totals


def clean_model(model: str) -> str:
    return model.replace("/", "_").replace("-", "_")


if __name__ == "__main__":
    main()
