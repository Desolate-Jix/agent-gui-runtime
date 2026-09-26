"""会话内异步识别交接；保存候选不等于允许输入或证明操作成功。"""
from copy import deepcopy
from hashlib import sha256
import math
from pathlib import Path
import re
from threading import RLock
import time

from PIL import Image

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from .grounding_contract import validate_grounding_result
from .recognition_source import resolve_recognition_route


_STORE_LOCK = RLock()


class GroundingHandoffError(ValueError):
    def __init__(self, code, details=None):
        self.code = code
        super().__init__(code + (": " + details if details else ""))


class GroundingHandoffStore:
    """由单个 MCP 宿主管理；多个进程不得同时拥有同一会话目录。"""

    def __init__(self, session_root, *, owner_id, clock=time.time, ttl_seconds=180):
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("owner_id must be non-empty")
        if type(ttl_seconds) not in (int, float) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be finite and positive")
        self.session_root = Path(session_root).resolve()
        self.owner_id = owner_id
        self._clock = clock
        self._ttl = ttl_seconds

    def _path(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", request_id):
            raise GroundingHandoffError("request_id_invalid")
        path = (self.session_root / "grounding" / (request_id + ".json")).resolve()
        if not path.is_relative_to(self.session_root):
            raise GroundingHandoffError("request_path_invalid")
        return path

    def _capture(self, capture):
        if not isinstance(capture, dict) or not isinstance(capture.get("image_path"), str):
            raise GroundingHandoffError("capture_invalid")
        path = Path(capture["image_path"]).resolve()
        if not path.is_relative_to(self.session_root):
            raise GroundingHandoffError("capture_outside_session")
        if not isinstance(capture.get("capture_id"), str) or not capture["capture_id"].strip():
            raise GroundingHandoffError("capture_id_invalid")
        identity = capture.get("window_identity")
        if (not isinstance(identity, dict)
                or any(type(identity.get(key)) is not int or identity[key] <= 0 for key in ("handle", "process_id"))
                or type(identity.get("process_create_time")) not in (int, float)
                or not math.isfinite(identity["process_create_time"]) or identity["process_create_time"] <= 0):
            raise GroundingHandoffError("capture_identity_invalid")
        try:
            data = path.read_bytes()
        except OSError:
            raise GroundingHandoffError("capture_unavailable") from None
        if sha256(data).hexdigest() != capture.get("sha256"):
            raise GroundingHandoffError("capture_digest_mismatch")
        try:
            from io import BytesIO
            with Image.open(BytesIO(data)) as image:
                if image.format != "PNG":
                    raise GroundingHandoffError("capture_format_invalid")
                size = {"width": image.width, "height": image.height}
                image.verify()
        except (OSError, ValueError):
            raise GroundingHandoffError("capture_format_invalid") from None
        # 保留公共截图诊断，避免交接后遮挡证据和耗时消失；不透传任意附加数据。
        diagnostics = {key: deepcopy(capture[key]) for key in (
            "capture_visibility", "capture_timings", "capture_purpose", "roi", "window_size")
            if key in capture}
        return {"capture_id": capture["capture_id"], "image_path": str(path),
                "sha256": capture["sha256"], "image_size": size,
                "window_identity": deepcopy(identity), **diagnostics}

    def _read(self, request_id):
        path = self._path(request_id)
        if not path.is_file():
            raise GroundingHandoffError("request_unknown")
        state = read_json_snapshot(path)
        if state.get("owner_id") != self.owner_id:
            raise GroundingHandoffError("owner_mismatch")
        if state["phase"] in {"awaiting_grounding", "grounding_ready", "ambiguous"} and self._clock() >= state["expires_at"]:
            state.update(phase="expired", next_action="capture_and_request_again")
            write_json_snapshot(path, state)
        return state

    def get(self, request_id):
        with _STORE_LOCK:
            return self._read(request_id)

    def prepare(self, request_id, *, goal, capture, configuration, capabilities):
        with _STORE_LOCK:
            path = self._path(request_id)
            if not isinstance(goal, str) or not goal.strip() or len(goal) > 4096:
                raise GroundingHandoffError("goal_invalid")
            if path.exists():
                previous = self._read(request_id)
                frozen = previous["capture"]
                if (not isinstance(capture, dict)
                        or not isinstance(capture.get("image_path"), str)
                        or any(capture.get(key) != frozen[key] for key in
                               ("capture_id", "sha256", "window_identity"))
                        or str(Path(capture["image_path"]).resolve()) != frozen["image_path"]
                        or capture.get("image_size", frozen["image_size"]) != frozen["image_size"]
                        or previous["goal"] != goal or previous["configuration"] != configuration.model_dump()):
                    raise GroundingHandoffError("request_conflict")
                return previous
            route = resolve_recognition_route(configuration, capabilities)
            if route.status != "eligible":
                raise GroundingHandoffError(route.code)
            if route.dispatch_owner != "agent_client":
                raise GroundingHandoffError("handoff_requires_agent_source")
            intent = {"goal": goal, "capture": self._capture(capture),
                      "configuration": configuration.model_dump()}
            state = {"contract_version": "grounding_handoff.v1", "request_id": request_id,
                     "owner_id": self.owner_id, **intent, "phase": "awaiting_grounding",
                     "expires_at": self._clock() + self._ttl, "input_dispatched": False,
                     "requires_live_revalidation": True,
                     "next_action": "inspect_image_and_submit_grounding"}
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_snapshot(path, state)
            return deepcopy(state)

    def resolve(self, request_id, payload):
        with _STORE_LOCK:
            state = self._read(request_id)
            if state["phase"] in {"cancelled", "expired"}:
                raise GroundingHandoffError("request_" + state["phase"])
            capture = state["capture"]
            try:
                result = validate_grounding_result(payload, request_id=request_id,
                    capture_id=capture["capture_id"],
                    image_size=(capture["image_size"]["width"], capture["image_size"]["height"]))
            except ValueError as error:
                raise GroundingHandoffError("grounding_invalid", str(error)) from None
            if any(candidate.evidence_source != "agent_visual" for candidate in result.candidates):
                raise GroundingHandoffError("source_mismatch")
            value = result.model_dump()
            if "result" in state:
                if state["result"] != value:
                    raise GroundingHandoffError("result_conflict")
                return state
            self._capture(capture)
            state.update(result=value, phase="grounding_ready" if result.status == "found" else result.status,
                         next_action="execute_via_common_action_entry" if result.status == "found"
                         else "inspect_result_without_input")
            write_json_snapshot(self._path(request_id), state)
            return state

    def claim_execution(self, request_id, execution_id):
        with _STORE_LOCK:
            self._path(execution_id)
            state = self._read(request_id)
            if "execution_id" in state:
                raise GroundingHandoffError("execution_already_claimed")
            if state["phase"] != "grounding_ready":
                raise GroundingHandoffError("execution_not_ready")
            self._capture(state["capture"])
            # 先持久化占用，再进入动作路由；崩溃后不能自动重放。
            state.update(phase="executing", execution_id=execution_id,
                         input_dispatched=None, next_action="poll_original_execution")
            write_json_snapshot(self._path(request_id), state)
            return state

    def finish_execution(self, request_id, execution_id, result, *, input_attempted):
        if type(input_attempted) is not bool or not isinstance(result, dict):
            raise GroundingHandoffError("execution_result_invalid")
        with _STORE_LOCK:
            state = self._read(request_id)
            if state.get("execution_id") != execution_id:
                raise GroundingHandoffError("execution_not_owned")
            if state["phase"] == "completed":
                if state["execution_result"] != result or state["input_attempted"] != input_attempted:
                    raise GroundingHandoffError("execution_result_conflict")
                return state
            if state["phase"] != "executing":
                raise GroundingHandoffError("execution_not_owned")
            state.update(phase="completed", execution_result=deepcopy(result),
                         input_attempted=input_attempted, input_dispatched=None if input_attempted else False,
                         next_action="inspect_execution_receipt_and_images")
            write_json_snapshot(self._path(request_id), state)
            return state

    def cancel(self, request_id):
        with _STORE_LOCK:
            state = self._read(request_id)
            if "execution_id" in state:
                raise GroundingHandoffError("execution_already_claimed")
            if state["phase"] not in {"cancelled", "expired"}:
                state.update(phase="cancelled", next_action="none")
                write_json_snapshot(self._path(request_id), state)
            return state
