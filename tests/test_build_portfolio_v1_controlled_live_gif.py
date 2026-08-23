from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont, ImageSequence


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_portfolio_v1_controlled_live_gif.py"


def _load_builder_module():
    spec = importlib.util.spec_from_file_location("portfolio_controlled_live_builder", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BUILDER_MODULE = _load_builder_module()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verification_ref(verification: dict[str, object]) -> str:
    canonical = json.dumps(
        verification,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "verification:" + hashlib.sha256(canonical).hexdigest()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = Path(r"C:\Windows\Fonts\arial.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def _write_sources(tmp_path: Path) -> tuple[Path, Path]:
    pre = Image.new("RGB", (1390, 1211), "white")
    pre_draw = ImageDraw.Draw(pre)
    pre_draw.rectangle((190, 680, 1120, 1070), fill="#f7f8fb")
    pre_draw.text((260, 720), "Entry-Level Sales & Recruitment", fill="#12264a", font=_font(38))
    pre_draw.rounded_rectangle((266, 975, 411, 1022), radius=9, fill="#e6007e")
    pre_draw.text((285, 986), "Quick apply", fill="white", font=_font(22))
    pre_path = tmp_path / "pre.png"
    pre.save(pre_path)

    post = Image.new("RGB", (1390, 1211), "white")
    post_draw = ImageDraw.Draw(post)
    post_draw.text((220, 225), "Applying for", fill="#314267", font=_font(24))
    post_draw.text((220, 420), "Choose documents", fill="#12264a", font=_font(28))
    post_draw.rectangle((180, 548, 1200, 1211), fill="#ff00ff")
    post_draw.text((220, 590), "PERSON NAME +64 person@example.test private_resume.pdf", fill="black", font=_font(24))
    post_path = tmp_path / "post.png"
    post.save(post_path)
    return pre_path, post_path


def _receipt_payload(post_sha256: str) -> dict[str, object]:
    backend_ref = "backend-receipt:test-controlled-live"
    candidate_ref = "candidate:test-controlled-live"
    capture_evidence_ref = "capture:test-controlled-live"
    gate_ref = "gate:test-controlled-live:allowed"
    resolution_ref = "resolution:test-controlled-live"
    selection_ref = "selection:" + "b" * 64
    trace_ref = "trace:test-controlled-live"
    session_id = "session.test-controlled-live"
    source_observation_id = "observation.test-source"
    next_observation_id = "observation.test-next"
    transition_id = "transition.test-open-apply-flow"
    source_state_id = "state.test-job-detail"
    target_state_id = "state.test-choose-documents"
    workflow = {
        "asset_content_sha256": "a" * 64,
        "asset_id": "workflow.test-controlled-live",
        "reviewed_revision_hash": "d" * 64,
        "source_workflow_sha256": "c" * 64,
        "workflow_id": "portfolio_v1_seek_apply_entry",
    }
    capture = {
        "capture_id": "runtime-capture.test-post",
        "screenshot_sha256": post_sha256,
        "viewport_size": {"height": 1211, "width": 1390},
    }
    verification = {
        "contract_version": "transition_verification_v1",
        "status": "verified",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "state_advanced": True,
        "asset_content_sha256": workflow["asset_content_sha256"],
        "selection_sha256": "b" * 64,
        "transition_id": transition_id,
        "source_state_id": source_state_id,
        "target_state_id": target_state_id,
        "post_capture_lineage": copy.deepcopy(capture),
        "post_state_resolution": {
            "artifact_is_authorization": False,
            "asset_content_sha256": workflow["asset_content_sha256"],
            "asset_id": workflow["asset_id"],
            "canonical_origin": "https://nz.seek.com",
            "contract_version": "current_state_resolution_v1",
            "evidence_refs": ["current-recognition:test-controlled-live"],
            "execute_binding_enabled": False,
            "matched_anchor_ids": ["anchor.test-choose-documents"],
            "observed_origin": "https://nz.seek.com",
            "resolution_sha256": "e" * 64,
            "reviewed_revision_hash": workflow["reviewed_revision_hash"],
            "score": 0.86,
            "source_workflow_sha256": workflow["source_workflow_sha256"],
            "status": "resolved",
            "state_id": target_state_id,
            "state_availability": "stop_boundary",
            "capture_lineage": copy.deepcopy(capture),
        },
        "evidence_refs": [
            backend_ref,
            candidate_ref,
            "current-recognition:test-controlled-live",
            gate_ref,
            selection_ref,
            trace_ref,
        ],
    }
    verification_ref = _verification_ref(verification)
    return {
        "backend_receipt": {
            "reason_code": "none",
            "receipt_ref": backend_ref,
            "status": "dispatched",
        },
        "runtime_receipt": {
            "receipt_id": "receipt.test-controlled-live",
            "contract_version": "runtime_result_receipt_v1",
            "issued_at": "2026-08-24T00:00:00Z",
            "session_id": session_id,
            "observation_id": source_observation_id,
            "intent_id": "intent.test-controlled-live",
            "next_observation_id": next_observation_id,
            "attempt_count": 1,
            "action": {
                "action_id": transition_id,
                "semantic_action": "open_apply_flow",
            },
            "gate_status": "allowed",
            "dispatch_status": "dispatched",
            "effect_status": "verified",
            "destination_status": "verified",
            "outcome": "SAFE_STOP",
            "reason_code": "stop_boundary",
            "safe_stop": {"reason_code": "stop_boundary", "required": True},
            "evidence": {
                "backend_receipt_ref": backend_ref,
                "candidate_ref": candidate_ref,
                "gate_decision_ref": gate_ref,
                "selection_ref": selection_ref,
                "state_resolution_ref": resolution_ref,
                "trace_refs": [trace_ref],
                "verification_ref": verification_ref,
            },
            "workflow": copy.deepcopy(workflow),
            "artifact_is_authorization": False,
        },
        "next_observation": {
            "contract_version": "agent_observation_v1",
            "session_id": session_id,
            "observation_id": next_observation_id,
            "workflow": copy.deepcopy(workflow),
            "application": {
                "display_name": "web:nz.seek.com",
                "identity_ref": "application:web:nz.seek.com",
                "kind": "web",
            },
            "state_resolution_ref": resolution_ref,
            "current_capture": {
                "capture_id": capture["capture_id"],
                "evidence_ref": capture_evidence_ref,
                "screenshot_sha256": post_sha256,
            },
            "state": {
                "display_name": "Choose documents",
                "state_availability": "stop_boundary",
                "status": "stop_boundary",
                "surface_type": "application_entry",
                "state_id": target_state_id,
                "resolution_sha256": "e" * 64,
                "responsibility": "Stop at the reviewed terminal boundary.",
                "source_interface_id": "apply_entry",
            },
            "semantic_facts": [],
            "evidence_refs": [resolution_ref, capture_evidence_ref],
            "blockers": [
                {
                    "blocker_id": "blocker.stop_boundary",
                    "blocker_type": "state",
                    "description": "Runtime requires safe stop: stop_boundary.",
                    "evidence_refs": [resolution_ref],
                    "safe_stop_required": True,
                }
            ],
            "safe_stop": {"reason_code": "stop_boundary", "required": True},
            "available_actions": [
                {
                    "action_id": "runtime.safe_stop",
                    "description": "Stop without dispatching another action.",
                    "expected_effect": "Stop without dispatching another action.",
                    "requires_user_confirmation": False,
                    "risk_level": "low",
                    "semantic_action": "safe_stop",
                    "target_state_id": None,
                    "verification_rule_refs": [],
                }
            ],
            "artifact_is_authorization": False,
        },
        "verification_evidence": verification,
    }


def _write_receipt(tmp_path: Path, post_sha256: str) -> Path:
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(_receipt_payload(post_sha256)), encoding="utf-8")
    return path


def _set_nested(payload: dict[str, object], dotted_path: str, value: object) -> None:
    current: object = payload
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        assert isinstance(current, dict)
        current = current[part]
    assert isinstance(current, dict)
    current[parts[-1]] = value


def test_builder_creates_post_receipt_bound_public_safe_replay(tmp_path: Path) -> None:
    pre, post = _write_sources(tmp_path)
    receipt = _write_receipt(tmp_path, _sha256(post))
    output = tmp_path / "controlled-live.gif"
    manifest = tmp_path / "controlled-live.manifest.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--pre",
            str(pre),
            "--post",
            str(post),
            "--receipt",
            str(receipt),
            "--output",
            str(output),
            "--manifest",
            str(manifest),
            "--forbidden-token",
            "SecretName",
        ],
        cwd=ROOT,
        capture_output=True,
        text=False,
        check=False,
    )

    assert completed.returncode == 0, (completed.stderr or completed.stdout).decode("utf-8", errors="replace")
    assert completed.stderr == b""
    assert output.is_file()
    assert manifest.is_file()

    manifest_text = manifest.read_text(encoding="utf-8")
    payload = json.loads(manifest_text)
    for private_input in (str(tmp_path), pre.name, post.name, receipt.name):
        assert private_input not in manifest_text
    assert payload["artifact_kind"] == "post-receipt-bound controlled-live replay"
    assert payload["continuous_recording"] is False
    assert "real_runtime_capture" not in payload
    assert "post capture is cryptographically bound" in payload["claim_boundary"].lower()
    assert "pre capture is separately hashed and is not receipt-bound" in payload["claim_boundary"].lower()
    assert payload["receipt"]["receipt_id"] == "receipt.test-controlled-live"
    assert payload["receipt"]["content_ref"] == f"sha256:{_sha256(receipt)}"
    assert payload["receipt"]["availability"] == "not_published"
    assert "path" not in payload["receipt"]
    assert payload["sources"]["pre"]["content_ref"] == f"sha256:{_sha256(pre)}"
    assert payload["sources"]["pre"]["receipt_binding"] == "unbound_supplemental_capture"
    assert payload["sources"]["post"]["content_ref"] == f"sha256:{_sha256(post)}"
    assert payload["sources"]["post"]["receipt_binding"] == "bound_by_receipt_screenshot_sha256"
    assert all(source["availability"] == "not_published" and "path" not in source for source in payload["sources"].values())
    assert payload["receipt"]["validated_claims"] == {
        "attempt_count": 1,
        "semantic_action": "open_apply_flow",
        "gate_status": "allowed",
        "backend_dispatch_count": 1,
        "effect_status": "verified",
        "destination": "Choose documents / application_entry",
        "safe_stop_required": True,
        "next_action_projection": ["safe_stop"],
        "form_mutation_or_followup_dispatch_evidenced": False,
    }
    assert payload["privacy"]["post_crop_excludes_y_at_or_below"] <= 548
    assert payload["privacy"]["source_masks"]
    assert "excluded_classes" not in payload["privacy"]
    assert payload["privacy"]["source_mask_intent"] == [
        "operator identity regions",
        "contact and profile details",
        "resume filenames",
        "account identifiers",
    ]
    assert payload["privacy"]["automated_scan_scope"] == [
        "required_denylist_token",
        "email",
        "new_zealand_phone_+64",
        "new_zealand_phone_local_02x",
        "pdf_or_resume_filename",
    ]

    with Image.open(output) as gif:
        frames = [frame.convert("RGB") for frame in ImageSequence.Iterator(gif)]
        durations = [int(frame.info.get("duration", 0)) for frame in ImageSequence.Iterator(gif)]
        assert gif.size == (960, 540)
        assert len(frames) == 120
        assert durations == [100] * 120
        assert sum(durations) == 12_000
        assert all(pixel != (255, 0, 255) for frame in frames for pixel in frame.get_flattened_data())

    assert payload["render"]["canvas_size"] == [960, 540]
    assert payload["render"]["frame_count"] == 120
    assert payload["render"]["frame_duration_ms"] == 100
    assert payload["render"]["duration_ms"] == 12_000
    assert payload["render"]["transition"]["label"] == "editorial crossfade — not continuous recording"
    assert not Path(payload["output"]["path"]).is_absolute()
    assert payload["output"]["sha256"] == _sha256(output)
    assert payload["privacy"]["frame_scan"]["frames_scanned"] == 120
    assert payload["privacy"]["frame_scan"]["forbidden_matches"] == []


