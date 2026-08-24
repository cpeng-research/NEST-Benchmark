#!/usr/bin/env python3
"""
Step 7: Generate filled HTML for instance B.

This script reads already-filled HTML tables from Step 3 (instance A) and
generates another filled version of the same table (instance B). The table
structure is preserved while filled values are changed.

Usage:
  python workflow/7-html-b/step7_gen_html_b.py --lang en
  python workflow/7-html-b/step7_gen_html_b.py --lang en --start_id 87 --end_id 88
  python workflow/7-html-b/step7_gen_html_b.py --lang en --check-updates
  python workflow/7-html-b/step7_gen_html_b.py --lang en --force
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUT_DIR = "workflow/3-filled_html-a/data_{lang}"
DEFAULT_TEMPLATE_DIR = "workflow/0-html_template/data_{lang}"
DEFAULT_OUTPUT_DIR = "workflow/7-html-b/data_{lang}"

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


@dataclass(frozen=True)
class WorkItem:
    item_id: int
    input_path: Path
    output_path: Path
    template_path: Optional[Path]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate instance-B filled HTML tables from instance-A filled HTML tables."
    )
    parser.add_argument("--lang", default=None, help="Language suffix, e.g. en or zh. If omitted, both are processed")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR, help="Input filled-A HTML dir")
    parser.add_argument("--template-dir", default=DEFAULT_TEMPLATE_DIR, help="Optional unfilled template dir")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output filled-B HTML dir")
    parser.add_argument("--start_id", type=int, default=None, help="Start numeric ID")
    parser.add_argument("--end_id", type=int, default=None, help="End numeric ID")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model name")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL")
    parser.add_argument("--api-key", default=None, help="API key; defaults to OPENAI_API_KEY")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS, help="Concurrent workers")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES, help="Retries per file")
    parser.add_argument("--check-updates", action="store_true", default=True, help="Reprocess if input changed")
    parser.add_argument(
        "--no-check-updates",
        dest="check_updates",
        action="store_false",
        help="Skip update checks and only process missing outputs",
    )
    parser.add_argument("--force", action="store_true", help="Reprocess even if output exists")
    parser.add_argument(
        "--no-template",
        action="store_true",
        help="Do not include Step 0 template in the prompt even if available",
    )
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


def add_file_signature(meta: dict[str, Any], prefix: str, path: Optional[Path]) -> None:
    meta[f"{prefix}_mtime"] = get_file_mtime(path)
    meta[f"{prefix}_size"] = get_file_size(path)
    meta[f"{prefix}_sha256"] = get_file_sha256(path) if path is not None else None


def file_changed(meta: dict[str, Any], prefix: str, path: Optional[Path]) -> tuple[bool, dict[str, Any]]:
    if path is None:
        return False, {"mtime": 0.0, "size": 0, "sha256": None}

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


def find_template_path(template_dir: Path, item_id: int) -> Optional[Path]:
    for suffix in (".html", ".HTML", ".htm", ".HTM"):
        candidate = template_dir / f"{item_id}{suffix}"
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
        import json

        with meta_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_json_atomic(path: Path, data: Any, indent: int = 2) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{time.time_ns()}")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    tmp_path.replace(path)


def write_meta(output_dir: Path, item: WorkItem, model: str) -> None:
    meta = {
        "id": item.item_id,
        "input_path": str(item.input_path),
        "template_path": str(item.template_path) if item.template_path else None,
        "model": model,
        "processed_at": time.time(),
    }
    add_file_signature(meta, "input", item.input_path)
    add_file_signature(meta, "template", item.template_path)
    write_json_atomic(meta_path_for(output_dir, item.item_id), meta)


def refresh_meta(
    output_dir: Path,
    item_id: int,
    input_path: Path,
    template_path: Optional[Path],
    model: Optional[str],
) -> None:
    meta = {
        "id": item_id,
        "input_path": str(input_path),
        "template_path": str(template_path) if template_path else None,
        "model": model,
        "processed_at": time.time(),
        "metadata_refreshed": True,
    }
    add_file_signature(meta, "input", input_path)
    add_file_signature(meta, "template", template_path)
    write_json_atomic(meta_path_for(output_dir, item_id), meta)


def should_process(
    input_path: Path,
    output_path: Path,
    output_dir: Path,
    item_id: int,
    template_path: Optional[Path],
    check_updates: bool,
    force: bool,
) -> bool:
    if force or not output_path.exists():
        return True
    if not check_updates:
        return False
    meta = read_meta(output_dir, item_id)
    input_changed, input_signature = file_changed(meta, "input", input_path)
    template_changed, template_signature = file_changed(meta, "template", template_path)
    if not input_changed and not template_changed:
        return False

    latest_input_mtime = max(input_signature["mtime"], template_signature["mtime"])
    if get_file_mtime(output_path) >= latest_input_mtime:
        refresh_meta(output_dir, item_id, input_path, template_path, meta.get("model"))
        return False

    return True


def scan_work_items(args: argparse.Namespace) -> list[WorkItem]:
    input_dir = resolve_lang_path(args.input_dir, args.lang)
    output_dir = resolve_lang_path(args.output_dir, args.lang)
    template_dir = resolve_lang_path(args.template_dir, args.lang)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    items: list[WorkItem] = []
    for input_path in sorted(input_dir.iterdir(), key=lambda p: (get_id_from_filename(p) is None, p.name)):
        if input_path.suffix.lower() not in {".html", ".htm"}:
            continue
        item_id = get_id_from_filename(input_path)
        if item_id is None:
            continue
        if args.start_id is not None and item_id < args.start_id:
            continue
        if args.end_id is not None and item_id > args.end_id:
            continue

        output_path = output_dir / f"{item_id}.html"
        template_path = None if args.no_template else find_template_path(template_dir, item_id)
        if not should_process(
            input_path=input_path,
            output_path=output_path,
            output_dir=output_dir,
            item_id=item_id,
            template_path=template_path,
            check_updates=args.check_updates,
            force=args.force,
        ):
            continue

        items.append(
            WorkItem(
                item_id=item_id,
                input_path=input_path,
                output_path=output_path,
                template_path=template_path,
            )
        )
    return items


def clean_model_html(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""

    fence_match = re.search(r"```(?:html|HTML)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    doctype_pos = text.lower().find("<!doctype")
    html_pos = text.lower().find("<html")
    table_pos = text.lower().find("<table")
    starts = [p for p in (doctype_pos, html_pos, table_pos) if p >= 0]
    if starts:
        text = text[min(starts) :].strip()

    return text


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


def table_signature(html: str) -> list[tuple[str, int, int, tuple[tuple[str, str, str], ...]]]:
    soup = BeautifulSoup(html, "html.parser")
    signature = []
    for table_index, table in enumerate(soup.find_all("table")):
        rows = table.find_all("tr", recursive=False)
        if not rows:
            tbody = table.find("tbody", recursive=False)
            rows = tbody.find_all("tr", recursive=False) if tbody else table.find_all("tr")
        for row_index, row in enumerate(rows):
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells:
                cells = row.find_all(["td", "th"])
            cell_attrs = tuple(
                (
                    cell.name,
                    cell.get("rowspan", "1"),
                    cell.get("colspan", "1"),
                )
                for cell in cells
            )
            signature.append((str(table_index), row_index, len(cells), cell_attrs))
    return signature


def has_html_table(html: str) -> bool:
    return bool(BeautifulSoup(html, "html.parser").find("table"))


def document_structure_signature(html: str) -> tuple[Any, ...]:
    """Capture non-text DOM structure while allowing instance values to change."""
    soup = BeautifulSoup(html, "html.parser")
    mutable_value_attrs = {"checked", "selected", "value"}

    def normalize_attr(value: Any) -> Any:
        if isinstance(value, list):
            return tuple(str(item) for item in value)
        return str(value)

    def visit(tag: Tag) -> tuple[Any, ...]:
        attrs = tuple(
            sorted(
                (name, normalize_attr(value))
                for name, value in tag.attrs.items()
                if name not in mutable_value_attrs
            )
        )
        children = tuple(visit(child) for child in tag.children if isinstance(child, Tag))
        return tag.name, attrs, children

    return tuple(visit(child) for child in soup.children if isinstance(child, Tag))


def normalize_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def validate_generated_html(source_html: str, generated_html: str) -> tuple[bool, str]:
    if not generated_html:
        return False, "empty response"
    if "```" in generated_html:
        return False, "contains markdown code fence"
    if has_html_table(source_html):
        if not has_html_table(generated_html):
            return False, "table removed"
        if table_signature(source_html) != table_signature(generated_html):
            return False, "table structure changed"
    elif document_structure_signature(source_html) != document_structure_signature(generated_html):
        return False, "document structure changed"

    if normalize_visible_text(source_html) == normalize_visible_text(generated_html):
        return False, "visible text is unchanged"

    return True, ""


def build_messages(source_html: str, template_html: Optional[str]) -> list[dict[str, str]]:
    nonce = f"{int(time.time() * 1000)}-{random.randint(100000, 999999)}"
    system_prompt = (
        "You generate synthetic filled HTML table instances. Return pure HTML only. "
        "Do not use markdown fences, explanations, or comments."
    )

    template_block = ""
    if template_html:
        template_block = (
            "\nUnfilled HTML template for reference. Use it only to understand labels and structure; "
            "do not copy blanks from it:\n"
            f"{template_html}\n"
        )

    user_prompt = f"""Task: create a new filled instance B from the already-filled instance A.

