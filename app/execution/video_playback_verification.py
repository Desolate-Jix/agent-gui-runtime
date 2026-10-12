"""播放核验跨既有 tick 持久化；文件回放不初始化桌面或输入组件。"""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter_ns
from uuid import uuid4

from PIL import Image

from .task_plan_cancellation import assert_no_queued_plan_cancel, TaskPlanCancelPending
from .task_plan_conditions import semantic_binding, effective_plan_review_policy
from .task_plan_review import assess, digest, policy_snapshot, review_context
from .task_plan_observation_evidence import reference


CLOCK_ID = uuid4().hex
BUDGET_MS = 8000
MAX_SAMPLES = 7
LEGACY_ANALYSIS_POLICY = "video_playback_local.v1"
ANALYSIS_POLICY = "video_picture_change.v1"
DYNAMIC_ANALYSIS_POLICY = "dynamic_content_change.v1"
PICTURE_POLICIES = (ANALYSIS_POLICY, DYNAMIC_ANALYSIS_POLICY)
PICTURE_SAMPLES = 3


def now_ns():
    return perf_counter_ns()


def locate_player(*args, **kwargs):
    from .video_playback_observer import locate_player as locate
    return locate(*args, **kwargs)


def page_loading(*args, **kwargs):
    from .video_playback_observer import page_loading as loading
    return loading(*args, **kwargs)


def observe_player_frame(*args, **kwargs):
    from .video_playback_observer import observe_player_frame as observe
    return observe(*args, **kwargs)


def observation_evidence_refs(*args, **kwargs):
    from .video_playback_observer import observation_evidence_refs as references
    return references(*args, **kwargs)


def capture_followup(*args, **kwargs):
    from .task_plan_observation_capture import capture_followup as capture
    return capture(*args, **kwargs)


def _analysis(samples, region):
    from .video_playback_evidence import evaluate_playback_sequence
    frames = [{**deepcopy(item["frame"]), "elapsed_ms": item["elapsed_ms"]} for item in samples]
    return evaluate_playback_sequence(frames, region, [item["observation"] for item in samples])


