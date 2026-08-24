from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZipFile


DEFAULT_LANGS = ("en", "zh")
DEFAULT_EN_ANNOTATORS_XLSX = Path("en/annotators.xlsx")
DEFAULT_ZH_GOLD_ANNOTATOR = "annotator_E"
NAME_TO_ANNOTATOR: dict[str, str] = {}
XLSX_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass(frozen=True)
class AnnotationFile:
    annotator: str
    lang: str
    sample_id: str
    path: Path


@dataclass(frozen=True)
class NodeScores:
    precision: float
    recall: float
    f1: float
    true_positive: int
    pred_count: int
    gold_count: int


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute stage 3 IAA by comparing each student's re-annotated JSON "
            "against workflow/1-annotated_json source JSON."
        )
    )
    parser.add_argument("--stage_dir", "--stage-dir", type=Path, default=Path("IAA/stage3"))
    parser.add_argument("--gold_root", "--gold-root", type=Path, default=Path("workflow/1-annotated_json"))
    parser.add_argument("--en_annotators_xlsx", "--en-annotators-xlsx", type=Path, default=DEFAULT_EN_ANNOTATORS_XLSX)
    parser.add_argument("--zh_gold_annotator", "--zh-gold-annotator", default=DEFAULT_ZH_GOLD_ANNOTATOR)
    parser.add_argument("--output_dir", "--output-dir", type=Path, default=Path("IAA/results/stage3"))
    parser.add_argument(
        "--annotators",
        nargs="*",
        default=None,
        help="Annotator directories to include. Defaults to every annotator_* directory currently present.",
    )
    parser.add_argument("--langs", nargs="*", default=list(DEFAULT_LANGS), choices=list(DEFAULT_LANGS))
    parser.add_argument(
        "--flat_lang",
        "--flat-lang",
        default="en",
        choices=list(DEFAULT_LANGS),
        help="Language assigned to JSON files placed directly under annotator_* without en/zh subdirs.",
    )
    parser.add_argument(
        "--no_flat",
        "--no-flat",
        action="store_true",
        help="Disable backward-compatible scanning of flat annotator directories.",
    )
    parser.add_argument(
        "--no_leaf_values",
        "--no-leaf-values",
        action="store_true",
        help="Ignore non-empty primitive leaf values when extracting node paths.",
    )
    parser.add_argument("--details_name", "--details-name", default="stage3_iaa_details.csv")
    parser.add_argument("--summary_name", "--summary-name", default="stage3_iaa_summary.csv")
    parser.add_argument("--json_name", "--json-name", default="stage3_iaa_summary.json")
    parser.add_argument("--dry_run", "--dry-run", action="store_true")
    args = parser.parse_args()

    annotators = tuple(args.annotators) if args.annotators else discover_annotators(args.stage_dir)
    files = discover_annotation_files(
        args.stage_dir,
        annotators=annotators,
        langs=tuple(args.langs),
        allow_flat=not args.no_flat,
        flat_lang=args.flat_lang,
    )
    if not files:
        print(f"No stage 3 annotation JSON files found under {args.stage_dir}")
        return

    reference_annotators = load_stage3_reference_annotators(
        args.en_annotators_xlsx,
        zh_gold_annotator=args.zh_gold_annotator,
    )
    detail_rows = [
        evaluate_annotation_file(
            annotation_file,
            gold_root=args.gold_root,
            reference_annotators=reference_annotators,
            zh_gold_annotator=args.zh_gold_annotator,
            include_leaf_values=not args.no_leaf_values,
        )
        for annotation_file in files
    ]
    summary_rows, summary_json = summarize(detail_rows)

    print_summary(summary_rows)
    if args.dry_run:
        return

    ensure_dir(args.output_dir)
    write_csv(args.output_dir / args.details_name, detail_rows, detail_fieldnames())
    write_csv(args.output_dir / args.summary_name, summary_rows, summary_fieldnames())
    write_json(args.output_dir / args.json_name, summary_json)
    print(f"Wrote {args.output_dir / args.details_name}")
    print(f"Wrote {args.output_dir / args.summary_name}")
    print(f"Wrote {args.output_dir / args.json_name}")


