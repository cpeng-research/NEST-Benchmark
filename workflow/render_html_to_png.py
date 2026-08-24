from __future__ import annotations

import argparse
import base64
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PRESETS = {
    "empty": {
        "en": (
            PROJECT_ROOT / "workflow" / "0-html_template" / "data_en",
            PROJECT_ROOT / "workflow" / "9-png-a" / "data_en" / "empty",
        ),
        "zh": (
            PROJECT_ROOT / "workflow" / "0-html_template" / "data_zh",
            PROJECT_ROOT / "workflow" / "9-png-a" / "data_zh" / "empty",
        ),
    },
    "filled": {
        "en": (
            PROJECT_ROOT / "workflow" / "3-filled_html-a" / "data_en",
            PROJECT_ROOT / "workflow" / "9-png-a" / "data_en" / "filled",
        ),
        "zh": (
            PROJECT_ROOT / "workflow" / "3-filled_html-a" / "data_zh",
            PROJECT_ROOT / "workflow" / "9-png-a" / "data_zh" / "filled",
        ),
    },
}

DEFAULT_CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
    "chromium-browser",
]

GRIDLINE_CSS = """
html, body {
  background: #ffffff !important;
}
table {
  border-collapse: collapse !important;
  border-spacing: 0 !important;
}
table.html-png-fixed-grid-table {
  table-layout: fixed !important;
}
th.html-png-grid-cell,
td.html-png-grid-cell {
  border: 1px solid #000000 !important;
}
th, td {
  box-sizing: border-box !important;
  overflow-wrap: anywhere !important;
  word-break: normal !important;
  white-space: normal !important;
  vertical-align: top !important;
}
th > *, td > * {
  box-sizing: border-box !important;
  max-width: 100% !important;
}
input, select, textarea, img, svg, canvas, video {
  box-sizing: border-box !important;
  max-width: 100% !important;
}
body > :not(table):not(script):not(style) {
  box-sizing: border-box !important;
  overflow-wrap: anywhere !important;
  word-break: normal !important;
  white-space: normal !important;
}
tr.html-png-empty-row > th,
tr.html-png-empty-row > td {
  height: var(--html-png-empty-row-height, 28px) !important;
  min-height: var(--html-png-empty-row-height, 28px) !important;
}
tr:not(.html-png-empty-row) > th.html-png-empty-cell::after,
tr:not(.html-png-empty-row) > td.html-png-empty-cell::after {
  content: "";
  display: inline-block;
  width: var(--html-png-empty-cell-width, 96px);
  height: 1em;
}
"""


@dataclass(frozen=True)
class RenderTask:
    source: Path
    output: Path
    strip_legacy_placeholders: bool = False


@dataclass(frozen=True)
class RenderAudit:
    source: str
    output: str
    pixel_width: int
    pixel_height: int
    repaired_rows: int
    unresolved_rows: int
    overflowing_cells: int
    overflowing_elements: int
    source_transform: str

    @property
    def ok(self) -> bool:
        return not (self.unresolved_rows or self.overflowing_cells or self.overflowing_elements)


