"""新界面与补充截图必须通过真实候选采用链持久化。"""
from copy import deepcopy
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.agent_link import AgentLinkService, AgentLinkStore
from app.agent_link.contracts import AgentLinkError
from app.desktop_review.external_mapping import source_image_relative_path
from app.desktop_review.external_mapping import assert_source_identity, normalize_agent_link_batch, ExternalMappingError
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
from test_agent_link_flow_candidates import REVIEWER_TOKEN
from test_agent_link_flow_candidates import flow_batch
from test_desktop_flow_candidates import _setup, _submit
from test_desktop_missing_flow_entities import _adopt, _artifacts


def new_interface_changes():
    image = Image.new("RGB", (320, 200), "#e9f3fa")
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), "DETAIL / NEW EVIDENCE", fill="#123456")
    draw.rectangle((20, 100, 120, 140), fill="#e2cc92", outline="#123456")
    draw.text((30, 113), "BACK", fill="#123456")
    output = BytesIO()
    image.save(output, format="PNG")
    return [
        {"change_type": "steps_add", "after_step_id": "s1", "steps": [
            {"step_id": "new-return", "action_type": "open_detail", "target_region_id": "r-new",
             "start_state": "i-new", "arrival_state": "i1", "prerequisites": ["核对新增详情界面"],
             "expected_result": "返回原界面", "stop_condition": "不一致则停止"}]},
        {"change_type": "interfaces_add", "anchor_interface_id": "i1",
         "screenshots": [{"screenshot_id": "shot-new", "png_base64": base64.b64encode(output.getvalue()).decode("ascii")}],
         "interfaces": [{"interface_id": "i-new", "screenshot_id": "shot-new", "meaning": "新增详情界面",
                         "regions": [{"region_id": "r-new", "bbox": [20., 100., 100., 40.],
                                      "name": "返回", "meaning": "返回之前界面"}]}]},
        {"change_type": "relationships_add", "relationships": [
            {"relationship_id": "rel-new", "from_interface_id": "i1", "to_interface_id": "i-new", "kind": "打开详情"}]},
    ]


def _candidate(service, grant, facade):
    return _submit(service, grant, facade, changes=new_interface_changes())


def _reopen(path, root):
    store = AgentLinkStore(path)
    service = AgentLinkService(store, REVIEWER_TOKEN)
    facade = NativeReviewFacade(service, REVIEWER_TOKEN, root)
    return store, service, facade


def test_interface_identity_extension_requires_explicit_adoption_gate():
    original = normalize_agent_link_batch(flow_batch())
    proposed = deepcopy(flow_batch())
    change = new_interface_changes()[1]
    proposed["screenshots"].extend(change["screenshots"])
    proposed["interfaces"].extend(change["interfaces"])
    added = normalize_agent_link_batch(proposed)
    with pytest.raises(ExternalMappingError):
        assert_source_identity(original, added)
    assert_source_identity(original, added, allow_interface_additions=True)
    for field in ("screenshots", "interfaces"):
        invalid = deepcopy(added)
        invalid[field].reverse()
        with pytest.raises(ExternalMappingError):
            assert_source_identity(original, invalid, allow_interface_additions=True)


def test_new_png_candidate_adopt_edit_reopen_next_feedback_preserves_original(tmp_path):
    path, root, store, service, grant, facade, original = _setup(tmp_path)
    try:
        before = _artifacts(facade)
        issue, candidate, comparison = _candidate(service, grant, facade)
        assert comparison["status"] == "current" and comparison["blocked_reasons"] == []
        assert _artifacts(facade) == before
        snapshot = _adopt(facade, candidate, comparison)["snapshot"]
        assert snapshot["source_ref"] == original["source_ref"]
        batch = snapshot["batch"]
        assert batch["screenshots"][:-1] == original["batch"]["screenshots"]
        assert batch["interfaces"][:-1] == original["batch"]["interfaces"]
        shot = batch["screenshots"][-1]
        assert shot["sha256"] != original["batch"]["screenshots"][0]["sha256"]
        image_path = root / source_image_relative_path(snapshot["source_ref"], shot)
        assert hashlib.sha256(image_path.read_bytes()).hexdigest() == shot["sha256"]
        assert all(_artifacts(facade)[name] == digest for name, digest in before.items() if not name.endswith("current.json"))
        workflow = json.loads(Path(snapshot["workflow_review_path"]).read_text(encoding="utf-8"))
        assert workflow["workflow"]["review_status"] == "needs_human_review"
        assert facade.list_reviewed_assets() == []
        edited = deepcopy(batch)
        edited["interfaces"][-1]["meaning"] = "人工核对后的详情界面"
        edited["interfaces"][-1]["regions"][0]["bbox"] = [21., 101., 98., 38.]
        saved = facade.save_revision("task-flow", "flow-batch", 2, edited)
        facade.close(); store.close()
        store, service, facade = _reopen(path, root)
        assert facade.load_batch("task-flow", "flow-batch") == saved
        view = facade.request_relearn("task-flow", "flow-batch", 3, 1,
            {"interface_ids": ["i-new"], "relationship_ids": []}, "再核对新界面", "next-interface")
        new_issue = view["issues"][-1]
        assert new_issue["review_baseline"]["batch"]["screenshots"][-1]["png_base64"] == shot["png_base64"]
        follow = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "idempotency_key": "next-interface-candidate",
            "batch_id": "flow-batch", "issue_id": new_issue["issue_id"], "baseline_revision": 2,
            "review_baseline_sha256": new_issue["review_baseline_sha256"], "scope": new_issue["scope"],
            "changes": [{"change_type": "geometry", "region_id": "r-new", "bbox": [22., 101., 98., 38.]}]})
        assert facade.compare_relearn_candidate("task-flow", "flow-batch", 3, follow["candidate_id"])["status"] == "current"
        detail = service.reviewer_call(REVIEWER_TOKEN, "get_batch", {"task_id": "task-flow", "batch_id": "flow-batch"})
        assert len(detail["batch"]["screenshots"]) == 1 and len(detail["batch"]["interfaces"]) == 3
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("mutation", ["add", "drop", "reorder", "replace", "rebind"])
def test_ordinary_save_cannot_modify_new_evidence_identity(tmp_path, mutation):
    _, _, store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        snapshot = _adopt(facade, candidate, comparison)["snapshot"]
        edited = deepcopy(snapshot["batch"])
        if mutation == "add":
            edited["interfaces"].append({"interface_id": "ordinary", "screenshot_id": "shot-new", "meaning": "普通新增", "regions": []})
        elif mutation == "drop":
            edited["screenshots"].pop(0)
            for interface in edited["interfaces"][:-1]:
                interface["screenshot_id"] = "shot-new"
        elif mutation == "reorder":
            edited["screenshots"].reverse(); edited["interfaces"].reverse()
        elif mutation == "replace":
            edited["screenshots"][-1] = deepcopy(edited["screenshots"][0]) | {"screenshot_id": "shot-new"}
            edited["interfaces"][-1]["regions"][0]["bbox"] = [1., 1., 20., 10.]
        else:
            edited["interfaces"][0]["screenshot_id"] = "shot-new"
        before = _artifacts(facade)
        with pytest.raises(DesktopReviewError):
            facade.save_revision("task-flow", "flow-batch", 2, edited)
        assert _artifacts(facade) == before and facade.load_batch("task-flow", "flow-batch") == snapshot
    finally:
        facade.close(); store.close()


