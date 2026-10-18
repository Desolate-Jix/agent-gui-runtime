"""持久保存只属于本地 reviewer 的候选拒绝决定。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from app.agent_link.contracts import canonical_hash
from app.agent_link.review_baseline import candidate_content_sha256

from .external_mapping import canonical_json_bytes
from .relearn_adoption import _candidate_projection, _issue_projection
from .workspace import DesktopReviewError, _atomic_write_bytes


_DOCUMENT_CONTRACT = "desktop_candidate_decisions_v1"
_RECORD_CONTRACT = "desktop_candidate_rejection_record_v1"
_RECEIPT_CONTRACT = "desktop_candidate_rejection_receipt_v1"
_DOCUMENT_KEYS = {
    "contract_version", "task_id", "batch_id", "source_ref",
    "decision_revision", "records",
}
_RECORD_KEYS = {
    "contract_version", "task_id", "batch_id", "source_ref",
    "workspace_ref", "workspace_revision", "decision_revision",
    "candidate_id", "candidate_sha256", "issue_id",
    "review_baseline_sha256", "scope", "reason",
    "idempotency_key_sha256", "request_sha256",
    "candidate", "issue", "record_sha256",
}
_WORKSPACE_REF_KEYS = {
    "revision", "workspace_path", "workspace_sha256",
    "workflow_review_sha256",
}


class CandidateDecisionService:
    def __init__(self, facade: Any) -> None:
        self._facade = facade

    def reject(
        self,
        task_id: Any,
        batch_id: Any,
        expected_revision: Any,
        candidate_id: Any,
        expected_candidate_sha256: Any,
        expected_review_baseline_sha256: Any,
        expected_decision_revision: Any,
        reason: Any,
        idempotency_key: Any,
    ) -> dict[str, Any]:
        task = _text(task_id, "task_id", 4000)
        batch = _text(batch_id, "batch_id", 160)
        revision = _positive_int(expected_revision, "expected_revision")
        candidate_identifier = _text(candidate_id, "candidate_id", 160)
        candidate_sha = _digest(expected_candidate_sha256, "expected_candidate_sha256")
        baseline_sha = _optional_digest(
            expected_review_baseline_sha256,
            "expected_review_baseline_sha256",
        )
        decision_revision = _non_negative_int(
            expected_decision_revision, "expected_decision_revision"
        )
        checked_reason = _text(reason, "reason", 4000)
        key = _text(idempotency_key, "idempotency_key", 160)
        key_sha = hashlib.sha256(key.encode("utf-8")).hexdigest()
        request_sha = _request_sha(
            task, batch, revision, candidate_identifier, candidate_sha,
            baseline_sha, decision_revision, checked_reason, key_sha,
        )

        current = self._facade.load_batch(task, batch)
        if current.get("revision", 0) < 1:
            raise DesktopReviewError("拒绝必须绑定已保存人工修订")
        detail = self._detail(current)
        document = self._load_document(current, detail)
        matching_key = [
            record for record in document["records"]
            if record["idempotency_key_sha256"] == key_sha
        ]
        if matching_key:
            if len(matching_key) != 1 or matching_key[0]["request_sha256"] != request_sha:
                raise DesktopReviewError("idempotency_conflict: 同一拒绝 key 已用于不同请求")
            return _receipt(matching_key[0], current, document["decision_revision"])

        if current["revision"] != revision:
            raise DesktopReviewError("stale_revision: 人工作业修订已变化")
        if document["decision_revision"] != decision_revision:
            raise DesktopReviewError("stale_decision_revision: 本地决定修订已变化")
        if any(
            record["candidate_id"] == candidate_identifier
            for record in document["records"]
        ):
            raise DesktopReviewError("candidate_already_rejected: 候选已有本地拒绝决定")
        self._reject_if_adopted(current, candidate_identifier, candidate_sha)

        candidate = next(
            (item for item in detail["candidates"] if item.get("candidate_id") == candidate_identifier),
            None,
        )
        if candidate is None:
            raise DesktopReviewError("candidate_not_found: 候选不存在于当前批次")
        issue = next(
            (item for item in detail["issues"] if item.get("issue_id") == candidate.get("issue_id")),
            None,
        )
        if issue is None:
            raise DesktopReviewError("candidate_issue_missing: 候选问题引用无效")
        if issue.get("status") == "withdrawn" or candidate.get("status") == "withdrawn":
            raise DesktopReviewError("candidate_withdrawn: 已撤回候选不能新增本地拒绝")
        actual_candidate_sha = candidate_content_sha256(candidate)
        if candidate_sha != actual_candidate_sha:
            raise DesktopReviewError("candidate_hash_mismatch: 候选摘要不匹配")
        actual_baseline_sha = issue.get("review_baseline_sha256")
        if candidate.get("review_baseline_sha256") != actual_baseline_sha:
            raise DesktopReviewError("candidate_baseline_invalid: 候选与问题基线不一致")
        if baseline_sha != actual_baseline_sha:
            raise DesktopReviewError("baseline_hash_mismatch: 人工基线摘要不匹配")

        next_revision = decision_revision + 1
        record = {
            "contract_version": _RECORD_CONTRACT,
            "task_id": task,
            "batch_id": batch,
            "source_ref": current["source_ref"],
            "workspace_ref": self._facade._parent_reference(current),
            "workspace_revision": revision,
            "decision_revision": next_revision,
            "candidate_id": candidate_identifier,
            "candidate_sha256": candidate_sha,
            "issue_id": issue["issue_id"],
            "review_baseline_sha256": baseline_sha,
            "scope": deepcopy(issue["scope"]),
            "reason": checked_reason,
            "idempotency_key_sha256": key_sha,
            "request_sha256": request_sha,
            "candidate": _candidate_projection(candidate),
            "issue": _issue_projection(issue),
        }
        record["record_sha256"] = canonical_hash(record)
        updated = {
            **document,
            "decision_revision": next_revision,
            "records": [*deepcopy(document["records"]), record],
        }
        self._validate_document(updated, current, detail)
        self._publish(updated)
        verified = self._load_document(current, detail)
        saved = verified["records"][-1]
        if saved != record:
            raise DesktopReviewError("本地拒绝原子提交后内容不一致")
        return _receipt(saved, current, verified["decision_revision"])

    def load(
        self,
        snapshot: dict[str, Any],
        detail: dict[str, Any] | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        checked_detail = self._detail(snapshot) if detail is None else detail
        document = self._load_document(snapshot, checked_detail)
        return document["decision_revision"], deepcopy(document["records"])

    def is_rejected(
        self,
        snapshot: dict[str, Any],
        detail: dict[str, Any],
        candidate_id: str,
        candidate_sha256: str,
    ) -> bool:
        _, records = self.load(snapshot, detail)
        return any(
            record["candidate_id"] == candidate_id
            and record["candidate_sha256"] == candidate_sha256
            for record in records
        )

    def _detail(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        from .relearn import RelearnReviewService

        return RelearnReviewService(self._facade)._detail(snapshot)

    def _path(self, task_id: str, batch_id: str) -> Path:
        return self._facade._workspace_dir(task_id, batch_id) / "candidate-decisions.json"

    def _empty(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "contract_version": _DOCUMENT_CONTRACT,
            "task_id": snapshot["task_id"],
            "batch_id": snapshot["batch_id"],
            "source_ref": snapshot["source_ref"],
            "decision_revision": 0,
            "records": [],
        }

    def _load_document(
        self,
        snapshot: dict[str, Any],
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        path = self._path(snapshot["task_id"], snapshot["batch_id"])
        if not path.exists():
            return self._empty(snapshot)
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DesktopReviewError("本地候选决定文档损坏，未自动重置") from error
        return self._validate_document(document, snapshot, detail)

    def _validate_document(
        self,
        document: Any,
        snapshot: dict[str, Any],
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            not isinstance(document, dict)
            or set(document) != _DOCUMENT_KEYS
            or document.get("contract_version") != _DOCUMENT_CONTRACT
            or document.get("task_id") != snapshot["task_id"]
            or document.get("batch_id") != snapshot["batch_id"]
            or document.get("source_ref") != snapshot["source_ref"]
        ):
            raise DesktopReviewError("本地候选决定文档契约或身份无效")
        revision = _non_negative_int(
            document.get("decision_revision"), "decision_revision"
        )
        records = document.get("records")
        if not isinstance(records, list) or len(records) != revision:
            raise DesktopReviewError("本地候选决定记录序列不连续")
        chain = self._facade._validated_revision_chain(snapshot)
        live_candidates = {
            item.get("candidate_id"): item
            for item in detail["candidates"] if isinstance(item, dict)
        }
        live_issues = {
            item.get("issue_id"): item
            for item in detail["issues"] if isinstance(item, dict)
        }
        seen_keys: set[str] = set()
        seen_candidates: set[str] = set()
        for index, record in enumerate(records, 1):
            self._validate_record(
                record, index, snapshot, chain, live_candidates, live_issues
            )
            if record["idempotency_key_sha256"] in seen_keys:
                raise DesktopReviewError("本地候选决定幂等 key 重复")
            if record["candidate_id"] in seen_candidates:
                raise DesktopReviewError("本地候选决定重复拒绝同一候选")
            seen_keys.add(record["idempotency_key_sha256"])
            seen_candidates.add(record["candidate_id"])
        return deepcopy(document)

    def _validate_record(
        self,
        record: Any,
        index: int,
        current: dict[str, Any],
        chain: list[dict[str, Any]],
        live_candidates: dict[str, dict[str, Any]],
        live_issues: dict[str, dict[str, Any]],
    ) -> None:
        if (
            not isinstance(record, dict)
            or set(record) != _RECORD_KEYS
            or record.get("contract_version") != _RECORD_CONTRACT
            or record.get("task_id") != current["task_id"]
            or record.get("batch_id") != current["batch_id"]
            or record.get("source_ref") != current["source_ref"]
        ):
            raise DesktopReviewError("本地候选拒绝记录契约或身份无效")
        record_revision = _positive_int(
            record.get("decision_revision"), "decision_revision"
        )
        if record_revision != index:
            raise DesktopReviewError("本地候选拒绝记录序号不连续")
        workspace_revision = _positive_int(
            record.get("workspace_revision"), "workspace_revision"
        )
        workspace_ref = record.get("workspace_ref")
        if (
            not isinstance(workspace_ref, dict)
            or set(workspace_ref) != _WORKSPACE_REF_KEYS
            or not isinstance(workspace_ref.get("workspace_path"), str)
        ):
            raise DesktopReviewError("本地候选拒绝的工作区引用无效")
        reference_revision = _positive_int(
            workspace_ref.get("revision"), "workspace_ref.revision"
        )
        if reference_revision != workspace_revision:
            raise DesktopReviewError("本地候选拒绝的工作区引用修订不一致")
        _digest(workspace_ref.get("workspace_sha256"), "workspace_sha256")
        _digest(
            workspace_ref.get("workflow_review_sha256"),
            "workflow_review_sha256",
        )
        matched = [
            saved for saved in chain
            if saved["revision"] == workspace_revision
            and self._facade._parent_reference(saved) == workspace_ref
        ]
        if len(matched) != 1:
            raise DesktopReviewError("本地候选拒绝未绑定当前可达的确切工作区修订")
        candidate_id = _text(record.get("candidate_id"), "candidate_id", 160)
        issue_id = _text(record.get("issue_id"), "issue_id", 160)
        candidate_sha = _digest(record.get("candidate_sha256"), "candidate_sha256")
        baseline_sha = _optional_digest(
            record.get("review_baseline_sha256"), "review_baseline_sha256"
        )
        reason = _text(record.get("reason"), "reason", 4000)
        key_sha = _digest(
            record.get("idempotency_key_sha256"), "idempotency_key_sha256"
        )
        request_sha = _digest(record.get("request_sha256"), "request_sha256")
        record_sha = _digest(record.get("record_sha256"), "record_sha256")
        if not isinstance(record.get("scope"), dict):
            raise DesktopReviewError("本地候选拒绝范围无效")
        candidate = record.get("candidate")
        issue = record.get("issue")
        if not isinstance(candidate, dict) or not isinstance(issue, dict):
            raise DesktopReviewError("本地候选拒绝的候选或问题封存无效")
        if candidate != _candidate_projection(candidate) or issue != _issue_projection(issue):
            raise DesktopReviewError("本地候选拒绝封存含有可变状态字段")
        if (
            candidate.get("candidate_id") != candidate_id
            or candidate.get("issue_id") != issue_id
            or issue.get("issue_id") != issue_id
            or issue.get("scope") != record["scope"]
            or candidate.get("review_baseline_sha256") != baseline_sha
            or issue.get("review_baseline_sha256") != baseline_sha
        ):
            raise DesktopReviewError("本地候选拒绝封存身份、范围或基线无效")
        if candidate_content_sha256(candidate) != candidate_sha:
            raise DesktopReviewError("本地候选拒绝候选摘要无法重派生")
        if baseline_sha is not None:
            baseline = issue.get("review_baseline")
            if not isinstance(baseline, dict):
                raise DesktopReviewError("本地候选拒绝基线无效")
            baseline_revision = _positive_int(
                baseline.get("workspace_revision"),
                "review_baseline.workspace_revision",
            )
            if baseline_revision > workspace_revision:
                raise DesktopReviewError("本地候选拒绝不能早于候选的人工基线修订")
            baseline_snapshots = [
                saved for saved in chain
                if saved["revision"] == baseline_revision
            ]
            if (
                len(baseline_snapshots) != 1
                or baseline.get("task_id") != current["task_id"]
                or baseline.get("source_ref") != current["source_ref"]
                or baseline.get("batch_sha256")
                != canonical_hash(baseline_snapshots[0]["batch"])
            ):
                raise DesktopReviewError("本地候选拒绝基线不是确切可达人工修订")
        live_candidate = live_candidates.get(candidate_id)
        live_issue = live_issues.get(issue_id)
        if live_candidate is None or _candidate_projection(live_candidate) != candidate:
            raise DesktopReviewError("本地候选拒绝与 inbox 候选不可变内容不一致")
        if live_issue is None or _issue_projection(live_issue) != issue:
            raise DesktopReviewError("本地候选拒绝与 inbox 问题不可变内容不一致")
        expected_request_sha = _request_sha(
            current["task_id"], current["batch_id"], workspace_revision,
            candidate_id, candidate_sha, baseline_sha, index - 1,
            reason, key_sha,
        )
        if request_sha != expected_request_sha:
            raise DesktopReviewError("本地候选拒绝请求摘要无法重派生")
        content = {key: deepcopy(value) for key, value in record.items() if key != "record_sha256"}
        if record_sha != canonical_hash(content):
            raise DesktopReviewError("本地候选拒绝内容摘要不匹配")

    def _reject_if_adopted(
        self,
        current: dict[str, Any],
        candidate_id: str,
        candidate_sha256: str,
    ) -> None:
        for snapshot in self._facade._validated_revision_chain(current):
            origin = snapshot.get("relearn_adoption")
            if (
                isinstance(origin, dict)
                and origin.get("candidate_id") == candidate_id
                and origin.get("candidate_sha256") == candidate_sha256
            ):
                raise DesktopReviewError(
                    "candidate_already_adopted: 已采用候选不能伪装为本地拒绝"
                )

    def _publish(self, document: dict[str, Any]) -> None:
        path = self._path(document["task_id"], document["batch_id"])
        try:
            _atomic_write_bytes(path, canonical_json_bytes(document) + b"\n")
        except (OSError, ValueError, TypeError) as error:
            raise DesktopReviewError(
                "decision_persistence_failed: 本地候选拒绝未原子持久化"
            ) from error


def _receipt(
    record: dict[str, Any],
    current: dict[str, Any],
    current_decision_revision: int,
) -> dict[str, Any]:
    return {
        "contract_version": _RECEIPT_CONTRACT,
        "task_id": record["task_id"],
        "batch_id": record["batch_id"],
        "source_ref": record["source_ref"],
        "candidate_id": record["candidate_id"],
        "candidate_sha256": record["candidate_sha256"],
        "review_baseline_sha256": record["review_baseline_sha256"],
        "workspace_revision": record["workspace_revision"],
        "decision_revision": record["decision_revision"],
        "current_revision": current["revision"],
        "current_decision_revision": current_decision_revision,
        "reason": record["reason"],
        "record_sha256": record["record_sha256"],
        "staging_only": True,
    }


def _request_sha(
    task_id: str,
    batch_id: str,
    workspace_revision: int,
    candidate_id: str,
    candidate_sha256: str,
    review_baseline_sha256: str | None,
    expected_decision_revision: int,
    reason: str,
    idempotency_key_sha256: str,
) -> str:
    return canonical_hash({
        "task_id": task_id,
        "batch_id": batch_id,
        "expected_revision": workspace_revision,
        "candidate_id": candidate_id,
        "expected_candidate_sha256": candidate_sha256,
        "expected_review_baseline_sha256": review_baseline_sha256,
        "expected_decision_revision": expected_decision_revision,
        "reason": reason,
        "idempotency_key_sha256": idempotency_key_sha256,
    })


def _text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise DesktopReviewError(f"{name} 无效")
    return value.strip()


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 1:
        raise DesktopReviewError(f"{name} 必须是正整数")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise DesktopReviewError(f"{name} 必须是非负整数")
    return value


def _digest(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DesktopReviewError(f"{name} 必须是 SHA-256")
    return value


def _optional_digest(value: Any, name: str) -> str | None:
    return None if value is None else _digest(value, name)
