from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.runtime_architecture.profiles import get_app_profile


class GateContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["gate_contract_descriptor_v1"] = "gate_contract_descriptor_v1"
    contract_id: str
    layer_module: str
    purpose: str
    blocks_or_flags: list[str]
    required_for_real_actions: bool = True


_BASE_GATE_CONTRACTS: tuple[GateContract, ...] = (
    GateContract(
        contract_id="candidate_freshness_v1",
        layer_module="app.gate.candidates",
        purpose="Reject stale screenshot coordinates, missing bbox/click_point evidence, and mismatched viewport captures.",
        blocks_or_flags=[
            "candidate_freshness_missing_fields",
            "candidate_capture_id_stale",
            "candidate_viewport_size_stale",
            "candidate_click_point_outside_bbox",
        ],
    ),
    GateContract(
        contract_id="bound_window_match_v1",
        layer_module="app.gate.window",
        purpose="Verify the currently bound window matches the requested app alias before live capture or real action.",
        blocks_or_flags=["process_name_mismatch", "unexpected_bound_window"],
    ),
    GateContract(
        contract_id="pre_click_decision_v1",
        layer_module="app.operation.recognition",
        purpose="Require an explicit pre-click decision before a real click is executed.",
        blocks_or_flags=["missing_pre_click_decision", "ambiguous_candidate", "target_evidence_mismatch"],
    ),
    GateContract(
        contract_id="action_taxonomy_v1",
        layer_module="app.gate.actions",
        purpose="Classify actions such as open_detail, open_apply_flow, fill_field, continue_next_step, and final_submit.",
        blocks_or_flags=["final_submit", "send", "confirm", "payment"],
    ),
    GateContract(
        contract_id="scroll_scope_v1",
        layer_module="app.gate.scroll",
        purpose="Detect when a scroll changed a non-target pane or failed to move target content.",
        blocks_or_flags=["wrong_scope_detected", "target_did_not_change"],
    ),
    GateContract(
        contract_id="scoped_danger_detection_v1",
        layer_module="app.gate.danger",
        purpose="Detect final submit/send/confirm/payment only inside the active flow scope.",
        blocks_or_flags=["final_submit_visible_stop_before_submission"],
    ),
    GateContract(
        contract_id="apply_entry_is_open_apply_flow_v1",
        layer_module="app.gate.actions",
        purpose="Treat Apply or Quick Apply as opening an application flow, not as final submit.",
        blocks_or_flags=["standard_external_apply_requires_review"],
    ),
    GateContract(
        contract_id="final_submit_guard_v1",
        layer_module="app.gate.danger",
        purpose="Hard-block final submit unless a structured current suitability and authorization decision exists.",
        blocks_or_flags=["final_submit_default_forbidden", "missing_final_submit_decision"],
    ),
    GateContract(
        contract_id="profile_mutation_requires_user_approval_v1",
        layer_module="app.gate.candidates",
        purpose="Block Add/Edit/update-profile style controls unless the Agent asks the user first.",
        blocks_or_flags=["profile_mutation_candidate_at_click_point"],
    ),
    GateContract(
        contract_id="ocr_contextual_normalization_v1",
        layer_module="app.gate.ocr",
        purpose="Normalize short OCR confusions only in matched acronym/context, not globally.",
        blocks_or_flags=["unmatched_short_token", "unsafe_global_replacement"],
        required_for_real_actions=False,
    ),
    GateContract(
        contract_id="latest_detail_snapshot_v1",
        layer_module="app.gate.dataflow",
        purpose="Ensure downstream match/apply decisions read the latest full-detail snapshot only.",
        blocks_or_flags=["stale_detail_snapshot"],
    ),
)


def list_gate_contracts(app_id: str | None = None) -> list[dict[str, Any]]:
    contracts = {item.contract_id: item.model_dump() for item in _BASE_GATE_CONTRACTS}
    if not app_id:
        return list(contracts.values())
    profile, _path = get_app_profile(app_id)
    result: list[dict[str, Any]] = []
    for contract_id in profile.gate_contracts:
        if contract_id in contracts:
            payload = dict(contracts[contract_id])
            payload["profile_contract_id"] = contract_id
            result.append(payload)
        else:
            result.append(
                GateContract(
                    contract_id=contract_id,
                    layer_module="app.gate",
                    purpose=f"{profile.display_name} profile-specific Gate contract.",
                    blocks_or_flags=["profile_specific_gate_required"],
                ).model_dump()
            )
    return result


def build_gate_contract_catalog(app_id: str | None = None) -> dict[str, Any]:
    profile_path = None
    if app_id:
        _profile, path = get_app_profile(app_id)
        profile_path = str(path)
    return {
        "contract_version": "gate_contract_catalog_v1",
        "execution_model": "agentic_loop_first",
        "app_id": app_id,
        "profile_path": profile_path,
        "contracts": list_gate_contracts(app_id),
    }
