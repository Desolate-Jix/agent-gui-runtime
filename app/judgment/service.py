"""共用证据服务；持久发送标记防重复计费，认证结果不替代原动作收据。"""
from hashlib import sha256
from contextlib import closing
import json
import math
import os
from pathlib import Path
import sqlite3
import re
from threading import RLock
from time import perf_counter_ns

from .evidence import prepare_request
from .openai_decisions import DecisionNotConnected, MODEL, OpenAIDecisionsProvider, _probability, _usage_counts
from .profile import DecisionProfile, load_decision_profile
from .adaptive_policy import assessment, effective_review_policy, enabled_predicates, metadata, require_review
from .choice_contract import choice_assessment, validate_choice_result
from .field_content_choice import (field_content_requested, field_content_assessment,
    validate_field_content_result)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def decision_profile_sha256(profile):
    return sha256(_canonical(profile.model_dump(mode="json"))).hexdigest()


def _connect_decision_ledger_readonly(session_dir):
    root = Path(session_dir).resolve(strict=True)
    storage = root / "judgments"
    path = storage / "decisions.sqlite3"
    if (not storage.is_dir() or storage.resolve(strict=True) != storage
            or path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path):
        raise OSError("decision_persistence_path_invalid")
    # 状态与恢复认证共用只读连接，不创建目录或表。
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2, isolation_level=None)


def read_decision_budget_status(session_dir, profile):
    v2 = profile.contract_version == "decision_profile.v2"
    result = {"used": 0, "remaining": profile.request_cap, "unknown_dispatches": 0,
              "budget_scope": "host_session" if v2 else "execution", "budget_status": "available"}
    storage = Path(session_dir) / "judgments"
    try:
        try:
            storage.lstat()
        except FileNotFoundError:
            # 尚无持久目录才是未使用；目录已存在而账本缺失属于读取失败。
            return result
        with closing(_connect_decision_ledger_readonly(session_dir)) as db:
            clause = "" if v2 else " AND scope='execution'"
            used, unknown = db.execute("SELECT COUNT(*), COALESCE(SUM(result_blob IS NULL),0) "
                "FROM dispatches WHERE dispatched=1" + clause).fetchone()
        result.update(used=used, remaining=max(0, profile.request_cap - used), unknown_dispatches=unknown)
    except (sqlite3.Error, OSError, ValueError):
        result.update(used=None, remaining=None, unknown_dispatches=None, budget_status="unavailable")
    return result


def _protect(data, entropy, *, decrypt=False):
    try:
        import win32crypt
        import pywintypes
    except ImportError:
        raise OSError("decision_persistence_dpapi_unavailable") from None
    try:
        if decrypt:
            return win32crypt.CryptUnprotectData(data, entropy, None, None, 1)[1]
        return win32crypt.CryptProtectData(data, None, entropy, None, None, 1)
    except pywintypes.error:
        raise OSError("decision_persistence_authentication_failed") from None


