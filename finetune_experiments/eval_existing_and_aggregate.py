from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finetune_experiments.checkpoint_utils import (
    DEFAULT_CHECKPOINT_TASKS,
    expand_checkpoint_langs,
    expand_checkpoint_tasks,
    load_test_records,
    prediction_path_for_record as checkpoint_prediction_path_for_record,
)
from finetune_experiments.evaluate_checkpoint_predictions import gold_file_for_record, read_prediction_text
from finetune_experiments.finetune_data import COMBINED_LANG, DATASET_DIR, FINETUNE_ROOT, PREDICTIONS_DIR, clean_model_name
from comparative_eval.config import OPEN_SOURCE_MODELS, prediction_dir, workflow_paths
from comparative_eval.eval_alignment import (
    choose_coordinate_strategy,
    compare_alignment,
    expand_meta,
    resolve_expected_names_from_gold,
)
from comparative_eval.eval_schema import parse_schema_json, zero_similarity_result
from comparative_eval.metrics.infill import (
    SOURCE_FAITHFUL_MATCHER,
    SUPPORTED_INFILL_MATCHERS,
    compare_infill,
)
from comparative_eval.metrics.jedi_cpp import compare_json_similarity_cpp
from comparative_eval.metrics.jedi_py import compare_json_similarity
from comparative_eval.utils.io_utils import ensure_dir, read_csv, read_json, read_text, write_csv, write_json, write_text


RESULTS_DIR = FINETUNE_ROOT / "results"
SUPPORTED_BASE_ORDER = (
    "Llama-3.1-8B-Instruct",
    "Qwen2.5-7B-Instruct",
    "Gemma-2-9B-it",
    "Mistral-7B-Instruct-v0.3",
)
TASK_TABLE4_LABELS = {
    "schema": "Task 1 (SSP)",
    "alignment": "Task 2 (CHA)",
    "infill": "Task 3 (Infilling)",
}
TASK_TABLE4_KEYS = {
    "schema": "task1_ssp",
    "alignment": "task2_cha",
    "infill": "task3_infill",
}
CACHE_VERSION = "table4_detail_v1"
INFILL_CACHE_VERSION = "table4_detail_v2_infill"
CACHE_COMPARE_FIELDS = (
    "cache_version",
    "cache_key",
    "schema_metric",
    "active_prediction_sha1",
    "paired_prediction_sha1",
    "source_fingerprint",
)


@dataclass
class TaskScore:
    kind: str
    sample_count: int = 0
    correct: float = 0.0
    total: float = 0.0

    def add_schema(self, score: float) -> None:
        self.sample_count += 1
        self.correct += score
        self.total += 1

    def add_accuracy_counts(self, correct: int, total: int) -> None:
        self.sample_count += 1
        self.correct += correct
        self.total += total

    @property
    def score(self) -> float | None:
        if self.total <= 0:
            return None
        return self.correct / self.total


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Table 4: Base vs fine-tuned models on the fine-tune test split, "
            "using the Base/FT prediction intersection for each model/task/language."
        )
    )
    parser.add_argument("--dataset_dir", "--dataset-dir", dest="dataset_dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--tasks", nargs="*", choices=[*DEFAULT_CHECKPOINT_TASKS, "all"], default=["all"])
    parser.add_argument("--lang", default=COMBINED_LANG, choices=[COMBINED_LANG, "en", "zh"])
    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="Explicit fine-tuned prediction model directories. Defaults to scanning finetune_experiments/predictions.",
    )
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
        "--resume_from_details",
        "--resume-from-details",
        dest="resume_from_details",
        action="store_true",
        help="Reuse unchanged rows from the existing Table 4 details CSV.",
    )
    parser.add_argument(
        "--include_qa_variants",
        "--include-qa-variants",
        dest="include_qa_variants",
        action="store_true",
        help="Also evaluate QA fine-tuned prediction directories as QA rows.",
    )
    parser.add_argument("--dry_run", "--dry-run", dest="dry_run", action="store_true")
    args = parser.parse_args()

    tasks = expand_checkpoint_tasks(args.tasks)
    langs = expand_checkpoint_langs(args.lang)
    records_by_task = {
        task: load_test_records(task, args.lang, args.dataset_dir, args.limit)
        for task in tasks
    }
    ft_models = unique_models(args.models or discover_ft_prediction_models(tasks, langs))
    if not ft_models:
        print(f"No fine-tuned prediction model directories found under {PREDICTIONS_DIR}.")
        return

    model_pairs = resolve_model_pairs(ft_models, include_qa_variants=args.include_qa_variants)
    if not model_pairs:
        print("No fine-tuned prediction models could be mapped to supported Base models.")
        return

    coverage_rows = coverage_for_pairs(records_by_task, model_pairs, langs)
    default_prefix = "table4_base_vs_ft_qa" if args.include_qa_variants else "table4_base_vs_ft"
    output_prefix = args.output_prefix or f"{default_prefix}_{args.lang}_test_intersection"
    write_coverage(output_prefix, coverage_rows)
    print_coverage(coverage_rows)
    if args.dry_run:
        return

    detail_path = RESULTS_DIR / f"{output_prefix}_details.csv"
    cached_rows = load_cached_detail_rows(detail_path) if args.resume_from_details else {}
    table = compute_table4(
        records_by_task,
        model_pairs,
        langs,
        args.schema_metric,
        args.infill_matcher,
        args.cpp_timeout,
        cached_rows,
    )
    write_table4(
        output_prefix,
        table,
        args.schema_metric,
        args.infill_matcher,
        coverage_rows,
        include_qa_variants=args.include_qa_variants,
    )
    stats = table.get("cache_stats", {})
    if args.resume_from_details:
        print(
            f"Table 4 detail cache: reused={stats.get('reused', 0)} "
            f"computed={stats.get('computed', 0)}",
            flush=True,
        )


