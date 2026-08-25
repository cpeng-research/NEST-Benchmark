from __future__ import annotations

import argparse
import base64
import mimetypes
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comparative_eval.config import (
    SUPPORTED_CONDITIONS,
    SUPPORTED_TASKS,
    prediction_dir,
    rendered_image_dir,
    workflow_paths,
)
from comparative_eval.prompts import TABLE3_SYSTEM_PROMPT
from comparative_eval.run_inference import optional_int, should_skip_prediction, write_prediction
from comparative_eval.utils.io_utils import ensure_dir, id_in_range, iter_numeric_files, read_text
from comparative_eval.utils.openai_utils import create_client, extract_text


LANGS = ("en", "zh")
ALL_TASKS = (*SUPPORTED_TASKS, "all")
ALL_CONDITIONS = (*SUPPORTED_CONDITIONS, "both")
ALL_LANGS = (*LANGS, "both")


@dataclass(frozen=True)
class ImageJob:
    task: str
    condition: str
    lang: str
    sample_id: int
    prompt: str
    image_path: Path
    out_file: Path


@dataclass(frozen=True)
class PredictionResult:
    job: ImageJob
    success: bool
    attempts: int
    error: str | None = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run Table 3 image-based multimodal inference. Results are stored under "
            "comparative_eval/predictions using a separate prediction model label."
        )
    )
    parser.add_argument("--task", required=True, choices=ALL_TASKS)
    parser.add_argument("--condition", default="both", choices=ALL_CONDITIONS)
    parser.add_argument("--lang", default="both", choices=ALL_LANGS)
    parser.add_argument("--api_model", "--api-model", dest="api_model", default="gpt-5.4-nano")
    parser.add_argument(
        "--prediction_model_name",
        "--prediction-model-name",
        dest="prediction_model_name",
        default=None,
        help="Directory/evaluation label. Defaults to '<api_model>-image'.",
    )
    parser.add_argument("--start_id", type=optional_int, default=None)
    parser.add_argument("--end_id", type=optional_int, default=None)
    parser.add_argument("--limit", type=int, default=0, help="Per task/condition/lang limit.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--request_timeout", "--request-timeout", dest="request_timeout", type=float, default=180.0)
    parser.add_argument("--max_retries", "--max-retries", dest="max_retries", type=int, default=3)
    parser.add_argument("--retry_sleep", "--retry-sleep", dest="retry_sleep", type=float, default=5.0)
    parser.add_argument(
        "--detail",
        choices=["low", "high", "auto", "original"],
        default="high",
        help="OpenAI image detail level. Use high for dense form images; original is only supported by newer models.",
    )
    parser.add_argument(
        "--api_surface",
        "--api-surface",
        dest="api_surface",
        choices=["auto", "responses", "chat_completions"],
        default="auto",
        help="Use Responses API, Chat Completions, or try Responses then Chat Completions on endpoint/schema failures.",
    )
    parser.add_argument(
        "--max_output_tokens",
        "--max-output-tokens",
        dest="max_output_tokens",
        type=int,
        default=0,
        help="Optional output cap. 0 omits the parameter for compatibility with OpenAI-compatible proxies.",
    )
    parser.add_argument("--dry_run", "--dry-run", dest="dry_run", action="store_true")
    parser.add_argument("--evaluate", action="store_true", help="Run the existing Table 3 evaluator after inference.")
    parser.add_argument("--schema_metric", "--schema-metric", dest="schema_metric", choices=["py_tree", "py_fast", "cpp"], default="py_tree")
    parser.add_argument("--cpp_timeout", "--cpp-timeout", dest="cpp_timeout", type=float, default=10.0)
    parser.add_argument("--resume_from_details", "--resume-from-details", dest="resume_from_details", action="store_true")
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1.")
    if args.request_timeout <= 0:
        parser.error("--request_timeout must be positive.")
    if args.max_retries < 1:
        parser.error("--max_retries must be at least 1.")
    if args.retry_sleep < 0:
        parser.error("--retry_sleep cannot be negative.")
    if args.max_output_tokens < 0:
        parser.error("--max_output_tokens cannot be negative.")

    prediction_model_name = args.prediction_model_name or f"{args.api_model}-image"
    selected_tasks = SUPPORTED_TASKS if args.task == "all" else (args.task,)
    selected_conditions = SUPPORTED_CONDITIONS if args.condition == "both" else (args.condition,)
    selected_langs = LANGS if args.lang == "both" else (args.lang,)

    jobs = collect_jobs(
        tasks=selected_tasks,
        conditions=selected_conditions,
        langs=selected_langs,
        prediction_model_name=prediction_model_name,
        start_id=args.start_id,
        end_id=args.end_id,
        limit=args.limit,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    print(
        f"api_model={args.api_model} prediction_model_name={prediction_model_name} "
        f"tasks={','.join(selected_tasks)} conditions={','.join(selected_conditions)} "
        f"langs={','.join(selected_langs)} jobs={len(jobs)} pending={len(jobs)}"
    )
    if args.dry_run:
        for job in jobs[:20]:
            print(describe_job(job))
        if len(jobs) > 20:
            print(f"... {len(jobs) - 20} more jobs")
        return

    if jobs:
        run_openai_image_predictions(args, prediction_model_name, jobs)
    if args.evaluate:
        run_evaluators(args, prediction_model_name, selected_tasks, selected_conditions, selected_langs)


def collect_jobs(
    tasks: tuple[str, ...],
    conditions: tuple[str, ...],
    langs: tuple[str, ...],
    prediction_model_name: str,
    start_id: int | None,
    end_id: int | None,
    limit: int,
    overwrite: bool,
    dry_run: bool,
) -> list[ImageJob]:
    jobs: list[ImageJob] = []
    for task in tasks:
        for condition in conditions:
            for lang in langs:
                combo_jobs = build_jobs_for_combo(
                    task=task,
                    condition=condition,
                    lang=lang,
                    prediction_model_name=prediction_model_name,
                    start_id=start_id,
                    end_id=end_id,
                    limit=limit,
                    overwrite=overwrite,
                    dry_run=dry_run,
                )
                print(f"task={task} condition={condition} lang={lang} pending={len(combo_jobs)}")
                jobs.extend(combo_jobs)
    return jobs


def build_jobs_for_combo(
    task: str,
    condition: str,
    lang: str,
    prediction_model_name: str,
    start_id: int | None,
    end_id: int | None,
    limit: int,
    overwrite: bool,
    dry_run: bool,
) -> list[ImageJob]:
    image_dir = rendered_image_dir(condition, lang)
    paths = workflow_paths(lang)
    out_dir = prediction_dir(task, condition, lang, prediction_model_name)
    if not dry_run:
        ensure_dir(out_dir)

    jobs: list[ImageJob] = []
    for image_path in iter_numeric_files(image_dir, ".png"):
        sample_id = int(image_path.stem)
        if not id_in_range(sample_id, start_id, end_id):
            continue
        prompt = build_image_prompt(task, condition, lang, sample_id, paths)
        if prompt is None:
            continue
        out_file = out_dir / f"{sample_id}.json"
        if should_skip_prediction(out_file, overwrite):
            continue
        jobs.append(
            ImageJob(
                task=task,
                condition=condition,
                lang=lang,
                sample_id=sample_id,
                prompt=prompt,
                image_path=image_path,
                out_file=out_file,
            )
        )
        if limit and len(jobs) >= limit:
            break
    return jobs


def build_image_prompt(task: str, condition: str, lang: str, sample_id: int, paths) -> str | None:
    source = "filled form/table image" if condition == "filled" else "empty form/table template image"
    lang_rule = "Keep Chinese labels in Chinese." if lang == "zh" else "Keep English labels in English."

    if task == "schema":
        value_rule = (
            "Preserve visible filled values when they are present."
            if condition == "filled"
            else "Use empty strings for fillable values."
        )
        return f"""Convert the attached {source} into a concise hierarchical JSON object.

Rules:
1. {lang_rule}
2. Preserve the form/table field hierarchy and repeated structures.
3. Convert selectable fields to objects with "select" and "value" when possible.
4. {value_rule}
5. Return only valid JSON, without markdown fences or explanations."""

    if task == "alignment":
        return f"""Identify all fillable positions in the attached {source}.

Return a complete HTML table/form approximation of the image using the legacy placeholder format from the original project. At every position that should contain user-provided data, insert an HTML input placeholder:
<input type="text" name="FieldName" value="placeholder">

Rules:
1. {lang_rule}
2. Preserve the visible table structure, labels, row/column order, and fillable cells as closely as possible.
3. Do not invent field names; use the most local visible label text from the form/table as the input name.
4. For plain text fields, replace the fillable blank/value with <input type="text" name="FieldName" value="placeholder">.
5. For repeated rows, add 1-based indices to the name when needed, for example name="Item1" and name="Item2".
6. For checkbox, radio, or other selectable groups, use the same field name for every option in the group and include an input placeholder near each option.
7. Return only the final HTML, without markdown fences or explanations."""

    if task == "infill":
        context_file = paths.context / f"{sample_id}.txt"
        if not context_file.exists():
            return None
        context = read_text(context_file)
        action = "check, correct, and complete this already filled form/table" if condition == "filled" else "fill this empty form/table template"
        return f"""Use the relevant information to {action} shown in the attached image.

Rules:
1. {lang_rule}
2. Reconstruct the visible table/form structure as HTML as closely as possible.
3. Fill all fields supported by the relevant information.
4. Preserve checkbox/radio/selectable semantics and mark the selected option where appropriate.
5. Return only the final HTML, without markdown fences or explanations.

Relevant information:
{context}"""

    raise ValueError(task)


def run_openai_image_predictions(args: argparse.Namespace, prediction_model_name: str, jobs: list[ImageJob]) -> None:
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [
            pool.submit(run_one_openai_image, args, prediction_model_name, job)
            for job in jobs
        ]
        for fut in as_completed(futures):
            result = fut.result()
            if result.success:
                print(f"completed {describe_job(result.job)} attempts={result.attempts}")
            else:
                print(f"skipped {describe_job(result.job)} attempts={result.attempts} error={result.error}", file=sys.stderr)


def run_one_openai_image(args: argparse.Namespace, prediction_model_name: str, job: ImageJob) -> PredictionResult:
    client = create_client()
    attempts = max(1, args.max_retries)
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            response, api_surface = create_image_response(client, args, job)
            text = extract_text(response).strip()
            if not text:
                raise RuntimeError("empty response")
            write_prediction(
                job.out_file,
                {
                    "sample_id": job.sample_id,
                    "model": prediction_model_name,
                    "api_model": args.api_model,
                    "backend": "openai",
                    "api_surface": api_surface,
                    "input_modality": "image",
                    "task": job.task,
                    "condition": job.condition,
                    "lang": job.lang,
                    "image_path": str(job.image_path),
                    "image_detail": args.detail,
                    "raw_response": text,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "attempts": attempt,
                    "request_timeout": args.request_timeout,
                    "usage": response_usage(response),
                },
            )
            return PredictionResult(job=job, success=True, attempts=attempt)
        except Exception as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            print(f"{describe_job(job)} attempt {attempt}/{attempts} failed: {last_error}", file=sys.stderr)
            if attempt < attempts:
                time.sleep(args.retry_sleep * attempt)
    return PredictionResult(job=job, success=False, attempts=attempts, error=last_error)


def create_image_response(client, args: argparse.Namespace, job: ImageJob) -> tuple[Any, str]:
    if args.api_surface == "responses":
        return create_responses_image_response(client, args, job), "responses"
    if args.api_surface == "chat_completions":
        return create_chat_image_response(client, args, job), "chat_completions"

    try:
        return create_responses_image_response(client, args, job), "responses"
    except Exception as exc:
        if not should_fallback_to_chat(exc):
            raise
        print(f"{describe_job(job)} responses API failed; falling back to chat_completions: {exc}", file=sys.stderr)
        return create_chat_image_response(client, args, job), "chat_completions"


def create_responses_image_response(client, args: argparse.Namespace, job: ImageJob):
    kwargs: dict[str, Any] = {
        "model": args.api_model,
        "instructions": TABLE3_SYSTEM_PROMPT,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": job.prompt},
                    {
                        "type": "input_image",
                        "image_url": image_data_url(job.image_path),
                        "detail": args.detail,
                    },
                ],
            }
        ],
        "timeout": args.request_timeout,
    }
    if args.max_output_tokens:
        kwargs["max_output_tokens"] = args.max_output_tokens
    return client.responses.create(**kwargs)


