from __future__ import annotations

from copy import deepcopy
import json

import pytest

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review import interface_content
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
from test_formal_graph_exact_review import BATCH, BINDING, TASK, TOKEN, _runtime


def test_imports_a_single_interface_without_creating_a_graph(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        snapshot = facade.import_interface_content(TASK, BATCH, "state-a")
        assert snapshot["interface_id"].startswith("interface-")
        assert snapshot["review_status"] == "draft"
        assert set(snapshot["source"]) == {
            "task_id", "batch_id", "source_ref", "external_interface_id",
            "screenshot_id", "screenshot_sha256",
        }
        assert snapshot["source"]["external_interface_id"] == "state-a"
        assert snapshot["content"]["meaning"]
        assert not (tmp_path / "fresh-artifacts" / "desktop-review" / "graph-revisions").exists()
    finally:
        facade.close()
        store.close()


def test_import_is_stable_and_reopens_without_graph_or_title_deduplication(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    root = tmp_path / "fresh-artifacts"
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        assert facade.import_interface_content(TASK, BATCH, "state-a") == first
        assert facade.import_interface_content(TASK, BATCH, "state-b")["interface_id"] != first["interface_id"]
        assert not (root / "desktop-review" / "graph-revisions").exists()
    finally:
        facade.close()
        store.close()
    reopened_store = AgentLinkStore(tmp_path / "fresh-inbox.json")
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, TOKEN), TOKEN, root)
    try:
        assert reopened.load_interface_content(first["interface_id"]) == first
    finally:
        reopened.close()
        reopened_store.close()


def test_atomic_save_rejects_bad_bbox_stale_and_conflicting_idempotency(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        region = first["content"]["regions"][0]
        changes = {
            "meaning": "Synthetic independent screen",
            "recognition_text": "Visible synthetic text",
            "regions": [{"region_id": region["region_id"], "bbox": [4, 5, 20, 12]}],
        }
        second = facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], changes, "s55-save")
        assert second["revision"] == 2 and second["review_status"] == "draft"
        assert facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], changes, "s55-save") == second
        with pytest.raises(DesktopReviewError, match="idempotency_conflict"):
            facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"meaning": "different"}, "s55-save")
        with pytest.raises(DesktopReviewError, match="stale_revision"):
            facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"meaning": "stale"}, "s55-stale")
        before = facade.load_interface_content(first["interface_id"])
        with pytest.raises(DesktopReviewError, match="bbox_invalid"):
            facade.save_interface_content(second["interface_id"], second["revision"], second["content_sha256"], {"regions": [{"region_id": region["region_id"], "bbox": [99, 5, 20, 12]}]}, "s55-bad-box")
        assert facade.load_interface_content(first["interface_id"]) == before
        with pytest.raises(DesktopReviewError, match="identity_changed"):
            facade.save_interface_content(second["interface_id"], second["revision"], second["content_sha256"], {"regions": [{"region_id": "changed", "bbox": [4, 5, 20, 12]}]}, "s55-bad-id")
    finally:
        facade.close()
        store.close()


