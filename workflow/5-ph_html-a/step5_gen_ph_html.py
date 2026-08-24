#!/usr/bin/env python3
"""
Step 5: Generate Placeholder HTML from Filled HTML

Features:
1. Reads filled HTML files from workflow/3-filled_html-a/data/
2. Uses LLM to replace filled values with placeholders in format [FieldName]
3. Saves placeholder HTML as individual .html files in workflow/5-ph_html-a/data/
4. Supports processing data within a specified ID range
5. Automatically skips files that already exist in output directory (resume-from-breakpoint)
6. Tracks input file modification times for smart reprocessing
7. Supports --check-updates mode to reprocess if input files changed
8. Uses multi-threaded concurrency to improve throughput

Usage:
1. Process all data:
   python workflow/5-ph_html-a/step5_gen_ph_html.py

2. Process a specified ID range (e.g., 87-88):
   python workflow/5-ph_html-a/step5_gen_ph_html.py --start_id 87 --end_id 88

3. Check for updates and reprocess changed files:
   python workflow/5-ph_html-a/step5_gen_ph_html.py --check-updates

Notes:
- Always run from project root directory
- Filenames should be numeric (e.g., 87.html, 88.html)
- Each HTML file will be processed independently
- Use --check-updates to reprocess files whose inputs have been modified
"""
from dotenv import load_dotenv
load_dotenv()
import hashlib
import html
import json
import os
import re
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from openai import OpenAI, BadRequestError
from tqdm import tqdm
import sys
from bs4 import BeautifulSoup, Comment


# ================= Configuration Parameters =================
# Language selection (en or zh)
LANGUAGE = None  # None means process both en and zh; can be overridden by --lang
SUPPORTED_LANGUAGES = ("en", "zh")

# Input/Output Directories (relative to project root)
# Note: These are templates and will be formatted with the selected language in main()
INPUT_HTML_DIR_TEMPLATE = "workflow/3-filled_html-a/data_{lang}"
TEMPLATE_HTML_DIR_TEMPLATE = "workflow/0-html_template/data_{lang}"
OUTPUT_PH_DIR_TEMPLATE = "workflow/5-ph_html-a/data_{lang}"

# Actual directories (initialized in main)
INPUT_HTML_DIR = "workflow/3-filled_html-a/data_en"
TEMPLATE_HTML_DIR = "workflow/0-html_template/data_en"
OUTPUT_PH_DIR = "workflow/5-ph_html-a/data_en"

# Processing parameters
DEFAULT_MODEL = "gpt-5"
MODEL = DEFAULT_MODEL
MAX_WORKERS = 10           # Number of concurrent threads; adjust based on API limits
MAX_RETRIES = 50           # Maximum retry attempts per item
SAVE_INTERVAL = 1          # Save after every N processed items (1 means save after every item)

# Check updates mode
CHECK_UPDATES = True       # If True, reprocess files whose inputs have been modified

# Global locks to protect shared resources
print_lock = Lock()
save_lock = Lock()
client_create_lock = Lock()