def discover_ft_prediction_models(tasks: tuple[str, ...], langs: tuple[str, ...]) -> list[str]:
    models: set[str] = set()
    for task in tasks:
        for lang in langs:
            root = PREDICTIONS_DIR / f"{task}_empty" / lang
            if not root.exists():
                continue
            for child in root.iterdir():
                if child.is_dir():
                    models.add(canonical_ft_model_name(child.name))
    return sorted(models)


def resolve_model_pairs(ft_models: list[str], include_qa_variants: bool = False) -> list[dict[str, str]]:
    pairs = []
    for ft_model in ft_models:
        comparison_method = infer_finetune_method(ft_model)
        if comparison_method == "QA" and not include_qa_variants:
            continue
        base_model = infer_base_model(ft_model)
        if base_model is None:
            print(f"Warning: cannot infer Base model for fine-tuned predictions: {ft_model}", flush=True)
            continue
        pairs.append({"ft_model": ft_model, "base_model": base_model, "comparison_method": comparison_method})
    return sorted(pairs, key=lambda item: (*model_order_key(item["base_model"]), method_order_key(item["comparison_method"]), item["ft_model"]))


def infer_base_model(ft_model: str) -> str | None:
    name = normalized_finetuned_base_name(ft_model)
    for base_model in OPEN_SOURCE_MODELS:
        if name == base_model or name == clean_model_name(base_model):
            return base_model
    return None


def canonical_ft_model_name(ft_model: str) -> str:
    name = ft_model.strip()
    name = re.sub(r"^(?:schema|alignment|infill)[\s_-]+(?:en|zh)[\s_-]+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*_\s*", "_", name)
    name = re.sub(r"\s+", "_", name)
    return name


def normalized_finetuned_base_name(ft_model: str) -> str:
    name = canonical_ft_model_name(ft_model).removeprefix("finetuned_")
    suffix_patterns = (
        (r"[\s_-]seed=\d+$", re.IGNORECASE),
        (r"[\s_-]checkpoint(?:[\s_-]\d+)?$", 0),
        (r"[\s_-]InfillFT(?:[\s_-].*)?$", re.IGNORECASE),
        (r"[\s_-]infill(?:[\s_-].*)?$", re.IGNORECASE),
        (r"[\s_-]QA(?:[\s_-].*)?$", 0),
        (r"[\s_-]repair$", re.IGNORECASE),
    )
    changed = True
    while changed:
        changed = False
        for pattern, flags in suffix_patterns:
            updated = re.sub(pattern, "", name, flags=flags)
            if updated != name:
                name = updated
                changed = True
                break
    return name


def infer_finetune_method(ft_model: str) -> str:
    return "QA" if re.search(r"(?:^|[\s_-])QA(?:[\s_-]|$)", canonical_ft_model_name(ft_model)) else "FT"


def method_order_key(method: str) -> int:
    return {"FT": 0, "QA": 1}.get(method, 9)


def model_order_key(base_model: str) -> tuple[int, str]:
    try:
        return (SUPPORTED_BASE_ORDER.index(base_model), base_model)
    except ValueError:
        return (len(SUPPORTED_BASE_ORDER), base_model)


def coverage_for_pairs(
    records_by_task: dict[str, list[dict[str, Any]]],
    model_pairs: list[dict[str, str]],
    langs: tuple[str, ...],
) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for pair in model_pairs:
        ft_model = pair["ft_model"]
        base_model = pair["base_model"]
        comparison_method = pair["comparison_method"]
        for task, records in records_by_task.items():
            for lang in langs:
                lang_records = [record for record in records if record.get("lang") == lang]
                ft_ids = prediction_ids(lang_records, lambda record: prediction_path_for_record(record, ft_model))
                base_ids = prediction_ids(lang_records, lambda record: base_prediction_path(record, base_model))
                test_ids = {int(record["sample_id"]) for record in lang_records}
                intersection_ids = ft_ids & base_ids
                rows.append(
                    {
                        "model": base_model,
                        "ft_model": ft_model,
                        "comparison_method": comparison_method,
                        "task": task,
                        "condition": "empty",
                        "lang": lang,
                        "test_count": len(test_ids),
                        "base_prediction_count": len(base_ids),
                        "ft_prediction_count": len(ft_ids),
                        "intersection_count": len(intersection_ids),
                        "base_missing_count": len(test_ids - base_ids),
                        "ft_missing_count": len(test_ids - ft_ids),
                        "base_missing_ids": " ".join(str(item) for item in sorted(test_ids - base_ids)[:50]),
                        "ft_missing_ids": " ".join(str(item) for item in sorted(test_ids - ft_ids)[:50]),
                    }
                )
    return rows


