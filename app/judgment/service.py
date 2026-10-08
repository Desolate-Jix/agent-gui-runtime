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


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


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
        return {"enabled": self.enabled, "mode": self.adoption_mode, "model": MODEL,
                "contract_version": self.profile.contract_version, "configured": self.enabled,
                "request_cap": self.profile.request_cap, "timeout_seconds": self.profile.timeout_seconds,
                "closed": self._closed}

    def readiness(self):
        if not self.enabled:
            return {"ready": False, "status": "disabled"}
        if self._closed:
            return {"ready": False, "status": "closed"}
        ready = getattr(self._provider, "ready", None) if self._provider is not None else None
        if type(ready) is not bool:
            ready = bool((os.environ.get(self.profile.api_key_env) or "").strip())
        return {"ready": ready, "status": "ready" if ready else "not_connected"}

    def auto_condition_allowed(self, condition):
        return self.enabled and self.adoption_mode == "auto" and condition in self.profile.auto_conditions

    def _get_provider(self):
        with self._provider_lock:
            if self._closed:
                raise OSError("decision_service_closed")
            if self._provider is None:
                self._provider = OpenAIDecisionsProvider(api_key_env=self.profile.api_key_env, timeout_seconds=self.profile.timeout_seconds)
            return self._provider

    def _base(self, *, status="uncertain", phase="after_action", request_id=None, execution_request_id=None):
        return {"status": status, "verdict": "uncertain", "source": "openai_decisions", "model": MODEL,
                "phase": phase, "request_id": request_id, "execution_request_id": execution_request_id,
                "predicates": {}, "probabilities": {}, "usage": None, "elapsed_ms": 0,
                "http_elapsed_ms": None, "server_processing_ms": None, "provider_request_id": None,
                "adopted": False, "authorizes_action": False, "automatic_retry_allowed": False, "evidence_hashes": []}

    def _prepare(self, kwargs):
        binding, frames = prepare_request(self.session_dir, **kwargs)
        policy = {"mode": self.profile.mode, "pass_threshold": self.profile.pass_threshold,
                  "fail_threshold": self.profile.fail_threshold, "auto_conditions": self.profile.auto_conditions}
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
        root = self.session_dir.resolve(strict=True)
        storage = root / "judgments"
        path = storage / "decisions.sqlite3"
        if (not storage.is_dir() or storage.resolve(strict=True) != storage
                or path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path):
            raise OSError("decision_persistence_path_invalid")
        # 恢复认证不创建目录或表；URI 编码保留空格、井号等合法路径字符。
        return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2, isolation_level=None)

    def _saved(self, row, binding, digest):
        base = {**self._base(phase=binding["phase"], request_id=binding["request_id"], execution_request_id=binding["execution_request_id"]), **binding,
                "request_sha256": digest, "evidence_hashes": [f["sha256"] for f in binding["frames"]]}
        if row[0] != digest:
            return {**base, "status": "conflict", "reason": "decision_request_id_conflict"}
        try:
            blob = row[1] if row[1] is not None else row[2]
            value = json.loads(_protect(blob, self._entropy(binding["request_id"]), decrypt=True).decode("utf-8"))
            if (not isinstance(value, dict) or value.get("request_sha256") != digest
                    or any(value.get(key) != binding[key] for key in binding)
                    or value.get("authorizes_action") is not False or value.get("automatic_retry_allowed") is not False
                    or value.get("evidence_hashes") != base["evidence_hashes"]
                    or value.get("status") not in ("completed", "refused", "timeout", "error", "not_connected", "unknown", "limited")
                    or value.get("verdict") not in ("success", "failure", "uncertain")
                    or type(value.get("adopted")) is not bool):
                raise ValueError("decision_saved_binding_invalid")
            if value["adopted"] and (not self.auto_condition_allowed(binding["condition"]) or value["status"] != "completed" or value["verdict"] == "uncertain"):
                raise ValueError("decision_saved_adoption_invalid")
            return value
        except (OSError, ValueError, UnicodeError, TypeError):
            return {**base, "status": "error", "reason": "decision_saved_result_invalid"}

    def evaluate(self, *, request_id, execution_request_id, condition, frames, mode="execution", phase="after_action",
                 run_id=None, step_id=None, action=None):
        base = self._base(phase=phase, request_id=request_id, execution_request_id=execution_request_id)
        if not self.enabled:
            return {**base, "status": "disabled"}
        if self._closed:
            return {**base, "status": "error", "reason": "decision_service_closed"}
        started = perf_counter_ns()
        kwargs = {"request_id": request_id, "execution_request_id": execution_request_id, "condition": condition,
                  "frames": frames, "mode": mode, "phase": phase, "run_id": run_id, "step_id": step_id, "action": action}
        try:
            binding, upload_frames, digest = self._prepare(kwargs)
        except (OSError, ValueError, TypeError):
            return {**base, "status": "rejected", "reason": "decision_evidence_or_binding_invalid"}
        base.update(binding, request_sha256=digest, evidence_hashes=[f["sha256"] for f in binding["frames"]])
        scope = "learning:" + run_id if mode == "learning" else "execution"
        try:
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                prior = db.execute("SELECT request_sha256, result_blob, marker_blob FROM dispatches WHERE request_id=?", (request_id,)).fetchone()
                if prior is not None:
                    db.commit()
                    return self._saved(prior, binding, digest)
                count = db.execute("SELECT COUNT(*) FROM dispatches WHERE scope=? AND dispatched=1", (scope,)).fetchone()[0]
                if count >= self.profile.request_cap:
                    limited = {**base, "status": "limited", "reason": "decision_scope_request_cap"}
                    encrypted = _protect(_canonical(limited), self._entropy(request_id))
                    db.execute("INSERT INTO dispatches(request_id, request_sha256, scope, dispatched, marker_blob, result_blob) VALUES(?,?,?,0,?,?)", (request_id, digest, scope, encrypted, encrypted))
                    db.commit()
                    return limited
                # 先确认认证持久化可用，再冻结发送；任何崩溃均留下不可重派标记。
                marker = {**base, "status": "unknown", "reason": "decision_prior_dispatch_unresolved"}
                encrypted = _protect(_canonical(marker), self._entropy(request_id))
                db.execute("INSERT INTO dispatches(request_id, request_sha256, scope, dispatched, marker_blob) VALUES(?,?,?,1,?)", (request_id, digest, scope, encrypted))
                db.commit()
        except (sqlite3.Error, OSError):
            return {**base, "status": "error", "reason": "decision_persistence_unavailable"}
        try:
            answer = self._get_provider().judge({"condition": condition, "phase": phase, "frames": upload_frames,
                                           "action": binding["action"], "request_sha256": digest})
            if (not isinstance(answer, dict) or set(answer) != {"request_sha256", "predicates", "usage", "http_elapsed_ms", "server_processing_ms", "provider_request_id"}
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
            danger = "unsafe_effect" if phase == "before_action" else "visible_error"
            predicates = answer["predicates"]
            if not isinstance(predicates, dict) or set(predicates) != {"condition_met", danger}:
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
            base.update({key: answer[key] for key in ("http_elapsed_ms", "server_processing_ms", "provider_request_id")},
                        usage=usage, predicates=predicates, probabilities=probabilities)
            if any(value is None for value in probabilities.values()):
                base.update(status="refused", reason="decision_predicate_refused")
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
        except TimeoutError:
            base.update(status="timeout", reason="decision_provider_timeout")
        except (OSError, ValueError, KeyError, TypeError):
            base.update(status="error", reason="decision_provider_or_contract_error")
        # 完成和关闭共用锁；先完成的认证记录保留，先关闭则只保存不确定结果。
        with self._provider_lock:
            if self._closed:
                base.update(status="error", verdict="uncertain", adopted=False, reason="decision_service_closed_during_evaluation")
            base["elapsed_ms"] = (perf_counter_ns() - started) / 1_000_000
            try:
                encrypted = _protect(_canonical(base), self._entropy(request_id))
                with closing(self._connect()) as db:
                    changed = db.execute("UPDATE dispatches SET result_blob=? WHERE request_id=? AND request_sha256=? AND result_blob IS NULL", (encrypted, request_id, digest)).rowcount
                    if changed != 1:
                        raise OSError("decision_result_write_conflict")
            except (sqlite3.Error, OSError, ValueError, TypeError):
                return {**base, "status": "error", "verdict": "uncertain", "adopted": False, "reason": "decision_result_persistence_failed"}
        return base

    def validate_result(self, result, **original_evaluate_kwargs):
        if not self.enabled or self._closed or not isinstance(result, dict):
            return False
        try:
            kwargs = original_evaluate_kwargs or {key: result[key] for key in (
                "request_id", "execution_request_id", "condition", "frames", "mode", "phase", "run_id", "step_id", "action")}
            binding, _, digest = self._prepare(kwargs)
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