# System prompt for placeholder generation
SYSTEM_PROMPT = """Below is a text generation task.
**Task**:
In the filled form, replace each text content that has been filled with a concrete value with the corresponding field name as a placeholder. The placeholder format is [FieldName]. The field name must come from the most relevant visible label/header text at that position in the input HTML table.
***Main task***: Find the filled value positions in the input HTML form and insert placeholders there. The placeholder content is the key, i.e., the exact visible field label/header. The field name refers to the innermost label text. For example, <td>Name: Xiao Ming</td> becomes <td>Name: [Name]</td>. (For example, for the "Family Status" field, the child field is "Member", so the field name should be "Member" without considering the parent field name. Example: <td> Family Info </td><td> Member: Sister</td> becomes <td> Family Info </td><td> Member: [Member]</td>. Focus only on the innermost label text. If you truly do not understand, use a connector form instead, e.g., [FamilyMember-Member].)

***Critical naming rule***:
The text inside every placeholder must be copied from the original visible label/header text in the input table. Preserve the original language, script, wording, spacing, punctuation, and capitalization. Do NOT translate, romanize, paraphrase, summarize, camelCase, or invent English names for non-English labels.
- Chinese example: <td>姓名</td><td>张三</td> must become <td>姓名</td><td>[姓名]</td>. It must NOT become [Name].
- Chinese example: <td>员工编号</td><td>HR2026-0457</td> must become <td>员工编号</td><td>[员工编号]</td>. It must NOT become [EmployeeID].
- Repeated Chinese row example: if the visible column header is 姓名, use [姓名1], [姓名2], etc. Do NOT use [Name1], [Name2].
- Connector names, if truly needed, must also use exact visible labels, e.g. [家庭成员-姓名1], not [FamilyMember-Name1].

***Special Task 1***: For checkboxes or other selectable types (anything selectable counts): for example, Is Married: <input type="checkbox" checked>YES <input type="checkbox">NO becomes Is Married: [Is Married]<input type="checkbox" checked>YES [Is Married]<input type="checkbox">NO (as long as <input type="checkbox"> exists, you should insert the corresponding placeholder [FieldName] before or after the data value). Therefore, when a checkbox group has a common title, use that exact visible title as the field name. Chinese example: 是否已婚：<input type="checkbox" checked>是 <input type="checkbox">否 becomes 是否已婚：[是否已婚]<input type="checkbox" checked>是 [是否已婚]<input type="checkbox">否.
***Special Task 2***: Repeated fields (e.g., row data in a table): If data appears in repeated rows, add a numeric index starting from 1 after the field name to distinguish different rows. For example: [FamilyMember1]...[FamilyMember2]...[FamilyMember3]...[...]. (You may also use "-" to connect parent and child field names, e.g., [FamilyStatus-FamilyMember1]...[FamilyStatus-FamilyMember2]...[FamilyStatus-FamilyMember3]...[...]). Note: If there are clear row headers on the left and clear column headers, and each row's data is a repeated instance of that column header, then use [ColumnHeader] plus the index as the field name, e.g., [FamilyMember1], [FamilyMember2].

***All field names (label texts) above refer to the innermost label text. For example: <tr><td> Family Info </td><td colspan="3"> Family Member: [FamilyMember] Related Work: [RelatedWork] </td></tr>. We only look at child fields, not parent fields.***
Also for single-character cases: If it is "Date: Year Month Day" then it is "Date: [Date]". If it only has "Year Month Day", then it is "[Year]Year[Month]Month[Day]Day". That is, the placeholder content must come from the table, not something you invent yourself.
***Important: Field names should remain exactly consistent with the original field names in the table, except that repeated data rows may append numeric indexes.***
Output requirement: Return the final generated HTML code containing placeholders. Do not include code fences or write code."""


