"""首次写入中断与已有人工后续版本下的重试不能丢记录或回退内容。"""
import json
from copy import deepcopy

import pytest

from app.desktop_review.interface_relearning import InterfaceRelearningService
from app.desktop_review.workspace import DesktopReviewError
from tests.test_interface_relearning_integrity import _opened, _issue, _candidate
from tests.test_formal_graph_exact_review import TASK


@pytest.fixture
def opened(tmp_path):
    store, facade, snap = _opened(tmp_path)
    yield InterfaceRelearningService(facade), facade, snap
    facade.close(); store.close()


def test_request_state_interrupted_then_exact_retry_and_conflicting_key(opened, monkeypatch):
    service, _, snap = opened
    original = service._write_state
    monkeypatch.setattr(service, "_write_state", lambda *_: (_ for _ in ()).throw(OSError("synthetic")))
    with pytest.raises(DesktopReviewError, match="persistence_failed"):
        _issue(service, snap, "first-state")
    monkeypatch.setattr(service, "_write_state", original)
    issue = _issue(service, snap, "first-state")
    assert len(service.list(TASK)) == 1
    with pytest.raises(DesktopReviewError, match="idempotency_conflict"):
        service.request(snap["interface_id"], snap["revision"], snap["content_sha256"], [], "不同问题", "first-state")
    assert service.read(issue["issue_id"])["status"] == "open"


def test_adopt_retry_finalizes_saved_version_without_overwriting_later_human_edit(opened, monkeypatch):
    service, facade, snap = opened
    issue = _issue(service, snap)
    candidate = _candidate(service, snap, issue)
    import app.desktop_review.interface_relearning as module
    original = module._write_immutable
    def fail_decision(path, payload):
        if path.parent.name == "decisions": raise OSError("synthetic")
        return original(path, payload)
    monkeypatch.setattr(module, "_write_immutable", fail_decision)
    with pytest.raises(DesktopReviewError, match="persistence_failed"):
        service.adopt(issue["issue_id"], candidate["candidate_id"], 1, snap["content_sha256"], "later-human-adopt")
    saved = facade.load_interface_content(snap["interface_id"])
    latest = facade.save_interface_content(snap["interface_id"], saved["revision"], saved["content_sha256"],
        {"meaning": "之后的人工版本"}, "human-after-adopt")
    monkeypatch.setattr(module, "_write_immutable", original)
    with pytest.raises(DesktopReviewError, match="idempotency_conflict"):
        service.adopt(issue["issue_id"], candidate["candidate_id"], latest["revision"], latest["content_sha256"], "later-human-adopt")
    service.adopt(issue["issue_id"], candidate["candidate_id"], 1, snap["content_sha256"], "later-human-adopt")
    assert service.read(issue["issue_id"])["status"] == "adopted"
    assert facade.load_interface_content(snap["interface_id"])["content_sha256"] == latest["content_sha256"]


def test_missing_post_candidate_state_does_not_reopen_issue(opened):
    service, _, snap = opened
    issue = _issue(service, snap)
    _candidate(service, snap, issue)
    service._state_path(issue["issue_id"]).unlink()
    with pytest.raises(DesktopReviewError, match="state_invalid"):
        service.read(issue["issue_id"])


@pytest.mark.parametrize("method", ["reject", "withdraw"])
def test_terminal_feedback_decision_retry_and_tamper(opened, method):
    service, _, snap = opened
    issue = _issue(service, snap)
    close = getattr(service, method)
    first = close(issue["issue_id"], "保留说明", "close-key")
    assert close(issue["issue_id"], "保留说明", "close-key") == first
    with pytest.raises(DesktopReviewError, match="idempotency_conflict"):
        close(issue["issue_id"], "不同说明", "close-key")
    path = service._decision_path(issue["issue_id"], "close-key")
    value = json.loads(path.read_text(encoding="utf-8")); value["decision"] = "adopted"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DesktopReviewError, match="decision_invalid"):
        close(issue["issue_id"], "保留说明", "close-key")


def test_candidate_region_replacement_is_explicit_and_keeps_unchanged_ids(opened):
    service, _, snap = opened
    issue = _issue(service, snap)
    regions = [{"region_id": r["region_id"]} for r in snap["content"]["regions"]]
    regions[0]["meaning"] = "只改变一框的含义"
    candidate = service.submit_candidate(TASK, issue["issue_id"], snap["content_sha256"], {"regions": regions}, "regions-complete")
    assert len(candidate["content"]["regions"]) == len(snap["content"]["regions"])
    assert candidate["content"]["regions"][0]["meaning"] == "只改变一框的含义"
    assert candidate["content"]["regions"][1:] == snap["content"]["regions"][1:]
