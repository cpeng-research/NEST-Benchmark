from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TABLE3_ROOT = ROOT / "comparative_eval"

CLOSED_SOURCE_MODELS = ("gpt-5", "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo")
OPEN_SOURCE_MODEL_PATHS = {
    "Llama-3.1-8B-Instruct": "meta-llama/Llama-3.1-8B-Instruct",
    "Qwen2.5-7B-Instruct": "Qwen/Qwen2.5-7B-Instruct",
    "Gemma-2-9B-it": "google/gemma-2-9b-it",
    "Mistral-7B-Instruct-v0.3": "mistralai/Mistral-7B-Instruct-v0.3",
}
OPEN_SOURCE_MODELS = tuple(OPEN_SOURCE_MODEL_PATHS)
SUPPORTED_MODELS = CLOSED_SOURCE_MODELS + OPEN_SOURCE_MODELS
SUPPORTED_TASKS = ("schema", "alignment", "infill")
SUPPORTED_CONDITIONS = ("empty", "filled")


@dataclass(frozen=True)
class WorkflowPaths:
    html_empty: Path
    json_empty: Path
    json_filled: Path
    html_filled: Path
    context: Path
    placeholder_html: Path
    meta: Path


def workflow_paths(lang: str) -> WorkflowPaths:
    return WorkflowPaths(
        html_empty=ROOT / f"workflow/0-html_template/data_{lang}",
        json_empty=ROOT / f"workflow/1-annotated_json/data_{lang}",
        json_filled=ROOT / f"workflow/2-filled_json-a/data_{lang}",
        html_filled=ROOT / f"workflow/3-filled_html-a/data_{lang}",
        context=ROOT / f"workflow/4-context-a/data_{lang}",
        placeholder_html=ROOT / f"workflow/5-ph_html-a/data_{lang}",
        meta=ROOT / f"workflow/6-meta-a/data_{lang}",
    )


def prediction_dir(task: str, condition: str, lang: str, model: str) -> Path:
    model_dir = model.replace("/", "_").replace("-", "_")
    return TABLE3_ROOT / "predictions" / f"{task}_{condition}" / lang / model_dir


def rendered_image_dir(condition: str, lang: str) -> Path:
    if condition not in SUPPORTED_CONDITIONS:
        raise ValueError(f"Unsupported condition: {condition}")
    if lang not in {"en", "zh"}:
        raise ValueError(f"Unsupported language: {lang}")
    return ROOT / "workflow" / "9-png-a" / f"data_{lang}" / condition


def is_open_source_model(model: str) -> bool:
    return model in OPEN_SOURCE_MODEL_PATHS


def resolve_open_source_model(model: str, override_path: str | None = None) -> str:
    if override_path:
        return override_path
    try:
        return OPEN_SOURCE_MODEL_PATHS[model]
    except KeyError as exc:
        raise ValueError(f"Unsupported open-source model: {model}") from exc


def details_dir() -> Path:
    return TABLE3_ROOT / "results" / "details"


def summaries_dir() -> Path:
    return TABLE3_ROOT / "results" / "summaries"


def old_jedi_root() -> Path:
    return ROOT / "json_algorithm"
