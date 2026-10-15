"""同一活跃输入线程的 Main 字段审核等待；磁盘证据不能重启输入。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re
from time import perf_counter_ns

from app.core.vision_admission_contract import AgentCommandCancelled, AgentCommandError
from app.desktop_review.external_mapping import canonical_json_bytes


def _digest(value):
    return sha256(canonical_json_bytes(value)).hexdigest()


def _request_id(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", value) is None:
        raise AgentCommandError("field_review_request_id_invalid")


def _record_view(record):
    return deepcopy({key: record[key] for key in (
        "packet", "review", "review_request_id", "continued", "continue_request_id")})


class FieldReviewWait:
    """由 AgentCommandJobs 复用其 Condition、原 job 与原回执。"""

    def _field_plan_bound(self, job):
        validator = self.field_review_plan_validator
        return callable(validator) and validator(job.command_id, deepcopy(job.action_review)) is True

    def _field_reference(self, path):
        root = Path(self.store.session_root).resolve()
        try:
            actual = Path(path).resolve(strict=True)
            relative = actual.relative_to(root)
            if not actual.is_file():
                raise ValueError
            return {"path": relative.as_posix(), "sha256": sha256(actual.read_bytes()).hexdigest()}
        except (OSError, ValueError):
            raise AgentCommandError("field_review_evidence_unavailable") from None

    def _field_source(self, job, error, *, stage, progress, context):
        from app.core.input_sequence_partial import _compound_input_fact, _request
        from app.execution.action_review import normalize_action_review_context
        from app.execution.visual_field_proof import VisualFieldReviewRequired, VISUAL_TEXT_VALUE_CONDITION
        if (type(error) is not VisualFieldReviewRequired or stage != "after_type"
                or job.command.get("kind") != "input_sequence"
                or not isinstance(context, dict) or context.get("native_field_evidence") is not False
                or not isinstance(progress, dict) or job.action_review is None
                or not self._field_plan_bound(job)):
            raise error
        if self._closed or job.cancelled:
            raise AgentCommandCancelled("agent_command_cancelled")
        cancelled = context.get("cancelled")
        if callable(cancelled) and cancelled():
            raise AgentCommandError("field_review_cancelled")
        binding = normalize_action_review_context(job.action_review)
        if (context.get("action_review") != binding or context.get("execution_request_id") != job.command_id
                or context.get("service") is not getattr(self.coordinator, "_decision_service", None)):
            raise AgentCommandError("field_review_context_binding_invalid")
        original = VisualFieldReviewRequired.to_reference(error)
        request, assessment = original["request"], original["assessment"]
        service = context["service"]
        if (assessment.get("status") != "completed" or assessment.get("adopted") is not False
                or assessment.get("disposition") != "review_required"
                or (assessment.get("choice_result") or {}).get("choice") not in {"condition_not_met", "evidence_insufficient"}
                or (assessment.get("ordinary_review") or {}).get("status") != "completed"
                or ((assessment.get("ordinary_review") or {}).get("review_result") or {}).get("choice") not in {
                    "condition_not_met", "evidence_insufficient"}
                or service.validate_result(assessment, **request) is not True):
            raise AgentCommandError("field_review_authentication_invalid")
        action = request.get("action") or {}
        frames = request.get("frames") or []
        review_context = request.get("review_context") or {}
        spec = _request(job.command["request"])
        fact = _compound_input_fact(progress, spec)
        state = self._snapshots[job.command_id]
        attempts = state.get("dispatch_attempts") or []
        rows = progress.get("steps") or []
        if (fact is None or not fact["completed"] or len(rows) != 1
                or progress.get("contract_version") != "input_sequence_v1"
                or progress.get("phase") != "check_input" or progress.get("action_executed") is not True
                or progress.get("completed_steps") != ["focus_type"]
                or progress.get("text_sha256") != sha256(spec["text"].encode("utf-8")).hexdigest()
                or progress.get("text_length") != len(spec["text"])
                or progress.get("submit_search") is not spec["submit_search"]
                or fact["fact"]["execution_request_id"] != job.command_id
                or any(fact["identity"][key] != job.target[key] for key in ("handle", "process_id"))
                or state.get("dispatch_in_progress") is not False or state.get("action_executed") is not True
                or state.get("status") != "running" or len(attempts) != 1
                or attempts[0].get("operation") != "execute_recognition_plan"
                or attempts[0].get("status") != "returned" or attempts[0].get("action_executed") is not True
                or (state.get("last_execution") or {}).get("operation") != "execute_recognition_plan"
                or (state.get("last_execution") or {}).get("attempt_index") != attempts[0].get("index")
                or (state.get("last_execution") or {}).get("receipt") != fact["receipt"]):
            raise AgentCommandError("field_review_input_unsettled")
        if (request.get("execution_request_id") != job.command_id or request.get("step_id") != fact["receipt"]["step_id"]
                or request.get("phase") != "after_action" or request.get("condition") != VISUAL_TEXT_VALUE_CONDITION
                or action.get("operation") != "visual_field_check" or action.get("field_phase") != "value"
                or action.get("focus_stage") is not None or action.get("value_verification") != "visual"
                or action.get("value_reading") is not None or action.get("actual_text") is not None
                or action.get("focus_receipt_sha256") != _digest(fact["receipt"])
                or action.get("input_receipt_sha256") != _digest(fact["receipt"])
                or action.get("expected_text") != spec["text"]
                or (action.get("field") or {}).get("expected_text") != spec["text"]
                or (action.get("field") or {}).get("field_goal") != spec["field_goal"]
                or (action.get("field") or {}).get("window_identity") != fact["identity"]
                or review_context.get("source_id") != binding["run_id"]
                or review_context.get("source_sha256") != _digest(binding["plan"])
                or len(frames) != 1 or frames[0].get("role") != "after"
                or frames[0].get("window_identity") != fact["identity"]):
            raise AgentCommandError("field_review_original_binding_invalid")
        from app.execution.decision_check import decision_frame
        if frames[0] != decision_frame(progress["observation"]["capture"], fact["identity"], role="after"):
            raise AgentCommandError("field_review_original_binding_invalid")
        return binding, original, service

    def _field_checked(self, job, record):
        if (self._closed or job.cancelled or self._jobs.get(job.command_id) is not job
                or job.field_review_state is not record or not self._field_plan_bound(job)):
            raise AgentCommandError("field_review_no_longer_active")
        cancelled = record["context"].get("cancelled")
        if callable(cancelled) and cancelled():
            raise AgentCommandError("field_review_cancelled")
        packet = record["packet"]
        body = {key: value for key, value in packet.items() if key != "packet_sha256"}
        if (packet["packet_sha256"] != _digest(body)
                or packet["evidence_set_sha256"] != _digest(packet["evidence_refs"])
                or packet["progress_sha256"] != _digest(record["progress"])
                or record["service"].validate_result(packet["assessment"], **packet["request"]) is not True
                or self._snapshots[job.command_id].get("field_review") != _record_view(record)):
            raise AgentCommandError("field_review_original_binding_invalid")
        for reference in packet["evidence_refs"]:
            current = self._field_reference(Path(self.store.session_root) / reference["path"])
            if current != reference:
                raise AgentCommandError("field_review_evidence_changed")
        return True

    def _await_field_review(self, job, error, *, stage, progress, context):
        from app.execution.main_field_approval import _issue_main_field_approval
        with self._condition:
            binding, original, service = self._field_source(job, error, stage=stage, progress=progress, context=context)
            if job.field_review_state is not None:
                raise AgentCommandError("field_review_already_waited")
            root = self._root / "field-reviews"
            root.mkdir(parents=True, exist_ok=True)
            path = root / (job.command_id + "-round0-progress.json")
            try:
                with path.open("xb") as stream:
                    stream.write(canonical_json_bytes(progress))
            except FileExistsError:
                raise AgentCommandError("field_review_progress_already_exists") from None
            progress_reference = self._field_reference(path)
            references = [progress_reference]
            for frame in original["request"]["frames"]:
                reference = self._field_reference(frame["image_path"])
                if reference["sha256"] != frame["sha256"]:
                    raise AgentCommandError("field_review_evidence_changed")
                if reference not in references:
                    references.append(reference)
            packet = {"schema": "field_review_packet.v1", "command_id": job.command_id,
                "session_directory": str(Path(self.store.session_root).resolve()),
                "stage": stage, "run_id": binding["run_id"], "step_id": binding["step_id"],
                "execution_request_id": job.command_id, "plan_sha256": _digest(binding["plan"]),
                "assessment_round": 0, "request": deepcopy(original["request"]),
                "assessment": deepcopy(original["assessment"]), "condition": original["request"]["condition"],
                "after": deepcopy(original["request"]["frames"][-1]), "frames": deepcopy(original["request"]["frames"]),
                "progress_snapshot": progress_reference, "progress_sha256": _digest(progress),
                "evidence_refs": references, "evidence_set_sha256": _digest(references),
                "authorizes_action": False, "automatic_retry_allowed": False}
            packet["packet_sha256"] = _digest(packet)
            record = {"packet": packet, "progress": deepcopy(progress), "service": service, "context": context,
                "review": None, "review_request_id": None, "continued": False, "continue_request_id": None,
                "requests": {}}
            job.field_review_state = record
            self._update(job, status="awaiting_field_review", pending_field_review=packet,
                progress=progress, field_review=_record_view(record))
            self._condition.notify_all()
            while not record["continued"] and (record["review"] or {}).get("verdict") != "failure":
                if job.cancelled or self._closed:
                    raise AgentCommandCancelled("agent_command_cancelled")
                self._condition.wait()
            if job.cancelled or self._closed:
                raise AgentCommandCancelled("agent_command_cancelled")
            if record["review"]["verdict"] == "failure":
                raise error
            self._field_checked(job, record)

        def validate():
            with self._condition:
                return (record["continued"] is True and record["review"]["verdict"] == "success"
                    and self._snapshots[job.command_id]["status"] == "running"
                    and self._field_checked(job, record))
        return _issue_main_field_approval(error, service=service, review=deepcopy(record["review"]),
            deadline_ns=job.action_review_deadline_ns, validator=validate)

    def get_field_review(self, command_id):
        self._path(command_id)
        with self._condition:
            job = self._jobs.get(command_id)
            if (job is None or self._closed or job.cancelled
                    or self._snapshots[command_id]["status"] != "awaiting_field_review"):
                return None
            record = job.field_review_state
            if record is None or record["continued"]:
                return None
            self._field_checked(job, record)
            return _record_view(record)

    def review_field(self, command_id, request_id, review):
        self._path(command_id)
        _request_id(request_id)
        with self._condition:
            job = self._jobs.get(command_id)
            record = getattr(job, "field_review_state", None)
            if record is None:
                raise AgentCommandError("field_review_not_awaiting")
            claim = {"action": "review", "review": deepcopy(review)}
            prior = record["requests"].get(request_id)
            if prior is not None:
                if prior != claim:
                    raise AgentCommandError("field_review_request_conflict")
                return self.get_field_review(command_id)
            if self._snapshots[command_id]["status"] != "awaiting_field_review" or record["continued"]:
                raise AgentCommandError("field_review_not_awaiting")
            self._field_checked(job, record)
            packet = record["packet"]
            fields = {"action", "run_id", "step_id", "execution_request_id", "verdict", "reason", "evidence_sha256",
                "review_packet_sha256", "evidence_set_sha256", "assessment_round"}
            if (type(review) is not dict or set(review) != fields or review.get("action") != "review"
                    or review.get("verdict") not in {"success", "failure"}
                    or type(review.get("reason")) is not str or not review["reason"].strip() or len(review["reason"]) > 4000
                    or type(review.get("assessment_round")) is not int
                    or any(review[key] != packet[key] for key in (
                        "run_id", "step_id", "execution_request_id", "evidence_set_sha256", "assessment_round"))
                    or review["evidence_sha256"] != packet["after"]["sha256"]
                    or review["review_packet_sha256"] != packet["packet_sha256"]):
                raise AgentCommandError("field_review_request_binding_invalid")
            if record["review"] is not None and record["review"] != review:
                raise AgentCommandError("field_review_already_reviewed")
            record["requests"][request_id] = claim
            if record["review"] is None:
                record.update(review=deepcopy(review), review_request_id=request_id)
                self._update(job, field_review=_record_view(record))
            result = _record_view(record)
            if review["verdict"] == "failure":
                self._condition.notify_all()
            return result

    def continue_field(self, command_id, request_id):
        self._path(command_id)
        _request_id(request_id)
        with self._condition:
            job = self._jobs.get(command_id)
            record = getattr(job, "field_review_state", None)
            if record is None:
                raise AgentCommandError("field_review_not_awaiting")
            claim = {"action": "continue", "packet_sha256": record["packet"]["packet_sha256"]}
            prior = record["requests"].get(request_id)
            if prior is not None:
                if prior != claim:
                    raise AgentCommandError("field_review_request_conflict")
                return deepcopy(self._snapshots[command_id])
            if (self._snapshots[command_id]["status"] != "awaiting_field_review" or record["continued"]
                    or (record["review"] or {}).get("verdict") != "success"):
                raise AgentCommandError("field_review_success_required")
            self._field_checked(job, record)
            record["requests"][request_id] = claim
            record.update(continued=True, continue_request_id=request_id)
            job.action_review_deadline_ns = perf_counter_ns() + min(job.action_review["budget_ms"], 60000) * 1_000_000
            result = self._update(job, status="running", pending_field_review=None, field_review=_record_view(record))
            self._condition.notify_all()
            return result
