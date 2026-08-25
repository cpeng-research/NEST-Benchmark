from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from comparative_eval.utils.html_utils import (
    ALL_LOGICAL_REGIONS_LAYOUT,
    FIRST_TABLE_LAYOUT,
    cell_nodes,
    cell_texts,
    normalize_text,
    placeholders_by_cell,
)


LEGACY_MATCHER = "legacy_v1"
SOURCE_FAITHFUL_V2_MATCHER = "source_faithful_v2"
SOURCE_FAITHFUL_MATCHER = "source_faithful_v3"
SUPPORTED_INFILL_MATCHERS = (
    LEGACY_MATCHER,
    SOURCE_FAITHFUL_V2_MATCHER,
    SOURCE_FAITHFUL_MATCHER,
)

PLACEHOLDER_RE = re.compile(r"\[([^\[\]]+)\]")
REMOVED_PUNCTUATION_RE = re.compile(r"[\[\]{}()<>:：,，.;；。!?！？'\"`_\-/\\|~]")


@dataclass(frozen=True)
class LegacyTarget:
    row: int
    col: int
    name: str
    index: int
    gold: str


@dataclass(frozen=True)
class LegacyTargetResult:
    row: int
    col: int
    name: str
    index: int
    gold: str
    prediction: str
    correct: bool
    match_kind: str


@dataclass(frozen=True)
class ControlValue:
    index: int
    kind: str
    value: str


@dataclass(frozen=True)
class InfillCellTarget:
    row: int
    col: int
    marker_count: int
    gold_raw_text: str
    gold_text: str
    placeholder_static_text: str
    text_required: bool
    control_targets: tuple[ControlValue, ...]


@dataclass(frozen=True)
class InfillCellResult:
    row: int
    col: int
    marker_count: int
    gold_raw_text: str
    prediction_raw_text: str
    gold_text: str
    prediction_text: str
    text_required: bool
    control_target_count: int
    correct: bool
    text_correct: bool
    controls_correct: bool
    match_kind: str


def normalize_infill_text(text: str | None) -> str:
    """Normalize harmless presentation variation while retaining value symbols."""
    if text is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text)).casefold()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = REMOVED_PUNCTUATION_RE.sub("", normalized)
    return normalized.strip()


def compare_infill(
    pred_html: str,
    gold_html: str,
    placeholder_html: str,
    matcher: str = SOURCE_FAITHFUL_MATCHER,
) -> tuple[int, int]:
    if matcher == LEGACY_MATCHER:
        results = evaluate_legacy_targets(pred_html, gold_html, placeholder_html)
    elif matcher in {SOURCE_FAITHFUL_V2_MATCHER, SOURCE_FAITHFUL_MATCHER}:
        results = evaluate_source_faithful_cells(
            pred_html,
            gold_html,
            placeholder_html,
            matcher=matcher,
        )
    else:
        raise ValueError(f"Unsupported infill matcher: {matcher}")
    return sum(int(result.correct) for result in results), len(results)


def evaluate_legacy_targets(
    pred_html: str,
    gold_html: str,
    placeholder_html: str,
) -> list[LegacyTargetResult]:
    """Reproduce the submitted bidirectional whole-cell substring matcher."""
    return evaluate_legacy_targets_from_targets(
        pred_html,
        build_legacy_targets(gold_html, placeholder_html),
    )


def build_legacy_targets(gold_html: str, placeholder_html: str) -> list[LegacyTarget]:
    gold_cells = cell_texts(gold_html, layout=FIRST_TABLE_LAYOUT)
    placeholders = placeholders_by_cell(placeholder_html, layout=FIRST_TABLE_LAYOUT)
    targets: list[LegacyTarget] = []
    seen_slots: set[tuple[int, int, int]] = set()
    for placeholder in placeholders:
        slot = (placeholder.row, placeholder.col, placeholder.index)
        if slot in seen_slots:
            continue
        seen_slots.add(slot)
        gold = normalize_text(gold_cells.get((placeholder.row, placeholder.col), ""))
        if not gold:
            continue
        targets.append(
            LegacyTarget(
                row=placeholder.row,
                col=placeholder.col,
                name=placeholder.name,
                index=placeholder.index,
                gold=gold,
            )
        )
    return targets


