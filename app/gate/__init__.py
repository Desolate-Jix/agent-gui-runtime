from __future__ import annotations

from app.gate.candidates import (
    ACTION_CANDIDATE_TARGET_CONTRACT,
    CANDIDATE_FRESHNESS_CONTRACT,
    attach_candidate_freshness,
    build_candidate_freshness,
    validate_action_candidate_freshness,
    validate_action_candidate_target_at_point,
)
from app.gate.contracts import GateContract, build_gate_contract_catalog, list_gate_contracts
from app.gate.actions import (
    ACTION_TAXONOMY_CONTRACT,
    classify_action_taxonomy,
    infer_action_kind,
    infer_low_level_action_type,
)
from app.gate.danger import FINAL_SUBMIT_SCOPE_CONTRACT, scoped_final_submit_visible_blocker
from app.gate.dataflow import (
    DETAIL_SNAPSHOT_CONTRACT,
    merge_read_batch_into_detail_snapshot,
    put_latest_detail_snapshot,
    require_latest_detail_snapshot,
    with_detail_snapshot,
)
from app.gate.ocr import canonicalize_short_ocr_token, ocr_contextual_match
from app.gate.scroll import SCROLL_SCOPE_CONTRACT, apply_scroll_scope_invariant, build_scroll_scope_invariant
from app.gate.window import BOUND_WINDOW_MATCH_CONTRACT, validate_bound_window_for_app

__all__ = [
    "ACTION_CANDIDATE_TARGET_CONTRACT",
    "ACTION_TAXONOMY_CONTRACT",
    "BOUND_WINDOW_MATCH_CONTRACT",
    "CANDIDATE_FRESHNESS_CONTRACT",
    "DETAIL_SNAPSHOT_CONTRACT",
    "FINAL_SUBMIT_SCOPE_CONTRACT",
    "GateContract",
    "SCROLL_SCOPE_CONTRACT",
    "attach_candidate_freshness",
    "apply_scroll_scope_invariant",
    "build_candidate_freshness",
    "build_gate_contract_catalog",
    "build_scroll_scope_invariant",
    "canonicalize_short_ocr_token",
    "classify_action_taxonomy",
    "infer_action_kind",
    "infer_low_level_action_type",
    "list_gate_contracts",
    "merge_read_batch_into_detail_snapshot",
    "ocr_contextual_match",
    "put_latest_detail_snapshot",
    "require_latest_detail_snapshot",
    "scoped_final_submit_visible_blocker",
    "validate_action_candidate_freshness",
    "validate_action_candidate_target_at_point",
    "validate_bound_window_for_app",
    "with_detail_snapshot",
]