Rules:
1. Preserve the exact HTML/table structure from instance A: do not add, remove, reorder, split, or merge rows/cells/tables.
2. Change filled values to different plausible values. Names, IDs, dates, addresses, numbers, amounts, notes, signatures, selected options, and checked/ticked states should differ from A where applicable.
3. Keep field labels, table titles, column headers, units, punctuation, styles, and attributes unless the attribute represents a selected/checked value.
4. Keep internal consistency: totals should match row values when the table contains calculations; dates should be plausible; signatures should match generated names when applicable.
5. Complete every value. Do not leave placeholders, blanks, markdown, or explanatory text.
6. Return only the final HTML for instance B.

Randomization nonce: {nonce}
{template_block}
Already-filled instance A:
{source_html}

Return filled instance B HTML:
"""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def call_model_with_retries(
    client: Any,
    args: argparse.Namespace,
    source_html: str,
    template_html: Optional[str],
) -> str:
    last_error = ""
    for attempt in range(1, args.max_retries + 1):
        try:
            completion = client.chat.completions.create(
                model=args.model,
                messages=build_messages(source_html, template_html),
            )
            raw = extract_llm_content(completion)
            html = clean_model_html(raw or "")
            valid, reason = validate_generated_html(source_html, html)
            if valid:
                return html
            last_error = reason
        except Exception as exc:
            last_error = str(exc)

        if attempt < args.max_retries:
            time.sleep(min(0.5 * (1.5 ** min(attempt, 8)), 8.0))

    raise RuntimeError(f"failed after {args.max_retries} attempts: {last_error}")


def process_item(item: WorkItem, args: argparse.Namespace, output_dir: Path) -> None:
    global processed_count, error_count, skipped_count

    if item.output_path.exists() and not args.force and not args.check_updates:
        with count_lock:
            skipped_count += 1
        return

    try:
        source_html = item.input_path.read_text(encoding="utf-8")
        template_html = item.template_path.read_text(encoding="utf-8") if item.template_path else None
        client = create_client(args)
        generated_html = call_model_with_retries(client, args, source_html, template_html)
        item.output_path.write_text(generated_html, encoding="utf-8")
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

    output_dir = resolve_lang_path(args.output_dir, args.lang)
    input_dir = resolve_lang_path(args.input_dir, args.lang)
    template_dir = resolve_lang_path(args.template_dir, args.lang)

    print(f"Language: {args.lang.upper()}")
    print(f"Input filled-A HTML dir: {input_dir}")
    print(f"Template dir: {template_dir} {'(disabled)' if args.no_template else ''}")
    print(f"Output filled-B HTML dir: {output_dir}")
    print(f"Model: {args.model}")

    try:
        items = scan_work_items(args)
    except Exception as exc:
        print(f"Error scanning input files: {exc}")
        return 1

    print(f"\n{'=' * 60}")
    print(f"ID range: {args.start_id if args.start_id is not None else 'start'} - {args.end_id if args.end_id is not None else 'end'}")
    print(f"To be processed: {len(items)}")
    print(f"{'=' * 60}\n")

    if not items:
        print("No data needs processing.")
        return 0

    start = time.time()
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_item = {executor.submit(process_item, item, args, output_dir): item for item in items}
        total = len(items)
        completed = 0
        for future in as_completed(future_to_item):
            completed += 1
            future.result()
            if completed % 10 == 0 or completed == total:
                print(f"Progress: {completed}/{total} ({completed * 100 // total}%) | Errors: {error_count}")

    elapsed = time.time() - start
    print("\nInstance-B HTML generation completed!")
    print(f"Total attempted: {len(items)}")
    print(f"Successful saves: {processed_count}")
    print(f"Errors: {error_count}")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"Results saved in: {output_dir}")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