def test_explicit_v1_remains_readable_while_default_memory_uses_saved_v2_without_leaking_paths(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        v1 = facade.import_interface_content(TASK, BATCH, "state-a")
        reviewed = facade.review_interface_content(v1["interface_id"], v1["revision"], v1["content_sha256"], deepcopy(BINDING))
        assert reviewed["review_status"] == "reviewed" and reviewed["application_binding"]["kind"] == "native"
        v2 = facade.save_interface_content(v1["interface_id"], v1["revision"], v1["content_sha256"], {"meaning": "V2 draft"}, "s55-v2")
        assert v2["review_status"] == "draft"
        exact_v1 = facade.load_interface_content(v1["interface_id"], v1["version_id"])
        assert exact_v1["review_status"] == "reviewed" and exact_v1["content"]["meaning"] != v2["content"]["meaning"]
        assert facade.list_interface_contents(reviewed_only=True) == [exact_v1]
        evidence = facade.load_interface_content_evidence(v1["interface_id"], v1["version_id"])
        assert set(evidence) == {"image_path", "sha256", "width", "height"}
        assert (evidence["width"], evidence["height"]) == (101, 67)
        memory = facade.get_interface_memory(TASK, v1["interface_id"], v1["version_id"])
        assert memory["version_id"] == v1["version_id"] and "image_path" not in str(memory) and "png" not in memory
        latest_memory = facade.get_interface_memory(TASK, v2["interface_id"])
        assert latest_memory["version_id"] == v2["version_id"]
        assert facade.search_interface_memory(TASK, "V2") == [latest_memory]
        assert facade.get_interface_memory(TASK, v2["interface_id"], v2["version_id"]) == latest_memory
        with pytest.raises(DesktopReviewError, match="memory_not_found"):
            facade.get_interface_memory("other-task", v1["interface_id"], v1["version_id"])
        (tmp_path / "fresh-artifacts" / evidence["image_path"]).write_bytes(b"tampered")
        with pytest.raises(DesktopReviewError, match="evidence_sha256_mismatch"):
            facade.load_interface_content_evidence(v1["interface_id"], v1["version_id"])
        with pytest.raises(DesktopReviewError, match="evidence_sha256_mismatch"):
            facade.get_interface_memory(TASK, v1["interface_id"], v1["version_id"])
    finally:
        facade.close()
        store.close()


def test_rejects_path_like_identifiers_and_nontext_semantics_without_writing(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        before = facade.load_interface_content(first["interface_id"])
        with pytest.raises(DesktopReviewError, match="id_invalid"):
            facade.load_interface_content("../outside")
        with pytest.raises(DesktopReviewError, match="idempotency_key_invalid"):
            facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"meaning": "x"}, "../escape")
        with pytest.raises(DesktopReviewError, match="meaning must be text"):
            facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"meaning": {"untrusted": "object"}}, "s55-nontext")
        assert facade.load_interface_content(first["interface_id"]) == before
    finally:
        facade.close()
        store.close()


def test_rejects_tampered_immutable_version_and_review_record(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    root = tmp_path / "fresh-artifacts" / "desktop-review" / "interface-contents"
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        reviewed = facade.review_interface_content(first["interface_id"], first["revision"], first["content_sha256"], deepcopy(BINDING))
        review_path = root / first["interface_id"] / "reviews" / f"{first['version_id']}.json"
        review_payload = json.loads(review_path.read_text(encoding="utf-8"))
        original_review = deepcopy(review_payload)
        review_payload["application_binding"]["display_name"] = "Tampered binding"
        review_path.write_text(json.dumps(review_payload), encoding="utf-8")
        with pytest.raises(DesktopReviewError, match="review_invalid"):
            facade.load_interface_content(first["interface_id"], first["version_id"])
        review_path.write_text(json.dumps(original_review), encoding="utf-8")
        version_path = root / first["interface_id"] / "revisions" / f"{first['content_sha256']}.json"
        version_payload = json.loads(version_path.read_text(encoding="utf-8"))
        version_payload["content"]["meaning"] = "Tampered content"
        version_path.write_text(json.dumps(version_payload), encoding="utf-8")
        with pytest.raises(DesktopReviewError, match="version_invalid"):
            facade.get_interface_memory(TASK, first["interface_id"], first["version_id"])
    finally:
        facade.close()
        store.close()


def test_save_write_fault_leaves_only_committed_history_and_retry_commits_once(tmp_path, monkeypatch):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        original_write = interface_content._atomic_write_bytes
        failed = False

        def fail_once(path, payload):
            nonlocal failed
            if path.name == "current.json" and not failed:
                failed = True
                raise OSError("synthetic current manifest failure")
            return original_write(path, payload)

        monkeypatch.setattr(interface_content, "_atomic_write_bytes", fail_once)
        with pytest.raises(OSError, match="synthetic current manifest failure"):
            facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"meaning": "retryable"}, "s55-retry")
        assert facade.load_interface_content(first["interface_id"]) == first
        committed = facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"meaning": "retryable"}, "s55-retry")
        assert committed["revision"] == 2
        assert facade.list_interface_contents() == [committed]
        assert facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"meaning": "retryable"}, "s55-retry") == committed
    finally:
        facade.close()
        store.close()