def prediction_ids(records: list[dict[str, Any]], path_for_record: Any) -> set[int]:
    ids = set()
    for record in records:
        path = path_for_record(record)
        if read_prediction_text(path):
            ids.add(int(record["sample_id"]))
    return ids


def prediction_path_for_record(record: dict[str, Any], prediction_model_name: str) -> Path:
    direct_path = checkpoint_prediction_path_for_record(record, prediction_model_name)
    if direct_path.exists():
        return direct_path

    task = str(record["task"])
    condition = str(record.get("condition", "empty"))
    lang = str(record["lang"])
    sample_id = int(record["sample_id"])
    root = PREDICTIONS_DIR / f"{task}_{condition}" / lang
    if not root.exists():
        return direct_path

    canonical_name = canonical_ft_model_name(prediction_model_name)
    matches = sorted(
        child
        for child in root.iterdir()
        if child.is_dir() and canonical_ft_model_name(child.name) == canonical_name
    )
    if not matches:
        return direct_path
    return matches[0] / f"{sample_id}.json"


def base_prediction_path(record: dict[str, Any], base_model: str) -> Path:
    task = str(record["task"])
    lang = str(record["lang"])
    sample_id = int(record["sample_id"])
    return prediction_dir(task, "empty", lang, base_model) / f"{sample_id}.json"


def write_coverage(output_prefix: str, rows: list[dict[str, str | int]]) -> None:
    fields = [
        "model",
        "ft_model",
        "comparison_method",
        "task",
        "condition",
        "lang",
        "test_count",
        "base_prediction_count",
        "ft_prediction_count",
        "intersection_count",
        "base_missing_count",
        "ft_missing_count",
        "base_missing_ids",
        "ft_missing_ids",
    ]
    write_csv(RESULTS_DIR / f"{output_prefix}_coverage.csv", rows, fields)
    write_json(RESULTS_DIR / f"{output_prefix}_coverage.json", {"rows": rows})


def print_coverage(rows: list[dict[str, str | int]]) -> None:
    print("Table 4 Base/FT test-split prediction intersection coverage:", flush=True)
    for row in rows:
        print(
            f"  {row['model']} | {row['comparison_method']} | {row['task']} | {row['lang']}: "
            f"intersection={row['intersection_count']}/{row['test_count']}, "
            f"base_missing={row['base_missing_count']}, ft_missing={row['ft_missing_count']}",
            flush=True,
        )


