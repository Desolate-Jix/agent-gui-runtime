from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from app.learn.surface_rule_registry import RULE_ROOT, register_surface_rule_candidate


CORRECTION_ENTRY_CONTRACT = "learning_correction_memory_entry_v1"


def record_human_review_correction(
    human_review_patch: dict[str, Any],
    *,
    review: dict[str, Any],
    reviewed_draft: dict[str, Any],
    project_root: str | Path,
    source_patch_path: str | None = None,
) -> dict[str, Any] | None:
    if human_review_patch.get("contract_version") != "human_review_patch_v1":
        raise ValueError("correction memory requires human_review_patch_v1")
    operations = [item for item in human_review_patch.get("operations", []) if isinstance(item, dict)]
    if not operations:
        return None

    root = Path(project_root).resolve()
    surface = _surface_context(review, reviewed_draft)
    corrections = [_correction_from_operation(item, index) for index, item in enumerate(operations)]
    identity = {
        "source_draft_path": human_review_patch.get("source_draft_path"),
        "source_draft_sha256": human_review_patch.get("source_draft_sha256"),
        "screenshot_sha256": human_review_patch.get("screenshot_sha256"),
        "operations": operations,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    rule_id = f"surface_correction_{digest[:16]}"
    entry_path = root / RULE_ROOT / "entries" / f"{rule_id}.json"
    relative_entry_path = entry_path.relative_to(root).as_posix()
    entry = {
        "contract_version": CORRECTION_ENTRY_CONTRACT,
        "rule_id": rule_id,
        "created_at": datetime.now().isoformat(),
        "initial_status": "candidate",
        "source_type": "human_review_patch",
        "source_patch_path": str(source_patch_path or ""),
        "source": {
            "draft_path": str(human_review_patch.get("source_draft_path") or review.get("source", {}).get("source_path") or ""),
            "draft_sha256": str(human_review_patch.get("source_draft_sha256") or review.get("source", {}).get("sha256") or ""),
            "human_patch_revision": human_review_patch.get("revision"),
        },
        "surface": surface,
        "evidence": {
            "screenshot_path": str(human_review_patch.get("screenshot_path") or ""),
            "screenshot_sha256": str(human_review_patch.get("screenshot_sha256") or ""),
            "human_reason": str(human_review_patch.get("reason") or "").strip(),
            "editor_source": str(human_review_patch.get("source") or "human_panel_editor_v1"),
        },
        "corrections": corrections,
        "correction_count": len(corrections),
        "applicability": {
            "adapter_ids": [surface["adapter_id"]],
            "requires_visible_surface_evidence": True,
            "app_name_only_forbidden": True,
            "scope_status": "candidate_scope_requires_regression",
        },
        "counterexamples": {
            "items": deepcopy(human_review_patch.get("counterexamples"))
            if isinstance(human_review_patch.get("counterexamples"), list)
            else [],
            "required_before_activation": True,
        },
        "model_generated_rule": False,
        "model_may_suggest_counterexamples": True,
        "model_may_activate": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
    }

    entry_path.parent.mkdir(parents=True, exist_ok=True)
    if entry_path.exists():
        existing = json.loads(entry_path.read_text(encoding="utf-8-sig"))
        if not isinstance(existing, dict) or existing.get("rule_id") != rule_id:
            raise ValueError("correction memory entry collision")
        entry = existing
    else:
        entry_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entry_sha256 = hashlib.sha256(entry_path.read_bytes()).hexdigest()
    registry_record = register_surface_rule_candidate(
        rule_id=rule_id,
        correction_entry_path=relative_entry_path,
        correction_sha256=entry_sha256,
        surface=surface,
        project_root=root,
    )
    return {
        "contract_version": "learning_correction_memory_record_v1",
        "rule_id": rule_id,
        "status": registry_record["status"],
        "production_eligible": registry_record["production_eligible"],
        "correction_entry_path": relative_entry_path,
        "registry_path": (RULE_ROOT / "registry.json").as_posix(),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _surface_context(review: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    preview = review.get("screen_understanding_preview") if isinstance(review.get("screen_understanding_preview"), dict) else {}
    audit = review.get("audit") if isinstance(review.get("audit"), dict) else {}
    candidates = [
        page_details.get("surface_adapter_decision"),
        draft.get("surface_adapter_decision"),
        preview.get("surface_adapter_decision"),
        audit.get("surface_adapter_decision"),
    ]
    decision = next((item for item in candidates if isinstance(item, dict)), {})
    adapter_id = str(decision.get("adapter_id") or "generic").strip() or "generic"
    return {
        "adapter_id": adapter_id,
        "decision_status": str(decision.get("status") or "surface_evidence_not_available"),
        "selection_evidence": deepcopy(decision.get("selection_evidence"))
        if isinstance(decision.get("selection_evidence"), list)
        else [],
        "app_name_used_as_final_decision": decision.get("app_name_used_as_final_decision") is True,
        "surface_evidence_required_for_reuse": True,
    }


def _correction_from_operation(operation: dict[str, Any], index: int) -> dict[str, Any]:
    edit_type = str(operation.get("op") or "").strip()
    correction = {
        "correction_id": f"correction_{index + 1}",
        "edit_type": edit_type,
        "target_kind": str(operation.get("target_kind") or "region"),
        "target_id": str(operation.get("target_id") or ""),
    }
    if edit_type == "add":
        correction.update({"before": None, "after": deepcopy(operation.get("item"))})
    elif edit_type == "delete":
        correction.update({"before": deepcopy(operation.get("before_item")), "after": None})
    elif edit_type == "update_bbox":
        correction.update(
            {
                "before": deepcopy(operation.get("before_bbox")),
                "after": deepcopy(operation.get("after_bbox")),
            }
        )
    elif edit_type in {"update_role", "update_parent"}:
        correction.update(
            {
                "before": operation.get("before_value"),
                "after": operation.get("after_value"),
            }
        )
    elif edit_type == "update_metadata":
        correction.update(
            {
                "before": deepcopy(operation.get("before_metadata")),
                "after": deepcopy(operation.get("after_metadata")),
            }
        )
    else:
        raise ValueError(f"unsupported human correction operation: {edit_type}")
    return correction