class DecisionService:
    def __init__(self, session_dir, *, profile=None, provider=None):
        self.session_dir = Path(session_dir)
        self.profile = profile if profile is not None else DecisionProfile(mode="off")
        if not isinstance(self.profile, DecisionProfile):
            raise ValueError("decision_profile_required")
        self.enabled = self.profile.mode != "off"
        self.adoption_mode = self.profile.mode
        self._provider = provider
        self._closed = False
        self._provider_lock = RLock()

    @classmethod
    def from_environment(cls, session_dir, *, profile_path=None):
        path = profile_path if profile_path is not None else os.environ.get("AGENT_GUI_DECISION_PROFILE")
        if not path:
            return cls(session_dir)
        return cls(session_dir, profile=load_decision_profile(path))

    def status(self):
        result = {"enabled": self.enabled, "mode": self.adoption_mode, "model": MODEL,
                 "contract_version": self.profile.contract_version, "configured": self.enabled,
                 "request_cap": self.profile.request_cap, "timeout_seconds": self.profile.timeout_seconds,
                 "closed": self._closed}
        result.update(self._budget_status())
        if self._v2:
            result.update(proactive_review=self.profile.proactive_review, review_policy=self.profile.review_policy,
                          profile_sha256=self._profile_sha256())
            if "decision_format" in self.profile.model_fields_set:
                result["decision_format"] = self.profile.decision_format
        return result

    @property
    def _v2(self):
        return self.profile.contract_version == "decision_profile.v2"

    def _profile_sha256(self):
        return decision_profile_sha256(self.profile)

    def _admission_budget(self, used):
        return {"scope": "host_session", "request_cap": self.profile.request_cap, "used": used,
                "remaining": max(0, self.profile.request_cap - used), "snapshot_phase": "dispatch_admission"}

    def _budget_status(self):
        return read_decision_budget_status(self.session_dir, self.profile)

    def readiness(self):
        if not self.enabled:
            return {"ready": False, "status": "disabled"}
        if self._closed:
            return {"ready": False, "status": "closed"}
        ready = getattr(self._provider, "ready", None) if self._provider is not None else None
        if type(ready) is not bool:
            ready = bool((os.environ.get(self.profile.api_key_env) or "").strip())
        return {"ready": ready, "status": "ready" if ready else "not_connected"}

    def auto_condition_allowed(self, condition, *, condition_snapshot=None):
        if not self.enabled or self.adoption_mode != "auto":
            return False
        if condition_snapshot is None:
            return condition in self.profile.auto_conditions
        if not self._v2:
            return False
        from .condition_templates import validate_condition_snapshot
        try:
            snapshot = validate_condition_snapshot(condition_snapshot)
        except (ValueError, TypeError):
            return False
        return condition == snapshot["condition"] and any(
            all(getattr(identity, key) == snapshot[key]
                for key in ("condition_template_id", "revision", "template_sha256"))
            for identity in self.profile.auto_condition_templates)

    def _get_provider(self):
        with self._provider_lock:
            if self._closed:
                raise OSError("decision_service_closed")
            if self._provider is None:
                self._provider = OpenAIDecisionsProvider(api_key_env=self.profile.api_key_env, timeout_seconds=self.profile.timeout_seconds)
            return self._provider

    def _base(self, *, status="uncertain", phase="after_action", request_id=None, execution_request_id=None):
        result = {"status": status, "verdict": "uncertain", "source": "openai_decisions", "model": MODEL,
                "phase": phase, "request_id": request_id, "execution_request_id": execution_request_id,
                "predicates": {}, "probabilities": {}, "usage": None, "elapsed_ms": 0,
                "http_elapsed_ms": None, "server_processing_ms": None, "provider_request_id": None,
                 "adopted": False, "authorizes_action": False, "automatic_retry_allowed": False, "evidence_hashes": []}
        if self._v2:
            result.update(metadata(self.profile, phase), profile_sha256=self._profile_sha256(), budget=None)
        return result

    def _diagnostic(self, result, reason, *, review_scope="runtime_diagnostic", **patch):
        result = {**result, **patch, "reason": reason}
        if self._v2:
            require_review(result, reason, scope=review_scope)
        return result

    def _prepare(self, kwargs, *, include_upload=True):
        if not self._v2 and (kwargs.get("condition_snapshot") is not None or kwargs.get("assessment_context") is not None
                or kwargs.get("temporal_context") is not None
                or isinstance(kwargs.get("review_context"), dict) and "wait_policy" in kwargs["review_context"]):
            raise ValueError("decision_profile_v2_required")
        binding, frames = prepare_request(self.session_dir, **kwargs, include_upload=include_upload)
        if field_content_requested(binding) and (not self._v2 or self.profile.decision_format != "choice"):
            raise ValueError("decision_field_content_choice_required")
        policy = {"mode": self.profile.mode, "pass_threshold": self.profile.pass_threshold,
                  "fail_threshold": self.profile.fail_threshold, "auto_conditions": self.profile.auto_conditions}
        if self._v2:
            binding.setdefault("review_context", None)
            policy = {"profile": self.profile.model_dump(mode="json"),
                      "enabled_predicates": enabled_predicates(self.profile, binding["phase"], binding["review_context"]),
                      "review_policy": effective_review_policy(self.profile, binding["review_context"]),
                      "prompt_version": "decision_prompt." + binding["temporal_context"]["schema"] if "temporal_context" in binding else "decision_prompt.v2"}
        digest = sha256(_canonical({"binding": binding, "policy": policy})).hexdigest()
        return binding, frames, digest

    def _connect(self):
        root = self.session_dir.resolve(strict=True)
        storage = root / "judgments"
        storage.mkdir(exist_ok=True)
        if storage.resolve() != storage or not storage.resolve().is_relative_to(root):
            raise OSError("decision_persistence_path_invalid")
        path = storage / "decisions.sqlite3"
        if path.is_symlink() or (path.exists() and path.resolve() != path):
            raise OSError("decision_persistence_path_invalid")
        connection = sqlite3.connect(path, timeout=2, isolation_level=None)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("CREATE TABLE IF NOT EXISTS dispatches (request_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, scope TEXT NOT NULL, dispatched INTEGER NOT NULL, marker_blob BLOB NOT NULL, result_blob BLOB)")
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    def _entropy(self, request_id):
        return sha256((str(self.session_dir.resolve()) + "\0" + request_id).encode("utf-8")).digest()

    def _connect_readonly(self):
        return _connect_decision_ledger_readonly(self.session_dir)

    def _saved(self, row, binding, digest):
        base = {**self._base(phase=binding["phase"], request_id=binding["request_id"], execution_request_id=binding["execution_request_id"]), **binding,
                 "request_sha256": digest, "evidence_hashes": [f["sha256"] for f in binding["frames"]]}
        if self._v2:
            base.update(metadata(self.profile, binding["phase"], binding.get("review_context")))
        if row[0] != digest:
            return self._diagnostic(base, "decision_request_id_conflict", status="conflict")
        try:
            blob = row[1] if row[1] is not None else row[2]
            value = json.loads(_protect(blob, self._entropy(binding["request_id"]), decrypt=True).decode("utf-8"))
            statuses = {"completed", "refused", "timeout", "error", "not_connected", "unknown", "limited"}
            if self._v2:
                statuses.add("skipped")
            if (not isinstance(value, dict) or value.get("request_sha256") != digest
                    or any(value.get(key) != binding[key] for key in binding)
                    or value.get("authorizes_action") is not False or value.get("automatic_retry_allowed") is not False
                    or value.get("evidence_hashes") != base["evidence_hashes"]
                    or value.get("status") not in statuses
                    or value.get("verdict") not in ("success", "failure", "uncertain")
                    or type(value.get("adopted")) is not bool):
                raise ValueError("decision_saved_binding_invalid")
            if value["adopted"] and (not self.auto_condition_allowed(binding["condition"],
                    condition_snapshot=binding.get("condition_snapshot"))
                    or value["status"] != "completed" or value["verdict"] == "uncertain"):
                raise ValueError("decision_saved_adoption_invalid")
            if self._v2 and (value.get("schema_version") != "decision_assessment.v2"
                    or value.get("profile_sha256") != self._profile_sha256()
                    or value.get("enabled_predicates") != enabled_predicates(self.profile, binding["phase"], binding.get("review_context"))
                    or value.get("disposition") not in ("continue", "observe", "review_required")
                    or value.get("review_scope") not in ("effect", "remaining_plan", "effect_and_plan", "runtime_diagnostic")
                    or not isinstance(value.get("reason_codes"), list)
                    or any(not isinstance(reason, str) for reason in value["reason_codes"])
                    or value["adopted"] != (value.get("disposition") == "continue")
                    or value["adopted"] and value["verdict"] != "success"):
                raise ValueError("decision_saved_disposition_invalid")
            content_requested = field_content_requested(binding)
            content = None
            if "field_content_result" in value:
                if not content_requested:
                    raise ValueError("decision_saved_unrequested_field_content")
                content = validate_field_content_result(value["field_content_result"])
            if content_requested and value["status"] in ("completed", "refused") and content is None:
                raise ValueError("decision_saved_field_content_missing")
            if self._v2 and self.profile.decision_format == "choice":
                if (value.get("decision_format") != "choice" or value.get("predicates") != {}
                        or value.get("probabilities") != {}):
                    raise ValueError("decision_saved_choice_invalid")
                choice = value.get("choice_result")
                if choice is not None:
                    choice = validate_choice_result(choice)
                if value["status"] == "completed":
                    if choice is None or choice["type"] != "choice":
                        raise ValueError("decision_saved_choice_invalid")
                    if content_requested and content["type"] != "choice":
                        raise ValueError("decision_saved_field_content_invalid")
                    expected = (field_content_assessment(self.profile, choice["choice"], content,
                        clear_existing=binding["action"]["field_content_check"]["clear_existing"]) if content_requested else
                        choice_assessment(self.profile, choice["choice"]))
                    if any(value.get(key) != item for key, item in expected.items()):
                        raise ValueError("decision_saved_choice_disposition_invalid")
                elif value["status"] == "refused":
                    if choice is None:
                        raise ValueError("decision_saved_choice_refusal_invalid")
                    if choice["type"] != "refusal":
                        if not content_requested or content["type"] != "refusal":
                            raise ValueError("decision_saved_choice_refusal_invalid")
                        expected = field_content_assessment(self.profile, choice["choice"], content,
                            clear_existing=binding["action"]["field_content_check"]["clear_existing"])
                        if (any(value.get(key) != item for key, item in expected.items())
                                or value.get("reason") != "decision_field_content_refused"):
                            raise ValueError("decision_saved_field_content_refusal_invalid")
            return value
        except (OSError, ValueError, UnicodeError, TypeError):
            return self._diagnostic(base, "decision_saved_result_invalid", status="error")

    def evaluate(self, *, request_id, execution_request_id, condition, frames, mode="execution", phase="after_action",
                 run_id=None, step_id=None, action=None, review_context=None, assessment_context=None, condition_snapshot=None,
                 temporal_context=None, request_budget_seconds=None):
        base = self._base(phase=phase, request_id=request_id, execution_request_id=execution_request_id)
        if not self.enabled:
            return self._diagnostic(base, "decision_disabled", status="disabled") if self._v2 else {**base, "status": "disabled"}
        if self._closed:
            return self._diagnostic(base, "decision_service_closed", status="error")
        started = perf_counter_ns()
        kwargs = {"request_id": request_id, "execution_request_id": execution_request_id, "condition": condition,
                  "frames": frames, "mode": mode, "phase": phase, "run_id": run_id, "step_id": step_id, "action": action,
                  "review_context": review_context, "assessment_context": assessment_context, "condition_snapshot": condition_snapshot,
                  "temporal_context": temporal_context, "request_budget_seconds": request_budget_seconds}
        try:
            binding, upload_frames, digest = self._prepare(kwargs)
        except (OSError, ValueError, TypeError):
            return self._diagnostic(base, "decision_evidence_or_binding_invalid", status="rejected")
        base.update(binding, request_sha256=digest, evidence_hashes=[f["sha256"] for f in binding["frames"]])
        annotations = [item["candidate_annotation"]["metadata"] for item in upload_frames if "candidate_annotation" in item]
        executed_annotations = [item["executed_click_annotation"]["metadata"]
            for item in upload_frames if "executed_click_annotation" in item]
        if executed_annotations:
            base["executed_click_annotations"] = executed_annotations
        if annotations:
            # 派生视图记入认证回执；原图和候选已有绑定，旧请求摘要不变。
            base["candidate_annotations"] = annotations
        if self._v2:
            base.update(metadata(self.profile, phase, binding["review_context"]))
        scope = "host_session" if self._v2 else "learning:" + run_id if mode == "learning" else "execution"
        skip_reason = None
        if self._v2:
            if effective_review_policy(self.profile, binding["review_context"]) == "always_main":
                skip_reason = "decision_always_main"
            elif self.adoption_mode == "auto" and not self.auto_condition_allowed(condition,
                    condition_snapshot=binding.get("condition_snapshot")):
                skip_reason = ("decision_condition_template_not_allowlisted" if "condition_snapshot" in binding
                               else "decision_condition_not_allowlisted")
            elif self.profile.proactive_review and binding["review_context"] is None:
                skip_reason = "decision_review_context_missing"
        try:
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                prior = db.execute("SELECT request_sha256, result_blob, marker_blob FROM dispatches WHERE request_id=?", (request_id,)).fetchone()
                if prior is not None:
                    db.commit()
                    return self._saved(prior, binding, digest)
                count = (db.execute("SELECT COUNT(*) FROM dispatches WHERE dispatched=1").fetchone()[0] if self._v2 else
                         db.execute("SELECT COUNT(*) FROM dispatches WHERE scope=? AND dispatched=1", (scope,)).fetchone()[0])
                if self._v2:
                    base["budget"] = self._admission_budget(count)
                if skip_reason is not None:
                    review_scope = "effect_and_plan" if skip_reason == "decision_always_main" else (
                        "effect" if skip_reason in ("decision_condition_not_allowlisted",
                            "decision_condition_template_not_allowlisted") else "runtime_diagnostic")
                    skipped = self._diagnostic(base, skip_reason, status="skipped", review_scope=review_scope)
                    skipped["predicates"] = {name: {"type": "not_requested", "probability": None} for name in base["predicates"]}
                    encrypted = _protect(_canonical(skipped), self._entropy(request_id))
                    db.execute("INSERT INTO dispatches(request_id, request_sha256, scope, dispatched, marker_blob, result_blob) VALUES(?,?,?,0,?,?)",
                               (request_id, digest, scope, encrypted, encrypted))
                    db.commit()
                    return skipped
                if count >= self.profile.request_cap:
                    limited = self._diagnostic(base, "decision_scope_request_cap", status="limited")
                    encrypted = _protect(_canonical(limited), self._entropy(request_id))
                    db.execute("INSERT INTO dispatches(request_id, request_sha256, scope, dispatched, marker_blob, result_blob) VALUES(?,?,?,0,?,?)", (request_id, digest, scope, encrypted, encrypted))
                    db.commit()
                    return limited
                # 先确认认证持久化可用，再冻结发送；任何崩溃均留下不可重派标记。
                if self._v2:
                    base["budget"] = self._admission_budget(count + 1)
                marker = self._diagnostic(base, "decision_prior_dispatch_unresolved", status="unknown")
                encrypted = _protect(_canonical(marker), self._entropy(request_id))
                db.execute("INSERT INTO dispatches(request_id, request_sha256, scope, dispatched, marker_blob) VALUES(?,?,?,1,?)", (request_id, digest, scope, encrypted))
                db.commit()
        except (sqlite3.Error, OSError):
            return self._diagnostic(base, "decision_persistence_unavailable", status="error")
        try:
            payload = {"condition": condition, "phase": phase, "frames": upload_frames,
                       "action": binding["action"], "request_sha256": digest}
            if self._v2:
                payload.update(schema_version="decision_request.v2", enabled_predicates=list(base["enabled_predicates"]),
                               review_context=json.loads(_canonical(binding["review_context"])))
                if self.profile.decision_format == "choice":
                    payload["decision_format"] = "choice"
                if "assessment_context" in binding:
                    payload["assessment_context"] = json.loads(_canonical(binding["assessment_context"]))
                if "temporal_context" in binding:
                    payload["temporal_context"] = json.loads(_canonical(binding["temporal_context"]))
            provider = self._get_provider()
            budgets = [binding[key]["timeout_seconds"] for key in ("assessment_context", "temporal_context") if key in binding]
            if "request_budget_seconds" in binding:
                budgets.append(binding["request_budget_seconds"])
            if budgets:
                # 取得 provider 后再扣余量，包含 getter 等待；认证摘要保持入场余量不变。
                remaining = min(budgets) - (perf_counter_ns() - started) / 1_000_000_000
                if remaining <= 0:
                    raise TimeoutError("decision_assessment_budget_expired")
                payload["request_timeout_seconds"] = min(self.profile.timeout_seconds, remaining)
            answer = provider.judge(payload)
            if (budgets and (perf_counter_ns() - started) / 1_000_000_000 >= min(budgets)):
                raise TimeoutError("decision_assessment_budget_expired")
            result_key = "choice_result" if self._v2 and self.profile.decision_format == "choice" else "predicates"
            content_requested = field_content_requested(binding)
            answer_keys = {"request_sha256", result_key, "usage", "http_elapsed_ms", "server_processing_ms", "provider_request_id"}
            if content_requested:
                answer_keys.add("field_content_result")
            if (not isinstance(answer, dict) or set(answer) != answer_keys
                    or answer.get("request_sha256") != digest):
                raise ValueError("decision_reply_binding_invalid")
            usage = _usage_counts(answer["usage"])
            for name in ("http_elapsed_ms", "server_processing_ms"):
                value = answer[name]
                if (value is None and name == "http_elapsed_ms") or (value is not None and (
                        type(value) not in (int, float) or not math.isfinite(value) or value < 0)):
                    raise ValueError("decision_timing_invalid")
            provider_id = answer["provider_request_id"]
            if provider_id is not None and (not isinstance(provider_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", provider_id)):
                raise ValueError("decision_provider_request_id_invalid")
            if result_key == "choice_result":
                choice = validate_choice_result(answer["choice_result"])
                content = validate_field_content_result(answer["field_content_result"]) if content_requested else None
                if content_requested:
                    base["field_content_result"] = content
                base.update({key: answer[key] for key in ("http_elapsed_ms", "server_processing_ms", "provider_request_id")}, usage=usage, choice_result=choice)
                if choice["type"] == "refusal":
                    base.update(status="refused", reason="decision_choice_refused")
                    require_review(base, "decision_choice_refused")
                elif content_requested:
                    base.update(status="refused" if content["type"] == "refusal" else "completed",
                        **field_content_assessment(self.profile, choice["choice"], content,
                            clear_existing=binding["action"]["field_content_check"]["clear_existing"]))
                    if content["type"] == "refusal":
                        base["reason"] = "decision_field_content_refused"
                else:
                    base.update(status="completed", **choice_assessment(self.profile, choice["choice"]))
            else:
                danger = "unsafe_effect" if phase == "before_action" else "visible_error"
                predicates = answer["predicates"]
                expected = set(base["enabled_predicates"]) if self._v2 else {"condition_met", danger}
                if not isinstance(predicates, dict) or set(predicates) != expected:
                    raise ValueError("decision_predicates_invalid")
                probabilities = {}
                for name, predicate in predicates.items():
                    if not isinstance(predicate, dict) or set(predicate) != {"type", "probability"}:
                        raise ValueError("decision_predicate_invalid")
                    if predicate["type"] == "refusal" and predicate["probability"] is None:
                        probabilities[name] = None
                    elif predicate["type"] == "predicate":
                        probabilities[name] = _probability(predicate["probability"])
                    else:
                        raise ValueError("decision_predicate_invalid")
                if self._v2:
                    base["predicates"].update(predicates)
                    base["probabilities"].update(probabilities)
                    base.update({key: answer[key] for key in ("http_elapsed_ms", "server_processing_ms", "provider_request_id")}, usage=usage)
                else:
                    base.update({key: answer[key] for key in ("http_elapsed_ms", "server_processing_ms", "provider_request_id")},
                                usage=usage, predicates=predicates, probabilities=probabilities)
                if any(value is None for value in probabilities.values()):
                    base.update(status="refused", reason="decision_predicate_refused")
                    if self._v2:
                        require_review(base, "decision_predicate_refused")
                elif self._v2:
                    base.update(status="completed", **assessment(self.profile, phase, base["probabilities"], binding["review_context"]))
                    if "decision_predicate_conflict" in base["reason_codes"]:
                        base["reason"] = "decision_predicate_conflict"
                else:
                    met, unsafe = probabilities["condition_met"], probabilities[danger]
                    conflict = met >= self.profile.pass_threshold and unsafe >= self.profile.pass_threshold
                    verdict = "uncertain" if conflict else (
                        "failure" if met <= self.profile.fail_threshold or unsafe >= self.profile.pass_threshold else (
                            "success" if met >= self.profile.pass_threshold and unsafe <= self.profile.fail_threshold else "uncertain"))
                    base.update(status="completed", verdict=verdict,
                                adopted=self.auto_condition_allowed(condition) and verdict != "uncertain")
                    if conflict:
                        base["reason"] = "decision_predicate_conflict"
        except DecisionNotConnected:
            base.update(status="not_connected", reason="decision_key_missing")
            if self._v2:
                require_review(base, "decision_key_missing")
        except TimeoutError:
            base.update(status="timeout", reason="decision_provider_timeout")
            if self._v2:
                require_review(base, "decision_provider_timeout")
        except (OSError, ValueError, KeyError, TypeError) as error:
            base.update(status="error", reason="decision_provider_or_contract_error")
            # 只投影适配器的精确固定码，不保留异常文本、请求地址或凭据。
            code = error.args[0] if len(error.args) == 1 and type(error.args[0]) is str else None
            if (code in {"decision_transport_error", "decision_protocol_error", "decision_response_too_large",
                    "decision_provider_closed"}
                    or type(code) is str and re.fullmatch(r"decision_http_status_[1-5][0-9]{2}", code)):
                base["provider_error_code"] = code
            if self._v2:
                require_review(base, "decision_provider_or_contract_error")
        # 完成和关闭共用锁；先完成的认证记录保留，先关闭则只保存不确定结果。
        with self._provider_lock:
            if self._closed:
                base.update(status="error", verdict="uncertain", adopted=False, reason="decision_service_closed_during_evaluation")
                if self._v2:
                    require_review(base, "decision_service_closed_during_evaluation")
            base["elapsed_ms"] = (perf_counter_ns() - started) / 1_000_000
            try:
                encrypted = _protect(_canonical(base), self._entropy(request_id))
                with closing(self._connect()) as db:
                    changed = db.execute("UPDATE dispatches SET result_blob=? WHERE request_id=? AND request_sha256=? AND result_blob IS NULL", (encrypted, request_id, digest)).rowcount
                    if changed != 1:
                        raise OSError("decision_result_write_conflict")
            except (sqlite3.Error, OSError, ValueError, TypeError):
                return self._diagnostic(base, "decision_result_persistence_failed", status="error", verdict="uncertain", adopted=False)
        return base

    def validate_result(self, result, *, condition_snapshot=None, **original_evaluate_kwargs):
        if not self.enabled or self._closed or not isinstance(result, dict):
            return False
        if "condition_snapshot" in result and condition_snapshot is None:
            # 返回快照只证明内部一致；采用端必须从原运行输入重建预期快照。
            return False
        try:
            kwargs = original_evaluate_kwargs or {key: result[key] for key in (
                "request_id", "execution_request_id", "condition", "frames", "mode", "phase", "run_id", "step_id", "action")}
            if not original_evaluate_kwargs and "review_context" in result:
                kwargs["review_context"] = result["review_context"]
            if not original_evaluate_kwargs and "assessment_context" in result:
                kwargs["assessment_context"] = result["assessment_context"]
            if not original_evaluate_kwargs and "temporal_context" in result:
                kwargs["temporal_context"] = result["temporal_context"]
            if not original_evaluate_kwargs and "request_budget_seconds" in result:
                kwargs["request_budget_seconds"] = result["request_budget_seconds"]
            if condition_snapshot is not None:
                kwargs["condition_snapshot"] = condition_snapshot
            binding, _, digest = self._prepare(kwargs, include_upload=False)
            with closing(self._connect_readonly()) as db:
                row = db.execute("SELECT request_sha256, result_blob, marker_blob FROM dispatches WHERE request_id=?", (binding["request_id"],)).fetchone()
            if row is None:
                return False
            saved = self._saved(row, binding, digest)
            return saved.get("reason") != "decision_saved_result_invalid" and saved.get("status") != "conflict" and _canonical(saved) == _canonical(result)
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
            return False

    def close(self):
        with self._provider_lock:
            self._closed = True
            provider = self._provider
        if provider is not None:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