def test_new_evidence_origin_is_checked_before_any_materialization(tmp_path, monkeypatch):
    _, _, store, service, grant, facade, original = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        before = _artifacts(facade)
        real_save = facade._save_revision_locked
        def invalid_origin(*args, **kwargs):
            kwargs["relearn_adoption"]["candidate_sha256"] = "0" * 64
            return real_save(*args, **kwargs)
        monkeypatch.setattr(facade, "_save_revision_locked", invalid_origin)
        with pytest.raises(DesktopReviewError):
            _adopt(facade, candidate, comparison)
        assert _artifacts(facade) == before and facade.load_batch("task-flow", "flow-batch") == original
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("mutation", ["missing", "corrupt", "missing_origin"])
def test_reopen_requires_supplemental_png_and_verified_origin(tmp_path, mutation):
    path, root, store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        snapshot = _adopt(facade, candidate, comparison)["snapshot"]
        shot = snapshot["batch"]["screenshots"][-1]
        image_path = root / source_image_relative_path(snapshot["source_ref"], shot)
        if mutation == "missing_origin":
            current_path = facade._workspace_dir("task-flow", "flow-batch") / "current.json"
            manifest = json.loads(current_path.read_text(encoding="utf-8"))
            child_path = root / manifest["workspace_path"]
            child = json.loads(child_path.read_text(encoding="utf-8"))
            child["relearn_adoption"] = None
            raw = (json.dumps(child, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            child_path.write_bytes(raw)
            manifest["workspace_sha256"] = hashlib.sha256(raw).hexdigest()
            current_path.write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")
        elif mutation == "missing":
            image_path.rename(image_path.with_suffix(".fixture-missing"))
        else:
            image_path.write_bytes(b"invalid synthetic PNG")
        facade.close(); store.close()
        store, service, facade = _reopen(path, root)
        with pytest.raises(DesktopReviewError):
            facade.load_batch("task-flow", "flow-batch")
    finally:
        facade.close(); store.close()


def test_new_interface_collision_is_not_silently_adopted(tmp_path):
    _, _, store, service, grant, facade, _ = _setup(tmp_path)
    try:
        issue, first, comparison = _candidate(service, grant, facade)
        second = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "idempotency_key": "colliding-interface",
            "batch_id": "flow-batch", "issue_id": issue["issue_id"], "baseline_revision": 1,
            "review_baseline_sha256": issue["review_baseline_sha256"], "scope": issue["scope"],
            "changes": [new_interface_changes()[1]]})
        saved = _adopt(facade, first, comparison)["snapshot"]
        collision = facade.compare_relearn_candidate("task-flow", "flow-batch", 2, second["candidate_id"])
        assert collision["status"] == "stale"
        for kind, identity in (("screenshot", "shot-new"), ("interface", "i-new")):
            diff = next(d for d in collision["diffs"] if d["target_type"] == kind)
            assert diff["baseline"] is None and diff["current"] is not None
            assert f"reference_drift:{kind}:{identity}:entity" in collision["blocked_reasons"]
        with pytest.raises(DesktopReviewError):
            facade.adopt_relearn_candidate("task-flow", "flow-batch", 2, second["candidate_id"], collision["candidate_sha256"], collision["review_baseline_sha256"], "collision-adopt")
        assert facade.load_batch("task-flow", "flow-batch") == saved
    finally:
        facade.close(); store.close()
