from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finetune_experiments.finetune_data import (
    COMBINED_LANG,
    build_samples,
    default_dataset_path,
    expand_tasks,
    split_dataset_path,
    summarize_records,
    write_jsonl,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Table 3 template fine-tuning JSONL data.")
    parser.add_argument("--task", required=True, choices=["schema", "alignment", "infill", "all"])
    parser.add_argument("--lang", default=COMBINED_LANG, choices=[COMBINED_LANG, "en", "zh"])
    parser.add_argument("--start_id", "--start-id", dest="start_id", type=optional_int, default=None)
    parser.add_argument("--end_id", "--end-id", dest="end_id", type=optional_int, default=None)
    parser.add_argument("--limit", type=int, default=0, help="Maximum samples per task. 0 means no limit.")
    parser.add_argument("--split", choices=["both", "train", "test", "all"], default="both")
    parser.add_argument("--test_ratio", "--test-ratio", dest="test_ratio", type=float, default=0.2)
    parser.add_argument("--split_seed", "--split-seed", dest="split_seed", type=int, default=3407)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--no_validate_alignment",
        "--no-validate-alignment",
        dest="validate_alignment",
        action="store_false",
        help="Skip evaluator-based self-checks for converted alignment gold.",
    )
    parser.set_defaults(validate_alignment=True)
    args = parser.parse_args()

    output_paths = output_paths_for_args(args)
    existing = [path for path in output_paths.values() if path.exists()]
    if existing and not args.overwrite:
        parser.error(
            "Output already exists: "
            + ", ".join(str(path) for path in existing)
            + ". Pass --overwrite to replace it."
        )

    for (task, split), output_path in output_paths.items():
        samples, stats = build_samples(
            task=task,
            lang=args.lang,
            start_id=args.start_id,
            end_id=args.end_id,
            limit=args.limit,
            validate_alignment=args.validate_alignment,
            split=split,
            test_ratio=args.test_ratio,
            split_seed=args.split_seed,
        )
        write_jsonl(samples, output_path)
        stats = replace(stats, output_path=output_path)
        record_summary = summarize_records([sample.to_json_record() for sample in samples])
        print(json.dumps(stats.to_json_record(), indent=2, ensure_ascii=False))
        print(json.dumps(record_summary, indent=2, ensure_ascii=False))


def output_paths_for_args(args: argparse.Namespace) -> dict[tuple[str, str], Path]:
    tasks = expand_tasks(args.task)
    splits = ("train", "test") if args.split == "both" else (args.split,)
    return {
        (task, split): output_path_for_task_split(args, task, split, len(tasks) > 1)
        for task in tasks
        for split in splits
    }


def output_path_for_task_split(
    args: argparse.Namespace,
    task: str,
    split: str,
    task_is_expanded: bool,
) -> Path:
    if args.output is None:
        if split == "all":
            return default_dataset_path(task, args.lang)
        return split_dataset_path(task, args.lang, split)

    if task_is_expanded:
        return output_path_for_expanded_task(args.output, task, args.lang, split)

    if args.split == "both":
        stem = args.output.with_suffix("")
        suffix = args.output.suffix or ".jsonl"
        return Path(f"{stem}_{split}{suffix}")
    return args.output


def output_path_for_expanded_task(output: Path, task: str, lang: str, split: str) -> Path:
    output_dir = output if output.suffix == "" else output.parent
    if split == "all":
        return output_dir / default_dataset_path(task, lang).name
    return output_dir / split_dataset_path(task, lang, split).name


def optional_int(value: str) -> int | None:
    if value.strip() == "":
        return None
    return int(value)


if __name__ == "__main__":
    main()
