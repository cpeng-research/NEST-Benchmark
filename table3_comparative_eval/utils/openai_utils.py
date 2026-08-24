from __future__ import annotations

import os
import re
import threading
from typing import Any


_client_lock = threading.Lock()
_THINK_BLOCK_PATTERNS = (
    re.compile(r"<think\b[^>]*>.*?</think\s*/?>", flags=re.IGNORECASE | re.DOTALL),
    re.compile(r"<think\b[^>]*>.*?<think\s*/>", flags=re.IGNORECASE | re.DOTALL),
)
_TRAILING_SPECIAL_TOKEN_PATTERN = re.compile(
    r"(?:\s*(?:<end_of_turn>|<\|endoftext\|>|</s>|<eos>))+\s*$",
    flags=re.IGNORECASE,
)


def create_client():
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependency: install openai with `pip install openai`.") from exc

    kwargs = {}
    if os.getenv("OPENAI_API_KEY"):
        kwargs["api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.getenv("OPENAI_BASE_URL")
    with _client_lock:
        return OpenAI(**kwargs)


def extract_text(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return strip_thinking(response)
    if hasattr(response, "output_text") and isinstance(response.output_text, str):
        return strip_thinking(response.output_text)
    output = getattr(response, "output", None)
    text = normalize_response_output(output)
    if text:
        return strip_thinking(text)
    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message is not None else None
        text = normalize_content(content)
        if text:
            return strip_thinking(text)
        reasoning_content = getattr(message, "reasoning_content", None) if message is not None else None
        return strip_thinking(normalize_content(reasoning_content))
    if isinstance(response, dict):
        if isinstance(response.get("output_text"), str):
            return strip_thinking(response["output_text"])
        text = normalize_response_output(response.get("output"))
        if text:
            return strip_thinking(text)
        choices = response.get("choices")
        if choices:
            message = choices[0].get("message", {})
            text = normalize_content(message.get("content"))
            if text:
                return strip_thinking(text)
            return strip_thinking(normalize_content(message.get("reasoning_content")))
        return strip_thinking(normalize_content(response.get("content")))
    return strip_thinking(normalize_content(getattr(response, "content", "")))


def normalize_response_output(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, list):
        parts = []
        for item in output:
            if isinstance(item, dict):
                text = normalize_content(item.get("content"))
                if text:
                    parts.append(text)
                    continue
                text_value = item.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
            else:
                content = getattr(item, "content", None)
                text = normalize_content(content)
                if text:
                    parts.append(text)
                    continue
                text_value = getattr(item, "text", None)
                if isinstance(text_value, str):
                    parts.append(text_value)
        return "".join(parts)
    return normalize_content(output)


def strip_thinking(text: str | None) -> str:
    if not text:
        return ""
    cleaned = str(text)
    for pattern in _THINK_BLOCK_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = _TRAILING_SPECIAL_TOKEN_PATTERN.sub("", cleaned)
    return cleaned.strip()


def normalize_content(content: Any) -> str:
    if content is None:
        return ""
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
        return "".join(parts)
    return str(content)