def compute_table4(
    records_by_task: dict[str, list[dict[str, Any]]],
    model_pairs: list[dict[str, str]],
    langs: tuple[str, ...],
    schema_metric: str,
    infill_matcher: str,
    cpp_timeout: float,
    cached_rows: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    model_rows = []
    details: list[dict[str, Any]] = []
    cache_stats = {"reused": 0, "computed": 0}
    cached_rows = cached_rows or {}

    for pair in model_pairs:
        base_model = pair["base_model"]
        ft_model = pair["ft_model"]
        comparison_method = pair["comparison_method"]
        model_scores = {
            "Base": {task: TaskScore(kind="schema" if task == "schema" else "counts") for task in DEFAULT_CHECKPOINT_TASKS},
            comparison_method: {task: TaskScore(kind="schema" if task == "schema" else "counts") for task in DEFAULT_CHECKPOINT_TASKS},
        }

        for task, records in records_by_task.items():
            for lang in langs:
                lang_records = [record for record in records if record.get("lang") == lang]
                intersection_records = [
                    record
                    for record in lang_records
                    if read_prediction_text(prediction_path_for_record(record, ft_model))
                    and read_prediction_text(base_prediction_path(record, base_model))
                ]
                for method, active_path_fn, paired_path_fn in (
                    (
                        "Base",
                        lambda record, current_base=base_model: base_prediction_path(record, current_base),
                        lambda record, current_ft=ft_model: prediction_path_for_record(record, current_ft),
                    ),
                    (
                        comparison_method,
                        lambda record, current_ft=ft_model: prediction_path_for_record(record, current_ft),
                        lambda record, current_base=base_model: base_prediction_path(record, current_base),
                    ),
                ):
                    task_score, task_details = score_records(
                        task,
                        method,
                        base_model,
                        ft_model,
                        intersection_records,
                        active_path_fn,
                        paired_path_fn,
                        schema_metric,
                        infill_matcher,
                        cpp_timeout,
                        cached_rows,
                        cache_stats,
                        comparison_method,
                    )
                    add_task_score(model_scores[method][task], task_score)
                    details.extend(task_details)

        base_row = table_row(base_model, ft_model, "Base", model_scores["Base"], comparison_method)
        ft_row = table_row(base_model, ft_model, comparison_method, model_scores[comparison_method], comparison_method)
        ft_row["delta_avg"] = pct_diff(ft_row["avg_value"], base_row["avg_value"])
        model_rows.extend([base_row, ft_row])

    for comparison_method in sorted({row["comparison_method"] for row in model_rows}, key=method_order_key):
        average_base = average_table_row(model_rows, "Base", comparison_method)
        average_ft = average_table_row(model_rows, comparison_method, comparison_method)
        average_ft["delta_avg"] = pct_diff(average_ft["avg_value"], average_base["avg_value"])
        model_rows.extend([average_base, average_ft])

    return {"rows": model_rows, "details": details, "cache_stats": cache_stats}


def score_records(
    task: str,
    method: str,
    base_model: str,
    ft_model: str,
    records: list[dict[str, Any]],
    path_for_record: Any,
    paired_path_for_record: Any,
    schema_metric: str,
    infill_matcher: str,
    cpp_timeout: float,
    cached_rows: dict[str, dict[str, str]],
    cache_stats: dict[str, int],
    comparison_method: str,
) -> tuple[TaskScore, list[dict[str, Any]]]:
    score = TaskScore(kind="schema" if task == "schema" else "counts")
    details = []
    for record in records:
        sample_id = int(record["sample_id"])
        lang = str(record["lang"])
        active_path = path_for_record(record)
        paired_path = paired_path_for_record(record)
        cache_record = detail_cache_record(
            record,
            task,
            method,
            base_model,
            ft_model,
            active_path,
            paired_path,
            schema_metric,
            infill_matcher,
        )
        cached_row = cached_rows.get(cache_record["cache_key"])
        if cached_detail_is_current(cached_row, cache_record):
            add_cached_detail_to_score(score, cached_row)
            details.append(cached_row)
            cache_stats["reused"] += 1
            continue

        pred_text = read_prediction_text(active_path)
        if task == "schema":
            sample_score, pred_status = score_schema_record(record, pred_text, schema_metric, cpp_timeout)
            score.add_schema(sample_score)
            details.append(add_detail_cache(detail_row(base_model, ft_model, comparison_method, method, task, lang, sample_id, sample_score, 1, pred_status), cache_record))
        elif task == "alignment":
            correct, total, pred_status = score_alignment_record(record, pred_text)
            score.add_accuracy_counts(correct, total)
            details.append(add_detail_cache(detail_row(base_model, ft_model, comparison_method, method, task, lang, sample_id, correct, total, pred_status), cache_record))
        elif task == "infill":
            correct, total, pred_status = score_infill_record(record, pred_text, infill_matcher)
            score.add_accuracy_counts(correct, total)
            details.append(add_detail_cache(detail_row(base_model, ft_model, comparison_method, method, task, lang, sample_id, correct, total, pred_status), cache_record))
        else:
            raise ValueError(task)
        cache_stats["computed"] += 1
    return score, details


def score_schema_record(record: dict[str, Any], pred_text: str, schema_metric: str, cpp_timeout: float) -> tuple[float, str]:
    gold = read_json(gold_file_for_record(record, "schema"))
    pred_obj, pred_status = parse_schema_json(pred_text)
    gold_obj, gold_status = parse_schema_json(gold, source="gold")
    if pred_obj is None or gold_obj is None:
        res = zero_similarity_result(pred_status, schema_metric, gold_status=gold_status)
    elif schema_metric == "cpp":
        res = compare_json_similarity_cpp(pred_obj, gold_obj, timeout=cpp_timeout)
    else:
        mode = "fast_structural" if schema_metric == "py_fast" else "tree_edit"
        res = compare_json_similarity(pred_obj, gold_obj, mode=mode)
    return float(res["similarity"]), pred_status


def score_alignment_record(record: dict[str, Any], pred_html: str) -> tuple[int, int, str]:
    from comparative_eval.eval_alignment import FIELD_TYPES

    sample_id = int(record["sample_id"])
    lang = str(record["lang"])
    paths = workflow_paths(lang)
    meta_file = paths.meta / f"{sample_id}.json"
    gold_file = gold_file_for_record(record, "alignment")
    if not meta_file.exists() or not gold_file.exists():
        return 0, 0, "missing_gold"

    expected = expand_meta(read_json(meta_file))
    if not expected:
        return 0, 0, "missing_expected"
    gold_html = read_text(gold_file)
    strategy = choose_coordinate_strategy(gold_html, expected)
    expected = resolve_expected_names_from_gold(gold_html, expected, strategy)
    results, _records = compare_alignment(pred_html, expected, strategy)
    correct = sum(int(results[field_type]["correct"]) for field_type in FIELD_TYPES)
    total = sum(int(results[field_type]["total"]) for field_type in FIELD_TYPES)
    return correct, total, "ok"


def score_infill_record(
    record: dict[str, Any],
    pred_html: str,
    infill_matcher: str = SOURCE_FAITHFUL_MATCHER,
) -> tuple[int, int, str]:
    sample_id = int(record["sample_id"])
    lang = str(record["lang"])
    paths = workflow_paths(lang)
    gold_file = gold_file_for_record(record, "infill")
    ph_file = paths.placeholder_html / f"{sample_id}.html"
    if not gold_file.exists() or not ph_file.exists():
        return 0, 0, "missing_gold"
    correct, total = compare_infill(
        pred_html,
        read_text(gold_file),
        read_text(ph_file),
        matcher=infill_matcher,
    )
    return correct, total, "ok"


def detail_row(
    base_model: str,
    ft_model: str,
    comparison_method: str,
    method: str,
    task: str,
    lang: str,
    sample_id: int,
    correct_or_score: float,
    total: float,
    pred_status: str,
) -> dict[str, Any]:
    score = correct_or_score / total if total else None
    return {
        "model": base_model,
        "ft_model": ft_model,
        "comparison_method": comparison_method,
        "method": method,
        "task": task,
        "condition": "empty",
        "lang": lang,
        "sample_id": sample_id,
        "correct_or_score": f"{correct_or_score:.6f}",
        "total": f"{total:.6f}",
        "score": f"{score:.6f}" if score is not None else "",
        "pred_status": pred_status,
    }


def detail_cache_record(
    record: dict[str, Any],
    task: str,
    method: str,
    base_model: str,
    ft_model: str,
    active_prediction_path: Path,
    paired_prediction_path: Path,
    schema_metric: str,
    infill_matcher: str,
) -> dict[str, str]:
    lang = str(record["lang"])
    sample_id = int(record["sample_id"])
    active_fingerprint = file_fingerprint(active_prediction_path)
    paired_fingerprint = file_fingerprint(paired_prediction_path)
    source_paths = source_paths_for_record(record, task)
    source_fingerprint = "|".join(file_fingerprint(path)["fingerprint"] for path in source_paths)
    source_path_text = "|".join(str(path) for path in source_paths)
    cache_key_parts = [
        base_model,
        ft_model,
        method,
        task,
        "empty",
        lang,
        str(sample_id),
        schema_metric,
    ]
    if task == "infill":
        cache_key_parts.append(infill_matcher)
    cache_key = "::".join(cache_key_parts)
    return {
        "cache_version": INFILL_CACHE_VERSION if task == "infill" else CACHE_VERSION,
        "cache_key": cache_key,
        "schema_metric": schema_metric,
        "infill_matcher": infill_matcher if task == "infill" else "",
        "active_prediction_path": active_fingerprint["path"],
        "active_prediction_mtime_ns": active_fingerprint["mtime_ns"],
        "active_prediction_size": active_fingerprint["size"],
        "active_prediction_sha1": active_fingerprint["sha1"],
        "paired_prediction_path": paired_fingerprint["path"],
        "paired_prediction_mtime_ns": paired_fingerprint["mtime_ns"],
        "paired_prediction_size": paired_fingerprint["size"],
        "paired_prediction_sha1": paired_fingerprint["sha1"],
        "source_paths": source_path_text,
        "source_fingerprint": source_fingerprint,
    }


def source_paths_for_record(record: dict[str, Any], task: str) -> list[Path]:
    lang = str(record["lang"])
    sample_id = int(record["sample_id"])
    paths = workflow_paths(lang)
    if task == "schema":
        return [gold_file_for_record(record, "schema")]
    if task == "alignment":
        return [paths.meta / f"{sample_id}.json", gold_file_for_record(record, "alignment")]
    if task == "infill":
        return [gold_file_for_record(record, "infill"), paths.placeholder_html / f"{sample_id}.html"]
    raise ValueError(task)


def file_fingerprint(path: Path) -> dict[str, str]:
    if not path.exists():
        return {
            "path": str(path),
            "mtime_ns": "",
            "size": "",
            "sha1": "missing",
            "fingerprint": f"{path}:missing",
        }
    data = path.read_bytes()
    stat = path.stat()
    sha1 = hashlib.sha1(data).hexdigest()
    return {
        "path": str(path),
        "mtime_ns": str(stat.st_mtime_ns),
        "size": str(stat.st_size),
        "sha1": sha1,
        "fingerprint": f"{path}:{stat.st_size}:{sha1}",
    }


def add_detail_cache(row: dict[str, Any], cache_record: dict[str, str]) -> dict[str, Any]:
    out = dict(row)
    out.update(cache_record)
    return out


def cached_detail_is_current(row: dict[str, str] | None, cache_record: dict[str, str]) -> bool:
    if not row:
        return False
    return all(str(row.get(field, "")) == str(cache_record.get(field, "")) for field in CACHE_COMPARE_FIELDS)


def add_cached_detail_to_score(score: TaskScore, row: dict[str, str]) -> None:
    correct_or_score = safe_float(row.get("correct_or_score"))
    total = safe_float(row.get("total"))
    if score.kind == "schema":
        score.add_schema(correct_or_score)
    else:
        score.add_accuracy_counts(int(round(correct_or_score)), int(round(total)))


def load_cached_detail_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        cache_key = str(row.get("cache_key", ""))
        if not cache_key:
            continue
        rows[cache_key] = row
    return rows


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def add_task_score(target: TaskScore, source: TaskScore) -> None:
    target.sample_count += source.sample_count
    target.correct += source.correct
    target.total += source.total


def table_row(base_model: str, ft_model: str, method: str, scores: dict[str, TaskScore], comparison_method: str) -> dict[str, Any]:
    task_values = {task: scores[task].score for task in DEFAULT_CHECKPOINT_TASKS}
    valid_values = [value for value in task_values.values() if value is not None]
    avg_value = sum(valid_values) / len(valid_values) if valid_values else None
    row: dict[str, Any] = {
        "model": base_model,
        "ft_model": ft_model,
        "comparison_method": comparison_method,
        "method": method,
        "avg_value": avg_value,
        "avg": pct(avg_value),
        "delta_avg": "-",
    }
    for task in DEFAULT_CHECKPOINT_TASKS:
        key = TASK_TABLE4_KEYS[task]
        row[f"{key}_value"] = task_values[task]
        row[key] = pct(task_values[task])
        row[f"{key}_sample_count"] = scores[task].sample_count
    return row


def average_table_row(rows: list[dict[str, Any]], method: str, comparison_method: str) -> dict[str, Any]:
    selected_rows = [
        row
        for row in rows
        if row.get("method") == method
        and row.get("comparison_method") == comparison_method
        and row.get("model") != "Average"
    ]
    row: dict[str, Any] = {
        "model": "Average",
        "ft_model": "",
        "comparison_method": comparison_method,
        "method": method,
        "delta_avg": "-",
    }
    task_values = []
    for task in DEFAULT_CHECKPOINT_TASKS:
        key = TASK_TABLE4_KEYS[task]
        values = [item.get(f"{key}_value") for item in selected_rows if item.get(f"{key}_value") is not None]
        value = sum(values) / len(values) if values else None
        row[f"{key}_value"] = value
        row[key] = pct(value)
        row[f"{key}_sample_count"] = sum(int(item.get(f"{key}_sample_count") or 0) for item in selected_rows)
        if value is not None:
            task_values.append(value)
    row["avg_value"] = sum(task_values) / len(task_values) if task_values else None
    row["avg"] = pct(row["avg_value"])
    return row


def write_table4(
    output_prefix: str,
    table: dict[str, Any],
    schema_metric: str,
    infill_matcher: str,
    coverage_rows: list[dict[str, str | int]],
    include_qa_variants: bool = False,
) -> None:
    rows = table["rows"]
    summary_rows = qa_summary_rows(rows) if include_qa_variants else rows
    latex_rows = (
        qa_summary_rows(
            latest_variant_rows(rows),
            show_method_versions=False,
            tuned_method_order=("QA", "FT"),
        )
        if include_qa_variants
        else rows
    )
    detail_rows = table["details"]
    csv_fields = [
        "model",
        "method",
        "task1_ssp",
        "task2_cha",
        "task3_infill",
        "avg",
        "delta_avg",
        "ft_model",
        "task1_ssp_sample_count",
        "task2_cha_sample_count",
        "task3_infill_sample_count",
    ]
    detail_fields = [
        "model",
        "ft_model",
        "comparison_method",
        "method",
        "task",
        "condition",
        "lang",
        "sample_id",
        "correct_or_score",
        "total",
        "score",
        "pred_status",
        "cache_version",
        "cache_key",
        "schema_metric",
        "infill_matcher",
        "active_prediction_path",
        "active_prediction_mtime_ns",
        "active_prediction_size",
        "active_prediction_sha1",
        "paired_prediction_path",
        "paired_prediction_mtime_ns",
        "paired_prediction_size",
        "paired_prediction_sha1",
        "source_paths",
        "source_fingerprint",
    ]
    write_csv(RESULTS_DIR / f"{output_prefix}.csv", select_fields(summary_rows, csv_fields), csv_fields)
    write_csv(RESULTS_DIR / f"{output_prefix}_details.csv", select_fields(detail_rows, detail_fields), detail_fields)
    write_json(
        RESULTS_DIR / f"{output_prefix}.json",
        {
            "caption": (
                "Table 4: Base vs. fine-tuned models across three NEST tasks. "
                "Base and tuned-model scores are computed on the fine-tune test split using "
                "the per-model/task/language intersection of non-empty Base and tuned predictions."
            ),
            "schema_metric": schema_metric,
            "infill_matcher": infill_matcher,
            "include_qa_variants": include_qa_variants,
            "rows": summary_rows,
            "raw_comparison_rows": rows if include_qa_variants else None,
            "coverage_rows": coverage_rows,
            "cache_stats": table.get("cache_stats", {}),
        },
    )
    write_text(RESULTS_DIR / f"{output_prefix}.md", markdown_table(summary_rows))
    write_text(RESULTS_DIR / f"{output_prefix}.tex", latex_table(latex_rows, include_qa_variants=include_qa_variants))
    print(f"Wrote {RESULTS_DIR / f'{output_prefix}.csv'}")


def pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value * 100:.2f}%"


