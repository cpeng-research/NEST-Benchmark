from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from table3_comparative_eval.config import (
    CLOSED_SOURCE_MODELS,
    OPEN_SOURCE_MODELS,
    SUPPORTED_CONDITIONS,
    SUPPORTED_MODELS,
    SUPPORTED_TASKS,
    is_open_source_model,
    prediction_dir,
    workflow_paths,
)
from table3_comparative_eval.prompts import TABLE3_SYSTEM_PROMPT
from table3_comparative_eval.run_inference import (
    build_jobs,
    optional_int,
    run_openai_predictions,
    should_skip_prediction,
    write_prediction,
)
from table3_comparative_eval.utils.io_utils import ensure_dir
from table3_comparative_eval.utils.openai_utils import strip_thinking


LANGS = ("en", "zh")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run one Table 3 task across empty/filled conditions, en/zh languages, "
            "and a selected model group."
        )
    )
    parser.add_argument("--task", required=True, choices=SUPPORTED_TASKS)
    parser.add_argument("--model_group", "--model-group", dest="model_group", choices=["api", "open_source", "all"], default="all")
    parser.add_argument("--langs", nargs="*", choices=LANGS, default=list(LANGS))
    parser.add_argument("--conditions", nargs="*", choices=SUPPORTED_CONDITIONS, default=list(SUPPORTED_CONDITIONS))
    parser.add_argument("--models", nargs="*", choices=SUPPORTED_MODELS, default=list(SUPPORTED_MODELS))
    parser.add_argument("--start_id", type=optional_int, default=None)
    parser.add_argument("--end_id", type=optional_int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--api_workers", "--api-workers", dest="api_workers", type=int, default=8)
    parser.add_argument("--request_timeout", "--request-timeout", dest="request_timeout", type=float, default=120.0)
    parser.add_argument("--max_retries", "--max-retries", dest="max_retries", type=int, default=3)
    parser.add_argument("--retry_sleep", "--retry-sleep", dest="retry_sleep", type=float, default=5.0)
    parser.add_argument("--max_seq_length", "--max-seq-length", dest="max_seq_length", type=int, default=8192)
    parser.add_argument("--max_new_tokens", "--max-new-tokens", dest="max_new_tokens", type=int, default=2048)
    parser.add_argument("--device_map", "--device-map", dest="device_map", default="auto")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top_p", "--top-p", dest="top_p", type=float, default=0.9)
    parser.add_argument(
        "--load_in_4bit",
        "--load-in-4bit",
        dest="load_in_4bit",
        action="store_true",
        default=True,
    )
    parser.add_argument("--no_load_in_4bit", "--no-load-in-4bit", dest="load_in_4bit", action="store_false")
    parser.add_argument("--local_files_only", "--local-files-only", dest="local_files_only", action="store_true")
    parser.add_argument("--raw_prompt", "--raw-prompt", dest="raw_prompt", action="store_true")
    parser.add_argument("--continue_on_error", "--continue-on-error", dest="continue_on_error", action="store_true")
    parser.add_argument("--dry_run", "--dry-run", dest="dry_run", action="store_true")
    args = parser.parse_args()

    if args.api_workers < 1:
        parser.error("--api_workers must be at least 1.")
    if args.request_timeout <= 0:
        parser.error("--request_timeout must be positive.")
    if args.max_retries < 1:
        parser.error("--max_retries must be at least 1.")
    if args.retry_sleep < 0:
        parser.error("--retry_sleep cannot be negative.")

    selected_models = filter_models(args.models, args.model_group)
    api_models = [model for model in selected_models if not is_open_source_model(model)]
    local_models = [model for model in selected_models if is_open_source_model(model)]

    print(
        f"task={args.task} model_group={args.model_group} langs={','.join(args.langs)} conditions={','.join(args.conditions)} "
        f"api_models={len(api_models)} local_models={len(local_models)}"
    )
    print(f"API inference uses {args.api_workers} workers per model/lang/condition.")
    print("Local open-source inference runs serially with one loaded model at a time.")

    run_api_matrix(args, api_models)
    run_local_matrix(args, local_models)


def filter_models(models: list[str], model_group: str) -> list[str]:
    if model_group == "api":
        return [model for model in models if model in CLOSED_SOURCE_MODELS]
    if model_group == "open_source":
        return [model for model in models if model in OPEN_SOURCE_MODELS]
    return models


def run_api_matrix(args: argparse.Namespace, api_models: list[str]) -> None:
    for lang in args.langs:
        for condition in args.conditions:
            for model in api_models:
                pending = collect_pending(args, model, lang, condition)
                describe_combo("api", args.task, condition, lang, model, pending)
                if args.dry_run or not pending:
                    continue
                run_openai_predictions(
                    model,
                    pending,
                    args.api_workers,
                    args.request_timeout,
                    args.max_retries,
                    args.retry_sleep,
                )


def run_local_matrix(args: argparse.Namespace, local_models: list[str]) -> None:
    if not local_models:
        return

    if args.dry_run:
        for model in local_models:
            for lang in args.langs:
                for condition in args.conditions:
                    pending = collect_pending(args, model, lang, condition)
                    describe_combo("local", args.task, condition, lang, model, pending)
        return

    from table3_comparative_eval.utils.local_model_utils import LocalGenerationConfig, LocalUnslothGenerator

    config = LocalGenerationConfig(
        max_seq_length=args.max_seq_length,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        load_in_4bit=args.load_in_4bit,
        local_files_only=args.local_files_only,
        raw_prompt=args.raw_prompt,
        model_path=None,
        device_map=args.device_map,
    )

    for model in local_models:
        combo_pending = [
            (lang, condition, collect_pending(args, model, lang, condition))
            for lang in args.langs
            for condition in args.conditions
        ]
        if not any(pending for _, _, pending in combo_pending):
            for lang, condition, pending in combo_pending:
                describe_combo("local", args.task, condition, lang, model, pending)
            continue

        generator = LocalUnslothGenerator(model, config)
        print(f"local model={model} backend={generator.backend} resolved_model={generator.resolved_model}")
        for lang, condition, pending in combo_pending:
            describe_combo("local", args.task, condition, lang, model, pending)
            run_local_combo(args, generator, model, pending)


def collect_pending(
    args: argparse.Namespace,
    model: str,
    lang: str,
    condition: str,
) -> list[tuple[int, str, Path]]:
    paths = workflow_paths(lang)
    out_dir = prediction_dir(args.task, condition, lang, model)
    if not args.dry_run:
        ensure_dir(out_dir)

    jobs = build_jobs(args.task, condition, paths, args.start_id, args.end_id, args.limit)
    pending = []
    for sample_id, prompt in jobs:
        out_file = out_dir / f"{sample_id}.json"
        if should_skip_prediction(out_file, args.overwrite):
            continue
        pending.append((sample_id, prompt, out_file))
    return pending


def run_local_combo(args: argparse.Namespace, generator, model: str, pending: list[tuple[int, str, Path]]) -> None:
    for sample_id, prompt, out_file in pending:
        try:
            text = strip_thinking(generator.generate(prompt, TABLE3_SYSTEM_PROMPT))
            if not text:
                raise RuntimeError("empty local response")
            write_prediction(
                out_file,
                {
                    "sample_id": sample_id,
                    "model": model,
                    "resolved_model": generator.resolved_model,
                    "backend": generator.backend,
                    "raw_response": text,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            print(f"completed sample {sample_id}")
        except Exception as exc:
            if not args.continue_on_error:
                raise
            print(f"skipped sample {sample_id} after local inference error: {exc}", file=sys.stderr)


def describe_combo(backend: str, task: str, condition: str, lang: str, model: str, pending: list[tuple[int, str, Path]]) -> None:
    print(
        f"[{backend}] task={task} condition={condition} lang={lang} "
        f"model={model} pending={len(pending)}"
    )


if __name__ == "__main__":
    main()
