"""重学候选明确采用的持久、幂等与负向后端测试。"""

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
from app.desktop_review.exact_review import ExactReviewError
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
from test_desktop_relearn import REVIEWER_TOKEN, _setup


_APPLICATION_BINDING = {
    "kind": "native",
    "display_name": "Notepad",
    "executable_identity": "notepad.exe",
    "product_name": "Notepad",
}


def _candidate(service, grant, facade, *, key="candidate", changes=None):
    view = facade.request_relearn(
        "task-1", "batch-1", 1, 0,
        {"interface_ids": ["interface-1"], "relationship_ids": []},
        "请采用前先明确比较", "request",
    )
    issue = view["issues"][0]
    receipt = service.agent_call(grant["token"], "submit_candidate", {
        "contract_version": "agent_link_v1", "idempotency_key": key,
        "batch_id": "batch-1", "issue_id": issue["issue_id"],
        "baseline_revision": 1,
        "review_baseline_sha256": issue["review_baseline_sha256"],
        "scope": issue["scope"],
        "changes": changes or [
            {"change_type": "geometry", "region_id": "region-1", "bbox": [4.0, 5.0, 20.0, 15.0]},
            {"change_type": "semantic", "target_type": "region", "target_id": "region-1", "meaning": "采用后的框"},
            {"change_type": "step", "step_id": "step-1", "action_type": "open_detail", "target_region_id": "region-1", "expected_result": "采用后的结果"},
        ],
    })
    comparison = facade.compare_relearn_candidate("task-1", "batch-1", 1, receipt["candidate_id"])
    return issue, receipt, comparison


def _adopt(facade, receipt, comparison, *, expected_revision=1, key="adopt-key"):
    return facade.adopt_relearn_candidate(
        "task-1", "batch-1", expected_revision,
        receipt["candidate_id"], comparison["candidate_sha256"],
        comparison["review_baseline_sha256"], key,
    )


def test_adoption_creates_hash_bound_child_and_survives_restart(tmp_path):
    store, service, grant, facade, saved = _setup(tmp_path)
    issue, candidate, comparison = _candidate(service, grant, facade)
    original = service.reviewer_call(REVIEWER_TOKEN, "get_batch", {"task_id": "task-1", "batch_id": "batch-1"})
    try:
        receipt = _adopt(facade, candidate, comparison)
        assert receipt["contract_version"] == "desktop_relearn_adoption_receipt_v1"
        assert receipt["previous_revision"] == 1
        assert receipt["adopted_revision"] == receipt["current_revision"] == 2
        assert receipt["is_current"] is True and receipt["staging_only"] is True
        adopted = receipt["snapshot"]
        assert adopted["revision"] == 2 and adopted["review_status"] == "needs_human_review"
        assert adopted["batch"]["interfaces"][0]["regions"][0]["bbox"] == [4.0, 5.0, 20.0, 15.0]
        assert adopted["batch"]["interfaces"][0]["regions"][0]["meaning"] == "采用后的框"
        assert adopted["parent_revision"]["revision"] == 1
        assert adopted["relearn_adoption"]["candidate_id"] == candidate["candidate_id"]
        assert "adopt-key" not in json.dumps(adopted["relearn_adoption"], ensure_ascii=False)
        assert "idempotency_key" not in adopted["relearn_adoption"]
        assert facade.load_batch("task-1", "batch-1") == adopted
        assert service.reviewer_call(REVIEWER_TOKEN, "get_batch", {"task_id": "task-1", "batch_id": "batch-1"}) == original
        assert saved["revision"] == 1 and saved["batch"]["interfaces"][0]["regions"][0]["meaning"] == "人工框"
        facade.close(); store.close()
        reopened_store = AgentLinkStore(tmp_path / "inbox.json")
        reopened = NativeReviewFacade(AgentLinkService(reopened_store, REVIEWER_TOKEN), REVIEWER_TOKEN, tmp_path / "review-data")
        try:
            assert reopened.load_batch("task-1", "batch-1") == adopted
        finally:
            reopened.close(); reopened_store.close()
    finally:
        facade.close(); store.close()