def pct_diff(ft_value: float | None, base_value: float | None) -> str:
    if ft_value is None or base_value is None:
        return ""
    diff = (ft_value - base_value) * 100
    if diff > 0:
        return f"+{diff:.2f}%"
    return f"{diff:.2f}%"


def qa_summary_rows(
    rows: list[dict[str, Any]],
    show_method_versions: bool = True,
    tuned_method_order: tuple[str, ...] = ("FT", "QA"),
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    model_order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        model = str(row.get("model", ""))
        if model not in grouped:
            grouped[model] = []
            model_order.append(model)
        grouped[model].append(row)

    for model in model_order:
        model_rows = grouped[model]
        base_rows = [row for row in model_rows if row.get("method") == "Base"]
        tuned_rows = [row for row in model_rows if row.get("method") != "Base"]
        if not base_rows and not tuned_rows:
            continue

        preferred_base = next((row for row in base_rows if row.get("comparison_method") == "FT"), base_rows[0] if base_rows else None)
        if preferred_base is not None:
            base_row = dict(preferred_base)
            base_row["method"] = "Base"
            base_row["delta_avg"] = "-"
            out.append(base_row)

        method_rank = {method: index for index, method in enumerate(tuned_method_order)}
        for tuned_row in sorted(
            tuned_rows,
            key=lambda row: (
                method_rank.get(str(row.get("comparison_method", row.get("method", ""))), len(method_rank)),
                method_order_key(str(row.get("comparison_method", row.get("method", "")))),
                str(row.get("ft_model", "")),
            ),
        ):
            row = dict(tuned_row)
            row["method"] = display_method_label(
                str(row.get("comparison_method", row.get("method", ""))),
                str(row.get("ft_model", "")),
                include_version=show_method_versions,
            )
            out.append(row)
    return out


def latest_variant_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    model_order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        model = str(row.get("model", ""))
        if model == "Average":
            continue
        if model not in grouped:
            grouped[model] = []
            model_order.append(model)
        grouped[model].append(row)

    for model in model_order:
        model_rows = grouped[model]
        comparison_methods = sorted(
            {
                str(row.get("comparison_method", ""))
                for row in model_rows
                if row.get("method") != "Base"
            },
            key=method_order_key,
        )
        for comparison_method in comparison_methods:
            tuned_candidates = [
                row
                for row in model_rows
                if row.get("method") == comparison_method
                and row.get("comparison_method") == comparison_method
            ]
            if not tuned_candidates:
                continue
            tuned_row = max(enumerate(tuned_candidates), key=lambda item: latest_variant_key(item[1], item[0]))[1]
            base_row = next(
                (
                    row
                    for row in model_rows
                    if row.get("method") == "Base"
                    and row.get("comparison_method") == comparison_method
                    and row.get("ft_model") == tuned_row.get("ft_model")
                ),
                None,
            )
            if base_row is not None:
                out.append(base_row)
            out.append(tuned_row)

    for comparison_method in sorted({row["comparison_method"] for row in out}, key=method_order_key):
        average_base = average_table_row(out, "Base", comparison_method)
        average_ft = average_table_row(out, comparison_method, comparison_method)
        average_ft["delta_avg"] = pct_diff(average_ft["avg_value"], average_base["avg_value"])
        out.extend([average_base, average_ft])

    return out


def latest_variant_key(row: dict[str, Any], index: int) -> tuple[int, int]:
    ft_model = str(row.get("ft_model", ""))
    method = str(row.get("comparison_method", row.get("method", "")))
    if method == "FT":
        version_match = re.search(r"[\s_-]InfillFT[\s_-]v?(\d+)$", ft_model, flags=re.IGNORECASE)
    elif method == "QA":
        version_match = re.search(r"[\s_-]QA[\s_-]v?(\d+)$", ft_model, flags=re.IGNORECASE)
    else:
        version_match = None
    version = int(version_match.group(1)) if version_match else 0
    return version, index


def display_method_label(method: str, ft_model: str = "", include_version: bool = True) -> str:
    if method == "FT":
        label = "Infill-FT"
        if not include_version:
            return label
        version_match = re.search(r"[\s_-]InfillFT[\s_-]v?(\d+)$", ft_model, flags=re.IGNORECASE)
        return f"{label} v{version_match.group(1)}" if version_match else label
    if method == "QA":
        label = "QA-FT"
        if not include_version:
            return label
        version_match = re.search(r"[\s_-]QA[\s_-]v?(\d+)$", ft_model, flags=re.IGNORECASE)
        return f"{label} v{version_match.group(1)}" if version_match else label
    return method


def markdown_table(rows: list[dict[str, Any]]) -> str:
    headers = ["Model", "Method", "Task 1 (SSP)", "Task 2 (CHA)", "Task 3 (Infilling)", "Avg.", "Delta Avg."]
    keys = ["model", "method", "task1_ssp", "task2_cha", "task3_infill", "avg", "delta_avg"]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(key, "")) for key in keys) + " |")
    return "\n".join(lines) + "\n"


