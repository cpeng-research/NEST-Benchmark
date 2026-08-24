#!/usr/bin/env python3
"""
Step 8: Generate filled JSON for instance B from filled HTML B.

This script reads filled HTML tables from Step 7 and fills the corresponding
annotated JSON template from Step 1. It preserves the JSON structure and writes
one filled JSON file per input HTML.

Usage:
  python workflow/8-json-b/step8_gen_json_b.py --lang en
  python workflow/8-json-b/step8_gen_json_b.py --lang en --start_id 87 --end_id 88
  python workflow/8-json-b/step8_gen_json_b.py --lang en --check-updates
  python workflow/8-json-b/step8_gen_json_b.py --lang en --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUT_HTML_DIR = "workflow/7-html-b/data_{lang}"
DEFAULT_TEMPLATE_JSON_DIR = "workflow/1-annotated_json/data_{lang}"
DEFAULT_OUTPUT_JSON_DIR = "workflow/8-json-b/data_{lang}"

DEFAULT_MODEL = "gpt-5"
DEFAULT_MAX_WORKERS = 10
DEFAULT_MAX_RETRIES = 50
SUPPORTED_LANGUAGES = ("en", "zh")

print_lock = Lock()
count_lock = Lock()
client_create_lock = Lock()

processed_count = 0
error_count = 0
skipped_count = 0


SYSTEM_PROMPT = (
    "You extract information from a filled HTML table and populate a JSON template. "
    "Return pure JSON only, with no markdown fences, comments, or explanations. "
    "Keep the JSON structure unchanged: preserve all object keys and nesting. Preserve list lengths for repeated "
    "records; a multi-select field whose key is 'value' may contain the options selected in the HTML. "
    "Only fill template values using information present in the HTML table. "
    "If a value cannot be determined exactly, infer a plausible value from the surrounding filled table context."
)

USER_TEMPLATE = """Filled HTML table:
{html_filled}

JSON template to populate:
{json_template}

Task:
Extract the values from the filled HTML table and fill the JSON template.

