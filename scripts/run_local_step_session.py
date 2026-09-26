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
    from app.core.json_snapshot import write_json_snapshot
    write_json_snapshot(path, data)


def configure_recognition_startup(coordinator, args, report):
    from app.vision.recognition_source import RecognitionSourceConfig
    if args.recognition_source == "external_api":
        raise ValueError("external_api recognition source is not implemented")
    config = RecognitionSourceConfig.model_validate({"source": args.recognition_source,
        "delegate_profile": args.delegate_profile})
    if config.source == "local" and (args.model_directory is None or not args.model_directory.is_dir()):
        raise ValueError("local recognition requires an existing --model-directory")
    report["recognition_source"] = config.source
    report["delegate_profile"] = config.delegate_profile
    # Agent 视觉路线不配置、加载或预热本地 VISTA。
    report["model_configuration"] = (coordinator.configure_vista_model(
        model_directory=str(args.model_directory.resolve())) if config.source == "local" else None)


def prepare_models_for_source(coordinator, recognition_source):
    return (coordinator.prepare_local_step_models(prepare_ocr=True)
        if recognition_source == "local" else
        {"status": "model_not_required", "recognition_source": recognition_source})


def run_step_command(coordinator, target, command):
    operation = command["operation"]
    request = command["request"]
    # 默认时机由公共运行时决定，脚本只转交显式覆盖。
    return coordinator.execute_local_step(
        target_window_handle=target["handle"], target_process_id=target["process_id"],
        operation=operation, request=request, include_observation=True,
        observation_wait_ms=command.get("observation_wait_ms"),
        **({"observation_condition": command["observation_condition"]}
           if command.get("observation_condition") is not None else {}))


def run_read_text_command(capture_current, command, *, recognition_source="local"):
    observation = {**capture_current(), 'capture_id': 'text-' + secrets.token_hex(16),
                   'captured_at': now()}
    if recognition_source != 'local':
        return {'status': 'agent_read_required', 'recognition_source': recognition_source,
            'text': None, 'next_action': 'read_returned_original_image',
            'max_chars': command.get('max_chars', 10000), 'action_executed': False}, observation
    from app.operation.screen_reading.captured_text import read_captured_text
    result = read_captured_text(observation, max_chars=command.get('max_chars', 10000))
    return result, observation


def check_agent_command_admission(jobs, kind):
    if jobs is not None and jobs.active and kind not in {
            'close', 'agent_command_status', 'agent_command_continue', 'agent_command_cancel',
            'grounding_resolve', 'grounding_status', 'grounding_cancel'}:
        raise ValueError('agent_command_in_progress: continue, inspect or cancel the original command')


def dispatch_agent_command(jobs, request_id, command, target):
    from app.vision.agent_command_contract import AGENT_COMMANDS
    kind = command['kind']
    if kind in AGENT_COMMANDS:
        if jobs is None:
            raise ValueError('agent_command_requires_agent_source')
        request = AGENT_COMMANDS[kind].model_validate(command['request'])
        if kind == 'agent_command_continue':
            return jobs.resume(request.command_id, request.grounding_request_id, request_id)
        return (jobs.cancel if kind == 'agent_command_cancel' else jobs.get)(request.command_id)
    if jobs is not None and (kind in {'form_fill', 'input_sequence'} or
            kind == 'step' and command.get('operation') == 'execute_recognition_plan'):
        return jobs.start(request_id, command, target, command.get('vision_capabilities') or {})
    return None


def run_grounding_command(store, capture_current, request_id, command, *, session_configuration=None):
    from app.vision.grounding_commands import validate_grounding_command
    from app.vision.grounding_contract import GroundingResult
    from app.vision.grounding_handoff import GroundingHandoffError
    from app.vision.recognition_source import resolve_recognition_route
    request = validate_grounding_command(command["kind"], command["request"])
    if command["kind"] == "grounding_execute":
        raise GroundingHandoffError("use_grounding_execution_dispatch")
    if command["kind"] == "grounding_prepare":
        if session_configuration is not None and request.configuration != session_configuration:
            raise GroundingHandoffError("session_recognition_source_mismatch")
        route = resolve_recognition_route(request.configuration, request.capabilities)
        if route.status != "eligible":
            raise GroundingHandoffError(route.code)
        if route.dispatch_owner != "agent_client":
            raise GroundingHandoffError("handoff_requires_agent_source")
        observation = {**capture_current(), "capture_id": "grounding-" + secrets.token_hex(16)}
        state = store.prepare(request_id, goal=request.goal, capture=observation,
                              configuration=request.configuration, capabilities=request.capabilities)
    elif command["kind"] == "grounding_resolve":
        state = store.resolve(request.grounding_request_id, request.result)
    elif command["kind"] == "grounding_cancel":
        state = store.cancel(request.grounding_request_id)
    else:
        state = store.get(request.grounding_request_id)
    result = {**state, "execution_available": state["phase"] == "grounding_ready"}
    if state["phase"] == "awaiting_grounding":
        result["output_schema"] = GroundingResult.model_json_schema()
    elif state["phase"] == "grounding_ready":
        result["next_action"] = "submit_grounding_execute_with_original_request_id"
    return result, state["capture"]


