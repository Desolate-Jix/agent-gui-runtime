"""内部键入派发事实；未知派发不能冒充零输入或充当续执行许可。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from threading import get_ident
from time import perf_counter_ns
from uuid import uuid4


_ISSUER = object()


class TypingDispatchReceipt:
    def __init__(self, *, _issuer=None):
        if _issuer is not _ISSUER:
            raise ValueError("typing dispatch issuer unavailable")
        self._issuer, self._owner = _issuer, get_ident()
        self._started = perf_counter_ns()
        self._states = {name: "not_started" for name in ("focus", "selection", "text", "submit")}
        self._events, self._evidence = [], None

    def _check(self):
        if self._issuer is not _ISSUER or self._owner != get_ident():
            raise ValueError("typing dispatch owner unavailable")

    def record(self, phase, status):
        self._check()
        expected = "not_started" if status == "started" else "started" if status == "completed" else None
        if phase not in self._states or self._states[phase] != expected:
            raise ValueError("typing dispatch transition invalid")
        self._states[phase] = status
        self._events.append({"phase": phase, "status": status,
            "elapsed_ms": (perf_counter_ns() - self._started) / 1_000_000})

    def reference(self):
        self._check()
        values = tuple(self._states.values())
        result = {"schema": "typing_dispatch.v1", **{key + "_dispatch": value for key, value in self._states.items()},
            "input_started": any(value != "not_started" for value in values),
            "action_executed": True if "completed" in values else None if "started" in values else False,
            "events": deepcopy(self._events), "artifact_is_authorization": False}
        if self._evidence is not None:
            if sha256(Path(self._evidence["path"]).read_bytes()).hexdigest() != self._evidence["sha256"]:
                raise ValueError("typing dispatch evidence changed")
            result["selection_evidence"] = deepcopy(self._evidence)
        return result

    def persist_selection(self, folder):
        self._check()
        if self._states["selection"] != "completed" or self._states["text"] != "not_started" or self._evidence is not None:
            raise ValueError("typing selection checkpoint invalid")
        path = Path(folder) / ("selection-" + uuid4().hex + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.reference(), ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        path.write_bytes(payload)
        self._evidence = {"path": str(path), "sha256": sha256(payload).hexdigest()}

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, kind, error, traceback):
        if error is not None:
            error._typing_dispatch_receipt = self


def create_typing_dispatch():
    return TypingDispatchReceipt(_issuer=_ISSUER)


def typing_dispatch_from_error(error):
    receipt = getattr(error, "_typing_dispatch_receipt", None)
    return receipt.reference() if type(receipt) is TypingDispatchReceipt else None
