from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review import exact_review as exact_review_module
from app.desktop_review.exact_review import ExactReviewError
from app.desktop_review.workspace import NativeReviewFacade


_TOKEN = "exact-review-token"
_BINDING = {"kind": "native", "display_name": "Notepad", "executable_identity": "notepad.exe", "product_name": "Notepad"}


def _png_bytes(colour: str = "white") -> bytes:
    image = Image.new("RGB", (80, 60), colour)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _batch(*, action_type: str = "open_detail") -> dict:
    return {
        "contract_version": "agent_link_v1", "idempotency_key": "exact-review-batch", "batch_id": "exact-review-batch",
        "title": "Untrusted Notepad draft", "learning_outcome": "completed",
        "screenshots": [{"screenshot_id": "screen", "png_base64": base64.b64encode(_png_bytes()).decode("ascii")}],
        "interfaces": [{"interface_id": "list", "screenshot_id": "screen", "meaning": "list", "regions": [{"region_id": "open", "bbox": [2.0, 3.0, 20.0, 12.0], "name": "Open", "meaning": "open details"}]}],
        "relationships": [],
        "steps": [{"step_id": "open", "action_type": action_type, "target_region_id": "open", "start_state": "list", "arrival_state": "list", "prerequisites": [], "expected_result": "details visible", "stop_condition": "stop"}],
        "issues": [],
    }


def _new_runtime(tmp_path: Path, batch: dict | None = None):
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, _TOKEN)
    grant = service.reviewer_call(_TOKEN, "create_connection", {"task_id": "task", "agent_name": "fixture"})
    service.agent_call(grant["token"], "submit_batch", batch or _batch())
    facade = NativeReviewFacade(service, _TOKEN, tmp_path / "root")
    workspace = facade.save_revision("task", "exact-review-batch", 0, facade.load_batch("task", "exact-review-batch")["batch"])
    return store, service, facade, workspace


def _prepare(facade: NativeReviewFacade, workspace: dict, **kwargs) -> dict:
    return facade.prepare_exact_review("task", "exact-review-batch", workspace["revision"], deepcopy(_BINDING), **kwargs)


def _complete(facade: NativeReviewFacade, prepared: dict) -> dict:
    approved = facade.record_review_decisions(prepared["review_ref"], prepared["approval_revision"], [subject["subject_id"] for subject in prepared["subjects"]])
    return facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"])


def _record_dir(root: Path) -> Path:
    records = list((root / "desktop-review" / "exact-reviews").glob("*/current.json"))
    assert len(records) == 1
    return records[0].parent


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def test_exact_review_requires_complete_subjects_and_supports_withdrawal(tmp_path: Path) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        prepared = _prepare(facade, workspace)
        assert prepared["contract_version"] == "desktop_exact_review_v1"
        assert prepared["status"] == "prepared"
        assert prepared["review_ref"]
        assert not any(subject["confirmed"] for subject in prepared["subjects"])
        partial = facade.record_review_decisions(prepared["review_ref"], 0, [prepared["subjects"][0]["subject_id"]])
        assert partial["approval_revision"] == 1
        assert facade.compile_exact_review(prepared["review_ref"], 1)["status"] == "blocked"
        compiled = _complete(facade, partial)
        assert compiled["status"] == "compiled", compiled
        published = facade.publish_exact_review(compiled["compile_receipt_id"])
        assert published["status"] == "published"
        asset_summary = facade.list_reviewed_assets()[0]
        assert asset_summary["content_sha256"] == published["content_sha256"]
        assert asset_summary["application"] == "notepad.exe"
        assert asset_summary["display_name"] == "Notepad"
        withdrawn = facade.record_review_decisions(prepared["review_ref"], compiled["approval_revision"], [])
        assert withdrawn["compile_receipt_id"] is None
        with pytest.raises(ExactReviewError, match="stale"):
            facade.publish_exact_review(compiled["compile_receipt_id"])
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize(("action_type", "stops"), (("observe", []), ("safe_stop", ["list"])))
def test_declaration_steps_are_subjects_not_executable_edges(tmp_path: Path, action_type: str, stops: list[str]) -> None:
    batch = _batch(action_type=action_type)
    if action_type == "safe_stop":
        batch["interfaces"].append(
            {"interface_id": "terminal", "screenshot_id": "screen", "meaning": "terminal", "recognition_text": "terminal", "regions": []}
        )
        batch["steps"][0]["action_type"] = "open_detail"
        batch["steps"][0]["arrival_state"] = "terminal"
        batch["steps"].append(
            {"step_id": "stop", "action_type": "safe_stop", "target_region_id": None, "start_state": "terminal", "arrival_state": "terminal", "prerequisites": [], "expected_result": "workflow ended", "stop_condition": "ended"}
        )
        stops = ["terminal"]
    store, _, facade, workspace = _new_runtime(tmp_path, batch)
    try:
        prepared = _prepare(facade, workspace, stop_interface_ids=stops)
        step_subjects = [item for item in prepared["subjects"] if item["kind"] == "step"]
        assert [item["content"] for item in step_subjects] == batch["steps"]
        declaration_subject_ids = {
            item["subject_id"]
            for item in prepared["subjects"]
            if item["kind"] in {"action", "edge"}
            and item["content"].get("external_step_id") == ("stop" if action_type == "safe_stop" else "open")
        }
        assert not declaration_subject_ids
        assert not prepared["blocked_reasons"]
        compiled = _complete(facade, prepared)
        assert compiled["status"] == "compiled", compiled
        receipt = _load(_record_dir(tmp_path / "root") / f"receipt-{compiled['compile_receipt_id']}.json")
        assert len(receipt["asset"]["transitions"]) == (1 if action_type == "safe_stop" else 0)
        if action_type == "safe_stop":
            assert receipt["asset"]["states"][1]["availability"] == "stop_boundary"
    finally:
        facade.close(); store.close()


