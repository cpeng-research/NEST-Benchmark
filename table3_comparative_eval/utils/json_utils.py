from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from table3_comparative_eval.config import ROOT


ROOT_JSON_REPAIR_SRC = ROOT / "json_repair" / "src"
JSON_REPAIR_SRC = ROOT_JSON_REPAIR_SRC
if JSON_REPAIR_SRC.exists() and str(JSON_REPAIR_SRC) not in sys.path:
    sys.path.insert(0, str(JSON_REPAIR_SRC))

try:
    from json_repair import repair_json as _repair_json  # type: ignore
except Exception:  # pragma: no cover - optional dependency path
    _repair_json = None


def extract_first_json(text_or_obj: Any) -> Any:
    if isinstance(text_or_obj, (dict, list)):
        return text_or_obj
    if not isinstance(text_or_obj, str):
        return text_or_obj
    text = text_or_obj.strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass

    starts = [idx for idx in (text.find("{"), text.find("[")) if idx >= 0]
    if not starts:
        return text
    start = min(starts)
    stack: list[str] = []
    in_str = False
    escape = False
    for pos, ch in enumerate(text[start:], start=start):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
        if not stack and pos > start:
            candidate = text[start : pos + 1]
            try:
                return json.loads(candidate)
            except Exception:
                break
    return text[start:]


def parse_json_lenient(text_or_obj: Any) -> tuple[Any | None, str]:
    extracted = extract_first_json(text_or_obj)
    if isinstance(extracted, (dict, list)):
        return extracted, "ok"
    if extracted is None:
        return None, "empty"
    if not isinstance(extracted, str):
        return extracted, "non_string"
    try:
        return json.loads(extracted), "ok"
    except Exception:
        pass
    if _repair_json is not None:
        try:
            repaired = _repair_json(extracted, ensure_ascii=False, skip_json_loads=True)
            return json.loads(repaired), "repaired"
        except Exception:
            return None, "unrepairable"
    return None, "unrepairable"


def normalize_json_text(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {normalize_key(k): normalize_json_text(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_json_text(v) for v in obj]
    if isinstance(obj, str):
        value = re.sub(r"[\s:：。，、；;]", "", obj)
        return value
    return obj


def normalize_key(key: Any) -> str:
    return re.sub(r"[\s:：。，、；;]", "", str(key))
