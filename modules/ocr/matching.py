from __future__ import annotations

from typing import Optional

from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def find_text_matches(result: OCRResult, query: str, *, partial_match: bool = False) -> list[OCRTextMatch]:
    normalized_query = normalize_text(query)
    matches: list[tuple[int, float, OCRTextMatch]] = []

    for match in result.matches:
        normalized_text = normalize_text(match.text)
        rank = _match_rank(normalized_query, normalized_text, partial_match=partial_match)
        if rank <= 0:
            continue
        matches.append((rank, float(match.score), match))

    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in matches]


def select_best_text_match(result: OCRResult, query: str, *, partial_match: bool = False) -> Optional[OCRTextMatch]:
    matches = find_text_matches(result, query, partial_match=partial_match)
    return matches[0] if matches else None


def bbox_center(bbox: OCRBoundingBox) -> dict[str, int]:
    return {
        "x": int(round(bbox.x + (bbox.width / 2.0))),
        "y": int(round(bbox.y + (bbox.height / 2.0))),
    }


def _match_rank(query: str, candidate: str, *, partial_match: bool) -> int:
    if candidate == query:
        return 2
    if partial_match and query in candidate:
        return 1
    return 0
