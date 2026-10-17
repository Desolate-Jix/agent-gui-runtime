"""有限观察复用原 tick；持久声明先于采集或判断，未知声明不重试。"""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter_ns
from uuid import uuid4

from .task_plan_cancellation import assert_no_queued_plan_cancel, TaskPlanCancelPending
from .task_plan_review import assess, digest, policy_snapshot, review_context
from .task_plan_conditions import semantic_binding
from .task_plan_observation_capture import capture_followup
from .task_plan_observation_evidence import reference


CLOCK_ID = uuid4().hex


def now_ns():
    return perf_counter_ns()


def _put(path, value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


class ObservationLedger:
    def __init__(self, backend, execution_id):
        self.backend, self.session = backend, backend.session
        self.root = self.session / "task-plan-observations" / execution_id

    def read(self):
        events, previous = [], None
        for index, path in enumerate(sorted(self.root.glob("*.json"))):
            if path.name != f"{index:04d}.json" or not path.resolve().is_relative_to(self.session):
                raise ValueError("task_plan_observation_chain_invalid")
            value = json.loads(path.read_text(encoding="utf-8"))
            if (set(value) != {"schema", "sequence", "previous_sha256", "event", "payload"}
                    or value["schema"] != "task_plan_observation_event.v1" or value["sequence"] != index
                    or value["previous_sha256"] != previous or not isinstance(value["payload"], dict)):
                raise ValueError("task_plan_observation_chain_invalid")
            previous = reference(self.session, path)["sha256"]
            events.append(value)
        if events and events[0]["event"] != "opened":
            raise ValueError("task_plan_observation_chain_invalid")
        return events

    def append(self, event, payload):
        with self.backend._locked():
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.root.resolve().is_relative_to(self.session):
                raise ValueError("task_plan_observation_ledger_outside_session")
            events = self.read()
            index = len(events)
            previous = reference(self.session, self.root / f"{index-1:04d}.json")["sha256"] if index else None
            _put(self.root / f"{index:04d}.json", {"schema": "task_plan_observation_event.v1", "sequence": index,
                "previous_sha256": previous, "event": event, "payload": deepcopy(payload)})

    def header(self):
        events = self.read()
        return events[0]["payload"] if events else None

    def input_refs(self):
        refs = deepcopy(self.header()["input_evidence_refs"])
        refs.extend(deepcopy(event["payload"]["image_ref"]) for event in self.read() if event["event"] == "captured")
        return refs

    def artifacts(self):
        refs = self.input_refs()
        for index, event in enumerate(self.read()):
            refs.append(reference(self.session, self.root / f"{index:04d}.json"))
            if event["event"] == "assessed":
                refs.append(deepcopy(event["payload"]["assessment_ref"]))
        return refs

    def summary(self):
        events = self.read()
        claims = [event["payload"] for event in events if event["event"] == "capture_claimed"]
        assessments = [event["payload"] for event in events if event["event"] == "assessed"]
        refs = [reference(self.session, self.root / f"{index:04d}.json") for index in range(len(events))]
        return {"schema": "task_plan_observation_binding.v1", "ledger_refs": refs,
            "ledger_sha256": digest(refs), "input_evidence_refs": self.input_refs(),
            "evidence_set_sha256": digest(self.input_refs()),
            "assessment_round": claims[-1]["round"] if claims else 0,
            "assessment_ref": deepcopy(assessments[-1]["assessment_ref"]) if assessments else None,
            "original_receipt_sha256": self.header()["original_receipt_sha256"]}

    def last_assessment(self):
        events = [event["payload"] for event in self.read() if event["event"] == "assessed"]
        if not events:
            return None
        ref = events[-1]["assessment_ref"]
        if reference(self.session, self.session / ref["path"]) != ref:
            raise ValueError("task_plan_observation_assessment_changed")
        return json.loads((self.session / ref["path"]).read_text(encoding="utf-8"))

    def finished(self):
        events = [event["payload"] for event in self.read() if event["event"] == "finished"]
        if len(events) > 1:
            raise ValueError("task_plan_observation_finish_conflict")
        return events[0] if events else None


def projection(backend, state):
    pending = state.get("pending")
    if not pending:
        return None
    ledger = ObservationLedger(backend, pending["execution_request_id"])
    if ledger.header() is None:
        return None
    return {"observation_pending": ledger.finished() is None,
        "observation": ledger.summary(), "observation_read_only": True}


def abort_observation(backend, execution_id, error):
    ledger = ObservationLedger(backend, execution_id)
    if ledger.header() is not None and ledger.finished() is None:
        ledger.append("finished", {"reason": "task_plan_observation_validation_failed",
            "error_type": type(error).__name__, "finished_ns": now_ns()})


def _remaining(header):
    if header["clock_id"] != CLOCK_ID:
        raise ValueError("task_plan_observation_clock_changed")
    elapsed = (now_ns() - header["started_ns"]) / 1_000_000
    if elapsed < 0:
        raise ValueError("task_plan_observation_clock_changed")
    budget_ms = (header["grace"]["budget_ms"] if header.get("mode") == "adaptive_grace" else 12000)
    return elapsed, max(0.0, (budget_ms - elapsed) / 1000)


def _guard(backend, state, ledger, service, target_reader, *, allow_expired=False):
    assert_no_queued_plan_cancel(backend.session, state["run_id"])
    if (backend.session / "closing.json").exists():
        raise ValueError("task_plan_observation_session_closing")
    backend._require_owner(state)
    source = backend._source(state)
    header = ledger.header()
    current = backend.status(state["run_id"])
    if current["status"] == "cancel_requested":
        raise ValueError("task_plan_observation_cancelled")
    if (current.get("pending") != state["pending"] or current["owner_id"] != header["owner_id"]
            or current["plan_sha256"] != header["plan_sha256"] or source["plan_sha256"] != header["plan_sha256"]
            or reference(backend.session, backend._source_path(state["plan_id"])) != header["source_ref"]):
        raise ValueError("task_plan_observation_source_changed")
    for ref in ledger.input_refs():
        if reference(backend.session, backend.session / ref["path"]) != ref:
            raise ValueError("task_plan_observation_original_evidence_changed")
    if policy_snapshot(service) != header["policy_snapshot"]:
        raise ValueError("task_plan_observation_profile_changed")
    step = backend.pinned_step(state["run_id"], state["pending"]["step_id"])
    if header.get("condition_snapshot") != semantic_binding(source["plan"], step).get("condition_snapshot"):
        raise ValueError("task_plan_observation_condition_changed")
    if not callable(target_reader) or target_reader() != header["target_identity"]:
        raise ValueError("task_plan_observation_window_changed")
    elapsed, remaining = _remaining(header)
    if remaining <= 0 and not allow_expired:
        raise ValueError("task_plan_observation_budget_expired")
    return elapsed, remaining


def _outcome(ledger, *, pending=False, reason=None):
    saved = ledger.last_assessment()
    return {"pending": pending, "reason": reason,
        "decision": saved["result"] if saved else None, "valid": bool(saved and saved["validated"]),
        "policy": ledger.header()["policy_snapshot"], "observation": ledger.summary(), "refs": ledger.artifacts()}


def _finish(ledger, reason):
    if ledger.finished() is None:
        ledger.append("finished", {"reason": reason, "finished_ns": now_ns()})
    return _outcome(ledger, reason=ledger.finished()["reason"])


def drive_observation(backend, state, step, frame, original_frame, refs, service, *, coordinator, target_reader):
    ledger = ObservationLedger(backend, state["pending"]["execution_request_id"])
    if ledger.header() is None:
        source_ref = reference(backend.session, backend._source_path(state["plan_id"]))
        input_refs = deepcopy(refs) + [source_ref]
        receipt_ref = next(ref for ref in refs if ref["path"] == "responses/" + state["pending"]["execution_request_id"] + ".json")
        semantic = semantic_binding(backend._source(state)["plan"], step)
        ledger.append("opened", {"run_id": state["run_id"], "step_id": step["step_id"],
            "execution_request_id": state["pending"]["execution_request_id"], "plan_id": state["plan_id"],
            "plan_sha256": state["plan_sha256"], "source_ref": source_ref, "owner_id": state["owner_id"],
            "session_directory": state["session_directory"], "target_identity": deepcopy(state["target_identity"]),
            "after": deepcopy(frame), "original_frame": deepcopy(original_frame),
            "input_evidence_refs": input_refs, "original_receipt_sha256": receipt_ref["sha256"],
            "policy_snapshot": policy_snapshot(service), "clock_id": CLOCK_ID, "started_ns": now_ns(),
            **({"condition_snapshot": semantic["condition_snapshot"]} if "condition_snapshot" in semantic else {})})
    header = ledger.header()
    if (header["run_id"] != state["run_id"] or header["step_id"] != step["step_id"]
            or header["after"] != frame or header["session_directory"] != str(backend.session)):
        raise ValueError("task_plan_observation_binding_changed")
    if ledger.finished() is not None:
        return _outcome(ledger, reason=ledger.finished()["reason"])
    try:
        _guard(backend, state, ledger, service, target_reader)
    except TaskPlanCancelPending:
        raise
    except ValueError as error:
        return _finish(ledger, str(error))
    events = ledger.read()
    api_claims = [event["payload"] for event in events if event["event"] == "assessment_claimed"]
    assessed = [event["payload"] for event in events if event["event"] == "assessed"]
    capture_claims = [event["payload"] for event in events if event["event"] == "capture_claimed"]
    completed_captures = [event["payload"] for event in events if event["event"] in {"captured", "capture_rejected"}]
    if len(api_claims) > len(assessed):
        return _finish(ledger, "task_plan_observation_assessment_unknown")
    if len(capture_claims) > len(completed_captures):
        return _finish(ledger, "task_plan_observation_capture_unknown")

    def evaluate(round_number, frames):
        elapsed, remaining = _guard(backend, state, ledger, service, target_reader)
        if len(api_claims) >= 2:
            raise ValueError("task_plan_observation_request_limit")
        input_refs = ledger.input_refs()
        semantic = semantic_binding(backend._source(state)["plan"], step)
        binding = {"request_id": "task-decision-" + sha256(state["pending"]["execution_request_id"].encode()).hexdigest()[:32]
            + ("-observation-" + str(round_number) if round_number else ""),
            "execution_request_id": state["pending"]["execution_request_id"],
            **semantic, "frames": deepcopy(frames),
            "mode": "execution", "phase": "after_action", "run_id": state["run_id"], "step_id": step["step_id"],
            "review_context": review_context(backend._source(state)["plan"], step,
                source_id=state["plan_id"], source_sha256=state["plan_sha256"]),
            "assessment_context": {"assessment_round": round_number, "original_receipt_sha256": header["original_receipt_sha256"],
                "evidence_set_sha256": digest(input_refs), "elapsed_ms": elapsed, "timeout_seconds": remaining}}
        ledger.append("assessment_claimed", {"round": round_number, "binding": binding, "input_evidence_refs": input_refs})
        value, valid = assess(service, binding, v2=True)
        directory = backend.session / "task-plan-decisions"
        directory.mkdir(exist_ok=True)
        filename = state["pending"]["execution_request_id"] + ("-observation-" + str(round_number) if round_number else "") + ".json"
        path = directory / filename
        _put(path, {"binding": binding, "result": value, "validated": valid, "policy_snapshot": header["policy_snapshot"]})
        ledger.append("assessed", {"round": round_number, "assessment_ref": reference(backend.session, path)})
        _guard(backend, state, ledger, service, target_reader)
        return value, valid

    if not api_claims:
        try:
            value, valid = evaluate(0, [frame])
        except TaskPlanCancelPending:
            raise
        except ValueError as error:
            return _finish(ledger, str(error))
        auto = header["policy_snapshot"].get("mode", header["policy_snapshot"].get("adoption_mode")) == "auto"
        if valid and auto and value.get("disposition") == "observe":
            ledger.append("observing", {"started_ns": now_ns()})
            return _outcome(ledger, pending=True)
        return _finish(ledger, "authenticated_decision" if valid and value.get("adopted") is True
            else value.get("reason", "decision_requested_agent_review"))
    observing = next((event["payload"] for event in events if event["event"] == "observing"), None)
    if observing is None:
        return _finish(ledger, "task_plan_observation_assessment_unknown")
    elapsed_observation = (now_ns() - observing["started_ns"]) / 1_000_000_000
    attempted = {claim["round"] for claim in capture_claims}
    if not attempted and elapsed_observation >= 1.5:
        ledger.append("slot_skipped", {"round": 1, "reason": "tick_after_later_slot"})
        attempted.add(1)
    attempted.update(event["payload"]["round"] for event in events if event["event"] == "slot_skipped")
    next_round = next((index for index in (1, 2) if index not in attempted), None)
    if next_round is not None and elapsed_observation < (.5 if next_round == 1 else 1.5):
        return _outcome(ledger, pending=True)
    if next_round is not None:
        ledger.append("capture_claimed", {"round": next_round, "claimed_ns": now_ns()})
        try:
            _, remaining = _guard(backend, state, ledger, service, target_reader)
            def cancelled():
                _guard(backend, state, ledger, service, target_reader)
                return False
            captured = capture_followup(coordinator, session_dir=backend.session, target_identity=header["target_identity"],
                original_frame=header["original_frame"], observation_id="task-observation-" + digest([
                    state["run_id"], state["pending"]["execution_request_id"], next_round])[:32],
                cancelled=cancelled, remaining_seconds=lambda: _remaining(header)[1])
            new_frame = captured["frame"]
            if (set(new_frame) != {"capture_id", "image_path", "sha256", "window_identity", "role"}
                    or new_frame["role"] != "observation" or new_frame["window_identity"] != header["target_identity"]
                    or new_frame["capture_id"] == frame["capture_id"]
                    or Path(new_frame["image_path"]).resolve() == Path(frame["image_path"]).resolve()):
                raise ValueError("task_plan_observation_capture_binding_invalid")
            previous_frames = [header["after"]] + [event["payload"]["frame"] for event in ledger.read()
                if event["event"] == "captured"]
            if any(new_frame["capture_id"] == previous["capture_id"]
                    or Path(new_frame["image_path"]).resolve() == Path(previous["image_path"]).resolve()
                    or Path(new_frame["image_path"]).samefile(previous["image_path"]) for previous in previous_frames):
                raise ValueError("task_plan_observation_capture_reused")
            image_ref = reference(backend.session, new_frame["image_path"])
            if image_ref["sha256"] != new_frame["sha256"]:
                raise ValueError("task_plan_observation_capture_hash_invalid")
            ledger.append("captured", {"round": next_round, "frame": new_frame, "image_ref": image_ref,
                "capture_elapsed_ms": captured["capture_elapsed_ms"], "completed_ns": now_ns()})
            _guard(backend, state, ledger, service, target_reader)
        except TaskPlanCancelPending as error:
            ledger.append("capture_rejected", {"round": next_round, "reason": str(error)})
            raise
        except ValueError as error:
            try:
                _guard(backend, state, ledger, service, target_reader)
            except TaskPlanCancelPending as cancelled_error:
                ledger.append("capture_rejected", {"round": next_round, "reason": str(cancelled_error)})
                raise
            except ValueError as guard_error:
                error = guard_error
            reason = getattr(error, "reason_code", None) or (str(error) if str(error).startswith("task_plan_")
                else "task_plan_observation_capture_failed:" + type(error).__name__)
            ledger.append("capture_rejected", {"round": next_round, "reason": reason})
            return _finish(ledger, reason)
        if next_round == 1:
            if now_ns() - observing["started_ns"] < 1_500_000_000:
                return _outcome(ledger, pending=True)
            ledger.append("slot_skipped", {"round": 2, "reason": "capture_crossed_later_slot"})
    captures = [event["payload"] for event in ledger.read() if event["event"] == "captured"]
    if not captures or captures[-1]["frame"]["sha256"] == frame["sha256"]:
        return _finish(ledger, "task_plan_observation_pixels_unchanged")
    latest = captures[-1]
    try:
        value, valid = evaluate(latest["round"], [frame, latest["frame"]])
    except TaskPlanCancelPending:
        raise
    except ValueError as error:
        return _finish(ledger, str(error))
    return _finish(ledger, "authenticated_decision" if valid and value.get("adopted") is True
        and value.get("disposition") == "continue" else "task_plan_observation_limit_reached"
        if valid and value.get("disposition") == "observe" else value.get("reason", "decision_requested_agent_review"))


def validate_observation(backend, state, observation, refs):
    ledger = ObservationLedger(backend, observation["execution_request_id"] if "execution_request_id" in observation
        else state["pending"]["execution_request_id"])
    if observation != ledger.summary() or ledger.finished() is None:
        raise ValueError("task_plan_observation_settlement_binding_invalid")
    header = ledger.header()
    if any(header[key] != state[key] for key in ("run_id", "plan_id", "plan_sha256", "owner_id", "session_directory", "target_identity")):
        raise ValueError("task_plan_observation_settlement_source_invalid")
    if any(ref not in refs for ref in ledger.artifacts()):
        raise ValueError("task_plan_observation_artifact_missing")
    step = backend.pinned_step(state["run_id"], state["pending"]["step_id"])
    if header.get("condition_snapshot") != semantic_binding(backend._source(state)["plan"], step).get("condition_snapshot"):
        raise ValueError("task_plan_observation_condition_changed")
    return ledger


def validate_decision_adoption(backend, state, ledger, frame, saved, *, service=None, target_reader=None):
    if ledger.header().get("mode") == "adaptive_grace":
        from .task_plan_adaptive_grace import validate_grace_adoption
        return validate_grace_adoption(backend, state, ledger, frame, saved,
            service=service, target_reader=target_reader)
    claims = [event["payload"] for event in ledger.read() if event["event"] == "assessment_claimed"]
    header = ledger.header()
    if not claims or len(claims) > 2 or ledger.finished()["reason"] != "authenticated_decision":
        raise ValueError("task_plan_observation_adoption_budget_invalid")
    assert_adoption_budget(ledger)
    claim = claims[-1]
    binding = deepcopy(claim["binding"])
    round_number = claim["round"]
    frames = [frame]
    if round_number:
        captures = [event["payload"] for event in ledger.read() if event["event"] == "captured"]
        if not captures or captures[-1]["round"] != round_number:
            raise ValueError("task_plan_observation_adoption_frame_invalid")
        frames.append(captures[-1]["frame"])
    step = backend.pinned_step(state["run_id"], state["pending"]["step_id"])
    source = backend._source(state)
    semantic = semantic_binding(source["plan"], step)
    expected_context = review_context(source["plan"], step,
        source_id=state["plan_id"], source_sha256=state["plan_sha256"])
    context = binding.get("assessment_context") or {}
    expected_id = "task-decision-" + sha256(state["pending"]["execution_request_id"].encode()).hexdigest()[:32]
    if round_number:
        expected_id += "-observation-" + str(round_number)
    if (saved.get("binding") != binding or saved.get("policy_snapshot") != header["policy_snapshot"]
            or binding.get("request_id") != expected_id or binding.get("frames") != frames
            or binding.get("execution_request_id") != state["pending"]["execution_request_id"]
            or binding.get("run_id") != state["run_id"] or binding.get("step_id") != step["step_id"]
            or any(binding.get(key) != value for key, value in semantic.items())
            or binding.get("condition_snapshot") != semantic.get("condition_snapshot")
            or header.get("condition_snapshot") != semantic.get("condition_snapshot")
            or binding.get("phase") != "after_action" or binding.get("mode") != "execution"
            or binding.get("review_context") != expected_context
            or context.get("assessment_round") != round_number
            or context.get("original_receipt_sha256") != header["original_receipt_sha256"]
            or context.get("evidence_set_sha256") != digest(claim["input_evidence_refs"])
            or claim["input_evidence_refs"] != ledger.input_refs()):
        raise ValueError("task_plan_observation_adoption_binding_invalid")
    assert_adoption_budget(ledger)
    return binding


def assert_adoption_budget(ledger):
    if ledger.header().get("mode") == "adaptive_grace":
        # 原渲染宽限只约束等待；末帧截图和原规则判断不重开观察预算。
        _remaining(ledger.header())
        if any(event["event"] == "adoption_rejected" for event in ledger.read()):
            raise ValueError("task_plan_observation_adoption_budget_invalid")
        return
    if (any(event["event"] == "adoption_rejected" for event in ledger.read())
            or _remaining(ledger.header())[1] <= 0):
        raise ValueError("task_plan_observation_adoption_budget_invalid")
