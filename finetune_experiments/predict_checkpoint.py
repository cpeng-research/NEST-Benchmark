from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finetune_experiments.checkpoint_utils import (
    DEFAULT_CHECKPOINT_TASKS,
    FineTunedCheckpointGenerator,
    derive_prediction_model_name,
    expand_checkpoint_tasks,
    load_test_records,
    prediction_has_nonempty_response,
    prediction_path_for_record,
)
from finetune_experiments.finetune_data import COMBINED_LANG, DATASET_DIR
from comparative_eval.prompts import TABLE3_SYSTEM_PROMPT
from comparative_eval.utils.io_utils import ensure_dir, write_json
from comparative_eval.utils.local_model_utils import LocalGenerationConfig
from comparative_eval.utils.openai_utils import strip_thinking


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Load a fine-tuned LoRA checkpoint, run inference on the new "
            "finetune_experiments/datasets test split, and save fine-tune predictions."
        )
    )
    parser.add_argument("--checkpoint_dir", "--checkpoint-dir", dest="checkpoint_dir", type=Path, required=True)
    parser.add_argument("--base_model", "--base-model", dest="base_model", default=None, help="Optional base model override.")
    parser.add_argument("--prediction_model_name", "--prediction-model-name", dest="prediction_model_name", default=None)
    parser.add_argument("--dataset_dir", "--dataset-dir", dest="dataset_dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--tasks", nargs="*", choices=[*DEFAULT_CHECKPOINT_TASKS, "all"], default=["all"])
    parser.add_argument("--lang", default=COMBINED_LANG, choices=[COMBINED_LANG, "en", "zh"])
    parser.add_argument("--limit", type=int, default=0, help="Limit records per task after filtering. 0 means no limit.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--clear_task_predictions", "--clear-task-predictions", dest="clear_task_predictions", action="store_true")
    parser.add_argument("--dry_run", "--dry-run", dest="dry_run", action="store_true")

    parser.add_argument("--max_seq_length", "--max-seq-length", dest="max_seq_length", type=int, default=32768)
    parser.add_argument("--max_new_tokens", "--max-new-tokens", dest="max_new_tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top_p", "--top-p", dest="top_p", type=float, default=0.9)
    parser.add_argument("--load_in_4bit", "--load-in-4bit", dest="load_in_4bit", action="store_true", default=True)
    parser.add_argument("--no_load_in_4bit", "--no-load-in-4bit", dest="load_in_4bit", action="store_false")
    parser.add_argument("--local_files_only", "--local-files-only", dest="local_files_only", action="store_true")
    parser.add_argument("--raw_prompt", "--raw-prompt", dest="raw_prompt", action="store_true")
    parser.add_argument("--device_map", "--device-map", dest="device_map", default="auto")
    parser.add_argument("--dtype", default=None)
    args = parser.parse_args()

    if not args.checkpoint_dir.exists():
        parser.error(f"Checkpoint directory does not exist: {args.checkpoint_dir}")
    if args.limit < 0:
        parser.error("--limit cannot be negative.")

    tasks = expand_checkpoint_tasks(args.tasks)
    prediction_model_name = args.prediction_model_name or derive_prediction_model_name(args.checkpoint_dir)
    records_by_task = {
        task: load_test_records(task, args.lang, args.dataset_dir, args.limit)
        for task in tasks
    }
    if args.clear_task_predictions and not args.dry_run:
        clear_prediction_dirs_for_records(records_by_task, prediction_model_name)

    pending = []
    skipped_existing = 0
    for task, records in records_by_task.items():
        for record in records:
            out_file = prediction_path_for_record(record, prediction_model_name)
            if prediction_has_nonempty_response(out_file) and not args.overwrite:
                skipped_existing += 1
                continue
            pending.append((task, record, out_file))

    print(
        json.dumps(
            {
                "checkpoint_dir": str(args.checkpoint_dir),
                "prediction_model_name": prediction_model_name,
                "dataset_dir": str(args.dataset_dir),
                "tasks": list(tasks),
                "lang": args.lang,
                "records_by_task": {task: len(records) for task, records in records_by_task.items()},
                "pending": len(pending),
                "skipped_existing": skipped_existing,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if args.dry_run or not pending:
        return

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
    generator = FineTunedCheckpointGenerator(
        checkpoint_dir=args.checkpoint_dir,
        config=config,
        base_model=args.base_model,
        dtype=args.dtype,
    )
    print(
        json.dumps(
            {
                "backend": generator.backend,
                "adapter_format": generator.adapter_format,
                "raw_base_model": generator.raw_base_model,
                "resolved_base_model": generator.resolved_base_model,
                "adapter_load_dir": str(generator.adapter_load_dir),
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    completed = 0
    failed = 0
    for index, (task, record, out_file) in enumerate(pending, start=1):
        sample_id = int(record["sample_id"])
        lang = str(record["lang"])
        condition = str(record.get("condition", "empty"))
        label = f"task={task} condition={condition} lang={lang} sample_id={sample_id}"
        try:
            text = strip_thinking(generator.generate(str(record["prompt"]), TABLE3_SYSTEM_PROMPT))
            if not text:
                raise RuntimeError("empty response")
            ensure_dir(out_file.parent)
            write_json(
                out_file,
                {
                    "sample_id": sample_id,
                    "task": task,
                    "condition": condition,
                    "lang": lang,
                    "model": prediction_model_name,
                    "checkpoint_dir": str(args.checkpoint_dir),
                    "raw_base_model": generator.raw_base_model,
                    "resolved_base_model": generator.resolved_base_model,
                    "adapter_load_dir": str(generator.adapter_load_dir),
                    "backend": generator.backend,
                    "adapter_format": generator.adapter_format,
                    "raw_response": text,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "finetune_split": record.get("split", "test"),
                    "source_files": record.get("source_files", {}),
                    "max_seq_length": args.max_seq_length,
                    "max_new_tokens": args.max_new_tokens,
                    "temperature": args.temperature,
                    "top_p": args.top_p,
                },
            )
            completed += 1
            print(f"[{index}/{len(pending)}] completed {label}")
        except Exception as exc:
            failed += 1
            print(f"[{index}/{len(pending)}] failed {label}: {exc}", file=sys.stderr)

    print(f"done completed={completed} failed={failed} skipped_existing={skipped_existing}")


def clear_prediction_dirs_for_records(records_by_task: dict[str, list[dict]], prediction_model_name: str) -> None:
    dirs = {
        prediction_path_for_record(record, prediction_model_name).parent
        for records in records_by_task.values()
        for record in records
    }
    for directory in dirs:
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            path.unlink()


if __name__ == "__main__":
    main()