def discover_annotation_files(
    stage_dir: Path,
    *,
    annotators: tuple[str, ...],
    langs: tuple[str, ...],
    allow_flat: bool,
    flat_lang: str,
) -> list[AnnotationFile]:
    files: list[AnnotationFile] = []
    seen: set[tuple[str, str, str, Path]] = set()
    for annotator in annotators:
        annotator_dir = stage_dir / annotator
        if not annotator_dir.exists():
            continue

        for lang in langs:
            for lang_dir_name in (lang, f"data_{lang}"):
                lang_dir = annotator_dir / lang_dir_name
                if not lang_dir.exists():
                    continue
                for path in json_files(lang_dir):
                    sample_id = path.stem
                    key = (annotator, lang, sample_id, path.resolve())
                    if key not in seen:
                        seen.add(key)
                        files.append(AnnotationFile(annotator, lang, sample_id, path))

        if allow_flat and flat_lang in langs:
            for path in json_files(annotator_dir):
                sample_id = path.stem
                key = (annotator, flat_lang, sample_id, path.resolve())
                if key not in seen:
                    seen.add(key)
                    files.append(AnnotationFile(annotator, flat_lang, sample_id, path))

    return sorted(files, key=lambda item: (item.lang, item.annotator, numeric_id(item.sample_id), item.sample_id))


def discover_annotators(stage_dir: Path) -> tuple[str, ...]:
    if not stage_dir.exists():
        return ()
    return tuple(sorted(path.name for path in stage_dir.iterdir() if path.is_dir() and path.name.startswith("annotator_")))


def json_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".json"),
        key=numeric_path_key,
    )