def evaluate_legacy_targets_from_targets(
    pred_html: str,
    targets: list[LegacyTarget],
) -> list[LegacyTargetResult]:
    pred_cells = cell_texts(pred_html, layout=FIRST_TABLE_LAYOUT)
    results: list[LegacyTargetResult] = []
    for target in targets:
        prediction = normalize_text(pred_cells.get((target.row, target.col), ""))
        match_kind = "none"
        if prediction:
            if prediction == target.gold:
                match_kind = "exact"
            elif target.gold in prediction:
                match_kind = "gold_in_prediction"
            elif prediction in target.gold:
                match_kind = "prediction_in_gold"
        results.append(
            LegacyTargetResult(
                row=target.row,
                col=target.col,
                name=target.name,
                index=target.index,
                gold=target.gold,
                prediction=prediction,
                correct=match_kind != "none",
                match_kind=match_kind,
            )
        )
    return results


def build_source_faithful_targets(
    gold_html: str,
    placeholder_html: str,
    *,
    matcher: str = SOURCE_FAITHFUL_MATCHER,
) -> list[InfillCellTarget]:
    layout = _layout_for_matcher(matcher)
    gold_cells = cell_nodes(gold_html, layout=layout)
    placeholder_cells = cell_nodes(placeholder_html, layout=layout)
    targets: list[InfillCellTarget] = []

    for position, placeholder_cell in placeholder_cells.items():
        marker_count = len(PLACEHOLDER_RE.findall(str(placeholder_cell)))
        if marker_count == 0:
            continue
        gold_cell = gold_cells.get(position)
        if gold_cell is None:
            continue

        gold_raw_text = gold_cell.get_text(" ", strip=True)
        gold_text = normalize_infill_text(gold_raw_text)
        static_text = normalize_infill_text(
            PLACEHOLDER_RE.sub("", placeholder_cell.get_text(" ", strip=True))
        )
        text_required = bool(gold_text) and gold_text != static_text
        controls = _target_control_values(placeholder_cell, gold_cell)

        # A marker without an observable text/control value cannot support a
        # source-faithful correctness decision and is excluded from v2.
        if not text_required and not controls:
            continue
        targets.append(
            InfillCellTarget(
                row=position[0],
                col=position[1],
                marker_count=marker_count,
                gold_raw_text=gold_raw_text,
                gold_text=gold_text,
                placeholder_static_text=static_text,
                text_required=text_required,
                control_targets=controls,
            )
        )
    return targets


def evaluate_source_faithful_cells(
    pred_html: str,
    gold_html: str,
    placeholder_html: str,
    *,
    matcher: str = SOURCE_FAITHFUL_MATCHER,
) -> list[InfillCellResult]:
    return evaluate_source_faithful_targets(
        pred_html,
        build_source_faithful_targets(gold_html, placeholder_html, matcher=matcher),
        matcher=matcher,
    )


