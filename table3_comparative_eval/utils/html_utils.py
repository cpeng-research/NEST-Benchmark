from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None


@dataclass(frozen=True)
class Placeholder:
    row: int
    col: int
    name: str
    index: int
    cell_text: str


FIRST_TABLE_LAYOUT = "first_table"
ALL_LOGICAL_REGIONS_LAYOUT = "all_logical_regions"
SUPPORTED_LAYOUTS = (FIRST_TABLE_LAYOUT, ALL_LOGICAL_REGIONS_LAYOUT)

# Keep the first table's historical coordinates unchanged while assigning a
# stable, non-overlapping row range to each additional top-level table.
TABLE_ROW_STRIDE = 100_000


def normalize_text(text: str | None) -> str:
    if text is None:
        return ""
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[\[\]{}()<>:：,，.;；。!?！？'\"`_\-/\\|~]", "", text)
    return text.strip()


def cell_texts(
    html: str,
    layout: str = ALL_LOGICAL_REGIONS_LAYOUT,
) -> dict[tuple[int, int], str]:
    if BeautifulSoup is None:
        return _cell_texts_regex(html)
    return {
        pos: cell.get_text(" ", strip=True)
        for pos, cell in cell_nodes(html, layout=layout).items()
    }


def cell_nodes(
    html: str,
    layout: str = ALL_LOGICAL_REGIONS_LAYOUT,
) -> dict[tuple[int, int], Any]:
    """Return each physical table cell or supported form region once."""
    if layout not in SUPPORTED_LAYOUTS:
        raise ValueError(f"Unsupported HTML layout strategy: {layout}")
    if BeautifulSoup is None:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    top_level_tables = [
        table for table in soup.find_all("table") if table.find_parent("table") is None
    ]
    if top_level_tables:
        tables = top_level_tables[:1] if layout == FIRST_TABLE_LAYOUT else top_level_tables
        out: dict[tuple[int, int], Any] = {}
        for table_index, table in enumerate(tables):
            row_offset = table_index * TABLE_ROW_STRIDE
            for (row, col), cell in _table_cell_nodes(table).items():
                out[(row_offset + row, col)] = cell
        return out
    if layout == ALL_LOGICAL_REGIONS_LAYOUT:
        return _div_form_cell_nodes(soup)
    return {}


def _table_cell_nodes(table: Any) -> dict[tuple[int, int], Any]:
    grid: dict[tuple[int, int], Any] = {}
    for r, tr in enumerate(table.find_all("tr")):
        c = 0
        for cell in tr.find_all(["td", "th"]):
            while (r, c) in grid:
                c += 1
            rowspan = _safe_span(cell.get("rowspan"))
            colspan = _safe_span(cell.get("colspan"))
            for rr in range(r, r + rowspan):
                for cc in range(c, c + colspan):
                    grid[(rr, cc)] = cell
            c += colspan
    first_positions: dict[int, tuple[int, int]] = {}
    for pos, cell in grid.items():
        key = id(cell)
        if key not in first_positions or pos < first_positions[key]:
            first_positions[key] = pos
    return {pos: grid[pos] for pos in sorted(first_positions.values()) if pos in grid}


def _div_form_cell_nodes(soup: Any) -> dict[tuple[int, int], Any]:
    """Map the project's row/column div forms to stable logical regions."""
    container = soup.select_one(".form-container")
    if container is None:
        return {}

    out: dict[tuple[int, int], Any] = {}
    logical_row = 0
    for row in container.find_all("div", recursive=False):
        if "row" not in (row.get("class") or []):
            continue
        cells = [
            child
            for child in row.find_all("div", recursive=False)
            if {"col", "col-half", "col-full"}.intersection(child.get("class") or [])
        ]
        if not cells:
            continue
        for col, cell in enumerate(cells):
            out[(logical_row, col)] = cell
        logical_row += 1
    return out


def placeholders_by_cell(
    html: str,
    layout: str = ALL_LOGICAL_REGIONS_LAYOUT,
) -> list[Placeholder]:
    cells = cell_texts(html, layout=layout)
    counters: Counter[tuple[int, int, str]] = Counter()
    found: list[Placeholder] = []
    for (row, col), text in cells.items():
        for match in re.finditer(r"\[([^\[\]]+)\]", text):
            name = match.group(1).strip()
            key = (row, col, normalize_text(name))
            idx = counters[key]
            counters[key] += 1
            found.append(Placeholder(row=row, col=col, name=name, index=idx, cell_text=text))
    return found


def placeholder_counter(
    html: str,
    layout: str = ALL_LOGICAL_REGIONS_LAYOUT,
) -> Counter[tuple[int, int, str, int]]:
    counter: Counter[tuple[int, int, str, int]] = Counter()
    for ph in placeholders_by_cell(html, layout=layout):
        counter[(ph.row, ph.col, normalize_text(ph.name), ph.index)] += 1
    return counter


def _safe_span(value: Any) -> int:
    try:
        if value is None:
            return 1
        match = re.search(r"\d+", str(value))
        return max(1, int(match.group(0))) if match else 1
    except Exception:
        return 1


def _cell_texts_regex(html: str) -> dict[tuple[int, int], str]:
    rows = re.findall(r"<tr[\s\S]*?</tr>", html, flags=re.I)
    out: dict[tuple[int, int], str] = {}
    for r, row_html in enumerate(rows):
        cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row_html, flags=re.I)
        for c, cell in enumerate(cells):
            text = re.sub(r"<[^>]+>", " ", cell)
            out[(r, c)] = re.sub(r"\s+", " ", text).strip()
    return out