def test_retry_after_later_manual_save_returns_original_adoption_without_overwrite(tmp_path):
    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        adopted = _adopt(facade, candidate, comparison)
        later_batch = copy.deepcopy(adopted["snapshot"]["batch"])
        later_batch["interfaces"][0]["meaning"] = "采用后的再次人工修订"
        later = facade.save_revision("task-1", "batch-1", 2, later_batch)
        assert later["parent_revision"]["revision"] == 2
        retry = _adopt(facade, candidate, comparison)
        assert retry["adopted_revision"] == 2
        assert retry["current_revision"] == 3 and retry["is_current"] is False
        assert retry["snapshot"] == adopted["snapshot"]
        assert facade.load_batch("task-1", "batch-1") == later
        with pytest.raises(DesktopReviewError, match="idempotency|幂等|冲突"):
            _adopt(facade, candidate, comparison, key="adopt-key", expected_revision=3)
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("mutation", ["feedback", "withdraw"])
def test_committed_adoption_survives_later_feedback_or_withdraw(tmp_path, mutation):
    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        issue, candidate, comparison = _candidate(service, grant, facade)
        adopted = _adopt(facade, candidate, comparison)
        if mutation == "feedback":
            service.reviewer_call(REVIEWER_TOKEN, "record_feedback", {
                "task_id": "task-1", "batch_id": "batch-1", "idempotency_key": "later-feedback",
                "expected_revision": 1, "notes": [{"note_id": "later", "text": "采用后备注"}], "issues": [],
            })
        else:
            service.reviewer_call(REVIEWER_TOKEN, "withdraw_issue", {
                "task_id": "task-1", "batch_id": "batch-1", "issue_id": issue["issue_id"],
                "expected_revision": 1, "idempotency_key": "later-withdraw",
            })
        assert facade.load_batch("task-1", "batch-1") == adopted["snapshot"]
        retry = _adopt(facade, candidate, comparison)
        assert retry == adopted
    finally:
        facade.close(); store.close()


def test_stale_withdrawn_wrong_hash_and_blocked_candidates_never_commit(tmp_path):
    store, service, grant, facade, saved = _setup(tmp_path)
    try:
        issue, candidate, comparison = _candidate(service, grant, facade)
        with pytest.raises(DesktopReviewError):
            facade.adopt_relearn_candidate("task-1", "batch-1", 1, candidate["candidate_id"], "0" * 64, comparison["review_baseline_sha256"], "wrong-candidate")
        with pytest.raises(DesktopReviewError):
            facade.adopt_relearn_candidate("task-1", "batch-1", 1, candidate["candidate_id"], comparison["candidate_sha256"], "0" * 64, "wrong-baseline")
        facade.withdraw_relearn("task-1", "batch-1", 1, issue["issue_id"], 1, "withdraw")
        with pytest.raises(DesktopReviewError):
            _adopt(facade, candidate, comparison, key="withdrawn")
        assert facade.load_batch("task-1", "batch-1") == saved
    finally:
        facade.close(); store.close()

    store, service, grant, facade, saved = _setup(tmp_path / "blocked")
    try:
        _, candidate, comparison = _candidate(service, grant, facade, changes=[
            {"change_type": "step", "step_id": "step-1", "action_type": "final_submit", "target_region_id": "region-1", "expected_result": "提交"},
        ])
        assert comparison["status"] == "blocked"
        with pytest.raises(DesktopReviewError):
            _adopt(facade, candidate, comparison)
        assert facade.load_batch("task-1", "batch-1") == saved
    finally:
        facade.close(); store.close()


def test_current_write_failure_leaves_orphan_and_retry_commits_once(tmp_path, monkeypatch):
    from app.desktop_review import workspace as workspace_module

    store, service, grant, facade, saved = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        original_write = workspace_module._atomic_write_bytes
        failed = False

        def fail_once(path, payload):
            nonlocal failed
            if path.name == "current.json" and not failed:
                failed = True
                raise OSError("simulated current failure")
            return original_write(path, payload)

        monkeypatch.setattr(workspace_module, "_atomic_write_bytes", fail_once)
        with pytest.raises(DesktopReviewError, match="persist|持久"):
            _adopt(facade, candidate, comparison)
        assert facade.load_batch("task-1", "batch-1") == saved
        receipt = _adopt(facade, candidate, comparison)
        assert receipt["adopted_revision"] == 2
        assert facade.load_batch("task-1", "batch-1")["revision"] == 2
    finally:
        facade.close(); store.close()


