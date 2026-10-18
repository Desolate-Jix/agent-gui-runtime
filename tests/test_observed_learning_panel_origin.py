from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.desktop_review.content_library import InterfaceContentLibrary
from app.desktop_review.observed_interface_learning import submit_observed_interface_learning
from app.desktop_review.workspace import DesktopReviewError
from app.agent_link.contracts import AgentLinkError
from app.desktop_review.external_mapping import canonical_json_bytes
import hashlib
from tests.test_formal_fresh_graph_source import _stage

_APP = QApplication.instance() or QApplication([])


def _complete(host, connection, segment, args, result, *, key="origin-complete", meaning="Agent 首次完成", expected=None):
    current = expected or host.facade.import_interface_content(args["task_id"], result["batch_id"], "observed-screen")
    return submit_observed_interface_learning(
        host.facade, connection_id=connection["connection_id"], task_id=args["task_id"],
        segment_id=segment["segment_id"], batch_id=result["batch_id"],
        expected_revision=current["revision"], expected_sha256=current["content_sha256"],
        meaning=meaning, recognition_text="原始 OCR", regions=[{
            "bbox": [2, 3, 20, 12], "name": "按钮", "kind": "button", "meaning": "控件",
        }], idempotency_key=key,
    )


def test_observed_completion_is_new_then_human_revision_is_modified(tmp_path: Path):
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    try:
        completed = _complete(host, connection, segment, args, result)
        assert completed["revision"] == 2 and completed["origin_status"] == "new"
        assert host.facade.list_interface_contents() == [completed]
        edited = host.facade.save_interface_content(
            completed["interface_id"], completed["revision"], completed["content_sha256"],
            {"meaning": "人工修改"}, "origin-human-edit",
        )
        assert edited["revision"] == 3 and edited["origin_status"] == "modified"
        assert host.facade.list_interface_contents() == [edited]
    finally:
        host.close()


def test_plain_human_revision_two_is_not_new(tmp_path: Path):
    host, _connection, _segment, _packet, args, _result = _stage(tmp_path)
    try:
        first = host.facade.import_interface_content(args["task_id"], _result["batch_id"], "observed-screen")
        human = host.facade.save_interface_content(
            first["interface_id"], first["revision"], first["content_sha256"],
            {"meaning": "人工首改"}, "plain-human-v2",
        )
        assert human["revision"] == 2 and human["origin_status"] == "modified"
    finally:
        host.close()


def test_completion_retry_finishes_marker_after_marker_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    try:
        original_v1 = host.facade.import_interface_content(args["task_id"], result["batch_id"], "observed-screen")
        import app.desktop_review.interface_content as module
        original = module._write_immutable
        failed = False
        def fail_marker_once(path, payload):
            nonlocal failed
            if path.name == "origin.json" and not failed:
                failed = True
                raise OSError("synthetic origin marker failure")
            return original(path, payload)
        monkeypatch.setattr(module, "_write_immutable", fail_marker_once)
        with pytest.raises(AgentLinkError) as error:
            _complete(host, connection, segment, args, result, key="origin-retry", expected=original_v1)
        assert error.value.code == "persistence_failed"
        failed = False
        with pytest.raises(AgentLinkError) as retry_error:
            _complete(host, connection, segment, args, result, key="origin-retry", expected=original_v1)
        assert retry_error.value.code == "persistence_failed"
        monkeypatch.setattr(module, "_write_immutable", original)
        retried = _complete(host, connection, segment, args, result, key="origin-retry", expected=original_v1)
        assert retried["revision"] == 2 and retried["origin_status"] == "new"
        assert (host.facade._workspace_root / "interface-contents" / retried["interface_id"] / "origin.json").exists()
    finally:
        host.close()


def test_origin_marker_rejects_self_consistent_wrong_completion_revision(tmp_path: Path):
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    try:
        completed = _complete(host, connection, segment, args, result)
        path = host.facade._workspace_root / "interface-contents" / completed["interface_id"] / "origin.json"
        marker = json.loads(path.read_text(encoding="utf-8"))
        marker["completion_revision"] = 3
        marker.pop("marker_sha256")
        marker["marker_sha256"] = hashlib.sha256(canonical_json_bytes(marker)).hexdigest()
        path.write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(DesktopReviewError, match="origin_marker_invalid"):
            host.facade.load_interface_content(completed["interface_id"])
    finally:
        host.close()


def test_damaged_origin_marker_surfaces_instead_of_falling_back(tmp_path: Path):
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    try:
        completed = _complete(host, connection, segment, args, result)
        marker_path = host.facade._workspace_root / "interface-contents" / completed["interface_id"] / "origin.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["completion_content_sha256"] = "0" * 64
        marker_path.write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(DesktopReviewError, match="origin_marker_invalid"):
            host.facade.load_interface_content(completed["interface_id"])
    finally:
        host.close()


def test_library_new_filter_uses_verified_origin_then_human_edit_is_modified(tmp_path: Path):
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    library = None
    try:
        completed = _complete(host, connection, segment, args, result, key="qt-origin")
        library = InterfaceContentLibrary(host.facade)
        library.filter.setCurrentIndex(1)
        library.refresh()
        assert library.items.count() == 1
        assert "新学内容" in library.pane.status.text()
        assert "有修改" not in library.pane.status.text()
        edited = host.facade.save_interface_content(
            completed["interface_id"], completed["revision"], completed["content_sha256"],
            {"meaning": "人工修订"}, "qt-human-edit",
        )
        library.filter.setCurrentIndex(1)
        library.refresh()
        assert library.items.count() == 0
        library.filter.setCurrentIndex(2)
        library.refresh()
        assert library.items.count() == 1
        assert "有修改" in library.pane.status.text()
        assert host.facade.load_interface_content(completed["interface_id"], completed["version_id"])["content_sha256"] == completed["content_sha256"]
        assert edited["origin_status"] == "modified"
    finally:
        if library is not None:
            library.close()
        host.close()