def run_grounding_execution(store, coordinator, selected, request_id, command):
    from app.core.agent_grounding_target import AgentGroundingTarget
    from app.vision.grounding_commands import validate_grounding_command
    from app.vision.grounding_handoff import GroundingHandoffError
    request = validate_grounding_command(command["kind"], command["request"])
    state = store.get(request.grounding_request_id)
    identity = state["capture"]["window_identity"]
    if (not isinstance(selected, dict)
            or any(selected.get(key) != identity[key] for key in ("handle", "process_id"))):
        raise GroundingHandoffError("selected_target_changed")
    claimed = store.claim_execution(request.grounding_request_id, request_id)
    target = None
    try:
        target = AgentGroundingTarget(claimed)
        result = coordinator.execute_local_step(target_window_handle=identity["handle"],
            target_process_id=identity["process_id"], operation="execute_recognition_plan",
            request={"goal": target.goal}, grounding_target=target, include_observation=True)
        result["grounding_request_id"] = request.grounding_request_id
    except Exception as error:
        # 输入异常可能发生在派发之后，记录不确定性，绝不退回可执行状态。
        store.finish_execution(request.grounding_request_id, request_id,
            {"phase": "result_unknown" if target and target.input_claimed else "failed",
             "error_type": type(error).__name__, "automatic_retry_allowed": False},
            input_attempted=bool(target and target.input_claimed))
        raise
    store.finish_execution(request.grounding_request_id, request_id, result,
                           input_attempted=target.input_claimed)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path)
    parser.add_argument("--recognition-source", choices=["local", "agent_current", "agent_delegate", "external_api"],
                        default="local")
    parser.add_argument("--delegate-profile")
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
    agent_jobs = None
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
        process_created = psutil.Process(bound.process_id).create_time()
        image = ScreenshotService(window_manager=co._windows(), capture_dir=out / "captures").capture_window(
            focus_window=False, purpose="live-latency-observation")
        if psutil.Process(bound.process_id).create_time() != process_created:
            raise ValueError("target process identity changed during capture")
        return {**image, "window": {"handle": bound.handle, "process_id": bound.process_id},
                "window_identity": {"handle": bound.handle, "process_id": bound.process_id,
                                    "process_create_time": process_created},
                "sha256": hashlib.sha256(Path(image["image_path"]).read_bytes()).hexdigest()}

    try:
        host = DesktopReviewHost(out / "inbox.json", out / "reviews", secrets.token_urlsafe(32))
        host.start()
        co = NativeSingleStepCoordinator(out / "reviews", host.facade, host, enable_agent_learning=False,
            runtime_output_root=out / "runtime-output", vision_config_path=out / "configs/vision.json")
        co.set_automatic_safety_interception(False)
        co.set_keep_models_loaded(True)
        configure_recognition_startup(co, args, report)
        report["phase"] = "ready"
        write(out / "report.json", report)
        from app.vision.grounding_handoff import GroundingHandoffStore
        from app.vision.grounding_commands import GROUNDING_COMMANDS
        from app.vision.recognition_source import RecognitionSourceConfig
        session_configuration = RecognitionSourceConfig(source=args.recognition_source,
                                                        delegate_profile=args.delegate_profile)
        grounding_store = GroundingHandoffStore(out, owner_id="host-" + secrets.token_hex(16))
        if args.recognition_source != 'local':
            from app.vision.agent_command_jobs import AgentCommandJobs
            agent_jobs = AgentCommandJobs(co, grounding_store, capture, session_configuration)
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
                check_agent_command_admission(agent_jobs, kind)
                agent_result = dispatch_agent_command(agent_jobs, path.stem, command, target)
                if agent_result is not None:
                    response['result'] = agent_result
                    response['observation'] = (agent_result.get('observation') or {}).get('capture')
                elif kind == "grounding_execute":
                    response["result"] = run_grounding_execution(grounding_store, co, target, path.stem, command)
                    response["observation"] = response["result"].get("observation", {}).get("capture")
                elif kind in GROUNDING_COMMANDS:
                    response["result"], response["observation"] = co._owner.call(
                        lambda: run_grounding_command(grounding_store, capture, path.stem, command,
                                                      session_configuration=session_configuration))
                elif kind == "discover":
                    response["result"] = co.discover_applications()
                elif kind in {"desktop_capture", "desktop_click"}:
                    from app.desktop_review.desktop_command import prepare_desktop_target
                    # 丢弃旧应用选择，准备失败时不得误用旧坐标或旧目标。
                    target = None
                    desktop = prepare_desktop_target(co)
                    target = desktop["window"]
                    response["desktop_context"] = desktop
                    if kind == "desktop_capture":
                        response["result"] = {"status": "focused", "window": target,
                                              "binding_mode": "automatic_desktop_host"}
                        response["observation"] = co._owner.call(capture)
                    else:
                        step = {**command, 'kind': 'step', "operation": "execute_recognition_plan"}
                        response["result"] = (dispatch_agent_command(agent_jobs, path.stem, step, target)
                            if agent_jobs is not None else run_step_command(co, target, step))
                        response["observation"] = response["result"].get("observation", {}).get("capture")
                elif kind == "select":
                    preview = co.preview_selected_window_preparation(
                        target_window_handle=command["handle"], target_process_id=command["process_id"])
                    response["preparation_preview"] = preview
                    response["result"] = co.confirm_window_preparation(preview["preparation_id"])
                    target = response["result"]["window"]
                    response["observation"] = co._owner.call(capture)
                elif kind == "launch":
                    target = None
                    preview = co.preview_application_launch(prefer_existing=command.get('prefer_existing', True),
                        **{key: command[key] for key in ("app_id", "name", "path", "url") if key in command})
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
                    response["result"] = prepare_models_for_source(co, args.recognition_source)
                elif kind == "release_models":
                    response["result"] = co.release_resident_models()
                elif kind == "capture":
                    response["observation"] = co._owner.call(capture)
                elif kind == "read_text":
                    response["result"], response["observation"] = co._owner.call(
                        lambda: run_read_text_command(capture, command, recognition_source=args.recognition_source))
                elif kind == "step":
                    response["result"] = run_step_command(co, target, command)
                    observed = response["result"].get("observation", {})
                    response["observation"] = observed.get("capture")
                elif kind == "form_fill":
                    from app.desktop_review.form_fill import run_form_fill
                    progress = out / "sequence-progress"
                    progress.mkdir(exist_ok=True)
                    response["result"] = run_form_fill(co, target, command["request"],
                        persist=lambda value: write(progress / path.name, value))
                    response["observation"] = response["result"].get("observation", {}).get("capture")
                elif kind == "input_sequence":
                    from app.desktop_review.input_sequence import run_input_sequence
                    progress = out / "sequence-progress"
                    progress.mkdir(exist_ok=True)
                    response["result"] = run_input_sequence(co, target, command["request"],
                        observation_wait_ms=command.get("observation_wait_ms"),
                        observation_condition=command.get("observation_condition"),
                        persist=lambda value: write(progress / path.name, value))
                    response["observation"] = response["result"].get("observation", {}).get("capture")
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
        terminal_phase = report.get('phase')
        if agent_jobs is not None:
            # 先停止组合命令再销毁协调器，未退出的输入线程不算清理完成。
            while not agent_jobs.close(timeout=5):
                report.update(phase='cleanup_pending', cleanup_verified=False,
                    agent_command_cleanup={'status': 'waiting_for_worker', 'automatic_retry_allowed': False})
                write(out / 'report.json', report)
            report['agent_command_cleanup'] = {'status': 'stopped'}
        if co is not None:
            from app.desktop_review.session_cleanup import shutdown_retaining_owner
            from app.core.json_snapshot import read_json_snapshot

            def cleanup_retry_token():
                path = out / 'cleanup-retry.json'
                return read_json_snapshot(path).get('request_id') if path.is_file() else None

            shutdown_retaining_owner(co, report, lambda: write(out / 'report.json', report), cleanup_retry_token)
            report['phase'] = 'failed' if terminal_phase == 'failed' else 'stopped'
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