@pytest.mark.parametrize(
    ("field", "bad_value", "refresh_verification_ref"),
    [
        ("runtime_receipt.attempt_count", 2, False),
        ("runtime_receipt.action.semantic_action", "fill_field", False),
        ("runtime_receipt.gate_status", "blocked", False),
        ("backend_receipt.status", "indeterminate", False),
        ("runtime_receipt.evidence.backend_receipt_ref", "backend-receipt:different", False),
        ("runtime_receipt.effect_status", "failed", False),
        ("next_observation.state.display_name", "Job Detail", False),
        ("next_observation.state.surface_type", "detail", False),
        ("next_observation.safe_stop.required", False, False),
        (
            "next_observation.available_actions",
            [{"action_id": "runtime.continue", "semantic_action": "continue_next_step"}],
            False,
        ),
        ("verification_evidence.status", "failed", True),
        ("verification_evidence.state_advanced", False, True),
        ("verification_evidence.transition_id", "transition.different", True),
        ("verification_evidence.asset_content_sha256", "c" * 64, True),
        ("next_observation.workflow.asset_content_sha256", "d" * 64, False),
        ("next_observation.workflow.workflow_id", "different_workflow", False),
        ("next_observation.session_id", "session.different", False),
        ("next_observation.observation_id", "observation.different", False),
        ("runtime_receipt.evidence.verification_ref", "verification:" + "e" * 64, False),
        ("verification_evidence.target_state_id", "state.different", True),
        ("verification_evidence.post_state_resolution.state_id", "state.different", True),
        ("verification_evidence.post_state_resolution.asset_id", "asset.forged", True),
        ("verification_evidence.post_state_resolution.asset_content_sha256", "f" * 64, True),
        ("verification_evidence.post_state_resolution.reviewed_revision_hash", "f" * 64, True),
        ("verification_evidence.post_state_resolution.source_workflow_sha256", "f" * 64, True),
        ("verification_evidence.post_state_resolution.resolution_sha256", "f" * 64, True),
        ("verification_evidence.post_state_resolution.contract_version", "forged_v1", True),
        ("verification_evidence.post_state_resolution.observed_origin", "https://evil.invalid", True),
        ("verification_evidence.post_state_resolution.artifact_is_authorization", True, True),
        ("verification_evidence.post_state_resolution.execute_binding_enabled", True, True),
        (
            "verification_evidence.post_state_resolution.capture_lineage.viewport_size",
            {"height": 1, "width": 1},
            True,
        ),
        ("verification_evidence.post_state_resolution.evidence_refs", [], True),
    ],
)
def test_receipt_claim_validation_rejects_mismatches(
    field: str,
    bad_value: object,
    refresh_verification_ref: bool,
) -> None:
    post_sha256 = "b" * 64
    payload = _receipt_payload(post_sha256)
    _set_nested(payload, field, bad_value)
    if refresh_verification_ref:
        verification = payload["verification_evidence"]
        runtime = payload["runtime_receipt"]
        assert isinstance(verification, dict)
        assert isinstance(runtime, dict)
        evidence = runtime["evidence"]
        assert isinstance(evidence, dict)
        evidence["verification_ref"] = _verification_ref(verification)

    with pytest.raises(ValueError):
        BUILDER_MODULE._validate_receipt(payload, post_sha256)