def evaluate_annotation_file(
    annotation_file: AnnotationFile,
    *,
    gold_root: Path,
    reference_annotators: dict[tuple[str, str], str],
    zh_gold_annotator: str,
    include_leaf_values: bool,
) -> dict[str, Any]:
    gold_path = gold_root / f"data_{annotation_file.lang}" / f"{annotation_file.sample_id}.json"
    reference_annotator = resolve_stage3_reference_annotator(
        annotation_file.lang,
        annotation_file.sample_id,
        reference_annotators,
        zh_gold_annotator=zh_gold_annotator,
    )
    row: dict[str, Any] = {
        "annotator": annotation_file.annotator,
        "reference": reference_annotator,
        "comparison_label": f"{annotation_file.annotator}__vs__{reference_annotator}",
        "lang": annotation_file.lang,
        "sample_id": annotation_file.sample_id,
        "annotation_path": str(annotation_file.path),
        "reference_path": str(gold_path),
        "status": "ok",
    }

    annotation, annotation_error = load_json(annotation_file.path, missing_status="missing_annotation")
    gold, gold_error = load_json(gold_path, missing_status="missing_gold")
    if annotation_error:
        row["status"] = annotation_error
    elif gold_error:
        row["status"] = gold_error

    if annotation_error or gold_error:
        row.update(empty_metric_values())
        return row

    table_iaa = 1.0 if canonical_json(annotation, case_insensitive=False) == canonical_json(gold, case_insensitive=False) else 0.0
    table_iaa_ci = 1.0 if canonical_json(annotation, case_insensitive=True) == canonical_json(gold, case_insensitive=True) else 0.0

    node_scores = calculate_label_scores(annotation, gold, include_leaf_values=include_leaf_values, case_insensitive=False)
    node_scores_ci = calculate_label_scores(annotation, gold, include_leaf_values=include_leaf_values, case_insensitive=True)

    annotation_paths = extract_node_paths(annotation, include_leaf_values=include_leaf_values, case_insensitive=False)
    gold_paths = extract_node_paths(gold, include_leaf_values=include_leaf_values, case_insensitive=False)
    path_scores = calculate_node_scores(annotation_paths, gold_paths)

    annotation_paths_ci = extract_node_paths(annotation, include_leaf_values=include_leaf_values, case_insensitive=True)
    gold_paths_ci = extract_node_paths(gold, include_leaf_values=include_leaf_values, case_insensitive=True)
    path_scores_ci = calculate_node_scores(annotation_paths_ci, gold_paths_ci)

    row.update(
        {
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
    )
    return row


def load_stage3_reference_annotators(
    en_annotators_xlsx: Path,
    *,
    zh_gold_annotator: str,
) -> dict[tuple[str, str], str]:
    reference_annotators: dict[tuple[str, str], str] = {}
    if en_annotators_xlsx.exists():
        for row in read_annotator_rows(en_annotators_xlsx):
            sample_id = normalize_sample_id(row.get("id", ""))
            owner = normalize_text(row.get("owner", row.get("\u8d1f\u8d23\u4eba", "")), case_insensitive=False)
            if sample_id and owner:
                reference_annotators[("en", sample_id)] = annotator_code(owner)
    reference_annotators[("zh", "*")] = zh_gold_annotator
    return reference_annotators


def resolve_stage3_reference_annotator(
    lang: str,
    sample_id: str,
    reference_annotators: dict[tuple[str, str], str],
    *,
    zh_gold_annotator: str,
) -> str:
    if lang == "zh":
        return reference_annotators.get(("zh", "*"), zh_gold_annotator)
    return reference_annotators.get((lang, normalize_sample_id(sample_id)), "gold")


def read_annotator_rows(path: Path) -> list[dict[str, str]]:
    rows = read_xlsx_rows(path)
    if not rows:
        return []
    header = [normalize_text(cell, case_insensitive=False) for cell in rows[0]]
    output: list[dict[str, str]] = []
    for row in rows[1:]:
        item = {
            header[index]: normalize_text(value, case_insensitive=False)
            for index, value in enumerate(row)
            if index < len(header) and header[index]
        }
        if item:
            output.append(item)
    return output


def read_xlsx_rows(path: Path) -> list[list[str]]:
    with ZipFile(path) as zf:
        names = set(zf.namelist())
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in names:
            return []
        shared_strings = read_shared_strings(zf) if "xl/sharedStrings.xml" in names else []
        sheet_root = ET.fromstring(zf.read(sheet_name))
        rows: list[list[str]] = []
        for row_element in sheet_root.findall(".//a:sheetData/a:row", XLSX_NS):
            row_values: list[str] = []
            for cell in row_element.findall("a:c", XLSX_NS):
                ref = cell.attrib.get("r", "A1")
                index = xlsx_column_index(ref)
                while len(row_values) <= index:
                    row_values.append("")
                row_values[index] = read_xlsx_cell(cell, shared_strings)
            rows.append(row_values)
        return rows


def read_shared_strings(zf: ZipFile) -> list[str]:
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(text.text or "" for text in item.findall(".//a:t", XLSX_NS)) for item in root.findall("a:si", XLSX_NS)]


