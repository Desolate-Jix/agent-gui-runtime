from __future__ import annotations

from pathlib import Path

import pytest

from app.desktop_review.interface_relearning import InterfaceRelearningService
from app.desktop_review.workspace import DesktopReviewError
from tests.test_formal_graph_exact_review import BATCH, TASK, _runtime


def _opened(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    snap = facade.import_interface_content(TASK, BATCH, "state-a")
    return store, facade, snap


def _issue(service, snap, key="issue-integrity"):
    return service.request(snap["interface_id"], snap["revision"], snap["content_sha256"],
                           [snap["content"]["regions"][0]["region_id"]], "识别问题", key)


def _candidate(service, snap, issue, key="candidate-integrity"):
    return service.submit_candidate(TASK, issue["issue_id"], snap["content_sha256"],
                                    {"meaning": "候选修正"}, key)


@pytest.mark.parametrize("kwargs", [
    {"expected_revision": "1"}, {"expected_sha256": []}, {"region_ids": "r"},
    {"message": []}, {"idempotency_key": []},
])
def test_request_rejects_bad_types_without_raw_typeerror(tmp_path, kwargs):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        args = {"interface_id": snap["interface_id"], "expected_revision": 1,
                "expected_sha256": snap["content_sha256"],
                "region_ids": [snap["content"]["regions"][0]["region_id"]],
                "message": "问题", "idempotency_key": "typed-key"}
        args.update(kwargs)
        with pytest.raises(DesktopReviewError):
            service.request(**args)
    finally:
        facade.close(); store.close()


def test_corrupt_issue_state_and_candidate_hashes_fail_closed(tmp_path):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        issue = _issue(service, snap)
        issue_path = service._issue_path(issue["issue_id"])
        issue_path.write_text(issue_path.read_text(encoding="utf-8").replace('"issue_sha256":"', '"issue_sha256":"0'), encoding="utf-8")
        with pytest.raises(DesktopReviewError, match="issue_invalid"):
            service.read(issue["issue_id"])
    finally:
        facade.close(); store.close()

    store, facade, snap = _opened(tmp_path / "state")
    try:
        service = InterfaceRelearningService(facade)
        issue = _issue(service, snap, "issue-state")
        state_path = service._state_path(issue["issue_id"])
        state_path.write_text(state_path.read_text(encoding="utf-8").replace('"state_sha256":"', '"state_sha256":"0'), encoding="utf-8")
        with pytest.raises(DesktopReviewError, match="state_invalid"):
            service.read(issue["issue_id"])
    finally:
        facade.close(); store.close()


def test_candidate_corruption_bbox_and_cross_task_fail_closed(tmp_path):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        issue = _issue(service, snap)
        rid = snap["content"]["regions"][0]["region_id"]
        with pytest.raises(DesktopReviewError):
            service.submit_candidate(TASK, issue["issue_id"], snap["content_sha256"],
                                     {"regions": [{"region_id": rid, "bbox": [1, 2]}]}, "bad-bbox")
        with pytest.raises(DesktopReviewError, match="task_mismatch"):
            service.submit_candidate("foreign-task", issue["issue_id"], snap["content_sha256"], {"meaning": "x"}, "foreign")
        candidate = _candidate(service, snap, issue)
        path = service._candidate_path(candidate["candidate_id"])
        path.write_text(path.read_text(encoding="utf-8").replace('"candidate_record_sha256":"', '"candidate_record_sha256":"0'), encoding="utf-8")
        with pytest.raises(DesktopReviewError, match="candidate_invalid"):
            service.compare(issue["issue_id"], candidate["candidate_id"])
    finally:
        facade.close(); store.close()


def test_exact_request_retry_survives_current_change_but_wrong_key_is_stale(tmp_path):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        args = (snap["interface_id"], 1, snap["content_sha256"], [snap["content"]["regions"][0]["region_id"]], "问题", "retry")
        first = service.request(*args)
        facade.save_interface_content(snap["interface_id"], 1, snap["content_sha256"], {"meaning": "人工先改"}, "human")
        assert service.request(*args)["issue_id"] == first["issue_id"]
        with pytest.raises(DesktopReviewError, match="stale"):
            service.request(snap["interface_id"], 1, snap["content_sha256"], args[3], "问题", "retry-new")
    finally:
        facade.close(); store.close()


def test_request_registry_failure_retry_is_single_issue(tmp_path, monkeypatch):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        original = service._write_registry
        failed = True
        def fail_once(value):
            nonlocal failed
            if failed:
                failed = False
                raise OSError("synthetic")
            return original(value)
        monkeypatch.setattr(service, "_write_registry", fail_once)
        with pytest.raises(DesktopReviewError, match="persistence_failed"):
            _issue(service, snap, "registry-retry")
        retried = _issue(service, snap, "registry-retry")
        assert len(service.list(TASK)) == 1 and retried["issue_id"] == service.list(TASK)[0]["issue_id"]
    finally:
        facade.close(); store.close()


def test_candidate_state_failure_does_not_duplicate_or_lose_candidate(tmp_path, monkeypatch):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        issue = _issue(service, snap, "candidate-state")
        original = service._write_state
        failed = True
        def fail_once(issue_id, value):
            nonlocal failed
            if failed and value.get("candidate_ids"):
                failed = False
                raise OSError("synthetic")
            return original(issue_id, value)
        monkeypatch.setattr(service, "_write_state", fail_once)
        with pytest.raises(DesktopReviewError, match="persistence_failed"):
            _candidate(service, snap, issue, "candidate-state")
        monkeypatch.setattr(service, "_write_state", original)
        recovered = _candidate(service, snap, issue, "candidate-state")
        assert recovered["candidate_id"] == service.list(TASK)[0]["candidate_ids"][0]
    finally:
        facade.close(); store.close()


def test_adoption_state_failure_retries_one_interface_version(tmp_path, monkeypatch):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        issue = _issue(service, snap, "adopt-state")
        candidate = _candidate(service, snap, issue, "adopt-candidate")
        original = service._write_state
        calls = 0
        def fail_final(issue_id, value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic")
            return original(issue_id, value)
        monkeypatch.setattr(service, "_write_state", fail_final)
        with pytest.raises(DesktopReviewError, match="persistence_failed"):
            service.adopt(issue["issue_id"], candidate["candidate_id"], 1, snap["content_sha256"], "adopt-state")
        monkeypatch.setattr(service, "_write_state", original)
        retried = service.adopt(issue["issue_id"], candidate["candidate_id"], 1, snap["content_sha256"], "adopt-state")
        assert retried["status"] == "adopted"
        assert facade.load_interface_content(snap["interface_id"])["revision"] == 2
    finally:
        facade.close(); store.close()


def test_same_value_manual_edit_cannot_impersonate_adoption(tmp_path):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        issue = _issue(service, snap, "same-value-issue")
        candidate = _candidate(service, snap, issue, "same-value-candidate")
        facade.save_interface_content(snap["interface_id"], 1, snap["content_sha256"], {"meaning": "候选修正"}, "manual-same-value")
        with pytest.raises(DesktopReviewError, match="stale"):
            service.adopt(issue["issue_id"], candidate["candidate_id"], 1, snap["content_sha256"], "same-value-adopt")
    finally:
        facade.close(); store.close()


def test_adoption_terminal_retry_with_wrong_key_is_rejected(tmp_path):
    store, facade, snap = _opened(tmp_path)
    try:
        service = InterfaceRelearningService(facade)
        issue = _issue(service, snap, "terminal-issue")
        candidate = _candidate(service, snap, issue, "terminal-candidate")
        service.adopt(issue["issue_id"], candidate["candidate_id"], 1, snap["content_sha256"], "terminal-adopt")
        with pytest.raises(DesktopReviewError):
            service.adopt(issue["issue_id"], candidate["candidate_id"], 1, snap["content_sha256"], "different-key")
    finally:
        facade.close(); store.close()
