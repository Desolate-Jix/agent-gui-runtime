from __future__ import annotations

import re
from typing import Any


OCR_CANONICALIZATION_CONTRACT = "ocr_canonicalization_v1"


def canonicalize_short_ocr_token(value: Any, *, context: str | None = None) -> dict[str, Any]:
    raw = str(value or "").strip()
    tokens = re.findall(r"[A-Za-z0-9]+", raw)
    normalized: list[str] = []
    changed = False
    allow_short_acronym_fix = str(context or "") in {"company_name", "acronym", "already_matched_acronym"}
    for token in tokens:
        cleaned = token.casefold()
        if allow_short_acronym_fix and _short_acronym_like(cleaned):
            replaced = cleaned.replace("1", "i").replace("l", "i").replace("0", "o")
            changed = changed or replaced != cleaned
            cleaned = replaced
        normalized.append(cleaned)
    return {
        "contract_version": OCR_CANONICALIZATION_CONTRACT,
        "raw": raw,
        "canonical": "".join(normalized),
        "context": context,
        "changed": changed,
        "policy": "short_acronym_only",
    }


def ocr_contextual_match(expected: Any, observed: Any, *, context: str | None = None) -> bool:
    expected_key = canonicalize_short_ocr_token(expected, context=context)["canonical"]
    observed_key = canonicalize_short_ocr_token(observed, context=context)["canonical"]
    return bool(expected_key and observed_key and expected_key == observed_key)


def _short_acronym_like(token: str) -> bool:
    return 1 <= len(token) <= 4 and bool(re.search(r"[a-z]", token))