class ChromeRenderer:
    def __init__(
        self,
        chrome_path: str,
        viewport_width: int,
        viewport_height: int,
        device_scale_factor: float,
        wait_ms: int,
        timeout: float,
        gridlines: bool,
        empty_row_height: int,
        empty_cell_width: int,
        normalize_table_widths: bool,
        normalize_block_widths: bool,
        normalize_colspans: bool,
        crop_to_content: bool,
        crop_margin: int,
    ) -> None:
        self.chrome_path = chrome_path
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.device_scale_factor = device_scale_factor
        self.wait_ms = wait_ms
        self.timeout = timeout
        self.gridlines = gridlines
        self.empty_row_height = empty_row_height
        self.empty_cell_width = empty_cell_width
        self.normalize_table_widths = normalize_table_widths
        self.normalize_block_widths = normalize_block_widths
        self.normalize_colspans = normalize_colspans
        self.crop_to_content = crop_to_content
        self.crop_margin = crop_margin
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self._proc: subprocess.Popen[str] | None = None
        self._ws: DevToolsWebSocket | None = None
        self._port = 0

    def __enter__(self) -> "ChromeRenderer":
        self._tmpdir = tempfile.TemporaryDirectory(prefix="html_png_chrome_")
        self._port = find_free_port()
        cmd = [
            self.chrome_path,
            "--headless=new",
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self._tmpdir.name}",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        page_ws_url = self._wait_for_page_websocket()
        self._ws = DevToolsWebSocket(page_ws_url, timeout=self.timeout)
        self._ws.call("Page.enable")
        self._ws.call("Runtime.enable")
        self._ws.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": self.viewport_width,
                "height": self.viewport_height,
                "deviceScaleFactor": self.device_scale_factor,
                "mobile": False,
            },
        )
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._ws is not None:
            self._ws.close()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=3)
        if self._tmpdir is not None:
            self._tmpdir.cleanup()

    def render(self, source: Path, output: Path, strip_legacy_placeholders: bool = False) -> RenderAudit:
        if self._ws is None:
            raise RuntimeError("ChromeRenderer is not started")
        file_url = source.resolve().as_uri()
        self._ws.call("Page.navigate", {"url": file_url})
        self._ws.wait_for_event("Page.loadEventFired", timeout=self.timeout)
        self._wait_for_document_ready()
        if strip_legacy_placeholders:
            self._strip_legacy_placeholders()
        layout_audit: dict[str, Any] = {}
        if self.gridlines:
            layout_audit = self._inject_gridlines()
        if self.wait_ms:
            time.sleep(self.wait_ms / 1000)

        metrics = self._ws.call("Page.getLayoutMetrics")
        content = metrics["contentSize"]
        content_width = max(1, math.ceil(content.get("width", self.viewport_width)))
        content_height = max(1, math.ceil(content.get("height", self.viewport_height)))
        clip = {"x": 0, "y": 0, "width": content_width, "height": content_height, "scale": 1}
        if self.crop_to_content:
            bounds = self._content_bounds()
            if bounds is not None:
                margin = max(0, self.crop_margin)
                left = max(0, math.floor(bounds["left"] - margin))
                top = max(0, math.floor(bounds["top"] - margin))
                right = min(content_width, math.ceil(bounds["right"] + margin))
                bottom = min(content_height, math.ceil(bounds["bottom"] + margin))
                if right > left and bottom > top:
                    clip = {
                        "x": left,
                        "y": top,
                        "width": max(1, right - left),
                        "height": max(1, bottom - top),
                        "scale": 1,
                    }
        screenshot = self._ws.call(
            "Page.captureScreenshot",
            {
                "format": "png",
                "fromSurface": True,
                "captureBeyondViewport": True,
                "clip": clip,
            },
            timeout=max(self.timeout, 60),
        )
        png_bytes = base64.b64decode(screenshot["data"])
        if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("Chrome returned an invalid PNG payload")
        pixel_width, pixel_height = struct.unpack(">II", png_bytes[16:24])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(png_bytes)
        return RenderAudit(
            source=project_relative(source),
            output=project_relative(output),
            pixel_width=pixel_width,
            pixel_height=pixel_height,
            repaired_rows=int(layout_audit.get("repairedRows", 0)),
            unresolved_rows=int(layout_audit.get("unresolvedRows", 0)),
            overflowing_cells=int(layout_audit.get("overflowingCells", 0)),
            overflowing_elements=int(layout_audit.get("overflowingElements", 0)),
            source_transform="strip_legacy_placeholders" if strip_legacy_placeholders else "none",
        )

    def _wait_for_document_ready(self) -> None:
        assert self._ws is not None
        self._ws.call(
            "Runtime.evaluate",
            {
                "expression": (
                    "new Promise(resolve => {"
                    "  const done = () => {"
                    "    if (document.fonts && document.fonts.ready) {"
                    "      document.fonts.ready.then(() => resolve(true));"
                    "    } else { resolve(true); }"
                    "  };"
                    "  if (document.readyState === 'complete') done();"
                    "  else window.addEventListener('load', done, { once: true });"
                    "})"
                ),
                "awaitPromise": True,
            },
        )

    def _content_bounds(self) -> dict[str, float] | None:
        assert self._ws is not None
        result = self._ws.call(
            "Runtime.evaluate",
            {
                "expression": (
                    "(() => {"
                    "  const ignored = new Set(['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT']);"
                    "  const rects = [];"
                    "  const visible = element => {"
                    "    const style = window.getComputedStyle(element);"
                    "    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';"
                    "  };"
                    "  for (const element of Array.from(document.body.children)) {"
                    "    if (ignored.has(element.tagName) || !visible(element)) continue;"
                    "    const rect = element.getBoundingClientRect();"
                    "    const hasText = element.textContent.replace(/\\u00a0/g, ' ').trim().length > 0;"
                    "    const hasMedia = !!element.querySelector('table, input, select, textarea, img, svg, canvas, video');"
                    "    if ((rect.width <= 0 || rect.height <= 0) && !hasText && !hasMedia) continue;"
                    "    rects.push({"
                    "      left: rect.left + window.scrollX,"
                    "      top: rect.top + window.scrollY,"
                    "      right: rect.right + window.scrollX,"
                    "      bottom: rect.bottom + window.scrollY"
                    "    });"
                    "  }"
                    "  if (!rects.length) return null;"
                    "  return {"
                    "    left: Math.min(...rects.map(rect => rect.left)),"
                    "    top: Math.min(...rects.map(rect => rect.top)),"
                    "    right: Math.max(...rects.map(rect => rect.right)),"
                    "    bottom: Math.max(...rects.map(rect => rect.bottom))"
                    "  };"
                    "})()"
                ),
                "returnByValue": True,
            },
        )
        value = result.get("result", {}).get("value")
        if not isinstance(value, dict):
            return None
        required = ("left", "top", "right", "bottom")
        if not all(isinstance(value.get(key), (int, float)) for key in required):
            return None
        return {key: float(value[key]) for key in required}

    def _strip_legacy_placeholders(self) -> None:
        assert self._ws is not None
        self._ws.call(
            "Runtime.evaluate",
            {
                "expression": (
                    "(() => {"
                    "  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);"
                    "  const nodes = [];"
                    "  while (walker.nextNode()) nodes.push(walker.currentNode);"
                    "  for (const node of nodes) {"
                    "    node.nodeValue = node.nodeValue.replace(/\\[[^\\[\\]\\r\\n]{1,120}\\]/g, '');"
                    "  }"
                    "  return nodes.length;"
                    "})()"
                ),
                "returnByValue": True,
            },
        )

    def _inject_gridlines(self) -> dict[str, Any]:
        assert self._ws is not None
        result = self._ws.call(
            "Runtime.evaluate",
            {
                "expression": (
                    "(() => {"
                    f"  document.documentElement.style.setProperty('--html-png-empty-row-height', '{self.empty_row_height}px');"
                    f"  const emptyCellWidth = {self.empty_cell_width};"
                    "  const audit = { repairedRows: 0, unresolvedRows: 0, overflowingCells: 0, overflowingElements: 0 };"
                    "    const directRows = table => {"
                    "      const rows = [];"
                    "      if (table.tHead) rows.push(...Array.from(table.tHead.rows));"
                    "      for (const body of Array.from(table.tBodies || [])) rows.push(...Array.from(body.rows));"
                    "      if (table.tFoot) rows.push(...Array.from(table.tFoot.rows));"
                    "      rows.push(...Array.from(table.children).filter(child => child.tagName === 'TR'));"
                    "      return Array.from(new Set(rows));"
                    "    };"
                    "  const parseSpan = (element, name) => {"
                    "    const value = Number(element.getAttribute(name) || 1);"
                    "    return Number.isFinite(value) && value > 0 ? Math.floor(value) : 1;"
                    "  };"
                    "  const positiveBorderAttr = element => {"
                    "    const value = element.getAttribute('border');"
                    "    if (value === null) return false;"
                    "    const normalized = value.trim();"
                    "    return normalized === '' || Number(normalized) > 0;"
                    "  };"
                    "  const inlineBorderStyle = element => {"
                    "    const style = element.getAttribute('style') || '';"
                    "    return /(?:^|;)\\s*border(?:-(?:top|right|bottom|left))?\\s*:\\s*(?!\\s*(?:0|none|hidden)\\b)[^;]+/i.test(style);"
                    "  };"
                    "  const tableWantsGrid = table => {"
                    "    if (positiveBorderAttr(table) || inlineBorderStyle(table)) return true;"
                    "    if (table.getAttribute('border') !== null) return false;"
                    "    return !table.closest('td, th');"
                    "  };"
                    "  const hasExplicitColumnHints = table => {"
                    "    if (table.querySelector('colgroup, col')) return true;"
                    "    return directRows(table).some(row => Array.from(row.cells || []).some(cell => {"
                    "      const style = cell.getAttribute('style') || '';"
                    "      return cell.getAttribute('width') !== null || /(?:^|;)\\s*width\\s*:/i.test(style);"
                    "    }));"
                    "  };"
                    "  const installEqualColgroup = (table, columns) => {"
                    "    if (columns < 2 || table.querySelector('colgroup, col')) return;"
                    "    const width = Math.max(1, Math.ceil(table.getBoundingClientRect().width));"
                    "    const colgroup = document.createElement('colgroup');"
                    "    for (let index = 0; index < columns; index += 1) {"
                    "      const col = document.createElement('col');"
                    "      col.style.width = `${100 / columns}%`;"
                    "      colgroup.appendChild(col);"
                    "    }"
                    "    table.insertBefore(colgroup, table.firstChild);"
                    "    table.classList.add('html-png-fixed-grid-table');"
                    "    table.style.width = `${width}px`;"
                    "  };"
                    "  const tableGrid = table => {"
                    "      const rows = directRows(table);"
                    "      const active = [];"
                    "      const infos = [];"
                    "      for (const row of rows) {"
                    "        let col = 0;"
                    "        const placements = [];"
                    "        const occupiedBefore = active.reduce((max, value, index) => value > 0 ? Math.max(max, index + 1) : max, 0);"
                    "        for (const cell of Array.from(row.cells || [])) {"
                    "          while ((active[col] || 0) > 0) col += 1;"
                    "          const colspan = parseSpan(cell, 'colspan');"
                    "          const rowspan = parseSpan(cell, 'rowspan');"
                    "          placements.push({ cell, col, colspan, rowspan });"
                    "          for (let offset = 0; offset < colspan; offset += 1) {"
                    "            active[col + offset] = Math.max(active[col + offset] || 0, rowspan);"
                    "          }"
                    "          col += colspan;"
                    "        }"
                    "        const width = Math.max(col, occupiedBefore, active.reduce((max, value, index) => value > 0 ? Math.max(max, index + 1) : max, 0));"
                    "        infos.push({ row, width, placements });"
                    "        for (let index = 0; index < active.length; index += 1) {"
                    "          if ((active[index] || 0) > 0) active[index] -= 1;"
                    "        }"
                    "      }"
                    "      return infos;"
                    "  };"
                    "  const isStaggeredRowStart = (info, target) => ("
                    "    info.width < target &&"
                    "    info.placements.length > 0 &&"
                    "    info.placements.every(item => item.rowspan > 1)"
                    "  );"
                    f"  if ({json.dumps(self.normalize_colspans)}) {{"
                    "    for (const table of document.querySelectorAll('table')) {"
                    "      const infos = tableGrid(table);"
                    "      const counts = infos.map(info => info.width).filter(count => count > 0);"
                    "      if (counts.length < 2) continue;"
                    "      const frequencies = new Map();"
                    "      for (const count of counts) frequencies.set(count, (frequencies.get(count) || 0) + 1);"
                    "      let target = counts[0];"
                    "      for (const [count, freq] of frequencies) {"
                    "        const best = frequencies.get(target) || 0;"
                    "        if (freq > best || (freq === best && count < target)) target = count;"
                    "      }"
                    "      for (const info of infos) {"
                    "        const reducible = info.placements.reduce((total, item) => total + Math.max(0, item.colspan - 1), 0);"
                    "        target = Math.max(target, info.width - reducible);"
                    "      }"
                    "      const shouldInstallColgroup = new Set(counts).size > 1 && !hasExplicitColumnHints(table);"
                    "      for (const info of infos) {"
                    "        let excess = info.width - target;"
                    "        if (excess <= 0) continue;"
                    "        const adjustable = info.placements"
                    "          .filter(item => item.colspan > 1)"
                    "          .sort((a, b) => b.colspan - a.colspan);"
                    "        for (const item of adjustable) {"
                    "          if (excess <= 0) break;"
                    "          const span = parseSpan(item.cell, 'colspan');"
                    "          const reduction = Math.min(excess, span - 1);"
                    "          if (reduction > 0) {"
                    "            item.cell.setAttribute('colspan', String(span - reduction));"
                    "            excess -= reduction;"
                    "          }"
                    "        }"
                    "      }"
                    "      const reducedInfos = tableGrid(table);"
                    "      for (const info of reducedInfos) {"
                    "        const deficit = target - info.width;"
                    "        if (deficit <= 0 || !info.placements.length) continue;"
                    "        if (isStaggeredRowStart(info, target)) continue;"
                    "        const placements = info.placements;"
                    "        if (placements.length >= 4 && placements.length % 2 === 0 && deficit <= placements.length / 2) {"
                    "          let remaining = deficit;"
                    "          for (let index = 1; index < placements.length && remaining > 0; index += 2) {"
                    "            const cell = placements[index].cell;"
                    "            cell.setAttribute('colspan', String(parseSpan(cell, 'colspan') + 1));"
                    "            remaining -= 1;"
                    "          }"
                    "          if (remaining > 0) {"
                    "            const cell = placements[placements.length - 1].cell;"
                    "            cell.setAttribute('colspan', String(parseSpan(cell, 'colspan') + remaining));"
                    "          }"
                    "        } else {"
                    "          const cell = placements[placements.length - 1].cell;"
                    "          cell.setAttribute('colspan', String(parseSpan(cell, 'colspan') + deficit));"
                    "        }"
                    "        info.row.classList.add('html-png-repaired-row');"
                    "        audit.repairedRows += 1;"
                    "      }"
                    "      table.dataset.htmlPngTargetColumns = String(target);"
                    "      if (shouldInstallColgroup) installEqualColgroup(table, target);"
                    "    }"
                    "  }"
                    "  for (const table of document.querySelectorAll('table')) {"
                    "    const tableGridWanted = tableWantsGrid(table);"
                    "    for (const row of directRows(table)) {"
                    "      for (const cell of Array.from(row.cells || [])) {"
                    "        if (tableGridWanted || positiveBorderAttr(cell) || inlineBorderStyle(cell)) {"
                    "          cell.classList.add('html-png-grid-cell');"
                    "        }"
                    "      }"
                    "    }"
                    "  }"
                    "  for (const row of document.querySelectorAll('tr')) {"
                    "    const cells = Array.from(row.cells || []);"
                    "    if (!cells.length) continue;"
                    "    const cellEmpty = cell => ("
                    "      cell.textContent.replace(/\\u00a0/g, ' ').trim().length === 0 &&"
                    "      !cell.querySelector('input, select, textarea, img, svg, canvas, video')"
                    "    );"
                    "    const emptyCells = cells.filter(cellEmpty);"
                    "    if (emptyCells.length === cells.length) {"
                    "      row.classList.add('html-png-empty-row');"
                    "    } else {"
                    "      for (const cell of emptyCells) {"
                    "        const colspan = parseSpan(cell, 'colspan');"
                    "        cell.classList.add('html-png-empty-cell');"
                    "        cell.style.setProperty('--html-png-empty-cell-width', `${Math.min(emptyCellWidth * colspan, emptyCellWidth * 4)}px`);"
                    "      }"
                    "    }"
                    "  }"
                    "  const style = document.createElement('style');"
                    f"  style.textContent = {json.dumps(GRIDLINE_CSS)};"
                    "  document.head.appendChild(style);"
                    "    const topTables = Array.from(document.querySelectorAll('table')).filter(table => !table.parentElement.closest('table'));"
                    "    const tableWidths = topTables.map(table => table.getBoundingClientRect().width).filter(width => Number.isFinite(width) && width > 0);"
                    "    const maxWidth = tableWidths.length ? Math.max(...tableWidths) : 0;"
                    f"  if ({json.dumps(self.normalize_table_widths)}) {{"
                    "    if (topTables.length > 1 && maxWidth > 0) {"
                    "        for (const table of topTables) {"
                    "          if (table.getBoundingClientRect().width < maxWidth - 1) {"
                    "            table.style.width = `${maxWidth}px`;"
                    "          }"
                    "        }"
                    "    }"
                    "  }"
                    f"  if ({json.dumps(self.normalize_block_widths)}) {{"
                    "    if (maxWidth > 0) {"
                    "      for (const child of Array.from(document.body.children)) {"
                    "        if (child.matches('table, script, style')) continue;"
                    "        child.style.maxWidth = `${maxWidth}px`;"
                    "      }"
                    "    }"
                    "  }"
                    "  for (const table of document.querySelectorAll('table[data-html-png-target-columns]')) {"
                    "    const target = Number(table.dataset.htmlPngTargetColumns);"
                    "    audit.unresolvedRows += tableGrid(table).filter(info => ("
                    "      info.placements.length && info.width !== target && !isStaggeredRowStart(info, target)"
                    "    )).length;"
                    "  }"
                    "  for (const table of document.querySelectorAll('table')) {"
                    "    const tableRect = table.getBoundingClientRect();"
                    "    for (const row of directRows(table)) {"
                    "      for (const cell of Array.from(row.cells || [])) {"
                    "        const cellRect = cell.getBoundingClientRect();"
                    "        if (cellRect.left < tableRect.left - 1 || cellRect.right > tableRect.right + 1) {"
                    "          audit.overflowingCells += 1;"
                    "        }"
                    "        for (const child of Array.from(cell.children)) {"
                    "          const childRect = child.getBoundingClientRect();"
                    "          if (childRect.width > 0 && (childRect.left < cellRect.left - 1 || childRect.right > cellRect.right + 1)) {"
                    "            audit.overflowingElements += 1;"
                    "          }"
                    "        }"
                    "      }"
                    "    }"
                    "  }"
                    "  return audit;"
                    "})()"
                ),
                "returnByValue": True,
            },
        )
        value = result.get("result", {}).get("value")
        return value if isinstance(value, dict) else {}

    def _wait_for_page_websocket(self) -> str:
        deadline = time.time() + self.timeout
        last_error: Exception | None = None
        while time.time() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError(f"Chrome exited early with code {self._proc.returncode}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/json/list", timeout=1) as response:
                    targets = json.loads(response.read().decode("utf-8"))
                for target in targets:
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        return str(target["webSocketDebuggerUrl"])
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            time.sleep(0.1)
        raise RuntimeError(f"Timed out waiting for Chrome DevTools endpoint: {last_error}")


