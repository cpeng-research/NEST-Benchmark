#!/usr/bin/env python3
"""
Step 6: Generate Metadata from Placeholder HTML

Features:
1. Reads placeholder HTML files from workflow/5-ph_html-a/data/
2. Analyzes HTML structure to extract field metadata (position, type, grouping)
3. Categorizes fields into types: LI (List Items), GI (Grouped Input), SI (Single Input), GO (Grouped Output), SO (Single Output)
4. Saves metadata as individual .json files in workflow/6-meta-a/data/
5. Supports processing data within a specified ID range
6. Automatically skips files that already exist in output directory (resume-from-breakpoint)
7. Tracks input file modification times for smart reprocessing
8. Supports --check-updates mode to reprocess if input files changed
9. Uses AI-based judgment for field type classification (optional)

Usage:
1. Process all data:
   python workflow/6-meta-a/step6_gen_meta.py

2. Process a specified ID range (e.g., 87-88):
   python workflow/6-meta-a/step6_gen_meta.py --start_id 87 --end_id 88

3. Check for updates and reprocess changed files:
   python workflow/6-meta-a/step6_gen_meta.py --check-updates

4. Enable AI judgment for selection-type fields:
   python workflow/6-meta-a/step6_gen_meta.py --use-ai

Notes:
- Always run from project root directory
- Filenames should be numeric (e.g., 87.html, 88.html)
- Each HTML file will be processed independently
- Use --check-updates to reprocess files whose inputs have been modified
"""
from dotenv import load_dotenv
load_dotenv()
import hashlib
import os
import re
import json
import time
import sys
import subprocess
from bs4 import BeautifulSoup
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from tqdm import tqdm


# ================= Configuration Parameters =================
MAX_WORKERS = 10

# Language selection (en or zh)
LANGUAGE = None  # None means process both en and zh; can be overridden by --lang
SUPPORTED_LANGUAGES = ("en", "zh")

# Directories
INPUT_PH_DIR = "workflow/5-ph_html-a/data_{lang}"      # Directory containing placeholder HTML files
OUTPUT_META_DIR = "workflow/6-meta-a/data_{lang}"      # Directory to save metadata JSON files

# Processing parameters
DEFAULT_MODEL = "gpt-5"
MODEL = DEFAULT_MODEL
MAX_WORKERS = 10           # Number of concurrent threads

# Check updates mode
CHECK_UPDATES = True       # If True, reprocess files whose inputs have been modified

# AI Judgment Toggle
USE_AI_JUDGMENT = True     # Use AI to judge non-pure-text fields by default

# Global locks
print_lock = Lock()
save_lock = Lock()
client_create_lock = Lock()

# Create OpenAI client
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


# ==================== Helper Functions ====================
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


def parse_span_attr(value, default: int = 1) -> int:
    """Parse rowspan/colspan defensively; empty or invalid values fall back to 1."""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        parsed = int(text)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


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


def write_json_atomic(filepath: str, data, indent: int = 2) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp_path = f"{filepath}.tmp.{os.getpid()}.{id(data)}"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
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


def clean_placeholders_in_html(html: str) -> str:
    """
    Clean all placeholders in HTML: remove '-' and everything before it inside [ ... ].
    Example: [A-B-C] -> [C]
    """
    def clean_placeholder(match):
        placeholder = match.group(0)
        inner_text = match.group(1)

        if '-' in inner_text:
            cleaned_text = inner_text.split('-')[-1]
            return f'[{cleaned_text}]'
        return placeholder

    return re.sub(r'\[([^\]]+)\]', clean_placeholder, html)


def normalize_text(text: str) -> str:
    """
    Remove spaces, Chinese/English colons, periods, quotes, etc., for fuzzy matching.
    """
    if not text:
        return ""
    return re.sub(r'[\W_]+', '', text, flags=re.UNICODE).lower()


def extract_placeholders_from_cell(cell_text: str, cell_html: str) -> list[str]:
    """Extract placeholders from visible text and HTML attributes, preserving order."""
    seen = set()
    placeholders = []
    for source in (cell_text, cell_html):
        for placeholder in re.findall(r'(\[.*?\])', source or ''):
            if placeholder in seen:
                continue
            seen.add(placeholder)
            placeholders.append(placeholder)
    return placeholders


def is_non_pure_text(cell_html: str) -> bool:
    """
    Determine whether a cell is non-pure-text type (traditional heuristic).
    """
    if not cell_html:
        return False
    pattern = r'<input|<select|\(√\)|\(\s*\)|\[√\]|\[\s*\]|\(×\)|\[×\]'
    return bool(re.search(pattern, cell_html))


def remove_duplicate_placeholders(placeholders_data):
    """
    Remove duplicates in placeholders_data by 'key', keeping the first occurrence.
    """
    seen_keys = set()
    unique_placeholders_data = []
    for item in placeholders_data:
        if item['key'] not in seen_keys:
            seen_keys.add(item['key'])
            unique_placeholders_data.append(item)
    return unique_placeholders_data


