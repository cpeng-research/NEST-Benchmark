from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from table3_comparative_eval.config import (
    SUPPORTED_CONDITIONS,
    SUPPORTED_MODELS,
    SUPPORTED_TASKS,
    is_open_source_model,
    prediction_dir,
    workflow_paths,
)
from table3_comparative_eval.prompts import TABLE3_SYSTEM_PROMPT, alignment_prompt, infill_prompt, schema_prompt
from table3_comparative_eval.utils.io_utils import ensure_dir, id_in_range, iter_numeric_files, read_json, read_text, write_json
from table3_comparative_eval.utils.openai_utils import create_client, extract_text, strip_thinking


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Table 3 model inference.")
    parser.add_argument("--task", required=True, choices=SUPPORTED_TASKS)
    parser.add_argument("--condition", required=True, choices=SUPPORTED_CONDITIONS)
    parser.add_argument("--model", required=True, choices=SUPPORTED_MODELS)
    parser.add_argument("--lang", default="en", choices=["en", "zh"])
    parser.add_argument("--start_id", type=optional_int, default=None)
    parser.add_argument("--end_id", type=optional_int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--request_timeout", "--request-timeout", dest="request_timeout", type=float, default=120.0, help="API request timeout in seconds.")
    parser.add_argument("--max_retries", "--max-retries", dest="max_retries", type=int, default=3, help="Maximum API attempts per sample.")
    parser.add_argument("--retry_sleep", "--retry-sleep", dest="retry_sleep", type=float, default=5.0, help="Base seconds to sleep between API retries.")
    parser.add_argument("--model_path", "--model-path", dest="model_path", default=None, help="Override HF/local path for open-source models.")
    parser.add_argument("--max_seq_length", "--max-seq-length", dest="max_seq_length", type=int, default=8192)
    parser.add_argument("--max_new_tokens", "--max-new-tokens", dest="max_new_tokens", type=int, default=2048)
    parser.add_argument("--device_map", "--device-map", dest="device_map", default="auto", help="Device map for CUDA/PyTorch open-source loading.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top_p", "--top-p", dest="top_p", type=float, default=0.9)
    parser.add_argument(
        "--load_in_4bit",
        "--load-in-4bit",
        dest="load_in_4bit",
        action="store_true",
        default=True,
        help="Load open-source models in 4-bit mode when supported. Enabled by default.",
    )
    parser.add_argument(
        "--no_load_in_4bit",
        "--no-load-in-4bit",
        dest="load_in_4bit",
        action="store_false",
        help="Disable 4-bit loading for open-source models.",
    )
    parser.add_argument(
        "--local_files_only",
        "--local-files-only",
        dest="local_files_only",
        action="store_true",
        help="Only use cached/local files for open-source models.",
    )
    parser.add_argument(
        "--raw_prompt",
        "--raw-prompt",
        dest="raw_prompt",
        action="store_true",
        help="Do not apply the model chat template for open-source models.",
    )
    args = parser.parse_args()
    
    if args.model_path and not is_open_source_model(args.model):
        parser.error("--model_path is only valid for open-source models.")
    if args.request_timeout <= 0:
        parser.error("--request_timeout must be positive.")
    if args.max_retries < 1:
        parser.error("--max_retries must be at least 1.")
    if args.retry_sleep < 0:
        parser.error("--retry_sleep cannot be negative.")

    paths = workflow_paths(args.lang)
    out_dir = ensure_dir(prediction_dir(args.task, args.condition, args.lang, args.model))
    jobs = build_jobs(args.task, args.condition, paths, args.start_id, args.end_id, args.limit)
    if not jobs:
        print("No jobs found.")
        return

    pending = []
    for sample_id, prompt in jobs:
        out_file = out_dir / f"{sample_id}.json"
        if should_skip_prediction(out_file, args.overwrite):
            continue
        pending.append((sample_id, prompt, out_file))

    print(f"task={args.task} condition={args.condition} model={args.model} jobs={len(jobs)} pending={len(pending)}")
    if not pending:
        return

    if is_open_source_model(args.model):
        run_local_predictions(args, pending)
        return

    run_openai_predictions(args.model, pending, args.workers, args.request_timeout, args.max_retries, args.retry_sleep)


def optional_int(value: str) -> int | None:
    if value.strip() == "":
        return None
    return int(value)


def should_skip_prediction(out_file: Path, overwrite: bool) -> bool:
    if overwrite or not out_file.exists():
        return False
    return not prediction_has_empty_response(out_file)


def prediction_has_empty_response(out_file: Path) -> bool:
    try:
        record = read_json(out_file)
    except Exception:
        return True
    if not isinstance(record, dict):
        return True
    return not str(record.get("raw_response", "")).strip()


@dataclass(frozen=True)
class PredictionResult:
    sample_id: int
    success: bool
    attempts: int
    error: str | None = None


def run_openai_predictions(
    model: str,
    pending: list[tuple[int, str, Path]],
    workers: int,
    request_timeout: float,
    max_retries: int,
    retry_sleep: float,
) -> None:
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [
            pool.submit(
                run_one_openai,
                model,
                sample_id,
                prompt,
                out_file,
                request_timeout,
                max_retries,
                retry_sleep,
            )
            for sample_id, prompt, out_file in pending
        ]
        for fut in as_completed(futures):
            result = fut.result()
            if result.success:
                print(f"completed sample {result.sample_id} attempts={result.attempts}")
            else:
                print(f"skipped sample {result.sample_id} attempts={result.attempts} error={result.error}")


def run_local_predictions(args: argparse.Namespace, pending: list[tuple[int, str, Path]]) -> None:
    from table3_comparative_eval.utils.local_model_utils import LocalGenerationConfig, LocalUnslothGenerator

    if args.workers != 1:
        print("Open-source local inference loads one model instance and runs serially; --workers is ignored.")

    config = LocalGenerationConfig(
        max_seq_length=args.max_seq_length,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        load_in_4bit=args.load_in_4bit,
        local_files_only=args.local_files_only,
        raw_prompt=args.raw_prompt,
        model_path=args.model_path,
        device_map=args.device_map,
    )
    generator = LocalUnslothGenerator(args.model, config)
    print(f"local backend={generator.backend} resolved_model={generator.resolved_model}")

    for sample_id, prompt, out_file in pending:
        try:
            text = strip_thinking(generator.generate(prompt, TABLE3_SYSTEM_PROMPT))
            if not text:
                raise RuntimeError("empty local response")
            write_prediction(
                out_file,
                {
                    "sample_id": sample_id,
                    "model": args.model,
                    "resolved_model": generator.resolved_model,
                    "backend": generator.backend,
                    "raw_response": text,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            print(f"completed sample {sample_id}")
        except Exception as exc:
            print(f"skipped sample {sample_id} after local inference error: {exc}")


def build_jobs(task: str, condition: str, paths, start_id: int | None, end_id: int | None, limit: int) -> list[tuple[int, str]]:
    html_dir = paths.html_filled if condition == "filled" else paths.html_empty
    jobs: list[tuple[int, str]] = []
    for html_file in iter_numeric_files(html_dir, ".html"):
        sample_id = int(html_file.stem)
        if not id_in_range(sample_id, start_id, end_id):
            continue
        html = read_text(html_file)
        if task == "schema":
            prompt = schema_prompt(html, condition)
        elif task == "alignment":
            prompt = alignment_prompt(html, condition)
        elif task == "infill":
            context_file = paths.context / f"{sample_id}.txt"
            if not context_file.exists():
                continue
            context = read_text(context_file)
            prompt = infill_prompt(html, context, condition)
        else:
            raise ValueError(task)
        jobs.append((sample_id, prompt))
        if limit and len(jobs) >= limit:
            break
    return jobs


def run_one_openai(
    model: str,
    sample_id: int,
    prompt: str,
    out_file: Path,
    request_timeout: float,
    max_retries: int,
    retry_sleep: float,
) -> PredictionResult:
    client = create_client()
    attempts = max(1, max_retries)
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": TABLE3_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                timeout=request_timeout,
            )
            text = extract_text(response).strip()
            if not text:
                raise RuntimeError("empty response")
            write_prediction(
                out_file,
                {
                    "sample_id": sample_id,
                    "model": model,
                    "backend": "openai",
                    "raw_response": text,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "attempts": attempt,
                    "request_timeout": request_timeout,
                },
            )
            return PredictionResult(sample_id=sample_id, success=True, attempts=attempt)
        except Exception as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            print(f"sample {sample_id} attempt {attempt}/{attempts} failed: {last_error}")
            if attempt < attempts:
                time.sleep(retry_sleep * attempt)

    return PredictionResult(sample_id=sample_id, success=False, attempts=attempts, error=last_error)


def write_prediction(out_file: Path, record: dict) -> None:
    write_json(out_file, record)


if __name__ == "__main__":
    main()
