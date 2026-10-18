"""固定已保存人工修订的重学反馈与只读候选比较。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.agent_link.contracts import (
    AgentLinkError,
    canonical_hash,
    validate_candidate,
    validate_scope,
)
from app.agent_link.candidate_projection import (
    CandidateProjectionError,
    index_candidate_fields,
    project_candidate_fields,
)
from app.agent_link.review_baseline import (
    candidate_content_sha256,
    hashes_equal,
    validate_review_baseline,
    validate_candidate_changes,
)


_REVIEW_CONTRACT = "desktop_relearn_review_v1"
_COMPARISON_CONTRACT = "desktop_relearn_comparison_v1"
_DANGEROUS_ACTIONS = {"confirm", "delete", "final_submit", "payment", "send", "submit"}
_KNOWN_ACTIONS = {
    "back", "click", "close_modal", "continue_next_step", "fill_field",
    "open_apply_flow", "open_detail", "open_filter", "open_link", "open_modal",
    "observe", "read", "safe_stop", "scroll", "scroll_region", "select", "select_option",
    "submit_search", "type_text", "wait",
}


class RelearnReviewService:
    def __init__(self, facade: Any) -> None:
        self._facade = facade

    def load(self, task_id: str, batch_id: str, expected_revision: int) -> dict[str, Any]:
        snapshot = self._saved_snapshot(task_id, batch_id, expected_revision)
        detail = self._detail(snapshot)
        return self._view(snapshot, detail)

    def request(
        self,
        task_id: str,
        batch_id: str,
        expected_revision: int,
        expected_feedback_revision: int,
        scope: Any,
        message: Any,
        idempotency_key: Any,
    ) -> dict[str, Any]:
        snapshot = self._saved_snapshot(task_id, batch_id, expected_revision)
        feedback_revision = _non_negative_int(expected_feedback_revision, "expected_feedback_revision")
        checked_scope = self._scope(scope, snapshot["batch"])
        checked_message = _required_text(message, "message", maximum=4000)
        key = _required_text(idempotency_key, "idempotency_key", maximum=160)
        baseline = _baseline(snapshot)
        identity = {
            "task_id": snapshot["task_id"],
            "batch_id": snapshot["batch_id"],
            "workspace_revision": snapshot["revision"],
            "source_ref": snapshot["source_ref"],
            "feedback_revision": feedback_revision,
            "scope": checked_scope,
            "message": checked_message,
            "review_baseline_sha256": canonical_hash(baseline),
        }
        issue_id = "relearn-" + canonical_hash(identity)
        receipt = self._facade._reviewer("record_feedback", {
            "task_id": snapshot["task_id"],
            "batch_id": snapshot["batch_id"],
            "idempotency_key": key,
            "expected_revision": feedback_revision,
            "notes": [],
            "issues": [{
                "issue_id": issue_id,
                "scope": checked_scope,
                "message": checked_message,
                "review_baseline": baseline,
            }],
        })
        if (
            receipt.get("batch_id") != snapshot["batch_id"]
            or receipt.get("revision") != feedback_revision + 1
            or receipt.get("status") != "feedback_recorded"
        ):
            raise _error("inbox 返回的重学问题回执身份或修订无效")
        view = self._view(snapshot, self._detail(snapshot))
        matching = next((item for item in view["issues"] if item.get("issue_id") == issue_id), None)
        if not matching or any((
            matching.get("message") != checked_message,
            matching.get("scope") != checked_scope,
            matching.get("status") != "open",
            matching.get("baseline_revision") != feedback_revision + 1,
            matching.get("review_baseline") != baseline,
            matching.get("review_baseline_sha256") != canonical_hash(baseline),
        )):
            raise _error("重学问题未以确切人工基线持久化")
        return view

    def withdraw(
        self,
        task_id: str,
        batch_id: str,
        expected_revision: int,
        issue_id: Any,
        expected_feedback_revision: int,
        idempotency_key: Any,
    ) -> dict[str, Any]:
        snapshot = self._saved_snapshot(task_id, batch_id, expected_revision)
        feedback_revision = _positive_int(expected_feedback_revision, "expected_feedback_revision")
        issue = _required_text(issue_id, "issue_id", maximum=160)
        key = _required_text(idempotency_key, "idempotency_key", maximum=160)
        receipt = self._facade._reviewer("withdraw_issue", {
            "task_id": snapshot["task_id"], "batch_id": snapshot["batch_id"],
            "issue_id": issue, "expected_revision": feedback_revision,
            "idempotency_key": key,
        })
        if (
            receipt.get("batch_id") != snapshot["batch_id"]
            or receipt.get("issue_id") != issue
            or receipt.get("revision") != feedback_revision + 1
            or receipt.get("status") != "issue_withdrawn"
        ):
            raise _error("inbox 返回的撤回回执身份或修订无效")
        view = self._view(snapshot, self._detail(snapshot))
        if not any(item.get("issue_id") == issue and item.get("status") == "withdrawn" for item in view["issues"]):
            raise _error("重学问题撤回状态未持久化")
        return view

    def compare(
        self, task_id: str, batch_id: str, expected_revision: int, candidate_id: Any
    ) -> dict[str, Any]:
        snapshot = self._saved_snapshot(task_id, batch_id, expected_revision)
        detail = self._detail(snapshot)
        identifier = _required_text(candidate_id, "candidate_id", maximum=160)
        candidate = next((item for item in detail["candidates"] if item.get("candidate_id") == identifier), None)
        if candidate is None:
            raise _error("candidate_not_found: 候选不存在于当前批次")
        issue = next((item for item in detail["issues"] if item.get("issue_id") == candidate.get("issue_id")), None)
        if issue is None:
            raise _error("candidate_issue_missing: 候选问题引用无效")

        original = detail["batch"]
        blockers: list[str] = []
        baseline_wire = issue.get("review_baseline")
        if baseline_wire is None:
            baseline = original
            baseline_sha = None
            baseline_workspace_revision = None
            legacy = True
            blockers.append("legacy_unbound: candidate has no saved human review baseline")
        else:
            legacy = False
            try:
                _, baseline = validate_review_baseline(
                    baseline_wire, task_id=snapshot["task_id"], original_batch=original
                )
            except AgentLinkError as error:
                raise _error("candidate_baseline_invalid: " + error.message) from error
            baseline_sha = issue.get("review_baseline_sha256")
            if not hashes_equal(baseline_sha, canonical_hash(baseline_wire)):
                raise _error("candidate_baseline_invalid: 基线摘要不匹配")
            if not hashes_equal(candidate.get("review_baseline_sha256"), baseline_sha):
                raise _error("candidate_baseline_invalid: 候选未绑定问题基线")
            baseline_workspace_revision = baseline_wire["workspace_revision"]

        expected_candidate_hash = candidate_content_sha256(candidate)
        stored_candidate_hash = candidate.get("candidate_sha256")
        if stored_candidate_hash is not None and not hashes_equal(stored_candidate_hash, expected_candidate_hash):
            raise _error("candidate_content_invalid: 候选内容摘要不匹配")
        candidate_sha = stored_candidate_hash or expected_candidate_hash
        diffs = _build_diffs(candidate, baseline, snapshot["batch"], blockers)
        if (
            not legacy
            and baseline_workspace_revision == snapshot["revision"]
            and baseline_wire["batch_sha256"] != canonical_hash(snapshot["batch"])
        ):
            blockers.append("baseline_current_revision_content_mismatch")
        from .candidate_decisions import CandidateDecisionService
        if CandidateDecisionService(self._facade).is_rejected(
            snapshot, detail, identifier, candidate_sha
        ):
            blockers.append("locally_rejected")

        feedback_revision = _feedback_revision(detail)
        if issue.get("status") == "withdrawn" or candidate.get("status") == "withdrawn":
            status = "withdrawn"
        elif legacy:
            status = "legacy_unbound"
        elif (
            candidate.get("status") == "stale"
            or baseline_workspace_revision != snapshot["revision"]
            or candidate.get("baseline_revision") != feedback_revision
        ):
            status = "stale"
        elif blockers:
            status = "blocked"
        else:
            status = "current"
        return {
            "contract_version": _COMPARISON_CONTRACT,
            "task_id": snapshot["task_id"], "batch_id": snapshot["batch_id"],
            "source_ref": snapshot["source_ref"], "workspace_revision": snapshot["revision"],
            "candidate_id": identifier, "candidate_sha256": candidate_sha,
            "issue_id": issue["issue_id"], "review_baseline_sha256": baseline_sha,
            "baseline_workspace_revision": baseline_workspace_revision,
            "status": status, "blocked_reasons": blockers, "diffs": diffs,
        }

    def _saved_snapshot(self, task_id: Any, batch_id: Any, expected_revision: Any) -> dict[str, Any]:
        task = _required_text(task_id, "task_id", maximum=4000)
        batch = _required_text(batch_id, "batch_id", maximum=160)
        revision = _positive_int(expected_revision, "expected_revision")
        snapshot = self._facade.load_batch(task, batch)
        if snapshot.get("revision") != revision or not snapshot.get("workflow_review_path"):
            raise _error("stale_revision: 必须重新加载确切的已保存人工修订")
        return snapshot

    def _detail(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        detail = self._facade._reviewer("get_batch", {
            "task_id": snapshot["task_id"], "batch_id": snapshot["batch_id"],
        })
        if detail.get("source") != "untrusted_external" or not isinstance(detail.get("batch"), dict):
            raise _error("inbox 返回的重学批次来源无效")
        if canonical_hash(detail["batch"]) != snapshot["source_ref"]:
            raise _error("source_changed: inbox 原始批次与工作区来源不一致")
        if not isinstance(detail.get("feedback_history"), list) or not isinstance(detail.get("issues"), list) or not isinstance(detail.get("candidates"), list):
            raise _error("inbox 返回的重学记录无效")
        _validate_detail_records(detail, snapshot)
        return detail

    def _view(self, snapshot: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
        from .candidate_decisions import CandidateDecisionService
        decision_revision, candidate_decisions = CandidateDecisionService(
            self._facade
        ).load(snapshot, detail)
        return {
            "contract_version": _REVIEW_CONTRACT,
            "task_id": snapshot["task_id"], "batch_id": snapshot["batch_id"],
            "source_ref": snapshot["source_ref"], "workspace_revision": snapshot["revision"],
            "feedback_revision": _feedback_revision(detail),
            "decision_revision": decision_revision,
            "candidate_decisions": candidate_decisions,
            "issues": deepcopy(detail["issues"]), "candidates": deepcopy(detail["candidates"]),
            "staging_only": True,
        }

    @staticmethod
    def _scope(value: Any, batch: dict[str, Any]) -> dict[str, list[str]]:
        try:
            return validate_scope(value, batch)
        except AgentLinkError as error:
            raise _error("invalid_scope: " + error.message) from error


def _baseline(snapshot: dict[str, Any]) -> dict[str, Any]:
    raw_batch = deepcopy(snapshot["batch"])
    for screenshot in raw_batch["screenshots"]:
        screenshot.pop("sha256", None)
        screenshot.pop("width", None)
        screenshot.pop("height", None)
    return {
        "contract_version": "desktop_review_baseline_v1",
        "task_id": snapshot["task_id"],
        "workspace_revision": snapshot["revision"],
        "source_ref": snapshot["source_ref"],
        "batch_sha256": canonical_hash(snapshot["batch"]),
        "batch": raw_batch,
    }


def _feedback_revision(detail: dict[str, Any]) -> int:
    history = detail["feedback_history"]
    if not history:
        return 0
    revision = history[-1].get("revision") if isinstance(history[-1], dict) else None
    if type(revision) is not int or revision < 1:
        raise _error("inbox 反馈修订历史无效")
    return revision


def _validate_detail_records(detail: dict[str, Any], snapshot: dict[str, Any]) -> None:
    history = detail["feedback_history"]
    revisions = [entry.get("revision") if isinstance(entry, dict) else None for entry in history]
    if revisions != list(range(1, len(history) + 1)):
        raise _error("inbox 反馈修订历史不连续")
    feedback_revision = len(history)
    issue_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    try:
        for issue in detail["issues"]:
            if not isinstance(issue, dict):
                raise _error("inbox 问题记录无效")
            allowed = {"issue_id", "scope", "message", "status", "baseline_revision"}
            has_baseline = "review_baseline" in issue or "review_baseline_sha256" in issue
            if has_baseline:
                allowed |= {"review_baseline", "review_baseline_sha256"}
            if set(issue) != allowed:
                raise _error("inbox 问题记录含有未知字段")
            issue_id = issue.get("issue_id")
            baseline_revision = issue.get("baseline_revision")
            if (
                not isinstance(issue_id, str) or not issue_id or issue_id in issue_by_id
                or issue.get("status") not in {"open", "withdrawn"}
                or type(baseline_revision) is not int
                or not 1 <= baseline_revision <= feedback_revision
                or not isinstance(issue.get("message"), str) or not issue["message"]
            ):
                raise _error("inbox 问题记录身份或状态无效")
            effective_batch = detail["batch"]
            if has_baseline:
                baseline, effective_batch = validate_review_baseline(
                    issue["review_baseline"],
                    task_id=snapshot["task_id"],
                    original_batch=detail["batch"],
                )
                if not hashes_equal(issue["review_baseline_sha256"], canonical_hash(baseline)):
                    raise _error("inbox 问题的审核基线摘要无效")
            checked_scope = validate_scope(issue["scope"], effective_batch)
            if checked_scope != issue["scope"]:
                raise _error("inbox 问题范围没有规范化")
            issue_by_id[issue_id] = (issue, effective_batch)

        candidate_ids: set[str] = set()
        for stored in detail["candidates"]:
            if not isinstance(stored, dict):
                raise _error("inbox 候选记录无效")
            has_hash = "candidate_sha256" in stored
            base = {
                key: deepcopy(value)
                for key, value in stored.items()
                if key not in {"candidate_id", "connection_id", "status", "candidate_sha256"}
            }
            allowed = set(base) | {"candidate_id", "connection_id", "status"}
            if has_hash:
                allowed.add("candidate_sha256")
            if set(stored) != allowed:
                raise _error("inbox 候选记录含有未知字段")
            candidate_id = stored.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id or candidate_id in candidate_ids:
                raise _error("inbox 候选身份无效")
            candidate_ids.add(candidate_id)
            candidate = validate_candidate(base)
            if candidate != base or candidate.get("batch_id") != snapshot["batch_id"]:
                raise _error("inbox 候选内容或批次身份无效")
            binding = issue_by_id.get(candidate["issue_id"])
            if binding is None:
                raise _error("inbox 候选的问题引用无效")
            issue, effective_batch = binding
            if candidate["baseline_revision"] != issue["baseline_revision"] or candidate["scope"] != issue["scope"]:
                raise _error("inbox 候选的反馈修订或范围无效")
            has_baseline = "review_baseline" in issue
            if has_baseline:
                if (
                    not has_hash
                    or not hashes_equal(candidate.get("review_baseline_sha256"), issue["review_baseline_sha256"])
                    or not hashes_equal(stored["candidate_sha256"], candidate_content_sha256(stored))
                ):
                    raise _error("inbox 候选的审核基线或内容摘要无效")
            elif "review_baseline_sha256" in candidate or has_hash:
                raise _error("旧问题的候选伪称拥有人工作业基线")
            validate_candidate_changes(
                candidate,
                effective_batch,
                issue["scope"],
                reject_duplicate_fields=has_baseline,
            )
            status = stored.get("status")
            if status not in {"pending_review_proposal", "stale", "withdrawn"}:
                raise _error("inbox 候选状态无效")
            if status == "pending_review_proposal" and (issue["status"] != "open" or candidate["baseline_revision"] != feedback_revision):
                raise _error("inbox 当前候选与反馈修订不一致")
            if status == "stale" and (issue["status"] != "open" or candidate["baseline_revision"] == feedback_revision):
                raise _error("inbox 过期候选状态无效")
            if status == "withdrawn" and issue["status"] != "withdrawn":
                raise _error("inbox 撤回候选状态无效")
    except AgentLinkError as error:
        raise _error("inbox 重学记录校验失败：" + error.message) from error


def _build_diffs(
    candidate: dict[str, Any], baseline: dict[str, Any], current: dict[str, Any], blockers: list[str]
) -> list[dict[str, Any]]:
    baseline_index = index_candidate_fields(baseline)
    current_index = index_candidate_fields(current)
    diffs: list[dict[str, Any]] = []
    try:
        writes = project_candidate_fields(
            candidate, baseline, candidate["scope"],
            reject_duplicate_fields=True,
        )
    except CandidateProjectionError as error:
        blockers.append(
            "duplicate_target_field" if error.code == "duplicate_change"
            else f"candidate_projection:{error.code}"
        )
        return []
    by_change: dict[int, list] = {}
    for write in writes:
        by_change.setdefault(write.change_index, []).append(write)
    for change_index, change in enumerate(candidate["changes"]):
        if change["change_type"] in {"step", "step_flow"}:
            action = change["action_type"].strip().casefold()
            if action in _DANGEROUS_ACTIONS:
                blockers.append(f"dangerous_action:{change['step_id']}:{action}")
            elif action not in _KNOWN_ACTIONS:
                blockers.append(f"unknown_action:{change['step_id']}:{action}")
        elif change["change_type"] == "steps_add":
            for step in change["steps"]:
                action = step["action_type"].strip().casefold()
                if action in _DANGEROUS_ACTIONS:
                    blockers.append(f"dangerous_action:{step['step_id']}:{action}")
                elif action not in _KNOWN_ACTIONS:
                    blockers.append(f"unknown_action:{step['step_id']}:{action}")
        proposed = by_change.get(change_index, [])
        if not proposed:
            blockers.append(f"candidate_projection:empty:{change_index}")
            continue
        no_effect = all(
            baseline_index.get(
                (item.target_type, item.target_id, item.field), _MISSING
            ) == item.proposed
            for item in proposed
        )
        for item in proposed:
            target_type, target_id, field, value = (
                item.target_type, item.target_id, item.field, item.proposed
            )
            key = (target_type, target_id, field)
            baseline_value = baseline_index.get(key, _MISSING)
            current_value = current_index.get(key, _MISSING)
            entity_addition = field == "entity" and baseline_value is _MISSING and current_value is _MISSING
            if baseline_value is _MISSING or current_value is _MISSING:
                if not entity_addition:
                    blockers.append(f"reference_drift:{target_type}:{target_id}:{field}")
                baseline_value = None if baseline_value is _MISSING else baseline_value
                current_value = None if current_value is _MISSING else current_value
            diffs.append({
                "target_type": target_type, "target_id": target_id, "field": field,
                "baseline": deepcopy(baseline_value), "current": deepcopy(current_value),
                "proposed": deepcopy(value),
            })
        if no_effect:
            item = proposed[0]
            blockers.append(
                f"no_effect:{item.target_type}:{item.target_id}:{change['change_type']}"
            )
    return diffs


_MISSING = object()


def _index(batch: dict[str, Any]) -> dict[tuple[str, str, str], Any]:
    return index_candidate_fields(batch)


def _required_text(value: Any, name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _error(f"{name} is invalid")
    return value.strip()


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 1:
        raise _error(f"{name} 必须是正整数")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise _error(f"{name} 必须是非负整数")
    return value


def _error(message: str):
    from .workspace import DesktopReviewError
    return DesktopReviewError(message)