def ai_batch_analyze_table(html_content: str, all_keys_with_positions: list) -> dict:
    """
    Batch AI analysis for the entire table.
    Identifies all non-pure-text (selection-type) fields in one API call.
    
    Args:
        html_content: The complete HTML table content
        all_keys_with_positions: List of dicts with 'key', 'label_row', 'label_col'
        
    Returns:
        Dict mapping (label_row, label_col) -> is_non_pure_text (bool)
    """
    if not USE_AI_JUDGMENT:
        return {}
    
    if not all_keys_with_positions:
        return {}

    try:
        client = create_client()
        
        # Build position-key mapping for reference
        position_key_list = []
        for item in all_keys_with_positions:
            pos = (item['label_row'], item['label_col'])
            position_key_list.append(f"Position ({item['label_row']}, {item['label_col']}): Key = '{item['key']}'")
        
        position_reference = "\n".join(position_key_list)
        
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You analyze HTML tables to identify selection-type fields vs plain text input fields."
                },
                {
                    "role": "user",
                    "content": f"""Please analyze this HTML table and identify which fields are selection-type (checkbox, radio, select dropdown, yes/no choices, etc.) vs plain text input fields.

HTML Table:
{html_content}

Field positions and keys (format: Position (row, col): Key = 'key_name'):
{position_reference}

**Task**:
For each field position listed above, determine if it is a selection-type field or plain text input field.

**Selection-type fields include**:
- Checkboxes (<input type="checkbox">)
- Radio buttons (<input type="radio">)
- Select dropdowns (<select>)
- Yes/No or True/False choices
- Multiple choice options
- Any field where user selects from predefined options

**Plain text input fields include**:
- Text input boxes
- Textarea fields
- Any field where user types free-form text

**Output format**:
Return a JSON object with this structure:
{{
  "selection_type_fields": [
    {{"position": [row, col], "key": "FieldName", "type": "checkbox/radio/select/yesno/etc"}},
    ...
  ]
}}

Only include fields that are selection-type. Do NOT include plain text input fields.
If a key appears multiple times at different positions, specify the exact position.

Think carefully and analyze each field.
"""
                }
            ]
        )
        response = (extract_llm_content(completion) or "").strip()
        print(f"AI batch analysis completed, processing response...")
        
        # Parse response to extract selection-type fields
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                result_json = json.loads(json_match.group(0))
                selection_fields = result_json.get('selection_type_fields', [])
                
                # Build result mapping: (row, col) -> True
                result = {}
                for field in selection_fields:
                    pos = tuple(field['position'])
                    result[pos] = True
                
                return result
            else:
                print("Warning: Could not extract JSON from AI response")
                return {}
        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse AI response as JSON: {e}")
            return {}
            
    except Exception as e:
        print(f"AI batch analysis failed: {e}")
        print("Falling back to heuristic judgment...")
        return {}


