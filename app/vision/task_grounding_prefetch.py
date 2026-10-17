"""前步原图上的一次只读定位；成功落账前不签发执行票据。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic, perf_counter_ns
from uuid import uuid4

from app.core.json_snapshot import write_json_snapshot
from app.core.vision_admission_contract import AgentCommandError
from app.execution.task_plan_cancellation import assert_no_queued_plan_cancel
from app.execution.task_plan_review import digest, policy_snapshot
from .grounding_handoff import GroundingHandoffError
from .recognition_source import ClientVisionCapabilities


def _visual_step(step):
    action, verification = step["action"], step["verification"]
    return (action["kind"] in {"click", "input_sequence"} and "target" not in action
        and verification["kind"] == "agent_judgment"
        and not any(key in verification for key in ("wait_policy", "render_grace_ms")))


class TaskGroundingPrefetch:
    def __init__(self, manager):
        self.manager = manager
        self.epoch = uuid4().hex
        self.root = manager.store.session_root / "task-grounding-prefetch"
        self._lock = RLock()
        self._entries = {}
        self._active = None
        self._closed = False

    def _configuration(self):
        profile = getattr(self.manager.api_grounder, "profile", None)
        return {"recognition": self.manager.configuration.model_dump(),
            "profile": profile.model_dump() if callable(getattr(profile, "model_dump", None)) else None}

    def _save(self, entry):
        self.root.mkdir(parents=True, exist_ok=True)
        write_json_snapshot(self.root / (entry["record"]["key"] + ".json"), entry["record"])

    def _ineligible(self, state, reason):
        key = "eligibility-" + digest([self.epoch, state["run_id"], state["pending"]["execution_request_id"]])[:32]
        entry = {"record": {"schema": "task_grounding_prefetch.v1", "key": key, "epoch": self.epoch,
            "run_id": state["run_id"], "phase": "ineligible", "eligibility": reason,
            "api_attempts": 0, "authorizes_action": False}}
        with self._lock:
            if key not in self._entries:
                self._entries[key] = entry
                self._save(entry)

    def begin(self, backend, state, step, capture, target_reader):
        source = backend._source(state)
        plan = source["plan"]
        policy = policy_snapshot(getattr(self.manager.coordinator, "_decision_service", None))
        decision_profile = getattr(getattr(self.manager.coordinator, "_decision_service", None), "profile", None)
        index = next(i for i, item in enumerate(plan["steps"]) if item["step_id"] == step["step_id"])
        if (self._closed or self.manager.configuration.source != "external_api"
                or self.manager.api_grounder is None or plan["schema_version"] != "task_plan.v3"
                or policy.get("adoption_mode", policy.get("mode")) != "auto"
                or getattr(decision_profile, "scene_precheck", "off") != "off"
                or not _visual_step(step) or index + 1 == len(plan["steps"])
                or not _visual_step(plan["steps"][index + 1])):
            self._ineligible(state, "source_or_step_not_eligible")
            return None
        next_step = plan["steps"][index + 1]
        previous_command = state["pending"]["suggested_command"]
        command = backend._bound_command(state, next_step, previous_command.get("vision_capabilities"), source=source)
        if any(previous_command.get(key) is not None for key in ("observation_wait_ms", "observation_condition")):
            self._ineligible(state, "explicit_observation")
            return None
        request = command["request"]
        goal = request["goal"] if command["kind"] == "step" else request["field_goal"]
        if (not callable(target_reader) or target_reader() != state["target_identity"]
                or capture.get("window_identity") != state["target_identity"]):
            self._ineligible(state, "window_changed")
            return None
        assert_no_queued_plan_cancel(backend.session, state["run_id"])
        binding = {"epoch": self.epoch, "owner_id": backend.owner_id, "store_owner_id": self.manager.store.owner_id,
            "run_id": state["run_id"], "plan_id": state["plan_id"], "plan_sha256": state["plan_sha256"],
            "previous_execution_id": state["pending"]["execution_request_id"],
            "capture_id": capture["capture_id"], "sha256": capture["sha256"],
            "next_step_id": next_step["step_id"],
            "next_execution_id": command["action_review"]["attempt_id"], "command_sha256": digest(command),
            "configuration_sha256": digest(self._configuration()), "window_identity": deepcopy(state["target_identity"])}
        key = digest(binding)
        with self._lock:
            if self._closed:
                return None
            if key in self._entries:
                return key
            if self._active is not None:
                self._discard(self._active, "superseded")
                if not self._active["done"].is_set():
                    self._ineligible(state, "previous_http_still_running")
                    return None
            request_id = "pf-" + key[:40]
            pending = self.manager.store.prepare(request_id, goal=goal, capture=deepcopy(capture),
                configuration=self.manager.configuration,
                capabilities=ClientVisionCapabilities.model_validate(previous_command.get("vision_capabilities") or {}))
            timeout = min(45.0, getattr(getattr(self.manager.api_grounder, "profile", None), "timeout_seconds", 45.0))
            entry = {"record": {"schema": "task_grounding_prefetch.v1", "key": key, "epoch": self.epoch,
                "binding": binding, "run_id": state["run_id"], "goal": goal, "command": deepcopy(command),
                "source_capture": deepcopy(capture), "grounding_request_id": request_id,
                "phase": "requesting", "eligibility": "external_api_v3_visual_linear_next_step",
                "api_attempts": 0, "released": False, "authorizes_action": False,
                "measurement": {"started_ns": perf_counter_ns()}},
                "backend": backend, "target_reader": target_reader,
                "pending": pending, "stop": Event(), "done": Event(), "deadline": monotonic() + timeout}
            self._entries[key] = self._active = entry
            self._save(entry)
            thread = Thread(target=self._invoke, args=(entry,), name="task-grounding-prefetch-" + key[:12], daemon=True)
            entry["thread"] = thread
            thread.start()
            return key

    def _invoke(self, entry):
        record = entry["record"]
        try:
            with self._lock:
                if entry["stop"].is_set():
                    return
                record["api_attempts"] = 1
                record["measurement"]["api_started_ns"] = perf_counter_ns()
                self._save(entry)
            remaining = entry["deadline"] - monotonic()
            if remaining <= 0:
                raise AgentCommandError("task_grounding_prefetch_timeout")
            response = self.manager.api_grounder.ground(request_id=record["grounding_request_id"],
                capture=deepcopy(entry["pending"]["capture"]), goal=record["goal"], timeout_seconds=remaining)
            with self._lock:
                record["provider"] = deepcopy(response.get("provider"))
                if entry["stop"].is_set():
                    return
                if monotonic() >= entry["deadline"]:
                    raise AgentCommandError("task_grounding_prefetch_timeout")
                pending = self.manager.store.resolve(record["grounding_request_id"], response["result"])
                if pending["phase"] != "grounding_ready":
                    raise AgentCommandError("task_grounding_prefetch_request_" + pending["phase"])
                entry["pending"] = pending
                record["phase"] = "ready"
        except Exception as error:
            with self._lock:
                if getattr(error, "provider", None) is not None:
                    record["provider"] = deepcopy(error.provider)
                if getattr(error, "attempt", None) is not None:
                    record["attempt"] = deepcopy(error.attempt)
                record["error_code"] = (getattr(error, "code", None) or
                    (str(error) if isinstance(error, AgentCommandError) and str(error).startswith("task_grounding_prefetch_")
                     else type(error).__name__))
                record["error_type"] = type(error).__name__
                if not entry["stop"].is_set():
                    record["phase"] = "failed"
                self._cancel_pending(entry)
        finally:
            with self._lock:
                record["measurement"]["ended_ns"] = perf_counter_ns()
                try:
                    self._save(entry)
                finally:
                    entry["done"].set()

    def _cancel_pending(self, entry):
        try:
            self.manager.store.cancel(entry["record"]["grounding_request_id"])
        except GroundingHandoffError as error:
            # 所有权变化不能修改别人的交接；保留明确拒绝，仍使本地预取失效。
            entry["record"]["cancellation_error_code"] = error.code

    def _discard(self, entry, reason):
        if entry["record"]["phase"] in {"consumed", "discarded"}:
            return
        entry["stop"].set()
        entry["record"].update(phase="discarded", released=False, discard_reason=reason)
        self._cancel_pending(entry)
        self._save(entry)

    def discard(self, reason, *, run_id=None):
        with self._lock:
            if self._active is not None and (run_id is None or self._active["record"]["run_id"] == run_id):
                self._discard(self._active, reason)

    def settled(self, backend, previous_state, settled, result):
        with self._lock:
            entry = self._active
            if entry is None or entry["record"]["binding"]["previous_execution_id"] != previous_state["pending"]["execution_request_id"]:
                return
            record = entry["record"]
            if (result["verdict"] != "success" or result["judged_by"] != "decision"
                    or result.get("observation") is not None or result.get("video_playback") is not None
                    or settled.get("status") != "ready"
                    or not settled.get("history") or settled["history"][-1].get("verdict") != "success"
                    or settled["history"][-1].get("execution_request_id") != record["binding"]["previous_execution_id"]):
                self._discard(entry, "previous_not_automatic_success")
                return
            backend._source(settled)
            if entry["target_reader"]() != record["binding"]["window_identity"]:
                self._discard(entry, "window_changed")
                return
            assert_no_queued_plan_cancel(backend.session, settled["run_id"])
            if record["phase"] != "discarded":
                record["released"] = True
                record["measurement"]["released_ns"] = perf_counter_ns()
                self._save(entry)

    def _current(self, entry, job, goal):
        record, binding = entry["record"], entry["record"]["binding"]
        if goal != record["goal"]:
            return "goal_changed"
        if (job.command_id != binding["next_execution_id"] or digest(job.command) != binding["command_sha256"]
                or getattr(job, "learning_context", None) is not None):
            return "command_changed"
        if digest(self._configuration()) != binding["configuration_sha256"]:
            return "configuration_changed"
        if entry["target_reader"]() != binding["window_identity"] or any(
                job.target.get(key) != binding["window_identity"][key] for key in ("handle", "process_id")):
            return "window_changed"
        state = entry["backend"].status(binding["run_id"])
        entry["backend"]._source(state)
        pending = state.get("pending") or {}
        if (entry["backend"].owner_id != binding["owner_id"] or self.manager.store.owner_id != binding["store_owner_id"]
                or binding["epoch"] != self.epoch or state["owner_id"] != binding["owner_id"]
                or state["plan_id"] != binding["plan_id"] or state["plan_sha256"] != binding["plan_sha256"]
                or state["status"] != "pending"
                or pending.get("execution_request_id") != job.command_id
                or digest(pending.get("suggested_command")) != binding["command_sha256"]):
            return "plan_changed"
        if (entry["backend"].session / "closing.json").exists() or job.cancelled:
            return "cancelled_or_closing"
        assert_no_queued_plan_cancel(entry["backend"].session, binding["run_id"])
        raw = Path(record["source_capture"]["image_path"]).read_bytes()
        if sha256(raw).hexdigest() != binding["sha256"]:
            return "source_capture_changed"
        return None

    def consume(self, job, goal):
        if getattr(job, "prefetch_checked", False):
            return None
        job.prefetch_checked = True
        with self._lock:
            entry = self._active
            if entry is None or self._closed or entry["record"]["phase"] in {"consumed", "discarded"}:
                stale = [item for item in self._entries.values() if "thread" in item and not item["done"].is_set()]
            else:
                stale = []
        if entry is None or self._closed or entry["record"]["phase"] in {"consumed", "discarded"}:
            # 已弃用但还在途的请求仍占原供应商并发槽；不能马上再发导致 api_busy。
            for item in stale:
                if not item["done"].wait(max(0, item["deadline"] - monotonic())):
                    raise AgentCommandError("task_grounding_prefetch_previous_request_unsettled")
            if (entry is not None and entry["record"]["binding"]["next_execution_id"] == job.command_id
                    and entry["record"].get("error_code") and entry["record"]["api_attempts"]):
                raise AgentCommandError("task_grounding_prefetch_failed:" + entry["record"]["error_code"])
            return None
        with self._lock:
            reason = self._current(entry, job, goal)
            if reason is not None:
                self._discard(entry, reason)
                raise AgentCommandError("task_grounding_prefetch_" + reason)
            elif not entry["record"]["released"]:
                raise AgentCommandError("task_grounding_prefetch_previous_success_required")
        if not entry["done"].wait(max(0, entry["deadline"] - monotonic())):
            self.discard("timeout")
            raise AgentCommandError("task_grounding_prefetch_timeout")
        with self._lock:
            record = entry["record"]
            if record["phase"] == "discarded":
                if record.get("error_code") and record["api_attempts"]:
                    raise AgentCommandError("task_grounding_prefetch_failed:" + record["error_code"])
                return None
            reason = self._current(entry, job, goal)
            if reason is not None:
                self._discard(entry, reason)
                raise AgentCommandError("task_grounding_prefetch_" + reason)
            provider = record.get("provider")
            self.manager._record_recognition_call(job, record["grounding_request_id"], record["binding"]["capture_id"],
                provider=provider, attempt=record.get("attempt") or (provider or {}).get("attempt"))
            if record["phase"] == "failed":
                raise AgentCommandError("task_grounding_prefetch_failed:" + record["error_code"])
            pending = self.manager.store.get(record["grounding_request_id"])
            if pending["phase"] != "grounding_ready":
                raise AgentCommandError("task_grounding_prefetch_request_" + pending["phase"])
            record["phase"] = "consumed"
            record["measurement"]["consumed_ns"] = perf_counter_ns()
            self._save(entry)
            with self.manager._condition:
                self.manager._update(job, grounding_prefetch={"status": "consumed", "record_path": str(
                    self.root / (record["key"] + ".json")), "api_attempts": record["api_attempts"]})
            return pending

    def close(self, timeout=30):
        deadline = monotonic() + timeout
        with self._lock:
            self._closed = True
            self.discard("host_closing")
            threads = [item["thread"] for item in self._entries.values() if "thread" in item]
        for thread in threads:
            thread.join(max(0, deadline - monotonic()))
        return all(not thread.is_alive() for thread in threads)
