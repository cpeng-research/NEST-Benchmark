"""
Step 2: JSON Filling Script

Features:
1. Reads unfilled JSON files from input directory
2. Uses LLM to fill all JSON values with no missing fields
3. Saves filled JSON to output directory as individual files
4. Supports processing data within a specified ID range
5. Automatically skips files that already exist in output directory (resume-from-breakpoint)
6. Tracks input file modification times for smart reprocessing
7. Supports --check-updates mode to reprocess if input files changed
8. Uses multi-threaded concurrency to improve throughput

Usage:
1. Process all data (English):
   python workflow/2-filled_json-a/step2_fill_json.py --lang en

2. Process all data (Chinese):
   python workflow/2-filled_json-a/step2_fill_json.py --lang zh

3. Process a specified ID range (e.g., 1-50):
   python workflow/2-filled_json-a/step2_fill_json.py --lang en --start_id 1 --end_id 50

4. Check for updates and reprocess changed files (enabled by default):
   python workflow/2-filled_json-a/step2_fill_json.py --lang en

Notes:
- Always run from project root directory
- Filenames should be numeric (e.g., 1.json, 2.json).
- Each JSON file will be processed independently.
- Update checking is enabled by default; use --no-check-updates to only skip existing outputs
- Language parameter (--lang) is required: use 'en' for English or 'zh' for Chinese
"""
import json
import os
import hashlib
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import threading
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

# ================= Configuration Parameters =================
MAX_WORKERS = 10  # Number of concurrent threads
DEFAULT_MODEL = "gpt-5-mini"
MODEL = DEFAULT_MODEL

# Language selection (en or zh)
LANGUAGE = None  # None means process both en and zh; can be overridden by --lang
SUPPORTED_LANGUAGES = ("en", "zh")

# Input/Output Directories (relative to project root)
INPUT_JSON_DIR = "workflow/1-annotated_json/data_{lang}"   # Directory containing unfilled JSON files
OUTPUT_JSON_DIR = "workflow/2-filled_json-a/data_{lang}"   # Directory to save filled JSON files

# ID range selection (None means process all found files)
START_ID = None 
END_ID = None   

# Check updates mode
CHECK_UPDATES = True  # If True, reprocess files whose inputs have been modified

# Global lock for console printing
print_lock = Lock()
client_create_lock = Lock()