def read_xlsx_cell(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//a:t", XLSX_NS))
    value = cell.find("a:v", XLSX_NS)
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        return shared_strings[int(value.text)]
    return value.text


def xlsx_column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 0
    index = 0
    for char in match.group(1):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def normalize_sample_id(value: Any) -> str:
    text = normalize_text(value, case_insensitive=False)
    if re.fullmatch(r"\d+(?:\\.0+)?", text):
        return str(int(float(text)))
    return text


def annotator_code(name: str) -> str:
    text = normalize_text(name, case_insensitive=False)
    if not text:
        return "gold"
    if text.startswith("annotator_"):
        return text
    return NAME_TO_ANNOTATOR.get(text, "annotator_external")


def canonical_json(value: Any, *, case_insensitive: bool) -> Any:
    if isinstance(value, dict):
        return (
            "dict",
            tuple(
                sorted(
                    (normalize_text(key, case_insensitive=case_insensitive), canonical_json(child, case_insensitive=case_insensitive))
                    for key, child in value.items()
                )
            ),
        )
    if isinstance(value, list):
        return ("list", tuple(canonical_json(item, case_insensitive=case_insensitive) for item in value))
    if isinstance(value, str):
        return ("str", normalize_text(value, case_insensitive=case_insensitive))
    if value is None:
        return ("none", None)
    return (type(value).__name__, value)


def extract_node_paths(
    value: Any,
    *,
    include_leaf_values: bool,
    case_insensitive: bool,
    current_path: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = normalize_text(key, case_insensitive=case_insensitive)
            child_path = current_path + (f"K:{key_text}",)
            paths.add(child_path)
            paths.update(
                extract_node_paths(
                    child,
                    include_leaf_values=include_leaf_values,
                    case_insensitive=case_insensitive,
                    current_path=child_path,
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = current_path + (f"I:{index}",)
            paths.add(child_path)
            paths.update(
                extract_node_paths(
                    child,
                    include_leaf_values=include_leaf_values,
                    case_insensitive=case_insensitive,
                    current_path=child_path,
                )
            )
    elif include_leaf_values and is_meaningful_leaf(value):
        leaf_text = normalize_text(value, case_insensitive=case_insensitive)
        if leaf_text:
            paths.add(current_path + (f"V:{leaf_text}",))
    return paths


def extract_node_labels(
    value: Any,
    *,
    include_leaf_values: bool,
    case_insensitive: bool,
) -> list[str]:
    labels: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            labels.append(f"K:{normalize_text(key, case_insensitive=case_insensitive)}")
            labels.extend(
                extract_node_labels(
                    child,
                    include_leaf_values=include_leaf_values,
                    case_insensitive=case_insensitive,
                )
            )
    elif isinstance(value, list):
        for child in value:
            labels.append("I:[]")
            labels.extend(
                extract_node_labels(
                    child,
                    include_leaf_values=include_leaf_values,
                    case_insensitive=case_insensitive,
                )
            )
    elif include_leaf_values and is_meaningful_leaf(value):
        leaf_text = normalize_text(value, case_insensitive=case_insensitive)
        if leaf_text:
            labels.append(f"V:{leaf_text}")
    return labels


def calculate_label_scores(
    annotation: Any,
    gold: Any,
    *,
    include_leaf_values: bool,
    case_insensitive: bool,
) -> NodeScores:
    annotation_counter = Counter(
        extract_node_labels(annotation, include_leaf_values=include_leaf_values, case_insensitive=case_insensitive)
    )
    gold_counter = Counter(extract_node_labels(gold, include_leaf_values=include_leaf_values, case_insensitive=case_insensitive))
    true_positive = sum((annotation_counter & gold_counter).values())
    pred_count = sum(annotation_counter.values())
    gold_count = sum(gold_counter.values())
    if pred_count == 0 and gold_count == 0:
        return NodeScores(1.0, 1.0, 1.0, 0, 0, 0)
    precision = true_positive / pred_count if pred_count else 0.0
    recall = true_positive / gold_count if gold_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return NodeScores(precision, recall, f1, true_positive, pred_count, gold_count)


def calculate_node_scores(annotation_paths: set[tuple[str, ...]], gold_paths: set[tuple[str, ...]]) -> NodeScores:
    if not annotation_paths and not gold_paths:
        return NodeScores(1.0, 1.0, 1.0, 0, 0, 0)
    true_positive = len(annotation_paths & gold_paths)
    pred_count = len(annotation_paths)
    gold_count = len(gold_paths)
    precision = true_positive / pred_count if pred_count else 0.0
    recall = true_positive / gold_count if gold_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return NodeScores(precision, recall, f1, true_positive, pred_count, gold_count)


def summarize(detail_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    ok_rows = [row for row in detail_rows if row.get("status") == "ok"]
    for row in ok_rows:
        groups[(str(row["annotator"]), str(row["lang"]))].append(row)
        groups[(str(row["annotator"]), "both")].append(row)
        groups[("ALL", str(row["lang"]))].append(row)
        groups[("ALL", "both")].append(row)

    summary_rows = [
        summarize_group(annotator, lang, rows)
        for (annotator, lang), rows in sorted(groups.items(), key=summary_sort_key)
        if rows
    ]
    status_counts: dict[str, int] = defaultdict(int)
    for row in detail_rows:
        status_counts[str(row.get("status", ""))] += 1
    summary_json = {
        "detail_count": len(detail_rows),
        "valid_count": len(ok_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "summary": summary_rows,
    }
    return summary_rows, summary_json


def summarize_group(annotator: str, lang: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    node_tp = sum(int(row["node_tp"]) for row in rows)
    node_pred = sum(int(row["annotation_node_count"]) for row in rows)
    node_gold = sum(int(row["reference_node_count"]) for row in rows)
    node_micro_precision = node_tp / node_pred if node_pred else 0.0
    node_micro_recall = node_tp / node_gold if node_gold else 0.0
    node_micro_f1 = (
        2 * node_micro_precision * node_micro_recall / (node_micro_precision + node_micro_recall)
        if node_micro_precision + node_micro_recall
        else 0.0
    )
    path_tp = sum(int(row["node_path_tp"]) for row in rows)
    path_pred = sum(int(row["annotation_path_node_count"]) for row in rows)
    path_gold = sum(int(row["reference_path_node_count"]) for row in rows)
    path_micro_precision = path_tp / path_pred if path_pred else 0.0
    path_micro_recall = path_tp / path_gold if path_gold else 0.0
    path_micro_f1 = (
        2 * path_micro_precision * path_micro_recall / (path_micro_precision + path_micro_recall)
        if path_micro_precision + path_micro_recall
        else 0.0
    )
    return {
        "annotator": annotator,
        "lang": lang,
        "file_count": len(rows),
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
        "annotator",
        "reference",
        "comparison_label",
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
        "annotator",
        "lang",
        "file_count",
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


def print_summary(summary_rows: list[dict[str, Any]]) -> None:
    if not summary_rows:
        print("No valid annotation/gold pairs were found.")
        return
    print("Stage 3 IAA summary:")
    for row in summary_rows:
        if row["annotator"] != "ALL" or row["lang"] != "both":
            continue
        print(
            "  OVERALL "
            f"files={row['file_count']} "
            f"table_iaa={pct(row['table_iaa'])} "
            f"node_iaa_macro={pct(row['node_iaa_macro'])} "
            f"node_iaa_micro={pct(row['node_iaa_micro'])}"
        )
    for row in summary_rows:
        if row["annotator"] == "ALL" and row["lang"] == "both":
            continue
        print(
            f"  {row['annotator']} | {row['lang']} "
            f"files={row['file_count']} "
            f"table={pct(row['table_iaa'])} "
            f"node_macro={pct(row['node_iaa_macro'])} "
            f"node_micro={pct(row['node_iaa_micro'])}"
        )


def load_json(path: Path, *, missing_status: str) -> tuple[Any | None, str | None]:
    if not path.exists():
        return None, missing_status
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception:
        return None, "invalid_json"


def normalize_text(value: Any, *, case_insensitive: bool) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold() if case_insensitive else text


def is_meaningful_leaf(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(normalize_text(value, case_insensitive=False))
    return isinstance(value, (int, float, bool))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def numeric_path_key(path: Path) -> tuple[int, str]:
    return (numeric_id(path.stem), path.stem)


def numeric_id(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 10**12


def summary_sort_key(item: tuple[tuple[str, str], list[dict[str, Any]]]) -> tuple[int, str, int, str]:
    annotator, lang = item[0]
    return (1 if annotator == "ALL" else 0, annotator, 1 if lang == "both" else 0, lang)


def mean(values: Iterable[float]) -> float:
    data = list(values)
    return sum(data) / len(data) if data else 0.0


def format_float(value: float) -> str:
    return f"{value:.6f}"


def pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return ""


if __name__ == "__main__":
    main()