def evaluate_source_faithful_targets(
    pred_html: str,
    targets: list[InfillCellTarget],
    *,
    matcher: str = SOURCE_FAITHFUL_MATCHER,
) -> list[InfillCellResult]:
    pred_cells = cell_nodes(pred_html, layout=_layout_for_matcher(matcher))
    results: list[InfillCellResult] = []

    for target in targets:
        pred_cell = pred_cells.get((target.row, target.col))
        prediction_raw_text = pred_cell.get_text(" ", strip=True) if pred_cell is not None else ""
        prediction_text = (
            normalize_infill_text(prediction_raw_text)
            if pred_cell is not None
            else ""
        )
        text_correct, match_kind = _source_faithful_text_match(
            target.gold_text,
            prediction_text,
            required=target.text_required,
        )
        controls_correct = _controls_match(target.control_targets, pred_cell)
        results.append(
            InfillCellResult(
                row=target.row,
                col=target.col,
                marker_count=target.marker_count,
                gold_raw_text=target.gold_raw_text,
                prediction_raw_text=prediction_raw_text,
                gold_text=target.gold_text,
                prediction_text=prediction_text,
                text_required=target.text_required,
                control_target_count=len(target.control_targets),
                correct=text_correct and controls_correct,
                text_correct=text_correct,
                controls_correct=controls_correct,
                match_kind=match_kind if controls_correct else "control_mismatch",
            )
        )
    return results


def _layout_for_matcher(matcher: str) -> str:
    if matcher == SOURCE_FAITHFUL_V2_MATCHER:
        return FIRST_TABLE_LAYOUT
    if matcher == SOURCE_FAITHFUL_MATCHER:
        return ALL_LOGICAL_REGIONS_LAYOUT
    raise ValueError(f"Unsupported source-faithful matcher: {matcher}")


def _source_faithful_text_match(
    gold: str,
    prediction: str,
    *,
    required: bool,
) -> tuple[bool, str]:
    if not required:
        return True, "not_required"
    if not prediction:
        return False, "empty_prediction"
    if prediction == gold:
        return True, "exact"
    return False, "mismatch"


def _target_control_values(placeholder_cell: Any, gold_cell: Any) -> tuple[ControlValue, ...]:
    placeholder_controls = _controls(placeholder_cell)
    gold_controls = _controls(gold_cell)
    text_has_markers = bool(PLACEHOLDER_RE.search(placeholder_cell.get_text(" ", strip=True)))
    target_indices: set[int] = set()

    for index, control in enumerate(placeholder_controls):
        if _element_has_placeholder(control):
            target_indices.add(index)
        kind = _control_kind(control)
        if text_has_markers and kind in {"checkbox", "radio", "select"}:
            target_indices.add(index)

    targets: list[ControlValue] = []
    for index in sorted(target_indices):
        if index >= len(gold_controls):
            continue
        control = gold_controls[index]
        targets.append(
            ControlValue(index=index, kind=_control_kind(control), value=_control_value(control))
        )
    return tuple(targets)


def _controls_match(targets: tuple[ControlValue, ...], pred_cell: Any | None) -> bool:
    if not targets:
        return True
    if pred_cell is None:
        return False
    pred_controls = _controls(pred_cell)
    for target in targets:
        if target.index >= len(pred_controls):
            return False
        pred_control = pred_controls[target.index]
        if _control_kind(pred_control) != target.kind:
            return False
        if _control_value(pred_control) != target.value:
            return False
    return True


def _controls(cell: Any) -> list[Any]:
    return list(cell.find_all(["input", "select", "textarea"]))


def _element_has_placeholder(element: Any) -> bool:
    if PLACEHOLDER_RE.search(element.get_text(" ", strip=True)):
        return True
    return any(PLACEHOLDER_RE.search(str(value)) for value in element.attrs.values())


def _control_kind(control: Any) -> str:
    if control.name == "input":
        return str(control.get("type") or "text").casefold()
    return str(control.name).casefold()


def _control_value(control: Any) -> str:
    kind = _control_kind(control)
    if kind in {"checkbox", "radio"}:
        return "checked" if control.has_attr("checked") else "unchecked"
    if kind == "select":
        options = list(control.find_all("option"))
        selected = [option for option in options if option.has_attr("selected")]
        if not selected and options:
            selected = [options[0]]
        values = [option.get("value", option.get_text(" ", strip=True)) for option in selected]
        return "|".join(normalize_infill_text(value) for value in values)
    if kind == "textarea":
        return normalize_infill_text(control.get_text(" ", strip=True))
    return normalize_infill_text(control.get("value", ""))
