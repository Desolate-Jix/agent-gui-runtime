"""本地无学习单步会话：一条命令一份回执和后图，不自动规划或重放输入。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_step_command(coordinator, target, command):
    operation = command["operation"]
    request = command["request"]
    # 默认时机由公共运行时决定，脚本只转交显式覆盖。
    return coordinator.execute_local_step(
        target_window_handle=target["handle"], target_process_id=target["process_id"],
        operation=operation, request=request, include_observation=True,
        observation_wait_ms=command.get("observation_wait_ms"))


def run_read_text_command(capture_current, command):
    from app.operation.screen_reading.captured_text import read_captured_text
    observation = {**capture_current(), 'capture_id': 'text-' + secrets.token_hex(16),
                   'captured_at': now()}
    result = read_captured_text(observation, max_chars=command.get('max_chars', 10000))
    return result, observation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--local-no-learning", action="store_true", required=True)
    parser.add_argument("--observer", choices=["minimal", "original"], default="minimal")
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    from app.core.screenshot import ScreenshotService
    from app.core.process_sampler import ProcessSampler
    from app.desktop_review.host import DesktopReviewHost
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    import psutil
    parent_created = psutil.Process(args.parent_pid).create_time() if args.parent_pid else None

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    for name in ("commands", "responses"):
        (out / name).mkdir()
    host = None
    co = None
    target = None
    stop = threading.Event()
    sampler_thread = None
    errors = []
    report = {"started_at": now(), "phase": "starting", "runner_pid": os.getpid(),
              "learning_enabled": False, "observer": args.observer, "completed_commands": []}
    import ctypes
    report["host_is_admin"] = bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == "nt" else False
    sampler = ProcessSampler(os.getpid(), extra_root_getter=lambda: target, sample_interval=3)

    def sample_once():
        if args.observer == "minimal":
            return sampler.snapshot()
        started = time.perf_counter()
        root = psutil.Process()
        processes = {root.pid: root, **{p.pid: p for p in root.children(recursive=True)}}
        if target:
            try:
                browser = psutil.Process(target["process_id"])
                processes[browser.pid] = browser
                processes.update({p.pid: p for p in browser.children(recursive=True)})
            except psutil.NoSuchProcess:
                pass
        rows = []
        for p in processes.values():
            try:
                with p.oneshot():
                    cpu = p.cpu_times()
                    rows.append({"pid": p.pid, "ppid": p.ppid(), "name": p.name(), "exe": p.exe(),
                        "created_at_unix": p.create_time(), "threads": p.num_threads(),
                        "rss_bytes": p.memory_info().rss, "cpu_user_seconds": cpu.user,
                        "cpu_system_seconds": cpu.system, "status": p.status()})
            except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
                rows.append({"pid": p.pid, "observation_error": type(error).__name__})
        return {"at": now(), "processes": rows,
                "collection_ms": round((time.perf_counter() - started) * 1000, 3)}

    def sample_loop():
        with (out / "process-samples.jsonl").open("a", encoding="utf-8") as stream:
            while not stop.is_set():
                try:
                    snapshot = sample_once()
                except Exception as error:
                    snapshot = {"at": now(), "processes": [], "collection_error": type(error).__name__}
                stream.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
                stream.flush()
                stop.wait(3 if args.observer == "minimal" else 1)

    def capture():
        if target is None:
            raise ValueError("select a target window before observing")
        bound = co._windows().bind_window_by_handle(target["handle"])
        if bound is None or bound.process_id != target["process_id"]:
            raise ValueError("target window identity changed")
        image = ScreenshotService(window_manager=co._windows(), capture_dir=out / "captures").capture_window(
            focus_window=False, purpose="live-latency-observation")
        return {**image, "window": {"handle": bound.handle, "process_id": bound.process_id},
                "sha256": hashlib.sha256(Path(image["image_path"]).read_bytes()).hexdigest()}

    try:
        host = DesktopReviewHost(out / "inbox.json", out / "reviews", secrets.token_urlsafe(32))
        host.start()
        co = NativeSingleStepCoordinator(out / "reviews", host.facade, host, enable_agent_learning=False,
            runtime_output_root=out / "runtime-output", vision_config_path=out / "configs/vision.json")
        co.set_automatic_safety_interception(False)
        co.set_keep_models_loaded(True)
        report["model_configuration"] = co.configure_vista_model(model_directory=str(args.model_directory.resolve()))
        report["phase"] = "ready"
        write(out / "report.json", report)
        sampler_thread = threading.Thread(target=sample_loop, daemon=True, name="live-process-sampler")
        sampler_thread.start()
        done = set()
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            if args.parent_pid:
                try:
                    if psutil.Process(args.parent_pid).create_time() != parent_created:
                        break
                except psutil.NoSuchProcess:
                    break
            paths = sorted(p for p in (out / "commands").glob("*.json") if p.name not in done)
            if (out / "closing.json").is_file():
                closing_id = json.loads((out / "closing.json").read_text(encoding="utf-8"))["request_id"]
                paths.sort(key=lambda p: p.stem == closing_id)
            if not paths:
                stop.wait(.03)
                continue
            path = paths[0]
            command = {}
            response = {"command": command, "received_at": now()}
            if args.observer == "original":
                response["processes_before"] = sample_once()
            response["started_at"] = now()
            started = time.perf_counter()
            kind = None
            try:
                command = json.loads(path.read_text(encoding="utf-8"))
                response["command"] = command
                kind = command["kind"]
                if kind == "discover":
                    response["result"] = co.discover_applications()
                elif kind == "select":
                    preview = co.preview_selected_window_preparation(
                        target_window_handle=command["handle"], target_process_id=command["process_id"])
                    response["preparation_preview"] = preview
                    response["result"] = co.confirm_window_preparation(preview["preparation_id"])
                    target = response["result"]["window"]
                    response["observation"] = co._owner.call(capture)
                elif kind == "launch":
                    preview = co.preview_application_launch(app_id=command["app_id"], url=command.get("url"))
                    response["preparation_preview"] = preview
                    result = co.confirm_window_preparation(preview["preparation_id"])
                    target = result["window"]
                    response["result"] = result
                elif kind == "maximize":
                    preview = co.preview_selected_window_maximize(target_window_handle=target["handle"],
                        target_process_id=target["process_id"])
                    response["preparation_preview"] = preview
                    response["result"] = co.confirm_window_preparation(preview["preparation_id"])
                    response["observation"] = co._owner.call(capture)
                elif kind == "close_launched_window":
                    response["result"] = co.close_launched_window(
                        target_window_handle=command["handle"], target_process_id=command["process_id"])
                    if (response["result"].get("status") == "window_closed" and target
                            and target["handle"] == command["handle"]
                            and target["process_id"] == command["process_id"]):
                        target = None
                elif kind == "prepare_models":
                    response["result"] = co.prepare_local_step_models(prepare_ocr=True)
                elif kind == "release_models":
                    response["result"] = co.release_resident_models()
                elif kind == "capture":
                    response["observation"] = co._owner.call(capture)
                elif kind == "read_text":
                    response["result"], response["observation"] = co._owner.call(
                        lambda: run_read_text_command(capture, command))
                elif kind == "step":
                    response["result"] = run_step_command(co, target, command)
                    observed = response["result"].get("observation", {})
                    response["observation"] = observed.get("capture")
                elif kind == "close":
                    response["result"] = {"closing": True}
                else:
                    raise ValueError("unsupported local session command")
                response["status"] = "returned"
            except Exception as error:
                response.update(status="failed", error_type=type(error).__name__, error=str(error),
                    automatic_retry_allowed=False)
                if isinstance(getattr(error, "diagnostics", None), dict):
                    response["diagnostics"] = error.diagnostics
            response["finished_at"] = now()
            response["command_wall_ms"] = round((time.perf_counter() - started) * 1000, 3)
            if args.observer == "original":
                response["processes_after"] = sample_once()
            response["response_available_at"] = now()
            write(out / "responses" / path.name, response)
            done.add(path.name)
            report["completed_commands"].append({"name": path.name, "status": response["status"]})
            report["target"] = target
            write(out / "report.json", report)
            if kind == "close":
                break
        report["phase"] = "stopped"
    except Exception as error:
        report.update(phase="failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        if co is not None:
            try:
                co.shutdown()
            except Exception as error:
                errors.append({"operation": "shutdown", "error_type": type(error).__name__})
        try:
            if host is not None:
                host.close()
        except Exception as error:
            errors.append({"operation": "host_close", "error_type": type(error).__name__})
        stop.set()
        if sampler_thread is not None:
            sampler_thread.join(timeout=10)
        report.update(finished_at=now(), cleanup_errors=errors, host_phase=host.status()["phase"] if host else "not_created",
            sampler_stopped=sampler_thread is None or not sampler_thread.is_alive())
        write(out / "report.json", report)


if __name__ == "__main__":
    main()
