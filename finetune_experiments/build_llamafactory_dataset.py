from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FINETUNE_ROOT = Path(__file__).resolve().parent
DATASET_DIR = FINETUNE_ROOT / "datasets"
LLAMAFACTORY_DATASET_DIR = FINETUNE_ROOT / "llamafactory_data"
SUPPORTED_FINETUNE_TASKS = ("infill",)
COMBINED_LANG = "both"
LLAMAFACTORY_TASK_NAMES = {"infill": "fill"}
FILL_INSTRUCTION = (
    "根据提供的相关内容，提取信息填写到表格里面，注意严格遵守相关内容的信息，"
    "有些内容需要填写在key（key指的就是键值对的键，例如：\"姓名：小明\"，"
    "这里面的\"姓名\"就是key）的同一个单元格里面，有的需要填写在不同的单元格里面，"
    "注意有些是需要打对勾的、或者在input标签里面写入“checked”，"
    "最终输出填写后的HTML表格"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Task 3 fine-tuning JSONL data to the LLaMA-Factory magic_conch JSON format.")
    parser.add_argument("--task", default="infill", choices=["infill", "all"])
    parser.add_argument("--lang", default=COMBINED_LANG, choices=[COMBINED_LANG, "en", "zh"])
    parser.add_argument("--source_dir", "--source-dir", dest="source_dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--output_dir", "--output-dir", dest="output_dir", type=Path, default=LLAMAFACTORY_DATASET_DIR)
    parser.add_argument("--split", choices=["both", "train", "test"], default="both")
    parser.add_argument(
        "--id_style",
        "--id-style",
        dest="id_style",
        choices=["prefixed", "offset", "sample_id"],
        default="prefixed",
        help="How to write record ids. prefixed avoids en/zh collisions, e.g. en_1.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    output_paths = output_paths_for_args(args)
    existing = [path for path in output_paths.values() if path.exists()]
    if existing and not args.overwrite:
        parser.error(
            "Output already exists: "
            + ", ".join(str(path) for path in existing)
            + ". Pass --overwrite to replace it."
        )

    manifest: list[dict[str, Any]] = []
    for task in expand_tasks(args.task):
        for split in splits_for_arg(args.split):
            source_path = args.source_dir / split_dataset_path(task, args.lang, split).name
            records = read_jsonl(source_path)
            llamafactory_records = [
                llamafactory_record(record, split_index=index, id_style=args.id_style)
                for index, record in enumerate(records, start=1)
            ]
            output_path = output_paths[(task, split)]
            write_json_file(llamafactory_records, output_path)
            manifest.append(
                {
                    "task": task,
                    "llamafactory_task": LLAMAFACTORY_TASK_NAMES[task],
                    "split": split,
                    "source_path": str(source_path),
                    "output_path": str(output_path),
                    "record_count": len(llamafactory_records),
                    "id_style": args.id_style,
                }
            )
            print(json.dumps(manifest[-1], indent=2, ensure_ascii=False))

    manifest_path = args.output_dir / "manifest.json"
    if not manifest_path.exists() or args.overwrite:
        write_json_file(manifest, manifest_path)


def splits_for_arg(split: str) -> tuple[str, ...]:
    return ("train", "test") if split == "both" else (split,)


def expand_tasks(task: str) -> tuple[str, ...]:
    if task == "all":
        return SUPPORTED_FINETUNE_TASKS
    if task not in SUPPORTED_FINETUNE_TASKS:
        raise ValueError(f"Unsupported fine-tuning task: {task}")
    return (task,)


def split_dataset_path(task: str, lang: str, split: str) -> Path:
    return DATASET_DIR / f"{task}_{lang}_template_{split}.jsonl"


def output_paths_for_args(args: argparse.Namespace) -> dict[tuple[str, str], Path]:
    return {
        (task, split): args.output_dir / f"magic_conch_{LLAMAFACTORY_TASK_NAMES[task]}_{split}.json"
        for task in expand_tasks(args.task)
        for split in splits_for_arg(args.split)
    }


def llamafactory_record(record: dict[str, Any], split_index: int, id_style: str) -> dict[str, Any]:
    task = str(record["task"])
    split = str(record["split"])
    output = str(record["completion"])
    item_id = record_id(record, id_style)

    if task == "infill":
        item = {
            "id": item_id,
            "split_id": split_index,
            "input": llamafactory_input(record),
            "output": fenced_html(output),
        }
        if split == "train":
            item["instruction"] = FILL_INSTRUCTION
        return item
    raise ValueError(f"Unsupported task in record: {task}")


def record_id(record: dict[str, Any], id_style: str) -> int | str:
    sample_id = int(record["sample_id"])
    lang = str(record.get("lang", ""))
    if id_style == "sample_id":
        return sample_id
    if id_style == "offset":
        return sample_id if lang == "en" else sample_id + 100000
    return f"{lang}_{sample_id}" if lang else str(sample_id)


def llamafactory_input(record: dict[str, Any]) -> str:
    source_files = record.get("source_files")
    if not isinstance(source_files, dict):
        raise ValueError(f"Record missing source_files: {record.get('sample_id')}")

    html_path = Path(str(source_files["html"]))
    html = read_text(html_path).strip()
    text = f"HTML:\n{html}"

    if record.get("task") == "infill":
        context_path = Path(str(source_files["context"]))
        context = read_text(context_path).strip()
        text = f"{text}\n相关内容:\n{context}"

    return text


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fenced_html(html: str) -> str:
    text = html.strip()
    if text.startswith("```"):
        return text
    return f"```html\n{text}\n```"


def write_json_file(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