def create_client():
    """Create an independent client per thread."""
    kwargs = {}
    if os.getenv("OPENAI_API_KEY"):
        kwargs["api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.getenv("OPENAI_BASE_URL")

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


def get_id_from_filename(filename: str) -> int | None:
    """Extract numeric ID from filename (e.g., '87.html' -> 87)."""
    try:
        name_without_ext = os.path.splitext(filename)[0]
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


def add_file_signature(meta_data: dict, prefix: str, filepath: str) -> None:
    meta_data[f"{prefix}_mtime"] = get_file_mtime(filepath)
    meta_data[f"{prefix}_size"] = get_file_size(filepath)
    meta_data[f"{prefix}_sha256"] = get_file_sha256(filepath)


def file_changed(meta: dict, prefix: str, filepath: str) -> tuple[bool, dict]:
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


def write_json_atomic(filepath: str, data) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp_path = f"{filepath}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, filepath)


def id_in_range(item_id: int, start_id: int | None, end_id: int | None) -> bool:
    if start_id is not None and item_id < start_id:
        return False
    if end_id is not None and item_id > end_id:
        return False
    return True


CJK_PATTERN = re.compile(r'[\u3400-\u9fff]')
PLACEHOLDER_PATTERN = re.compile(r'\[([^\[\]]+)\]')
TAG_PATTERN = re.compile(r'<[^>]+>')
TRAILING_INDEX_PATTERN = re.compile(r'\d+$')


def contains_cjk(text: str) -> bool:
    return bool(CJK_PATTERN.search(text or ""))


def html_to_visible_text(html_content: str) -> str:
    soup = BeautifulSoup(html_content or "", 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    text = soup.get_text(" ")
    return html.unescape(re.sub(r'\s+', ' ', text)).strip()


def normalize_inline_space(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def remove_all_space(text: str) -> str:
    return re.sub(r'\s+', '', text or '')


def normalize_html_fragment(html_fragment: str) -> str:
    return re.sub(r'\s+', ' ', html_fragment or '').strip()


def cell_visible_text(cell) -> str:
    return html_to_visible_text(cell.decode_contents())


def compact_visible_text(cell) -> str:
    return remove_all_space(cell_visible_text(cell))


def has_form_control(cell) -> bool:
    return bool(cell.find(['input', 'select', 'textarea', 'button']))


def get_leaf_cells(html_content: str):
    soup = BeautifulSoup(html_content or "", 'html.parser')
    cells = [
        cell for cell in soup.find_all(['td', 'th'])
        if cell.find('table') is None
    ]
    return soup, cells


def cells_align(template_cells: list, filled_cells: list, output_cells: list) -> bool:
    return len(template_cells) == len(filled_cells) == len(output_cells)


def is_static_template_cell(template_cell, filled_cell) -> bool:
    """
    A static cell is content that already existed in the blank template and
    did not change in the filled HTML. These are labels, headers, row numbers,
    and titles; Step 5 must not turn them into placeholders.
    """
    template_text = compact_visible_text(template_cell)
    if not template_text:
        return False

    if template_text != compact_visible_text(filled_cell):
        return False

    if has_form_control(template_cell) or has_form_control(filled_cell):
        return False

    return True


def replace_cell_contents(target_cell, source_cell) -> None:
    fragment = BeautifulSoup(source_cell.decode_contents(), 'html.parser')
    target_cell.clear()
    for child in list(fragment.contents):
        target_cell.append(child.extract())


def restore_static_template_cells(template_html: str | None, filled_html: str, output_html: str) -> str:
    """
    Programmatic guardrail for Step 5: after the LLM output, restore any cell
    that is unchanged between the blank template and the filled HTML.
    """
    if not template_html:
        return output_html

    _, template_cells = get_leaf_cells(template_html)
    _, filled_cells = get_leaf_cells(filled_html)
    output_soup, output_cells = get_leaf_cells(output_html)

    if not cells_align(template_cells, filled_cells, output_cells):
        return output_html

    changed = False
    for template_cell, filled_cell, output_cell in zip(template_cells, filled_cells, output_cells):
        if not is_static_template_cell(template_cell, filled_cell):
            continue

        if normalize_html_fragment(output_cell.decode_contents()) != normalize_html_fragment(filled_cell.decode_contents()):
            replace_cell_contents(output_cell, filled_cell)
            changed = True

    return str(output_soup) if changed else output_html


def validate_static_cells_against_template(template_html: str | None, filled_html: str, output_html: str) -> str | None:
    if not template_html:
        return None

    _, template_cells = get_leaf_cells(template_html)
    _, filled_cells = get_leaf_cells(filled_html)
    _, output_cells = get_leaf_cells(output_html)

    if not cells_align(template_cells, filled_cells, output_cells):
        return None

    bad_examples = []
    for template_cell, filled_cell, output_cell in zip(template_cells, filled_cells, output_cells):
        if not is_static_template_cell(template_cell, filled_cell):
            continue
        if normalize_html_fragment(output_cell.decode_contents()) == normalize_html_fragment(filled_cell.decode_contents()):
            continue
        if PLACEHOLDER_PATTERN.search(output_cell.decode_contents()):
            bad_examples.append(cell_visible_text(filled_cell))
            if len(bad_examples) >= 8:
                break

    if not bad_examples:
        return None

    examples = ", ".join(repr(text) for text in bad_examples)
    return (
        "Invalid placeholders in static template cells. These cells were "
        f"unchanged from the blank template and should stay as labels/headers: {examples}"
    )


def placeholder_base_parts(name: str) -> list[str]:
    parts = []
    for raw_part in re.split(r'[-/]', name):
        part = TRAILING_INDEX_PATTERN.sub('', raw_part.strip())
        if part:
            parts.append(part)
    return parts or [TRAILING_INDEX_PATTERN.sub('', name.strip())]


def validate_placeholder_names_against_source(input_html: str, output_html: str, label_html: str | None = None) -> str | None:
    """
    Guard against translated placeholder names in Chinese forms.

    Step 5 is LLM-based, so the prompt is the main control. This validator
    catches the common failure mode where a Chinese label such as "姓名" is
    output as an invented English placeholder like [Name].
    """
    label_source_text = html_to_visible_text(label_html if label_html is not None else input_html)
    if not contains_cjk(label_source_text):
        return None

    source_text = html_to_visible_text(input_html)
    compact_source_text = remove_all_space(source_text)
    suspicious = []

    for placeholder_name in PLACEHOLDER_PATTERN.findall(output_html or ""):
        for part in placeholder_base_parts(placeholder_name):
            has_latin = bool(re.search(r'[A-Za-z]', part))
            if not has_latin or contains_cjk(part):
                continue
            normalized_part = normalize_inline_space(part)
            compact_part = remove_all_space(part)
            if (
                part not in source_text
                and normalized_part not in source_text
                and compact_part not in compact_source_text
            ):
                suspicious.append(placeholder_name)
                break

    if not suspicious:
        return None

    examples = ", ".join(f"[{name}]" for name in suspicious[:12])
    return (
        "Invalid placeholder names for a Chinese table. The output appears to "
        "translate original Chinese labels into English placeholder names. "
        "Every placeholder name must be copied verbatim from visible labels in "
        f"the input table. Suspicious examples: {examples}"
    )


def validate_existing_placeholder_file(input_path: str, output_path: str, template_path: str | None = None) -> str | None:
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            input_html = f.read()
        with open(output_path, 'r', encoding='utf-8') as f:
            output_html = f.read()
        template_html = None
        if template_path and os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                template_html = f.read()
    except OSError as e:
        return f"Could not read files for validation: {e}"

    static_issue = validate_static_cells_against_template(template_html, input_html, output_html)
    if static_issue:
        return static_issue

    return validate_placeholder_names_against_source(input_html, output_html, template_html)


def refresh_meta(fid: int, input_path: str, template_path: str | None, meta_path: str) -> None:
    meta_data = {
        "id": fid,
        "processed_at": time.time(),
        "metadata_refreshed": True,
    }
    add_file_signature(meta_data, "input", input_path)
    if template_path and os.path.exists(template_path):
        add_file_signature(meta_data, "template", template_path)
    write_json_atomic(meta_path, meta_data)


def meta_path_for(output_dir: str, item_id: int) -> str:
    cache_dir = os.path.join(output_dir, "cache")
    cache_path = os.path.join(cache_dir, f".meta_{item_id}.json")
    legacy_path = os.path.join(output_dir, f".meta_{item_id}.json")
    if not os.path.exists(cache_path) and os.path.exists(legacy_path):
        os.makedirs(cache_dir, exist_ok=True)
        os.replace(legacy_path, cache_path)
    return cache_path


def scan_html_files(start_id=None, end_id=None):
    """
    Scan INPUT_HTML_DIR for HTML files.
    Check OUTPUT_PH_DIR to skip already processed files.
    If CHECK_UPDATES is True, also checks if input files have been modified.
    Returns list of dicts with id, input_path, output_path.
    """
    processed_ids = set()
    needs_reprocess = set()  # IDs that need reprocessing due to input changes
    
    # 1. Scan Output Directory to find already completed items
    if os.path.exists(OUTPUT_PH_DIR):
        for f in os.listdir(OUTPUT_PH_DIR):
            if f.lower().endswith('.html'):
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

    template_files = {}
    if os.path.exists(TEMPLATE_HTML_DIR):
        for f in os.listdir(TEMPLATE_HTML_DIR):
            if f.lower().endswith('.html'):
                fid = get_id_from_filename(f)
                if fid is not None and id_in_range(fid, start_id, end_id):
                    template_files[fid] = os.path.join(TEMPLATE_HTML_DIR, f)
    
    # 3. Check for updates if in check-updates mode
    if CHECK_UPDATES and os.path.exists(OUTPUT_PH_DIR):
        for fid in processed_ids:
            if fid in html_files:
                input_path = html_files[fid]
                template_path = template_files.get(fid)
                output_path = os.path.join(OUTPUT_PH_DIR, f"{fid}.html")

                validation_issue = validate_existing_placeholder_file(input_path, output_path, template_path)
                if validation_issue:
                    needs_reprocess.add(fid)
                    with print_lock:
                        print(f"[Update Check] ID {fid}: Existing placeholder HTML failed validation, will reprocess ({validation_issue})")
                    continue
                
                # Get metadata file path (stores input mtime)
                meta_path = meta_path_for(OUTPUT_PH_DIR, fid)
                
                # Check if we have recorded metadata
                meta = {}
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, 'r', encoding='utf-8') as mf:
                            meta = json.load(mf)
                    except (json.JSONDecodeError, IOError):
                        pass
                
                input_changed, input_signature = file_changed(meta, "input", input_path)
                template_changed = False
                template_signature = None
                if template_path:
                    template_changed, template_signature = file_changed(meta, "template", template_path)

                if input_changed or template_changed:
                    output_mtime = get_file_mtime(output_path)
                    source_mtime = input_signature["mtime"]
                    if template_signature:
                        source_mtime = max(source_mtime, template_signature["mtime"])

                    if output_mtime >= source_mtime:
                        try:
                            refresh_meta(fid, input_path, template_path, meta_path)
                            with print_lock:
                                print(f"[Update Check] ID {fid}: Metadata refreshed; output is newer than input")
                        except IOError as e:
                            needs_reprocess.add(fid)
                            with print_lock:
                                print(f"[Update Check] ID {fid}: Metadata refresh failed ({e}), will reprocess")
                    else:
                        needs_reprocess.add(fid)
                        with print_lock:
                            print(f"[Update Check] ID {fid}: Input content changed, will reprocess")
    
    # 4. Exclude processed ones (unless they need reprocessing) and build dataset list
    dataset_list = []
    for fid in sorted(html_files.keys()):
        if fid in processed_ids and fid not in needs_reprocess:
            continue  # Skip already processed (and not needing update)
        
        dataset_list.append({
            "id": fid,
            "input_path": html_files[fid],
            "template_path": template_files.get(fid),
            "output_path": os.path.join(OUTPUT_PH_DIR, f"{fid}.html"),
            "needs_reprocess": fid in needs_reprocess,
        })
    
    return dataset_list


def ensure_output_dir():
    """Create output directory if it doesn't exist."""
    if not os.path.exists(OUTPUT_PH_DIR):
        os.makedirs(OUTPUT_PH_DIR)
    os.makedirs(os.path.join(OUTPUT_PH_DIR, "cache"), exist_ok=True)


def parse_args():
    """Parse command-line arguments."""
    args = sys.argv[1:]
    start_id = None
    end_id = None
    check_updates = True
    lang = None
    model = DEFAULT_MODEL
    
    i = 0
    while i < len(args):
        if args[i] == '--start_id' and i + 1 < len(args):
            try:
                start_id = int(args[i + 1])
            except ValueError:
                print(f"Invalid start_id: {args[i+1]}")
            i += 2
        elif args[i] == '--end_id' and i + 1 < len(args):
            try:
                end_id = int(args[i + 1])
            except ValueError:
                print(f"Invalid end_id: {args[i+1]}")
            i += 2
        elif args[i] == '--check-updates':
            check_updates = True
            i += 1
        elif args[i] == '--no-check-updates':
            check_updates = False
            i += 1
        elif args[i] == '--lang' and i + 1 < len(args):
            candidate = args[i + 1].lower()
            if candidate in SUPPORTED_LANGUAGES:
                lang = candidate
            else:
                print(f"Invalid language: {args[i+1]}. Use 'en' or 'zh'.")
            i += 2
        elif args[i] == '--model' and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        else:
            i += 1
    
    return start_id, end_id, check_updates, lang, model


def process_single_item(item_data):
    """Process a single HTML file to generate placeholder version."""
    item_id = item_data["id"]
    input_path = item_data["input_path"]
    template_path = item_data.get("template_path")
    output_path = item_data["output_path"]
    needs_reprocess = item_data.get("needs_reprocess", False)
    
    # Double check if output file exists (race condition protection)
    if os.path.exists(output_path) and not needs_reprocess:
        with print_lock:
            print(f"[Thread {threading.current_thread().name}] ID {item_id} already exists in output, skipping.")
        return None
    
    try:
        # Create a dedicated client per thread
        client = create_client()
        
        # Read filled HTML
        with open(input_path, 'r', encoding='utf-8') as f:
            html_completion = f.read()
        template_html = None
        if template_path and os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                template_html = f.read()
        
        # API call with retry mechanism
        max_retries = MAX_RETRIES
        retries = 0
        html_content = None
        validation_feedback = ""
        
        while retries < max_retries:
            try:
                feedback_block = ""
                if validation_feedback:
                    feedback_block = f"""
***Previous output was rejected***:
{validation_feedback}

Regenerate the complete HTML. Do not translate placeholder names. Copy each placeholder name from the original visible label/header text exactly.
"""

                completion = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"""                     
***Input***:
Filled HTML:

{html_completion}
{feedback_block}

Answer after careful thinking.
"""}
                    ]
                )
                html_content = extract_llm_content(completion)
                if html_content is None:
                    raise Exception("LLM returned None content")

                html_content = restore_static_template_cells(template_html, html_completion, html_content)

                static_validation_error = validate_static_cells_against_template(template_html, html_completion, html_content)
                if static_validation_error:
                    validation_feedback = static_validation_error
                    raise ValueError(static_validation_error)

                validation_error = validate_placeholder_names_against_source(html_completion, html_content, template_html)
                if validation_error:
                    validation_feedback = validation_error
                    raise ValueError(validation_error)

                break  # Success: exit loop
            except Exception as e:
                retries += 1
                with print_lock:
                    print(f"[Thread {threading.current_thread().name}] Data ID {item_id} attempt {retries} failed: {e}")
                if retries >= max_retries:
                    raise e  # Reached max retries, raise exception
                time.sleep(min(2 ** retries, 3))  # Exponential backoff, max wait 3 seconds
        
        # Save placeholder HTML to file
        if html_content is None:
            raise Exception("HTML content is None after retries")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Save metadata (input file modification time) for update tracking
        meta_path = meta_path_for(OUTPUT_PH_DIR, item_id)
        meta_data = {
            "id": item_id,
            "processed_at": time.time()
        }
        add_file_signature(meta_data, "input", input_path)
        if template_path and os.path.exists(template_path):
            add_file_signature(meta_data, "template", template_path)
        try:
            write_json_atomic(meta_path, meta_data)
        except IOError as e:
            with print_lock:
                print(f"[Warning] Failed to save metadata for ID {item_id}: {e}")
        
        with print_lock:
            print(f"[Thread {threading.current_thread().name}] Completed ID {item_id} -> {output_path}")
        return item_id
        
    except Exception as e:
        with print_lock:
            print(f"[Thread {threading.current_thread().name}] Error processing data ID {item_id}: {e}")
        return None


