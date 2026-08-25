from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import site
from threading import Thread
import time
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROOF_CONTRACT = "portfolio_hybrid_v1_1_persistence_proof_v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
FORBIDDEN_RUNTIME_POINT_FIELDS = {
    "actual_point",
    "click_point",
    "clickpoint",
    "confirmed_point",
    "expected_point",
    "screen_point",
    "target_point",
}
NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}
SEQUENCE = [
    "save",
    "compile_without_publish_a",
    "terminate_process_a",
    "fresh_process_b",
    "reload_exact_saved_bytes",
    "compile_without_publish_b",
    "compare_sha",
    "publish_b_once",
    "verify_registry_cas",
]
_WORKER_MARKER = "PORTFOLIO_HYBRID_WORKER_RESULT="


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    from app.learn.recognition.uei.canonical import canonical_json_bytes

    return canonical_json_bytes(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _runtime_point_fields(value: object) -> list[str]:
    found: set[str] = set()

    def visit(item: object, path: tuple[str, ...] = ()) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized_key = str(key)
                child_path = (*path, normalized_key)
                is_fresh_grounding_policy = (
                    normalized_key == "click_point"
                    and child == {"required": True}
                    and len(path) == 4
                    and path[0] == "transitions"
                    and path[1].isdigit()
                    and path[2:] == ("preconditions", "grounding")
                )
                if (
                    normalized_key in FORBIDDEN_RUNTIME_POINT_FIELDS
                    and not is_fresh_grounding_policy
                ):
                    found.add(normalized_key)
                visit(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, (*path, str(index)))

    visit(value)
    return sorted(found)


def _contains_proposals(value: object) -> tuple[bool, bool]:
    serialized = json.dumps(value, ensure_ascii=False)
    return "vista_proposal" in serialized, "human_point_proposal" in serialized


def _window_binding() -> dict[str, object]:
    return {
        "window_binding_id": "window:managed-proof",
        "process_id": 202,
        "process_name": "managed-proof-fixture.exe",
        "rect": {"left": 0, "top": 0, "right": 160, "bottom": 90},
    }


def _put_uei_object(store: Any, value: dict[str, object]) -> dict[str, str]:
    from app.learn.recognition.uei.canonical import seal_immutable

    return store.put(seal_immutable(value))


def _provider_context_ref(
    root: Path,
    *,
    lineage_ref: dict[str, str],
    source_kind: str,
    run_id: str,
    revision: int,
) -> dict[str, str]:
    from app.learn.recognition.uei.store import UEIObjectStore

    store = UEIObjectStore(root=root / "artifacts" / "uei-shadow-store")
    suffix = f"{run_id}-{source_kind}-{revision}"
    provider_id = f"local.test/{source_kind}"
    profile_id = f"{provider_id}/v1"
    request_ref = _put_uei_object(
        store,
        {
            "contract_version": "screen_parse_request_v1",
            "request_id": f"request/{suffix}",
            "capture_lineage_ref": lineage_ref,
            "requested_profiles": [
                {
                    "provider_id": provider_id,
                    "profile_id": profile_id,
                    "mode": "Advisory",
                }
            ],
            "privacy_policy": "minimal",
            "requester_id": "server",
        },
    )
    registration_ref = _put_uei_object(
        store,
        {
            "contract_version": "trusted_provider_registration_v1",
            "registration_id": f"registration/{suffix}",
            "provider_id": provider_id,
            "profile_ids": [profile_id],
            "enabled": True,
            "allowed_modes": ["Advisory"],
            "allowed_privacy_policies": ["minimal"],
            "egress_policy": "local_only",
            "wire_payload_policy": "restricted_store_only",
            "safe_payload_limits": {
                "max_json_bytes": 4096,
                "max_depth": 6,
                "max_array_items": 16,
                "max_object_properties": 16,
                "max_string_chars": 256,
                "allowed_json_types": [
                    "object",
                    "array",
                    "string",
                    "number",
                    "boolean",
                    "null",
                ],
            },
            "required_conformance_suite": "uei-v1-static-projection",
        },
    )
    manifest_ref = _put_uei_object(
        store,
        {
            "contract_version": "provider_manifest_v1",
            "manifest_id": f"manifest/{suffix}",
            "provider_id": provider_id,
            "provider_version": "managed-proof-v1",
            "profiles": [
                {
                    "profile_id": profile_id,
                    "operation": "screen_parse",
                    "input_contract": "screen_parse_request_v1",
                    "output_contract": "provider_safe_result_v1",
                    "declared_output_kinds": [
                        "text" if source_kind == "ocr" else "element"
                    ],
                    "supported_coordinate_spaces": ["capture_pixel_xyxy"],
                    "supports_capture_artifact": True,
                    "privacy_capabilities": ["minimal"],
                    "mode_allowlist": ["Advisory"],
                }
            ],
        },
    )
    return _put_uei_object(
        store,
        {
            "contract_version": "provider_safe_result_v1",
            "result_id": f"result/{suffix}",
            "request_ref": request_ref,
            "requested_provider_id": provider_id,
            "requested_profile_id": profile_id,
            "registration_resolution": "resolved",
            "manifest_resolution": "resolved",
            "registration_ref": registration_ref,
            "manifest_ref": manifest_ref,
            "provider_id": provider_id,
            "profile_id": profile_id,
            "provider_version": "managed-proof-v1",
            "capture_lineage_ref": lineage_ref,
            "status": "success",
            "review_only": True,
            "items": [],
            "redaction_summary": {
                "redacted_item_count": 0,
                "redacted_field_count": 0,
                "secret_detected": False,
                "sensitive_categories": [],
            },
        },
    )


def _create_capture_image(root: Path) -> Path:
    from PIL import Image

    image_path = root / "artifacts" / "screenshots" / "managed-hybrid.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (160, 90), color=(18, 38, 68)).save(image_path)
    return image_path


def _build_capture(
    root: Path,
    *,
    image_path: Path,
    run_id: str,
    revision: int,
) -> dict[str, Any]:
    from app.learn.hybrid.capture import (
        load_and_verify_hybrid_capture_bundle,
        seal_hybrid_capture_bundle,
        seal_hybrid_capture_identity,
    )

    identity = seal_hybrid_capture_identity(
        project_root=root,
        image_path=image_path,
        run_id=run_id,
        workflow_revision=revision,
        window_binding=_window_binding(),
        captured_at="2026-08-25T00:00:00Z",
    )
    lineage_ref = deepcopy(identity["capture_lineage_ref"])
    sources = []
    for source_kind in ("ocr", "uia"):
        evidence_ref = _provider_context_ref(
            root,
            lineage_ref=lineage_ref,
            source_kind=source_kind,
            run_id=run_id,
            revision=revision,
        )
        sources.append(
            {
                "source_kind": source_kind,
                "capture_lineage_ref": lineage_ref,
                "run_id": run_id,
                "workflow_revision": revision,
                "window_binding": _window_binding(),
                "evidence_contract_version": "provider_safe_result_v1",
                "evidence_ref": evidence_ref,
            }
        )
    saved = seal_hybrid_capture_bundle(
        project_root=root,
        image_path=image_path,
        run_id=run_id,
        workflow_revision=revision,
        window_binding=_window_binding(),
        ocr_uia_context={
            "capture_lineage_ref": lineage_ref,
            "sources": sources,
            "derived_views": [],
        },
        capture_envelope=identity.capture_envelope,
    )
    bundle = load_and_verify_hybrid_capture_bundle(
        project_root=root,
        bundle_ref=saved["bundle_ref"],
        expected_run_id=run_id,
        expected_workflow_revision=revision,
    )
    bundle["bundle_ref"] = deepcopy(saved["bundle_ref"])
    return bundle


def fake_omni_runner(*, capture_bundle: Mapping[str, Any]) -> dict[str, Any]:
    from app.learn.recognition.uei.canonical import seal_immutable

    generic_ref = {"id": "fake-provider/ref", "content_sha256": "12" * 32}
    return seal_immutable(
        {
            "contract_version": "provider_safe_result_v1",
            "result_id": "result/fake-omni-managed-proof",
            "request_ref": generic_ref,
            "requested_provider_id": "local.runtime/omniparser",
            "requested_profile_id": "local.runtime/omniparser/shadow-v2",
            "registration_resolution": "resolved",
            "manifest_resolution": "resolved",
            "registration_ref": generic_ref,
            "manifest_ref": generic_ref,
            "provider_id": "local.runtime/omniparser",
            "profile_id": "local.runtime/omniparser/shadow-v2",
            "provider_version": "fake-omni-managed-proof-v1",
            "capture_lineage_ref": deepcopy(capture_bundle["capture_lineage_ref"]),
            "status": "success",
            "review_only": True,
            "items": [
                {
                    "source_item_id": "omni/managed-apply",
                    "source_id_origin": "provider",
                    "kind": "element",
                    "safe_text": "申请职位",
                    "safe_role": "button",
                    "safe_states": [],
                    "source_bbox": [40, 20, 120, 52],
                    "capture_bbox": [40, 20, 120, 52],
                    "source_coordinate_space": "capture_pixel_xyxy",
                    "coordinate_transform_ref": None,
                    "opaque_attributes": {"runner": "fake-omni"},
                    "provider_confidence": 0.93,
                }
            ],
            "redaction_summary": {
                "redacted_item_count": 0,
                "redacted_field_count": 0,
                "secret_detected": False,
                "sensitive_categories": [],
            },
        }
    )


def fake_qwen_runner(**kwargs: Any) -> dict[str, Any]:
    request = kwargs["request"]
    return {
        "bindings": [
            {
                "candidate_id": candidate["candidate_id"],
                "role": "button",
                "label": "申请职位",
                "description": "打开申请流程",
                "semantic_confidence": 0.94,
                "task_relevance": 0.9,
                "relation": "primary_action",
                "ambiguity": None,
            }
            for candidate in request["candidates"]
        ],
        "ambiguity_sets": [],
        "orphan_semantics": [],
    }


def fake_bounded_vista_runner(*, request: Mapping[str, Any]) -> dict[str, Any]:
    bbox = request["candidate_bbox_ref"]["xyxy"]
    return {
        "status": "PROPOSED",
        "candidate_id": request["candidate_id"],
        "capture_id": request["capture_id"],
        "capture_sha256": request["capture_sha256"],
        "source_revision": request["source_revision"],
        "affine_transform_ref": deepcopy(request["affine_transform_ref"]),
        "point_coordinate_space": "capture_pixel_xyxy",
        "point": [
            (bbox[0] + bbox[2]) / 2,
            (bbox[1] + bbox[3]) / 2,
        ],
        "provenance": {"provider": "fake-vista", "request_id": "managed-proof"},
    }


def _fake_qwen_cleanup_receipt() -> dict[str, Any]:
    from app.core.model_server import build_qwen_cleanup_receipt

    process = {
        "pid": 424242,
        "create_time": 100.5,
        "executable": "fake-qwen-server.exe",
    }
    lease = {
        "contract_version": "qwen_model_server_lease_v1",
        "lease_id": "lease-managed-proof",
        "owner_request_id": "request-managed-proof",
        "profile_id": "fake-qwen",
        "incarnation_id": "fake-qwen-managed-proof",
        "server_base_url": "http://127.0.0.1:1",
        "server_model_id": "fake-qwen",
        "profile_sha256": "1" * 64,
        "server_process_identity": process,
    }
    return build_qwen_cleanup_receipt(
        model_lease=lease,
        release_result={
            "status": "released",
            "lease": lease,
            "shared_server_retained": False,
            "server_termination": "verified_exact_process_exited",
            "release": {"status": "proven_absent", "identity": process},
            "process_identity": process,
        },
    )


def _trusted_review_roi(
    *, bundle: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    from app.learn.recognition.roi import build_roi_crop_metadata
    from app.learn.recognition.uei.canonical import seal_immutable

    bbox = candidate["bbox_original"]
    bbox_dict = {
        "x": bbox[0],
        "y": bbox[1],
        "w": bbox[2] - bbox[0],
        "h": bbox[3] - bbox[1],
    }
    metadata = build_roi_crop_metadata(
        source_image_size=bundle["capture_identity"]["image_size"],
        candidate_bbox=bbox_dict,
        crop_size={
            "width": max(1, bbox_dict["w"] * 2),
            "height": max(1, bbox_dict["h"] * 2),
        },
        expand_scale=2.0,
    )
    roi = metadata["coordinate_transform"]["roi_bbox"]
    return seal_immutable(
        {
            "contract_version": "hybrid_permitted_roi_v1",
            "roi_id": f"roi/{candidate['candidate_id']}",
            "candidate_id": candidate["candidate_id"],
            "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
            "coordinate_space": "capture_pixel_xyxy",
            "xyxy": [roi["x"], roi["y"], roi["x"] + roi["w"], roi["y"] + roi["h"]],
            "permitted_for_refinement": True,
        }
    )


def _negative_control_direct_hybrid_projection(
    root: Path,
    *,
    omni_runner: Callable[..., Mapping[str, Any]],
    qwen_runner: Callable[..., object],
    vista_runner: Callable[..., Mapping[str, Any]],
) -> tuple[Path, dict[str, Any], list[str]]:
    from app.learn.hybrid.contracts import load_hybrid_config
    from app.learn.hybrid.fusion import fuse_hybrid_candidates
    from app.learn.hybrid.omni_candidates import build_omni_candidate_ledger
    from app.learn.hybrid.qwen_binding import run_qwen_candidate_binding
    from app.learn.hybrid.review_projection import project_hybrid_review
    from app.learn.hybrid.vista_refinement import (
        build_vista_requests,
        validate_vista_proposal,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    trace: list[str] = []
    image_path = _create_capture_image(root)
    bundle = _build_capture(
        root,
        image_path=image_path,
        run_id="run-portfolio-hybrid-managed-proof",
        revision=8,
    )
    safe_result = omni_runner(capture_bundle=deepcopy(bundle))
    ledger = build_omni_candidate_ledger(
        safe_result=safe_result,
        capture_bundle=bundle,
    )
    inventory_value = deepcopy(ledger)
    inventory_value.pop("hybrid_capture_bundle_ref", None)
    inventory_value.pop("content_sha256", None)
    inventory_value["contract_version"] = "hybrid_omni_inventory_v1"
    sealed_inventory = seal_immutable(inventory_value)
    inventory = deepcopy(sealed_inventory)
    inventory.pop("content_sha256", None)
    trace.append("omni")
    sealed_bindings = run_qwen_candidate_binding(
        {
            "project_root": str(root),
            "run_id": bundle["run_id"],
            "workflow_revision": bundle["workflow_revision"],
            "hybrid_capture_bundle_ref": deepcopy(bundle["bundle_ref"]),
            "capture_image_path": image_path.relative_to(root).as_posix(),
            "omni_inventory": deepcopy(sealed_inventory),
        },
        model_runner=qwen_runner,
    )
    bindings = deepcopy(sealed_bindings)
    bindings.pop("content_sha256", None)
    trace.append("qwen")
    sealed_fusion = seal_immutable(
        fuse_hybrid_candidates(
            config=load_hybrid_config(REPOSITORY_ROOT),
            capture_bundle=bundle,
            omni_inventory=sealed_inventory,
            qwen_bindings=sealed_bindings,
        )
    )
    fusion = deepcopy(sealed_fusion)
    fusion.pop("content_sha256", None)
    trace.append("fusion")
    requests = build_vista_requests(
        sealed_fusion,
        bundle,
        omni_inventory=sealed_inventory,
        qwen_bindings=sealed_bindings,
        qwen_cleanup_receipt=_fake_qwen_cleanup_receipt(),
        expected_workflow_revision=bundle["workflow_revision"],
    )
    if len(requests) != 1:
        raise RuntimeError("managed proof expected exactly one bounded VISTA request")
    raw_vista = vista_runner(request=deepcopy(requests[0]))
    validated_vista = validate_vista_proposal(request=requests[0], raw_result=raw_vista)
    if validated_vista.get("status") != "PROPOSED":
        raise RuntimeError(f"fake bounded VISTA proposal rejected: {validated_vista}")
    trace.append("vista")
    candidate = inventory["candidates"][0]
    bbox_ref = seal_immutable(
        {
            "contract_version": "hybrid_candidate_bbox_ref_v1",
            "candidate_id": candidate["candidate_id"],
            "provider_result_ref": deepcopy(candidate["provider_result_ref"]),
            "coordinate_space": "capture_pixel_xyxy",
            "xyxy": deepcopy(candidate["bbox_original"]),
        }
    )
    vista_proposals = {
        "contract_version": "hybrid_vista_proposals_v1",
        "capture_identity": deepcopy(bundle["capture_identity"]),
        "proposals": [
            {
                "candidate_id": candidate["candidate_id"],
                "fusion_state": "BOUND",
                "candidate_bbox_ref": bbox_ref,
                "roi_ref": _trusted_review_roi(bundle=bundle, candidate=candidate),
                "point": deepcopy(validated_vista["canonical_point"]),
                "confidence": 0.86,
                "evidence": ["fake-vista-managed-boundary"],
                "status": "PROPOSED",
                "review_required": True,
            }
        ],
        **NON_AUTHORIZING,
    }
    projection = project_hybrid_review(
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        fusion_result=fusion,
        vista_proposals=vista_proposals,
    )
    return image_path, projection, trace


def _negative_control_direct_workflow_state(
    *, run_id: str, revision: int, trial_path: str
) -> dict[str, Any]:
    from app.learn.workflow_state import transition_learning_workflow_state

    state: dict[str, Any] | None = None
    transitions = [
        ("bind_capture", "running", {}),
        (
            "bind_capture",
            "completed",
            {"image_path": "artifacts/screenshots/managed-hybrid.png"},
        ),
        ("screen_understanding", "running", {}),
        ("screen_understanding", "completed", {"trial_path": trial_path}),
        ("numbered_map", "running", {}),
        (
            "numbered_map",
            "completed",
            {
                "report_path": "artifacts/managed-report.json",
                "overlay_path": "artifacts/managed-overlay.png",
            },
        ),
        ("precise_calibration", "running", {}),
        (
            "precise_calibration",
            "completed",
            {
                "result_path": "artifacts/managed-result.json",
                "overlay_path": "artifacts/managed-precise.png",
            },
        ),
    ]
    for stage, outcome, evidence_refs in transitions:
        state = transition_learning_workflow_state(
            previous_state=state,
            run_id=run_id,
            stage=stage,
            outcome=outcome,
            evidence_refs=evidence_refs,
        )
    if state is None or state["revision"] != revision:
        raise RuntimeError("managed workflow state revision mismatch")
    return state


@contextmanager
def _negative_control_static_panel_http_boundary(
    root: Path,
    *,
    workflow_state: dict[str, Any] | None = None,
) -> Iterator[Any]:
    os.environ.setdefault("AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER", "1")
    os.environ.setdefault("AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH", ":memory:")
    from fastapi.testclient import TestClient
    from app.api import panel as panel_api
    from app.main import app

    previous_root = panel_api.ROOT_DIR
    previous_trace = panel_api.write_trace
    previous_store = panel_api.learning_workflow_run_store
    panel_api.ROOT_DIR = root
    panel_api.write_trace = lambda **_kwargs: "managed-proof-trace.json"
    if workflow_state is not None:
        class _NegativeControlStaticWorkflowStore:
            def get(self, run_id: str) -> dict[str, Any]:
                if run_id != workflow_state["run_id"]:
                    raise ValueError("learning workflow run not found")
                return deepcopy(workflow_state)

        panel_api.learning_workflow_run_store = _NegativeControlStaticWorkflowStore()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        panel_api.ROOT_DIR = previous_root
        panel_api.write_trace = previous_trace
        panel_api.learning_workflow_run_store = previous_store


def _post_success(client: Any, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"{path} HTTP {response.status_code}: {response.text}")
    body = response.json()
    if body.get("success") is not True or not isinstance(body.get("data"), dict):
        raise RuntimeError(f"{path} failed: {body}")
    return body["data"]


def _negative_control_save_large_review(
    root: Path,
    *,
    image_path: Path,
    projection: dict[str, Any],
) -> dict[str, Any]:
    screen = projection["screen_facts"]
    run_id = projection["parent_evidence"]["capture_bundle"]["run_id"]
    revision = projection["parent_evidence"]["capture_bundle"]["workflow_revision"]
    trial_path = root / "artifacts" / "learning-runs" / "managed-proof" / "trial.json"
    trial = {
        "contract_version": "learning_template_draft_v1",
        "capture_lineage_ref": deepcopy(screen["capture_lineage_ref"]),
        "states": [],
        "regions": [],
        "action_templates": [],
        "page_details": {
            "screen": {
                "source_image_path": image_path.relative_to(root).as_posix(),
                "source_image_sha256": screen["displayed_image"]["sha256"],
            }
        },
        "hybrid_review_projection": deepcopy(projection),
    }
    _write_json(trial_path, trial)
    relative_trial = trial_path.relative_to(root).as_posix()
    state = _negative_control_direct_workflow_state(
        run_id=run_id,
        revision=revision,
        trial_path=relative_trial,
    )
    candidate_id = projection["candidates"][0]["candidate_id"]
    human_decision = {
        "decision_id": "decision/managed-proof-human-point",
        "decision_type": "human_point",
        "candidate_id": candidate_id,
        "human_point_proposal": {
            "coordinate_space": "capture_pixel_xyxy",
            "xy": [80, 40],
        },
    }
    with _negative_control_static_panel_http_boundary(
        root,
        workflow_state=state,
    ) as client:
        loaded = _post_success(
            client,
            "/panel/load_learning_draft_review",
            {"source_path": relative_trial, "workflow_run_id": run_id},
        )
        loaded_screen = loaded["draft"]["page_details"]["screen"]
        saved = _post_success(
            client,
            "/panel/save_learning_draft_review",
            {
                "source_path": relative_trial,
                "review_patch": {
                    "_hybrid_workflow_run_id": run_id,
                    "contract_version": "human_review_patch_v1",
                    "screenshot_path": loaded_screen["source_image_path"],
                    "screenshot_sha256": loaded_screen["source_image_sha256"],
                    "operations": [],
                    "review_status": "needs_human_review",
                    "source_after_review": "mixed",
                    "hybrid_review_decisions": [human_decision],
                },
            },
        )
    reviewed_path = root / saved["reviewed_template_candidate_path"]
    reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
    has_vista, has_human = _contains_proposals(reviewed)
    if not has_vista or not has_human:
        raise RuntimeError("Large Review save lost Hybrid proposal evidence")
    workflow_store_path = root / "runtime_state" / "learning-workflow-runs.json"
    _write_json(
        workflow_store_path,
        {
            "contract_version": "learning_workflow_run_store_v1",
            "runs": [state],
        },
    )
    return {
        "status": "saved",
        "reviewed_candidate_path": str(reviewed_path.resolve()),
        "reviewed_candidate_sha256": _sha256_bytes(reviewed_path.read_bytes()),
        "reviewed_candidate_contains_vista_proposal": has_vista,
        "reviewed_candidate_contains_human_proposal": has_human,
        "workflow_run_id": run_id,
        "workflow_revision": revision,
        "workflow_store_path": str(workflow_store_path.resolve()),
        "reviewed_candidate": reviewed,
    }


class _ProofInlineProcess:
    """仅在证明 worker seam 内同步执行，保留生产 registry 的持久回执。"""

    def __init__(self, *, target: Callable[..., Any], args: tuple[Any, ...], name: str):
        self._target = target
        self._args = args
        self.name = name
        self.pid: int | None = None
        self.exitcode: int | None = None

    def start(self) -> None:
        self._target(*self._args)
        self.exitcode = 0

    def is_alive(self) -> bool:
        return False

    def join(self, timeout: float | None = None) -> None:
        del timeout

    def terminate(self) -> None:
        self.exitcode = 0


def _proof_provider_cleanup_inventory(
    provider: str,
    *,
    lineage: Mapping[str, Any],
    predecessor_sha256: str,
    provider_result_sha256: str,
) -> dict[str, Any]:
    from app.learn.hybrid.gpu_lifecycle import release_hybrid_provider
    from app.learn.hybrid.windows_process_scope import process_scope_name

    process_identity = {
        "pid": 6100 + len(provider),
        "create_time_ns": 100_000_000_000,
    }
    exact_lineage = deepcopy(dict(lineage))
    if provider == "omni":
        provider_identity = {
            "provider_invocation_id": "invocation/proof-omni",
            "provider_receipt_ref": {
                "id": "receipt/proof-omni",
                "content_sha256": "a" * 64,
            },
            "process_identity": process_identity,
        }
    elif provider == "qwen":
        provider_identity = {
            "lease_id": "lease-proof-qwen",
            "incarnation_id": "qwen-proof",
            "profile_id": "qwen-proof",
            "server_process_identity": process_identity,
        }
    else:
        provider_identity = {
            "incarnation_id": "vista-proof",
            "profile_id": "vista-proof",
            "process_identities": [process_identity],
        }
    provider_identity["process_scope_name"] = process_scope_name(
        exact_lineage,
        provider,
    )
    inventory = {
        "contract_version": "hybrid_provider_process_inventory_v2",
        "provider": provider,
        "observer_contract": f"hybrid_{provider}_cleanup_observer_v1",
        "release_status": "verified",
        "termination_reason": "completed",
        "lineage": exact_lineage,
        "provider_lease_identity": provider_identity,
        "predecessor_sha256": predecessor_sha256,
        "provider_result_sha256": provider_result_sha256,
        "provider_processes_after": [],
        "helper_processes_after": [],
        "orphan_descendant_pids": [],
        "active_listeners_after": [],
        "lease_files_after": [],
        "source_cleanup_evidence": {"status": "verified", "seam": "proof_worker"},
    }
    return inventory


def _proof_provider_cleanup_receipt(
    provider: str,
    **kwargs: Any,
) -> dict[str, Any]:
    from app.learn.hybrid.gpu_lifecycle import release_hybrid_provider

    inventory = _proof_provider_cleanup_inventory(provider, **kwargs)
    return release_hybrid_provider(
        provider,
        process_inventory=lambda _provider: deepcopy(inventory),
    )


def _fake_model_lease(task_kind: str) -> dict[str, Any] | None:
    process = {"pid": 6200, "create_time": 100.5}
    if task_kind == "panel_learning_hybrid_qwen_binding":
        return {
            "contract_version": "qwen_model_server_lease_v1",
            "lease_id": "lease-managed-proof",
            "owner_request_id": "request-managed-proof",
            "profile_id": "fake-qwen",
            "incarnation_id": "fake-qwen-managed-proof",
            "server_base_url": "http://127.0.0.1:1",
            "server_model_id": "fake-qwen",
            "profile_sha256": "1" * 64,
            "server_process_identity": process,
        }
    if task_kind == "panel_learning_calibration_sequence":
        return {
            "contract_version": "vista_model_lease_v1",
            "profile_id": "fake-vista",
            "incarnation_id": "fake-vista-managed-proof",
            "process_identities": [process],
        }
    return None


@contextmanager
def _managed_panel_http_boundary(
    root: Path,
    *,
    workflow_store_path: Path,
    omni_runner: Callable[..., Mapping[str, Any]],
    qwen_runner: Callable[..., object],
    vista_runner: Callable[..., Mapping[str, Any]],
) -> Iterator[tuple[Any, Any, Any]]:
    os.environ.setdefault("AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER", "1")
    config_path = root / "configs" / "learn_hybrid_v1_1.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(
        (REPOSITORY_ROOT / "configs" / "learn_hybrid_v1_1.json").read_bytes()
    )
    from fastapi.testclient import TestClient
    from app.api import panel as panel_api
    from app.core import model_server
    from app.learn import workflow_worker
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
    from app.learn.hybrid.omni_candidates import (
        build_omni_candidate_ledger,
        omni_inventory_from_ledger,
    )
    from app.learn.hybrid.vista_refinement import (
        build_vista_requests,
        validate_vista_proposal,
    )
    from app.learn.workflow_store import LearningWorkflowRunStore
    from app.learn.workflow_tasks import hybrid_qwen as qwen_task_module
    from app.learn.workflow_worker import LearningStageWorkerRegistry
    from app.main import app

    store = LearningWorkflowRunStore(state_path=workflow_store_path)
    registry = LearningStageWorkerRegistry(
        result_root=root / "runtime_state" / "learning-stage-workers",
        process_factory=lambda **kwargs: _ProofInlineProcess(**kwargs),
    )

    def proof_omni_task(
        payload: dict[str, Any],
        *,
        cancellation_event: Any | None = None,
    ) -> dict[str, Any]:
        if cancellation_event is not None and cancellation_event.is_set():
            raise RuntimeError("proof Omni cancelled")
        bundle_ref = deepcopy(payload["hybrid_capture_bundle_ref"])
        bundle = load_and_verify_hybrid_capture_bundle(
            project_root=root,
            bundle_ref=bundle_ref,
            expected_run_id=payload["run_id"],
            expected_workflow_revision=payload["workflow_revision"],
        )
        bundle["bundle_ref"] = bundle_ref
        safe_result = omni_runner(capture_bundle=deepcopy(bundle))
        ledger = build_omni_candidate_ledger(
            safe_result=safe_result,
            capture_bundle=bundle,
        )
        inventory = omni_inventory_from_ledger(ledger)
        return {
            "contract_version": "hybrid_omni_discovery_result_v1",
            "outcome": "completed",
            "hybrid_capture_bundle_ref": bundle_ref,
            "provider_result_ref": deepcopy(inventory["provider_result_ref"]),
            "provider_error_ref": None,
            "provider_receipt_ref": {
                "id": "receipt/proof-omni",
                "content_sha256": "a" * 64,
            },
            "provider_invocation_id": "invocation/proof-omni",
            "provider_claim_status": "complete",
            "provider_status": "succeeded",
            "provider_reason_class": "none",
            "inventory": inventory,
            "omni_candidate_ledger": ledger,
            "duration_ms": 1,
            "cleanup_status": "clean",
        }

    def proof_qwen_task(
        payload: dict[str, Any],
        *,
        cancellation_event: Any | None = None,
        model_lease: dict[str, Any] | None = None,
        include_cleanup_receipt: bool = False,
    ) -> dict[str, Any]:
        return qwen_task_module.run_hybrid_qwen_task(
            payload,
            cancellation_event=cancellation_event,
            model_runner=qwen_runner,
            model_releaser=lambda **_kwargs: {"status": "released"},
            model_lease=model_lease,
            model_failure_reconciler=lambda **_kwargs: {"status": "not_needed"},
            include_cleanup_receipt=include_cleanup_receipt,
            cleanup_receipt_builder=lambda **_kwargs: _fake_qwen_cleanup_receipt(),
        )

    def proof_vista_task(
        payload: dict[str, Any],
        *,
        cancellation_event: Any | None = None,
    ) -> dict[str, Any]:
        requests = deepcopy(payload.get("hybrid_vista_requests"))
        if not isinstance(requests, list) or not requests:
            requests = build_vista_requests(
                payload["hybrid_fusion_result"],
                payload["capture_bundle"],
                omni_inventory=payload["omni_inventory"],
                qwen_bindings=payload["qwen_bindings"],
                qwen_cleanup_receipt=payload["qwen_cleanup_receipt"],
                expected_workflow_revision=payload["workflow_revision"],
            )
        results = []
        for request in requests:
            if cancellation_event is not None and cancellation_event.is_set():
                raise RuntimeError("proof VISTA cancelled")
            raw = vista_runner(request=deepcopy(request))
            proposal = validate_vista_proposal(request=request, raw_result=raw)
            if proposal.get("status") != "PROPOSED":
                raise RuntimeError(f"proof VISTA proposal rejected: {proposal}")
            results.append(
                {
                    "candidate_id": request["candidate_id"],
                    "hybrid_vista_request": deepcopy(request),
                    "hybrid_vista_proposal": proposal,
                }
            )
        sequence = {
            "contract_version": "learning_calibration_sequence_result_v1",
            "status": "completed",
            "remaining_count": 0,
            "completed_count": len(results),
            "hybrid_vista_requests": requests,
            "hybrid_vista_results": results,
            "qwen_cleanup_receipt": deepcopy(payload["qwen_cleanup_receipt"]),
        }
        return {
            "success": True,
            "data": {"result": {"calibration_sequence": sequence}},
        }

    def proof_reconcile_provider_record(record: dict[str, Any]) -> dict[str, Any]:
        result_path = Path(record["result_path"])
        result = json.loads(result_path.read_text(encoding="utf-8"))
        response = result.get("response") if isinstance(result, dict) else None
        lifecycle = (
            response.get("lifecycle_evidence")
            if isinstance(response, dict)
            else None
        )
        provider = str(record.get("provider") or "")
        receipt_key = {
            "omni": "omni_cleanup_receipt",
            "qwen": "qwen_gpu_cleanup_receipt",
            "vista": "vista_cleanup_receipt",
        }.get(provider)
        receipt = lifecycle.get(receipt_key) if isinstance(lifecycle, dict) else None
        verified = (
            isinstance(receipt, dict)
            and receipt.get("provider") == provider
            and receipt.get("cleanup_status") == "verified"
            and receipt.get("lineage") == record.get("provider_lineage")
        )
        return {
            "contract_version": "hybrid_supervisor_reconciliation_proof_v1",
            "status": "verified" if verified else "indeterminate",
            "cleanup_receipt": deepcopy(receipt),
            "proof_process_adapter": True,
        }

    previous = {
        "panel_root": panel_api.ROOT_DIR,
        "panel_trace": panel_api.write_trace,
        "panel_store": panel_api.learning_workflow_run_store,
        "panel_registry": panel_api.learning_stage_worker_registry,
        "worker_root": workflow_worker._PROJECT_ROOT,
        "qwen_root": qwen_task_module._PROJECT_ROOT,
        "omni_handler": workflow_worker.run_hybrid_omni_task,
        "qwen_handler": workflow_worker.run_hybrid_qwen_task,
        "vista_handler": workflow_worker.run_learning_calibration_sequence,
        "model_ready": workflow_worker._ensure_learning_stage_model_ready,
        "omni_observer": workflow_worker._observe_hybrid_omni_cleanup,
        "vista_release": workflow_worker._release_hybrid_vista_lease,
        "qwen_observer": model_server.observe_hybrid_qwen_cleanup,
        "provider_reconcile": workflow_worker._reconcile_hybrid_provider_scope_record,
    }
    panel_api.ROOT_DIR = root
    panel_api.write_trace = lambda **_kwargs: "managed-proof-trace.json"
    panel_api.learning_workflow_run_store = store
    panel_api.learning_stage_worker_registry = registry
    workflow_worker._PROJECT_ROOT = root
    qwen_task_module._PROJECT_ROOT = root
    workflow_worker.run_hybrid_omni_task = proof_omni_task
    workflow_worker.run_hybrid_qwen_task = proof_qwen_task
    workflow_worker.run_learning_calibration_sequence = proof_vista_task
    workflow_worker._ensure_learning_stage_model_ready = (
        lambda task_kind, *_args, **_kwargs: _fake_model_lease(task_kind)
    )
    workflow_worker._observe_hybrid_omni_cleanup = (
        lambda _result, **kwargs: _proof_provider_cleanup_inventory(
            "omni",
            lineage=kwargs["lineage"],
            predecessor_sha256=kwargs["predecessor_sha256"],
            provider_result_sha256=kwargs["provider_result_sha256"],
        )
    )
    model_server.observe_hybrid_qwen_cleanup = (
        lambda _receipt, **kwargs: _proof_provider_cleanup_inventory(
            "qwen",
            lineage=kwargs["lineage"],
            predecessor_sha256=kwargs["predecessor_sha256"],
            provider_result_sha256=kwargs["provider_result_sha256"],
        )
    )
    workflow_worker._release_hybrid_vista_lease = (
        lambda _lease, **kwargs: _proof_provider_cleanup_receipt(
            "vista",
            lineage=kwargs["lineage"],
            predecessor_sha256=kwargs["predecessor_sha256"],
            provider_result_sha256=kwargs["provider_result_sha256"],
        )
    )
    workflow_worker._reconcile_hybrid_provider_scope_record = (
        proof_reconcile_provider_record
    )
    try:
        with TestClient(app) as client:
            yield client, store, registry
    finally:
        panel_api.ROOT_DIR = previous["panel_root"]
        panel_api.write_trace = previous["panel_trace"]
        panel_api.learning_workflow_run_store = previous["panel_store"]
        panel_api.learning_stage_worker_registry = previous["panel_registry"]
        workflow_worker._PROJECT_ROOT = previous["worker_root"]
        qwen_task_module._PROJECT_ROOT = previous["qwen_root"]
        workflow_worker.run_hybrid_omni_task = previous["omni_handler"]
        workflow_worker.run_hybrid_qwen_task = previous["qwen_handler"]
        workflow_worker.run_learning_calibration_sequence = previous["vista_handler"]
        workflow_worker._ensure_learning_stage_model_ready = previous["model_ready"]
        workflow_worker._observe_hybrid_omni_cleanup = previous["omni_observer"]
        workflow_worker._release_hybrid_vista_lease = previous["vista_release"]
        workflow_worker._reconcile_hybrid_provider_scope_record = previous[
            "provider_reconcile"
        ]
        model_server.observe_hybrid_qwen_cleanup = previous["qwen_observer"]
        store.close()


def _post_success(client: Any, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"{path} HTTP {response.status_code}: {response.text}")
    body = response.json()
    if body.get("success") is not True or not isinstance(body.get("data"), dict):
        raise RuntimeError(f"{path} failed: {body}")
    return body["data"]


def _run_public_managed_hybrid_lifecycle(
    root: Path,
    *,
    client: Any,
) -> dict[str, Any]:
    from app.learn.hybrid.contracts import load_hybrid_config
    from app.learn.workflow_service import build_learning_pipeline_initial_worker_request

    run_id = "run-portfolio-hybrid-managed-proof"
    image_path = _create_capture_image(root)
    started_run = _post_success(
        client,
        "/panel/transition_learning_workflow_state",
        {
            "run_id": run_id,
            "expected_revision": 0,
            "stage": "bind_capture",
            "outcome": "running",
            "reason": "managed proof capture",
            "evidence_refs": {},
        },
    )["workflow_state"]
    bound = _post_success(
        client,
        "/panel/transition_learning_workflow_state",
        {
            "run_id": run_id,
            "expected_revision": started_run["revision"],
            "stage": "bind_capture",
            "outcome": "completed",
            "reason": "managed proof capture bound",
            "evidence_refs": {
                "image_path": image_path.relative_to(root).as_posix(),
            },
        },
    )["workflow_state"]
    operation = _post_success(
        client,
        "/panel/start_learning_workflow_stage_operation",
        {
            "run_id": run_id,
            "expected_revision": bound["revision"],
            "stage": "screen_understanding",
            "reason": "managed Hybrid proof",
            "lease_seconds": 600,
            "learning_pipeline_mode": "hybrid_v1_1",
        },
    )
    workflow_revision = operation["workflow_state"]["revision"]
    bundle = _build_capture(
        root,
        image_path=image_path,
        run_id=run_id,
        revision=workflow_revision,
    )
    generic_ref = {"id": "proof/ref", "content_sha256": "9" * 64}
    initial = build_learning_pipeline_initial_worker_request(
        learning_pipeline_mode="hybrid_v1_1",
        payload={
            "run_id": run_id,
            "workflow_revision": workflow_revision,
            "hybrid_capture_bundle_ref": deepcopy(bundle["bundle_ref"]),
            "request_ref": deepcopy(generic_ref),
            "registration_ref": deepcopy(generic_ref),
            "manifest_ref": deepcopy(generic_ref),
            "capture_image_path": image_path.relative_to(root).as_posix(),
            "hybrid_config": load_hybrid_config(root),
            "capture_bundle": deepcopy(bundle),
        },
    )
    worker = _post_success(
        client,
        "/panel/start_learning_stage_worker",
        {
            "run_id": run_id,
            "expected_revision": workflow_revision,
            "stage": "screen_understanding",
            "operation_id": operation["operation_id"],
            "task_kind": initial["task_kind"],
            "payload": initial["payload"],
        },
    )
    receipts: list[dict[str, Any]] = []
    final_projection: dict[str, Any] | None = None
    final_state: dict[str, Any] | None = None
    for _ in range(8):
        worker_id = worker["worker_id"]
        status_body = client.get(
            f"/panel/learning_stage_worker/{worker_id}",
            params={"run_id": run_id, "operation_id": operation["operation_id"]},
        ).json()
        if status_body.get("success") is not True:
            raise RuntimeError(f"worker status failed: {status_body}")
        status = status_body["data"]
        if status.get("status") != "completed":
            raise RuntimeError(f"managed proof worker did not complete: {status}")
        adopted = _post_success(
            client,
            "/panel/adopt_learning_stage_worker_result",
            {
                "run_id": run_id,
                "expected_revision": workflow_revision,
                "stage": "screen_understanding",
                "operation_id": operation["operation_id"],
                "worker_id": worker_id,
            },
        )
        continued = _post_success(
            client,
            "/panel/continue_learning_stage_worker_result",
            {
                "run_id": run_id,
                "expected_revision": workflow_revision,
                "stage": "screen_understanding",
                "operation_id": operation["operation_id"],
                "worker_id": worker_id,
            },
        )
        adoption_receipt = adopted["receipt"]
        managed_response = adopted["response"]
        lifecycle_evidence = deepcopy(managed_response.get("lifecycle_evidence") or {})
        receipts.append(
            {
                "operation_id": operation["operation_id"],
                "worker_id": worker_id,
                "task_kind": adoption_receipt["task_kind"],
                "worker_status": status["status"],
                "result_sha256": adoption_receipt["result_sha256"],
                "adoption_status": adopted["status"],
                "continuation_status": continued["continuation_status"],
                "lifecycle_evidence": lifecycle_evidence,
                "predecessor_lineage": deepcopy(
                    managed_response.get("orchestration") or {}
                ),
            }
        )
        if continued.get("stage_finished") is True:
            final_projection = deepcopy(continued["response"]["result"])
            final_state = deepcopy(continued["workflow_state"])
            break
        worker = continued.get("next_worker")
        if not isinstance(worker, dict):
            raise RuntimeError("managed continuation did not start the next worker")
    if final_projection is None or final_state is None:
        raise RuntimeError("managed lifecycle did not emit a review projection")
    state_projection = final_state["stages"]["screen_understanding"]["evidence_refs"][
        "hybrid_review_projection"
    ]
    if _canonical_bytes(final_projection) != _canonical_bytes(state_projection):
        raise RuntimeError("managed returned projection differs from durable state")
    task_trace = [receipt["task_kind"] for receipt in receipts]
    provider_by_task = {
        "panel_learning_hybrid_omni_discovery": "omni",
        "panel_learning_hybrid_qwen_binding": "qwen",
        "panel_learning_hybrid_fusion": "fusion",
        "panel_learning_calibration_sequence": "vista",
        "panel_learning_hybrid_review_projection": "review",
    }
    return {
        "image_path": image_path,
        "projection": final_projection,
        "workflow_state": final_state,
        "workflow_run_id": run_id,
        "workflow_revision": final_state["revision"],
        "operation_id": operation["operation_id"],
        "managed_lifecycle_receipts": receipts,
        "managed_lifecycle_task_trace": task_trace,
        "provider_boundary_trace": [provider_by_task[item] for item in task_trace],
        "managed_review_projection_receipt": deepcopy(receipts[-1]),
        "managed_review_trial_path": final_state["stages"][
            "screen_understanding"
        ]["evidence_refs"]["trial_path"],
    }


def _save_public_large_review(
    root: Path,
    *,
    client: Any,
    lifecycle: Mapping[str, Any],
) -> dict[str, Any]:
    projection = deepcopy(lifecycle["projection"])
    run_id = str(lifecycle["workflow_run_id"])
    relative_trial = str(lifecycle["managed_review_trial_path"])
    trial_path = (root / relative_trial).resolve()
    if not trial_path.is_file() or root not in trial_path.parents:
        raise RuntimeError("managed lifecycle did not persist its review trial")
    trial = json.loads(trial_path.read_text(encoding="utf-8-sig"))
    if _canonical_bytes(trial.get("managed_hybrid_review_projection")) != _canonical_bytes(
        projection
    ):
        raise RuntimeError("managed trial differs from its server projection")
    task8_projection = trial.get("hybrid_review_projection")
    loaded = _post_success(
        client,
        "/panel/load_learning_draft_review",
        {"source_path": relative_trial, "workflow_run_id": run_id},
    )
    if _canonical_bytes(loaded["hybrid_review_projection"]) != _canonical_bytes(
        task8_projection
    ):
        raise RuntimeError("Task 8 load did not return the managed projection")
    candidate_id = task8_projection["candidates"][0]["candidate_id"]
    loaded_screen = loaded["draft"]["page_details"]["screen"]
    saved = _post_success(
        client,
        "/panel/save_learning_draft_review",
        {
            "source_path": relative_trial,
            "review_patch": {
                "_hybrid_workflow_run_id": run_id,
                "contract_version": "human_review_patch_v1",
                "screenshot_path": loaded_screen["source_image_path"],
                "screenshot_sha256": loaded_screen["source_image_sha256"],
                "operations": [],
                "review_status": "needs_human_review",
                "source_after_review": "mixed",
                "hybrid_review_decisions": [
                    {
                        "decision_id": "decision/managed-proof-human-point",
                        "decision_type": "human_point",
                        "candidate_id": candidate_id,
                        "human_point_proposal": {
                            "coordinate_space": "capture_pixel_xyxy",
                            "xy": [80, 40],
                        },
                    }
                ],
            },
        },
    )
    reviewed_path = root / saved["reviewed_template_candidate_path"]
    reviewed_bytes = reviewed_path.read_bytes()
    reviewed = json.loads(reviewed_bytes.decode("utf-8-sig"))
    reloaded = _post_success(
        client,
        "/panel/load_learning_draft_review",
        {
            "source_path": reviewed_path.relative_to(root).as_posix(),
            "workflow_run_id": run_id,
            "discover_related_sidecars": False,
        },
    )
    has_vista, has_human = _contains_proposals(reviewed)
    if not has_vista or not has_human:
        raise RuntimeError("Large Review save lost Hybrid proposal evidence")
    return {
        "status": "saved",
        "reviewed_candidate_path": str(reviewed_path.resolve()),
        "reviewed_candidate_sha256": _sha256_bytes(reviewed_bytes),
        "reviewed_candidate_contains_vista_proposal": has_vista,
        "reviewed_candidate_contains_human_proposal": has_human,
        "managed_review_trial_path": str(trial_path),
        "managed_review_trial_sha256": _sha256_bytes(trial_path.read_bytes()),
        "workflow_run_id": run_id,
        "workflow_revision": lifecycle["workflow_revision"],
        "reviewed_candidate": reviewed,
        "public_reload": reloaded,
    }


def _base_workflow_review(
    *,
    workflow_id: str,
    reviewed_candidate_path: str,
    reviewed_candidate: Mapping[str, Any],
) -> dict[str, Any]:
    projection = reviewed_candidate["draft"]["hybrid_review_projection"]
    hybrid_region = deepcopy(projection["candidates"][0])
    hybrid_region.update(
        {
            "region_id": "hybrid_apply_region",
            "label": "Hybrid apply proposal",
            "display_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    return {
        "contract_version": "single_application_workflow_review_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "workflow": {
            "workflow_id": workflow_id,
            "goal": "Open a detail and stop at the application entry boundary.",
            "application_identity": {"url": "https://managed.example.test/jobs"},
            "entry_node_id": "home",
            "node_ids": ["home", "detail", "apply_entry"],
            "edge_ids": ["home_to_detail", "detail_to_apply"],
            "review_status": "needs_human_review",
        },
        "nodes": [
            {
                "node_id": "home",
                "display_name": "Managed Hybrid result list",
                "surface_type": "results",
                "state_signature": "managed-hybrid-home",
                "source_paths": [reviewed_candidate_path],
                "evidence": {},
                "controls": [{"control_id": "job_card", "label": "Managed result"}],
                "regions": [hybrid_region],
                "action_candidates": [
                    {
                        "action_template_id": "open_job_detail",
                        "semantic_action": "open_detail",
                        "target_control_id": "job_card",
                        "target_region_id": "",
                        "target_interface_id": "detail",
                    }
                ],
                "review_status": "needs_human_review",
                "reviewed_by_human": False,
            },
            {
                "node_id": "detail",
                "display_name": "Managed Hybrid detail",
                "surface_type": "detail",
                "state_signature": "managed-hybrid-detail",
                "source_paths": [],
                "evidence": {},
                "controls": [
                    {"control_id": "apply_entry_control", "label": "Open application flow"}
                ],
                "regions": [],
                "action_candidates": [
                    {
                        "action_template_id": "open_apply_entry",
                        "semantic_action": "open_apply_flow",
                        "target_control_id": "apply_entry_control",
                        "target_region_id": "",
                        "target_interface_id": "apply_entry",
                    }
                ],
                "review_status": "needs_human_review",
                "reviewed_by_human": False,
            },
            {
                "node_id": "apply_entry",
                "display_name": "Managed application entry boundary",
                "surface_type": "application",
                "state_signature": "managed-hybrid-apply-entry",
                "source_paths": [],
                "evidence": {},
                "controls": [],
                "regions": [],
                "action_candidates": [],
                "review_status": "needs_learning",
                "reviewed_by_human": False,
            },
        ],
        "edges": [
            {
                "edge_id": "home_to_detail",
                "operation_id": "home_to_detail",
                "source_node_id": "home",
                "target_node_id": "detail",
                "action_type": "open_detail",
                "action_template_id": "open_job_detail",
                "target_control_id": "job_card",
                "target_region_id": "",
                "risk_level": "low",
                "requires_user_confirmation": False,
                "preconditions": [],
                "success_conditions": ["Managed detail identity is visible"],
                "failure_conditions": [],
                "review_status": "needs_human_review",
            },
            {
                "edge_id": "detail_to_apply",
                "operation_id": "detail_to_apply",
                "source_node_id": "detail",
                "target_node_id": "apply_entry",
                "action_type": "open_apply_flow",
                "action_template_id": "open_apply_entry",
                "target_control_id": "apply_entry_control",
                "target_region_id": "",
                "risk_level": "low",
                "requires_user_confirmation": False,
                "preconditions": [],
                "success_conditions": ["Managed application entry identity is visible"],
                "failure_conditions": [],
                "review_status": "needs_human_review",
            },
        ],
        "safety": {
            "review_draft_only": True,
            "runtime_requires_fresh_capture": True,
            "runtime_requires_fresh_grounding": True,
            "runtime_requires_gate": True,
            "final_submit_forbidden": True,
        },
    }


def _approve_workflow_review(review: dict[str, Any]) -> dict[str, Any]:
    from app.agent.reviewed_workflow_compiler import (
        _GRANULAR_CONFIRMATION_CONTRACTS,
        _granular_review_revision,
    )
    from app.learn.interface_workflow_review import build_interface_node_review_revision

    approved = deepcopy(review)
    node_by_id = {node["node_id"]: node for node in approved["nodes"]}
    for edge in approved["edges"]:
        source_node = node_by_id[edge["source_node_id"]]
        target_id = edge.get("target_control_id") or edge.get("target_region_id")
        target_key = "control_id" if edge.get("target_control_id") else "region_id"
        collection = (
            source_node["controls"]
            if edge.get("target_control_id")
            else source_node["regions"]
        )
        target = next(item for item in collection if item[target_key] == target_id)
        action = next(
            item
            for item in source_node["action_candidates"]
            if item["action_template_id"] == edge["action_template_id"]
        )
        for subject, subject_kind in (
            (target, "target_control"),
            (action, "action_candidate"),
            (edge, "edge"),
        ):
            subject["review_status"] = "human_approved"
            subject["reviewed_by_human"] = True
            subject["display_only"] = True
            subject["artifact_is_authorization"] = False
            subject["execute_binding_enabled"] = False
            subject["human_review_confirmation"] = {
                "contract_version": _GRANULAR_CONFIRMATION_CONTRACTS[subject_kind],
                "revision": _granular_review_revision(subject),
            }
    for node in approved["nodes"][:2]:
        node["review_status"] = "human_approved"
        node["reviewed_by_human"] = True
        node["human_review_confirmation"] = {
            "contract_version": "interface_node_human_review_confirmation_v1",
            "revision": build_interface_node_review_revision(
                approved, node_id=node["node_id"]
            ),
        }
    return approved


def _persist_approved_workflow_via_api(
    root: Path,
    review: dict[str, Any],
    *,
    client: Any,
) -> dict[str, Any]:
    first = _post_success(
        client,
        "/panel/save_interface_workflow_review",
        {"review": review},
    )
    approved = _approve_workflow_review(first["saved_review"])
    second = _post_success(
        client,
        "/panel/save_interface_workflow_review",
        {"review": approved},
    )
    source = Path(second["path"])
    source_bytes = source.read_bytes()
    persisted = json.loads(source_bytes.decode("utf-8-sig"))
    has_vista, has_human = _contains_proposals(persisted)
    return {
        "source_path": str(source.resolve()),
        "source_relative_path": source.relative_to(root).as_posix(),
        "source_sha256": _sha256_bytes(source_bytes),
        "source_bytes": source_bytes,
        "workflow_id": second["workflow_id"],
        "application_identity_key": second["application_identity_key"],
        "review_contains_vista_proposal": has_vista,
        "review_contains_human_proposal": has_human,
    }


def build_managed_hybrid_review_source(
    project_root: str | Path,
    *,
    omni_runner: Callable[..., Mapping[str, Any]] = fake_omni_runner,
    qwen_runner: Callable[..., object] = fake_qwen_runner,
    vista_runner: Callable[..., Mapping[str, Any]] = fake_bounded_vista_runner,
) -> dict[str, Any]:
    """经公共 managed worker 生命周期和 Task 8 API 生成真实保存源。"""

    root = Path(project_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    workflow_store_path = root / "runtime_state" / "learning-workflow-runs.json"
    with _managed_panel_http_boundary(
        root,
        workflow_store_path=workflow_store_path,
        omni_runner=omni_runner,
        qwen_runner=qwen_runner,
        vista_runner=vista_runner,
    ) as (client, _store, _registry):
        lifecycle = _run_public_managed_hybrid_lifecycle(root, client=client)
        large_review = _save_public_large_review(
            root,
            client=client,
            lifecycle=lifecycle,
        )
        candidate_path = Path(large_review["reviewed_candidate_path"])
        workflow = _base_workflow_review(
            workflow_id="portfolio_hybrid_v1_1_managed",
            reviewed_candidate_path=candidate_path.relative_to(root).as_posix(),
            reviewed_candidate=large_review["reviewed_candidate"],
        )
        persisted = _persist_approved_workflow_via_api(
            root,
            workflow,
            client=client,
        )
    if not persisted["review_contains_vista_proposal"] or not persisted[
        "review_contains_human_proposal"
    ]:
        raise RuntimeError("saved workflow source lost Hybrid proposal evidence")
    return {
        **persisted,
        "provider_boundary_trace": lifecycle["provider_boundary_trace"],
        "managed_lifecycle_task_trace": lifecycle[
            "managed_lifecycle_task_trace"
        ],
        "managed_lifecycle_receipts": lifecycle["managed_lifecycle_receipts"],
        "managed_review_projection_receipt": lifecycle[
            "managed_review_projection_receipt"
        ],
        "large_review_save": {
            key: value
            for key, value in large_review.items()
            if key not in {"reviewed_candidate", "public_reload"}
        },
        "large_review_public_reload": large_review["public_reload"],
        "workflow_store_path": str(workflow_store_path.resolve()),
    }


def _api_payload(response: Any, *, operation: str) -> dict[str, Any]:
    body = response.model_dump(mode="json")
    if body.get("success") is not True or not isinstance(body.get("data"), dict):
        raise RuntimeError(f"{operation} failed: {body}")
    return body["data"]


def _worker_compile(
    *,
    root: Path,
    source_relative: str,
    expected_sha: str,
    application_identity_key: str,
    workflow_id: str,
    publish: bool,
) -> dict[str, Any]:
    os.environ.setdefault("AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER", "1")
    os.environ.setdefault("AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH", ":memory:")
    from app.api import panel as panel_api

    panel_api.ROOT_DIR = root
    source = root / source_relative
    source_bytes = source.read_bytes()
    source_sha = _sha256_bytes(source_bytes)
    if source_sha != expected_sha:
        raise RuntimeError("worker reloaded source bytes do not match expected SHA-256")
    compile_request = panel_api.PanelCompileReviewedWorkflowAssetRequest(
        application_identity_key=application_identity_key,
        workflow_id=workflow_id,
        expected_source_workflow_sha256=expected_sha,
    )
    compile_envelope = _api_payload(
        panel_api.compile_reviewed_workflow_asset_endpoint(compile_request),
        operation="compile_without_publish",
    )
    compile_data = compile_envelope.get("result")
    if not isinstance(compile_data, dict):
        raise RuntimeError(f"compile endpoint returned no result: {compile_envelope}")
    if compile_data.get("status") != "compiled" or not isinstance(
        compile_data.get("asset"), dict
    ):
        raise RuntimeError(f"compile blocked: {compile_data}")
    asset = compile_data["asset"]
    result: dict[str, Any] = {
        "pid": os.getpid(),
        "source_sha256": source_sha,
        "source_length": len(source_bytes),
        "compile_status": compile_data["status"],
        "compiled_asset_sha256": _sha256_bytes(_canonical_bytes(asset)),
        "compiled_runtime_point_fields": _runtime_point_fields(asset),
        "asset": asset,
        "publish_attempted": publish,
        "compile_registry_revision": compile_envelope["registry_revision"],
    }
    if not publish:
        result["cas_registry_exists"] = (
            root / "runtime_state" / "reviewed-workflow-assets-v2" / "registry.json"
        ).exists()
        return result

    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore

    store = ReviewedWorkflowAssetStore(project_root=root)
    before = store.registry()
    publish_request = panel_api.PanelPublishReviewedWorkflowAssetRequest(
        application_identity_key=application_identity_key,
        workflow_id=workflow_id,
        expected_source_workflow_sha256=expected_sha,
        expected_registry_revision=before["registry_revision"],
    )
    first = _api_payload(
        panel_api.publish_reviewed_workflow_asset_endpoint(publish_request),
        operation="publish_once",
    )
    duplicate = _api_payload(
        panel_api.publish_reviewed_workflow_asset_endpoint(publish_request),
        operation="duplicate_publish",
    )
    after = store.registry()
    active = store.load_active(asset["asset_id"])
    object_path = root / first["publish_result"]["object_path"]
    object_bytes = object_path.read_bytes()
    object_sha = _sha256_bytes(object_bytes)
    events = [
        event
        for event in after["events"]
        if event.get("event_type") == "publish"
        and event.get("asset_id") == asset["asset_id"]
    ]
    result.update(
        {
            "registry_revision_before": before["registry_revision"],
            "registry_revision_after": after["registry_revision"],
            "registry_publish_event_count": len(events),
            "publish_status": first["publish_result"]["status"],
            "duplicate_publish_status": duplicate["publish_result"]["status"],
            "published_object_path": str(object_path.resolve()),
            "published_object_sha256": object_sha,
            "published_runtime_point_fields": _runtime_point_fields(active),
            "registry_cas_verified": (
                first["publish_result"]["content_sha256"] == object_sha
                and after["active_by_asset"].get(asset["asset_id"]) == object_sha
                and _canonical_bytes(active) == object_bytes
            ),
        }
    )
    return result


def _run_worker_process(
    *,
    mode: str,
    root: Path,
    source_relative: str,
    expected_sha: str,
    application_identity_key: str,
    workflow_id: str,
) -> tuple[subprocess.Popen[str], dict[str, Any]]:
    command = [
        str(getattr(sys, "_base_executable", sys.executable)),
        str(Path(__file__).resolve()),
        "--worker",
        mode,
        "--project-root",
        str(root),
        "--source-relative",
        source_relative,
        "--expected-sha",
        expected_sha,
        "--application-identity-key",
        application_identity_key,
        "--workflow-id",
        workflow_id,
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER": "1",
            "AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH": ":memory:",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    python_paths = [str(REPOSITORY_ROOT), *site.getsitepackages()]
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    process = subprocess.Popen(
        command,
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    stdout, stderr = process.communicate(timeout=120)
    if process.returncode != 0:
        raise RuntimeError(
            f"{mode} worker failed with exit {process.returncode}: {stderr}\n{stdout}"
        )
    marker_lines = [line for line in stdout.splitlines() if line.startswith(_WORKER_MARKER)]
    if len(marker_lines) != 1:
        raise RuntimeError(f"{mode} worker returned no unique result: {stdout}")
    result = json.loads(marker_lines[0][len(_WORKER_MARKER) :])
    if result.get("pid") != process.pid:
        raise RuntimeError(f"{mode} worker PID identity mismatch")
    return process, result


def _child_environment(*, workflow_store_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER": "1",
            "AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH": str(workflow_store_path),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    python_paths = [str(REPOSITORY_ROOT), *site.getsitepackages()]
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    return environment


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _serve_proof_app(
    *, root: Path, workflow_store_path: Path, port: int, stop_file: Path
) -> int:
    os.environ["AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER"] = "1"
    os.environ["AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH"] = str(workflow_store_path)
    from app.api import panel as panel_api
    from app.main import app
    import uvicorn

    panel_api.ROOT_DIR = root
    panel_api.write_trace = lambda **_kwargs: "managed-proof-server-trace.json"
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )

    def watch_stop_file() -> None:
        while not stop_file.exists() and not server.should_exit:
            time.sleep(0.05)
        if stop_file.exists():
            server.should_exit = True

    Thread(target=watch_stop_file, daemon=True).start()
    server.run()
    return 0


def _http_json(
    url: str,
    *,
    payload: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    data = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {details}") from exc
    if not isinstance(body, dict):
        raise RuntimeError(f"HTTP response is not an object: {url}")
    return body


def _start_proof_server(
    *, root: Path, workflow_store_path: Path, label: str
) -> dict[str, Any]:
    port = _free_tcp_port()
    stop_file = root / "runtime_state" / f"proof-server-{label}.stop"
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.unlink(missing_ok=True)
    command = [
        str(getattr(sys, "_base_executable", sys.executable)),
        str(Path(__file__).resolve()),
        "--proof-server",
        "--project-root",
        str(root),
        "--workflow-store-path",
        str(workflow_store_path),
        "--port",
        str(port),
        "--stop-file",
        str(stop_file),
    ]
    process = subprocess.Popen(
        command,
        cwd=REPOSITORY_ROOT,
        env=_child_environment(workflow_store_path=workflow_store_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"proof server {label} exited during startup: {stderr}\n{stdout}"
            )
        try:
            _http_json(f"{base_url}/openapi.json", timeout=0.5)
            return {
                "process": process,
                "base_url": base_url,
                "stop_file": stop_file,
                "label": label,
            }
        except (RuntimeError, URLError, TimeoutError):
            time.sleep(0.05)
    process.kill()
    stdout, stderr = process.communicate(timeout=10)
    raise RuntimeError(f"proof server {label} readiness timeout: {stderr}\n{stdout}")


def _stop_proof_server(server: dict[str, Any]) -> tuple[int, str, str]:
    process: subprocess.Popen[str] = server["process"]
    stop_file: Path = server["stop_file"]
    if process.poll() is None:
        stop_file.write_text("stop\n", encoding="utf-8")
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=10)
        raise RuntimeError(
            f"proof server {server['label']} required forced termination: {stderr}\n{stdout}"
        )
    finally:
        stop_file.unlink(missing_ok=True)
    return int(process.returncode or 0), stdout, stderr


def _http_api_data(
    base_url: str, path: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    body = _http_json(f"{base_url}{path}", payload=payload, timeout=30.0)
    if body.get("success") is not True or not isinstance(body.get("data"), dict):
        raise RuntimeError(f"{path} failed: {body}")
    return body["data"]


def _raw_file_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "exists": False,
            "byte_length": 0,
            "sha256": None,
            "raw_base64": None,
        }
    raw = path.read_bytes()
    return {
        "exists": True,
        "byte_length": len(raw),
        "sha256": _sha256_bytes(raw),
        "raw_base64": base64.b64encode(raw).decode("ascii"),
    }


def _cas_snapshot(
    root: Path, *, relevant_paths: Sequence[Path] = ()
) -> dict[str, Any]:
    registry_path = (
        root / "runtime_state" / "reviewed-workflow-assets-v2" / "registry.json"
    )
    registry_raw = _raw_file_snapshot(registry_path)
    registry = (
        json.loads(registry_path.read_text(encoding="utf-8-sig"))
        if registry_path.is_file()
        else {"registry_revision": 0, "events": [], "objects": {}}
    )
    object_root = registry_path.parent / "objects"
    object_hashes = {
        path.relative_to(object_root).as_posix(): _sha256_bytes(path.read_bytes())
        for path in sorted(object_root.rglob("*"))
        if path.is_file()
    } if object_root.is_dir() else {}
    relevant = {
        path.resolve().relative_to(root.resolve()).as_posix(): _raw_file_snapshot(
            path.resolve()
        )
        for path in relevant_paths
    }
    return {
        "registry_revision": int(registry["registry_revision"]),
        "event_count": len(registry["events"]),
        "object_count": len(registry["objects"]),
        "registry_exists": registry_path.is_file(),
        "registry_raw": registry_raw,
        "registry_events": deepcopy(registry["events"]),
        "registry_objects": deepcopy(registry["objects"]),
        "cas_object_sha256_by_name": object_hashes,
        "relevant_store_files": relevant,
    }


def _write_proof_artifact(
    proof: dict[str, Any], output_path: Path
) -> dict[str, Any]:
    proof["proof_hash_scope"] = "canonical JSON excluding proof_sha256 and proof_file_sha256"
    proof["proof_artifact_path"] = str(output_path.resolve())
    body = deepcopy(proof)
    body.pop("proof_sha256", None)
    body.pop("proof_file_sha256", None)
    proof["proof_sha256"] = _sha256_bytes(_canonical_bytes(body))
    _write_json(output_path, proof)
    proof["proof_file_sha256"] = _sha256_bytes(output_path.read_bytes())
    return proof


def run_managed_two_process_persistence_proof(
    project_root: str | Path,
    *,
    omni_runner: Callable[..., Mapping[str, Any]] = fake_omni_runner,
    qwen_runner: Callable[..., object] = fake_qwen_runner,
    vista_runner: Callable[..., Mapping[str, Any]] = fake_bounded_vista_runner,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    managed = build_managed_hybrid_review_source(
        root,
        omni_runner=omni_runner,
        qwen_runner=qwen_runner,
        vista_runner=vista_runner,
    )
    source = Path(managed["source_path"])
    saved_bytes = source.read_bytes()
    source_sha = _sha256_bytes(saved_bytes)
    reviewed_path = Path(managed["large_review_save"]["reviewed_candidate_path"])
    reviewed_bytes = reviewed_path.read_bytes()
    compiler_review = json.loads(saved_bytes.decode("utf-8-sig"))
    reviewed_candidate = json.loads(reviewed_bytes.decode("utf-8-sig"))
    reviewed_draft = reviewed_candidate["draft"]
    reviewed_projection = reviewed_draft["hybrid_review_projection"]
    capture_lineage_ref = deepcopy(reviewed_draft["capture_lineage_ref"])
    reviewed_relative = reviewed_path.relative_to(root).as_posix()
    reviewed_source_nodes = [
        node
        for node in compiler_review.get("nodes", [])
        if isinstance(node, dict)
        and isinstance(node.get("source_paths"), list)
        and reviewed_relative in node["source_paths"]
    ]
    compiler_source_references_reviewed = len(reviewed_source_nodes) == 1
    review_has_vista, review_has_human = _contains_proposals(compiler_review)
    if not compiler_source_references_reviewed:
        raise RuntimeError("compiler source does not reference exact Task 8 reviewed candidate")
    if not review_has_vista or not review_has_human:
        raise RuntimeError("compiler review source lost non-authorizing Hybrid proposals")
    reviewed_source_node = reviewed_source_nodes[0]
    workflow_store_path = Path(managed["workflow_store_path"])
    compile_payload = {
        "application_identity_key": managed["application_identity_key"],
        "workflow_id": managed["workflow_id"],
        "expected_source_workflow_sha256": source_sha,
    }
    read_only_paths = (workflow_store_path, source, reviewed_path)
    cas_before_a = _cas_snapshot(root, relevant_paths=read_only_paths)
    server_a: dict[str, Any] | None = None
    server_b: dict[str, Any] | None = None
    server_a_exit_code: int | None = None
    server_b_exit_code: int | None = None
    try:
        server_a = _start_proof_server(
            root=root,
            workflow_store_path=workflow_store_path,
            label="a",
        )
        server_pid_a = server_a["process"].pid
        compile_a_envelope = _http_api_data(
            server_a["base_url"],
            "/panel/compile_reviewed_workflow_asset",
            compile_payload,
        )
        compile_a = compile_a_envelope.get("result")
        if not isinstance(compile_a, dict) or compile_a.get("status") != "compiled":
            raise RuntimeError(f"server A compile blocked: {compile_a_envelope}")
        cas_after_a = _cas_snapshot(root, relevant_paths=read_only_paths)
        server_a_exit_code, _stdout_a, stderr_a = _stop_proof_server(server_a)
        if server_a_exit_code != 0:
            raise RuntimeError(f"proof server A cleanup failed: {stderr_a}")
        process_a_terminated = server_a["process"].poll() is not None
        if not process_a_terminated:
            raise RuntimeError("server A did not terminate before server B")

        server_b = _start_proof_server(
            root=root,
            workflow_store_path=workflow_store_path,
            label="b",
        )
        server_pid_b = server_b["process"].pid
        reload_b = _http_api_data(
            server_b["base_url"],
            "/panel/load_learning_draft_review",
            {
                "source_path": reviewed_relative,
                "workflow_run_id": managed["large_review_save"]["workflow_run_id"],
                "discover_related_sidecars": False,
            },
        )
        public_reload_b_exact = (
            reviewed_path.read_bytes() == reviewed_bytes
            and reload_b.get("hybrid_review_projection_status", {}).get("status")
            == "projected"
            and len(reload_b.get("hybrid_review_projection", {}).get("review_decisions", []))
            == 1
        )
        reload_projection = reload_b.get("hybrid_review_projection") or {}
        reload_draft = reload_b.get("draft") or {}
        public_reload_b_identity = {
            "source_path": (reload_b.get("source") or {}).get("source_path"),
            "source_sha256": (reload_b.get("source") or {}).get("sha256"),
            "capture_lineage_ref": deepcopy(
                (reload_projection.get("screen_facts") or {}).get(
                    "capture_lineage_ref"
                )
            ),
            "projection_ledger_digest": reload_projection.get("content_sha256"),
            "decision_ledger_digest": _sha256_bytes(
                _canonical_bytes(reload_projection.get("review_decisions") or [])
            ),
        }
        compile_b_envelope = _http_api_data(
            server_b["base_url"],
            "/panel/compile_reviewed_workflow_asset",
            compile_payload,
        )
        compile_b = compile_b_envelope.get("result")
        if not isinstance(compile_b, dict) or compile_b.get("status") != "compiled":
            raise RuntimeError(f"server B compile blocked: {compile_b_envelope}")
        cas_before_publish = _cas_snapshot(root, relevant_paths=read_only_paths)
        publish_payload = {
            **compile_payload,
            "expected_registry_revision": cas_before_publish["registry_revision"],
        }
        first_publish = _http_api_data(
            server_b["base_url"],
            "/panel/publish_reviewed_workflow_asset",
            publish_payload,
        )
        cas_after_publish = _cas_snapshot(root, relevant_paths=read_only_paths)
        duplicate_publish = _http_api_data(
            server_b["base_url"],
            "/panel/publish_reviewed_workflow_asset",
            publish_payload,
        )
        cas_after_duplicate = _cas_snapshot(root, relevant_paths=read_only_paths)
        server_b_exit_code, _stdout_b, stderr_b = _stop_proof_server(server_b)
        if server_b_exit_code != 0:
            raise RuntimeError(f"proof server B cleanup failed: {stderr_b}")
    finally:
        for active in (server_a, server_b):
            if active is not None and active["process"].poll() is None:
                _stop_proof_server(active)

    if server_pid_a == server_pid_b:
        raise RuntimeError("fresh app server proof reused the same PID")
    if source.read_bytes() != saved_bytes:
        raise RuntimeError("saved compiler source bytes changed across process restart")
    if reviewed_path.read_bytes() != reviewed_bytes or not public_reload_b_exact:
        raise RuntimeError("server B did not publicly reload exact Task 8 saved bytes")
    asset_a = compile_a["asset"]
    asset_b = compile_b["asset"]
    compiled_sha_a = _sha256_bytes(_canonical_bytes(asset_a))
    compiled_sha_b = _sha256_bytes(_canonical_bytes(asset_b))
    source_sha_a = asset_a["source_review_lineage"]["source_workflow_sha256"]
    source_sha_b = asset_b["source_review_lineage"]["source_workflow_sha256"]
    if source_sha_a != source_sha_b or source_sha_a != source_sha:
        raise RuntimeError("fresh server reloaded different compiler source bytes")
    if compiled_sha_a != compiled_sha_b:
        raise RuntimeError("fresh server compile is not deterministic")
    publish_result = first_publish["publish_result"]
    duplicate_result = duplicate_publish["publish_result"]
    event_delta = cas_after_publish["event_count"] - cas_before_publish["event_count"]
    duplicate_event_delta = (
        cas_after_duplicate["event_count"] - cas_after_publish["event_count"]
    )
    revision_delta = (
        cas_after_publish["registry_revision"]
        - cas_before_publish["registry_revision"]
    )
    duplicate_revision_delta = (
        cas_after_duplicate["registry_revision"]
        - cas_after_publish["registry_revision"]
    )
    new_events = cas_after_publish["registry_events"][
        cas_before_publish["event_count"] :
    ]
    if len(new_events) != 1:
        raise RuntimeError("publish did not append exactly one registry event")
    single_publish_event = deepcopy(new_events[0])
    from app.agent.reviewed_workflow_asset import (
        ReviewedWorkflowAssetStore,
        content_sha256,
    )

    store = ReviewedWorkflowAssetStore(project_root=root)
    active = store.load_active(asset_b["asset_id"])
    active_sha = content_sha256(active)
    object_path = root / publish_result["object_path"]
    object_sha = _sha256_bytes(object_path.read_bytes())
    load_active_sha = _sha256_bytes(_canonical_bytes(active))
    published_runtime_points = _runtime_point_fields(active)
    asset_safety = asset_b["safety"]
    registry_cas_verified = (
        publish_result["content_sha256"]
        == compiled_sha_b
        == active_sha
        == object_sha
        == load_active_sha
    )
    predicates = {
        "distinct_server_pids": server_pid_a != server_pid_b,
        "server_a_exited_before_b": process_a_terminated,
        "both_servers_clean": server_a_exit_code == 0 and server_b_exit_code == 0,
        "public_exact_managed_reload": public_reload_b_exact,
        "compiler_source_sha_equal": source_sha == source_sha_a == source_sha_b,
        "compiled_asset_sha_equal": compiled_sha_a == compiled_sha_b,
        "compile_a_read_only": cas_before_a == cas_after_a,
        "one_registry_revision": revision_delta == 1,
        "one_registry_event": event_delta == 1,
        "duplicate_idempotent": (
            duplicate_result["status"] == "already_published"
            and duplicate_event_delta == 0
            and duplicate_revision_delta == 0
        ),
        "registry_cas_verified": registry_cas_verified,
        "no_runtime_point_values": published_runtime_points == [],
        "fresh_grounding_gate_preserved": (
            asset_safety["fresh_grounding_required"] is True
            and asset_safety["real_action_requires_gate"] is True
            and asset_safety["post_action_verification_required"] is True
        ),
        "non_authorizing": (
            asset_safety["artifact_is_authorization"] is False
            and asset_safety["execute_binding_enabled"] is False
        ),
    }
    proof = {
        "contract_version": PROOF_CONTRACT,
        "proof_mode": "managed_e2e_fake_provider_boundaries",
        "sequence": list(SEQUENCE),
        "provider_boundary_trace": managed["provider_boundary_trace"],
        "managed_lifecycle_task_trace": managed[
            "managed_lifecycle_task_trace"
        ],
        "managed_lifecycle_receipts": managed["managed_lifecycle_receipts"],
        "managed_review_projection_receipt": managed[
            "managed_review_projection_receipt"
        ],
        "large_review_save": managed["large_review_save"],
        "server_http_boundary": True,
        "managed_reviewed_source_path": str(reviewed_path.resolve()),
        "managed_reviewed_source_sha256": _sha256_bytes(reviewed_bytes),
        "managed_capture_lineage_ref": capture_lineage_ref,
        "managed_capture_lineage_digest": capture_lineage_ref[
            "content_sha256"
        ],
        "managed_projection_ledger_digest": reviewed_projection[
            "content_sha256"
        ],
        "managed_decision_ledger_digest": _sha256_bytes(
            _canonical_bytes(reviewed_projection["review_decisions"])
        ),
        "compiler_source_path": str(source.resolve()),
        "compiler_reviewed_source_node_id": reviewed_source_node["node_id"],
        "compiler_reviewed_source_field": "nodes[*].source_paths",
        "compiler_reviewed_source_relative_path": reviewed_relative,
        "compiler_reviewed_source_sha256": _sha256_bytes(reviewed_bytes),
        "saved_compiler_source_sha256": source_sha,
        "compiler_source_references_managed_reviewed_source": compiler_source_references_reviewed,
        "review_source_vista_proposal_present": review_has_vista,
        "review_source_human_proposal_present": review_has_human,
        "saved_source_path": str(source.resolve()),
        "saved_source_sha256": source_sha,
        "source_bytes_sha256": _sha256_bytes(saved_bytes),
        "source_byte_length": len(saved_bytes),
        "server_pid_a": server_pid_a,
        "server_pid_b": server_pid_b,
        "server_a_exit_code": server_a_exit_code,
        "server_b_exit_code": server_b_exit_code,
        "process_a_terminated_before_b": process_a_terminated,
        "all_subprocesses_terminated": (
            server_a["process"].poll() is not None
            and server_b["process"].poll() is not None
        ),
        "public_reload_b_exact_managed_bytes": public_reload_b_exact,
        "public_reload_b_identity": public_reload_b_identity,
        "compile_a_status": compile_a["status"],
        "compile_b_status": compile_b["status"],
        "compile_a_registry_revision_before": cas_before_a["registry_revision"],
        "compile_a_registry_revision_after": cas_after_a["registry_revision"],
        "compile_a_read_only_snapshot_before": cas_before_a,
        "compile_a_read_only_snapshot_after": cas_after_a,
        "source_sha_a": source_sha_a,
        "source_sha_b": source_sha_b,
        "compiled_asset_sha_a": compiled_sha_a,
        "compiled_asset_sha_b": compiled_sha_b,
        "publish_count": event_delta,
        "publish_status": publish_result["status"],
        "duplicate_publish_status": duplicate_result["status"],
        "registry_revision_before": cas_before_publish["registry_revision"],
        "registry_revision_after": cas_after_duplicate["registry_revision"],
        "registry_publish_event_count": event_delta,
        "single_publish_event": single_publish_event,
        "published_asset_id": asset_b["asset_id"],
        "event_count_delta": event_delta,
        "duplicate_event_count_delta": duplicate_event_delta,
        "duplicate_registry_revision_delta": duplicate_revision_delta,
        "registry_cas_verified": registry_cas_verified,
        "active_content_sha256": active_sha,
        "object_file_sha256": object_sha,
        "load_active_content_sha256": load_active_sha,
        "published_object_path": str(object_path.resolve()),
        "published_object_sha256": object_sha,
        "published_runtime_point_fields": published_runtime_points,
        "fresh_runtime_grounding_required": asset_safety[
            "fresh_grounding_required"
        ],
        "runtime_gate_required": asset_safety["real_action_requires_gate"],
        "post_action_verification_required": asset_safety[
            "post_action_verification_required"
        ],
        "artifact_is_authorization": asset_safety["artifact_is_authorization"],
        "execute_binding_enabled": asset_safety["execute_binding_enabled"],
        "predicate_results": predicates,
        "all_predicates_satisfied": all(predicates.values()),
    }
    destination = (
        Path(output_path).resolve()
        if output_path is not None
        else root
        / "runtime_state"
        / "portfolio-hybrid-v1-1"
        / "persistence-proof-managed-e2e.json"
    )
    return _write_proof_artifact(proof, destination)


def run_fixture_negative_control(
    *, project_root: str | Path, fixture_path: str | Path
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    fixture = Path(fixture_path).resolve()
    raw = json.loads(fixture.read_text(encoding="utf-8-sig"))
    with _managed_panel_http_boundary(
        root,
        workflow_store_path=root
        / "runtime_state"
        / "learning-workflow-runs.json",
        omni_runner=fake_omni_runner,
        qwen_runner=fake_qwen_runner,
        vista_runner=fake_bounded_vista_runner,
    ) as (client, _store, _registry):
        workflow = _persist_approved_workflow_via_api(root, raw, client=client)
    worker = _worker_compile(
        root=root,
        source_relative=workflow["source_relative_path"],
        expected_sha=workflow["source_sha256"],
        application_identity_key=workflow["application_identity_key"],
        workflow_id=workflow["workflow_id"],
        publish=False,
    )
    has_vista, has_human = _contains_proposals(raw)
    return {
        "contract_version": PROOF_CONTRACT,
        "proof_mode": "fixture_negative_control_only",
        "fixture_path": str(fixture),
        "fixture_sha256": _sha256_bytes(fixture.read_bytes()),
        "fixture_contains_non_authorizing_proposals": has_vista and has_human,
        "compiled_status": worker["compile_status"],
        "compiled_asset_sha256": worker["compiled_asset_sha256"],
        "compiled_runtime_point_fields": worker["compiled_runtime_point_fields"],
        "publish_attempted": False,
        "registry_exists": (
            root / "runtime_state" / "reviewed-workflow-assets-v2" / "registry.json"
        ).exists(),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--managed-e2e", action="store_true")
    parser.add_argument("--fake-provider-boundaries", action="store_true")
    parser.add_argument("--fixture")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--proof-server", action="store_true")
    parser.add_argument("--worker", choices=["compile-a", "compile-publish-b"])
    parser.add_argument("--project-root")
    parser.add_argument("--workflow-store-path")
    parser.add_argument("--port", type=int)
    parser.add_argument("--stop-file")
    parser.add_argument("--source-relative")
    parser.add_argument("--expected-sha")
    parser.add_argument("--application-identity-key")
    parser.add_argument("--workflow-id")
    arguments = parser.parse_args()

    if arguments.proof_server:
        if not all(
            (
                arguments.project_root,
                arguments.workflow_store_path,
                arguments.port,
                arguments.stop_file,
            )
        ):
            parser.error(
                "proof server requires project root, workflow store, port and stop file"
            )
        return _serve_proof_app(
            root=Path(arguments.project_root).resolve(),
            workflow_store_path=Path(arguments.workflow_store_path).resolve(),
            port=arguments.port,
            stop_file=Path(arguments.stop_file).resolve(),
        )

    if arguments.worker:
        required = (
            arguments.project_root,
            arguments.source_relative,
            arguments.expected_sha,
            arguments.application_identity_key,
            arguments.workflow_id,
        )
        if not all(required):
            parser.error("worker mode requires project/source/SHA/identity/workflow arguments")
        result = _worker_compile(
            root=Path(arguments.project_root).resolve(),
            source_relative=arguments.source_relative,
            expected_sha=arguments.expected_sha,
            application_identity_key=arguments.application_identity_key,
            workflow_id=arguments.workflow_id,
            publish=arguments.worker == "compile-publish-b",
        )
        print(_WORKER_MARKER + json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    if not arguments.output:
        parser.error("--output is required")
    output = Path(arguments.output).resolve()
    workspace = output.parent / f"managed-persistence-workspace-{os.getpid()}"
    if arguments.managed_e2e:
        if not arguments.fake_provider_boundaries:
            parser.error("managed E2E proof requires --fake-provider-boundaries")
        proof = run_managed_two_process_persistence_proof(
            workspace,
            output_path=output,
        )
    elif arguments.fixture:
        if not arguments.no_publish:
            parser.error("fixture mode is negative-control only and requires --no-publish")
        proof = run_fixture_negative_control(
            project_root=workspace,
            fixture_path=arguments.fixture,
        )
        proof = _write_proof_artifact(proof, output)
    else:
        parser.error("choose --managed-e2e or --fixture")
    print(json.dumps(proof, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