class DevToolsWebSocket:
    def __init__(self, url: str, timeout: float = 30) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "ws":
            raise ValueError(f"Only ws:// DevTools URLs are supported, got: {url}")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path
        if parsed.query:
            self.path += f"?{parsed.query}"
        self.timeout = timeout
        self._sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._id = 0
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._handshake()

    def close(self) -> None:
        try:
            self._send_frame(b"", opcode=8)
        except OSError:
            pass
        self._sock.close()

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
            self._id += 1
            msg_id = self._id
            payload: dict[str, Any] = {"id": msg_id, "method": method}
            if params is not None:
                payload["params"] = params
            self._send_text(json.dumps(payload, separators=(",", ":")))
            deadline = time.time() + (timeout or self.timeout)
            while time.time() < deadline:
                message = self._read_message(deadline)
                if "method" in message:
                    self._events.append(message)
                    continue
                if message.get("id") != msg_id:
                    continue
                if "error" in message:
                    raise RuntimeError(f"DevTools {method} failed: {message['error']}")
                return dict(message.get("result", {}))
        raise TimeoutError(f"Timed out waiting for DevTools response: {method}")

    def wait_for_event(self, method: str, timeout: float | None = None) -> dict[str, Any]:
        deadline = time.time() + (timeout or self.timeout)
        with self._lock:
            while time.time() < deadline:
                for index, event in enumerate(self._events):
                    if event.get("method") == method:
                        return self._events.pop(index)
                message = self._read_message(deadline)
                if "method" in message:
                    if message.get("method") == method:
                        return message
                    self._events.append(message)
        raise TimeoutError(f"Timed out waiting for DevTools event: {method}")

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        self._sock.sendall(request)
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._sock.recv(4096)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WebSocket handshake failed: {response[:200]!r}")

    def _send_text(self, text: str) -> None:
        self._send_frame(text.encode("utf-8"), opcode=1)

    def _send_frame(self, payload: bytes, opcode: int) -> None:
        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._sock.sendall(header + mask + masked)

    def _read_message(self, deadline: float) -> dict[str, Any]:
        chunks: list[bytes] = []
        while True:
            remaining = max(0.1, deadline - time.time())
            self._sock.settimeout(remaining)
            first, second = self._read_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 8:
                raise RuntimeError("DevTools WebSocket closed")
            if opcode == 9:
                self._send_frame(payload, opcode=10)
                continue
            if opcode in (1, 2, 0):
                chunks.append(payload)
                if fin:
                    data = b"".join(chunks)
                    if opcode == 2:
                        raise RuntimeError("Unexpected binary DevTools message")
                    return json.loads(data.decode("utf-8"))

    def _read_exact(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = self._sock.recv(size - len(data))
            if not chunk:
                raise RuntimeError("Unexpected EOF from DevTools WebSocket")
            data += chunk
        return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Render HTML table/page files to PNG images with headless Chrome.")
    parser.add_argument(
        "--preset",
        choices=PRESETS,
        required=True,
        help="empty=workflow/0-html_template; filled=workflow/3-filled_html-a",
    )
    parser.add_argument("--lang", choices=["en", "zh", "both"], default="both")
    parser.add_argument("--start_id", default="", help="Optional numeric start ID.")
    parser.add_argument("--end_id", default="", help="Optional numeric end ID.")
    parser.add_argument(
        "--update-mode",
        choices=["check", "missing-only", "force"],
        default="check",
        help="check rerenders stale PNGs; missing-only only creates missing PNGs; force rerenders all.",
    )
    parser.add_argument("--workers", type=int, default=2, help="Number of Chrome workers.")
    parser.add_argument("--viewport-width", type=int, default=1000)
    parser.add_argument("--viewport-height", type=int, default=900)
    parser.add_argument("--scale", type=float, default=1.0, help="Chrome device scale factor.")
    parser.add_argument("--wait-ms", type=int, default=100, help="Extra wait after page load before capture.")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--chrome", default="", help="Optional path to Chrome/Chromium executable.")
    parser.add_argument("--empty-row-height", type=int, default=28, help="Minimum pixel height for rows whose cells are all empty.")
    parser.add_argument("--empty-cell-width", type=int, default=64, help="Minimum content width in pixels for empty cells in otherwise non-empty rows.")
    parser.add_argument(
        "--no-normalize-table-widths",
        action="store_true",
        help="Do not align multiple top-level tables on the same page to the widest table.",
    )
    parser.add_argument(
        "--no-normalize-block-widths",
        action="store_true",
        help="Do not constrain body-level text blocks to the widest top-level table width.",
    )
    parser.add_argument(
        "--no-normalize-colspans",
        action="store_true",
        help="Do not normalize inconsistent logical column counts in malformed HTML tables.",
    )
    parser.add_argument(
        "--no-gridlines",
        action="store_true",
        help="Do not inject CSS borders for table gridlines before screenshot.",
    )
    parser.add_argument(
        "--crop-to-content",
        action="store_true",
        help="Crop the screenshot to the visible body content bounds instead of the full viewport/content area.",
    )
    parser.add_argument("--crop-margin", type=int, default=8, help="Pixel margin to keep around cropped content.")
    parser.add_argument(
        "--audit-report",
        type=Path,
        default=None,
        help="Optional JSON report for every rendered page, relative to the project root unless absolute.",
    )
    parser.add_argument(
        "--fail-on-audit",
        action="store_true",
        help="Exit nonzero if a rendered page still contains unresolved grid rows or horizontal overflow.",
    )
    args = parser.parse_args()

    chrome_path = resolve_chrome(args.chrome)
    langs = ("en", "zh") if args.lang == "both" else (args.lang,)
    tasks = collect_tasks(args.preset, langs, args.start_id, args.end_id, args.update_mode)
    if not tasks:
        print("No HTML files need rendering.", flush=True)
        return

    workers = max(1, min(args.workers, len(tasks)))
    print(
        f"Rendering {len(tasks)} HTML files with {workers} Chrome worker(s). "
        f"preset={args.preset}, lang={args.lang}, update_mode={args.update_mode}",
        flush=True,
    )
    chunks = [tasks[index::workers] for index in range(workers)]
    failures: list[tuple[RenderTask, str]] = []
    audits: list[RenderAudit] = []
    rendered = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                render_chunk,
                chunk,
                chrome_path,
                args.viewport_width,
                args.viewport_height,
                args.scale,
                args.wait_ms,
                args.timeout,
                not args.no_gridlines,
                args.empty_row_height,
                args.empty_cell_width,
                not args.no_normalize_table_widths,
                not args.no_normalize_block_widths,
                not args.no_normalize_colspans,
                args.crop_to_content,
                args.crop_margin,
            )
            for chunk in chunks
            if chunk
        ]
        for future in as_completed(futures):
            count, chunk_failures, chunk_audits = future.result()
            rendered += count
            failures.extend(chunk_failures)
            audits.extend(chunk_audits)
            print(f"Progress: rendered={rendered}, failed={len(failures)}", flush=True)

    audits.sort(key=lambda item: (item.source.casefold(), item.source))
    if args.audit_report is not None:
        report_path = args.audit_report if args.audit_report.is_absolute() else PROJECT_ROOT / args.audit_report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        items_by_output: dict[str, dict[str, Any]] = {}
        if report_path.exists():
            try:
                previous = json.loads(report_path.read_text(encoding="utf-8"))
                for item in previous.get("items", []):
                    if isinstance(item, dict) and isinstance(item.get("output"), str):
                        item.setdefault("source_transform", "none")
                        items_by_output[item["output"]] = item
            except (OSError, json.JSONDecodeError):
                pass
        for audit in audits:
            items_by_output[audit.output] = {**audit.__dict__, "ok": audit.ok}
        report_items = sorted(items_by_output.values(), key=lambda item: str(item.get("output", "")).casefold())
        report = {
            "preset": args.preset,
            "language": args.lang,
            "rendered_this_run": rendered,
            "failed_this_run": len(failures),
            "audited_items": len(report_items),
            "layout_audit_failures": sum(not bool(item.get("ok")) for item in report_items),
            "items": report_items,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Audit report: {report_path}", flush=True)

    if failures:
        print("\nFailed renders:", flush=True)
        for task, error in failures[:50]:
            print(f"- {task.source} -> {task.output}: {error}", flush=True)
        if len(failures) > 50:
            print(f"... {len(failures) - 50} more failures omitted", flush=True)
        raise SystemExit(1)
    audit_failures = [audit for audit in audits if not audit.ok]
    if audit_failures:
        print("\nLayout audit warnings:", flush=True)
        for audit in audit_failures[:50]:
            print(
                f"- {audit.output}: unresolved_rows={audit.unresolved_rows}, "
                f"overflowing_cells={audit.overflowing_cells}, "
                f"overflowing_elements={audit.overflowing_elements}",
                flush=True,
            )
        if len(audit_failures) > 50:
            print(f"... {len(audit_failures) - 50} more audit warnings omitted", flush=True)
        if args.fail_on_audit:
            raise SystemExit(2)
    print(f"Done. Rendered {rendered} PNG files.", flush=True)


def render_chunk(
    tasks: list[RenderTask],
    chrome_path: str,
    viewport_width: int,
    viewport_height: int,
    scale: float,
    wait_ms: int,
    timeout: float,
    gridlines: bool,
    empty_row_height: int,
    empty_cell_width: int,
    normalize_table_widths: bool,
    normalize_block_widths: bool,
    normalize_colspans: bool,
    crop_to_content: bool,
    crop_margin: int,
) -> tuple[int, list[tuple[RenderTask, str]], list[RenderAudit]]:
    failures: list[tuple[RenderTask, str]] = []
    audits: list[RenderAudit] = []
    rendered = 0
    with ChromeRenderer(
        chrome_path,
        viewport_width,
        viewport_height,
        scale,
        wait_ms,
        timeout,
        gridlines,
        empty_row_height,
        empty_cell_width,
        normalize_table_widths,
        normalize_block_widths,
        normalize_colspans,
        crop_to_content,
        crop_margin,
    ) as renderer:
        for task in tasks:
            try:
                audits.append(renderer.render(task.source, task.output, task.strip_legacy_placeholders))
                rendered += 1
            except Exception as exc:  # noqa: BLE001
                failures.append((task, str(exc)))
    return rendered, failures, audits


def collect_tasks(
    preset: str,
    langs: tuple[str, ...],
    start_id: str,
    end_id: str,
    update_mode: str,
) -> list[RenderTask]:
    start = optional_int(start_id, "--start_id")
    end = optional_int(end_id, "--end_id")
    tasks: list[RenderTask] = []
    for lang in langs:
        source_dir, output_dir = PRESETS[preset][lang]
        if not source_dir.exists():
            print(f"Warning: source directory does not exist: {source_dir}", flush=True)
            continue
        output_dir.mkdir(parents=True, exist_ok=True)
        for source in sorted(source_dir.iterdir(), key=html_sort_key):
            if not source.is_file() or source.suffix.lower() != ".html":
                continue
            sample_id = numeric_stem(source)
            if start is not None and (sample_id is None or sample_id < start):
                continue
            if end is not None and (sample_id is None or sample_id > end):
                continue
            output = output_dir / f"{source.stem}.png"
            render_source = source
            strip_legacy_placeholders = False
            if preset == "empty" and source.stat().st_size == 0:
                fallback = PROJECT_ROOT / "workflow" / "5-ph_html-a" / f"data_{lang}" / f"{source.stem}.html"
                if fallback.exists() and fallback.stat().st_size > 0:
                    render_source = fallback
                    strip_legacy_placeholders = True
                    print(
                        f"Template source is empty; using placeholder fallback for ID {source.stem}: {fallback}",
                        flush=True,
                    )
            if should_render(render_source, output, update_mode):
                tasks.append(
                    RenderTask(
                        source=render_source,
                        output=output,
                        strip_legacy_placeholders=strip_legacy_placeholders,
                    )
                )
    return tasks


def should_render(source: Path, output: Path, update_mode: str) -> bool:
    if update_mode == "force":
        return True
    if not output.exists():
        return True
    if update_mode == "missing-only":
        return False
    newest_input_mtime = max(source.stat().st_mtime, Path(__file__).stat().st_mtime)
    return output.stat().st_mtime < newest_input_mtime


def project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def optional_int(value: str, flag: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{flag} must be an integer, got: {value}") from exc


def numeric_stem(path: Path) -> int | None:
    try:
        return int(path.stem)
    except ValueError:
        return None


def html_sort_key(path: Path) -> tuple[int, int | str]:
    sample_id = numeric_stem(path)
    return (0, sample_id) if sample_id is not None else (1, path.name)


def resolve_chrome(explicit: str) -> str:
    if explicit:
        chrome = Path(explicit).expanduser()
        if chrome.exists():
            return str(chrome)
        resolved = shutil.which(explicit)
        if resolved:
            return resolved
        raise SystemExit(f"Chrome executable not found: {explicit}")
    for candidate in DEFAULT_CHROME_PATHS:
        path = Path(candidate)
        if path.exists():
            return str(path)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise SystemExit("Chrome/Chromium executable not found. Use --chrome to specify it.")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    main()
