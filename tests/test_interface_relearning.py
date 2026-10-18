from __future__ import annotations

from copy import deepcopy
import pytest

from app.desktop_review.interface_relearning import InterfaceRelearningService
from app.desktop_review.workspace import DesktopReviewError
from tests.test_formal_graph_exact_review import BATCH, TASK, _runtime


def _opened(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    snap = facade.import_interface_content(TASK, BATCH, "state-a")
    return store, facade, snap


def test_feedback_candidate_compare_and_adopt_without_review(tmp_path):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        issue = service.request(snap["interface_id"], snap["revision"], snap["content_sha256"], [snap["content"]["regions"][0]["region_id"]], "文字识别错误", "issue-1")
        candidate = service.submit_candidate(TASK, issue["issue_id"], snap["content_sha256"], {"meaning": "候选修正"}, "candidate-1")
        assert service.compare(issue["issue_id"], candidate["candidate_id"])["candidate"]["content"]["meaning"] == "候选修正"
        adopted = service.adopt(issue["issue_id"], candidate["candidate_id"], snap["revision"], snap["content_sha256"], "adopt-1")
        assert adopted["status"] == "adopted"
        assert service.adopt(issue["issue_id"], candidate["candidate_id"], snap["revision"], snap["content_sha256"], "adopt-1")["status"] == "adopted"
        with pytest.raises(DesktopReviewError, match="idempotency_conflict"):
            service.adopt(issue["issue_id"], candidate["candidate_id"], 99, snap["content_sha256"], "adopt-1")
        assert facade.load_interface_content(snap["interface_id"])["content"]["meaning"] == "候选修正"
    finally:
        facade.close(); store.close()


def test_cross_task_and_stale_baseline_are_rejected(tmp_path):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        issue = service.request(snap["interface_id"], 1, snap["content_sha256"], [snap["content"]["regions"][0]["region_id"]], "问题", "issue-2")
        with pytest.raises(DesktopReviewError, match="task_mismatch"):
            service.submit_candidate("other-task", issue["issue_id"], snap["content_sha256"], {"meaning": "x"}, "candidate-2")
        candidate = service.submit_candidate(TASK, issue["issue_id"], snap["content_sha256"], {"meaning": "候选"}, "candidate-2")
        facade.save_interface_content(snap["interface_id"], 1, snap["content_sha256"], {"meaning": "人工先改"}, "human-change")
        with pytest.raises(DesktopReviewError, match="stale"):
            service.adopt(issue["issue_id"], candidate["candidate_id"], 1, snap["content_sha256"], "adopt-2")
    finally:
        facade.close(); store.close()


def test_candidate_is_idempotent_and_does_not_write_content(tmp_path):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        rid = snap["content"]["regions"][0]["region_id"]
        issue = service.request(snap["interface_id"], 1, snap["content_sha256"], [rid], "问题", "issue-3")
        changes = {"regions": [{"region_id": rid, "bbox": [4, 5, 20, 12]}]}
        first = service.submit_candidate(TASK, issue["issue_id"], snap["content_sha256"], changes, "candidate-3")
        second = service.submit_candidate(TASK, issue["issue_id"], snap["content_sha256"], changes, "candidate-3")
        assert first == second
        assert facade.load_interface_content(snap["interface_id"])["revision"] == 1
    finally:
        facade.close(); store.close()


def test_adopt_retry_after_decision_write_failure_does_not_create_second_revision(tmp_path, monkeypatch):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        rid = snap["content"]["regions"][0]["region_id"]
        issue = service.request(snap["interface_id"], 1, snap["content_sha256"], [rid], "问题", "issue-retry")
        candidate = service.submit_candidate(TASK, issue["issue_id"], snap["content_sha256"], {"meaning": "候选"}, "candidate-retry")
        import app.desktop_review.interface_relearning as module
        original = module._write_immutable
        failed = False
        def fail_decision_once(path, payload):
            nonlocal failed
            if path.parent.name == "decisions" and not failed:
                failed = True
                raise OSError("synthetic decision failure")
            return original(path, payload)
        monkeypatch.setattr(module, "_write_immutable", fail_decision_once)
        with pytest.raises(DesktopReviewError, match="persistence_failed"):
            service.adopt(issue["issue_id"], candidate["candidate_id"], 1, snap["content_sha256"], "adopt-retry")
        monkeypatch.setattr(module, "_write_immutable", original)
        retried = service.adopt(issue["issue_id"], candidate["candidate_id"], 1, snap["content_sha256"], "adopt-retry")
        assert retried["status"] == "adopted"
        assert facade.load_interface_content(snap["interface_id"])["revision"] == 2
    finally:
        facade.close(); store.close()