Rules:
1. Preserve the exact JSON keys and nesting. Preserve list lengths for repeated records; a multi-select "value" list may contain the selected options.
2. Fill every scalar value in the template.
3. For checkbox, radio, select, yes/no, or other selection fields, use the selected value from the HTML.
4. For repeated rows, map row values into the corresponding JSON list entries in order.
5. Return only valid JSON.
"""


@dataclass(frozen=True)
class WorkItem:
    item_id: int
    html_path: Path
    template_json_path: Path
    output_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate instance-B filled JSON files from instance-B filled HTML tables."
    )
    parser.add_argument("--lang", default=None, help="Language suffix, e.g. en or zh. If omitted, both are processed")
    parser.add_argument("--input-html-dir", default=DEFAULT_INPUT_HTML_DIR, help="Input filled-B HTML dir")
    parser.add_argument("--template-json-dir", default=DEFAULT_TEMPLATE_JSON_DIR, help="Input annotated JSON template dir")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_JSON_DIR, help="Output filled-B JSON dir")
    parser.add_argument("--start_id", type=int, default=None, help="Start numeric ID")
    parser.add_argument("--end_id", type=int, default=None, help="End numeric ID")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model name")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL")
    parser.add_argument("--api-key", default=None, help="API key; defaults to OPENAI_API_KEY")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS, help="Concurrent workers")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES, help="Retries per file")
    parser.add_argument("--check-updates", action="store_true", default=True, help="Reprocess if inputs changed")
    parser.add_argument(
        "--no-check-updates",
        dest="check_updates",
        action="store_false",
        help="Skip update checks and only process missing outputs",
    )
    parser.add_argument("--force", action="store_true", help="Reprocess even if output exists")
    return parser.parse_args()


def resolve_lang_path(path_template: str, lang: str) -> Path:
    return (PROJECT_ROOT / path_template.format(lang=lang)).resolve()


def create_client(args: argparse.Namespace) -> Any:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependency: install openai with `pip install openai`.") from exc

    kwargs = {}
    if args.api_key:
        kwargs["api_key"] = args.api_key
    if args.base_url:
        kwargs["base_url"] = args.base_url
    with client_create_lock:
        return OpenAI(**kwargs)


def get_id_from_filename(path: Path) -> Optional[int]:
    try:
        return int(path.stem)
    except ValueError:
        return None


def get_file_mtime(path: Optional[Path]) -> float:
    if path is None:
        return 0.0
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def get_file_size(path: Optional[Path]) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def get_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_file_signature(meta: dict[str, Any], prefix: str, path: Path) -> None:
    meta[f"{prefix}_mtime"] = get_file_mtime(path)
    meta[f"{prefix}_size"] = get_file_size(path)
    meta[f"{prefix}_sha256"] = get_file_sha256(path)


def file_changed(meta: dict[str, Any], prefix: str, path: Path) -> tuple[bool, dict[str, Any]]:
    current = {
        "mtime": get_file_mtime(path),
        "size": get_file_size(path),
    }
    previous_mtime = meta.get(f"{prefix}_mtime")
    previous_size = meta.get(f"{prefix}_size")
    previous_sha256 = meta.get(f"{prefix}_sha256")

    if previous_mtime == current["mtime"] and previous_size == current["size"]:
        current["sha256"] = previous_sha256
        return False, current

    current["sha256"] = get_file_sha256(path)
    if previous_sha256 is not None:
        return current["sha256"] != previous_sha256, current

    if previous_mtime is None:
        return True, current
    return current["mtime"] > float(previous_mtime), current


def find_json_path(json_dir: Path, item_id: int) -> Optional[Path]:
    for suffix in (".json", ".JSON"):
        candidate = json_dir / f"{item_id}{suffix}"
        if candidate.exists():
            return candidate
    return None


def meta_path_for(output_dir: Path, item_id: int) -> Path:
    cache_path = output_dir / "cache" / f".meta_{item_id}.json"
    legacy_path = output_dir / f".meta_{item_id}.json"
    if not cache_path.exists() and legacy_path.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.replace(cache_path)
    return cache_path


def read_meta(output_dir: Path, item_id: int) -> dict[str, Any]:
    meta_path = meta_path_for(output_dir, item_id)
    if not meta_path.exists():
        return {}
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_json_atomic(path: Path, data: Any, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{time.time_ns()}")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    tmp_path.replace(path)


def write_meta(output_dir: Path, item: WorkItem, model: str, metadata_refreshed: bool = False) -> None:
    meta = {
        "id": item.item_id,
        "html_path": str(item.html_path),
        "template_json_path": str(item.template_json_path),
        "model": model,
        "processed_at": time.time(),
    }
    add_file_signature(meta, "html", item.html_path)
    add_file_signature(meta, "template_json", item.template_json_path)
    if metadata_refreshed:
        meta["metadata_refreshed"] = True
    write_json_atomic(meta_path_for(output_dir, item.item_id), meta)


def should_process(item: WorkItem, output_dir: Path, check_updates: bool, force: bool) -> bool:
    if force or not item.output_path.exists():
        return True
    if not check_updates:
        return False

    meta = read_meta(output_dir, item.item_id)
    html_changed, html_signature = file_changed(meta, "html", item.html_path)
    template_changed, template_signature = file_changed(meta, "template_json", item.template_json_path)
    if not html_changed and not template_changed:
        return False

    latest_input_mtime = max(html_signature["mtime"], template_signature["mtime"])
    if get_file_mtime(item.output_path) >= latest_input_mtime:
        write_meta(output_dir, item, str(meta.get("model") or ""), metadata_refreshed=True)
        return False

    return True


def scan_work_items(args: argparse.Namespace) -> list[WorkItem]:
    html_dir = resolve_lang_path(args.input_html_dir, args.lang)
    template_json_dir = resolve_lang_path(args.template_json_dir, args.lang)
    output_dir = resolve_lang_path(args.output_dir, args.lang)

    if not html_dir.exists():
        raise FileNotFoundError(f"Input HTML directory not found: {html_dir}")
    if not template_json_dir.exists():
        raise FileNotFoundError(f"Template JSON directory not found: {template_json_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    items: list[WorkItem] = []
    for html_path in sorted(html_dir.iterdir(), key=lambda p: (get_id_from_filename(p) is None, p.name)):
        if html_path.suffix.lower() not in {".html", ".htm"}:
            continue
        item_id = get_id_from_filename(html_path)
        if item_id is None:
            continue
        if args.start_id is not None and item_id < args.start_id:
            continue
        if args.end_id is not None and item_id > args.end_id:
            continue

        template_json_path = find_json_path(template_json_dir, item_id)
        if template_json_path is None:
            with print_lock:
                print(f"[Scan] ID {item_id}: missing JSON template, skipping.")
            continue

        output_path = output_dir / f"{item_id}.json"
        item = WorkItem(
            item_id=item_id,
            html_path=html_path,
            template_json_path=template_json_path,
            output_path=output_path,
        )
        if should_process(item, output_dir, args.check_updates, args.force):
            items.append(item)

    return items


def extract_llm_content(response: Any) -> Optional[str]:
    """Extract text from OpenAI SDK, dict-like, or string responses."""
    if response is None:
        return None

    if isinstance(response, str):
        return response

    if isinstance(response, dict):
        if isinstance(response.get("output_text"), str):
            return response["output_text"]

        choices = response.get("choices")
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if content is not None:
                return normalize_llm_content(content)

        content = response.get("content")
        if content is not None:
            return normalize_llm_content(content)

        return None

    if hasattr(response, "output_text"):
        output_text = response.output_text
        if isinstance(output_text, str):
            return output_text

    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message is not None else None
        if content is not None:
            return normalize_llm_content(content)

    content = getattr(response, "content", None)
    if content is not None:
        return normalize_llm_content(content)

    return None


def normalize_llm_content(content: Any) -> Optional[str]:
    """Normalize plain text or structured content blocks to a string."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(text, dict) and isinstance(text.get("value"), str):
                    parts.append(text["value"])
            else:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(text, dict) and isinstance(text.get("value"), str):
                    parts.append(text["value"])
        return "".join(parts) if parts else None

    return str(content)