# ==================== Template Analysis Functions ====================
def analyze_template(html: str):
    """
    Analyze an HTML template containing placeholders and return a list with position/offset info.
    Correctly handles rowspan/colspan merged cells.
    Simplified version - only keeps essential fields.
    """
    soup = BeautifulSoup(html, 'html.parser')
    placeholder_pattern = re.compile(r'\[.*?\]')

    def has_placeholder(tag) -> bool:
        return bool(tag and placeholder_pattern.search(tag.get_text()))

    def direct_rows(table):
        rows = []
        for child in table.children:
            if getattr(child, 'name', None) == 'tr':
                rows.append(child)
            elif getattr(child, 'name', None) in {'thead', 'tbody', 'tfoot'}:
                rows.extend(child.find_all('tr', recursive=False))
        return rows

    def find_leaf_placeholder_tables():
        """
        Return deepest placeholder tables for the normal path.

        This keeps existing behavior for nested tables that are self-contained.
        If those tables cannot match any labels, analyze_template falls back to
        the outer real form table below.
        """
        tables = soup.find_all('table')
        leaf_tables = []
        for table in tables:
            if not has_placeholder(table):
                continue

            nested_placeholder_tables = [
                child_table
                for child_table in table.find_all('table')
                if child_table is not table and has_placeholder(child_table)
            ]
            if not nested_placeholder_tables:
                leaf_tables.append(table)

        return leaf_tables

    def cell_text_without_nested_tables(cell) -> str:
        cell_copy_soup = BeautifulSoup(str(cell), 'html.parser')
        cell_copy = cell_copy_soup.find(cell.name)
        if cell_copy is None:
            return cell.get_text()

        for nested_table in cell_copy.find_all('table'):
            nested_table.decompose()
        return cell_copy.get_text()

    def direct_nested_placeholder_tables(table, cell):
        return [
            child_table
            for child_table in cell.find_all('table')
            if child_table.find_parent('table') is table and has_placeholder(child_table)
        ]

    def is_layout_wrapper_table(table) -> bool:
        """
        Detect one-cell Word/layout wrappers while preserving real form tables.

        Some templates wrap the actual table in a single empty cell; those must
        be skipped. Other templates put small input grids inside a real outer
        form row, where the outer row/column positions are the useful metadata.
        """
        rows = direct_rows(table)
        if len(rows) != 1:
            return False

        cells = rows[0].find_all(['td', 'th'], recursive=False)
        if len(cells) != 1:
            return False

        cell = cells[0]
        if not direct_nested_placeholder_tables(table, cell):
            return False

        direct_text = normalize_text(cell_text_without_nested_tables(cell))
        return direct_text == ""

    def find_analysis_tables():
        """
        Return the table grids to analyze.

        Prefer the outer real form table so placeholders embedded in nested
        controls can still match labels in sibling/parent cells. Only descend
        through a nested table when the current table is a pure one-cell layout
        wrapper with no direct label text.
        """
        analysis_tables = []

        def visit(table):
            if not has_placeholder(table):
                return

            if is_layout_wrapper_table(table):
                rows = direct_rows(table)
                cell = rows[0].find_all(['td', 'th'], recursive=False)[0]
                for nested_table in direct_nested_placeholder_tables(table, cell):
                    visit(nested_table)
                return

            analysis_tables.append(table)

        top_level_tables = [
            table for table in soup.find_all('table')
            if table.find_parent('table') is None
        ]
        for table in top_level_tables:
            visit(table)

        return analysis_tables

    def analyze_non_table_placeholders():
        placeholders = extract_placeholders_from_cell("", str(soup))
        final_locations = []
        for index, p_text in enumerate(placeholders):
            final_locations.append({
                'key': p_text.strip('[]'),
                'label_info': {'row': index, 'col': 0},
                'placeholder_offset': {'rows': 0, 'cols': 0},
                'cell_html': str(soup)
            })
        return final_locations

    def analyze_single_table(table, row_base=0):
        all_cells = []
        all_placeholders = []
        rows = direct_rows(table)

        if not rows:
            return [], 0

        max_cols = 50  # estimated upper bound for columns
        matrix = [[None for _ in range(max_cols)] for _ in range(len(rows))]

        row_info = []
        for row in rows:
            cells = row.find_all(['td', 'th'], recursive=False)
            row_info.append(cells)

        for row_index, cells in enumerate(row_info):
            col_idx = 0

            for cell in cells:
                while col_idx < max_cols and matrix[row_index][col_idx] is not None:
                    col_idx += 1
                if col_idx >= max_cols:
                    continue

                cell_text = cell.get_text()
                cell_html = str(cell)
                rowspan = parse_span_attr(cell.get('rowspan'), 1)
                colspan = parse_span_attr(cell.get('colspan'), 1)

                cell_info = {
                    'text': cell_text,
                    'row': row_base + row_index,
                    'col': col_idx,
                    'colspan': colspan,
                    'rowspan': rowspan
                }
                all_cells.append(cell_info)

                for r_offset in range(rowspan):
                    target_row = row_index + r_offset
                    if target_row >= len(rows):
                        break
                    for c_offset in range(colspan):
                        target_col = col_idx + c_offset
                        if target_col < max_cols:
                            if r_offset == 0 and c_offset == 0:
                                matrix[target_row][target_col] = cell_info
                            else:
                                matrix[target_row][target_col] = True

                placeholders_in_cell = extract_placeholders_from_cell(cell_text, cell_html)
                for p_text in placeholders_in_cell:
                    placeholder_key = p_text.strip('[]')

                    all_placeholders.append({
                        'key': placeholder_key,
                        'text': p_text,
                        'row': row_base + row_index,
                        'col': col_idx,
                        'cell_text': cell_text,
                        'cell_html': cell_html
                    })

                col_idx += colspan

        def infer_locations_from_placeholder_headers():
            """
            Handle list tables where Step 5 also wrapped column labels in
            placeholders, e.g. header [Field] with rows [Field1], [Field2].
            """
            header_candidates = []
            for ph in all_placeholders:
                key = ph['key']
                if re.match(r'.+?\d+$', key):
                    continue

                cell_text = ph.get('cell_text', ph['text'])
                placeholders_in_cell = re.findall(r'\[.*?\]', cell_text)
                if len(placeholders_in_cell) != 1 or cell_text.strip() != ph['text']:
                    continue

                header_candidates.append(ph)

            inferred_locations = []
            for ph in all_placeholders:
                key_text = ph['key']
                match = re.match(r'(.+?)(\d+)$', key_text)
                if not match:
                    continue

                normalized_base_key = normalize_text(match.group(1))
                candidates = [
                    header
                    for header in header_candidates
                    if normalize_text(header['key']) == normalized_base_key
                    and header['row'] < ph['row']
                ]
                if not candidates:
                    continue

                same_col_candidates = [header for header in candidates if header['col'] == ph['col']]
                use_candidates = same_col_candidates if same_col_candidates else candidates
                best_label_cell = min(
                    use_candidates,
                    key=lambda header: (ph['row'] - header['row'], abs(ph['col'] - header['col']))
                )

                inferred_locations.append({
                    'key': ph['key'],
                    'label_info': {'row': best_label_cell['row'], 'col': best_label_cell['col']},
                    'placeholder_offset': {
                        'rows': ph['row'] - best_label_cell['row'],
                        'cols': ph['col'] - best_label_cell['col']
                    },
                    'cell_html': ph['cell_html']
                })

            return inferred_locations

        def infer_same_cell_locations():
            return [
                {
                    'key': ph['key'],
                    'label_info': {'row': ph['row'], 'col': ph['col']},
                    'placeholder_offset': {'rows': 0, 'cols': 0},
                    'cell_html': ph['cell_html']
                }
                for ph in all_placeholders
            ]

        final_locations = []
        for placeholder in all_placeholders:
            best_label_cell = None

            key_text = placeholder['key']
            match = re.match(r'(.+?)(\d+)$', key_text)
            search_key = match.group(1) if match else key_text

            normalized_search_key = normalize_text(search_key)

            candidates = []
            for cell in all_cells:
                normalized_cell_text = normalize_text(cell['text'])

                if normalized_search_key in normalized_cell_text:
                    if cell['text'].strip() == placeholder['text']:
                        continue

                    # Remove all placeholders in the same cell
                    placeholders_in_this_cell = re.findall(r'\[.*?\]', cell['text'])
                    text_without_all_placeholders = cell['text']
                    for ph in placeholders_in_this_cell:
                        text_without_all_placeholders = text_without_all_placeholders.replace(ph, '')

                    normalized_remaining_text = normalize_text(text_without_all_placeholders)
                    if normalized_search_key not in normalized_remaining_text:
                        continue

                    distance = abs(placeholder['row'] - cell['row']) + abs(placeholder['col'] - cell['col'])

                    if cell['row'] == placeholder['row'] and cell['col'] == placeholder['col']:
                        direction = 'same_cell'
                    elif cell['row'] == placeholder['row'] and cell['col'] < placeholder['col']:
                        direction = 'left'
                    elif cell['row'] < placeholder['row']:
                        direction = 'up'
                    else:
                        direction = 'down'

                    candidates.append({'cell': cell, 'distance': distance, 'direction': direction})

            same_cell_candidates = [c for c in candidates if c['distance'] == 0]
            left_candidates = [c for c in candidates if c['direction'] == 'left']
            up_candidates = [c for c in candidates if c['direction'] == 'up']
            down_candidates = [c for c in candidates if c['direction'] == 'down']

            def choose_best(cand_list):
                if not cand_list:
                    return None
                same_col = [c for c in cand_list if c['cell']['col'] == placeholder['col']]
                use = same_col if same_col else cand_list
                return min(use, key=lambda x: x['distance'])

            if same_cell_candidates:
                best_label_cell = same_cell_candidates[0]['cell']
            elif left_candidates:
                best_candidate = choose_best(left_candidates)
                best_label_cell = best_candidate['cell'] if best_candidate else None
            elif up_candidates:
                best_candidate = choose_best(up_candidates)
                best_label_cell = best_candidate['cell'] if best_candidate else None
            elif down_candidates:
                best_candidate = choose_best(down_candidates)
                best_label_cell = best_candidate['cell'] if best_candidate else None
            else:
                best_label_cell = None

            if best_label_cell:
                row_offset = placeholder['row'] - best_label_cell['row']
                col_offset = placeholder['col'] - best_label_cell['col']

                final_locations.append({
                    'key': placeholder['key'],
                    'label_info': {'row': best_label_cell['row'], 'col': best_label_cell['col']},
                    'placeholder_offset': {'rows': row_offset, 'cols': col_offset},
                    'cell_html': placeholder['cell_html']
                })

        if not final_locations:
            final_locations = infer_locations_from_placeholder_headers()
        if not final_locations:
            final_locations = infer_same_cell_locations()

        return final_locations, len(rows)

    leaf_tables = find_leaf_placeholder_tables()
    if leaf_tables:
        final_locations = []
        row_base = 0
        for table in leaf_tables:
            table_locations, row_count = analyze_single_table(table, row_base)
            final_locations.extend(table_locations)
            row_base += row_count
        if final_locations:
            return final_locations

    analysis_tables = find_analysis_tables()
    if analysis_tables:
        final_locations = []
        row_base = 0
        for table in analysis_tables:
            table_locations, row_count = analyze_single_table(table, row_base)
            final_locations.extend(table_locations)
            row_base += row_count
        if final_locations:
            return final_locations

    all_cells = []
    all_placeholders = []
    rows = soup.find_all('tr')

    if not rows:
        return analyze_non_table_placeholders()

    max_cols = 50  # estimated upper bound for columns
    matrix = [[None for _ in range(max_cols)] for _ in range(len(rows))]

    row_info = []
    for row in rows:
        cells = row.find_all('td')
        row_info.append(cells)

    for row_index, cells in enumerate(row_info):
        col_idx = 0

        for cell in cells:
            while col_idx < max_cols and matrix[row_index][col_idx] is not None:
                col_idx += 1
            if col_idx >= max_cols:
                continue

            cell_text = cell.get_text()
            cell_html = str(cell)
            rowspan = parse_span_attr(cell.get('rowspan'), 1)
            colspan = parse_span_attr(cell.get('colspan'), 1)

            cell_info = {
                'text': cell_text,
                'row': row_index,
                'col': col_idx,
                'colspan': colspan,
                'rowspan': rowspan
            }
            all_cells.append(cell_info)

            for r_offset in range(rowspan):
                target_row = row_index + r_offset
                if target_row >= len(rows):
                    break
                for c_offset in range(colspan):
                    target_col = col_idx + c_offset
                    if target_col < max_cols:
                        if r_offset == 0 and c_offset == 0:
                            matrix[target_row][target_col] = cell_info
                        else:
                            matrix[target_row][target_col] = True

            placeholders_in_cell = extract_placeholders_from_cell(cell_text, cell_html)
            for p_text in placeholders_in_cell:
                placeholder_key = p_text.strip('[]')

                all_placeholders.append({
                    'key': placeholder_key,
                    'text': p_text,
                    'row': row_index,
                    'col': col_idx,
                    'cell_text': cell_text,
                    'cell_html': cell_html
                })

            col_idx += colspan

    final_locations = []
    for placeholder in all_placeholders:
        best_label_cell = None

        key_text = placeholder['key']
        match = re.match(r'(.+?)(\d+)$', key_text)
        search_key = match.group(1) if match else key_text

        normalized_search_key = normalize_text(search_key)

        candidates = []
        for cell in all_cells:
            normalized_cell_text = normalize_text(cell['text'])

            if normalized_search_key in normalized_cell_text:
                if cell['text'].strip() == placeholder['text']:
                    continue

                # Remove all placeholders in the same cell
                placeholders_in_this_cell = re.findall(r'\[.*?\]', cell['text'])
                text_without_all_placeholders = cell['text']
                for ph in placeholders_in_this_cell:
                    text_without_all_placeholders = text_without_all_placeholders.replace(ph, '')

                normalized_remaining_text = normalize_text(text_without_all_placeholders)
                if normalized_search_key not in normalized_remaining_text:
                    continue

                distance = abs(placeholder['row'] - cell['row']) + abs(placeholder['col'] - cell['col'])

                if cell['row'] == placeholder['row'] and cell['col'] == placeholder['col']:
                    direction = 'same_cell'
                elif cell['row'] == placeholder['row'] and cell['col'] < placeholder['col']:
                    direction = 'left'
                elif cell['row'] < placeholder['row']:
                    direction = 'up'
                else:
                    direction = 'down'

                candidates.append({'cell': cell, 'distance': distance, 'direction': direction})

        same_cell_candidates = [c for c in candidates if c['distance'] == 0]
        left_candidates = [c for c in candidates if c['direction'] == 'left']
        up_candidates = [c for c in candidates if c['direction'] == 'up']
        down_candidates = [c for c in candidates if c['direction'] == 'down']

        def choose_best(cand_list):
            if not cand_list:
                return None
            same_col = [c for c in cand_list if c['cell']['col'] == placeholder['col']]
            use = same_col if same_col else cand_list
            return min(use, key=lambda x: x['distance'])

        if same_cell_candidates:
            best_label_cell = same_cell_candidates[0]['cell']
        elif left_candidates:
            best_candidate = choose_best(left_candidates)
            best_label_cell = best_candidate['cell'] if best_candidate else None
        elif up_candidates:
            best_candidate = choose_best(up_candidates)
            best_label_cell = best_candidate['cell'] if best_candidate else None
        elif down_candidates:
            best_candidate = choose_best(down_candidates)
            best_label_cell = best_candidate['cell'] if best_candidate else None
        else:
            best_label_cell = None

        if best_label_cell:
            row_offset = placeholder['row'] - best_label_cell['row']
            col_offset = placeholder['col'] - best_label_cell['col']

            final_locations.append({
                'key': placeholder['key'],
                'label_info': {'row': best_label_cell['row'], 'col': best_label_cell['col']},
                'placeholder_offset': {'rows': row_offset, 'cols': col_offset},
                'cell_html': placeholder['cell_html']
            })

    return final_locations