def test_dangerous_action_from_stop_node_is_still_a_blocker(tmp_path: Path) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path, _batch(action_type="final_submit"))
    try:
        prepared = _prepare(facade, workspace, stop_interface_ids=["list"])
        assert any(item["code"] == "unsafe_or_unknown_action" for item in prepared["blocked_reasons"])
        blocked = _complete(facade, prepared)
        assert blocked["status"] == "blocked"
        assert any(item["code"] in {"semantic_action_not_mvp_executable", "stop_boundary_has_outgoing_transition"} for item in blocked["blocked_reasons"])
    finally:
        facade.close(); store.close()


def test_partial_review_survives_facade_restart(tmp_path: Path) -> None:
    store, service, facade, workspace = _new_runtime(tmp_path)
    prepared = _prepare(facade, workspace)
    facade.record_review_decisions(prepared["review_ref"], 0, [prepared["subjects"][0]["subject_id"]])
    facade.close()
    restarted = NativeReviewFacade(service, _TOKEN, tmp_path / "root")
    try:
        same = _prepare(restarted, workspace)
        assert same["review_ref"] == prepared["review_ref"]
        assert same["approval_revision"] == 1
        assert [item["confirmed"] for item in same["subjects"]].count(True) == 1
        assert restarted.compile_exact_review(same["review_ref"], 1)["status"] == "blocked"
    finally:
        restarted.close(); store.close()


def test_compile_and_publish_are_idempotent_across_registry_revision_change(tmp_path: Path) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        prepared = _prepare(facade, workspace)
        compiled = _complete(facade, prepared)
        receipt_id = compiled["compile_receipt_id"]
        assert facade.compile_exact_review(prepared["review_ref"], compiled["approval_revision"])["compile_receipt_id"] == receipt_id
        assert facade.publish_exact_review(receipt_id)["status"] == "published"
        assert facade.compile_exact_review(prepared["review_ref"], compiled["approval_revision"])["compile_receipt_id"] == receipt_id
        assert facade.publish_exact_review(receipt_id)["status"] == "already_published"
    finally:
        facade.close(); store.close()


def test_compile_refreshes_stale_unpublished_receipt_after_unrelated_publish(tmp_path: Path) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        first = _prepare(facade, workspace)
        first_compiled = _complete(facade, first)
        old_receipt_id = first_compiled["compile_receipt_id"]

        second = facade.prepare_exact_review(
            "task", "exact-review-batch", workspace["revision"],
            {"kind": "native", "display_name": "Calculator", "executable_identity": "calc.exe", "product_name": "Calculator"},
        )
        second_compiled = _complete(facade, second)
        assert facade.publish_exact_review(second_compiled["compile_receipt_id"])["status"] == "published"
        with pytest.raises(ExactReviewError, match="registry revision mismatch"):
            facade.publish_exact_review(old_receipt_id)

        refreshed = facade.compile_exact_review(first["review_ref"], first_compiled["approval_revision"])
        assert refreshed["status"] == "compiled"
        assert refreshed["compile_receipt_id"] != old_receipt_id
        assert facade.publish_exact_review(refreshed["compile_receipt_id"])["status"] == "published"
        with pytest.raises(ExactReviewError, match="stale"):
            facade.publish_exact_review(old_receipt_id)
    finally:
        facade.close(); store.close()