def test_exception_after_current_commit_recovers_original_receipt(tmp_path, monkeypatch):
    from app.desktop_review import workspace as workspace_module

    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        original_publish = workspace_module.NativeReviewFacade._publish_current

        def publish_then_fail(self, snapshot):
            original_publish(self, snapshot)
            raise OSError("simulated caller interruption after commit")

        monkeypatch.setattr(workspace_module.NativeReviewFacade, "_publish_current", publish_then_fail)
        with pytest.raises(DesktopReviewError, match="persist|持久"):
            _adopt(facade, candidate, comparison)
        monkeypatch.setattr(workspace_module.NativeReviewFacade, "_publish_current", original_publish)
        assert facade.load_batch("task-1", "batch-1")["revision"] == 2
        recovered = _adopt(facade, candidate, comparison)
        assert recovered["adopted_revision"] == recovered["current_revision"] == 2
        assert recovered["is_current"] is True
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("tamper_kind", ["adoption", "parent", "request", "baseline_revision", "bool_comparison_revision"])
def test_parent_or_adoption_tampering_fails_closed_without_repair(tmp_path, tamper_kind):
    store, service, grant, facade, _ = _setup(tmp_path)
    _, candidate, comparison = _candidate(service, grant, facade)
    adopted = _adopt(facade, candidate, comparison)["snapshot"]
    current_path = facade._workspace_dir("task-1", "batch-1") / "current.json"
    manifest = json.loads(current_path.read_text(encoding="utf-8"))
    workspace_path = facade._artifact_root / manifest["workspace_path"]
    original = workspace_path.read_bytes()
    facade.close(); store.close()
    payload = json.loads(original.decode("utf-8"))
    if tamper_kind == "adoption":
        payload["relearn_adoption"]["candidate_sha256"] = "0" * 64
    elif tamper_kind == "parent":
        payload["parent_revision"]["workspace_sha256"] = "0" * 64
    elif tamper_kind == "request":
        payload["relearn_adoption"]["request_sha256"] = "0" * 64
    elif tamper_kind == "baseline_revision":
        payload["relearn_adoption"]["issue"]["review_baseline"]["workspace_revision"] = 2
    else:
        payload["relearn_adoption"]["comparison"]["workspace_revision"] = True
    tampered = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
    workspace_path.write_bytes(tampered)
    manifest["workspace_sha256"] = hashlib.sha256(tampered).hexdigest()
    current_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    reopened_store = AgentLinkStore(tmp_path / "inbox.json")
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, REVIEWER_TOKEN), REVIEWER_TOKEN, tmp_path / "review-data")
    try:
        with pytest.raises(DesktopReviewError):
            reopened.load_batch("task-1", "batch-1")
        assert workspace_path.read_bytes() == tampered
    finally:
        reopened.close(); reopened_store.close()


def test_withdraw_cannot_interleave_between_adoption_validation_and_commit(tmp_path, monkeypatch):
    from app.desktop_review import workspace as workspace_module

    store, service, grant, facade, _ = _setup(tmp_path)
    issue, candidate, comparison = _candidate(service, grant, facade)
    entered, release = threading.Event(), threading.Event()
    original_persist = workspace_module.NativeReviewFacade._persist_revision

    def paused(self, snapshot):
        if snapshot.get("relearn_adoption"):
            entered.set()
            assert release.wait(3)
        return original_persist(self, snapshot)

    monkeypatch.setattr(workspace_module.NativeReviewFacade, "_persist_revision", paused)
    results, errors = [], []

    def adopt():
        try:
            results.append(_adopt(facade, candidate, comparison))
        except Exception as error:
            errors.append(error)

    def withdraw():
        try:
            service.reviewer_call(REVIEWER_TOKEN, "withdraw_issue", {
                "task_id": "task-1", "batch_id": "batch-1", "issue_id": issue["issue_id"],
                "expected_revision": 1, "idempotency_key": "withdraw-concurrent",
            })
        except Exception as error:
            errors.append(error)

    adopter = threading.Thread(target=adopt, daemon=True)
    withdrawer = threading.Thread(target=withdraw, daemon=True)
    adopter.start(); assert entered.wait(3)
    withdrawer.start()
    try:
        withdrawer.join(0.1)
        assert withdrawer.is_alive()
    finally:
        release.set()
    adopter.join(3); withdrawer.join(3)
    try:
        assert not adopter.is_alive() and not withdrawer.is_alive()
        assert results and results[0]["adopted_revision"] == 2
        assert not errors
    finally:
        facade.close(); store.close()