# Create client
def create_client():
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependency: install openai with `pip install openai`.") from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    kwargs = {"api_key": api_key}
    if os.getenv("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]

    with client_create_lock:
        return OpenAI(**kwargs)

def extract_llm_content(response):
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

def normalize_content(content):
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

# Parse command-line arguments
def parse_args():
    """Parse command-line arguments"""
    global START_ID, END_ID, CHECK_UPDATES, LANGUAGE, MODEL
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--start_id' and i + 1 < len(args):
            try:
                START_ID = int(args[i + 1])
            except ValueError:
                print(f"Invalid start_id: {args[i+1]}")
            i += 2
        elif args[i] == '--end_id' and i + 1 < len(args):
            try:
                END_ID = int(args[i + 1])
            except ValueError:
                print(f"Invalid end_id: {args[i+1]}")
            i += 2
        elif args[i] == '--check-updates':
            CHECK_UPDATES = True
            i += 1
        elif args[i] == '--no-check-updates':
            CHECK_UPDATES = False
            i += 1
        elif args[i] == '--lang' and i + 1 < len(args):
            lang = args[i + 1].lower()
            if lang in SUPPORTED_LANGUAGES:
                LANGUAGE = lang
            else:
                print(f"Invalid language: {args[i+1]}. Use 'en' or 'zh'.")
            i += 2
        elif args[i] == '--model' and i + 1 < len(args):
            MODEL = args[i + 1]
            i += 2
        else:
            i += 1

def run_all_languages_if_needed():
    if LANGUAGE is not None:
        return

    exit_code = 0
    for lang in SUPPORTED_LANGUAGES:
        print(f"\n{'='*60}\nRunning language: {lang.upper()}\n{'='*60}")
        result = subprocess.run([sys.executable, __file__, *sys.argv[1:], "--lang", lang])
        exit_code = max(exit_code, result.returncode)
    sys.exit(exit_code)

# Helper to get file modification time
def get_file_mtime(filepath: str) -> float:
    """Get file modification time as timestamp."""
    try:
        return os.path.getmtime(filepath)
    except OSError:
        return 0.0

def get_file_size(filepath: str) -> int:
    """Get file size in bytes."""
    try:
        return os.path.getsize(filepath)
    except OSError:
        return 0

def get_file_sha256(filepath: str) -> str:
    """Calculate SHA-256 by streaming file bytes."""
    digest = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def get_file_signature(filepath: str) -> dict:
    return {
        "mtime": get_file_mtime(filepath),
        "size": get_file_size(filepath),
        "sha256": get_file_sha256(filepath),
    }

def add_file_signature(meta_data: dict, prefix: str, filepath: str) -> None:
    signature = get_file_signature(filepath)
    meta_data[f"{prefix}_mtime"] = signature["mtime"]
    meta_data[f"{prefix}_size"] = signature["size"]
    meta_data[f"{prefix}_sha256"] = signature["sha256"]

def file_changed(meta: dict, prefix: str, filepath: str) -> tuple[bool, dict]:
    """Return whether file content changed, using hash when metadata has a prior hash."""
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

def write_json_atomic(filepath: str, data: dict) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp_path = f"{filepath}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp_path, 'w', encoding='utf-8') as mf:
        json.dump(data, mf, ensure_ascii=False, indent=2)
    os.replace(tmp_path, filepath)

def refresh_meta(input_path: str, meta_path: str, item_id: int) -> None:
    """Refresh tracking metadata when an existing output is already newer than input."""
    meta_data = {
        "id": item_id,
        "processed_at": time.time(),
        "metadata_refreshed": True,
    }
    add_file_signature(meta_data, "input", input_path)
    try:
        write_json_atomic(meta_path, meta_data)
    except IOError as e:
        with print_lock:
            print(f"[Warning] Failed to refresh metadata for ID {item_id}: {e}")

def meta_path_for(output_dir: str, item_id: int) -> str:
    cache_dir = os.path.join(output_dir, "cache")
    cache_path = os.path.join(cache_dir, f".meta_{item_id}.json")
    legacy_path = os.path.join(output_dir, f".meta_{item_id}.json")
    if not os.path.exists(cache_path) and os.path.exists(legacy_path):
        os.makedirs(cache_dir, exist_ok=True)
        os.replace(legacy_path, cache_path)
    return cache_path

# Helper to extract ID from filename
def get_id_from_filename(filename):
    try:
        name_without_ext = os.path.splitext(filename)[0]
        return int(name_without_ext)
    except ValueError:
        return None

def id_in_range(item_id: int) -> bool:
    if START_ID is not None and item_id < START_ID:
        return False
    if END_ID is not None and item_id > END_ID:
        return False
    return True

def scan_json_files():
    """
    Scans INPUT_JSON_DIR to find JSON files.
    Checks OUTPUT_JSON_DIR to skip already processed files.
    If CHECK_UPDATES is True, also checks if input files have been modified.
    Returns a list of dicts: {"id": ..., "input_path": ..., "output_path": ...}
    """
    processed_ids = set()
    needs_reprocess = set()  # IDs that need reprocessing due to input changes
    
    # 1. Scan Output Directory to find already completed items
    if os.path.exists(OUTPUT_JSON_DIR):
        for f in os.listdir(OUTPUT_JSON_DIR):
            if f.lower().endswith('.json'):
                fid = get_id_from_filename(f)
                if fid is not None:
                    processed_ids.add(fid)
                    
    # 2. Scan Input JSON Directory
    if not os.path.exists(INPUT_JSON_DIR):
        raise FileNotFoundError(f"Input JSON directory not found: {INPUT_JSON_DIR}")
        
    json_files = {}
    for f in os.listdir(INPUT_JSON_DIR):
        if f.lower().endswith('.json'):
            fid = get_id_from_filename(f)
            if fid is not None:
                json_files[fid] = os.path.join(INPUT_JSON_DIR, f)
    
    # 3. Check for updates if in check-updates mode
    if CHECK_UPDATES and os.path.exists(OUTPUT_JSON_DIR):
        for fid in processed_ids:
            if not id_in_range(fid):
                continue
            if fid in json_files:
                input_path = json_files[fid]
                output_path = os.path.join(OUTPUT_JSON_DIR, f"{fid}.json")
                
                # Get metadata file path (stores input mtime)
                meta_path = meta_path_for(OUTPUT_JSON_DIR, fid)
                
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
                    output_mtime = get_file_mtime(output_path)
                    if output_mtime >= input_signature["mtime"]:
                        refresh_meta(input_path, meta_path, fid)
                    else:
                        needs_reprocess.add(fid)
                        with print_lock:
                            print(f"[Update Check] ID {fid}: Input content changed, will reprocess")
    
    # 4. Exclude processed ones (unless they need reprocessing) and build dataset list
    dataset_list = []
    for fid in sorted(json_files.keys()):
        if not id_in_range(fid):
            continue
        if fid in processed_ids and fid not in needs_reprocess:
            continue  # Skip already processed (and not needing update)
            
        dataset_list.append({
            "id": fid,
            "input_path": json_files[fid],
            "output_path": os.path.join(OUTPUT_JSON_DIR, f"{fid}.json"),
            "needs_reprocess": fid in needs_reprocess,
        })
        
    return dataset_list

def ensure_output_dir():
    if not os.path.exists(OUTPUT_JSON_DIR):
        os.makedirs(OUTPUT_JSON_DIR)
    os.makedirs(os.path.join(OUTPUT_JSON_DIR, "cache"), exist_ok=True)

# Parse arguments
parse_args()
run_all_languages_if_needed()

# Initialize paths with language
INPUT_JSON_DIR = INPUT_JSON_DIR.format(lang=LANGUAGE)
OUTPUT_JSON_DIR = OUTPUT_JSON_DIR.format(lang=LANGUAGE)

print(f"Language: {LANGUAGE.upper()}")
print(f"Input Dir: {INPUT_JSON_DIR}")
print(f"Output Dir: {OUTPUT_JSON_DIR}")

# Ensure output directory exists
ensure_output_dir()

# Load dataset structure
print("Scanning JSON files...")
try:
    dataset = scan_json_files()
    print(f"Found {len(dataset)} JSON files to process.")
except Exception as e:
    print(f"Error scanning directories: {e}")
    sys.exit(1)

# Further filter by ID range if specified
filtered_dataset = []
for item in dataset:
    item_id = item["id"]
    if START_ID is not None and item_id < START_ID:
        continue
    if END_ID is not None and item_id > END_ID:
        continue
    filtered_dataset.append(item)

items_to_process = filtered_dataset

# Show info
id_range_str = f"ID range: {START_ID if START_ID is not None else 'start'} - {END_ID if END_ID is not None else 'end'}"
print(f"\n{'='*60}")
print(f"Config: {id_range_str}")
print(f"To be processed: {len(items_to_process)}")
print(f"Output Dir: {OUTPUT_JSON_DIR}")
print(f"{'='*60}\n")

if len(items_to_process) == 0:
    print("No data needs processing!")
    sys.exit(0)

# Statistics
processed_count = 0
error_count = 0
count_lock = Lock()

def process_single_json(item_data):
    """Process a single JSON file: Read -> LLM Fill -> Write"""
    global processed_count, error_count
    
    item_id = item_data["id"]
    input_path = item_data["input_path"]
    output_path = item_data["output_path"]
    needs_reprocess = item_data.get("needs_reprocess", False)
    
    # Double check if output file exists (race condition protection)
    if os.path.exists(output_path) and not needs_reprocess:
        with print_lock:
            print(f"[Thread {threading.current_thread().name}] ID {item_id} already exists in output, skipping.")
        return

    try:
        # Read input JSON file
        with open(input_path, 'r', encoding='utf-8') as f:
            standardized_json = f.read()
            
        client = create_client()
        
        # Call LLM to fill JSON
        max_retries = 50
        retries = 0
        json_data = None
        
        while retries < max_retries:
            try:
                completion = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": """You are a strict JSON data processing assistant. Your task is to populate the JSON data provided by the user while absolutely maintaining its original key names and hierarchical structure.
Execution Rules:
General filling: Complete all fillable value contents.
Enum selection: When a "choices" field is present, the "value" must be strictly extracted as one or more exact strings from the "choices" array.

Special option extension: If "choices" includes "Other" (or similar expressions) and you need to input a special case not in the list (e.g., "Probation Extension"), please input the specific information directly into the "value" field.
Example: If "choices": ["Approve", "Reject", "Other"], and you need to fill in "Extension", please output "value": "Extension".
Note: Output ONLY the final synthesized JSON code. Do not output any additional explanatory text!:"""},
                        {"role": "user", "content": f"JSON:{standardized_json}"}
                    ]
                )
                json_data = extract_llm_content(completion)
                if json_data is None:
                    raise Exception("LLM returned None content")
                break  # Success: exit retry loop
            except Exception as e:
                retries += 1
                if retries >= max_retries:
                    raise e
                time.sleep(min(2 ** retries, 3))  # Exponential backoff
                
        # Save filled JSON to file
        if json_data is None:
            raise Exception("JSON data is None after retries")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(json_data)
        
        # Save metadata (input file modification time) for update tracking
        meta_path = meta_path_for(OUTPUT_JSON_DIR, item_id)
        meta_data = {
            "id": item_id,
            "processed_at": time.time()
        }
        add_file_signature(meta_data, "input", input_path)
        try:
            write_json_atomic(meta_path, meta_data)
        except IOError as e:
            with print_lock:
                print(f"[Warning] Failed to save metadata for ID {item_id}: {e}")
            
        with print_lock:
            print(f"[Thread {threading.current_thread().name}] Completed ID {item_id} -> {output_path}")
            
        with count_lock:
            processed_count += 1
            
    except Exception as e:
        with print_lock:
            print(f"[Thread {threading.current_thread().name}] Error processing ID {item_id}: {e}")
        with count_lock:
            error_count += 1

# Start Processing
print(f"Starting concurrent JSON filling using {MAX_WORKERS} threads...")

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    future_to_item = {executor.submit(process_single_json, item_data): item_data for item_data in items_to_process}
    
    completed = 0
    total = len(items_to_process)
    
    for future in as_completed(future_to_item):
        completed += 1
        
        # Show progress
        if completed % 10 == 0 or completed == total:
            print(f"Progress: {completed}/{total} ({completed*100//total}%) | Errors: {error_count}")

print("\nJSON filling completed!")
print(f"Total attempted: {len(items_to_process)}")
print(f"Successful saves: {processed_count}")
print(f"Errors: {error_count}")
print(f"Results saved in: {OUTPUT_JSON_DIR}")