def latex_table(rows: list[dict[str, Any]], include_qa_variants: bool = False) -> str:
    caption = (
        r"    \caption{Base vs. fine-tuned models across three NEST tasks. "
        if not include_qa_variants
        else r"    \caption{Base vs. standard and QA fine-tuned models across three NEST tasks. "
    )
    lines = [
        r"\begin{table*}[t]",
        r"    \centering",
        caption,
        r"    Models are fine-tuned only on Task~3 using the NEST training split of 662 templates (80\%, balanced Chinese/English) and evaluated on a 20\% test split. ",
        (
            r"    $\Delta$ reports the FT--Base difference in average score.}"
            if not include_qa_variants
            else r"    $\Delta$ reports the tuned--Base difference in average score.}"
        ),
        r"    \label{tab:base_vs_finetune_qa}" if include_qa_variants else r"    \label{tab:base_vs_finetune}",
        r"    \small",
        r"    \setlength{\tabcolsep}{5pt}",
        r"    \renewcommand{\arraystretch}{0.95}",
        r"    \begin{tabular*}{\linewidth}{@{}l l @{\extracolsep{\fill}} ccc c c@{}}",
        r"      \toprule",
        r"      \textbf{Model} & \textbf{Method} ",
    ]
    lines.extend([
        r"      & \textbf{Task 1 (SSP)} ",
        r"      & \textbf{Task 2 (CHA)} ",
        r"      & \textbf{Task 3 (Infilling)} ",
        r"      & \textbf{Avg.} ",
        r"      & \textbf{$\Delta$ Avg.} \\",
        r"      \midrule",
    ])

    if include_qa_variants:
        for row_group in grouped_summary_rows(rows):
            if row_group and row_group[0].get("model") == "Average":
                lines.append(r"      \midrule")
            for row in row_group:
                lines.append(latex_summary_row(row, row_group))
    else:
        row_pairs = list(zip(rows[0::2], rows[1::2]))
        for base_row, ft_row in row_pairs:
            if base_row.get("model") == "Average":
                lines.append(r"      \midrule")
            lines.append(latex_row(base_row, ft_row, is_ft=False))
            lines.append(latex_row(ft_row, base_row, is_ft=True))

    lines.extend([
        r"      \bottomrule",
        r"    \end{tabular*}",
        r"\end{table*}",
        "",
    ])
    return "\n".join(lines)


