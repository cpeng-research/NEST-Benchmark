#!/usr/bin/env python3
"""
Step 4: Generate Context (Plain Text) from Filled HTML

Features:
1. Reads filled HTML files from workflow/3-filled_html-a/data/
2. Uses LLM to convert HTML table content into fluent narrative plain text
3. Saves generated context as individual .txt files in workflow/4-context-a/data/
4. Supports processing data within a specified ID range
5. Automatically skips files that already exist in output directory (resume-from-breakpoint)
6. Tracks input file modification times for smart reprocessing
7. Supports --check-updates mode to reprocess if input files changed
8. Uses async concurrency for high throughput

Usage:
1. Process all data:
   python workflow/4-context-a/step4_gen_context.py

2. Process a specified ID range (e.g., 87-88):
   python workflow/4-context-a/step4_gen_context.py --start_id 87 --end_id 88

3. Check for updates and reprocess changed files:
   python workflow/4-context-a/step4_gen_context.py --check-updates

Notes:
- Always run from project root directory
- Filenames should be numeric (e.g., 87.html, 88.html)
- Each HTML file will be processed independently
- Use --check-updates to reprocess files whose inputs have been modified
"""

from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

from tqdm import tqdm

try:
    from openai import AsyncOpenAI
except ModuleNotFoundError:
    AsyncOpenAI = None  # type: ignore[assignment]


# ================= Configuration Parameters =================
MAX_WORKERS = 10           # Number of concurrent threads

# Language selection (en or zh)
LANGUAGE = None  # None means process both en and zh; can be overridden by --lang

# Input/Output Directories (relative to project root)
INPUT_HTML_DIR = "workflow/3-filled_html-a/data_{lang}"    # Directory containing filled HTML files
OUTPUT_CONTEXT_DIR = "workflow/4-context-a/data_{lang}"    # Directory to save generated context files

# Check updates mode
CHECK_UPDATES = True  # If True, reprocess files whose inputs have been modified

# Default parameters
DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_CONCURRENCY = 10
DEFAULT_MAX_RETRIES = 5
SUPPORTED_LANGUAGES = ("en", "zh")

SYSTEM_PROMPT = (
    "Convert all table content into fluent narrative plain text without changing the original meaning. "
    "You may add minimal connective wording to make the narrative natural, but you must stay faithful to the original table content. "
    "For example, if the table field 'Job Position' is 'None', you must keep it as 'None' rather than changing it to 'No'. "
    "Generate background/contextual information as a paragraph, and do not reveal or imply that the source is a table. "
    "Every piece of content that appears in the table must be included. "
    "Do not include the table title. "
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Step 4: Generate context (plain text) from filled HTML tables. "
            "Converts HTML table content into fluent narrative text using LLM."
        )
    )
    parser.add_argument(
        "--start_id",
        type=int,
        default=None,
        help="Start ID for processing range (optional).",
    )
    parser.add_argument(
        "--end_id",
        type=int,
        default=None,
        help="End ID for processing range (optional).",
    )
    parser.add_argument(
        "--check-updates",
        action="store_true",
        default=True,
        help="Check if input files have been modified and reprocess if needed.",
    )
    parser.add_argument(
        "--no-check-updates",
        dest="check_updates",
        action="store_false",
        help="Skip update checks and only process missing outputs.",
    )
    parser.add_argument(
        "--lang",
        choices=["en", "zh"],
        default=None,
        help="Language selection: 'en' for English or 'zh' for Chinese. If omitted, both are processed.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model name to use (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"Sampling temperature (default: {DEFAULT_TEMPERATURE}).",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=DEFAULT_MAX_CONCURRENCY,
        help=f"Maximum concurrent API calls (default: {DEFAULT_MAX_CONCURRENCY}).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Max retries per failed call (default: {DEFAULT_MAX_RETRIES}).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY"),
        help="API key (default: OPENAI_API_KEY environment variable).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        help="Base URL for OpenAI-compatible endpoint.",
    )
    return parser.parse_args()


def get_id_from_filename(filename: str) -> int | None:
    """Extract numeric ID from filename (e.g., '87.html' -> 87)."""
    try:
        name_without_ext = Path(filename).stem
        return int(name_without_ext)
    except ValueError:
        return None


def get_file_mtime(filepath: str) -> float:
    """Get file modification time as timestamp."""
    try:
        return os.path.getmtime(filepath)
    except OSError:
        return 0.0