def create_chat_image_response(client, args: argparse.Namespace, job: ImageJob):
    kwargs: dict[str, Any] = {
        "model": args.api_model,
        "messages": [
            {"role": "system", "content": TABLE3_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": job.prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data_url(job.image_path),
                            "detail": args.detail,
                        },
                    },
                ],
            },
        ],
        "timeout": args.request_timeout,
    }
    if args.max_output_tokens:
        kwargs["max_completion_tokens"] = args.max_output_tokens
    return client.chat.completions.create(**kwargs)


def should_fallback_to_chat(exc: Exception) -> bool:
    message = str(exc).lower()
    names = {exc.__class__.__name__.lower()}
    return (
        "notfound" in names
        or "badrequest" in names
        or "attributeerror" in names
        or "typeerror" in names
        or "404" in message
        or "unknown parameter" in message
        or "unsupported parameter" in message
        or "responses" in message and "not" in message
    )


def image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def response_usage(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if hasattr(usage, "dict"):
        return usage.dict()
    return {key: getattr(usage, key) for key in dir(usage) if key.endswith("tokens") and not key.startswith("_")}


def run_evaluators(
    args: argparse.Namespace,
    prediction_model_name: str,
    tasks: tuple[str, ...],
    conditions: tuple[str, ...],
    langs: tuple[str, ...],
) -> None:
    evaluator_by_task = {
        "schema": "comparative_eval/eval_schema.py",
        "alignment": "comparative_eval/eval_alignment.py",
        "infill": "comparative_eval/eval_infill.py",
    }
    for task in tasks:
        for condition in conditions:
            for lang in langs:
                cmd = [
                    sys.executable,
                    evaluator_by_task[task],
                    "--condition",
                    condition,
                    "--model",
                    prediction_model_name,
                    "--lang",
                    lang,
                ]
                if task == "schema":
                    cmd.extend(["--metric", args.schema_metric])
                    if args.schema_metric == "cpp":
                        cmd.extend(["--cpp_timeout", str(args.cpp_timeout)])
                if args.resume_from_details:
                    cmd.append("--resume_from_details")
                print("Running evaluator:", " ".join(cmd))
                subprocess.run(cmd, check=True)


def describe_job(job: ImageJob) -> str:
    return f"task={job.task} condition={job.condition} lang={job.lang} sample={job.sample_id}"


if __name__ == "__main__":
    main()