def get_placeholder_position(item):
    """
    Calculate placeholder position from label_info and placeholder_offset.
    Returns (row, col) tuple.
    """
    offset = item['placeholder_offset']
    if isinstance(offset, list):
        offset = offset[0]
    return (item['label_info']['row'] + offset['rows'], 
            item['label_info']['col'] + offset['cols'])


def group_object_type_placeholders(items_with_object_type):
    """
    Smart grouping for LI placeholders (object-type lists).
    Group by numeric suffix continuity.
    Simplified version.
    """
    items_with_object_type.sort(key=get_placeholder_position)

    base_key_groups = {}
    base_key_current_group = {}
    base_key_expected_index = {}

    for item in items_with_object_type:
        if not item.get('is_object_type', False):
            continue
        base_key = item['base_key']
        key = item['key']
        
        # Calculate placeholder column from label_info + offset
        offset = item['placeholder_offset']
        if isinstance(offset, list):
            offset = offset[0]
        placeholder_col = item['label_info']['col'] + offset['cols']

        match = re.match(r'.+?(\d+)$', key)
        if not match:
            continue
        index = int(match.group(1))

        if base_key not in base_key_groups:
            base_key_groups[base_key] = []
            base_key_current_group[base_key] = None
            base_key_expected_index[base_key] = None

        current_group = base_key_current_group.get(base_key)
        if current_group and current_group['items']:
            first_item = current_group['items'][0]
            first_offset = first_item['placeholder_offset']
            if isinstance(first_offset, list):
                first_offset = first_offset[0]
            current_col = first_item['label_info']['col'] + first_offset['cols']
        else:
            current_col = None

        if index == 1:
            new_group = {
                'base_key': base_key,
                'items': [item],
                'indices': [index],
            }
            base_key_groups[base_key].append(new_group)
            base_key_current_group[base_key] = new_group
            base_key_expected_index[base_key] = 2
        elif (base_key_expected_index[base_key] == index and current_group is not None and placeholder_col == current_col):
            current_group['items'].append(item)
            current_group['indices'].append(index)
            base_key_expected_index[base_key] = index + 1
        else:
            if base_key_expected_index.get(base_key) != index and current_group is not None:
                print(f"Note: {key} has index {index}, expected {base_key_expected_index.get(base_key, '1')}; treating as independent item.")
            new_group = {
                'base_key': base_key,
                'items': [item],
                'indices': [index],
            }
            base_key_groups[base_key].append(new_group)
            base_key_current_group[base_key] = None
            base_key_expected_index[base_key] = None

    return base_key_groups


