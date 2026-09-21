"""把已比较的重学候选明确保存为新的待审人工修订。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

from app.agent_link.contracts import canonical_hash
from app.agent_link.candidate_projection import (
    CandidateProjectionError,
    apply_candidate_diffs,
)
from app.agent_link.review_baseline import candidate_content_sha256

from .relearn import RelearnReviewService, _build_diffs


_ORIGIN_CONTRACT = "desktop_relearn_adoption_origin_v1"
_RECEIPT_CONTRACT = "desktop_relearn_adoption_receipt_v1"
_ORIGIN_KEYS = {
    "contract_version", "idempotency_key_sha256", "request_sha256",
    "candidate_id", "candidate_sha256", "issue_id", "review_baseline_sha256",
    "scope", "candidate", "issue", "comparison",
}


class RelearnAdoptionService:
    def __init__(self, facade: Any) -> None:
        self._facade = facade

    def adopt(
        self,
        task_id: Any,
        batch_id: Any,
        expected_revision: Any,
        candidate_id: Any,
        expected_candidate_sha256: Any,
        expected_review_baseline_sha256: Any,
        idempotency_key: Any,
    ) -> dict[str, Any]:
        task = _text(task_id, "task_id", 4000)
        batch = _text(batch_id, "batch_id", 160)
        revision = _positive_int(expected_revision, "expected_revision")
        candidate_identifier = _text(candidate_id, "candidate_id", 160)
        candidate_sha = _digest(expected_candidate_sha256, "expected_candidate_sha256")
        baseline_sha = _digest(expected_review_baseline_sha256, "expected_review_baseline_sha256")
        key = _text(idempotency_key, "idempotency_key", 160)
        key_sha = hashlib.sha256(key.encode("utf-8")).hexdigest()
        request = {
            "task_id": task, "batch_id": batch, "expected_revision": revision,
            "candidate_id": candidate_identifier,
            "expected_candidate_sha256": candidate_sha,
            "expected_review_baseline_sha256": baseline_sha,
            "idempotency_key_sha256": key_sha,
        }
        request_sha = canonical_hash(request)

        current = self._facade.load_batch(task, batch)
        if current.get("revision", 0) < 1:
            raise _error("采用必须绑定已保存人工修订")
        chain = self._facade._validated_revision_chain(current)
        committed = [
            snapshot for snapshot in chain
            if isinstance(snapshot.get("relearn_adoption"), dict)
            and snapshot["relearn_adoption"].get("idempotency_key_sha256") == key_sha
        ]
        if committed:
            if len(committed) != 1 or committed[0]["relearn_adoption"].get("request_sha256") != request_sha:
                raise _error("idempotency_conflict: 同一采用 key 已用于不同请求")
            return _receipt(committed[0], current)

        from .candidate_decisions import CandidateDecisionService
        _, decisions = CandidateDecisionService(self._facade).load(current)
        if any(
            record["candidate_id"] == candidate_identifier
            and record["candidate_sha256"] == candidate_sha
            for record in decisions
        ):
            raise _error("candidate_locally_rejected: 已拒绝候选不能采用")

        if current["revision"] != revision:
            raise _error("stale_revision: 人工作业修订已变化")
        comparison = RelearnReviewService(self._facade).compare(
            task, batch, revision, candidate_identifier
        )
        if comparison.get("status") != "current" or comparison.get("blocked_reasons") != []:
            raise _error("candidate_not_current: 候选不是无阻断的当前比较")
        if comparison.get("candidate_sha256") != candidate_sha:
            raise _error("candidate_hash_mismatch: 候选摘要与比较绑定不一致")
        if comparison.get("review_baseline_sha256") != baseline_sha:
            raise _error("baseline_hash_mismatch: 人工基线摘要与比较绑定不一致")

        detail = RelearnReviewService(self._facade)._detail(current)
        candidate = next(
            (item for item in detail["candidates"] if item["candidate_id"] == candidate_identifier),
            None,
        )
        if candidate is None:
            raise _error("candidate_not_found: 候选已不存在")
        issue = next(
            (item for item in detail["issues"] if item["issue_id"] == candidate["issue_id"]),
            None,
        )
        if issue is None:
            raise _error("candidate_issue_missing: 候选问题已不存在")
        sealed_candidate = _candidate_projection(candidate)
        sealed_issue = _issue_projection(issue)
        origin = {
            "contract_version": _ORIGIN_CONTRACT,
            "idempotency_key_sha256": key_sha,
            "request_sha256": request_sha,
            "candidate_id": candidate_identifier,
            "candidate_sha256": candidate_sha,
            "issue_id": issue["issue_id"],
            "review_baseline_sha256": baseline_sha,
            "scope": deepcopy(issue["scope"]),
            "candidate": sealed_candidate,
            "issue": sealed_issue,
            "comparison": deepcopy(comparison),
        }
        validate_adoption_origin_shape(origin)
        adopted_batch = _apply_diffs(current["batch"], comparison["diffs"])
        snapshot = self._facade._save_revision_locked(
            task, batch, revision, adopted_batch, relearn_adoption=origin
        )
        return _receipt(snapshot, snapshot)


def validate_adoption_origin_shape(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _ORIGIN_KEYS or value.get("contract_version") != _ORIGIN_CONTRACT:
        raise _error("重学采用来源契约无效")
    for name in ("idempotency_key_sha256", "request_sha256", "candidate_sha256", "review_baseline_sha256"):
        _digest(value.get(name), name)
    for name in ("candidate_id", "issue_id"):
        _text(value.get(name), name, 160)
    if not isinstance(value.get("scope"), dict) or set(value["scope"]) != {"interface_ids", "relationship_ids"}:
        raise _error("重学采用范围无效")
    if not isinstance(value.get("candidate"), dict) or not isinstance(value.get("issue"), dict):
        raise _error("重学采用候选或问题封存无效")
    comparison = value.get("comparison")
    required_comparison = {
        "contract_version", "task_id", "batch_id", "source_ref", "workspace_revision",
        "candidate_id", "candidate_sha256", "issue_id", "review_baseline_sha256",
        "baseline_workspace_revision", "status", "blocked_reasons", "diffs",
    }
    if not isinstance(comparison, dict) or set(comparison) != required_comparison:
        raise _error("重学采用比较封存无效")
    if comparison.get("contract_version") != "desktop_relearn_comparison_v1" or comparison.get("status") != "current" or comparison.get("blocked_reasons") != []:
        raise _error("重学采用比较不是无阻断 current")
    if type(comparison.get("workspace_revision")) is not int or type(comparison.get("baseline_workspace_revision")) is not int:
        raise _error("重学采用比较修订号必须是严格整数")


def validate_adoption_origin(facade: Any, child: dict[str, Any], parent: dict[str, Any]) -> None:
    origin = child.get("relearn_adoption")
    validate_adoption_origin_shape(origin)
    comparison = origin["comparison"]
    if any((
        comparison.get("task_id") != parent["task_id"],
        comparison.get("batch_id") != parent["batch_id"],
        comparison.get("source_ref") != parent["source_ref"],
        comparison.get("workspace_revision") != parent["revision"],
        comparison.get("baseline_workspace_revision") != parent["revision"],
        comparison.get("candidate_id") != origin["candidate_id"],
        comparison.get("candidate_sha256") != origin["candidate_sha256"],
        comparison.get("issue_id") != origin["issue_id"],
        comparison.get("review_baseline_sha256") != origin["review_baseline_sha256"],
    )):
        raise _error("重学采用比较身份与父修订不一致")
    candidate = origin["candidate"]
    issue = origin["issue"]
    baseline = issue.get("review_baseline") if isinstance(issue, dict) else None
    if (
        not isinstance(baseline, dict)
        or type(baseline.get("workspace_revision")) is not int
        or baseline["workspace_revision"] != parent["revision"]
        or baseline.get("task_id") != parent["task_id"]
        or baseline.get("source_ref") != parent["source_ref"]
        or baseline.get("batch_sha256") != canonical_hash(parent["batch"])
    ):
        raise _error("重学采用封存基线不是确切父人工修订")
    if candidate != _candidate_projection(candidate) or issue != _issue_projection(issue):
        raise _error("重学采用封存含有可变状态字段")
    if candidate.get("candidate_id") != origin["candidate_id"] or candidate.get("issue_id") != origin["issue_id"]:
        raise _error("重学采用候选封存身份无效")
    if issue.get("issue_id") != origin["issue_id"] or issue.get("scope") != origin["scope"]:
        raise _error("重学采用问题封存身份或范围无效")
    if issue.get("review_baseline_sha256") != origin["review_baseline_sha256"] or candidate.get("review_baseline_sha256") != origin["review_baseline_sha256"]:
        raise _error("重学采用封存基线不一致")
    if candidate_content_sha256(candidate) != origin["candidate_sha256"]:
        raise _error("重学采用候选封存摘要不匹配")
    expected_request_sha = canonical_hash({
        "task_id": parent["task_id"],
        "batch_id": parent["batch_id"],
        "expected_revision": parent["revision"],
        "candidate_id": origin["candidate_id"],
        "expected_candidate_sha256": origin["candidate_sha256"],
        "expected_review_baseline_sha256": origin["review_baseline_sha256"],
        "idempotency_key_sha256": origin["idempotency_key_sha256"],
    })
    if origin["request_sha256"] != expected_request_sha:
        raise _error("重学采用完整请求摘要无法从封存绑定重新派生")

    detail = RelearnReviewService(facade)._detail(parent)
    live_candidate = next((item for item in detail["candidates"] if item["candidate_id"] == origin["candidate_id"]), None)
    live_issue = next((item for item in detail["issues"] if item["issue_id"] == origin["issue_id"]), None)
    if live_candidate is None or _candidate_projection(live_candidate) != candidate:
        raise _error("重学采用候选不可变内容与 inbox 不一致")
    if live_issue is None or _issue_projection(live_issue) != issue:
        raise _error("重学采用问题不可变内容与 inbox 不一致")
    blockers: list[str] = []
    diffs = _build_diffs(candidate, parent["batch"], parent["batch"], blockers)
    if blockers or diffs != comparison["diffs"]:
        raise _error("重学采用比较无法从父内容重新派生")
    if _apply_diffs(parent["batch"], diffs) != child["batch"]:
        raise _error("重学采用子批次无法从父内容和候选重新派生")


def _candidate_projection(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in candidate.items()
        if key not in {"status", "candidate_sha256"}
    }


def _issue_projection(issue: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in issue.items() if key != "status"}


def _apply_diffs(batch: dict[str, Any], diffs: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return apply_candidate_diffs(batch, diffs)
    except CandidateProjectionError as error:
        raise _error("重学采用差异无效：" + error.message) from error


def _receipt(adopted: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    origin = adopted["relearn_adoption"]
    return {
        "contract_version": _RECEIPT_CONTRACT,
        "task_id": adopted["task_id"], "batch_id": adopted["batch_id"],
        "source_ref": adopted["source_ref"],
        "candidate_id": origin["candidate_id"],
        "candidate_sha256": origin["candidate_sha256"],
        "review_baseline_sha256": origin["review_baseline_sha256"],
        "previous_revision": adopted["revision"] - 1,
        "adopted_revision": adopted["revision"],
        "current_revision": current["revision"],
        "is_current": adopted["revision"] == current["revision"],
        "snapshot": deepcopy(adopted), "staging_only": True,
    }


def _text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _error(f"{name} 无效")
    return value.strip()


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 1:
        raise _error(f"{name} 必须是正整数")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise _error(f"{name} 必须是 SHA-256")
    return value


def _error(message: str):
    from .workspace import DesktopReviewError
    return DesktopReviewError(message)