def test_record_retry_reuses_orphan_approval_after_current_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        prepared = _prepare(facade, workspace)
        wanted = [prepared["subjects"][0]["subject_id"]]
        original_atomic = exact_review_module._atomic
        failed = False

        def fail_current_once(path: Path, value: dict) -> None:
            nonlocal failed
            if path.name == "current.json" and value.get("approval_revision") == 1 and not failed:
                failed = True
                raise ExactReviewError("injected current write failure")
            original_atomic(path, value)

        monkeypatch.setattr(exact_review_module, "_atomic", fail_current_once)
        with pytest.raises(ExactReviewError, match="injected"):
            facade.record_review_decisions(prepared["review_ref"], 0, wanted)
        orphan = _load(_record_dir(tmp_path / "root") / "approval-1.json")
        monkeypatch.setattr(exact_review_module, "_atomic", original_atomic)
        recovered = facade.record_review_decisions(prepared["review_ref"], 0, wanted)
        assert recovered["approval_revision"] == 1
        current = _load(_record_dir(tmp_path / "root") / "current.json")
        assert current["recorded_at"] == orphan["recorded_at"]
        assert [item["subject_id"] for item in recovered["subjects"] if item["confirmed"]] == wanted
    finally:
        facade.close(); store.close()


def test_restart_recovers_matching_child_orphan_and_rejects_conflicting_retry(tmp_path: Path) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    prepared = _prepare(facade, workspace)
    wanted = [prepared["subjects"][0]["subject_id"]]
    facade.close(); store.close()
    script = "\n".join(
        [
            "import os, sys",
            "from pathlib import Path",
            "from app.agent_link import AgentLinkService, AgentLinkStore",
            "from app.desktop_review.workspace import NativeReviewFacade",
            "from app.desktop_review import exact_review as module",
            "store = AgentLinkStore(Path(sys.argv[1]))",
            "facade = NativeReviewFacade(AgentLinkService(store, sys.argv[2]), sys.argv[2], Path(sys.argv[3]))",
            "real_atomic = module._atomic",
            "def crash(path, value):",
            "    if path.name == 'current.json' and value.get('approval_revision') == 1: os._exit(23)",
            "    real_atomic(path, value)",
            "module._atomic = crash",
            "facade.record_review_decisions(sys.argv[4], 0, [sys.argv[5]])",
            "os._exit(24)",
        ]
    )
    environment = dict(os.environ)
    environment.update({"PYTHONIOENCODING": "utf-8", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH": ":memory:", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "CUDA_VISIBLE_DEVICES": ""})
    child = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "inbox.json"), _TOKEN, str(tmp_path / "root"), prepared["review_ref"], wanted[0]],
        cwd=Path(__file__).resolve().parents[1], env=environment, capture_output=True, text=True, timeout=20,
    )
    assert child.returncode == 23, child.stderr

    reopened_store = AgentLinkStore(tmp_path / "inbox.json")
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, _TOKEN), _TOKEN, tmp_path / "root")
    try:
        with pytest.raises(ExactReviewError, match="orphan|conflict"):
            reopened.record_review_decisions(prepared["review_ref"], 0, [prepared["subjects"][1]["subject_id"]])
        recovered = reopened.record_review_decisions(prepared["review_ref"], 0, wanted)
        assert recovered["approval_revision"] == 1
    finally:
        reopened.close(); reopened_store.close()