def latex_row(row: dict[str, Any], other_row: dict[str, Any], is_ft: bool) -> str:
    is_average = row.get("model") == "Average"
    model = ""
    if not is_ft:
        model = str(row.get("model", ""))
        if is_average:
            model = latex_bold(model)
    method = str(row.get("method", ""))
    if is_average and is_ft:
        method = latex_bold(method)

    cells = []
    for key in ("task1_ssp", "task2_cha", "task3_infill", "avg"):
        cell = latex_pct(str(row.get(key, "")))
        current_value = row.get(f"{key}_value")
        other_value = other_row.get(f"{key}_value")
        if current_value is not None and other_value is not None and float(current_value) > float(other_value):
            cell = latex_bold(cell)
        cells.append(cell)

    delta = str(row.get("delta_avg", ""))
    delta_cell = "--" if not is_ft or delta == "-" else latex_pct(delta)
    if is_ft and delta.startswith("+"):
        delta_cell = latex_bold(delta_cell)

    return (
        f"      {model:<28} & {method:<4} & {cells[0]} & {cells[1]} & "
        f"{cells[2]} & {cells[3]} & {delta_cell} \\\\"
    )


def grouped_summary_rows(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current_model: str | None = None
    for row in rows:
        model = str(row.get("model", ""))
        if model != current_model:
            groups.append([])
            current_model = model
        groups[-1].append(row)
    return groups


def latex_summary_row(row: dict[str, Any], group_rows: list[dict[str, Any]]) -> str:
    is_average = row.get("model") == "Average"
    is_base = row.get("method") == "Base"
    model = str(row.get("model", "")) if is_base else ""
    if is_average and is_base:
        model = latex_bold(model)
    method = str(row.get("method", ""))
    if is_average and not is_base:
        method = latex_bold(method)

    cells = []
    for key in ("task1_ssp", "task2_cha", "task3_infill", "avg"):
        cell = latex_pct(str(row.get(key, "")))
        current_value = row.get(f"{key}_value")
        values = [
            other_row.get(f"{key}_value")
            for other_row in group_rows
            if other_row.get(f"{key}_value") is not None
        ]
        if current_value is not None and values and float(current_value) == max(float(value) for value in values):
            cell = latex_bold(cell)
        cells.append(cell)

    delta = str(row.get("delta_avg", ""))
    delta_cell = "--" if is_base or delta == "-" else latex_pct(delta)
    if not is_base and delta.startswith("+"):
        delta_cell = latex_bold(delta_cell)

    return (
        f"      {model:<28} & {method:<9} & {cells[0]} & {cells[1]} & "
        f"{cells[2]} & {cells[3]} & {delta_cell} \\\\"
    )


def latex_pct(value: str) -> str:
    return value.replace("%", r"\%")


def latex_bold(value: str) -> str:
    return rf"\textbf{{{value}}}"


def unique_models(models: list[str]) -> list[str]:
    seen = set()
    out = []
    for model in models:
        if model in seen:
            continue
        seen.add(model)
        out.append(model)
    return out


def select_fields(rows: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    return [{field: row.get(field, "") for field in fields} for row in rows]


if __name__ == "__main__":
    main()