def get_file_size(filepath: str) -> int:
    try:
        return os.path.getsize(filepath)
    except OSError:
        return 0


def get_file_sha256(filepath: str) -> str:
    digest = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def add_file_signature(meta_data: Dict[str, Any], prefix: str, filepath: str) -> None:
    meta_data[f"{prefix}_mtime"] = get_file_mtime(filepath)
    meta_data[f"{prefix}_size"] = get_file_size(filepath)
    meta_data[f"{prefix}_sha256"] = get_file_sha256(filepath)


def file_changed(meta: Dict[str, Any], prefix: str, filepath: str) -> tuple[bool, Dict[str, Any]]:
    current = {
        "mtime": get_file_mtime(filepath),
        "size": get_file_size(filepath),
    }
    previous_mtime = meta.get(f"{prefix}_mtime")
    previous_size = meta.get(f"{prefix}_size")
    previous_sha256 = meta.get(f"{prefix}_sha256")

    if previous_mtime == current["mtime"] and previous_size == current["size"]:
        current["sha256"] = previous_sha256
        return False, current

    current["sha256"] = get_file_sha256(filepath)
    if previous_sha256 is not None:
        return current["sha256"] != previous_sha256, current

    if previous_mtime is None:
        return True, current
    return current["mtime"] > float(previous_mtime), current


def write_json_atomic(filepath: str, data: Any) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp_path = f"{filepath}.tmp.{os.getpid()}.{id(data)}"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, filepath)


def id_in_range(item_id: int, start_id: int | None, end_id: int | None) -> bool:
    if start_id is not None and item_id < start_id:
        return False
    if end_id is not None and item_id > end_id:
        return False
    return True


def refresh_meta(fid: int, input_path: str, meta_path: str) -> None:
    meta_data = {
        "id": fid,
        "processed_at": time.time(),
        "metadata_refreshed": True,
    }
    add_file_signature(meta_data, "input", input_path)
    write_json_atomic(meta_path, meta_data)


def meta_path_for(output_dir: str, item_id: int) -> str:
    cache_dir = os.path.join(output_dir, "cache")
    cache_path = os.path.join(cache_dir, f".meta_{item_id}.json")
    legacy_path = os.path.join(output_dir, f".meta_{item_id}.json")
    if not os.path.exists(cache_path) and os.path.exists(legacy_path):
        os.makedirs(cache_dir, exist_ok=True)
        os.replace(legacy_path, cache_path)
    return cache_path


def scan_html_files(start_id: int | None = None, end_id: int | None = None) -> List[Dict[str, Any]]:
    """
    Scan INPUT_HTML_DIR for HTML files.
    Check OUTPUT_CONTEXT_DIR to skip already processed files.
    If CHECK_UPDATES is True, also checks if input files have been modified.
    Returns list of dicts with id, input_path, output_path.
    """
    processed_ids = set()
    needs_reprocess = set()  # IDs that need reprocessing due to input changes
    
    # 1. Scan Output Directory to find already completed items
    if os.path.exists(OUTPUT_CONTEXT_DIR):
        for f in os.listdir(OUTPUT_CONTEXT_DIR):
            if f.lower().endswith('.txt'):
                fid = get_id_from_filename(f)
                if fid is not None:
                    processed_ids.add(fid)
    
    # 2. Scan Input HTML Directory
    if not os.path.exists(INPUT_HTML_DIR):
        raise FileNotFoundError(f"Input HTML directory not found: {INPUT_HTML_DIR}")
    
    html_files = {}
    for f in os.listdir(INPUT_HTML_DIR):
        if f.lower().endswith('.html'):
            fid = get_id_from_filename(f)
            if fid is not None and id_in_range(fid, start_id, end_id):
                html_files[fid] = os.path.join(INPUT_HTML_DIR, f)
    
    # 3. Check for updates if in check-updates mode
    if CHECK_UPDATES and os.path.exists(OUTPUT_CONTEXT_DIR):
        for fid in processed_ids:
            if fid in html_files:
                input_path = html_files[fid]
                # Get metadata file path (stores input mtime)
                meta_path = meta_path_for(OUTPUT_CONTEXT_DIR, fid)
                
                # Check if we have recorded metadata
                meta = {}
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, 'r', encoding='utf-8') as mf:
                            meta = json.load(mf)
                    except (json.JSONDecodeError, IOError):
                        pass
                
                changed, input_signature = file_changed(meta, "input", input_path)
                if changed:
                    output_path = os.path.join(OUTPUT_CONTEXT_DIR, f"{fid}.txt")
                    output_mtime = get_file_mtime(output_path)
                    if output_mtime >= input_signature["mtime"]:
                        try:
                            refresh_meta(fid, input_path, meta_path)
                            print(f"[Update Check] ID {fid}: Metadata refreshed; output is newer than input")
                        except IOError as e:
                            needs_reprocess.add(fid)
                            print(f"[Update Check] ID {fid}: Metadata refresh failed ({e}), will reprocess")
                    else:
                        needs_reprocess.add(fid)
                        print(f"[Update Check] ID {fid}: Input content changed, will reprocess")
    
    # 4. Exclude processed ones (unless they need reprocessing) and build dataset list
    dataset_list = []
    for fid in sorted(html_files.keys()):
        if fid in processed_ids and fid not in needs_reprocess:
            continue  # Skip already processed (and not needing update)
        
        dataset_list.append({
            "id": fid,
            "input_path": html_files[fid],
            "output_path": os.path.join(OUTPUT_CONTEXT_DIR, f"{fid}.txt"),
            "needs_reprocess": fid in needs_reprocess,
        })
    
    return dataset_list


