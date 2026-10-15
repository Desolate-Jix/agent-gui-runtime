"""仅运行时签发的 Main 字段审核凭据；原模型判断保持原样。"""
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter_ns


_ISSUER = object()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _artifact(reference):
    session = Path(reference["session_directory"]).resolve(strict=True)
    item = reference["artifact"]
    path = (session / item["path"]).resolve(strict=True)
    if (not path.is_relative_to(session / "visual-field-proof" / "main-reviews")
            or sha256(path.read_bytes()).hexdigest() != item["sha256"]):
        raise ValueError("main_field_approval_artifact_changed")
    record = json.loads(path.read_text(encoding="utf-8"))
    expected = {key: value for key, value in reference.items() if key != "artifact"}
    if record["reference"] != expected:
        raise ValueError("main_field_approval_artifact_binding_invalid")
    return record


@dataclass(frozen=True, slots=True)
class MainFieldApproval:
    _reference_json: str = field(repr=False)
    _service: object = field(repr=False)
    _validator: object = field(repr=False)
    _issuer: object = field(repr=False)

    @property
    def deadline_ns(self):
        return self.to_reference()["deadline_ns"]

    def validate(self):
        if self._issuer is not _ISSUER:
            raise ValueError("main_field_approval_issuer_invalid")
        reference = json.loads(self._reference_json)
        if (type(reference.get("deadline_ns")) is not int
                or reference["deadline_ns"] <= perf_counter_ns()
                or self._validator() is not True):
            raise ValueError("main_field_approval_no_longer_valid")
        record = _artifact(reference)
        if (self._service.validate_result(record["assessment"], **record["request"]) is not True
                or record["assessment"]["request_sha256"] != reference["request_sha256"]
                or _digest(record["assessment"]) != reference["assessment_sha256"]):
            raise ValueError("main_field_approval_authentication_invalid")
        return True

    def to_reference(self):
        MainFieldApproval.validate(self)
        return json.loads(self._reference_json)


def _issue_main_field_approval(error, *, service, review, deadline_ns, validator):
    from .visual_field_proof import VisualFieldReviewRequired
    if type(error) is not VisualFieldReviewRequired or not callable(validator):
        raise ValueError("main_field_approval_source_invalid")
    original = VisualFieldReviewRequired.to_reference(error)
    request, assessment = original["request"], original["assessment"]
    action = request["action"]
    if (action.get("field_phase") != "value" or action.get("value_verification") != "visual"
            or action.get("value_reading") is not None or len(request["frames"]) != 1
            or assessment.get("adopted") is not False or assessment.get("disposition") != "review_required"
            or service.validate_result(assessment, **request) is not True
            or type(review) is not dict or review.get("verdict") != "success"
            or review.get("execution_request_id") != request["execution_request_id"]
            or review.get("evidence_sha256") != request["frames"][-1]["sha256"]
            or type(deadline_ns) is not int or not perf_counter_ns() < deadline_ns <= perf_counter_ns() + 60_000_000_000
            or validator() is not True):
        raise ValueError("main_field_approval_binding_invalid")
    reference = {"schema": "main_field_approval.v1", "source": "main_agent",
        "request_sha256": assessment["request_sha256"], "assessment_sha256": _digest(assessment),
        "review": json.loads(_json(review)), "deadline_ns": deadline_ns,
        "session_directory": str(Path(service.session_dir).resolve()),
        "artifact_is_authorization": False}
    record = {"reference": reference, "request": request, "assessment": assessment,
        "profile": service.profile.model_dump(mode="json")}
    raw = _json(record).encode("utf-8")
    digest = sha256(raw).hexdigest()
    session = Path(reference["session_directory"])
    path = session / "visual-field-proof" / "main-reviews" / (digest + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError("main_field_approval_artifact_conflict")
    reference["artifact"] = {"path": path.relative_to(session).as_posix(), "sha256": digest}
    approval = MainFieldApproval(_json(reference), service, validator, _ISSUER)
    approval.validate()
    return approval