def main():
    global INPUT_HTML_DIR, TEMPLATE_HTML_DIR, OUTPUT_PH_DIR, CHECK_UPDATES, MODEL
    
    # Parse command-line arguments
    start_id, end_id, check_updates, lang, model = parse_args()
    if lang is None:
        exit_code = 0
        for selected in SUPPORTED_LANGUAGES:
            print(f"\n{'='*60}\nRunning language: {selected.upper()}\n{'='*60}")
            result = subprocess.run([sys.executable, __file__, *sys.argv[1:], "--lang", selected])
            exit_code = max(exit_code, result.returncode)
        sys.exit(exit_code)

    CHECK_UPDATES = check_updates
    MODEL = model
    
    # Determine language: command line arg takes precedence, then default config
    selected_lang = lang if lang else LANGUAGE
    
    # Initialize paths with language
    INPUT_HTML_DIR = INPUT_HTML_DIR_TEMPLATE.format(lang=selected_lang)
    TEMPLATE_HTML_DIR = TEMPLATE_HTML_DIR_TEMPLATE.format(lang=selected_lang)
    OUTPUT_PH_DIR = OUTPUT_PH_DIR_TEMPLATE.format(lang=selected_lang)
    
    print(f"Language: {selected_lang.upper()}")
    print(f"Input Dir: {INPUT_HTML_DIR}")
    print(f"Template Dir: {TEMPLATE_HTML_DIR}")
    print(f"Output Dir: {OUTPUT_PH_DIR}")
    
    # Ensure output directory exists
    ensure_output_dir()
    
    # Scan HTML files
    print("Scanning HTML files...")
    try:
        dataset = scan_html_files(start_id, end_id)
        print(f"Found {len(dataset)} HTML files to process.")
    except Exception as e:
        print(f"Error scanning directories: {e}")
        sys.exit(1)
    
    # Filter by ID range if specified
    filtered_dataset = []
    for item in dataset:
        item_id = item["id"]
        if start_id is not None and item_id < start_id:
            continue
        if end_id is not None and item_id > end_id:
            continue
        filtered_dataset.append(item)
    
    items_to_process = filtered_dataset
    
    # Show info
    id_range_str = f"ID range: {start_id if start_id is not None else 'start'} - {end_id if end_id is not None else 'end'}"
    check_mode_str = " [Check Updates Mode]" if CHECK_UPDATES else ""
    print(f"\n{'='*60}")
    print(f"Config: {id_range_str}{check_mode_str}")
    print(f"To be processed: {len(items_to_process)}")
    print(f"Output Dir: {OUTPUT_PH_DIR}")
    print(f"{'='*60}\n")
    
    if len(items_to_process) == 0:
        print("No data needs processing!")
        sys.exit(0)
    
    # Statistics
    processed_count = 0
    error_count = 0
    count_lock = Lock()
    
    # Create progress bar
    pbar = tqdm(total=len(items_to_process), desc="Progress", unit="items")
    
    # Use thread pool for concurrent processing
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_item = {executor.submit(process_single_item, item): item for item in items_to_process}
        
        # Collect results
        for future in as_completed(future_to_item):
            try:
                result = future.result()
                if result is not None:
                    with count_lock:
                        processed_count += 1
                else:
                    with count_lock:
                        error_count += 1
            except Exception as e:
                item = future_to_item[future]
                with print_lock:
                    print(f"Task execution exception: {e}, Data ID: {item['id']}")
                with count_lock:
                    error_count += 1
            
            # Update progress bar
            pbar.update(1)
    
    pbar.close()
    
    print(f"\n{'='*60}")
    print(f"Processing completed!")
    print(f"Total attempted: {len(items_to_process)}")
    print(f"Successful: {processed_count}")
    print(f"Failed: {error_count}")
    print(f"Results saved in: {OUTPUT_PH_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
