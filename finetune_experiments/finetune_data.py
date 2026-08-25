from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from comparative_eval.config import ROOT, workflow_paths
from comparative_eval.prompts import (
    TABLE3_SYSTEM_PROMPT,
    alignment_prompt,
    infill_prompt,
    schema_prompt,
)
from comparative_eval.utils.io_utils import id_in_range, iter_numeric_files, read_json, read_text


FINETUNE_ROOT = ROOT / "finetune_experiments"
DATASET_DIR = FINETUNE_ROOT / "datasets"
OUTPUT_DIR = FINETUNE_ROOT / "outputs"
PREDICTIONS_DIR = FINETUNE_ROOT / "predictions"
SUPPORTED_FINETUNE_TASKS = ("schema", "alignment", "infill")
SUPPORTED_FINETUNE_LANGS = ("en", "zh")
COMBINED_LANG = "both"
TEMPLATE_CONDITION = "empty"

_BRACKET_PLACEHOLDER_RE = re.compile(r"\[([^\[\]]+)\]")


@dataclass(frozen=True)
class FinetuneSample:
    sample_id: int
    task: str
    lang: str
    condition: str
    split: str
    prompt: str
    completion: str
    messages: list[dict[str, str]]
    source_files: dict[str, str]

    def to_json_record(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "task": self.task,
            "lang": self.lang,
            "condition": self.condition,
            "split": self.split,
            "prompt": self.prompt,
            "completion": self.completion,
            "messages": self.messages,
            "source_files": self.source_files,
        }


@dataclass(frozen=True)
class BuildStats:
    requested_task: str
    lang: str
    sample_count: int
    by_task: dict[str, int]
    by_lang: dict[str, int]
    skipped: list[str]
    warnings: list[str]
    alignment_checks: dict[str, int]
    output_path: Path | None = None

    def to_json_record(self) -> dict[str, Any]:
        return {
            "requested_task": self.requested_task,
            "lang": self.lang,
            "sample_count": self.sample_count,
            "by_task": self.by_task,
            "by_lang": self.by_lang,
            "skipped": self.skipped,
            "warnings": self.warnings,
            "alignment_checks": self.alignment_checks,
            "output_path": str(self.output_path) if self.output_path else None,
        }


def expand_tasks(task: str) -> tuple[str, ...]:
    if task == "all":
        return SUPPORTED_FINETUNE_TASKS
    if task not in SUPPORTED_FINETUNE_TASKS:
        raise ValueError(f"Unsupported fine-tuning task: {task}")
    return (task,)


def expand_langs(lang: str) -> tuple[str, ...]:
    if lang in {COMBINED_LANG, "all"}:
        return SUPPORTED_FINETUNE_LANGS
    if lang not in SUPPORTED_FINETUNE_LANGS:
        raise ValueError(f"Unsupported fine-tuning language: {lang}")
    return (lang,)


def default_dataset_path(task: str, lang: str) -> Path:
    return DATASET_DIR / f"{task}_{lang}_template.jsonl"


def split_dataset_path(task: str, lang: str, split: str) -> Path:
    return DATASET_DIR / f"{task}_{lang}_template_{split}.jsonl"


def default_output_dir(model: str, task: str, lang: str) -> Path:
    return OUTPUT_DIR / clean_model_name(model) / f"{task}_{lang}_template"


def clean_model_name(model: str) -> str:
    return model.replace("/", "_").replace("-", "_")


