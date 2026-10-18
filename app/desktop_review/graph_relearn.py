"""图草稿重学请求、比较与人工采用。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.agent_link.contracts import canonical_hash
from app.agent_link.feedback_view import compact_feedback_view
from app.agent_link.graph_contract import GraphContractError, apply_graph_operations, graph_issue_id, validate_graph_operations, validate_graph_scope
from app.agent_link.review_baseline import candidate_content_sha256, hashes_equal

from .graph_revision import GraphRevisionService
from .workspace import DesktopReviewError


class GraphRelearnService:
    def __init__(self, facade: Any):
        self._facade = facade
        self._graphs = GraphRevisionService(facade)

    def request(self, logical_workflow_id: str, expected_revision: int, expected_graph_sha256: str, expected_feedback_revision: int, scope: dict, message: str, idempotency_key: str) -> dict[str, Any]:
        current = self._graphs.load(logical_workflow_id, None)
        self._reject_action_only(current)
        self._assert_graph_cas(current, expected_revision, expected_graph_sha256)
        try: checked_scope = validate_graph_scope(scope, current["graph"])
        except GraphContractError as error: raise DesktopReviewError(str(error)) from error
        refs = current["source_refs"]
        if isinstance(expected_feedback_revision, bool) or not isinstance(expected_feedback_revision, int) or expected_feedback_revision < 0:
            raise DesktopReviewError("expected_feedback_revision 必须是非负整数")
        feedback_revision = expected_feedback_revision
        baseline = {
            "contract_version": "desktop_graph_review_baseline_v1",
            "task_id": refs["task_id"], "batch_id": refs["batch_id"],
            "logical_workflow_id": current["logical_workflow_id"],
            "revision": current["revision"], "graph_sha256": current["content_sha256"],
            "snapshot": deepcopy(current),
        }
        issue_id = graph_issue_id(
            logical_workflow_id=logical_workflow_id, graph_revision=expected_revision,
            graph_sha256=expected_graph_sha256, feedback_revision=expected_feedback_revision,
            scope=checked_scope, message=message,
        )
        receipt = self._facade._reviewer("record_feedback", {
            "task_id": refs["task_id"], "batch_id": refs["batch_id"],
            "idempotency_key": idempotency_key, "expected_revision": feedback_revision,
            "notes": [], "issues": [{"issue_id": issue_id, "scope": checked_scope,
            "message": message, "review_baseline": baseline}],
        })
        view = self._view(refs["task_id"], refs["batch_id"])
        issue = next((item for item in view["issues"] if item.get("issue_id") == issue_id), None)
        if issue is None or receipt.get("revision") != feedback_revision + 1:
            raise DesktopReviewError("图重学问题未按预期持久化")
        return {"receipt": receipt, "issue": issue, **view}

    def feedback(
        self,
        logical_workflow_id: str,
        expected_revision: int,
        expected_graph_sha256: str,
    ) -> dict[str, Any]:
        """返回当前图身份下、只属于该 logical workflow 的只读反馈。"""

        current = self._graphs.load(logical_workflow_id, None)
        self._reject_action_only(current)
        self._assert_graph_cas(current, expected_revision, expected_graph_sha256)
        refs = current["source_refs"]
        detail = self._detail(refs["task_id"], refs["batch_id"])
        graph_issues = []
        for item in detail["issues"]:
            if not isinstance(item, dict):
                continue
            baseline = item.get("review_baseline")
            if (
                not isinstance(baseline, dict)
                or baseline.get("contract_version")
                != "desktop_graph_review_baseline_v1"
                or baseline.get("logical_workflow_id") != logical_workflow_id
            ):
                continue
            graph_issues.append(deepcopy(item))
        issue_ids = {
            item["issue_id"]
            for item in graph_issues
            if isinstance(item.get("issue_id"), str)
        }
        graph_candidates = [
            deepcopy(item)
            for item in detail["candidates"]
            if isinstance(item, dict)
            and item.get("contract_version") == "agent_link_graph_candidate_v1"
            and item.get("logical_workflow_id") == logical_workflow_id
            and item.get("issue_id") in issue_ids
        ]
        compact = compact_feedback_view(
            {
                "contract_version": "agent_link_v1",
                "batch_id": refs["batch_id"],
                "revision": len(detail["feedback_history"]),
                "notes": [],
                "issues": graph_issues,
                "candidates": graph_candidates,
                "staging_only": True,
            }
        )
        issues = compact["issues"]
        issue_by_id = {item["issue_id"]: item for item in issues}
        for issue in issues:
            baseline = issue["review_baseline_view"]
            if issue.get("status") == "withdrawn":
                graph_status = "withdrawn"
            elif (
                baseline.get("revision") != current["revision"]
                or baseline.get("graph_sha256") != current["content_sha256"]
            ):
                graph_status = "stale"
            else:
                graph_status = "open"
            issue["graph_status"] = graph_status
        for candidate in compact["candidates"]:
            issue = issue_by_id[candidate["issue_id"]]
            baseline = issue["review_baseline_view"]
            if (
                issue["graph_status"] == "withdrawn"
                or candidate.get("status") == "withdrawn"
            ):
                graph_status = "withdrawn"
            elif any(
                (
                    candidate.get("review_baseline_sha256")
                    != issue.get("review_baseline_sha256"),
                    candidate.get("baseline_graph_sha256")
                    != baseline.get("graph_sha256"),
                    candidate.get("scope") != issue.get("scope"),
                )
            ):
                graph_status = "blocked"
            elif (
                issue["graph_status"] == "stale"
                or candidate.get("status") != "pending_review_proposal"
            ):
                graph_status = "stale"
            else:
                graph_status = "pending"
            candidate["graph_status"] = graph_status
        return {
            "contract_version": "desktop_graph_relearn_feedback_v1",
            "logical_workflow_id": logical_workflow_id,
            "graph_revision": current["revision"],
            "graph_sha256": current["content_sha256"],
            "feedback_revision": compact["revision"],
            "issues": issues,
            "candidates": compact["candidates"],
            "staging_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }

    def compare(self, logical_workflow_id: str, expected_revision: int, expected_graph_sha256: str, candidate_id: str) -> dict[str, Any]:
        current = self._graphs.load(logical_workflow_id, None)
        self._reject_action_only(current)
        refs = current["source_refs"]
        detail = self._detail(refs["task_id"], refs["batch_id"])
        candidate = next((item for item in detail["candidates"] if item.get("candidate_id") == candidate_id), None)
        if candidate is None: raise DesktopReviewError("图重学候选不存在")
        issue = next((item for item in detail["issues"] if item.get("issue_id") == candidate.get("issue_id")), None)
        if issue is None or issue.get("review_baseline", {}).get("contract_version") != "desktop_graph_review_baseline_v1":
            raise DesktopReviewError("候选不是图修订候选")
        baseline = issue["review_baseline"]
        candidate_sha = candidate_content_sha256(candidate)
        status = "current"
        if issue.get("status") == "withdrawn" or candidate.get("status") == "withdrawn": status = "withdrawn"
        elif candidate.get("status") != "pending_review_proposal": status = "stale"
        elif any((current["revision"] != expected_revision, current["content_sha256"] != expected_graph_sha256,
                  current["revision"] != baseline["revision"], current["content_sha256"] != baseline["graph_sha256"])): status = "stale"
        elif any((candidate.get("contract_version") != "agent_link_graph_candidate_v1",
                  candidate.get("logical_workflow_id") != logical_workflow_id,
                  candidate.get("baseline_graph_sha256") != baseline["graph_sha256"],
                  candidate.get("review_baseline_sha256") != issue.get("review_baseline_sha256"))): status = "blocked"
        try:
            operations = validate_graph_operations(candidate.get("changes"), baseline["snapshot"]["graph"], issue["scope"])
            projected = apply_graph_operations(baseline["snapshot"]["graph"], operations)
        except GraphContractError as error:
            raise DesktopReviewError("图重学候选操作无效") from error
        return {
            "contract_version": "desktop_graph_relearn_comparison_v1", "status": status,
            "logical_workflow_id": logical_workflow_id, "candidate_id": candidate_id,
            "candidate_sha256": candidate_sha, "review_baseline_sha256": issue["review_baseline_sha256"],
            "baseline_graph_sha256": baseline["graph_sha256"], "current_graph_sha256": current["content_sha256"],
            "operations": operations,
            "operation_previews": self._operation_previews(
                baseline["snapshot"]["graph"], projected, operations,
            ),
            "changed": projected != baseline["snapshot"]["graph"],
        }

    def adopt(self, logical_workflow_id: str, expected_revision: int, expected_graph_sha256: str, candidate_id: str, expected_candidate_sha256: str, expected_review_baseline_sha256: str, idempotency_key: str) -> dict[str, Any]:
        current = self._graphs.load(logical_workflow_id, None)
        self._reject_action_only(current)
        adoption_request = {
            "logical_workflow_id": logical_workflow_id, "expected_revision": expected_revision,
            "expected_graph_sha256": expected_graph_sha256, "candidate_id": candidate_id,
            "expected_candidate_sha256": expected_candidate_sha256,
            "expected_review_baseline_sha256": expected_review_baseline_sha256,
            "idempotency_key": idempotency_key,
        }
        duplicate = self._graphs.find_committed_adoption(
            logical_workflow_id, idempotency_key, canonical_hash(adoption_request),
        )
        if duplicate is not None:
            return duplicate
        compared = self.compare(logical_workflow_id, expected_revision, expected_graph_sha256, candidate_id)
        if compared["status"] != "current":
            raise DesktopReviewError("图重学候选不是当前可采用状态")
        if not hashes_equal(compared["candidate_sha256"], expected_candidate_sha256) or not hashes_equal(compared["review_baseline_sha256"], expected_review_baseline_sha256):
            raise DesktopReviewError("图重学候选或基线摘要不匹配")
        current = self._graphs.load(logical_workflow_id, None)
        detail = self._detail(current["source_refs"]["task_id"], current["source_refs"]["batch_id"])
        candidate = next(item for item in detail["candidates"] if item["candidate_id"] == candidate_id)
        issue = next(item for item in detail["issues"] if item["issue_id"] == candidate["issue_id"])
        adoption = {
            "candidate": deepcopy(candidate), "candidate_sha256": expected_candidate_sha256,
            "issue_id": candidate["issue_id"], "baseline_graph_sha256": expected_graph_sha256,
            "review_baseline_sha256": expected_review_baseline_sha256,
            "request_sha256": canonical_hash(adoption_request),
            "issue": {key: deepcopy(issue[key]) for key in ("issue_id", "scope", "message", "baseline_revision")},
        }
        return self._graphs.adopt_candidate(
            logical_workflow_id, expected_revision, expected_graph_sha256,
            compared["operations"], candidate["scope"], idempotency_key, adoption,
        )

    @staticmethod
    def _reject_action_only(current: dict[str, Any]) -> None:
        if current.get("source_refs", {}).get("kind") == "recorded_actions":
            raise DesktopReviewError("纯动作图可查看、编辑并供 Agent 读取，但旧批次反馈重学暂不支持")

    def _detail(self, task_id: str, batch_id: str) -> dict[str, Any]:
        detail = self._facade._reviewer("get_batch", {"task_id": task_id, "batch_id": batch_id})
        if not all(isinstance(detail.get(key), list) for key in ("feedback_history", "issues", "candidates")):
            raise DesktopReviewError("inbox 图重学详情无效")
        return detail

    def _view(self, task_id: str, batch_id: str) -> dict[str, Any]:
        detail = self._detail(task_id, batch_id)
        return compact_feedback_view({
            "contract_version": "agent_link_v1", "batch_id": batch_id,
            "revision": len(detail["feedback_history"]), "notes": [],
            "issues": detail["issues"], "candidates": detail["candidates"], "staging_only": True,
        })

    @staticmethod
    def _operation_previews(
        baseline_graph: dict[str, Any],
        projected_graph: dict[str, Any],
        operations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        baseline_nodes = {item["node_id"]: item for item in baseline_graph["nodes"]}
        projected_nodes = {item["node_id"]: item for item in projected_graph["nodes"]}
        baseline_edges = {item["edge_id"]: item for item in baseline_graph["edges"]}
        projected_edges = {item["edge_id"]: item for item in projected_graph["edges"]}
        previews = []
        for operation in operations:
            operation_type = operation["type"]
            extra_identity = {}
            if operation_type == "update_node_meaning":
                identity, field = operation["node_id"], "display_name"
                before, after = baseline_nodes[identity][field], projected_nodes[identity][field]
            elif operation_type == "update_node_recognition_text":
                identity, field = operation["node_id"], "recognition_anchor"
                before = baseline_nodes[identity].get(field)
                after = projected_nodes[identity][field]
            elif operation_type == "update_region_bbox":
                identity, field = operation["node_id"], "region_bbox"
                region_id = operation["region_id"]
                extra_identity["region_id"] = region_id
                before = next(
                    item["bbox"] for item in baseline_nodes[identity]["regions"]
                    if item["region_id"] == region_id
                )
                after = next(
                    item["bbox"] for item in projected_nodes[identity]["regions"]
                    if item["region_id"] == region_id
                )
            elif operation_type == "update_edge_target":
                identity, field = operation["edge_id"], "target_node_id"
                before, after = baseline_edges[identity][field], projected_edges[identity][field]
            else:
                identity, field = operation["edge_id"], "semantics"
                fields = (
                    "preconditions",
                    "success_conditions",
                    "failure_conditions",
                    "external_relationships",
                )
                before = {key: deepcopy(baseline_edges[identity][key]) for key in fields}
                after = {key: deepcopy(projected_edges[identity][key]) for key in fields}
            previews.append(
                {
                    "type": operation_type,
                    "target_id": identity,
                    "field": field,
                    "before": deepcopy(before),
                    "after": deepcopy(after),
                    **extra_identity,
                }
            )
        return previews

    @staticmethod
    def _assert_graph_cas(current: dict[str, Any], revision: int, digest: str) -> None:
        if current["revision"] != revision or current["content_sha256"] != digest:
            raise DesktopReviewError("stale_revision: 图草稿修订或内容摘要已过期")
