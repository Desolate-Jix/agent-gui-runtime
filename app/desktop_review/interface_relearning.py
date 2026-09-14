"""独立界面反馈重学：只记录候选，明确比较后才写入当前内容。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from functools import wraps
from uuid import uuid5, NAMESPACE_URL

from .interface_content import InterfaceContentService
from .workspace import DesktopReviewError, _atomic_write_bytes, _write_immutable
from .external_mapping import canonical_json_bytes

_CONTRACT = "desktop_interface_relearning_v1"
_STATE = "desktop_interface_relearning_state_v1"
_ID = re.compile(r"interface-[0-9a-f-]{36}\Z")
_ISSUE = re.compile(r"interface-issue-[0-9a-f-]{36}\Z")
_CANDIDATE = re.compile(r"interface-candidate-[0-9a-f-]{36}\Z")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")


def _storage_errors(method):
    @wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except OSError as error:
            raise DesktopReviewError("interface_relearning_persistence_failed") from error
    return call


class InterfaceRelearningService:
    def __init__(self, facade):
        self.facade = facade
        self.root = facade._workspace_root / "interface-relearning"
        self.registry = self.root / "registry.json"

    @_storage_errors
    def request(self, interface_id, expected_revision, expected_sha256, region_ids, message, idempotency_key):
        with self.facade._guard:
            key = self._key(idempotency_key)
            if (not isinstance(interface_id, str) or not _ID.fullmatch(interface_id)
                    or type(expected_revision) is not int or expected_revision < 1
                    or not self._sha(expected_sha256) or not isinstance(region_ids, list)
                    or any(not isinstance(x, str) or not x.strip() for x in region_ids)
                    or len(set(region_ids)) != len(region_ids)
                    or not isinstance(message, str) or not message.strip() or len(message) > 4000):
                raise DesktopReviewError("interface_relearning_arguments_invalid")
            request_sha = self._digest({"interface_id": interface_id, "revision": expected_revision, "sha": expected_sha256, "region_ids": region_ids, "message": message, "idempotency_key": key})
            index = self._registry()
            issue_id = "interface-issue-" + str(uuid5(NAMESPACE_URL, "issue:" + key))
            prior = index["issue_requests"].get(key)
            if prior is None and self._issue_path(issue_id).exists():
                existing = self._issue(issue_id)
                prior = {"request_sha256": existing["request_sha256"], "issue_id": issue_id}
            if prior:
                if prior["request_sha256"] != request_sha: raise DesktopReviewError("interface_relearning_idempotency_conflict")
                if prior["issue_id"] != issue_id:
                    raise DesktopReviewError("interface_relearning_registry_invalid")
                self._ensure_state(issue_id)
                if issue_id not in index["issue_ids"]:
                    index["issue_ids"].append(issue_id)
                index["issue_requests"][key] = prior
                self._write_registry(index)
                return self.read(prior["issue_id"])
            current = self._content(interface_id)
            if type(expected_revision) is not int or expected_revision < 1 or not self._sha(expected_sha256):
                raise DesktopReviewError("interface_relearning_arguments_invalid")
            if current["revision"] != expected_revision or current["content_sha256"] != expected_sha256:
                raise DesktopReviewError("interface_relearning_stale")
            if not isinstance(region_ids, list) or any(not isinstance(x, str) or not x.strip() for x in region_ids) or len(set(region_ids)) != len(region_ids):
                raise DesktopReviewError("interface_relearning_regions_invalid")
            available = {r["region_id"] for r in current["content"]["regions"]}
            if not set(region_ids) <= available or not isinstance(message, str) or not message.strip() or len(message) > 4000:
                raise DesktopReviewError("interface_relearning_arguments_invalid")
            prior = index["issue_requests"].get(key)
            if prior is not None:
                if prior["request_sha256"] != request_sha:
                    raise DesktopReviewError("interface_relearning_idempotency_conflict")
                return self.read(prior["issue_id"])
            issue = {"contract_version": _CONTRACT, "issue_id": issue_id, "interface_id": interface_id,
                     "task_id": current["source"]["task_id"], "source": deepcopy(current["source"]),
                     "baseline_revision": expected_revision, "baseline_content_sha256": expected_sha256,
                     "region_ids": list(region_ids), "message": message, "request_sha256": request_sha, "idempotency_key": key,
                     "issue_sha256": ""}
            issue["issue_sha256"] = self._digest({k: issue[k] for k in issue if k != "issue_sha256"})
            _write_immutable(self._issue_path(issue_id), canonical_json_bytes(issue) + b"\n")
            try:
                self._write_state(issue_id, {"status": "open", "candidate_ids": [], "candidate_requests": {}, "adopt_requests": {}, "adopt_operations": {}, "message": "", "status_requests": {}})
            except OSError as error:
                raise DesktopReviewError("interface_relearning_persistence_failed") from error
            index["issue_ids"].append(issue_id)
            index["issue_requests"][key] = {"request_sha256": request_sha, "issue_id": issue_id}
            try:
                self._write_registry(index)
            except OSError as error:
                raise DesktopReviewError("interface_relearning_persistence_failed") from error
            return self.read(issue_id)

    def list(self, allowed_task_id=None):
        with self.facade._guard:
            result = []
            for issue_id in self._registry()["issue_ids"]:
                issue = self._issue(issue_id)
                if allowed_task_id is None or issue["task_id"] == allowed_task_id:
                    result.append(self.read(issue_id))
            return result

    @_storage_errors
    def read(self, issue_id):
        with self.facade._guard:
            issue = self._issue(issue_id)
            self._ensure_state(issue_id)
            state = self._state(issue_id)
            return {**deepcopy(issue), "status": state["status"], "candidate_ids": list(state["candidate_ids"]), "artifact_is_authorization": False}

    @_storage_errors
    def submit_candidate(self, allowed_task_id, issue_id, expected_baseline_sha256, changes, idempotency_key):
        with self.facade._guard:
            issue = self._issue(issue_id)
            state = self._state(issue_id)
            if issue["task_id"] != allowed_task_id:
                raise DesktopReviewError("interface_relearning_task_mismatch")
            key = self._key(idempotency_key)
            if key in state["candidate_requests"]:
                prior = state["candidate_requests"][key]
                if prior["request_sha256"] != self._digest({"issue_id": issue_id, "baseline": expected_baseline_sha256, "changes": changes, "idempotency_key": key}):
                    raise DesktopReviewError("interface_relearning_idempotency_conflict")
                return self._candidate(prior["candidate_id"])
            if state["status"] != "open" or expected_baseline_sha256 != issue["baseline_content_sha256"]:
                raise DesktopReviewError("interface_relearning_stale")
            if not isinstance(changes, dict) or not changes or set(changes) - {"meaning", "recognition_text", "regions"}:
                raise DesktopReviewError("interface_relearning_changes_invalid")
            base = InterfaceContentService(self.facade)._load_version(issue["interface_id"], issue["baseline_content_sha256"])
            content = InterfaceContentService(self.facade)._changed(base, self._expanded_changes(base, changes))
            request_sha = self._digest({"issue_id": issue_id, "baseline": expected_baseline_sha256, "changes": changes, "idempotency_key": key})
            candidate_id = "interface-candidate-" + str(uuid5(NAMESPACE_URL, "candidate:" + request_sha))
            record = {"contract_version": _CONTRACT, "candidate_id": candidate_id, "issue_id": issue_id,
                      "interface_id": issue["interface_id"], "task_id": allowed_task_id,
                      "baseline_content_sha256": expected_baseline_sha256, "changes": deepcopy(changes), "idempotency_key": key,
                      "content": content, "content_sha256": self._digest(content), "request_sha256": request_sha}
            record["candidate_record_sha256"] = self._digest({k: record[k] for k in record})
            _write_immutable(self._candidate_path(candidate_id), canonical_json_bytes(record) + b"\n")
            state["candidate_ids"].append(candidate_id)
            state["candidate_requests"][key] = {"request_sha256": request_sha, "candidate_id": candidate_id}
            try:
                self._write_state(issue_id, state)
            except OSError as error:
                raise DesktopReviewError("interface_relearning_persistence_failed") from error
            return self._candidate(candidate_id)

    def compare(self, issue_id, candidate_id):
        with self.facade._guard:
            issue = self._issue(issue_id); candidate = self._candidate(candidate_id)
            if candidate["issue_id"] != issue["issue_id"]:
                raise DesktopReviewError("interface_relearning_candidate_mismatch")
            return {"status": self._state(issue_id)["status"], "baseline": self._content(issue["interface_id"], "interface-version-" + issue["baseline_content_sha256"]), "candidate": candidate}

    @_storage_errors
    def adopt(self, issue_id, candidate_id, expected_revision, expected_sha256, idempotency_key):
        with self.facade._guard:
            if type(expected_revision) is not int or expected_revision < 1 or not self._sha(expected_sha256):
                raise DesktopReviewError("interface_relearning_arguments_invalid")
            issue = self._issue(issue_id); state = self._state(issue_id); candidate = self._candidate(candidate_id)
            key = self._key(idempotency_key)
            prior = state["adopt_requests"].get(key)
            if prior:
                if (prior.get("candidate_id") != candidate_id or prior.get("expected_revision") != expected_revision
                        or prior.get("expected_sha256") != expected_sha256):
                    raise DesktopReviewError("interface_relearning_idempotency_conflict")
                self._decision(issue_id, key)
                return self.read(issue_id)
            operation = state["adopt_operations"].get(key)
            if operation and (operation.get("candidate_id") != candidate_id or operation.get("expected_revision") != expected_revision or operation.get("expected_sha256") != expected_sha256):
                raise DesktopReviewError("interface_relearning_idempotency_conflict")
            if (candidate["issue_id"] != issue_id or state["status"] != "open"
                    or expected_revision != issue["baseline_revision"] or expected_sha256 != issue["baseline_content_sha256"]):
                raise DesktopReviewError("interface_relearning_stale")
            current = self._content(issue["interface_id"])
            save_key = "relearn-" + hashlib.sha256((issue_id + "|" + key).encode("ascii")).hexdigest()
            operation = state["adopt_operations"].get(key)
            if operation and (operation.get("candidate_id") != candidate_id or operation.get("expected_revision") != expected_revision or operation.get("expected_sha256") != expected_sha256):
                raise DesktopReviewError("interface_relearning_idempotency_conflict")
            manifest = InterfaceContentService(self.facade)._current(issue["interface_id"])
            request_record = manifest.get("requests", {}).get(save_key)
            if (operation and isinstance(request_record, dict)
                    and request_record.get("request_sha256") == self._save_request_sha(issue, candidate)):
                saved = InterfaceContentService(self.facade).load(issue["interface_id"], request_record["version_id"])
            else:
                if current["revision"] != expected_revision or current["content_sha256"] != expected_sha256 or current["revision"] != issue["baseline_revision"] or current["content_sha256"] != issue["baseline_content_sha256"]:
                    raise DesktopReviewError("interface_relearning_stale")
                state["adopt_operations"][key] = {"candidate_id": candidate_id, "expected_revision": expected_revision, "expected_sha256": expected_sha256, "save_key": save_key}
                try:
                    self._write_state(issue_id, state)
                except OSError as error:
                    raise DesktopReviewError("interface_relearning_persistence_failed") from error
                base = InterfaceContentService(self.facade)._load_version(issue["interface_id"], issue["baseline_content_sha256"])
                saved = InterfaceContentService(self.facade).save(issue["interface_id"], expected_revision, expected_sha256, self._expanded_changes(base, candidate["changes"]), save_key)
            decision = {"contract_version": _CONTRACT, "issue_id": issue_id, "candidate_id": candidate_id, "version_id": saved["version_id"], "content_sha256": saved["content_sha256"], "decision": "adopted"}
            if saved["content_sha256"] != self._expected_saved_hash(issue, candidate):
                raise DesktopReviewError("interface_relearning_adoption_invalid")
            decision["decision_sha256"] = self._digest(decision)
            try:
                _write_immutable(self._decision_path(issue_id, key), canonical_json_bytes(decision) + b"\n")
            except OSError as error:
                raise DesktopReviewError("interface_relearning_persistence_failed") from error
            state["status"] = "adopted"; state["adopt_requests"][key] = {"candidate_id": candidate_id, "expected_revision": expected_revision, "expected_sha256": expected_sha256, "version_id": saved["version_id"]}
            try:
                self._write_state(issue_id, state)
            except OSError as error:
                raise DesktopReviewError("interface_relearning_persistence_failed") from error
            return self.read(issue_id)

    def reject(self, issue_id, message="", idempotency_key="reject"):
        return self._set_status(issue_id, "rejected", message, idempotency_key)

    def withdraw(self, issue_id, message="", idempotency_key="withdraw"):
        return self._set_status(issue_id, "withdrawn", message, idempotency_key)

    @_storage_errors
    def _set_status(self, issue_id, status, message, idempotency_key):
        with self.facade._guard:
            self._issue(issue_id)
            if not isinstance(message, str) or len(message) > 4000:
                raise DesktopReviewError("interface_relearning_arguments_invalid")
            state = self._state(issue_id)
            key = self._key(idempotency_key)
            prior = state["status_requests"].get(key)
            if prior:
                if prior.get("message") != message or self._decision(issue_id, key).get("decision") != status:
                    raise DesktopReviewError("interface_relearning_idempotency_conflict")
                return self.read(issue_id)
            if state["adopt_operations"]:
                raise DesktopReviewError("interface_relearning_adoption_pending")
            if state["status"] != "open": raise DesktopReviewError("interface_relearning_stale")
            decision = {"contract_version": _CONTRACT, "issue_id": issue_id, "decision": status, "message": message, "idempotency_key": key}
            decision["decision_sha256"] = self._digest(decision)
            try: _write_immutable(self._decision_path(issue_id, key), canonical_json_bytes(decision) + b"\n")
            except OSError as error: raise DesktopReviewError("interface_relearning_persistence_failed") from error
            state["status"] = status; state["message"] = message
            state["status_requests"][key] = {"message": message, "decision_sha256": decision["decision_sha256"]}
            self._write_state(issue_id, state)
            return self.read(issue_id)

    def _content(self, interface_id, version_id=None):
        return InterfaceContentService(self.facade).load(interface_id, version_id)

    def _expected_saved_hash(self, issue, candidate):
        request = self._save_request_sha(issue, candidate)
        value = InterfaceContentService(self.facade)._base(issue["interface_id"], issue["baseline_revision"] + 1, issue["source"], candidate["content"], parent_content_sha256=issue["baseline_content_sha256"], request_sha256=request)
        return value["content_sha256"]

    def _save_request_sha(self, issue, candidate):
        base = InterfaceContentService(self.facade)._load_version(issue["interface_id"], issue["baseline_content_sha256"])
        return self._digest({"revision": issue["baseline_revision"], "sha": issue["baseline_content_sha256"], "changes": self._expanded_changes(base, candidate["changes"])})

    @staticmethod
    def _expanded_changes(base, changes):
        value = deepcopy(changes)
        if isinstance(value, dict) and isinstance(value.get("regions"), list):
            existing = {region["region_id"]: region for region in base["content"]["regions"]}
            # 完整列表保留顺序及显式删除；列表内的局部字段从固定基线补齐。
            value["regions"] = [{**deepcopy(existing.get(region.get("region_id"), {})), **region}
                                if isinstance(region, dict) and isinstance(region.get("region_id"), str)
                                else region for region in value["regions"]]
        return value

    def _candidate(self, candidate_id):
        if not isinstance(candidate_id, str) or not _CANDIDATE.fullmatch(candidate_id): raise DesktopReviewError("interface_relearning_candidate_invalid")
        value = self._json(self._candidate_path(candidate_id), "interface relearning candidate")
        issue = self._issue(value.get("issue_id"))
        if (value.get("candidate_id") != candidate_id or value.get("contract_version") != _CONTRACT
                or value.get("interface_id") != issue["interface_id"] or value.get("task_id") != issue["task_id"]
                or value.get("baseline_content_sha256") != issue["baseline_content_sha256"]
                or value.get("content_sha256") != self._digest(value.get("content"))
                or value.get("candidate_record_sha256") != self._digest({k: value[k] for k in value if k != "candidate_record_sha256"})):
            raise DesktopReviewError("interface_relearning_candidate_invalid")
        try:
            base = InterfaceContentService(self.facade)._load_version(issue["interface_id"], issue["baseline_content_sha256"])
            expected = InterfaceContentService(self.facade)._changed(base, self._expanded_changes(base, value["changes"]))
        except (DesktopReviewError, KeyError, TypeError, ValueError):
            raise DesktopReviewError("interface_relearning_candidate_invalid") from None
        if expected != value.get("content") or value["candidate_id"] not in self._state(issue["issue_id"])["candidate_ids"]:
            raise DesktopReviewError("interface_relearning_candidate_invalid")
        return value

    def _issue(self, issue_id):
        if not isinstance(issue_id, str) or not _ISSUE.fullmatch(issue_id): raise DesktopReviewError("interface_relearning_issue_invalid")
        value = self._json(self._issue_path(issue_id), "interface relearning issue")
        expected_keys = {"contract_version", "issue_id", "interface_id", "task_id", "source", "baseline_revision", "baseline_content_sha256", "region_ids", "message", "request_sha256", "idempotency_key", "issue_sha256"}
        if set(value) != expected_keys or value.get("issue_id") != issue_id or value.get("contract_version") != _CONTRACT or value.get("issue_sha256") != self._digest({k: value[k] for k in value if k != "issue_sha256"}):
            raise DesktopReviewError("interface_relearning_issue_invalid")
        try:
            baseline = InterfaceContentService(self.facade)._load_version(value["interface_id"], value["baseline_content_sha256"])
        except (DesktopReviewError, KeyError, TypeError, ValueError):
            raise DesktopReviewError("interface_relearning_issue_invalid") from None
        if (type(value["baseline_revision"]) is not int or baseline["revision"] != value["baseline_revision"]
                or baseline["source"] != value["source"] or baseline["source"]["task_id"] != value["task_id"]
                or not isinstance(value["region_ids"], list) or any(not isinstance(x, str) for x in value["region_ids"])
                or not set(value["region_ids"]) <= {r["region_id"] for r in baseline["content"]["regions"]}
                or not isinstance(value["message"], str) or not value["message"].strip()
                or issue_id != "interface-issue-" + str(uuid5(NAMESPACE_URL, "issue:" + self._key(value["idempotency_key"])))):
            raise DesktopReviewError("interface_relearning_issue_invalid")
        request = {"interface_id": value["interface_id"], "revision": value["baseline_revision"],
                   "sha": value["baseline_content_sha256"], "region_ids": value["region_ids"],
                   "message": value["message"], "idempotency_key": value["idempotency_key"]}
        if value["request_sha256"] != self._digest(request):
            raise DesktopReviewError("interface_relearning_issue_invalid")
        return value

    def _state(self, issue_id):
        value = self._json(self._state_path(issue_id), "interface relearning state")
        required = {"issue_id", "status", "candidate_ids", "candidate_requests", "adopt_requests", "adopt_operations", "message", "status_requests", "state_sha256"}
        if set(value) != required or value.get("issue_id") != issue_id or not isinstance(value.get("status"), str) or value["status"] not in {"open", "adopted", "rejected", "withdrawn"} or not isinstance(value["candidate_ids"], list) or not all(isinstance(x, str) for x in value["candidate_ids"]) or not all(isinstance(value[k], dict) for k in ("candidate_requests", "adopt_requests", "adopt_operations", "status_requests")) or not isinstance(value["message"], str):
            raise DesktopReviewError("interface_relearning_state_invalid")
        if value.get("state_sha256") != self._digest({k: value[k] for k in value if k != "state_sha256"}):
            raise DesktopReviewError("interface_relearning_state_invalid")
        return value

    def _registry(self):
        if not self.registry.exists(): return {"contract_version": _STATE, "issue_ids": [], "issue_requests": {}}
        value = self._json(self.registry, "interface relearning registry")
        if value.get("contract_version") != _STATE or not isinstance(value.get("issue_ids"), list) or not isinstance(value.get("issue_requests"), dict): raise DesktopReviewError("interface_relearning_registry_invalid")
        return value

    def _write_registry(self, value):
        self.root.mkdir(parents=True, exist_ok=True); _atomic_write_bytes(self.registry, canonical_json_bytes(value) + b"\n")

    def _write_state(self, issue_id, value):
        value = dict(value); value.pop("state_sha256", None); value["issue_id"] = issue_id; value.setdefault("message", ""); value.setdefault("status_requests", {}); value.setdefault("adopt_operations", {})
        value["state_sha256"] = self._digest(value)
        self.root.mkdir(parents=True, exist_ok=True); _atomic_write_bytes(self._state_path(issue_id), canonical_json_bytes(value) + b"\n")

    def _ensure_state(self, issue_id):
        if not self._state_path(issue_id).exists():
            # 只恢复最初建档尚未写入 state 的中断；后续状态丢失不能伪造为 open。
            folder = self.root / "candidates"
            if any(self._json(path, "interface relearning candidate").get("issue_id") == issue_id
                   for path in folder.glob("interface-candidate-*.json")) or any((self.root / "decisions").glob(issue_id + "-*.json")):
                raise DesktopReviewError("interface_relearning_state_invalid")
            self._write_state(issue_id, {"status": "open", "candidate_ids": [], "candidate_requests": {}, "adopt_requests": {}, "adopt_operations": {}, "message": "", "status_requests": {}})

    def _decision(self, issue_id, key):
        value = self._json(self._decision_path(issue_id, key), "interface relearning decision")
        if (value.get("issue_id") != issue_id or value.get("contract_version") != _CONTRACT
                or value.get("decision_sha256") != self._digest({k: v for k, v in value.items() if k != "decision_sha256"})):
            raise DesktopReviewError("interface_relearning_decision_invalid")
        return value

    def _issue_path(self, issue_id): return self.root / "issues" / f"{issue_id}.json"
    def _state_path(self, issue_id): return self.root / "issues" / f"{issue_id}.state.json"
    def _candidate_path(self, candidate_id): return self.root / "candidates" / f"{candidate_id}.json"
    def _decision_path(self, issue_id, key): return self.root / "decisions" / f"{issue_id}-{key}.json"
    def _json(self, path, label):
        try: value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error: raise DesktopReviewError(f"{label}_invalid") from error
        if not isinstance(value, dict): raise DesktopReviewError(f"{label}_invalid")
        return value
    @staticmethod
    def _digest(value): return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    @staticmethod
    def _sha(value): return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))
    @staticmethod
    def _key(value):
        if not isinstance(value, str) or not _KEY.fullmatch(value): raise DesktopReviewError("interface_relearning_idempotency_key_invalid")
        return value