def ensure_output_dir() -> None:
    """Create output directory if it doesn't exist."""
    if not os.path.exists(OUTPUT_CONTEXT_DIR):
        os.makedirs(OUTPUT_CONTEXT_DIR)
    os.makedirs(os.path.join(OUTPUT_CONTEXT_DIR, "cache"), exist_ok=True)


def extract_llm_content(response: Any) -> str | None:
    """Extract message content from OpenAI SDK, dict-like, or string responses."""
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
                return normalize_content(content)

        content = response.get("content")
        if content is not None:
            return normalize_content(content)

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
            return normalize_content(content)

    content = getattr(response, "content", None)
    if content is not None:
        return normalize_content(content)

    return None


def normalize_content(content: Any) -> str | None:
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

# System prompt.
SYSTEM_PROMPT = """Convert all table content into fluent narrative plain text without changing the original meaning. You may add minimal connective wording to make the narrative natural, but you must stay faithful to the original table content. For example, if the table field 'Job Position' is 'None', you must keep it as 'None' rather than changing it to 'No'. Generate background/contextual information as a paragraph, and do not reveal or imply that the source is a table. Every piece of content that appears in the table must be included. Do not include the table title."""
async def generate_context(
    client: AsyncOpenAI,
    model: str,
    html_content: str,
    temperature: float,
    semaphore: asyncio.Semaphore,
    max_retries: int,
) -> str:
    """Generate plain text context from HTML content using LLM."""
    if not html_content:
        return ""
    
    attempt = 0
    delay = 1.0
    
    while True:
        try:
            async with semaphore:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": html_content},
                    ],
                    temperature=temperature,
                )
            return (extract_llm_content(response) or "").strip()
        except Exception as exc:
            attempt += 1
            if attempt > max_retries:
                raise RuntimeError(
                    f"Failed to generate context after {max_retries} retries: {exc}"
                ) from exc
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