def analyze_and_categorize_template_new(html: str):
    """
    Rebuilt template analysis function with simplified data structure.
    Only keeps essential fields: key, label position, placeholder position/offset, type info.
    """
    initial_analysis = analyze_template(html)
    # Sort by placeholder position (calculated from label_info + placeholder_offset)
    initial_analysis.sort(key=get_placeholder_position)

    all_placeholders = {}         # base_key -> set(number_suffixes)
    all_keys_for_ai = []          # List for batch AI analysis

    # First pass: identify object types (LI candidates) and prepare AI input
    for item in initial_analysis:
        key = item['key']
        label_row = item['label_info']['row']
        label_col = item['label_info']['col']

        match = re.match(r'(.+?)(\d+)$', key)
        if match:
            base_key = match.group(1)
            number_suffix = match.group(2)
            
            all_placeholders.setdefault(base_key, set()).add(number_suffix)
            
            # Add to AI analysis list
            all_keys_for_ai.append({
                'key': key,
                'label_row': label_row,
                'label_col': label_col
            })
        else:
            # Non-numbered keys also need analysis
            all_keys_for_ai.append({
                'key': key,
                'label_row': label_row,
                'label_col': label_col
            })

    # Perform Batch AI Analysis for the whole table
    ai_results_map = ai_batch_analyze_table(html, all_keys_for_ai)

    # Second pass: mark object types and apply AI results
    for item in initial_analysis:
        key = item['key']
        label_row = item['label_info']['row']
        label_col = item['label_info']['col']
        pos_key = (label_row, label_col)

        match = re.match(r'(.+?)(\d+)$', key)
        if match:
            base_key = match.group(1)
            number_suffix = match.group(2)

            if (base_key in all_placeholders and
                len(all_placeholders[base_key]) >= 2):
                item['is_object_type'] = True
                item['base_key'] = base_key
            else:
                item['is_object_type'] = False
                item['base_key'] = key
        else:
            item['is_object_type'] = False
            item['base_key'] = key

        # Determine is_non_pure_text:
        # Priority: 1) AI batch result  2) Heuristic fallback
        if USE_AI_JUDGMENT and pos_key in ai_results_map:
            # AI identified this as selection-type
            item['is_non_pure_text'] = True
        else:
            # Fallback to heuristic (either AI disabled or AI didn't identify it)
            item['is_non_pure_text'] = is_non_pure_text(item.get('cell_html', ''))
    
    # Smart grouping
    groups = {}
    group_counter = 0

    object_type_groups = group_object_type_placeholders(initial_analysis)

    for base_key, group_list in object_type_groups.items():
        for group_data in group_list:
            group_key = f"object_group_{group_counter}"
            groups[group_key] = group_data['items']
            group_counter += 1

    non_object_items = [it for it in initial_analysis if not it.get('is_object_type', False)]
    # Sort by placeholder position
    non_object_items.sort(key=get_placeholder_position)

    same_cell_groups = {}  # (row, col, key) -> list(items)

    current_key = None
    current_label_pos = None
    current_group_items = []

    for item in non_object_items:
        key = item.get('key')
        label_pos = (item['label_info']['row'], item['label_info']['col'])
        
        # Calculate placeholder position using helper
        placeholder_pos = get_placeholder_position(item)
        is_same_cell = (label_pos == placeholder_pos)

        if is_same_cell:
            cell_key = (placeholder_pos[0], placeholder_pos[1], key)
            same_cell_groups.setdefault(cell_key, []).append(item)

            # Save current group before reset
            if current_group_items:
                group_key = f"non_object_group_{group_counter}"
                groups[group_key] = current_group_items
                group_counter += 1

            current_key = None
            current_label_pos = None
            current_group_items = []
        else:
            if key == current_key and label_pos == current_label_pos:
                current_group_items.append(item)
            else:
                if current_group_items:
                    group_key = f"non_object_group_{group_counter}"
                    groups[group_key] = current_group_items
                    group_counter += 1

                current_key = key
                current_label_pos = label_pos
                current_group_items = [item]

    if current_group_items:
        group_key = f"non_object_group_{group_counter}"
        groups[group_key] = current_group_items
        group_counter += 1

    for cell_key, cell_items in same_cell_groups.items():
        group_key = f"non_object_group_{group_counter}"
        groups[group_key] = cell_items
        group_counter += 1

    processed_items = []

    for group_key, group_items in groups.items():
        if not group_items:
            continue

        group_items.sort(key=get_placeholder_position)
        first_item = group_items[0]

        if len(group_items) > 1:
            if first_item.get('is_object_type', False):
                display_key = first_item.get('base_key')
            else:
                display_key = first_item['key']

            aggregated_item = {
                'key': display_key,
                'label_info': {
                    'row': first_item['label_info']['row'],
                    'col': first_item['label_info']['col']
                },
                'placeholder_offset': [it['placeholder_offset'] for it in group_items],
                'is_object_type': first_item.get('is_object_type', False),
                'is_non_pure_text': first_item.get('is_non_pure_text', False)
            }
            processed_items.append(aggregated_item)
        else:
            it = group_items[0]
            item_data = {
                'key': it['key'],
                'label_info': {
                    'row': it['label_info']['row'],
                    'col': it['label_info']['col']
                },
                'placeholder_offset': it['placeholder_offset'],
                'is_object_type': it.get('is_object_type', False),
                'is_non_pure_text': it.get('is_non_pure_text', False)
            }
            processed_items.append(item_data)

    categorized_results = {'LI': [], 'GI': [], 'SI': [], 'GO': [], 'SO': []}

    for item in processed_items:
        is_object_type = item.get('is_object_type', False)
        field_is_non_pure_text = item.get('is_non_pure_text', False)

        if is_object_type:
            item['type'] = 'LI'
            categorized_results['LI'].append(item)
        elif field_is_non_pure_text:
            # Check if label and placeholder are in same cell
            label_pos = (item['label_info']['row'], item['label_info']['col'])
            placeholder_pos = get_placeholder_position(item)
            is_same_cell = (label_pos == placeholder_pos)
            
            item['type'] = 'GO' if is_same_cell else 'SO'
            categorized_results[item['type']].append(item)
        else:
            # Check if label and placeholder are in same cell
            label_pos = (item['label_info']['row'], item['label_info']['col'])
            placeholder_pos = get_placeholder_position(item)
            is_same_cell = (label_pos == placeholder_pos)
            
            item['type'] = 'GI' if is_same_cell else 'SI'
            categorized_results[item['type']].append(item)

    all_processed_items = []
    for category_items in categorized_results.values():
        all_processed_items.extend(category_items)
    all_processed_items.sort(key=lambda x: (x['label_info']['row'], x['label_info']['col']))

    return categorized_results, all_processed_items