def _put(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return raw


class VideoPlaybackLedger:
    def __init__(self, backend, execution_id):
        self.backend, self.session = backend, backend.session
        self.root = self.session / "task-plan-video-playback" / execution_id
        self._cached_events = None
        self._cached_refs = None
        self._integrity_error = None

    def read(self):
        if self._integrity_error is not None:
            raise ValueError(self._integrity_error)
        if self._cached_events is None:
            return self.refresh()
        return deepcopy(self._cached_events)

    def refresh(self):
        """外部边界重读完整字节链，不以文件时间或大小代替校验。"""
        if self._integrity_error is not None:
            raise ValueError(self._integrity_error)
        expected_refs = self._cached_refs
        self._cached_events = self._cached_refs = None
        events, refs, previous = [], [], None
        try:
            for index, path in enumerate(sorted(self.root.glob("*.json"))):
                resolved = path.resolve(strict=True)
                if path.name != f"{index:04d}.json" or path.is_symlink() or not resolved.is_relative_to(self.session):
                    raise ValueError("task_plan_video_chain_invalid")
                raw = resolved.read_bytes()
                value = json.loads(raw.decode("utf-8"))
                if (set(value) != {"schema", "sequence", "previous_sha256", "event", "payload"}
                        or value["schema"] != "video_playback_event.v1" or value["sequence"] != index
                        or value["previous_sha256"] != previous or not isinstance(value["payload"], dict)):
                    raise ValueError("task_plan_video_chain_invalid")
                previous = sha256(raw).hexdigest()
                refs.append({"path": resolved.relative_to(self.session).as_posix(), "sha256": previous})
                events.append(value)
            if events and events[0]["event"] != "opened":
                raise ValueError("task_plan_video_chain_invalid")
            if expected_refs is not None and refs[:len(expected_refs)] != expected_refs:
                raise ValueError("task_plan_video_chain_changed")
        except (OSError, ValueError, TypeError, KeyError) as error:
            self._integrity_error = (str(error) if str(error).startswith("task_plan_video_chain")
                else "task_plan_video_chain_invalid")
            raise ValueError(self._integrity_error) from None
        self._cached_events, self._cached_refs = events, refs
        return deepcopy(events)

    def _live_refs(self):
        self.read()
        try:
            paths = sorted(self.root.glob("*.json"))
            refs = [reference(self.session, path) for path in paths]
        except (OSError, ValueError):
            self._cached_events = self._cached_refs = None
            self._integrity_error = "task_plan_video_chain_invalid"
            raise ValueError(self._integrity_error) from None
        if refs != self._cached_refs:
            self._cached_events = self._cached_refs = None
            self._integrity_error = "task_plan_video_chain_changed"
            raise ValueError(self._integrity_error)
        return refs

    def append(self, event, payload):
        with self.backend._locked():
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.root.resolve().is_relative_to(self.session):
                raise ValueError("task_plan_video_ledger_outside_session")
            events = self.refresh()
            index = len(events)
            previous = self._cached_refs[-1]["sha256"] if index else None
            path = self.root / f"{index:04d}.json"
            value = {"schema": "video_playback_event.v1", "sequence": index,
                "previous_sha256": previous, "event": event, "payload": deepcopy(payload)}
            raw = _put(path, value)
            self._cached_events.append(value)
            self._cached_refs.append({"path": path.relative_to(self.session).as_posix(), "sha256": sha256(raw).hexdigest()})

    def payloads(self, event):
        return [item["payload"] for item in self.read() if item["event"] == event]

    def header(self):
        events = self.read()
        return events[0]["payload"] if events else None

    def locator(self):
        values = self.payloads("located")
        if len(values) > 1:
            raise ValueError("task_plan_video_locator_conflict")
        return values[0]["locator"] if values else None

    def samples(self):
        keys = ("frame", "elapsed_ms") if self.header()["analysis_policy"] in PICTURE_POLICIES else ("frame", "elapsed_ms", "observation")
        return [{key: deepcopy(item[key]) for key in keys}
            for item in self.payloads("captured")]

    def localization_frame(self):
        readiness = self.payloads("readiness_captured")
        original = self.header()["original_frame"]
        if readiness and readiness[-1]["page_loading"] is False:
            return {**deepcopy(readiness[-1]["frame"]),
                **{key: deepcopy(original[key]) for key in ("image_size", "window_rect")}}
        return original

    def input_refs(self):
        refs = deepcopy(self.header()["input_evidence_refs"])
        for item in (self.locator() or {}).get("refs", []):
            if item not in refs:
                refs.append(deepcopy(item))
        refs.extend(deepcopy(item["image_ref"]) for item in self.payloads("captured"))
        refs.extend(deepcopy(item["image_ref"]) for item in self.payloads("readiness_captured"))
        return refs

    def artifacts(self):
        refs = self.input_refs()
        for item in self.payloads("captured"):
            refs.extend(deepcopy(ref) for ref in item.get("observation_refs", []) if ref not in refs)
        refs.extend(self._live_refs())
        refs.extend(deepcopy(item["assessment_ref"]) for item in self.payloads("assessed"))
        return refs

    def last_assessment(self):
        values = self.payloads("assessed")
        if not values:
            return None
        ref = values[-1]["assessment_ref"]
        if reference(self.session, self.session / ref["path"]) != ref:
            raise ValueError("task_plan_video_assessment_changed")
        return json.loads((self.session / ref["path"]).read_text(encoding="utf-8"))

    def finished(self):
        values = self.payloads("finished")
        if len(values) > 1:
            raise ValueError("task_plan_video_finish_conflict")
        return values[0] if values else None

    def summary(self):
        refs = self._live_refs()
        analyses = self.payloads("analyzed")
        assessments = self.payloads("assessed")
        schema = {ANALYSIS_POLICY: "video_playback_binding.v2", DYNAMIC_ANALYSIS_POLICY: "dynamic_content_binding.v1",
            LEGACY_ANALYSIS_POLICY: "video_playback_binding.v1"}[self.header()["analysis_policy"]]
        return {"schema": schema, "execution_request_id": self.header()["execution_request_id"],
            "ledger_refs": refs, "ledger_sha256": digest(refs), "input_evidence_refs": self.input_refs(),
            "evidence_set_sha256": digest(self.input_refs()), "samples": self.samples(),
            "readiness_observations": self.payloads("readiness_captured"),
            "region": deepcopy((self.locator() or {}).get("region")),
            "analysis": deepcopy(analyses[-1]["analysis"]) if analyses else None,
            "assessment_round": 1 if assessments else 0,
            "assessment_ref": deepcopy(assessments[-1]["assessment_ref"]) if assessments else None,
            "original_receipt_sha256": self.header()["original_receipt_sha256"],
            "elapsed_ms": self.finished()["elapsed_ms"] if self.finished() else self.payloads("captured")[-1]["elapsed_ms"]
                if self.payloads("captured") else self.payloads("readiness_captured")[-1]["elapsed_ms"]
                if self.payloads("readiness_captured") else 0}


def projection(backend, state):
    if not state.get("pending"):
        return None
    ledger = VideoPlaybackLedger(backend, state["pending"]["execution_request_id"])
    if ledger.header() is None:
        return None
    return {"observation_pending": ledger.finished() is None, "video_playback": ledger.summary(),
        "observation_read_only": True}


def abort_video_playback(backend, execution_id, error):
    ledger = VideoPlaybackLedger(backend, execution_id)
    if ledger.header() is not None and ledger.finished() is None:
        _finish(ledger, "task_plan_video_validation_failed", error_type=type(error).__name__)


def _remaining(header):
    if header["clock_id"] != CLOCK_ID or now_ns() < header["started_ns"]:
        raise ValueError("task_plan_video_clock_changed")
    elapsed = (now_ns() - header["started_ns"]) / 1e6
    return elapsed, max(0, (BUDGET_MS - elapsed) / 1000)


def _guard(backend, state, ledger, service, target_reader):
    assert_no_queued_plan_cancel(backend.session, state["run_id"])
    ledger.refresh()
    backend._require_owner(state)
    current, header = backend.status(state["run_id"]), ledger.header()
    if (backend.session / "closing.json").exists():
        raise ValueError("task_plan_video_session_closing")
    if current["status"] == "cancel_requested":
        raise ValueError("task_plan_video_cancelled")
    if (current.get("pending") != state["pending"] or current["owner_id"] != header["owner_id"]
            or backend._source(current)["plan_sha256"] != header["plan_sha256"]
            or reference(backend.session, backend._source_path(state["plan_id"])) != header["source_ref"]):
        raise ValueError("task_plan_video_source_changed")
    for ref in ledger.input_refs():
        if reference(backend.session, backend.session / ref["path"]) != ref:
            raise ValueError("task_plan_video_original_evidence_changed")
    for captured in ledger.payloads("captured"):
        for ref in captured.get("observation_refs", []):
            if reference(backend.session, backend.session / ref["path"]) != ref:
                raise ValueError("task_plan_video_original_evidence_changed")
    if policy_snapshot(service) != header["policy_snapshot"]:
        raise ValueError("task_plan_video_profile_changed")
    if not callable(target_reader) or target_reader() != header["target_identity"]:
        raise ValueError("task_plan_video_window_changed")
    elapsed, remaining = _remaining(header)
    if remaining <= 0:
        raise ValueError("task_plan_video_budget_expired")
    return elapsed, remaining


def _outcome(ledger, *, pending=False):
    saved = ledger.last_assessment()
    finished = ledger.finished()
    return {"pending": pending, "reason": finished["reason"] if finished else None,
        "decision": saved["result"] if saved else None, "valid": bool(saved and saved["validated"] and
            (ledger.header()["analysis_policy"] == LEGACY_ANALYSIS_POLICY or finished and finished["reason"] == "authenticated_decision")),
        "policy": ledger.header()["policy_snapshot"], "video_playback": ledger.summary(),
        "refs": ledger.artifacts(), "local_success": bool(ledger.header()["analysis_policy"] == LEGACY_ANALYSIS_POLICY
            and finished and finished["reason"] == "video_playback_confirmed")}


def _finish(ledger, reason, **extra):
    if ledger.finished() is None:
        # 迟到与重连仍保留实测耗时，不能重新开始预算。
        finished_ns = now_ns()
        elapsed = max(0, (finished_ns - ledger.header()["started_ns"]) / 1e6)
        ledger.append("finished", {"reason": reason, "finished_ns": finished_ns, "elapsed_ms": elapsed, **extra})
    return _outcome(ledger)


def _frame_valid(ledger, frame, *, previous=None):
    header = ledger.header()
    if (not isinstance(frame, dict) or set(frame) != {"capture_id", "image_path", "sha256", "window_identity", "role"}
            or frame["role"] != "observation" or frame["window_identity"] != header["target_identity"]
            or reference(ledger.session, frame["image_path"])["sha256"] != frame["sha256"]):
        raise ValueError("task_plan_video_capture_binding_invalid")
    previous = previous if previous is not None else [header["after"],
        *[item["frame"] for item in ledger.payloads("readiness_captured")],
        *[item["frame"] for item in ledger.samples()]]
    for prior in previous:
        if (frame["capture_id"] == prior["capture_id"]
                or Path(frame["image_path"]).resolve() == Path(prior["image_path"]).resolve()
                or Path(frame["image_path"]).samefile(prior["image_path"])):
            raise ValueError("task_plan_video_capture_reused")
    with Image.open(header["after"]["image_path"]) as original, Image.open(frame["image_path"]) as image:
        if (image.format != "PNG" or image.size != original.size or header["analysis_policy"] in PICTURE_POLICIES
                and (getattr(image, "is_animated", False) or image.n_frames != 1)):
            raise ValueError("task_plan_video_geometry_changed")
        image.verify()


def drive_video_playback(backend, state, step, frame, original_frame, refs, service, *, coordinator,
                         target_reader, api_grounder=None):
    ledger = VideoPlaybackLedger(backend, state["pending"]["execution_request_id"])
    if ledger.header() is None:
        source_ref = reference(backend.session, backend._source_path(state["plan_id"]))
        receipt_ref = next(item for item in refs if item["path"] == "responses/" + state["pending"]["execution_request_id"] + ".json")
        ledger.append("opened", {key: deepcopy(state[key]) for key in
            ("run_id", "plan_id", "plan_sha256", "owner_id", "session_directory", "target_identity")} | {
            "step_id": step["step_id"], "execution_request_id": state["pending"]["execution_request_id"],
            "after": deepcopy(frame), "original_frame": deepcopy(original_frame), "source_ref": source_ref,
            "rule": deepcopy(step["verification"]), "input_evidence_refs": deepcopy(refs) + [source_ref],
            "original_receipt_sha256": receipt_ref["sha256"], "policy_snapshot": policy_snapshot(service),
            "analysis_policy": DYNAMIC_ANALYSIS_POLICY if step["verification"]["kind"] == "dynamic_content" else ANALYSIS_POLICY,
            "clock_id": CLOCK_ID, "started_ns": now_ns()})
    if (ledger.header()["after"] != frame or ledger.header()["rule"] != step["verification"]
            or ledger.header()["execution_request_id"] != state["pending"]["execution_request_id"]):
        raise ValueError("task_plan_video_binding_changed")
    if ledger.finished():
        return _outcome(ledger)
    # 旧未完成账本不能以新的三图语义续采；原证据只交人工审核。
    if ledger.header().get("analysis_policy") not in PICTURE_POLICIES:
        return _finish(ledger, "video_playback_legacy_requires_main_review")
    try:
        _guard(backend, state, ledger, service, target_reader)
        for claim, completed, reason in (("capture_claimed", "captured", "task_plan_video_capture_unknown"),
                ("assessment_claimed", "assessed", "task_plan_video_assessment_unknown")):
            if len(ledger.payloads(claim)) > len(ledger.payloads(completed)):
                return _finish(ledger, reason)
        samples = ledger.samples()
        if len(samples) > PICTURE_SAMPLES:
            raise ValueError("task_plan_video_claim_limit_invalid")
        elapsed, _ = _guard(backend, state, ledger, service, target_reader)
        # 首张等待和相邻间隔均从本轮核验计时，不借用原动作的渲染等待。
        if len(samples) < PICTURE_SAMPLES:
            if elapsed < (samples[-1]["elapsed_ms"] + 500 if samples else 1000):
                return _outcome(ledger, pending=True)
            index = len(samples) + 1
            ledger.append("capture_claimed", {"index": index, "claimed_ns": now_ns()})
            def cancelled():
                _guard(backend, state, ledger, service, target_reader)
                return False
            captured = capture_followup(coordinator, session_dir=backend.session,
                target_identity=state["target_identity"], original_frame=ledger.header()["original_frame"],
                observation_id="video-observation-" + sha256(state["pending"]["execution_request_id"].encode()).hexdigest()[:24] + "-" + str(index),
                cancelled=cancelled, remaining_seconds=lambda: _remaining(ledger.header())[1])
            completed_ns = now_ns()
            _guard(backend, state, ledger, service, target_reader)
            new_frame = captured["frame"]
            _frame_valid(ledger, new_frame)
            ledger.append("captured", {"index": index, "frame": new_frame,
                "image_ref": reference(backend.session, new_frame["image_path"]),
                "elapsed_ms": (completed_ns - ledger.header()["started_ns"]) / 1e6,
                "capture_elapsed_ms": captured["capture_elapsed_ms"], "completed_ns": completed_ns})
            samples = ledger.samples()
            _guard(backend, state, ledger, service, target_reader)
            if len(samples) < PICTURE_SAMPLES:
                return _outcome(ledger, pending=True)
        from .decision_check import service_enabled
        host_policy = ledger.header()["policy_snapshot"]
        if effective_plan_review_policy(step["verification"], host_policy=host_policy,
                host_enabled=service_enabled(service)) == "always_main":
            return _finish(ledger, "decision_always_main")
        if not service_enabled(service):
            return _finish(ledger, "video_playback_requires_main_review")
        if host_policy.get("contract_version") != "decision_profile.v2":
            return _finish(ledger, "decision_profile_v2_required")
        _guard(backend, state, ledger, service, target_reader)
        claimed_ns = now_ns()
        _, remaining = _remaining(ledger.header())
        if remaining <= 0:
            raise ValueError("task_plan_video_budget_expired")
        binding = {"request_id": "task-video-decision-" + sha256(state["pending"]["execution_request_id"].encode()).hexdigest()[:32],
            "execution_request_id": state["pending"]["execution_request_id"],
            **semantic_binding(backend._source(state)["plan"], step), "frames": [deepcopy(frame)],
            "mode": "execution", "phase": "after_action", "run_id": state["run_id"], "step_id": step["step_id"],
            "review_context": review_context(backend._source(state)["plan"], step,
                source_id=state["plan_id"], source_sha256=state["plan_sha256"]),
            "temporal_context": {"schema": "temporal_playback.v2", "original_after": deepcopy(frame),
                "samples": deepcopy(samples),
                "selected_capture_ids": [item["frame"]["capture_id"] for item in samples],
                "timeout_seconds": remaining}}
        if ledger.header()["analysis_policy"] == DYNAMIC_ANALYSIS_POLICY:
            binding["temporal_context"].update(schema="temporal_visual_change.v1",
                target_description=step["verification"]["target_description"])
        ledger.append("assessment_claimed", {"binding": binding, "claimed_ns": claimed_ns})
        value, valid = assess(service, binding, v2=True)
        path = backend.session / "task-plan-decisions" / (state["pending"]["execution_request_id"] + "-video.json")
        path.parent.mkdir(exist_ok=True)
        _put(path, {"binding": binding, "result": value, "validated": valid,
            "policy_snapshot": host_policy})
        ledger.append("assessed", {"assessment_ref": reference(backend.session, path), "completed_ns": now_ns()})
        _guard(backend, state, ledger, service, target_reader)
        adopted = (host_policy.get("mode", host_policy.get("adoption_mode")) == "auto"
            and valid and value.get("adopted") is True and value.get("disposition") == "continue")
        return _finish(ledger, "authenticated_decision" if adopted
            else value.get("reason", "video_playback_requires_main_review"))
    except TaskPlanCancelPending:
        raise
    except ValueError as error:
        # 证据损坏不能包装为仍可审核的可信包。
        if str(error) == "task_plan_video_original_evidence_changed":
            raise
        return _finish(ledger, getattr(error, "reason_code", None) or str(error))


def _validate_picture_samples(ledger):
    """只认证三图及真实采集时序，不计算画面变化或读取控件。"""
    header = ledger.header()
    captured, claims = ledger.payloads("captured"), ledger.payloads("capture_claimed")
    assessments, assessed = ledger.payloads("assessment_claimed"), ledger.payloads("assessed")
    allowed = {"opened", "capture_claimed", "captured", "assessment_claimed", "assessed", "finished", "adoption_rejected"}
    if (any(item["event"] not in allowed for item in ledger.read())
            or not len(captured) <= len(claims) <= PICTURE_SAMPLES or len(claims) - len(captured) > 1
            or not len(assessed) <= len(assessments) <= 1
            or assessments and len(captured) != PICTURE_SAMPLES):
        raise ValueError("task_plan_video_claim_limit_invalid")
    prior = [header["after"]]
    previous_ns = header["started_ns"] + 500_000_000
    for index, capture in enumerate(captured):
        claim = claims[index]
        _frame_valid(ledger, capture["frame"], previous=prior)
        if (set(capture) != {"index", "frame", "image_ref", "elapsed_ms", "capture_elapsed_ms", "completed_ns"}
                or set(claim) != {"index", "claimed_ns"}
                or capture["index"] != index + 1 or claim["index"] != index + 1
                or type(capture["completed_ns"]) is not int or type(claim["claimed_ns"]) is not int
                or not previous_ns + 500_000_000 <= claim["claimed_ns"] <= capture["completed_ns"]
                or capture["elapsed_ms"] != (capture["completed_ns"] - header["started_ns"]) / 1e6
                or not 1000 <= capture["elapsed_ms"] < BUDGET_MS
                or capture["image_ref"] != reference(ledger.session, capture["frame"]["image_path"])):
            raise ValueError("task_plan_video_sample_proof_invalid")
        prior.append(capture["frame"])
        previous_ns = capture["completed_ns"]
    if assessments:
        claim = assessments[0]
        if (set(claim) != {"binding", "claimed_ns"} or type(claim["claimed_ns"]) is not int
                or not previous_ns <= claim["claimed_ns"] < header["started_ns"] + BUDGET_MS * 1_000_000):
            raise ValueError("task_plan_video_decision_claim_invalid")
        if assessed and (type(assessed[0]["completed_ns"]) is not int
                or assessed[0]["completed_ns"] < claim["claimed_ns"]):
            raise ValueError("task_plan_video_decision_claim_invalid")
    finished = ledger.finished()
    if (type(finished["finished_ns"]) is not int or finished["finished_ns"] < previous_ns - (500_000_000 if not captured else 0)
            or finished["elapsed_ms"] != max(0, (finished["finished_ns"] - header["started_ns"]) / 1e6)):
        raise ValueError("task_plan_video_finish_invalid")


def validate_video_playback(backend, state, summary, refs, frame, *, service=None, target_reader=None,
                            adopt=False, original_frame=None):
    """采用端重建完整链、原绑定与像素证明；仅重放只读图像分析。"""
    ledger = VideoPlaybackLedger(backend, state["pending"]["execution_request_id"])
    header = ledger.header()
    step = backend.pinned_step(state["run_id"], state["pending"]["step_id"])
    if (header is None or summary != ledger.summary() or ledger.finished() is None
            or backend._source(state)["plan"]["schema_version"] not in {"task_plan.v2", "task_plan.v3"}
            or header["rule"] != step["verification"]
            or (step["verification"]["kind"], header.get("analysis_policy")) not in (
                ("video_playback", ANALYSIS_POLICY), ("video_playback", LEGACY_ANALYSIS_POLICY),
                ("dynamic_content", DYNAMIC_ANALYSIS_POLICY))
            or header["after"] != frame or any(header[key] != state[key] for key in
                ("run_id", "plan_id", "plan_sha256", "owner_id", "session_directory", "target_identity"))
            or header["execution_request_id"] != state["pending"]["execution_request_id"]
            or header["source_ref"] != reference(backend.session, backend._source_path(state["plan_id"]))
            or any(ref not in refs for ref in ledger.artifacts())):
        raise ValueError("task_plan_video_settlement_binding_invalid")
    if original_frame is not None and header["original_frame"] != original_frame:
        raise ValueError("task_plan_video_original_frame_changed")
    for ref in ledger.artifacts():
        if reference(backend.session, backend.session / ref["path"]) != ref:
            raise ValueError("task_plan_video_evidence_changed")
    if header["analysis_policy"] in PICTURE_POLICIES:
        _validate_picture_samples(ledger)
        if adopt:
            _guard(backend, state, ledger, service, target_reader)
            from .decision_check import service_enabled
            if (summary != ledger.summary() or ledger.finished()["reason"] != "authenticated_decision"
                    or len(ledger.samples()) != PICTURE_SAMPLES
                    or len(ledger.payloads("capture_claimed")) != PICTURE_SAMPLES
                    or len(ledger.payloads("assessment_claimed")) != len(ledger.payloads("assessed"))
                    or ledger.finished()["elapsed_ms"] >= BUDGET_MS or ledger.payloads("adoption_rejected")
                    or policy_snapshot(service).get("mode", policy_snapshot(service).get("adoption_mode")) != "auto"
                    or effective_plan_review_policy(step["verification"], host_policy=policy_snapshot(service),
                        host_enabled=service_enabled(service)) == "always_main"):
                raise ValueError("task_plan_video_adoption_policy_invalid")
        return ledger
    readiness = ledger.payloads("readiness_captured")
    if (len(ledger.payloads("location_claimed")) > 1 or len(ledger.payloads("assessment_claimed")) > 1
            or len(ledger.samples()) + len(readiness) > MAX_SAMPLES):
        raise ValueError("task_plan_video_claim_limit_invalid")
    samples, locator = ledger.samples(), ledger.locator()
    if locator is not None and locator["evidence"].get("source_frame") != ledger.localization_frame():
        raise ValueError("task_plan_video_locator_source_invalid")
    if locator is not None and readiness and (readiness[-1]["page_loading"] is not False
            or len(readiness) > MAX_SAMPLES - 3):
        raise ValueError("task_plan_video_readiness_proof_invalid")
    readiness_claims = ledger.payloads("readiness_claimed")
    if len(readiness_claims) < len(readiness) or len(readiness_claims) > MAX_SAMPLES:
        raise ValueError("task_plan_video_readiness_proof_invalid")
    if (readiness or locator is not None) and page_loading(header["original_frame"], session_dir=backend.session) != bool(readiness):
        raise ValueError("task_plan_video_readiness_proof_invalid")
    prior = [frame]
    for index, item in enumerate(readiness):
        claim = readiness_claims[index]
        _frame_valid(ledger, item["frame"], previous=prior)
        if (item["index"] != index + 1 or claim["index"] != index + 1
                or type(item["completed_ns"]) is not int or type(claim["claimed_ns"]) is not int
                or not header["started_ns"] <= claim["claimed_ns"] <= item["completed_ns"]
                or item["elapsed_ms"] != (item["completed_ns"] - header["started_ns"]) / 1e6
                or not 0 <= item["elapsed_ms"] < BUDGET_MS
                or index and item["elapsed_ms"] - readiness[index - 1]["elapsed_ms"] < 500
                or item["image_ref"] != reference(backend.session, item["frame"]["image_path"])
                or type(item["page_loading"]) is not bool
                or item["page_loading"] != page_loading(item["frame"], session_dir=backend.session)
                or index < len(readiness) - 1 and not item["page_loading"]):
            raise ValueError("task_plan_video_readiness_proof_invalid")
        prior.append(item["frame"])
    if samples:
        if locator is None or summary["analysis"] != _analysis(samples, locator["region"]):
            raise ValueError("task_plan_video_analysis_changed")
        captured = ledger.payloads("captured")
        claims = ledger.payloads("capture_claimed")
        if len(claims) < len(captured) or len(claims) > MAX_SAMPLES:
            raise ValueError("task_plan_video_capture_claim_invalid")
        seen_ids = {item["capture_id"] for item in prior}
        seen_paths = [Path(item["image_path"]).resolve(strict=True) for item in prior]
        with Image.open(frame["image_path"]) as original:
            original_size = original.size
        for index, item in enumerate(samples):
            sample_frame = item["frame"]
            sample_path = Path(sample_frame["image_path"]).resolve(strict=True)
            capture, claim = captured[index], claims[index]
            if (set(sample_frame) != {"capture_id", "image_path", "sha256", "window_identity", "role"}
                    or sample_frame["role"] != "observation" or sample_frame["capture_id"] in seen_ids
                    or any(sample_path == previous or sample_path.samefile(previous) for previous in seen_paths)
                    or reference(backend.session, sample_path)["sha256"] != sample_frame["sha256"]
                    or capture["image_ref"] != reference(backend.session, sample_path)
                    or capture["index"] != index + 1 or claim["index"] != index + 1
                    or type(capture["completed_ns"]) is not int or type(claim["claimed_ns"]) is not int
                    or not header["started_ns"] <= claim["claimed_ns"] <= capture["completed_ns"]
                    or item["elapsed_ms"] != (capture["completed_ns"] - header["started_ns"]) / 1e6
                    or sample_frame["window_identity"] != state["target_identity"]
                    or item["observation"] != observe_player_frame(item["frame"], locator, session_dir=backend.session)
                    or item["elapsed_ms"] < 0 or item["elapsed_ms"] >= BUDGET_MS
                    or not index and readiness and item["elapsed_ms"] - readiness[-1]["elapsed_ms"] < 500
                    or index and item["elapsed_ms"] - samples[index-1]["elapsed_ms"] < 500):
                raise ValueError("task_plan_video_sample_proof_invalid")
            with Image.open(sample_path) as image:
                if image.format != "PNG" or image.size != original_size:
                    raise ValueError("task_plan_video_geometry_changed")
            seen_ids.add(sample_frame["capture_id"])
            seen_paths.append(sample_path)
    if adopt:
        _guard(backend, state, ledger, service, target_reader)
        if summary != ledger.summary():
            raise ValueError("task_plan_video_settlement_binding_invalid")
        from .decision_check import service_enabled
        if (effective_plan_review_policy(step["verification"], host_policy=policy_snapshot(service),
                host_enabled=service_enabled(service)) == "always_main"
                or ledger.finished()["elapsed_ms"] >= BUDGET_MS or ledger.payloads("adoption_rejected")
                or len(ledger.payloads("capture_claimed")) != len(samples)
                or len(readiness_claims) != len(readiness)
                or len(ledger.payloads("location_claimed")) != len(ledger.payloads("located"))
                or len(ledger.payloads("assessment_claimed")) != len(ledger.payloads("assessed"))):
            raise ValueError("task_plan_video_adoption_policy_invalid")
    return ledger


def validate_video_decision(backend, state, ledger, frame, saved):
    claims = ledger.payloads("assessment_claimed")
    if len(claims) != 1 or ledger.finished()["reason"] != "authenticated_decision":
        raise ValueError("task_plan_video_decision_claim_invalid")
    binding = deepcopy(claims[0]["binding"])
    temporal = binding.get("temporal_context") or {}
    samples = ledger.samples()
    step = backend.pinned_step(state["run_id"], state["pending"]["step_id"])
    source = backend._source(state)
    picture = ledger.header()["analysis_policy"] in PICTURE_POLICIES
    expected_temporal = {"schema": "temporal_playback.v2", "original_after": frame,
        "samples": deepcopy(samples), "selected_capture_ids": [item["frame"]["capture_id"] for item in samples],
        "timeout_seconds": temporal.get("timeout_seconds")} if picture else {
        "schema": "temporal_playback.v1", "original_after": frame,
        "samples": deepcopy(samples), "analysis_policy": LEGACY_ANALYSIS_POLICY,
        "region": ledger.locator()["region"], "analysis": ledger.summary()["analysis"],
        "selected_capture_ids": [samples[0]["frame"]["capture_id"], samples[-1]["frame"]["capture_id"]],
        "timeout_seconds": temporal.get("timeout_seconds")}
    if ledger.header()["analysis_policy"] == DYNAMIC_ANALYSIS_POLICY:
        expected_temporal.update(schema="temporal_visual_change.v1",
            target_description=step["verification"]["target_description"])
    expected = {"request_id": "task-video-decision-" + sha256(state["pending"]["execution_request_id"].encode()).hexdigest()[:32],
        "execution_request_id": state["pending"]["execution_request_id"], **semantic_binding(source["plan"], step),
        "frames": [frame], "mode": "execution", "phase": "after_action", "run_id": state["run_id"], "step_id": step["step_id"],
        "review_context": review_context(source["plan"], step, source_id=state["plan_id"], source_sha256=state["plan_sha256"]),
        "temporal_context": expected_temporal}
    if (binding != expected or saved.get("binding") != expected
            or saved.get("policy_snapshot") != ledger.header()["policy_snapshot"]
            or saved.get("validated") is not True or len(samples) < 3
            or samples[-1]["elapsed_ms"] - samples[0]["elapsed_ms"] < 1000
            or type(temporal.get("timeout_seconds")) not in (int, float)
            or not 0 < temporal["timeout_seconds"] <= 8):
        raise ValueError("task_plan_video_decision_binding_invalid")
    if picture:
        _validate_picture_samples(ledger)
        remaining_at_claim = (BUDGET_MS * 1_000_000 + ledger.header()["started_ns"] - claims[0]["claimed_ns"]) / 1e9
        if len(samples) != PICTURE_SAMPLES or temporal["timeout_seconds"] > remaining_at_claim:
            raise ValueError("task_plan_video_decision_evidence_invalid")
        return binding
    analysis = ledger.summary()["analysis"]
    if (analysis["status"] != "uncertain" or analysis["metrics"]["image_size"] is None
            or len(analysis["metrics"]["motion_pairs"]) != len(samples) - 1):
        raise ValueError("task_plan_video_decision_evidence_invalid")
    return binding


__all__ = ["VideoPlaybackLedger", "drive_video_playback", "validate_video_playback", "validate_video_decision",
    "projection", "abort_video_playback"]