def build_samples(
    task: str,
    lang: str = COMBINED_LANG,
    start_id: int | None = None,
    end_id: int | None = None,
    limit: int = 0,
    validate_alignment: bool = True,
    split: str = "all",
    test_ratio: float = 0.2,
    split_seed: int = 3407,
) -> tuple[list[FinetuneSample], BuildStats]:
    tasks = expand_tasks(task)
    langs = expand_langs(lang)
    split_ids = compute_split_ids(langs, start_id, end_id, test_ratio, split_seed)
    samples: list[FinetuneSample] = []
    skipped: list[str] = []
    warnings: list[str] = []
    by_task = {item: 0 for item in tasks}
    by_lang = {item: 0 for item in langs}
    alignment_checks = {"checked": 0, "passed": 0, "failed": 0}

    for current_lang in langs:
        paths = workflow_paths(current_lang)
        for html_file in iter_numeric_files(paths.html_empty, ".html"):
            sample_id = int(html_file.stem)
            if not id_in_range(sample_id, start_id, end_id):
                continue
            sample_split = split_ids.get(sample_id, "train")
            if split != "all" and sample_split != split:
                continue

            for current_task in tasks:
                if limit and by_task[current_task] >= limit:
                    continue
                try:
                    sample = build_one_sample(
                        current_task,
                        current_lang,
                        sample_id,
                        split=sample_split,
                        validate_alignment=validate_alignment,
                    )
                except FileNotFoundError as exc:
                    skipped.append(f"{current_task}:{current_lang}:{sample_id}: missing {exc.filename}")
                    continue
                except Exception as exc:
                    skipped.append(f"{current_task}:{current_lang}:{sample_id}: {exc.__class__.__name__}: {exc}")
                    continue
                samples.append(sample)
                by_task[current_task] += 1
                by_lang[current_lang] += 1

                if current_task == "alignment" and validate_alignment:
                    alignment_checks["checked"] += 1
                    ok = alignment_gold_self_check(sample.completion, current_lang, sample_id)
                    if ok:
                        alignment_checks["passed"] += 1
                    else:
                        alignment_checks["failed"] += 1
                        warnings.append(f"alignment:{current_lang}:{sample_id}: converted gold failed evaluator self-check")

            if limit and all(by_task[item] >= limit for item in tasks):
                break
        if limit and all(by_task[item] >= limit for item in tasks):
            break

    stats = BuildStats(
        requested_task=task,
        lang=lang,
        sample_count=len(samples),
        by_task=by_task,
        by_lang=by_lang,
        skipped=skipped,
        warnings=warnings,
        alignment_checks=alignment_checks,
    )
    return samples, stats