def test_distinct_native_display_and_product_identity_survives_compile(tmp_path: Path) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        prepared = facade.prepare_exact_review(
            "task", "exact-review-batch", workspace["revision"],
            {"kind": "native", "display_name": "Editor view", "executable_identity": "editor.exe", "product_name": "Editor Pro"},
        )
        compiled = _complete(facade, prepared)
        assert compiled["status"] == "compiled", compiled
        receipt = _load(_record_dir(tmp_path / "root") / f"receipt-{compiled['compile_receipt_id']}.json")
        assert prepared["application_identity"]["identity_key"] == "native:editor.exe:editor-pro"
        assert receipt["asset"]["application"]["executable"] == "editor.exe"
        assert receipt["asset"]["application"]["product_identity"] == "editor-pro"
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("suffix", [".png", ".json"])
def test_publish_rejects_tampered_final_dependency(tmp_path: Path, suffix: str) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        compiled = _complete(facade, _prepare(facade, workspace))
        receipt = _load(_record_dir(tmp_path / "root") / f"receipt-{compiled['compile_receipt_id']}.json")
        final_path = _resolve(tmp_path / "root", receipt["final_path"])
        candidates = [_resolve(tmp_path / "root", value) for value in receipt["final_dependencies"] if value.endswith(suffix) and _resolve(tmp_path / "root", value).resolve() != final_path.resolve()]
        assert candidates
        candidates[0].write_bytes(candidates[0].read_bytes() + b"tampered")
        with pytest.raises(ExactReviewError, match="dependenc"):
            facade.publish_exact_review(compiled["compile_receipt_id"])
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("field", ["asset", "asset_id", "asset_sha256", "final_sha256", "receipt_id"])
def test_publish_rejects_tampered_receipt(tmp_path: Path, field: str) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        compiled = _complete(facade, _prepare(facade, workspace))
        path = _record_dir(tmp_path / "root") / f"receipt-{compiled['compile_receipt_id']}.json"
        receipt = _load(path)
        if field == "asset":
            receipt[field]["asset_id"] += "_forged"
        else:
            receipt[field] = str(receipt[field]) + "forged"
        _write(path, receipt)
        with pytest.raises(ExactReviewError, match="receipt|asset|source"):
            facade.publish_exact_review(compiled["compile_receipt_id"])
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("field", ["subjects", "options", "review_ref"])
def test_operations_reject_tampered_preparation_record(tmp_path: Path, field: str) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        prepared = _prepare(facade, workspace)
        path = _record_dir(tmp_path / "root") / "current.json"
        record = _load(path)
        if field == "subjects": record[field][0]["label"] = "forged"
        elif field == "options": record[field]["stop_interface_ids"] = ["forged"]
        else: record[field] = "f" * 64
        _write(path, record)
        requested_ref = record["review_ref"] if field == "review_ref" else prepared["review_ref"]
        with pytest.raises(ExactReviewError, match="preparation|subject|option|record|review"):
            facade.record_review_decisions(requested_ref, 0, [])
    finally:
        facade.close(); store.close()


def test_compile_rejects_forged_current_confirmation_set(tmp_path: Path) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        prepared = _prepare(facade, workspace)
        path = _record_dir(tmp_path / "root") / "current.json"
        record = _load(path)
        record["confirmed_subject_ids"] = sorted(item["subject_id"] for item in record["subjects"])
        _write(path, record)
        with pytest.raises(ExactReviewError, match="approval|confirmation"):
            facade.compile_exact_review(prepared["review_ref"], 0)
    finally:
        facade.close(); store.close()


def test_operations_reject_staging_path_outside_project_root(tmp_path: Path) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        prepared = _prepare(facade, workspace)
        path = _record_dir(tmp_path / "root") / "current.json"
        record = _load(path); record["staging_path"] = str(tmp_path / "outside.json"); _write(path, record)
        with pytest.raises(ExactReviewError, match="project-relative|preparation"):
            facade.record_review_decisions(prepared["review_ref"], 0, [])
    finally:
        facade.close(); store.close()


def test_workspace_revision_change_invalidates_exact_review(tmp_path: Path) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        prepared = _prepare(facade, workspace)
        edited = deepcopy(workspace["batch"]); edited["interfaces"][0]["meaning"] = "changed after preparation"
        facade.save_revision("task", "exact-review-batch", workspace["revision"], edited)
        with pytest.raises(ExactReviewError, match="revision|current"):
            facade.record_review_decisions(prepared["review_ref"], 0, [])
    finally:
        facade.close(); store.close()


def test_prepare_rejects_invalid_binding_relationship_and_stop(tmp_path: Path) -> None:
    store, _, facade, workspace = _new_runtime(tmp_path)
    try:
        with pytest.raises(ExactReviewError, match="executable_identity"):
            facade.prepare_exact_review("task", "exact-review-batch", workspace["revision"], {"kind": "native", "display_name": "title only"})
        with pytest.raises(ExactReviewError, match="relationship"):
            _prepare(facade, workspace, step_relationships={"open": ["missing"]})
        with pytest.raises(ExactReviewError, match="stop"):
            _prepare(facade, workspace, stop_interface_ids=["missing"])
    finally:
        facade.close(); store.close()
