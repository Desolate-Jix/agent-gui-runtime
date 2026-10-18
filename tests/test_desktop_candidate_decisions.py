"""候选本地拒绝的持久、血缘、幂等和线性化后端测试。"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from app.agent_link import AgentLinkService, AgentLinkStore
from app.agent_link.contracts import canonical_hash
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
from test_desktop_relearn import REVIEWER_TOKEN, _batch, _setup
from test_desktop_relearn_adoption import _adopt, _candidate


_BINDING = {
    "kind": "native", "display_name": "Notepad",
    "executable_identity": "notepad.exe", "product_name": "Notepad",
}


def _reject(
    facade, candidate, comparison, *, workspace_revision=1,
    decision_revision=0, reason="本地明确拒绝", key="reject-key",
):
    return facade.reject_relearn_candidate(
        "task-1", "batch-1", workspace_revision,
        candidate["candidate_id"], comparison["candidate_sha256"],
        comparison["review_baseline_sha256"], decision_revision, reason, key,
    )


def _decision_path(facade):
    return facade._workspace_dir("task-1", "batch-1") / "candidate-decisions.json"


def test_rejection_roundtrip_is_local_and_preserves_workspace_inbox_and_exact_review(tmp_path):
    store, service, grant, facade, saved = _setup(tmp_path)
    try:
        prepared = facade.prepare_exact_review(
            "task-1", "batch-1", 1, copy.deepcopy(_BINDING)
        )
        recorded = facade.record_review_decisions(
            prepared["review_ref"], 0,
            [subject["subject_id"] for subject in prepared["subjects"]],
        )
        exact_paths = list(
            (facade._artifact_root / "desktop-review" / "exact-reviews").glob(
                "*/current.json"
            )
        )
        assert len(exact_paths) == 1
        exact_before = exact_paths[0].read_bytes()
        _, candidate, comparison = _candidate(service, grant, facade)
        inbox_before = service.reviewer_call(
            REVIEWER_TOKEN, "get_batch", {"task_id": "task-1", "batch_id": "batch-1"}
        )
        receipt = _reject(facade, candidate, comparison)
        assert receipt == {
            "contract_version": "desktop_candidate_rejection_receipt_v1",
            "task_id": "task-1", "batch_id": "batch-1",
            "source_ref": saved["source_ref"],
            "candidate_id": candidate["candidate_id"],
            "candidate_sha256": comparison["candidate_sha256"],
            "review_baseline_sha256": comparison["review_baseline_sha256"],
            "workspace_revision": 1, "decision_revision": 1,
            "current_revision": 1, "current_decision_revision": 1,
            "reason": "本地明确拒绝",
            "record_sha256": receipt["record_sha256"], "staging_only": True,
        }
        view = facade.load_relearn_review("task-1", "batch-1", 1)
        assert view["decision_revision"] == 1
        assert len(view["candidate_decisions"]) == 1
        record = view["candidate_decisions"][0]
        for field in (
            "candidate_id", "candidate_sha256", "review_baseline_sha256",
            "workspace_revision", "decision_revision", "reason", "record_sha256",
        ):
            assert record[field] == receipt[field]
        assert "idempotency_key" not in record
        assert "reject-key" not in json.dumps(record, ensure_ascii=False)
        assert comparison["status"] == "current"
        rejected = facade.compare_relearn_candidate(
            "task-1", "batch-1", 1, candidate["candidate_id"]
        )
        assert rejected["status"] == "blocked"
        assert rejected["blocked_reasons"] == ["locally_rejected"]
        assert next(
            item for item in view["candidates"]
            if item["candidate_id"] == candidate["candidate_id"]
        )["status"] == candidate["status"]
        assert facade.load_batch("task-1", "batch-1") == saved
        assert service.reviewer_call(
            REVIEWER_TOKEN, "get_batch", {"task_id": "task-1", "batch_id": "batch-1"}
        ) == inbox_before
        exact = facade.prepare_exact_review(
            "task-1", "batch-1", 1, copy.deepcopy(_BINDING)
        )
        assert exact["approval_revision"] == recorded["approval_revision"]
        assert all(subject["confirmed"] for subject in exact["subjects"])
        assert exact_paths[0].read_bytes() == exact_before
        facade.close(); store.close()
        reopened_store = AgentLinkStore(tmp_path / "inbox.json")
        reopened = NativeReviewFacade(
            AgentLinkService(reopened_store, REVIEWER_TOKEN), REVIEWER_TOKEN,
            tmp_path / "review-data",
        )
        try:
            assert reopened.load_relearn_review("task-1", "batch-1", 1)[
                "candidate_decisions"
            ] == [record]
        finally:
            reopened.close(); reopened_store.close()
    finally:
        facade.close(); store.close()


def test_dual_cas_idempotency_and_later_manual_save_recovery(tmp_path):
    store, service, grant, facade, saved = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        with pytest.raises(DesktopReviewError, match="stale|revision|修订"):
            _reject(facade, candidate, comparison, workspace_revision=2)
        with pytest.raises(DesktopReviewError, match="stale|revision|修订"):
            _reject(facade, candidate, comparison, decision_revision=1)
        assert not _decision_path(facade).exists()
        first = _reject(facade, candidate, comparison)
        later_batch = copy.deepcopy(saved["batch"])
        later_batch["interfaces"][0]["meaning"] = "拒绝后的人工修订"
        facade.save_revision("task-1", "batch-1", 1, later_batch)
        retry = _reject(facade, candidate, comparison)
        assert retry["decision_revision"] == 1
        assert retry["current_revision"] == 2
        assert retry["current_decision_revision"] == 1
        assert retry["record_sha256"] == first["record_sha256"]
        with pytest.raises(DesktopReviewError, match="idempotency|幂等|冲突"):
            _reject(facade, candidate, comparison, reason="换一个原因")
        with pytest.raises(DesktopReviewError, match="already|已拒绝|冲突"):
            _reject(
                facade, candidate, comparison, workspace_revision=2,
                decision_revision=1, key="second-key",
            )
        assert len(json.loads(_decision_path(facade).read_text(encoding="utf-8"))["records"]) == 1
    finally:
        facade.close(); store.close()


def test_stale_candidate_rejection_binds_decision_workspace_and_baseline_ancestor(tmp_path):
    store, service, grant, facade, saved = _setup(tmp_path)
    try:
        _, candidate, _ = _candidate(service, grant, facade)
        changed = copy.deepcopy(saved["batch"])
        changed["interfaces"][0]["meaning"] = "第二个人工修订"
        revision_two = facade.save_revision("task-1", "batch-1", 1, changed)
        stale = facade.compare_relearn_candidate(
            "task-1", "batch-1", 2, candidate["candidate_id"]
        )
        assert stale["status"] == "stale"
        inbox_before = service.reviewer_call(
            REVIEWER_TOKEN, "get_batch", {"task_id": "task-1", "batch_id": "batch-1"}
        )
        receipt = _reject(
            facade, candidate, stale, workspace_revision=2,
            reason="拒绝旧错误候选", key="reject-stale",
        )
        assert receipt["workspace_revision"] == 2
        assert facade.load_batch("task-1", "batch-1") == revision_two
        assert service.reviewer_call(
            REVIEWER_TOKEN, "get_batch", {"task_id": "task-1", "batch_id": "batch-1"}
        ) == inbox_before
        facade.close(); store.close()
        reopened_store = AgentLinkStore(tmp_path / "inbox.json")
        reopened = NativeReviewFacade(
            AgentLinkService(reopened_store, REVIEWER_TOKEN), REVIEWER_TOKEN,
            tmp_path / "review-data",
        )
        try:
            view = reopened.load_relearn_review("task-1", "batch-1", 2)
            assert view["candidate_decisions"][0]["record_sha256"] == receipt["record_sha256"]
            compared = reopened.compare_relearn_candidate(
                "task-1", "batch-1", 2, candidate["candidate_id"]
            )
            assert compared["status"] == "stale"
            assert "locally_rejected" in compared["blocked_reasons"]
        finally:
            reopened.close(); reopened_store.close()
    finally:
        facade.close(); store.close()


def test_rejected_candidate_blocks_adoption_but_new_candidate_can_be_adopted(tmp_path):
    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, first_candidate, first_comparison = _candidate(service, grant, facade)
        rejection = _reject(facade, first_candidate, first_comparison)
        with pytest.raises(DesktopReviewError, match="rejected|拒绝|冲突"):
            _adopt(facade, first_candidate, first_comparison)
        _, second_candidate, second_comparison = _candidate(
            service, grant, facade, key="candidate-2", changes=[{
                "change_type": "semantic", "target_type": "interface",
                "target_id": "interface-1", "meaning": "未被旧拒绝绑定的新候选",
            }],
        )
        adopted = _adopt(
            facade, second_candidate, second_comparison, key="adopt-second"
        )
        assert adopted["adopted_revision"] == 2
        retry = _reject(facade, first_candidate, first_comparison)
        assert retry["record_sha256"] == rejection["record_sha256"]
        assert retry["current_revision"] == 2
        with pytest.raises(DesktopReviewError, match="adopt|采用|冲突"):
            facade.reject_relearn_candidate(
                "task-1", "batch-1", 2, second_candidate["candidate_id"],
                second_comparison["candidate_sha256"],
                second_comparison["review_baseline_sha256"], 1,
                "不能伪装撤销已采用事实", "reject-adopted",
            )
    finally:
        facade.close(); store.close()


def test_rejection_survives_later_withdraw_mutable_status(tmp_path):
    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        issue, candidate, comparison = _candidate(service, grant, facade)
        first = _reject(facade, candidate, comparison)
        facade.withdraw_relearn(
            "task-1", "batch-1", 1, issue["issue_id"], 1, "later-withdraw"
        )
        view = facade.load_relearn_review("task-1", "batch-1", 1)
        assert view["candidate_decisions"][0]["record_sha256"] == first["record_sha256"]
        assert _reject(facade, candidate, comparison)["record_sha256"] == first["record_sha256"]
    finally:
        facade.close(); store.close()


def test_legacy_unbound_candidate_can_be_rejected_without_gaining_adoption_rights(tmp_path):
    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        service.reviewer_call(REVIEWER_TOKEN, "record_feedback", {
            "task_id": "task-1", "batch_id": "batch-1",
            "idempotency_key": "legacy-feedback", "expected_revision": 0,
            "notes": [], "issues": [{
                "issue_id": "legacy", "message": "旧问题",
                "scope": {"interface_ids": ["interface-1"], "relationship_ids": []},
            }],
        })
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1",
            "idempotency_key": "legacy-candidate", "batch_id": "batch-1",
            "issue_id": "legacy", "baseline_revision": 1,
            "scope": {"interface_ids": ["interface-1"], "relationship_ids": []},
            "changes": [{
                "change_type": "semantic", "target_type": "interface",
                "target_id": "interface-1", "meaning": "旧候选语义",
            }],
        })
        comparison = facade.compare_relearn_candidate(
            "task-1", "batch-1", 1, candidate["candidate_id"]
        )
        assert comparison["status"] == "legacy_unbound"
        receipt = _reject(facade, candidate, comparison, key="reject-legacy")
        assert receipt["review_baseline_sha256"] is None
        rejected = facade.compare_relearn_candidate(
            "task-1", "batch-1", 1, candidate["candidate_id"]
        )
        assert rejected["status"] == "legacy_unbound"
        assert "locally_rejected" in rejected["blocked_reasons"]
        with pytest.raises(DesktopReviewError):
            _adopt(facade, candidate, comparison, key="legacy-cannot-adopt")
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize(
    "workspace_revision,decision_revision",
    [(True, 0), (1, True)],
)
def test_rejection_rejects_bool_revisions(
    tmp_path, workspace_revision, decision_revision,
):
    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        with pytest.raises(DesktopReviewError, match="整数|revision|修订"):
            _reject(
                facade, candidate, comparison,
                workspace_revision=workspace_revision,
                decision_revision=decision_revision,
            )
        assert not _decision_path(facade).exists()
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("invalid", ["candidate_hash", "baseline_hash", "reason_empty", "reason_long"])
def test_rejection_requires_exact_hashes_and_bounded_reason(tmp_path, invalid):
    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        candidate_sha = comparison["candidate_sha256"]
        baseline_sha = comparison["review_baseline_sha256"]
        reason = "明确拒绝"
        if invalid == "candidate_hash":
            candidate_sha = "0" * 64
        elif invalid == "baseline_hash":
            baseline_sha = "0" * 64
        elif invalid == "reason_empty":
            reason = "   "
        else:
            reason = "拒" * 4001
        with pytest.raises(DesktopReviewError):
            facade.reject_relearn_candidate(
                "task-1", "batch-1", 1, candidate["candidate_id"],
                candidate_sha, baseline_sha, 0, reason, "invalid-reject",
            )
        assert not _decision_path(facade).exists()
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize(
    "tamper", [
        "unknown", "bool", "record", "source", "baseline_revision",
        "workspace_ref",
    ]
)
def test_decision_document_tampering_fails_closed_without_reset(tmp_path, tamper):
    store, service, grant, facade, _ = _setup(tmp_path)
    _, candidate, comparison = _candidate(service, grant, facade)
    _reject(facade, candidate, comparison)
    path = _decision_path(facade)
    facade.close(); store.close()
    document = json.loads(path.read_text(encoding="utf-8"))
    if tamper == "unknown":
        document["unknown"] = True
    elif tamper == "bool":
        document["decision_revision"] = True
    elif tamper == "record":
        document["records"][0]["reason"] = "伪造原因"
    elif tamper == "baseline_revision":
        record = document["records"][0]
        record["issue"]["review_baseline"]["workspace_revision"] = 2
        record["record_sha256"] = canonical_hash({
            key: value for key, value in record.items()
            if key != "record_sha256"
        })
    elif tamper == "workspace_ref":
        record = document["records"][0]
        record["workspace_ref"]["workspace_sha256"] = "0" * 64
        record["record_sha256"] = canonical_hash({
            key: value for key, value in record.items()
            if key != "record_sha256"
        })
    else:
        document["source_ref"] = "0" * 64
    raw = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    path.write_bytes(raw)
    reopened_store = AgentLinkStore(tmp_path / "inbox.json")
    reopened = NativeReviewFacade(
        AgentLinkService(reopened_store, REVIEWER_TOKEN), REVIEWER_TOKEN,
        tmp_path / "review-data",
    )
    try:
        with pytest.raises(DesktopReviewError):
            reopened.load_relearn_review("task-1", "batch-1", 1)
        assert path.read_bytes() == raw
    finally:
        reopened.close(); reopened_store.close()


def test_candidate_from_another_batch_cannot_be_rejected(tmp_path):
    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        other = _batch()
        other["batch_id"] = "batch-2"
        other["idempotency_key"] = "batch-key-2"
        service.agent_call(grant["token"], "submit_batch", other)
        second = facade.load_batch("task-1", "batch-2")
        facade.save_revision("task-1", "batch-2", 0, second["batch"])
        with pytest.raises(DesktopReviewError, match="candidate|候选"):
            facade.reject_relearn_candidate(
                "task-1", "batch-2", 1, candidate["candidate_id"],
                comparison["candidate_sha256"],
                comparison["review_baseline_sha256"], 0,
                "跨批次拒绝", "cross-batch",
            )
        assert not (
            facade._workspace_dir("task-1", "batch-2") / "candidate-decisions.json"
        ).exists()
    finally:
        facade.close(); store.close()


def test_atomic_write_failures_retry_and_post_commit_receipt_recovery(tmp_path, monkeypatch):
    from app.desktop_review import candidate_decisions as decisions_module

    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        original = decisions_module._atomic_write_bytes
        calls = 0

        def fail_before(path, payload):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("before atomic replace")
            return original(path, payload)

        monkeypatch.setattr(decisions_module, "_atomic_write_bytes", fail_before)
        with pytest.raises(DesktopReviewError, match="persist|持久|原子"):
            _reject(facade, candidate, comparison)
        assert not _decision_path(facade).exists()
        assert _reject(facade, candidate, comparison)["decision_revision"] == 1

        _, second, second_comparison = _candidate(
            service, grant, facade, key="candidate-after", changes=[{
                "change_type": "semantic", "target_type": "interface",
                "target_id": "interface-1", "meaning": "第二条拒绝",
            }],
        )
        monkeypatch.setattr(decisions_module, "_atomic_write_bytes", original)

        def write_then_fail(path, payload):
            original(path, payload)
            raise OSError("after atomic replace")

        monkeypatch.setattr(decisions_module, "_atomic_write_bytes", write_then_fail)
        with pytest.raises(DesktopReviewError, match="persist|持久|原子"):
            _reject(
                facade, second, second_comparison,
                decision_revision=1, key="second-reject",
            )
        monkeypatch.setattr(decisions_module, "_atomic_write_bytes", original)
        recovered = _reject(
            facade, second, second_comparison,
            decision_revision=1, key="second-reject",
        )
        assert recovered["decision_revision"] == 2
        assert recovered["current_decision_revision"] == 2
    finally:
        facade.close(); store.close()


def test_invalid_new_record_is_rejected_before_atomic_publish(tmp_path, monkeypatch):
    from app.desktop_review import candidate_decisions as decisions_module

    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        monkeypatch.setattr(decisions_module, "_candidate_projection", lambda _value: {})
        with pytest.raises(DesktopReviewError):
            _reject(facade, candidate, comparison)
        assert not _decision_path(facade).exists()
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("field", ["decision_revision", "workspace_ref_revision"])
def test_persisted_record_rejects_bool_revision_even_with_recomputed_hash(
    tmp_path, field,
):
    store, service, grant, facade, _ = _setup(tmp_path)
    _, candidate, comparison = _candidate(service, grant, facade)
    _reject(facade, candidate, comparison)
    path = _decision_path(facade)
    facade.close(); store.close()
    document = json.loads(path.read_text(encoding="utf-8"))
    record = document["records"][0]
    if field == "decision_revision":
        record["decision_revision"] = True
    else:
        record["workspace_ref"]["revision"] = True
    record["record_sha256"] = canonical_hash({
        key: value for key, value in record.items() if key != "record_sha256"
    })
    raw = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    path.write_bytes(raw)
    reopened_store = AgentLinkStore(tmp_path / "inbox.json")
    reopened = NativeReviewFacade(
        AgentLinkService(reopened_store, REVIEWER_TOKEN), REVIEWER_TOKEN,
        tmp_path / "review-data",
    )
    try:
        with pytest.raises(DesktopReviewError, match="整数|序号|修订|引用"):
            reopened.load_relearn_review("task-1", "batch-1", 1)
        assert path.read_bytes() == raw
    finally:
        reopened.close(); reopened_store.close()


def test_rejection_history_cannot_predate_its_candidate_baseline(tmp_path):
    store, service, grant, facade, saved = _setup(tmp_path)
    try:
        old_reference = facade._parent_reference(saved)
        later = facade.save_revision("task-1", "batch-1", 1, saved["batch"])
        feedback = facade.request_relearn(
            "task-1", "batch-1", 2, 0,
            {"interface_ids": ["interface-1"], "relationship_ids": []},
            "复核第二版", "second-revision-question",
        )
        issue = feedback["issues"][0]
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "idempotency_key": "second-revision-candidate",
            "batch_id": "batch-1", "issue_id": issue["issue_id"],
            "baseline_revision": 1, "scope": issue["scope"],
            "review_baseline_sha256": issue["review_baseline_sha256"],
            "changes": [{"change_type": "semantic", "target_type": "region",
                         "target_id": "region-1", "meaning": "第二版候选含义"}],
        })
        comparison = facade.compare_relearn_candidate("task-1", "batch-1", 2, candidate["candidate_id"])
        _reject(facade, candidate, comparison, workspace_revision=2)
        path = _decision_path(facade)
        document = json.loads(path.read_text(encoding="utf-8"))
        record = document["records"][0]
        record["workspace_revision"], record["workspace_ref"] = 1, old_reference
        record["request_sha256"] = canonical_hash({
            "task_id": record["task_id"], "batch_id": record["batch_id"],
            "expected_revision": 1, "candidate_id": record["candidate_id"],
            "expected_candidate_sha256": record["candidate_sha256"],
            "expected_review_baseline_sha256": record["review_baseline_sha256"],
            "expected_decision_revision": 0, "reason": record["reason"],
            "idempotency_key_sha256": record["idempotency_key_sha256"],
        })
        record["record_sha256"] = canonical_hash({
            key: value for key, value in record.items() if key != "record_sha256"
        })
        payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
        path.write_bytes(payload)
        facade.close(); store.close()
        reopened_store = AgentLinkStore(tmp_path / "inbox.json")
        reopened = NativeReviewFacade(AgentLinkService(reopened_store, REVIEWER_TOKEN), REVIEWER_TOKEN, tmp_path / "review-data")
        try:
            with pytest.raises(DesktopReviewError, match="基线|修订"):
                reopened.load_relearn_review("task-1", "batch-1", 2)
            assert path.read_bytes() == payload
            assert reopened.load_batch("task-1", "batch-1") == later
        finally:
            reopened.close(); reopened_store.close()
    finally:
        facade.close(); store.close()


def test_process_exit_after_atomic_decision_replace_recovers_same_record(tmp_path):
    store, service, grant, facade, _ = _setup(tmp_path)
    _, candidate, comparison = _candidate(service, grant, facade)
    facade.close(); store.close()
    script = "\n".join([
        "import os, sys",
        "from pathlib import Path",
        "from app.agent_link import AgentLinkService, AgentLinkStore",
        "from app.desktop_review import candidate_decisions as decisions_module",
        "from app.desktop_review.workspace import NativeReviewFacade",
        "token = sys.argv[2]",
        "store = AgentLinkStore(Path(sys.argv[1]))",
        "facade = NativeReviewFacade(AgentLinkService(store, token), token, Path(sys.argv[3]))",
        "original = decisions_module._atomic_write_bytes",
        "def write_then_exit(path, payload):",
        "    original(path, payload)",
        "    os._exit(23)",
        "decisions_module._atomic_write_bytes = write_then_exit",
        "facade.reject_relearn_candidate('task-1', 'batch-1', 1, sys.argv[4], sys.argv[5], sys.argv[6], 0, '进程中断拒绝', 'process-reject')",
        "os._exit(24)",
    ])
    process = subprocess.Popen(
        [
            sys.executable, "-c", script,
            str(tmp_path / "inbox.json"), REVIEWER_TOKEN,
            str(tmp_path / "review-data"), candidate["candidate_id"],
            comparison["candidate_sha256"], comparison["review_baseline_sha256"],
        ],
        cwd=Path.cwd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    try:
        stdout, stderr = process.communicate(timeout=15)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)
    assert process.returncode == 23, (stdout, stderr)
    reopened_store = AgentLinkStore(tmp_path / "inbox.json")
    reopened = NativeReviewFacade(
        AgentLinkService(reopened_store, REVIEWER_TOKEN), REVIEWER_TOKEN,
        tmp_path / "review-data",
    )
    try:
        recovered = _reject(
            reopened, candidate, comparison,
            reason="进程中断拒绝", key="process-reject",
        )
        assert recovered["decision_revision"] == 1
        assert recovered["current_decision_revision"] == 1
        assert len(reopened.load_relearn_review(
            "task-1", "batch-1", 1
        )["candidate_decisions"]) == 1
    finally:
        reopened.close(); reopened_store.close()


@pytest.mark.parametrize("winner", ["reject", "adopt"])
def test_reject_and_adopt_are_linearized_in_both_orders(tmp_path, monkeypatch, winner):
    from app.desktop_review import candidate_decisions as decisions_module
    from app.desktop_review import workspace as workspace_module

    store, service, grant, facade, _ = _setup(tmp_path)
    _, candidate, comparison = _candidate(service, grant, facade)
    entered, release = threading.Event(), threading.Event()
    successes, failures = [], []
    if winner == "reject":
        original = decisions_module.CandidateDecisionService._publish

        def paused(self, document):
            entered.set(); assert release.wait(3)
            return original(self, document)

        monkeypatch.setattr(
            decisions_module.CandidateDecisionService, "_publish", paused
        )
    else:
        original = workspace_module.NativeReviewFacade._persist_revision

        def paused(self, snapshot):
            if snapshot.get("relearn_adoption"):
                entered.set(); assert release.wait(3)
            return original(self, snapshot)

        monkeypatch.setattr(
            workspace_module.NativeReviewFacade, "_persist_revision", paused
        )

    def reject():
        try:
            successes.append(("reject", _reject(facade, candidate, comparison)))
        except Exception as error:
            failures.append(("reject", error))

    def adopt():
        try:
            successes.append(("adopt", _adopt(facade, candidate, comparison)))
        except Exception as error:
            failures.append(("adopt", error))

    first = threading.Thread(target=reject if winner == "reject" else adopt, daemon=True)
    second = threading.Thread(target=adopt if winner == "reject" else reject, daemon=True)
    first.start(); assert entered.wait(3)
    second.start()
    try:
        second.join(0.1)
        assert second.is_alive()
    finally:
        release.set()
    first.join(3); second.join(3)
    try:
        assert not first.is_alive() and not second.is_alive()
        assert [kind for kind, _ in successes] == [winner]
        assert [kind for kind, _ in failures] == ["adopt" if winner == "reject" else "reject"]
        assert facade.load_batch("task-1", "batch-1")["revision"] == (
            1 if winner == "reject" else 2
        )
    finally:
        facade.close(); store.close()