# ==================== File Scanning and Processing ====================
def scan_ph_files(start_id=None, end_id=None):
    """
    Scan INPUT_PH_DIR for placeholder HTML files.
    Check OUTPUT_META_DIR to skip already processed files.
    If CHECK_UPDATES is True, also checks if input files have been modified.
    Returns list of dicts with id, input_path, output_path.
    """
    processed_ids = set()
    needs_reprocess = set()  # IDs that need reprocessing due to input changes
    
    # 1. Scan Output Directory to find already completed items
    if os.path.exists(OUTPUT_META_DIR):
        for f in os.listdir(OUTPUT_META_DIR):
            if f.lower().endswith('.json'):
                fid = get_id_from_filename(f)
                if fid is not None:
                    processed_ids.add(fid)
    
    # 2. Scan Input PH Directory
    if not os.path.exists(INPUT_PH_DIR):
        raise FileNotFoundError(f"Input placeholder HTML directory not found: {INPUT_PH_DIR}")
    
    ph_files = {}
    for f in os.listdir(INPUT_PH_DIR):
        if f.lower().endswith('.html'):
            fid = get_id_from_filename(f)
            if fid is not None and id_in_range(fid, start_id, end_id):
                ph_files[fid] = os.path.join(INPUT_PH_DIR, f)
    
    # 3. Check for updates if in check-updates mode
    if CHECK_UPDATES and os.path.exists(OUTPUT_META_DIR):
        for fid in processed_ids:
            if fid in ph_files:
                input_path = ph_files[fid]
                output_path = os.path.join(OUTPUT_META_DIR, f"{fid}.json")
                
                # Get metadata file path (stores input mtime)
                meta_track_path = meta_path_for(OUTPUT_META_DIR, fid)
                
                # Check if we have recorded metadata
                meta = {}
                if os.path.exists(meta_track_path):
                    try:
                        with open(meta_track_path, 'r', encoding='utf-8') as mf:
                            meta = json.load(mf)
                    except (json.JSONDecodeError, IOError):
                        pass
                
                changed, input_signature = file_changed(meta, "input", input_path)
                if changed:
                    output_mtime = get_file_mtime(output_path)
                    if output_mtime >= input_signature["mtime"]:
                        try:
                            refresh_meta(fid, input_path, meta_track_path)
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
    for fid in sorted(ph_files.keys()):
        if fid in processed_ids and fid not in needs_reprocess:
            continue  # Skip already processed (and not needing update)
        
        dataset_list.append({
            "id": fid,
            "input_path": ph_files[fid],
            "output_path": os.path.join(OUTPUT_META_DIR, f"{fid}.json"),
            "needs_reprocess": fid in needs_reprocess,
        })
    
    return dataset_list