def test_adoption_invalidates_previously_recorded_exact_review(tmp_path):
    store, service, grant, facade, _ = _setup(tmp_path)
    try:
        prepared = facade.prepare_exact_review(
            "task-1", "batch-1", 1, copy.deepcopy(_APPLICATION_BINDING)
        )
        recorded = facade.record_review_decisions(
            prepared["review_ref"],
            prepared["approval_revision"],
            [subject["subject_id"] for subject in prepared["subjects"]],
        )
        _, candidate, comparison = _candidate(service, grant, facade)
        assert _adopt(facade, candidate, comparison)["adopted_revision"] == 2
        with pytest.raises(ExactReviewError, match="workspace|工作区|修订|match"):
            facade.compile_exact_review(
                prepared["review_ref"], recorded["approval_revision"]
            )
    finally:
        facade.close(); store.close()


def test_process_exit_after_current_replace_recovers_without_duplicate(tmp_path):
    store, service, grant, facade, _ = _setup(tmp_path)
    _, candidate, comparison = _candidate(service, grant, facade)
    facade.close(); store.close()

    script = "\n".join([
        "import os, sys",
        "from pathlib import Path",
        "from app.agent_link import AgentLinkService, AgentLinkStore",
        "from app.desktop_review import workspace as workspace_module",
        "token = sys.argv[2]",
        "store = AgentLinkStore(Path(sys.argv[1]))",
        "service = AgentLinkService(store, token)",
        "facade = workspace_module.NativeReviewFacade(service, token, Path(sys.argv[3]))",
        "original = workspace_module.NativeReviewFacade._publish_current",
        "def publish_then_exit(self, snapshot):",
        "    original(self, snapshot)",
        "    os._exit(23)",
        "workspace_module.NativeReviewFacade._publish_current = publish_then_exit",
        "facade.adopt_relearn_candidate('task-1', 'batch-1', 1, sys.argv[4], sys.argv[5], sys.argv[6], 'process-exit-key')",
        "os._exit(24)",
    ])
    process = subprocess.Popen(
        [
            sys.executable, "-c", script,
            str(tmp_path / "inbox.json"), REVIEWER_TOKEN,
            str(tmp_path / "review-data"), candidate["candidate_id"],
            comparison["candidate_sha256"], comparison["review_baseline_sha256"],
        ],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=15)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    assert process.returncode == 23, (stdout, stderr)

    reopened_store = AgentLinkStore(tmp_path / "inbox.json")
    reopened = NativeReviewFacade(
        AgentLinkService(reopened_store, REVIEWER_TOKEN),
        REVIEWER_TOKEN,
        tmp_path / "review-data",
    )
    try:
        recovered = _adopt(
            reopened, candidate, comparison, key="process-exit-key"
        )
        assert recovered["adopted_revision"] == recovered["current_revision"] == 2
        assert recovered["is_current"] is True
        revision_files = list(
            (reopened._workspace_dir("task-1", "batch-1") / "revisions").glob(
                "r2-*/workspace.json"
            )
        )
        assert len(revision_files) == 1
    finally:
        reopened.close(); reopened_store.close()


def test_legacy_v1_root_adopt_save_and_retry_chain(tmp_path):
    store, service, grant, facade, saved = _setup(tmp_path)
    legacy = copy.deepcopy(saved)
    legacy["contract_version"] = "desktop_review_workspace_v1"
    legacy.pop("parent_revision")
    legacy.pop("relearn_adoption")
    facade._persist_revision(legacy)
    facade._publish_current(legacy)
    assert facade.load_batch("task-1", "batch-1") == legacy
    try:
        _, candidate, comparison = _candidate(service, grant, facade)
        adopted = _adopt(facade, candidate, comparison, key="legacy-adopt")
        assert adopted["snapshot"]["contract_version"] == "desktop_review_workspace_v2"
        assert adopted["snapshot"]["parent_revision"]["revision"] == 1
        later_batch = copy.deepcopy(adopted["snapshot"]["batch"])
        later_batch["interfaces"][0]["meaning"] = "legacy 链后的人工保存"
        later = facade.save_revision("task-1", "batch-1", 2, later_batch)
        assert later["contract_version"] == "desktop_review_workspace_v2"
        assert later["parent_revision"]["revision"] == 2
        assert later["relearn_adoption"] is None
        retry = _adopt(facade, candidate, comparison, key="legacy-adopt")
        assert retry["adopted_revision"] == 2
        assert retry["current_revision"] == 3
        assert retry["is_current"] is False
        assert retry["snapshot"] == adopted["snapshot"]
    finally:
        facade.close(); store.close()
