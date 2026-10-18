from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review import exact_review, external_mapping
from app.desktop_review.workspace import NativeReviewFacade
from test_formal_graph_semantics import _raw_batch


def _legacy_key(snapshot: dict, options: dict) -> str:
    # 固定升级前的身份公式，避免测试随新公式一起改变。
    return hashlib.sha256(external_mapping.canonical_json_bytes({
        "task_id": snapshot["task_id"], "batch_id": snapshot["batch_id"],
        "source": snapshot["source_ref"], "revision": snapshot["revision"],
        "options": options,
    })).hexdigest()


def _tree_bytes(root: Path) -> dict:
    # 排除 Windows 独占锁；仅比较持久审核内容和证据。
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file() and path.name != ".owner.lock"}


@pytest.fixture
def workspace(tmp_path):
    token = "formal-upgrade-reviewer-token"
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, token)
    facade = NativeReviewFacade(service, token, tmp_path / "artifacts")
    grant = service.reviewer_call(token, "create_connection", {
        "task_id": "upgrade-task", "agent_name": "upgrade-contract-client",
    })
    service.agent_call(grant["token"], "submit_batch", _raw_batch())
    loaded = facade.load_batch("upgrade-task", "fresh-graph-projection")
    facade.save_revision("upgrade-task", "fresh-graph-projection", 0, loaded["batch"])
    try:
        yield facade, tmp_path / "artifacts"
    finally:
        facade.close()
        store.close()


def _prepare(service, mapping):
    return service.prepare(
        "upgrade-task", "fresh-graph-projection", 1,
        {"kind": "native", "display_name": "Notepad",
         "executable_identity": "notepad.exe", "product_name": "Notepad"},
        step_relationships=mapping,
    )


def _old_preparation(facade, monkeypatch, mapping):
    current_builder = external_mapping.build_external_workflow_review

    def old_builder(**kwargs):
        # 升级前接受绑定选项，但投影尚未将它写入审核边。
        kwargs.pop("step_relationships", None)
        return current_builder(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(exact_review, "_preparation_key", _legacy_key)
        patch.setattr(external_mapping, "build_external_workflow_review", old_builder)
        service = exact_review.ExactReviewService(facade)
        prepared = _prepare(service, mapping)
        return service.record(prepared["review_ref"], 0,
                              [item["subject_id"] for item in prepared["subjects"]])


def test_bound_legacy_preparation_gets_distinct_unconfirmed_upgrade(workspace, monkeypatch):
    facade, root = workspace
    mapping = {"open-step": ["first"]}
    old = _old_preparation(facade, monkeypatch, mapping)
    before = _tree_bytes(root)
    assert all(item["confirmed"] for item in old["subjects"])
    service = exact_review.ExactReviewService(facade)
    upgraded = _prepare(service, mapping)
    assert upgraded["review_ref"] != old["review_ref"]
    assert upgraded["approval_revision"] == 0
    assert not any(item["confirmed"] for item in upgraded["subjects"])
    assert any(item["kind"] == "edge" and item["content"].get("external_relationships")
               for item in upgraded["subjects"])
    assert _prepare(exact_review.ExactReviewService(facade), mapping) == upgraded
    assert all((root / path).read_bytes() == data for path, data in before.items())


def test_old_bound_review_ref_has_actionable_upgrade_error_without_writes(workspace, monkeypatch):
    facade, root = workspace
    old = _old_preparation(facade, monkeypatch, {"open-step": ["first"]})
    before = _tree_bytes(root)
    service = exact_review.ExactReviewService(facade)
    for action in (
        lambda: service.record(old["review_ref"], old["approval_revision"], []),
        lambda: service.compile(old["review_ref"], old["approval_revision"]),
    ):
        with pytest.raises(exact_review.ExactReviewError, match="projection upgrade required"):
            action()
    assert _tree_bytes(root) == before


@pytest.mark.parametrize("mapping", [None, {"open-step": []}])
def test_no_projected_relationships_keep_legacy_identity_and_approval(workspace, monkeypatch, mapping):
    facade, root = workspace
    old = _old_preparation(facade, monkeypatch, mapping)
    before = _tree_bytes(root)
    assert _prepare(exact_review.ExactReviewService(facade), mapping) == old
    assert _tree_bytes(root) == before