async def process_single_file(
    item_data: Dict[str, Any],
    client: AsyncOpenAI,
    model: str,
    temperature: float,
    semaphore: asyncio.Semaphore,
    max_retries: int,
    progress: tqdm,
) -> bool:
    """Process a single HTML file: Read -> Generate Context -> Write."""
    item_id = item_data["id"]
    input_path = item_data["input_path"]
    output_path = item_data["output_path"]
    needs_reprocess = item_data.get("needs_reprocess", False)
    
    # Double check if output file exists (race condition protection)
    if os.path.exists(output_path) and not needs_reprocess:
        print(f"[ID {item_id}] Already exists in output, skipping.")
        progress.update(1)
        return True
    
    try:
        # Read HTML file
        with open(input_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Generate context
        context_text = await generate_context(
            client=client,
            model=model,
            html_content=html_content,
            temperature=temperature,
            semaphore=semaphore,
            max_retries=max_retries,
        )
        
        # Save to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(context_text)
        
        # Save metadata (input file modification time) for update tracking
        meta_path = meta_path_for(OUTPUT_CONTEXT_DIR, item_id)
        meta_data = {
            "id": item_id,
            "processed_at": time.time()
        }
        add_file_signature(meta_data, "input", input_path)
        try:
            write_json_atomic(meta_path, meta_data)
        except IOError as e:
            print(f"[Warning] Failed to save metadata for ID {item_id}: {e}")
        
        print(f"[ID {item_id}] Completed -> {output_path}")
        progress.update(1)
        return True
        
    except Exception as e:
        print(f"[ID {item_id}] Error: {e}")
        progress.update(1)
        return False


async def main_async(args: argparse.Namespace) -> None:
    """Main async function to process all HTML files."""
    # Set global variables from args
    global CHECK_UPDATES, LANGUAGE, INPUT_HTML_DIR, OUTPUT_CONTEXT_DIR
    CHECK_UPDATES = args.check_updates
    LANGUAGE = args.lang
    
    # Initialize paths with language
    INPUT_HTML_DIR = INPUT_HTML_DIR.format(lang=LANGUAGE)
    OUTPUT_CONTEXT_DIR = OUTPUT_CONTEXT_DIR.format(lang=LANGUAGE)
    
    print(f"Language: {LANGUAGE.upper()}")
    print(f"Input Dir: {INPUT_HTML_DIR}")
    print(f"Output Dir: {OUTPUT_CONTEXT_DIR}")
    
    # Ensure output directory exists
    ensure_output_dir()
    
    # Scan HTML files
    print("Scanning HTML files...")
    try:
        dataset = scan_html_files(args.start_id, args.end_id)
        print(f"Found {len(dataset)} HTML files to process.")
    except Exception as e:
        print(f"Error scanning directories: {e}")
        sys.exit(1)
    
    # Filter by ID range if specified
    filtered_dataset = []
    for item in dataset:
        item_id = item["id"]
        if args.start_id is not None and item_id < args.start_id:
            continue
        if args.end_id is not None and item_id > args.end_id:
            continue
        filtered_dataset.append(item)
    
    items_to_process = filtered_dataset
    
    # Show info
    id_range_str = f"ID range: {args.start_id if args.start_id is not None else 'start'} - {args.end_id if args.end_id is not None else 'end'}"
    print(f"\n{'='*60}")
    print(f"Config: {id_range_str}")
    print(f"To be processed: {len(items_to_process)}")
    print(f"Output Dir: {OUTPUT_CONTEXT_DIR}")
    print(f"{'='*60}\n")
    
    if len(items_to_process) == 0:
        print("No data needs processing!")
        sys.exit(0)
    
    # Check API key
    if args.api_key is None:
        raise ValueError("API key missing. Pass --api-key or set OPENAI_API_KEY.")
    
    if AsyncOpenAI is None:
        raise RuntimeError("Missing dependency: install openai with `pip install openai`.")

    # Create client
    client = AsyncOpenAI(base_url=args.base_url, api_key=args.api_key)
    semaphore = asyncio.Semaphore(args.max_concurrency)
    
    # Create progress bar
    progress = tqdm(
        total=len(items_to_process),
        desc="Generating context",
        unit="file",
        mininterval=0.2,
    )
    
    # Process all files concurrently
    tasks = [
        asyncio.create_task(
            process_single_file(
                item_data=item,
                client=client,
                model=args.model,
                temperature=args.temperature,
                semaphore=semaphore,
                max_retries=args.max_retries,
                progress=progress,
            )
        )
        for item in items_to_process
    ]
    
    try:
        results = await asyncio.gather(*tasks)
    finally:
        progress.close()

    failed_count = sum(not result for result in results)
    
    print("\nContext generation completed!")
    print(f"Total attempted: {len(items_to_process)}")
    print(f"Succeeded: {len(items_to_process) - failed_count}")
    print(f"Failed: {failed_count}")
    print(f"Results saved in: {OUTPUT_CONTEXT_DIR}")
    if failed_count:
        raise RuntimeError(f"{failed_count} context file(s) failed")


def main() -> None:
    """Entry point."""
    args = parse_args()
    if args.lang is None:
        exit_code = 0
        for lang in SUPPORTED_LANGUAGES:
            print(f"\n{'='*60}\nRunning language: {lang.upper()}\n{'='*60}")
            result = subprocess.run([sys.executable, __file__, *sys.argv[1:], "--lang", lang])
            exit_code = max(exit_code, result.returncode)
        raise SystemExit(exit_code)

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