def build_one_sample(
    task: str,
    lang: str,
    sample_id: int,
    split: str = "all",
    validate_alignment: bool = True,
) -> FinetuneSample:
    paths = workflow_paths(lang)
    html_file = paths.html_empty / f"{sample_id}.html"
    html = require_text(html_file)

    source_files = {"html": str(html_file)}
    if task == "schema":
        gold_file = paths.json_empty / f"{sample_id}.json"
        prompt = schema_prompt(html, TEMPLATE_CONDITION)
        completion = require_text(gold_file).strip()
        # Fail early on invalid gold JSON.
        json.loads(completion)
        source_files["gold"] = str(gold_file)
    elif task == "alignment":
        gold_file = paths.placeholder_html / f"{sample_id}.html"
        reference_html = require_text(gold_file)
        prompt = alignment_prompt(html, TEMPLATE_CONDITION)
        completion = convert_reference_alignment_html(reference_html)
        completion = repair_alignment_html_for_evaluator(completion, reference_html, lang, sample_id)
        source_files["gold"] = str(gold_file)
    elif task == "infill":
        context_file = paths.context / f"{sample_id}.txt"
        gold_file = paths.html_filled / f"{sample_id}.html"
        context = require_text(context_file)
        prompt = infill_prompt(html, context, TEMPLATE_CONDITION)
        completion = require_text(gold_file).strip()
        source_files["context"] = str(context_file)
        source_files["gold"] = str(gold_file)
    else:
        raise ValueError(f"Unsupported fine-tuning task: {task}")

    messages = [
        {"role": "system", "content": TABLE3_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": completion},
    ]
    return FinetuneSample(
        sample_id=sample_id,
        task=task,
        lang=lang,
        condition=TEMPLATE_CONDITION,
        split=split,
        prompt=prompt,
        completion=completion,
        messages=messages,
        source_files=source_files,
    )


def compute_split_ids(
    langs: tuple[str, ...] | list[str] | str,
    start_id: int | None = None,
    end_id: int | None = None,
    test_ratio: float = 0.2,
    split_seed: int = 3407,
) -> dict[int, str]:
    if not 0 < test_ratio < 1:
        raise ValueError("--test_ratio must be between 0 and 1")
    if isinstance(langs, str):
        langs = expand_langs(langs)
    sample_ids = sorted({
        int(html_file.stem)
        for lang in langs
        for html_file in iter_numeric_files(workflow_paths(lang).html_empty, ".html")
        if id_in_range(int(html_file.stem), start_id, end_id)
    })
    shuffled = list(sample_ids)
    random.Random(split_seed).shuffle(shuffled)
    test_count = max(1, int(round(len(shuffled) * test_ratio))) if len(shuffled) > 1 else len(shuffled)
    test_ids = set(shuffled[:test_count])
    return {sample_id: ("test" if sample_id in test_ids else "train") for sample_id in sample_ids}


def require_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return read_text(path)


def convert_reference_alignment_html(html: str, remove_checked: bool = True) -> str:
    """Convert [Field] placeholder HTML to the input-placeholder target.

    The reference alignment gold stores text markers like ``[Name]``. The
    Table 3 prompt asks for HTML inputs with ``name=...`` and
    ``value="placeholder"``. Markers immediately preceding checkbox or radio
    inputs are removed and the existing input receives the placeholder
    attributes. Other markers become text inputs.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    if remove_checked:
        for input_tag in soup.find_all("input"):
            input_tag.attrs.pop("checked", None)

    for text_node in list(soup.find_all(string=_BRACKET_PLACEHOLDER_RE)):
        if text_node.parent is None:
            continue
        replacement_nodes = nodes_for_placeholder_text(soup, text_node)
        text_node.replace_with(*replacement_nodes)

    return str(soup).strip()


def nodes_for_placeholder_text(soup: BeautifulSoup, text_node: NavigableString) -> list[Any]:
    text = str(text_node)
    nodes: list[Any] = []
    pos = 0
    for match in _BRACKET_PLACEHOLDER_RE.finditer(text):
        before = text[pos:match.start()]
        if before:
            nodes.append(NavigableString(before))

        name = match.group(1).strip()
        if placeholder_belongs_to_following_selectable(text, match, text_node):
            selectable = next_selectable_input(text_node)
            if selectable is not None:
                selectable["name"] = name
                selectable["value"] = "placeholder"
        else:
            nodes.append(new_text_input(soup, name))
        pos = match.end()

    tail = text[pos:]
    if tail:
        nodes.append(NavigableString(tail))
    return nodes


def placeholder_belongs_to_following_selectable(
    text: str,
    match: re.Match[str],
    text_node: NavigableString,
) -> bool:
    if text[match.end():].strip():
        return False
    return next_selectable_input(text_node) is not None


def next_selectable_input(node: NavigableString) -> Tag | None:
    sibling = node.next_sibling
    while sibling is not None:
        if isinstance(sibling, NavigableString):
            if str(sibling).strip():
                return None
            sibling = sibling.next_sibling
            continue
        if isinstance(sibling, Tag):
            if sibling.name != "input":
                return None
            input_type = str(sibling.get("type") or "text").lower()
            if input_type in {"checkbox", "radio"}:
                return sibling
            return None
        return None
    return None


def new_text_input(soup: BeautifulSoup, name: str) -> Tag:
    return soup.new_tag(
        "input",
        attrs={"type": "text", "name": name, "value": "placeholder"},
    )


def alignment_gold_self_check(converted_html: str, lang: str, sample_id: int) -> bool:
    from comparative_eval.eval_alignment import (
        FIELD_TYPES,
        choose_coordinate_strategy,
        compare_alignment,
        expand_meta,
        resolve_expected_names_from_gold,
    )

    paths = workflow_paths(lang)
    meta_file = paths.meta / f"{sample_id}.json"
    reference_gold_file = paths.placeholder_html / f"{sample_id}.html"
    if not meta_file.exists() or not reference_gold_file.exists():
        return False

    expected = expand_meta(read_json(meta_file))
    if not expected:
        return False
    reference_gold = read_text(reference_gold_file)
    strategy = choose_coordinate_strategy(reference_gold, expected)
    expected = resolve_expected_names_from_gold(reference_gold, expected, strategy)
    results, _records = compare_alignment(converted_html, expected, strategy)
    correct = sum(results[field_type]["correct"] for field_type in FIELD_TYPES)
    total = sum(results[field_type]["total"] for field_type in FIELD_TYPES)
    return total > 0 and correct == total


def repair_alignment_html_for_evaluator(
    converted_html: str,
    reference_html: str,
    lang: str,
    sample_id: int,
) -> str:
    """Add missing input placeholders at evaluator target cells.

    Most placeholder files can be converted by replacing ``[Field]`` in place.
    A few contain malformed attributes such as ``colspan="6>[Field]``;
    BeautifulSoup and the evaluator then disagree about the bracket's physical
    cell. The alignment metric uses Step 6 metadata target cells, so this
    repair pass appends an extra named input to any target cell still unmatched
    after the direct conversion.
    """
    from comparative_eval.eval_alignment import (
        FIELD_TYPES,
        choose_coordinate_strategy,
        compare_alignment,
        direct_cells_for_tables,
        expand_meta,
        input_table_marker,
        recursive_cells_for_table,
        resolve_expected_names_from_gold,
        select_analysis_tables,
        select_leaf_tables,
    )

    paths = workflow_paths(lang)
    meta_file = paths.meta / f"{sample_id}.json"
    if not meta_file.exists():
        return converted_html

    expected = expand_meta(read_json(meta_file))
    if not expected:
        return converted_html
    strategy = choose_coordinate_strategy(reference_html, expected)
    expected = resolve_expected_names_from_gold(reference_html, expected, strategy)
    results, records = compare_alignment(converted_html, expected, strategy)
    correct = sum(results[field_type]["correct"] for field_type in FIELD_TYPES)
    total = sum(results[field_type]["total"] for field_type in FIELD_TYPES)
    if total > 0 and correct == total:
        return converted_html

    soup = BeautifulSoup(converted_html or "", "html.parser")
    cells = cells_by_position_for_strategy(
        soup,
        strategy,
        input_table_marker,
        select_analysis_tables,
        select_leaf_tables,
        direct_cells_for_tables,
        recursive_cells_for_table,
    )
    changed = False
    for record in records:
        if record.get("matched"):
            continue
        cell = cells.get((int(record["target_row"]), int(record["target_col"])))
        if cell is None:
            continue
        cell.append(new_text_input(soup, str(record["key"])))
        changed = True

    return str(soup).strip() if changed else converted_html


def cells_by_position_for_strategy(
    soup: BeautifulSoup,
    strategy: str,
    marker: Any,
    select_analysis_tables: Any,
    select_leaf_tables: Any,
    direct_cells_for_tables: Any,
    recursive_cells_for_table: Any,
) -> dict[tuple[int, int], Tag]:
    if strategy == "leaf":
        tables = select_leaf_tables(soup, marker)
        cells = direct_cells_for_tables(tables, source_prefix="leaf")
    elif strategy == "recursive":
        table = soup.find("table")
        cells = recursive_cells_for_table(table, source="recursive") if table else []
    else:
        tables = select_analysis_tables(soup, marker)
        cells = direct_cells_for_tables(tables, source_prefix="analysis")
    return {(row, col): cell for _source, row, col, cell in cells}


def write_jsonl(samples: Iterable[FinetuneSample], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample.to_json_record(), ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, int] = {}
    char_lengths: list[int] = []
    for record in records:
        task = str(record.get("task", "unknown"))
        by_task[task] = by_task.get(task, 0) + 1
        char_lengths.append(len(str(record.get("prompt", ""))) + len(str(record.get("completion", ""))))

    return {
        "sample_count": len(records),
        "by_task": by_task,
        "max_chars": max(char_lengths) if char_lengths else 0,
        "avg_chars": int(sum(char_lengths) / len(char_lengths)) if char_lengths else 0,
    }