def ensure_output_dir():
    """Create output directory if it doesn't exist."""
    if not os.path.exists(OUTPUT_META_DIR):
        os.makedirs(OUTPUT_META_DIR)
    os.makedirs(os.path.join(OUTPUT_META_DIR, "cache"), exist_ok=True)


def parse_args():
    """Parse command-line arguments."""
    args = sys.argv[1:]
    start_id = None
    end_id = None
    check_updates = True
    lang = None
    model = DEFAULT_MODEL
    use_ai = USE_AI_JUDGMENT
    
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
        elif args[i] == '--use-ai':
            use_ai = True
            i += 1
        elif args[i] == '--no-ai':
            use_ai = False
            i += 1
        else:
            i += 1
    
    return start_id, end_id, check_updates, lang, model, use_ai


def process_single_file(item_data):
    """Process a single placeholder HTML file to generate metadata."""
    item_id = item_data["id"]
    input_path = item_data["input_path"]
    output_path = item_data["output_path"]
    needs_reprocess = item_data.get("needs_reprocess", False)
    
    # Double check if output file exists (race condition protection)
    if os.path.exists(output_path) and not needs_reprocess:
        with print_lock:
            print(f"[ID {item_id}] Already exists in output, skipping.")
        return None
    
    try:
        # Read placeholder HTML
        with open(input_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Clean placeholders
        cleaned_html = clean_placeholders_in_html(html_content)
        
        # Analyze and categorize template
        categorized_data, structured_analysis = analyze_and_categorize_template_new(cleaned_html)
        
        # Save metadata JSON
        write_json_atomic(output_path, structured_analysis, indent=4)
        
        # Save tracking metadata (input file modification time)
        meta_track_path = meta_path_for(OUTPUT_META_DIR, item_id)
        meta_data = {
            "id": item_id,
            "processed_at": time.time()
        }
        add_file_signature(meta_data, "input", input_path)
        try:
            write_json_atomic(meta_track_path, meta_data)
        except IOError as e:
            with print_lock:
                print(f"[Warning] Failed to save tracking metadata for ID {item_id}: {e}")
        
        with print_lock:
            print(f"[ID {item_id}] Completed -> {output_path}")
        return item_id
        
    except Exception as e:
        with print_lock:
            print(f"[ID {item_id}] Error: {e}")
        return None


def main():
    global INPUT_PH_DIR, OUTPUT_META_DIR, MODEL, USE_AI_JUDGMENT

    # Parse command-line arguments
    start_id, end_id, check_updates, lang, model, use_ai = parse_args()
    if lang is None:
        exit_code = 0
        for selected in SUPPORTED_LANGUAGES:
            print(f"\n{'='*60}\nRunning language: {selected.upper()}\n{'='*60}")
            result = subprocess.run([sys.executable, __file__, *sys.argv[1:], "--lang", selected])
            exit_code = max(exit_code, result.returncode)
        sys.exit(exit_code)

    selected_lang = lang if lang else LANGUAGE
    
    # Set global CHECK_UPDATES flag
    global CHECK_UPDATES
    CHECK_UPDATES = check_updates
    MODEL = model
    USE_AI_JUDGMENT = use_ai

    INPUT_PH_DIR = INPUT_PH_DIR.format(lang=selected_lang)
    OUTPUT_META_DIR = OUTPUT_META_DIR.format(lang=selected_lang)

    print(f"Language: {selected_lang.upper()}")
    print(f"Input Dir: {INPUT_PH_DIR}")
    print(f"Output Dir: {OUTPUT_META_DIR}")
    print(f"AI Judgment: {'enabled' if USE_AI_JUDGMENT else 'disabled'}")
    
    # Ensure output directory exists
    ensure_output_dir()
    
    # Scan placeholder HTML files
    print("Scanning placeholder HTML files...")
    try:
        dataset = scan_ph_files(start_id, end_id)
        print(f"Found {len(dataset)} placeholder HTML files to process.")
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
    print(f"Output Dir: {OUTPUT_META_DIR}")
    print(f"{'='*60}\n")
    
    if len(items_to_process) == 0:
        print("No data needs processing!")
        sys.exit(0)
    
    # Statistics
    processed_count = 0
    error_count = 0
    count_lock = Lock()
    
    # Create progress bar
    pbar = tqdm(total=len(items_to_process), desc="Generating metadata", unit="files")
    
    # Use thread pool for concurrent processing
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_item = {executor.submit(process_single_file, item): item for item in items_to_process}
        
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
    print(f"Metadata generation completed!")
    print(f"Total attempted: {len(items_to_process)}")
    print(f"Successful: {processed_count}")
    print(f"Failed: {error_count}")
    print(f"Results saved in: {OUTPUT_META_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
