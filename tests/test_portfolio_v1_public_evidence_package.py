from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "release" / "portfolio-v1" / "evidence"
RELEASE_MANIFEST = ROOT / "release" / "portfolio-v1" / "review-draft-manifest.json"
ROOT_README = ROOT / "README.md"
RELEASE_README = ROOT / "release" / "portfolio-v1" / "README.md"

SOURCE_WORKFLOW_SHA256 = "a934acc82708cfd956110ba2bba35e8d0bc317af9e095606efab87c5f3e027bc"
ASSET_SHA256 = "8284e1729409aa0a4f6a751a1a03d85fc51db1c7d53d473bd012455a3fc391b7"
PRIVATE_PARENT_SHA256 = "8d5f94cebbbb7b6de6b2a144390fbbb37fa6c018f51e82789af0f797266c485e"
RECEIPT_ID = "receipt.38d529e464f94dbf858ec4d18de90c7c"

EXPECTED_FILES = {
    "manifest.json",
    "receipts/controlled-live-receipt.public.json",
    "controls/matched-negative-controls.json",
    "rollback/navigation-restore.public.json",
    "schemas/manifest.schema.json",
    "schemas/public-receipt.schema.json",
    "schemas/matched-negative-controls.schema.json",
    "schemas/operator-cleanup.schema.json",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _assert_exact_keys(payload: dict, expected: set[str]) -> None:
    assert set(payload) == expected


def _walk(value, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield path + (key,), child
            yield from _walk(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path + (str(index),))


def test_public_evidence_manifest_is_content_addressed_and_schema_bound() -> None:
    actual_files = {
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in PACKAGE_ROOT.rglob("*")
        if path.is_file()
    }
    assert actual_files == EXPECTED_FILES

    manifest = _json(PACKAGE_ROOT / "manifest.json")
    _assert_exact_keys(
        manifest,
        {
            "contract_version",
            "package_id",
            "workflow",
            "status",
            "evidence_grade_taxonomy",
            "artifacts",
            "privacy",
            "claim_boundary",
        },
    )
    assert manifest["contract_version"] == "portfolio_v1_public_evidence_manifest_v1"
    assert manifest["package_id"] == "portfolio_v1_public_evidence"
    assert manifest["workflow"] == {
        "workflow_id": "portfolio_v1_seek_apply_entry",
        "source_workflow_sha256": SOURCE_WORKFLOW_SHA256,
        "asset_content_sha256": ASSET_SHA256,
    }
    assert manifest["status"] == {
        "package": "complete",
        "independent_review": "accepted",
        "release_status_promotion": "eligible",
        "controlled_live_workflow_proven": True,
    }
    assert manifest["evidence_grade_taxonomy"] == {
        "exact_live": "A projection of one observed real Runtime receipt.",
        "deterministic_exact_current_asset": (
            "A deterministic test that loads the exact checked-in current release asset."
        ),
        "deterministic_behavior_equivalent_synthetic_fixture": (
            "A deterministic LiveController/runtime-contract test using a behavior-equivalent "
            "synthetic fixture; it is not exact-current-asset or live evidence."
        ),
        "operator_cleanup_commitment": (
            "An operator cleanup statement without a retained raw cleanup artifact."
        ),
    }

    artifacts = manifest["artifacts"]
    assert [item["path"] for item in artifacts] == sorted(
        EXPECTED_FILES - {"manifest.json", "schemas/manifest.schema.json"}
    ) + ["schemas/manifest.schema.json"]
    assert len(artifacts) == len(EXPECTED_FILES) - 1
    for item in artifacts:
        _assert_exact_keys(item, {"path", "sha256", "role", "schema_path"})
        path = PACKAGE_ROOT / item["path"]
        assert path.is_file()
        assert item["sha256"] == _sha256(path)
        assert (PACKAGE_ROOT / item["schema_path"]).is_file()
        assert re.fullmatch(r"[0-9a-f]{64}", item["sha256"])

    assert manifest["privacy"] == {
        "projection_only": True,
        "contains_raw_runtime_object": False,
        "contains_raw_capture": False,
        "contains_personal_or_page_specific_fields": False,
    }
    assert "one bounded" in manifest["claim_boundary"].lower()
    assert "general reliability" in manifest["claim_boundary"].lower()


def test_public_receipt_is_a_minimal_exact_live_projection() -> None:
    receipt = _json(PACKAGE_ROOT / "receipts" / "controlled-live-receipt.public.json")
    _assert_exact_keys(
        receipt,
        {
            "contract_version",
            "projection_kind",
            "private_parent_object_sha256",
            "receipt_id",
            "workflow",
            "action",
            "gate",
            "backend",
            "verification",
            "terminal",
            "dispatch_accounting",
            "evidence_grade",
            "privacy",
            "claim_boundary",
        },
    )
    assert receipt["contract_version"] == "portfolio_v1_public_runtime_receipt_v1"
    assert receipt["projection_kind"] == "allowlisted_projection"
    assert receipt["private_parent_object_sha256"] == PRIVATE_PARENT_SHA256
    assert receipt["receipt_id"] == RECEIPT_ID
    assert receipt["workflow"] == {
        "workflow_id": "portfolio_v1_seek_apply_entry",
        "source_workflow_sha256": SOURCE_WORKFLOW_SHA256,
        "asset_content_sha256": ASSET_SHA256,
    }
    assert receipt["action"] == {
        "semantic_action": "open_apply_flow",
        "attempt_count": 1,
    }
    assert receipt["gate"] == {"status": "allowed"}
    assert receipt["backend"] == {"dispatch_status": "dispatched"}
    assert receipt["verification"] == {
        "effect_status": "verified",
        "destination_status": "verified",
        "post_state": {
            "state_id": "state_apply_entry_0e2ad9884555ee4fa7ba9d7fc697f4d2",
            "display_name": "Choose documents",
            "availability": "stop_boundary",
        },
    }
    assert receipt["terminal"] == {
        "outcome": "SAFE_STOP",
        "reason_code": "stop_boundary",
    }
    assert receipt["dispatch_accounting"] == {
        "runtime_dispatch_count": 1,
        "unexpected_dispatch_count": 0,
    }
    assert receipt["evidence_grade"] == "exact_live"
    assert receipt["privacy"] == {
        "allowlisted_projection": True,
        "raw_parent_included": False,
        "raw_capture_included": False,
        "page_specific_identity_included": False,
    }
    assert "not provider accuracy" in receipt["claim_boundary"].lower()
    assert "not production readiness" in receipt["claim_boundary"].lower()


def test_matched_negative_controls_separate_exact_and_equivalent_evidence() -> None:
    controls = _json(PACKAGE_ROOT / "controls" / "matched-negative-controls.json")
    _assert_exact_keys(
        controls,
        {
            "contract_version",
            "workflow",
            "controls",
            "summary",
            "claim_boundary",
        },
    )
    assert controls["contract_version"] == "portfolio_v1_matched_negative_controls_v1"
    assert controls["workflow"] == {
        "workflow_id": "portfolio_v1_seek_apply_entry",
        "source_workflow_sha256": SOURCE_WORKFLOW_SHA256,
        "asset_content_sha256": ASSET_SHA256,
    }
    by_id = {item["control_id"]: item for item in controls["controls"]}
    expected_results = {
        "stale_capture_or_observation_zero_dispatch": {
            "reason_code": "stale_candidate",
            "runtime_dispatch_count": 0,
        },
        "wrong_window_or_identity_mismatch_zero_dispatch": {
            "reason_codes": ["foreground_window_changed", "target_occluded"],
            "runtime_dispatch_count": 0,
        },
        "ambiguous_current_candidate_zero_dispatch": {
            "reason_code": "grounding_ambiguous",
            "runtime_dispatch_count": 0,
        },
        "unknown_or_unauthorized_intent_zero_dispatch": {
            "status": "REJECTED",
            "runtime_dispatch_count": 0,
        },
        "continue_form_or_terminal_boundary_safe_stop": {
            "post_state_availability": "stop_boundary",
            "available_semantic_actions": ["safe_stop"],
            "continuation_or_mutation_actions_present": False,
        },
        "semantic_verification_failure_terminal": {
            "outcome": "VERIFICATION_FAILED",
            "runtime_dispatch_count": 1,
        },
        "confirmation_required_zero_dispatch": {
            "confirmation_status": "NEEDS_REVIEW",
            "runtime_dispatch_count": 0,
        },
        "duplicate_approval_and_intent_zero_redispatch": {
            "initial_runtime_dispatch_count": 1,
            "additional_runtime_dispatch_count": 0,
            "stored_receipt_reused": True,
        },
    }
    assert set(by_id) == set(expected_results)
    for control_id, expected_result in expected_results.items():
        _assert_exact_keys(
            by_id[control_id],
            {
                "control_id",
                "contract_surface",
                "evidence_grade",
                "live_observed",
                "result",
                "source",
            },
        )
        assert by_id[control_id]["live_observed"] is False
        assert by_id[control_id]["result"] == expected_result

    exact_source = {
        "path": "tests/test_portfolio_v1_release_callsite.py",
        "sha256": _sha256(ROOT / "tests" / "test_portfolio_v1_release_callsite.py"),
        "test": "test_current_release_workspace_runs_confirmation_duplicate_and_stop_controls",
        "asset_relationship": "exact_current_asset",
    }
    exact_current_ids = {
        "confirmation_required_zero_dispatch",
        "duplicate_approval_and_intent_zero_redispatch",
        "continue_form_or_terminal_boundary_safe_stop",
    }
    for control_id in exact_current_ids:
        assert by_id[control_id]["evidence_grade"] == "deterministic_exact_current_asset"
        assert by_id[control_id]["source"] == exact_source

    historical_source_path = ROOT / "tests" / "test_live_controller_w4.py"
    historical_sha = _sha256(historical_source_path)
    for control_id, control in by_id.items():
        if control_id in exact_current_ids:
            continue
        assert (
            control["evidence_grade"]
            == "deterministic_behavior_equivalent_synthetic_fixture"
        )
        assert control["source"]["path"] == "tests/test_live_controller_w4.py"
        assert control["source"]["sha256"] == historical_sha
        assert (
            control["source"]["asset_relationship"]
            == "deterministic_behavior_equivalent_synthetic_fixture"
        )

    expected_contract_surfaces = {
        "stale_capture_or_observation_zero_dispatch": "runtime_result_receipt_v1",
        "wrong_window_or_identity_mismatch_zero_dispatch": "runtime_result_receipt_v1",
        "ambiguous_current_candidate_zero_dispatch": "runtime_result_receipt_v1",
        "unknown_or_unauthorized_intent_zero_dispatch": "live_controller_decision",
        "continue_form_or_terminal_boundary_safe_stop": "runtime_result_receipt_v1",
        "semantic_verification_failure_terminal": "runtime_result_receipt_v1",
        "confirmation_required_zero_dispatch": "live_controller_decision",
        "duplicate_approval_and_intent_zero_redispatch": "runtime_result_receipt_v1",
    }
    assert {
        control_id: control["contract_surface"]
        for control_id, control in by_id.items()
    } == expected_contract_surfaces

    assert controls["summary"] == {
        "control_count": 8,
        "canonical_control_count": 6,
        "supplemental_control_count": 2,
        "exact_live_control_count": 0,
        "deterministic_exact_current_asset_count": 3,
        "deterministic_behavior_equivalent_synthetic_fixture_count": 5,
    }
    assert "six canonical" in controls["claim_boundary"].lower()
    assert "production livecontroller/runtime behavior" in controls["claim_boundary"].lower()
    assert "only controls with contract_surface runtime_result_receipt_v1 are receipts" in controls["claim_boundary"].lower()
    assert "supplemental" in controls["claim_boundary"].lower()


def test_public_control_matrix_covers_canonical_categories_with_honest_asset_relationships() -> None:
    controls = _json(PACKAGE_ROOT / "controls" / "matched-negative-controls.json")
    by_id = {item["control_id"]: item for item in controls["controls"]}

    canonical_control_ids = {
        "stale_capture_or_observation_zero_dispatch",
        "wrong_window_or_identity_mismatch_zero_dispatch",
        "ambiguous_current_candidate_zero_dispatch",
        "unknown_or_unauthorized_intent_zero_dispatch",
        "continue_form_or_terminal_boundary_safe_stop",
        "semantic_verification_failure_terminal",
    }
    supplemental_control_ids = {
        "confirmation_required_zero_dispatch",
        "duplicate_approval_and_intent_zero_redispatch",
    }
    assert set(by_id) == canonical_control_ids | supplemental_control_ids

    exact_current_ids = {
        "confirmation_required_zero_dispatch",
        "duplicate_approval_and_intent_zero_redispatch",
        "continue_form_or_terminal_boundary_safe_stop",
    }
    for control_id, control in by_id.items():
        source = control["source"]
        source_path = ROOT / source["path"]
        assert source_path.is_file()
        assert source["sha256"] == _sha256(source_path)
        assert f"def {source['test']}(" in source_path.read_text(encoding="utf-8")
        if control_id in exact_current_ids:
            assert control["evidence_grade"] == "deterministic_exact_current_asset"
            assert source["asset_relationship"] == "exact_current_asset"
            assert source["path"] == "tests/test_portfolio_v1_release_callsite.py"
            assert source["test"] == (
                "test_current_release_workspace_runs_confirmation_duplicate_and_stop_controls"
            )
        else:
            assert (
                control["evidence_grade"]
                == "deterministic_behavior_equivalent_synthetic_fixture"
            )
            assert (
                source["asset_relationship"]
                == "deterministic_behavior_equivalent_synthetic_fixture"
            )

    assert controls["summary"] == {
        "control_count": 8,
        "canonical_control_count": 6,
        "supplemental_control_count": 2,
        "exact_live_control_count": 0,
        "deterministic_exact_current_asset_count": 3,
        "deterministic_behavior_equivalent_synthetic_fixture_count": 5,
    }
    assert "six canonical" in controls["claim_boundary"].lower()
    assert "production livecontroller/runtime behavior" in controls["claim_boundary"].lower()
    assert "only controls with contract_surface runtime_result_receipt_v1 are receipts" in controls["claim_boundary"].lower()
    assert "supplemental" in controls["claim_boundary"].lower()


def test_operator_cleanup_record_does_not_invent_missing_raw_evidence() -> None:
    cleanup = _json(PACKAGE_ROOT / "rollback" / "navigation-restore.public.json")
    _assert_exact_keys(
        cleanup,
        {
            "contract_version",
            "cleanup_kind",
            "positive_receipt_binding",
            "restore",
            "evidence_grade",
            "evidence_status",
            "raw_artifact",
            "claim_boundary",
        },
    )
    assert cleanup["contract_version"] == "portfolio_v1_operator_cleanup_v1"
    assert cleanup["cleanup_kind"] == "operator_cleanup"
    assert cleanup["positive_receipt_binding"] == {
        "receipt_id": RECEIPT_ID,
        "private_parent_object_sha256": PRIVATE_PARENT_SHA256,
    }
    assert cleanup["restore"] == {
        "post_state": "Job Detail",
        "additional_runtime_dispatch_count": 0,
        "external_mutation_performed": False,
    }
    assert cleanup["evidence_grade"] == "operator_cleanup_commitment"
    assert cleanup["evidence_status"] == "passive_semantic_restore_evidence_commitment"
    assert cleanup["raw_artifact"] == {
        "present": False,
        "reference": None,
        "sha256": None,
    }
    assert "not independently replayable" in cleanup["claim_boundary"].lower()
    assert "does not prove" in cleanup["claim_boundary"].lower()


def test_public_package_has_no_private_runtime_or_page_identity_payloads() -> None:
    forbidden_keys = {
        "bbox",
        "candidate",
        "candidate_id",
        "capture_id",
        "click_point",
        "company",
        "email",
        "full_url",
        "hwnd",
        "job_title",
        "operator_name",
        "phone",
        "pid",
        "process_id",
        "raw_capture",
        "raw_page",
        "resume_filename",
        "screenshot",
        "target_window_handle",
        "url",
        "window_title",
    }
    text_patterns = (
        re.compile(r"https?://", re.IGNORECASE),
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        re.compile(r"\b(?:\+?64|0)2\d(?:[ -]?\d){6,9}\b"),
    )
    for relative in sorted(EXPECTED_FILES):
        payload = _json(PACKAGE_ROOT / relative)
        for path, value in _walk(payload):
            assert path[-1].lower() not in forbidden_keys, (relative, path)
            if isinstance(value, str):
                if path == ("$schema",):
                    continue
                for pattern in text_patterns:
                    assert not pattern.search(value), (relative, path, pattern.pattern)
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        assert "runtime_state/runtime-receipts-v1/objects" not in serialized
        assert "microsoft-edge" not in serialized
        assert "artifacts/screenshots" not in serialized


def test_control_schema_rejects_duplicate_or_omitted_categories_with_draft202012(
    tmp_path: Path,
) -> None:
    schema_path = PACKAGE_ROOT / "schemas" / "matched-negative-controls.schema.json"
    controls = _json(PACKAGE_ROOT / "controls" / "matched-negative-controls.json")
    duplicate_and_omitted = deepcopy(controls)
    duplicate_and_omitted["controls"][1] = deepcopy(
        duplicate_and_omitted["controls"][0]
    )
    omitted = deepcopy(controls)
    omitted["controls"].pop()

    for name, mutation in {
        "duplicate-and-omitted": duplicate_and_omitted,
        "omitted": omitted,
    }.items():
        instance_path = tmp_path / f"{name}.json"
        instance_path.write_text(
            json.dumps(mutation, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                "uvx",
                "check-jsonschema",
                "--schemafile",
                str(schema_path),
                str(instance_path),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert completed.returncode != 0, completed.stdout + completed.stderr


def test_public_schemas_freeze_contract_versions_and_disallow_extra_fields() -> None:
    expected = {
        "schemas/manifest.schema.json": "portfolio_v1_public_evidence_manifest_v1",
        "schemas/public-receipt.schema.json": "portfolio_v1_public_runtime_receipt_v1",
        "schemas/matched-negative-controls.schema.json": (
            "portfolio_v1_matched_negative_controls_v1"
        ),
        "schemas/operator-cleanup.schema.json": "portfolio_v1_operator_cleanup_v1",
    }
    for relative, contract_version in expected.items():
        schema = _json(PACKAGE_ROOT / relative)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        contract = schema["properties"]["contract_version"]
        assert contract == {"const": contract_version}
        assert set(schema["required"]) == set(schema["properties"])

    controls_schema = _json(
        PACKAGE_ROOT / "schemas" / "matched-negative-controls.schema.json"
    )
    controls_array_schema = controls_schema["properties"]["controls"]
    assert controls_array_schema.get("uniqueItems") is True
    variants = controls_array_schema["items"]["oneOf"]
    assert len(variants) == 8
    assert {
        item["properties"]["control_id"]["const"] for item in variants
    } == {
        "stale_capture_or_observation_zero_dispatch",
        "wrong_window_or_identity_mismatch_zero_dispatch",
        "ambiguous_current_candidate_zero_dispatch",
        "unknown_or_unauthorized_intent_zero_dispatch",
        "continue_form_or_terminal_boundary_safe_stop",
        "semantic_verification_failure_terminal",
        "confirmation_required_zero_dispatch",
        "duplicate_approval_and_intent_zero_redispatch",
    }
    assert all(item["additionalProperties"] is False for item in variants)


def test_reviewed_package_promotes_only_the_bounded_live_workflow_claim() -> None:
    package = _json(PACKAGE_ROOT / "manifest.json")
    release = _json(RELEASE_MANIFEST)
    readme = ROOT_README.read_text(encoding="utf-8-sig")
    release_readme = RELEASE_README.read_text(encoding="utf-8-sig")

    assert package["status"]["independent_review"] == "accepted"
    assert package["status"]["release_status_promotion"] == "eligible"
    assert package["status"]["controlled_live_workflow_proven"] is True
    assert release["controlled_live_workflow_proven"] is True
    assert "Portfolio v1 close-out (W6) | **Partial" in readme
    assert "Portfolio v1 close-out (W6) | **Stable" not in readme
    assert "evidence/manifest.json" in release_readme
    assert "independent review" in release_readme.lower()
    assert "belongs to a later release slice" not in release_readme