def build_messages(html_filled: str, json_template: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(html_filled=html_filled, json_template=json_template),
        },
    ]


def parse_json_response(text: Optional[str]) -> tuple[Optional[Any], Optional[str]]:
    if not text:
        return None, "empty response"

    stripped = text.strip()
    candidates = [stripped]

    if "```" in stripped:
        parts = stripped.split("```")
        for part in parts:
            snippet = part.strip()
            if not snippet:
                continue
            if snippet.lower().startswith("json"):
                snippet = snippet[4:].strip()
            candidates.insert(0, snippet)

    first_obj = stripped.find("{")
    last_obj = stripped.rfind("}")
    if first_obj >= 0 and last_obj > first_obj:
        candidates.append(stripped[first_obj : last_obj + 1])

    first_arr = stripped.find("[")
    last_arr = stripped.rfind("]")
    if first_arr >= 0 and last_arr > first_arr:
        candidates.append(stripped[first_arr : last_arr + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate), None
        except json.JSONDecodeError:
            continue

    return None, "invalid json format"


def structure_matches(
    template: Any,
    output: Any,
    path: str = "$",
    allow_variable_scalar_list: bool = False,
) -> tuple[bool, str]:
    if isinstance(template, dict):
        if not isinstance(output, dict):
            return False, f"{path}: expected object"
        template_keys = set(template.keys())
        output_keys = set(output.keys())
        if template_keys != output_keys:
            missing = sorted(template_keys - output_keys)
            extra = sorted(output_keys - template_keys)
            return False, f"{path}: key mismatch, missing={missing}, extra={extra}"
        for key in template:
            ok, reason = structure_matches(
                template[key],
                output[key],
                f"{path}.{key}",
                allow_variable_scalar_list=(key == "value"),
            )
            if not ok:
                return ok, reason
        return True, ""

    if isinstance(template, list):
        if not isinstance(output, list):
            return False, f"{path}: expected list"
        if allow_variable_scalar_list:
            if all(not isinstance(item, (dict, list)) for item in output):
                return True, ""
            return False, f"{path}: expected a list of selected scalar values"
        if len(template) != len(output):
            return False, f"{path}: expected list length {len(template)}, got {len(output)}"
        for index, template_item in enumerate(template):
            ok, reason = structure_matches(template_item, output[index], f"{path}[{index}]")
            if not ok:
                return ok, reason
        return True, ""

    if isinstance(output, (dict, list)):
        return False, f"{path}: expected scalar value"
    return True, ""


def call_model_with_retries(client: Any, args: argparse.Namespace, html_filled: str, template_obj: Any) -> Any:
    template_text = json.dumps(template_obj, ensure_ascii=False, indent=2)
    last_error = ""

    for attempt in range(1, args.max_retries + 1):
        try:
            completion = client.chat.completions.create(
                model=args.model,
                messages=build_messages(html_filled, template_text),
            )
            raw = extract_llm_content(completion)
            parsed, parse_error = parse_json_response(raw)
            if parsed is None:
                last_error = parse_error or "failed to parse json"
            else:
                valid, reason = structure_matches(template_obj, parsed)
                if valid:
                    return parsed
                last_error = reason
        except Exception as exc:
            last_error = str(exc)

        if attempt < args.max_retries:
            time.sleep(min(0.5 * (1.5 ** min(attempt, 8)), 8.0))

    raise RuntimeError(f"failed after {args.max_retries} attempts: {last_error}")


def process_item(item: WorkItem, args: argparse.Namespace, output_dir: Path) -> None:
    global processed_count, error_count

    try:
        html_filled = item.html_path.read_text(encoding="utf-8")
        with item.template_json_path.open("r", encoding="utf-8") as f:
            template_obj = json.load(f)

        client = create_client(args)
        filled_json = call_model_with_retries(client, args, html_filled, template_obj)

        with item.output_path.open("w", encoding="utf-8") as f:
            json.dump(filled_json, f, ensure_ascii=False, indent=2)
            f.write("\n")
        write_meta(output_dir, item, args.model)

        with count_lock:
            processed_count += 1
        with print_lock:
            print(f"[Thread {threading.current_thread().name}] Completed ID {item.item_id} -> {item.output_path}")
    except Exception as exc:
        with count_lock:
            error_count += 1
        with print_lock:
            print(f"[Thread {threading.current_thread().name}] Error processing ID {item.item_id}: {exc}")


def main() -> int:
    args = parse_args()
    if args.lang is None:
        exit_code = 0
        for lang in SUPPORTED_LANGUAGES:
            print(f"\n{'='*60}\nRunning language: {lang.upper()}\n{'='*60}")
            result = subprocess.run([sys.executable, __file__, *sys.argv[1:], "--lang", lang])
            exit_code = max(exit_code, result.returncode)
        return exit_code

    input_html_dir = resolve_lang_path(args.input_html_dir, args.lang)
    template_json_dir = resolve_lang_path(args.template_json_dir, args.lang)
    output_dir = resolve_lang_path(args.output_dir, args.lang)

    print(f"Language: {args.lang.upper()}")
    print(f"Input filled-B HTML dir: {input_html_dir}")
    print(f"Template JSON dir: {template_json_dir}")
    print(f"Output filled-B JSON dir: {output_dir}")
    print(f"Model: {args.model}")

    try:
        items = scan_work_items(args)
    except Exception as exc:
        print(f"Error scanning work items: {exc}")
        return 1

    print(f"Found {len(items)} item(s) to process.")
    if not items:
        print("No data needs processing.")
        return 0

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_item = {executor.submit(process_item, item, args, output_dir): item for item in items}
        total = len(future_to_item)
        completed = 0
        for future in as_completed(future_to_item):
            completed += 1
            future.result()
            if completed % 10 == 0 or completed == total:
                print(f"Progress: {completed}/{total} ({completed * 100 // total}%) | Errors: {error_count}")

    print("\nJSON-B generation completed.")
    print(f"Total attempted: {len(items)}")
    print(f"Successful saves: {processed_count}")
    print(f"Errors: {error_count}")
    print(f"Results saved in: {output_dir}")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
