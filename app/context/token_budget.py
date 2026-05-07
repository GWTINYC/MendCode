from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def estimate_token_count(value: Any) -> int:
    text = _normalize_value(value)
    if not text:
        return 0
    tokenizer = _load_tokenizer()
    if tokenizer is not None:
        try:
            return len(tokenizer.encode(text))
        except Exception:  # pragma: no cover - optional adapter guard
            pass
    return _heuristic_token_count(text)


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return json.dumps(list(value), ensure_ascii=False, default=str)
    return str(value)


def _load_tokenizer():
    try:
        import tiktoken  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        return None
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - optional dependency
        return None


def _heuristic_token_count(text: str) -> int:
    ascii_words = _ASCII_WORD_RE.findall(text)
    cjk_chars = _CJK_RE.findall(text)
    other_chars = [
        ch
        for ch in text
        if ch not in {" ", "\t", "\n", "\r"}
        and not _ASCII_WORD_RE.match(ch)
        and not _CJK_RE.match(ch)
    ]
    ascii_tokens = sum(max(1, math.ceil(len(word) / 4)) for word in ascii_words)
    other_tokens = math.ceil(len(other_chars) / 2)
    return ascii_tokens + len(cjk_chars) + other_tokens