@pytest.mark.parametrize(
    "field",
    [
        "next_observation.current_capture.screenshot_sha256",
        "verification_evidence.post_capture_lineage.screenshot_sha256",
        "verification_evidence.post_state_resolution.capture_lineage.screenshot_sha256",
    ],
)
def test_receipt_claim_validation_rejects_post_capture_hash_mismatch(field: str) -> None:
    post_sha256 = "b" * 64
    payload = _receipt_payload(post_sha256)
    _set_nested(payload, field, "c" * 64)

    with pytest.raises(ValueError):
        BUILDER_MODULE._validate_receipt(payload, post_sha256)


def test_audit_rejects_crop_inside_private_identifiers(tmp_path: Path) -> None:
    image = Image.new("RGB", (960, 540), "white")
    draw = ImageDraw.Draw(image)
    font = _font(36)
    lines = [
        "person@example.test",
        "+64 21 123 4567",
        "021 123 4567",
        "SecretName_resume.pdf",
    ]
    for index, line in enumerate(lines):
        draw.text((50, 50 + 85 * index), line, fill="black", font=font)
    path = tmp_path / "private.gif"
    image.save(path, format="GIF", duration=100, loop=0)

    audit = BUILDER_MODULE.audit_public_gif(path, ["SecretName"])
    categories = {match["category"] for match in audit.forbidden_matches}

    assert categories == {
        "required_denylist_token",
        "email",
        "new_zealand_phone_+64",
        "new_zealand_phone_local_02x",
        "pdf_or_resume_filename",
    }


def test_builder_requires_at_least_one_forbidden_token() -> None:
    args = argparse.Namespace(
        pre="missing-pre.png",
        post="missing-post.png",
        receipt="missing-receipt.json",
        output="missing-output.gif",
        manifest="missing-manifest.json",
        forbidden_token=[],
    )

    with pytest.raises(ValueError, match="forbidden-token"):
        BUILDER_MODULE.build(args)
