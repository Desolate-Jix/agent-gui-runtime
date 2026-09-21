from __future__ import annotations

import base64
import hashlib
from binascii import Error as Base64Error
from copy import deepcopy
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError


def compact_feedback_view(value: dict[str, Any]) -> dict[str, Any]:
    # 仅转换 Agent 展示副本，规范基线及其摘要仍归服务端所有。
    result = deepcopy(value)
    issues = result.get("issues")
    if not isinstance(issues, list):
        return result
    for issue in issues:
        if not isinstance(issue, dict) or "review_baseline" not in issue:
            continue
        baseline = issue.pop("review_baseline")
        if not isinstance(baseline, dict):
            raise ValueError("review baseline is malformed")
        source_hash = issue.get("review_baseline_sha256")
        if not isinstance(source_hash, str) or not source_hash:
            raise ValueError("review baseline digest is missing")
        if baseline.get("contract_version") == "desktop_graph_review_baseline_v1":
            view = deepcopy(baseline)
            view["contract_version"] = "desktop_graph_review_baseline_view_v1"
            view["source_contract_version"] = baseline["contract_version"]
            view["source_baseline_sha256"] = source_hash
            view["artifact_is_authorization"] = False
            issue["review_baseline_view"] = view
            continue
        batch = baseline.get("batch")
        if not isinstance(batch, dict) or not isinstance(batch.get("screenshots"), list):
            raise ValueError("review baseline screenshots are malformed")
        view = deepcopy(baseline)
        view["contract_version"] = "desktop_review_baseline_view_v1"
        view["source_contract_version"] = baseline.get("contract_version")
        view["source_baseline_sha256"] = source_hash
        view["artifact_is_authorization"] = False
        shots = []
        for shot in batch["screenshots"]:
            if not isinstance(shot, dict) or not isinstance(shot.get("png_base64"), str):
                raise ValueError("review baseline screenshot is malformed")
            try:
                raw = base64.b64decode(shot["png_base64"], validate=True)
                with Image.open(BytesIO(raw)) as image:
                    if image.format != "PNG":
                        raise ValueError("not PNG")
                    image.verify()
            except (Base64Error, ValueError, UnidentifiedImageError, OSError, SyntaxError) as error:
                raise ValueError("review baseline screenshot is malformed") from error
            digest = hashlib.sha256(raw).hexdigest()
            if "sha256" in shot and shot["sha256"] != digest:
                raise ValueError("review baseline screenshot digest disagrees")
            compact = {key: deepcopy(shot[key]) for key in ("screenshot_id", "width", "height") if key in shot}
            if not isinstance(compact.get("screenshot_id"), str):
                raise ValueError("review baseline screenshot is malformed")
            compact["sha256"] = digest
            compact["inline_image_omitted"] = True
            shots.append(compact)
        view["batch"]["screenshots"] = shots
        issue["review_baseline_view"] = view
    return result
