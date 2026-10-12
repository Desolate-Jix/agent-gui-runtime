"""并行运行纯数据回调；场景预检不审核候选，也不签发或消费输入权限。"""
from concurrent.futures import Future
from copy import deepcopy
import math
from threading import Event, Lock, Thread
from time import perf_counter_ns


def _binding(value):
    if type(value) is not dict:
        raise ValueError("parallel_result_invalid")
    for key in ("capture_id", "attempt_id"):
        if type(value.get(key)) is not str or not value[key].strip() or len(value[key]) > 200:
            raise ValueError("parallel_result_binding_invalid")
    identity = value.get("window_identity")
    if (type(identity) is not dict or set(identity) != {"handle", "process_id", "process_create_time"}
            or any(type(identity[key]) is not int or identity[key] <= 0 for key in ("handle", "process_id"))
            or type(identity["process_create_time"]) not in (int, float)
            or not math.isfinite(identity["process_create_time"]) or identity["process_create_time"] <= 0
            or value.get("authorizes_action", False) is not False):
        raise ValueError("parallel_result_binding_invalid")
    return {"capture_id": value["capture_id"], "attempt_id": value["attempt_id"],
            "window_identity": dict(identity)}


def _validate_result(name, value):
    identity = _binding(value)
    if name == "ground":
        if type(value.get("candidate")) is not dict or not value["candidate"]:
            raise ValueError("parallel_candidate_unavailable")
    else:
        if (type(value.get("disposition")) is not str
                or value["disposition"] not in {"pass", "block", "review", "unknown", "unavailable"}
                or type(value.get("authenticated")) is not bool
                or value["disposition"] in {"pass", "block"} and value["authenticated"] is not True):
            raise ValueError("parallel_scene_unverified")
    return identity


def run_parallel_scene_probe(*, ground, probe, deadline_ns, cancelled) -> dict:
    """回调接收同一 deadline_ns/cancelled；调用方保证只做网络或纯计算并认证原请求。"""
    if not callable(ground) or not callable(probe) or not callable(cancelled):
        raise ValueError("parallel_callbacks_required")
    if type(deadline_ns) is not int or deadline_ns <= 0:
        raise ValueError("parallel_deadline_invalid")
    started_ns = perf_counter_ns()
    stop, wake, lock = Event(), Event(), Lock()
    futures = {}
    attempted = {"ground": 0, "probe": 0}
    errors = {}
    received, bindings = {}, {}

    def cancellation():
        value = cancelled()
        if type(value) is not bool:
            raise ValueError("parallel_cancellation_unknown")
        return value

    def should_stop():
        return stop.is_set() or perf_counter_ns() >= deadline_ns or cancellation()

    def finish(status, reason, *, matched=None):
        stop.set()
        for future in futures.values():
            if not future.done():
                future.cancel()
        with lock:
            counts = dict(attempted)
        # 不 join 尚在等待 HTTP 的 daemon 线程；已开始的远端请求仍可能产生费用。
        return {"schema": "parallel_scene_probe.v1", "status": status, "reason": reason,
            "authorizes_action": False, "requires_candidate_review": True,
            "grounding": deepcopy(received.get("ground")) if status == "joined" else None,
            "scene": deepcopy(received.get("probe")) if status in {"joined", "blocked"} else None,
            "binding_matched": matched, "started_attempts": counts,
            "unfinished_at_return": [name for name, future in futures.items() if not future.done()],
            "cancellation_requested": status != "joined",
            "cancellation_does_not_imply_no_charge": True, "errors": dict(errors),
            "elapsed_ms": (perf_counter_ns() - started_ns) / 1_000_000}

    def interrupted():
        try:
            if cancellation():
                return "cancelled", "caller_cancelled"
        except Exception as error:
            errors["cancelled"] = type(error).__name__
            return "unknown", "cancellation_check_failed"
        if perf_counter_ns() >= deadline_ns:
            return "timeout", "shared_deadline_expired"
        return None

    def calculate(name, callback, future):
        if not future.set_running_or_notify_cancel():
            wake.set()
            return
        try:
            if should_stop():
                record = {"stopped": True}
            else:
                with lock:
                    attempted[name] += 1
                value = callback(deadline_ns=deadline_ns, cancelled=should_stop)
                record = {"value": deepcopy(value)}
        except BaseException as error:
            # 线程异常转换为显式失败类型，不回显潜在秘密，也不假装场景阻挡。
            record = {"error_type": type(error).__name__}
        future.set_result(record)
        wake.set()

    interruption = interrupted()
    if interruption is not None:
        return finish(*interruption)
    try:
        for name, callback in (("ground", ground), ("probe", probe)):
            future = Future()
            futures[name] = future
            Thread(target=calculate, args=(name, callback, future), daemon=True,
                name="parallel-scene-" + name).start()
    except Exception as error:
        errors["startup"] = type(error).__name__
        return finish("unknown", "worker_start_failed")

    while True:
        interruption = interrupted()
        if interruption is not None:
            return finish(*interruption)
        for name, future in futures.items():
            if name in received or not future.done():
                continue
            if future.cancelled():
                return finish("unknown", "worker_cancelled")
            record = future.result()
            if "error_type" in record:
                errors[name] = record["error_type"]
                return finish("unknown", "worker_failed")
            if record.get("stopped"):
                interruption = interrupted()
                return finish(*(interruption or ("unknown", "worker_stopped")))
            try:
                bindings[name] = _validate_result(name, record["value"])
            except (ValueError, TypeError, KeyError):
                return finish("unknown", "result_binding_or_scope_invalid")
            received[name] = record["value"]
        interruption = interrupted()
        if interruption is not None:
            return finish(*interruption)
        matched = len(received) == 2
        if matched and bindings["ground"] != bindings["probe"]:
            return finish("unknown", "cross_frame_attempt_or_window")
        if received.get("probe", {}).get("disposition") == "block":
            return finish("blocked", "authenticated_scene_block", matched=matched or None)
        if matched:
            return finish("joined", "candidate_review_required", matched=True)
        wake.wait(min(.01, max(0, (deadline_ns - perf_counter_ns()) / 1_000_000_000)))
        wake.clear()
