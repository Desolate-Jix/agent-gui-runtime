from __future__ import annotations

from copy import deepcopy

import pytest

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
from test_formal_graph_exact_review import BATCH, BINDING, TASK, TOKEN, _runtime


def _user_region(identity: str, bbox: list[float]) -> dict:
    return {
        "region_id": identity,
        "bbox": bbox,
        "name": "Synthetic user region",
        "kind": "control",
        "meaning": "Synthetic editable control",
        "recognition_text": "Synthetic text",
    }


def test_saved_content_is_living_memory_without_review_gate_and_reopens(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    root = tmp_path / "fresh-artifacts"
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        assert first["storage_status"] == "saved"
        assert first["origin_status"] == "new"
        assert facade.get_interface_memory(TASK, first["interface_id"], None)["version_id"] == first["version_id"]
    finally:
        facade.close()
        store.close()
    reopened_store = AgentLinkStore(tmp_path / "fresh-inbox.json")
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, TOKEN), TOKEN, root)
    try:
        assert reopened.get_interface_memory(TASK, first["interface_id"], None)["version_id"] == first["version_id"]
    finally:
        reopened.close()
        reopened_store.close()


def test_full_region_living_edit_add_remove_binding_and_exact_history(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        original = deepcopy(first["content"]["regions"][0])
        original.update({
            "bbox": [5, 6, 20, 12],
            "name": "Renamed source region",
            "kind": "input",
            "meaning": "Updated source meaning",
            "recognition_text": "Updated source text",
        })
        user = _user_region("region-user-12345678-1234-4234-9234-123456789abc", [40, 8, 20, 14])
        second = facade.save_interface_content(
            first["interface_id"], first["revision"], first["content_sha256"],
            {
                "meaning": "Living synthetic screen",
                "recognition_text": "Living screen text",
                "regions": [original, user],
                "application_binding": deepcopy(BINDING),
            }, "living-content-v2",
        )
        assert second["storage_status"] == "saved" and second["origin_status"] == "modified"
        assert second["application_binding"]["kind"] == "native"
        assert len(second["content"]["regions"]) == 2
        third = facade.save_interface_content(
            second["interface_id"], second["revision"], second["content_sha256"],
            {"regions": [user]}, "living-content-v3",
        )
        assert [item["region_id"] for item in third["content"]["regions"]] == [user["region_id"]]
        assert len(facade.load_interface_content(first["interface_id"], second["version_id"])["content"]["regions"]) == 2
        latest = facade.get_interface_memory(TASK, first["interface_id"], None)
        exact = facade.get_interface_memory(TASK, first["interface_id"], second["version_id"])
        assert latest["version_id"] == third["version_id"] and exact["version_id"] == second["version_id"]
        assert facade.search_interface_memory(TASK, "living") == [latest]
    finally:
        facade.close()
        store.close()


def test_living_regions_reject_invalid_bbox_duplicate_or_preserved_field_tamper(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        original = deepcopy(first["content"]["regions"][0])
        before = facade.load_interface_content(first["interface_id"])
        with pytest.raises(DesktopReviewError, match="bbox_invalid"):
            facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"regions": [{**original, "bbox": [0, 0, float("inf"), 3]}]}, "living-bad-box")
        with pytest.raises(DesktopReviewError, match="duplicate"):
            facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"regions": [original, original]}, "living-duplicate")
        with pytest.raises(DesktopReviewError, match="preserved"):
            facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"regions": [{**original, "label": "tamper"}]}, "living-preserved")
        assert facade.load_interface_content(first["interface_id"]) == before
    finally:
        facade.close()
        store.close()


def test_living_save_keeps_stale_and_idempotency_contract(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        changes = {"meaning": "Idempotent living content"}
        second = facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], changes, "living-idempotent")
        assert facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], changes, "living-idempotent") == second
        with pytest.raises(DesktopReviewError, match="idempotency_conflict"):
            facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"meaning": "different"}, "living-idempotent")
        with pytest.raises(DesktopReviewError, match="stale_revision"):
            facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"meaning": "stale"}, "living-stale")
    finally:
        facade.close()
        store.close()
