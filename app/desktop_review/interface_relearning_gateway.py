"""同任务 Agent 的反馈与候选视图；不暴露本地文件或人工采用入口。"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib

from app.agent_link.interface_capability import INTERFACE_RELEARNING_CAPABILITY
from app.agent_link.contracts import AgentLinkError, MAX_LOCAL_PNG_BYTES
from .interface_relearning import InterfaceRelearningService
from .workspace import DesktopReviewError


def _envelope(**values):
    return {"contract_version": INTERFACE_RELEARNING_CAPABILITY["contract_version"], **values,
            "artifact_is_authorization": False, "execute_binding_enabled": False, "action_executed": False}


def _issue_view(issue):
    return {key: deepcopy(issue[key]) for key in (
        "issue_id", "interface_id", "baseline_revision", "baseline_content_sha256",
        "region_ids", "message", "status", "candidate_ids", "issue_sha256")}


class InterfaceRelearningGateway:
    def __init__(self, facade):
        self.facade = facade
        self.service = InterfaceRelearningService(facade)

    def list(self, allowed_task_id):
        return _envelope(issues=[_issue_view(issue) for issue in self.service.list(allowed_task_id)])

    def _owned(self, allowed_task_id, issue_id):
        issue = self.service.read(issue_id)
        if issue["task_id"] != allowed_task_id:
            raise AgentLinkError("not_found", "interface feedback was not found for this task")
        return issue

    def get(self, allowed_task_id, issue_id):
        issue = self._owned(allowed_task_id, issue_id)
        version_id = "interface-version-" + issue["baseline_content_sha256"]
        baseline = self.facade.get_interface_memory(allowed_task_id, issue["interface_id"], version_id)
        evidence = self.facade.load_interface_content_evidence(issue["interface_id"], version_id)
        with self.facade._artifact_file(evidence["image_path"], "界面重学原图").open("rb") as source:
            raw = source.read(MAX_LOCAL_PNG_BYTES + 1)
        if len(raw) > MAX_LOCAL_PNG_BYTES or hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
            raise DesktopReviewError("interface_relearning_evidence_invalid")
        candidates = []
        for candidate_id in issue["candidate_ids"]:
            candidate = self.service.compare(issue_id, candidate_id)["candidate"]
            candidates.append(self._candidate_view(candidate))
        return _envelope(issue=_issue_view(issue), baseline=baseline, candidates=candidates, screenshot={
            "mime_type": "image/png", "sha256": evidence["sha256"],
            "width": evidence["width"], "height": evidence["height"],
            "png_base64": base64.b64encode(raw).decode("ascii")})

    @staticmethod
    def _candidate_view(candidate):
        return {key: deepcopy(candidate[key]) for key in (
            "candidate_id", "issue_id", "interface_id", "baseline_content_sha256",
            "content", "content_sha256", "candidate_record_sha256")}

    def submit(self, allowed_task_id, issue_id, expected_baseline_sha256, changes, idempotency_key):
        self._owned(allowed_task_id, issue_id)
        candidate = self.service.submit_candidate(allowed_task_id, issue_id,
            expected_baseline_sha256, changes, idempotency_key)
        return _envelope(candidate=self._candidate_view(candidate))
