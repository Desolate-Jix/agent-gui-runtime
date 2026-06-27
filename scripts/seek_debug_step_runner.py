from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from seek_mvp_traversal_runner import (  # noqa: E402
    SeekTraversalError,
    _adaptive_wheel_clicks,
    _compact_action_response,
    _compact_type_response,
    _detail_observation_fingerprint,
    _execute_job_card,
    _execute_apply_entry,
    _observe,
    _resize_bound_window,
    _result_payload,
    _roi_bbox_payload,
    _safe_form_fill_attempt,
    _trace_apply_entry_summary,
    _write_json,
)
from app.seek.application import _collect_visible_items, assess_seek_application_flow_state, build_seek_apply_flow_decision  # noqa: E402
from app.seek.answer_plan import build_application_answer_plan  # noqa: E402
from app.seek.cover_letter import build_cover_letter_draft  # noqa: E402
from app.seek.employer_questions import (  # noqa: E402
    build_employer_question_answer_plan,
    build_employer_question_answer_preview,
    build_employer_question_inventory,
)
from app.seek.extraction import extract_seek_job_cards, extract_seek_job_detail, _trim_seek_detail_texts  # noqa: E402
from app.seek.execute_observation import build_seek_execute_observation  # noqa: E402
from app.seek.final_review import build_seek_final_review_extraction  # noqa: E402
from app.seek.form_inventory import build_seek_form_field_inventory  # noqa: E402
from app.seek.learn_artifacts import scroll_target_for_action  # noqa: E402
from app.seek.matching import load_candidate_profile, save_suitable_job_record, score_seek_job  # noqa: E402
from app.seek.scroll_containers import SEEK_JOB_DETAIL, discover_seek_scroll_containers, get_scroll_container  # noqa: E402
from app.execute.read_region_batch import build_read_region_batch_report  # noqa: E402
from app.execute.scroll_scope import build_scroll_scope_invariant  # noqa: E402
from app.execute.dataflow_contracts import (  # noqa: E402
    merge_read_batch_into_detail_snapshot,
    put_latest_detail_snapshot,
    require_latest_detail_snapshot,
    with_detail_snapshot,
)
from app.execute.candidate_contracts import validate_action_candidate_target_at_point  # noqa: E402
from app.execute.ui_diff_verification import build_ui_diff_verification  # noqa: E402


DEFAULT_SEEK_URL = "https://nz.seek.com/"
DEFAULT_RUN_DIR = Path("logs/smoke/seek_debug_step_run_latest")
DEFAULT_APPLICATION_FLOW_REPLAY = Path("logs/smoke/seek_application_flow_replay_20260620.json")
DEFAULT_PERSONAL_CANDIDATE_PROFILE = Path(r"D:\资料\CV\candidate_profile_wenqingji_personal.json")
DEFAULT_PROJECT_CANDIDATE_PROFILE = Path("artifacts/seek/candidate_profile_wenqingji_draft.json")


def _path_exists_no_raise(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


DEFAULT_CANDIDATE_PROFILE = (
    DEFAULT_PERSONAL_CANDIDATE_PROFILE
    if _path_exists_no_raise(DEFAULT_PERSONAL_CANDIDATE_PROFILE)
    else DEFAULT_PROJECT_CANDIDATE_PROFILE
)
STATE_CONTRACT = "seek_debug_step_state_v1"
REPORT_CONTRACT = "seek_debug_step_report_v1"
JOB_ARCHIVE_CONTRACT = "seek_job_archive_v1"


def _utcish_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


def _get_json(base_url: str, endpoint: str, timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{endpoint}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise SeekTraversalError(f"{endpoint} returned HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise SeekTraversalError(f"{endpoint} request failed: {exc}") from exc
    return json.loads(raw)


def _post_json(base_url: str, endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{endpoint}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise SeekTraversalError(f"{endpoint} returned HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise SeekTraversalError(f"{endpoint} request failed: {exc}") from exc
    return json.loads(raw)


def _screen_reading_from_observation(observation: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(observation.get("screen_reading"), dict):
        return observation["screen_reading"]
    parse_result = observation.get("parse_result") if isinstance(observation.get("parse_result"), dict) else {}
    if isinstance(parse_result.get("screen_reading"), dict):
        return parse_result["screen_reading"]
    if isinstance(observation.get("texts"), list):
        return observation
    return None


def _state_path(run_dir: Path) -> Path:
    return run_dir / "state.json"


def _load_state(run_dir: Path) -> dict[str, Any]:
    path = _state_path(run_dir)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            payload.setdefault("contract_version", STATE_CONTRACT)
            payload.setdefault("run_dir", str(run_dir))
            payload.setdefault("steps", [])
            payload.setdefault("safety", _default_safety())
            return payload
    return {
        "contract_version": STATE_CONTRACT,
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "created_at": _utcish_now(),
        "updated_at": _utcish_now(),
        "phase": "initialized",
        "step_index": 0,
        "bound_window": None,
        "current_job": None,
        "cards_payload": None,
        "detail": None,
        "match_decision": None,
        "steps": [],
        "safety": _default_safety(),
        "next_allowed_steps": ["open"],
    }


def _save_state(run_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _utcish_now()
    state_path = _state_path(run_dir)
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    _write_json(tmp_path, state)
    tmp_path.replace(state_path)


def _default_safety() -> dict[str, Any]:
    return {
        "final_submit_forbidden": True,
        "fill_safe_fields_allowed": False,
        "max_real_action_per_step": 1,
        "debug_mode_one_step_then_stop": True,
    }


def _step_dir(run_dir: Path, step_index: int, step_name: str) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in step_name)
    return run_dir / f"step_{step_index:03d}_{safe_name}"


def _image_path(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("image_path", "screenshot_path", "path"):
        if payload.get(key):
            return str(payload[key])
    for key in ("live_capture", "capture", "screenshot"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = _image_path(value)
            if nested:
                return nested
    return None


def _trace_paths(*items: Any) -> list[str]:
    paths: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get("trace_path")
        if value:
            paths.append(str(value))
        data = item.get("data")
        if isinstance(data, dict):
            paths.extend(_trace_paths(data))
        result = _result_payload(item)
        if result and result is not item:
            paths.extend(_trace_paths(result))
    return list(dict.fromkeys(paths))


def _capture(base_url: str, timeout: float) -> dict[str, Any]:
    response = _post_json(base_url, "/state/capture_window", {"save_image": True}, timeout)
    if response.get("success") is not True:
        raise SeekTraversalError(f"capture_window failed: {response.get('error') or response.get('message')}")
    payload = response.get("data") if isinstance(response.get("data"), dict) else {}
    return {"response": response, "image_path": _image_path(payload), "payload": payload}


def _execute_debug_artifacts(
    *,
    observation: dict[str, Any] | None = None,
    flow_state: dict[str, Any] | None = None,
    employer_question_inventory: dict[str, Any] | None = None,
    application_answer_plan: dict[str, Any] | None = None,
    before_image: str | None = None,
    after_image: str | None = None,
    expected_change: str | None = None,
    target_bbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    if isinstance(observation, dict) or isinstance(flow_state, dict):
        artifacts["execute_observation"] = build_seek_execute_observation(
            observation,
            application_flow_state=flow_state,
        )
    if isinstance(flow_state, dict):
        artifacts["form_field_inventory"] = build_seek_form_field_inventory(
            flow_state,
            employer_question_inventory=employer_question_inventory,
            application_answer_plan=application_answer_plan,
        )
    if before_image or after_image:
        artifacts["ui_diff_verification"] = build_ui_diff_verification(
            before_image,
            after_image,
            expected_change=expected_change,
            target_bbox=target_bbox,
        )
    return artifacts


def _runtime_state(base_url: str, timeout: float) -> dict[str, Any]:
    response = _get_json(base_url, "/state", timeout)
    if response.get("success") is not True:
        raise SeekTraversalError(f"state failed: {response.get('error') or response.get('message')}")
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    return {"response": response, "payload": data}


def _rect_size(payload: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(payload, dict):
        return None
    rect = payload.get("rect") if isinstance(payload.get("rect"), dict) else None
    if not rect:
        return None
    try:
        return {
            "width": int(rect["right"]) - int(rect["left"]),
            "height": int(rect["bottom"]) - int(rect["top"]),
        }
    except Exception:
        return None


def _bound_window_verification(payload: dict[str, Any], *, min_width: int, min_height: int) -> dict[str, Any]:
    size = _rect_size(payload)
    process_name = str(payload.get("process_name") or "").lower()
    title = str(payload.get("window_title") or "")
    title_key = "".join(
        char for char in unicodedata.normalize("NFKC", title).casefold() if unicodedata.category(char) != "Cf"
    )
    seek_title_match = any(marker in title_key for marker in ("seek", "job vacancies", "software engineer jobs"))
    return {
        "contract_version": "seek_bound_window_verification_v1",
        "bound": payload.get("bound") is True,
        "process_name": process_name or None,
        "title": title or None,
        "process_is_external_browser": process_name in {"msedge.exe", "chrome.exe"},
        "title_contains_seek": seek_title_match,
        "title_seek_match_markers": ["seek", "job vacancies", "software engineer jobs"],
        "window_active": payload.get("is_active"),
        "coordinate_window_size": size,
        "expected_minimum_size": {"width": int(min_width), "height": int(min_height)},
        "window_size_ok": bool(size and size["width"] >= min_width and size["height"] >= min_height),
        "is_codex_browser": False if process_name in {"msedge.exe", "chrome.exe"} else None,
    }


def _apps_snapshot(base_url: str, timeout: float) -> dict[str, Any]:
    response = _get_json(base_url, "/apps", timeout)
    if response.get("success") is not True:
        raise SeekTraversalError(f"apps list failed: {response.get('error') or response.get('message')}")
    return response


def _open_seek_debug(base_url: str, *, url: str, app_name: str, timeout: float) -> dict[str, Any]:
    app_key = str(app_name or "edge").lower()
    executable = "chrome.exe" if app_key == "chrome" else "msedge.exe"
    return _post_json(
        base_url,
        "/apps/open",
        {
            "app_id": app_name,
            "command": [executable, "--new-window"],
            "url": url,
            "process_name": executable,
            "title": "SEEK",
            "bind_after_open": True,
            "wait_seconds": 2.5,
        },
        timeout,
    )


def _bind_seek_debug_window(base_url: str, *, app_name: str, timeout: float) -> dict[str, Any]:
    app_key = str(app_name or "edge").lower()
    executable = "chrome.exe" if app_key == "chrome" else "msedge.exe"
    return _post_json(
        base_url,
        "/session/bind_window",
        {
            "process_name": executable,
            "title": "SEEK",
        },
        timeout,
    )


def _submit_seek_search_query(
    base_url: str,
    *,
    query: str,
    x: int,
    y: int,
    timeout: float,
    wait_seconds: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    request = {
        "text": query,
        "x": int(x),
        "y": int(y),
        "click_before_typing": True,
        "clear_existing": True,
        "submit": True,
        "restore_clipboard": True,
        "dry_run": False,
        "metadata": {
            "contract_version": "seek_search_submit_request_v1",
            "action_taxonomy": "type_public_search_query",
            "input_category": "public_search_query",
            "submit_method": "enter_key",
            "target_latency_ms": 20000,
        },
    }
    response = _post_json(base_url, "/action/type_text", request, timeout)
    states: list[dict[str, Any]] = []
    ready = False
    deadline = time.perf_counter() + max(0.0, float(wait_seconds))
    query_key = str(query or "").casefold()
    while time.perf_counter() < deadline:
        try:
            state = _runtime_state(base_url, min(timeout, 5.0))
        except Exception as exc:
            states.append({"error": str(exc)})
            time.sleep(0.4)
            continue
        payload = state.get("payload") if isinstance(state.get("payload"), dict) else {}
        states.append(payload)
        title = str(payload.get("window_title") or payload.get("title") or "")
        title_key = title.casefold()
        if "seek" in title_key and ("job" in title_key or (query_key and query_key in title_key)):
            ready = True
            break
        time.sleep(0.4)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "contract_version": "seek_search_submit_v1",
        "status": "ok" if response.get("success") is True and ready else "needs_review",
        "query": query,
        "input_point": {"x": int(x), "y": int(y)},
        "submit_method": "type_text_submit_enter",
        "response": _compact_type_response(response),
        "page_ready": ready,
        "elapsed_ms": elapsed_ms,
        "target_latency_ms": 20000,
        "within_target_latency": elapsed_ms <= 20000,
        "state_poll_count": len(states),
        "last_state": states[-1] if states else None,
        "trace_paths": _trace_paths(response),
    }


def _seek_window_candidates(apps_response: dict[str, Any]) -> list[dict[str, Any]]:
    data = apps_response.get("data") if isinstance(apps_response.get("data"), dict) else {}
    windows = data.get("windows") or data.get("running_windows") or data.get("visible_windows") or []
    candidates: list[dict[str, Any]] = []
    for item in windows if isinstance(windows, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        process = str(item.get("process_name") or "").lower()
        if ("seek" in title.lower() or "software engineer jobs" in title.lower()) and process in {
            "msedge.exe",
            "chrome.exe",
        }:
            candidates.append(item)
    return candidates


def _close_top_level_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    closed: list[dict[str, Any]] = []
    if sys.platform != "win32":
        return closed
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    wm_close = 0x0010
    for item in windows:
        title = str(item.get("title") or "")
        title_key = unicodedata.normalize("NFKC", title).casefold()
        if "和另外" in title_key or " other " in title_key or " other pages" in title_key:
            closed.append(
                {
                    "handle": item.get("handle"),
                    "title": item.get("title"),
                    "post_message_sent": False,
                    "skipped": True,
                    "skip_reason": "multi_tab_browser_window",
                }
            )
            continue
        handle = item.get("handle")
        try:
            hwnd = int(handle)
        except Exception:
            continue
        if hwnd <= 0:
            continue
        posted = bool(user32.PostMessageW(hwnd, wm_close, 0, 0))
        closed.append({"handle": hwnd, "title": item.get("title"), "post_message_sent": posted})
    return closed


def _observe_and_extract_cards(base_url: str, app_name: str, timeout: float) -> tuple[dict[str, Any], dict[str, Any]]:
    observation = _observe(
        base_url,
        app_name=app_name,
        state_hint="SEEK search results list",
        timeout=timeout,
    )
    cards = extract_seek_job_cards(observation, goal="find visible SEEK job cards")
    return observation, cards


def _select_job(state: dict[str, Any], job_index: int) -> dict[str, Any]:
    payload = state.get("cards_payload") if isinstance(state.get("cards_payload"), dict) else {}
    jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
    if not jobs:
        raise SeekTraversalError("no extracted SEEK job cards in state; run extract_cards first")
    if job_index < 0 or job_index >= len(jobs):
        raise SeekTraversalError(f"job_index {job_index} out of range for {len(jobs)} visible jobs")
    job = jobs[job_index]
    if not isinstance(job, dict):
        raise SeekTraversalError(f"selected job is not an object: index={job_index}")
    return job


def _observe_detail(base_url: str, app_name: str, timeout: float) -> tuple[dict[str, Any], dict[str, Any]]:
    observation = _observe(
        base_url,
        app_name=app_name,
        state_hint="SEEK opened job detail pane",
        timeout=timeout,
    )
    detail = extract_seek_job_detail(observation, goal="read the opened SEEK job detail")
    detail["trace_paths"] = [path for path in [observation.get("trace_path")] if path]
    return observation, detail


def _detail_container_bbox(detail: dict[str, Any]) -> dict[str, int] | None:
    container = detail.get("detail_container") if isinstance(detail.get("detail_container"), dict) else {}
    bbox = container.get("bbox") if isinstance(container.get("bbox"), dict) else None
    return _roi_bbox_payload(bbox)


def _learned_detail_container_bbox(base_url: str, timeout: float) -> dict[str, int] | None:
    runtime = _runtime_state(base_url, timeout)["payload"]
    size = _rect_size(runtime)
    if not size:
        return None
    containers = discover_seek_scroll_containers(window_size=size, app_name="seek")
    target = get_scroll_container(containers, SEEK_JOB_DETAIL)
    bbox = target.get("bbox") if isinstance(target, dict) else None
    return _roi_bbox_payload(bbox)


def _visible_cards_fingerprint(
    observation: dict[str, Any],
    *,
    exclude_detail_bbox: dict[str, int] | None = None,
) -> dict[str, Any]:
    cards = extract_seek_job_cards(observation, goal="fingerprint visible SEEK results list")
    jobs = cards.get("jobs") if isinstance(cards.get("jobs"), list) else []
    parts: list[str] = []
    display_parts: list[str] = []
    seen_parts: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if not _job_card_is_left_of_detail(job, exclude_detail_bbox):
            continue
        stable_key = _visible_card_stability_key(job)
        if not stable_key or stable_key in seen_parts:
            continue
        seen_parts.add(stable_key)
        parts.append(stable_key)
        display_parts.append(
            "|".join(str(job.get(key) or "").strip().casefold() for key in ("title", "company", "location"))
        )
    return {
        "jobs_seen": len(parts),
        "fingerprint": "||".join(parts),
        "job_keys": parts,
        "display_job_keys": display_parts,
    }


def _job_card_is_left_of_detail(job: dict[str, Any], detail_bbox: dict[str, int] | None) -> bool:
    if not detail_bbox:
        return True
    bbox = job.get("card_bbox") if isinstance(job.get("card_bbox"), dict) else None
    if not bbox:
        return True
    card_x = int(bbox.get("x") or 0)
    card_w = int(bbox.get("w") or bbox.get("width") or 0)
    detail_x = int(detail_bbox.get("x") or 0)
    if card_w <= 0 or detail_x <= 0:
        return True
    card_center_x = card_x + card_w / 2
    return card_center_x < detail_x - 24


def _visible_card_stability_key(job: dict[str, Any]) -> str:
    title_key = _compact_stability_text(job.get("title"))
    if not title_key:
        return ""
    bbox = job.get("card_bbox") if isinstance(job.get("card_bbox"), dict) else {}
    try:
        y_bucket = int(int(bbox.get("y") or 0) / 50)
    except (TypeError, ValueError):
        y_bucket = 0
    return f"{title_key}@y{y_bucket}"


def _compact_stability_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in normalized if ch.isalnum())


def _normalized_line_hash(text: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip().casefold()
    normalized = " ".join(normalized.split())
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def _detail_visible_line_hashes(detail: dict[str, Any]) -> list[str]:
    if not isinstance(detail, dict):
        return []
    lines: list[str] = []
    for key in ("title", "company", "location", "work_type", "classification", "salary_text"):
        value = detail.get(key)
        if value:
            lines.append(str(value))
    for key in ("requirements", "responsibilities", "benefits"):
        values = detail.get(key)
        if isinstance(values, list):
            lines.extend(str(item) for item in values if str(item).strip())
    sections = detail.get("description_sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            for key in ("heading", "title", "body", "text", "content"):
                value = section.get(key)
                if isinstance(value, list):
                    lines.extend(str(item) for item in value if str(item).strip())
                elif value:
                    lines.append(str(value))
    seen: set[str] = set()
    hashes: list[str] = []
    for line in lines:
        line_hash = _normalized_line_hash(line)
        if line_hash and line_hash not in seen:
            seen.add(line_hash)
            hashes.append(line_hash)
    return hashes


def _previous_no_progress_count(previous_scrolls: list[dict[str, Any]] | None) -> int:
    if not isinstance(previous_scrolls, list) or not previous_scrolls:
        return 0
    last = previous_scrolls[-1]
    validation = last.get("validation") if isinstance(last, dict) else None
    if not isinstance(validation, dict):
        return 0
    try:
        return max(0, int(validation.get("no_progress_count") or 0))
    except (TypeError, ValueError):
        return 0


def _scroll_progress_recommendation(
    *,
    progress: bool,
    no_progress_count: int,
    left_results_stable: bool | None,
    wrong_scope: bool,
    scroll_effect_status: str | None,
    current_wheel_clicks: int,
    new_unique_line_hashes: int,
) -> dict[str, Any]:
    if wrong_scope or left_results_stable is False:
        return {
            "stop_reason": "wrong_scope_scroll_results_list_changed",
            "next_recommendation": "abort_and_recapture",
            "next_allowed_steps": ["capture", "abort"],
            "next_wheel_clicks": current_wheel_clicks,
        }
    if no_progress_count >= 2:
        return {
            "stop_reason": "right_detail_no_progress_after_scroll",
            "next_recommendation": "match_or_review",
            "next_allowed_steps": ["match", "capture"],
            "next_wheel_clicks": current_wheel_clicks,
        }
    if scroll_effect_status in {"no_effect", "boundary", "at_boundary"} and not progress:
        return {
            "stop_reason": "right_detail_bottom_or_boundary_reached",
            "next_recommendation": "match_or_review",
            "next_allowed_steps": ["match", "capture"],
            "next_wheel_clicks": current_wheel_clicks,
        }
    next_wheel_clicks = current_wheel_clicks
    if progress and new_unique_line_hashes < 2:
        next_wheel_clicks = min(current_wheel_clicks + 4, 14)
    return {
        "stop_reason": None,
        "next_recommendation": "continue_detail_scroll",
        "next_allowed_steps": ["read_detail_scroll", "match"],
        "next_wheel_clicks": next_wheel_clicks,
    }


def _require_apply_entry_context(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    job = state.get("current_job") if isinstance(state.get("current_job"), dict) else None
    detail = state.get("detail") if isinstance(state.get("detail"), dict) else None
    decision = state.get("match_decision") if isinstance(state.get("match_decision"), dict) else None
    missing = [
        name
        for name, value in [
            ("current_job", job),
            ("detail", detail),
            ("match_decision", decision),
        ]
        if not value
    ]
    if missing:
        raise SeekTraversalError(f"apply entry requires completed match context: missing {', '.join(missing)}")
    return job, detail, decision


def _application_context_from_artifact(artifact: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    if not isinstance(artifact, dict):
        return None
    job_payload = artifact.get("job") if isinstance(artifact.get("job"), dict) else {}
    source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
    source_record = _artifact_source_record(source)
    source_record_job = source_record.get("job") if isinstance(source_record.get("job"), dict) else {}
    filled_content = source_record.get("filled_content") if isinstance(source_record.get("filled_content"), dict) else {}
    source_cover_letter = str(filled_content.get("cover_letter") or "")
    title = job_payload.get("title") or source.get("job_title")
    company = job_payload.get("company") or source.get("company") or source_record_job.get("company")
    job_id = job_payload.get("job_id") or source.get("job_id")
    apply_url = job_payload.get("apply_url") or source_record.get("apply_url") or source_record_job.get("application_url")
    if not (title or job_id or apply_url):
        return None
    job_theme_evidence = _artifact_job_theme_evidence(source_cover_letter)
    positive_evidence = [source_cover_letter] if source_cover_letter else []
    job = {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": source_record_job.get("location"),
        "application_url": apply_url,
        "source": "seek_application_flow_artifact_v1",
    }
    detail = {
        "contract_version": "seek_job_detail_v1",
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": source_record_job.get("location"),
        "application_url": apply_url,
        "requirements": job_theme_evidence,
        "responsibilities": job_theme_evidence,
        "evidence": {
            "texts": job_theme_evidence,
            "source_record_path": source.get("application_fill_record_path") or source.get("record_path"),
        },
        "source": "seek_application_flow_artifact_v1",
    }
    decision = {
        "contract_version": "seek_match_decision_v1",
        "decision": "strong_apply",
        "recommended_next_action": "continue_application_flow",
        "job_id": job_id,
        "source": "seek_application_flow_artifact_v1",
        "artifact_context_only": True,
        "final_submit_authorized": False,
        "positive_evidence": positive_evidence,
    }
    return job, detail, decision


def _artifact_job_theme_evidence(cover_letter: str) -> list[str]:
    text = " ".join(str(cover_letter or "").split())
    if not text:
        return []
    snippets: list[str] = []
    skip_prefixes = (
        "dear ",
        "kind regards",
        "my relevant background",
        "i can bring",
        "i would welcome",
    )
    useful_terms = {
        "agile",
        "business requirements",
        "code",
        "collaboration",
        "customer",
        "innovation",
        "libraries",
        "modular",
        "solutions",
        "stakeholders",
        "techniques",
    }
    for raw in re.split(r"[.;]+", text):
        snippet = " ".join(raw.split()).strip()
        lowered = snippet.casefold()
        if len(snippet) < 24 or lowered.startswith(skip_prefixes):
            continue
        if any(term in lowered for term in useful_terms):
            snippets.append(snippet)
    return snippets[:4]


def _artifact_source_record(source: dict[str, Any]) -> dict[str, Any]:
    path = source.get("application_fill_record_path") or source.get("record_path")
    if not path:
        return {}
    try:
        payload = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _require_application_flow_context(
    state: dict[str, Any],
    *,
    learned_artifact: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        job, detail, decision = _require_apply_entry_context(state)
        if decision.get("artifact_context_only") is True and learned_artifact:
            recovered = _application_context_from_artifact(learned_artifact)
            if recovered is not None:
                job, detail, decision = recovered
                state["current_job"] = job
                state["detail"] = detail
                state["match_decision"] = decision
                return job, detail, decision, {
                    "source": "learned_application_artifact",
                    "recovered": True,
                    "refreshed_stale_state_context": True,
                    "final_submit_authorized": False,
                }
        return job, detail, decision, {"source": "state", "recovered": False}
    except SeekTraversalError as exc:
        recovered = _application_context_from_artifact(learned_artifact)
        if recovered is None:
            raise exc
        job, detail, decision = recovered
        state["current_job"] = job
        state["detail"] = detail
        state["match_decision"] = decision
        return job, detail, decision, {
            "source": "learned_application_artifact",
            "recovered": True,
            "final_submit_authorized": False,
        }


def _application_replay_context(replay_report: dict[str, Any] | None, flow_state: dict[str, Any]) -> dict[str, Any]:
    report = replay_report if isinstance(replay_report, dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    timeline = report.get("timeline") if isinstance(report.get("timeline"), list) else []
    state_type = str(flow_state.get("state_type") or "")
    current_step = str(flow_state.get("current_step") or "")
    transition = _select_application_replay_transition(timeline, state_type=state_type, current_step=current_step)
    return {
        "contract_version": "seek_application_flow_replay_context_v1",
        "replay_report_contract": report.get("contract_version"),
        "replay_status": report.get("status"),
        "can_run_live_strict_replay": summary.get("can_run_live_strict_replay") is True,
        "current_step": current_step or None,
        "state_type": state_type or None,
        "selected_transition": transition,
        "requires_screenshot_before": bool((transition or {}).get("requires_screenshot_before", True)),
        "requires_screenshot_after": bool((transition or {}).get("requires_screenshot_after", True)),
        "requires_safe_fill_focus": bool((transition or {}).get("requires_safe_fill_focus")),
        "requires_post_fill_verification": bool((transition or {}).get("requires_post_fill_verification")),
        "allows_final_submit": bool((transition or {}).get("allows_final_submit")),
        "allows_profile_mutation": bool((transition or {}).get("allows_profile_mutation")),
    }


def _select_application_replay_transition(
    timeline: list[Any],
    *,
    state_type: str,
    current_step: str,
) -> dict[str, Any] | None:
    normalized_step = current_step.casefold()
    normalized_state = state_type.casefold()
    transition_id = None
    if normalized_step == "choose_documents":
        transition_id = "seek_apply:fill_cover_letter"
    elif normalized_step == "answer_employer_questions" or normalized_state == "screening_questions_detected":
        transition_id = "seek_apply:answer_questions"
    elif normalized_step == "update_seek_profile":
        transition_id = "seek_apply:skip_profile_update"
    elif normalized_step == "review_and_submit" or normalized_state in {"review_step_detected", "final_submit_visible"}:
        transition_id = "seek_apply:block_final_submit"
    elif normalized_state in {"cover_letter_field_detected", "application_form_detected", "application_flow_opened"}:
        transition_id = "seek_apply:fill_cover_letter"
    if not transition_id:
        return None
    for item in timeline:
        if isinstance(item, dict) and item.get("transition_id") == transition_id:
            return item
    return None


def _is_answer_questions_transition(transition: dict[str, Any] | None) -> bool:
    item = transition if isinstance(transition, dict) else {}
    return (
        item.get("transition_id") == "seek_apply:answer_questions"
        or item.get("action") == "answer_employer_questions_and_continue"
        or item.get("low_level_action_type") == "answer_employer_questions_and_continue"
    )


def _merge_scrolled_detail(
    *,
    previous_detail: dict[str, Any] | None,
    before_detail: dict[str, Any] | None,
    after_detail: dict[str, Any],
    current_job: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(after_detail)
    authoritative_title = _first_context_header("title", previous_detail, before_detail, current_job)
    authoritative_company = _first_context_header("company", previous_detail, before_detail, current_job)
    after_title = after_detail.get("title") if isinstance(after_detail, dict) else None
    after_company = after_detail.get("company") if isinstance(after_detail, dict) else None
    for key in ("job_id", "title", "company", "location", "work_type", "classification", "salary_text"):
        if key == "job_id" and (
            (authoritative_title and after_title and not _same_compact_header(authoritative_title, after_title))
            or (authoritative_company and after_company and not _same_compact_header(authoritative_company, after_company))
        ):
            merged[key] = None
        if key == "title" and authoritative_title and merged.get(key) and not _same_compact_header(authoritative_title, merged.get(key)):
            merged[key] = None
        if key == "company" and authoritative_company and merged.get(key) and not _same_compact_header(authoritative_company, merged.get(key)):
            merged[key] = None
        if merged.get(key) and not _usable_scrolled_detail_header_value(key, merged.get(key)):
            merged[key] = None
        if merged.get(key):
            continue
        fallback_sources = (
            (current_job, previous_detail, before_detail)
            if key in {"job_id", "title", "company"}
            else (before_detail, previous_detail, current_job)
        )
        for source in fallback_sources:
            if isinstance(source, dict) and _usable_scrolled_detail_header_value(key, source.get(key)):
                merged[key] = source[key]
                break

    for key in ("requirements", "responsibilities", "benefits"):
        merged[key] = _merge_unique_texts(
            *((source or {}).get(key) for source in (before_detail, previous_detail, after_detail) if isinstance(source, dict))
        )

    merged["description_sections"] = _merge_description_sections(
        *((source or {}).get("description_sections") for source in (before_detail, previous_detail, after_detail) if isinstance(source, dict))
    )
    merged["trace_paths"] = _merge_unique_texts(
        *((source or {}).get("trace_paths") for source in (before_detail, previous_detail, after_detail) if isinstance(source, dict))
    )
    return merged


def _merge_verified_detail(
    *,
    previous_detail: dict[str, Any] | None,
    after_detail: dict[str, Any],
    current_job: dict[str, Any] | None,
) -> dict[str, Any]:
    if not _uses_precise_detail_drawer(after_detail):
        return _merge_scrolled_detail(
            previous_detail=previous_detail,
            before_detail=previous_detail,
            after_detail=after_detail,
            current_job=current_job,
        )
    merged = dict(after_detail)
    for key in ("job_id", "title", "company", "location", "work_type", "classification", "salary_text"):
        if merged.get(key) and _usable_scrolled_detail_header_value(key, merged.get(key)):
            continue
        for source in (previous_detail, current_job):
            if isinstance(source, dict) and _usable_scrolled_detail_header_value(key, source.get(key)):
                merged[key] = source[key]
                break
    return merged


def _compact_detail_for_state(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(detail, dict):
        return None
    compact = dict(detail)
    compact.pop("evidence", None)
    compact.pop("detail_scroll_history", None)
    if isinstance(compact.get("trace_paths"), list):
        compact["trace_paths"] = compact["trace_paths"][-20:]
    return compact


def _merge_detail_batch_read_into_detail(detail: dict[str, Any], batch: dict[str, Any]) -> dict[str, Any]:
    merged = merge_read_batch_into_detail_snapshot(detail, batch, section_role="batch_ocr")
    apply_state = _apply_button_state_from_batch(batch)
    if apply_state and not isinstance(merged.get("apply_button_state"), dict):
        merged["apply_button_state"] = apply_state
    return merged


def _apply_button_state_from_batch(batch: dict[str, Any]) -> dict[str, Any] | None:
    lines = [str(item or "").strip() for item in batch.get("merged_text_lines") or [] if str(item or "").strip()]
    for line in lines:
        compact = re.sub(r"\s+", " ", line).strip()
        lowered = compact.casefold()
        if len(compact) <= 24 and lowered == "quick apply":
            return {"visible": True, "label": "Quick apply", "source": "read_detail_batch_ocr"}
    for line in lines:
        compact = re.sub(r"\s+", " ", line).strip()
        lowered = re.sub(r"[^a-z]+", "", compact.casefold())
        if len(compact) <= 12 and lowered in {"apply", "applyc"}:
            return {"visible": True, "label": "Apply", "source": "read_detail_batch_ocr"}
    return None


def _uses_precise_detail_drawer(detail: dict[str, Any]) -> bool:
    container = detail.get("detail_container") if isinstance(detail.get("detail_container"), dict) else {}
    sources = container.get("sources") if isinstance(container.get("sources"), list) else []
    return "seek_detail_drawer_anchor_bbox" in sources


def _first_context_header(key: str, *sources: dict[str, Any] | None) -> str | None:
    for source in sources:
        if isinstance(source, dict) and _usable_scrolled_detail_header_value(key, source.get(key)):
            return str(source[key])
    return None


def _same_compact_header(expected: Any, actual: Any) -> bool:
    expected_key = _compact_stability_text(expected)
    actual_key = _compact_stability_text(actual)
    return bool(expected_key and actual_key and expected_key == actual_key)


def _usable_scrolled_detail_header_value(key: str, value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = " ".join(text.casefold().split())
    if key == "classification":
        if len(text.split()) > 8 and "(" not in text:
            return False
        if normalized.startswith(
            (
                "we are ",
                "internal ",
                "at least ",
                "excellent ",
                "fxcellent ",
                "understanding of ",
                "solid understanding ",
                "knowledge of ",
                "bachelor",
                "degree",
                "additional certification",
                "certification",
            )
        ):
            return False
        if "professional services" in normalized or "we have managed" in normalized:
            return False
    if key == "work_type":
        if any(place in normalized for place in ("auckland", "wellington", "christchurch", "hamilton", "tauranga", "new zealand")):
            return False
        if len(text.split()) > 5:
            return False
    if key == "company":
        if len(normalized) < 2:
            return False
        if text.lstrip().startswith(("\u00b7", "\u2022", "- ")):
            return False
        if normalized in {"discipline", "goals", "transfer", "requirements", "benefits"}:
            return False
        if normalized.startswith(
            (
                "bachelor",
                "additional certification",
                "datacom is ",
                "we are ",
                "youll ",
                "you ll ",
                "see more",
                "seemore",
            )
        ):
            return False
    if key == "title":
        if normalized.startswith(("what can i earn as ", "what can i earn as a ")):
            return False
        if "salary information" in normalized:
            return False
    if key == "location":
        if "//" in text or "safe nz" in normalized:
            return False
        if normalized in {"westpacnz", "company profile", "banking credit"}:
            return False
        if normalized.startswith(("datacom is ", "spaces ", "spaces,", "we operate ", "we want ", "youll ", "you ll ")):
            return False
        if len(text.split()) > 8:
            return False
    return True


def _merge_unique_texts(*collections: Any) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()
    for collection in collections:
        if not isinstance(collection, list):
            continue
        for item in collection:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else str(item)
            if not key or key in seen:
                continue
            seen.add(key)
            values.append(item)
    return values


def _merge_description_sections(*collections: Any) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for collection in collections:
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            entry = dict(item)
            entry["index"] = len(sections)
            sections.append(entry)
    trimmed_texts = _trim_seek_detail_texts([str(item.get("text") or "") for item in sections])
    if len(trimmed_texts) == len(sections):
        return sections
    trimmed_sections = sections[: len(trimmed_texts)]
    for index, item in enumerate(trimmed_sections):
        item["index"] = index
    return trimmed_sections


def _left_results_crop_bbox(detail: dict[str, Any], image_width: int, image_height: int) -> dict[str, int] | None:
    container = detail.get("detail_container") if isinstance(detail.get("detail_container"), dict) else {}
    bbox = container.get("bbox") if isinstance(container.get("bbox"), dict) else None
    if not isinstance(bbox, dict):
        return None
    try:
        detail_x = int(bbox["x"])
        detail_y = int(bbox.get("y") or 0)
    except Exception:
        return None
    right = max(1, min(image_width, detail_x - 20))
    left = max(0, min(right - 1, detail_x - 760))
    top = max(0, min(image_height - 1, detail_y - 10))
    bottom = image_height
    width = right - left
    height = bottom - top
    if width < 160 or height < 160:
        return None
    return {"x": left, "y": top, "width": width, "height": height}


def _left_results_visual_stability(
    before_image_path: str | None,
    after_image_path: str | None,
    before_detail: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract_version": "visual_pane_stability_v1",
        "pane": "seek:results_list",
        "before_image": before_image_path,
        "after_image": after_image_path,
        "stable": None,
    }
    if not before_image_path or not after_image_path:
        result["error"] = "missing_observation_image"
        return result
    before_path = Path(before_image_path)
    after_path = Path(after_image_path)
    if not before_path.exists() or not after_path.exists():
        result["error"] = "observation_image_not_found"
        return result
    with Image.open(before_path) as before_img, Image.open(after_path) as after_img:
        if before_img.size != after_img.size:
            result["error"] = "image_size_changed"
            result["before_size"] = list(before_img.size)
            result["after_size"] = list(after_img.size)
            return result
        bbox = _left_results_crop_bbox(before_detail, before_img.width, before_img.height)
        if not bbox:
            result["error"] = "left_results_crop_unavailable"
            return result
        box = (bbox["x"], bbox["y"], bbox["x"] + bbox["width"], bbox["y"] + bbox["height"])
        before_crop = before_img.convert("RGB").crop(box)
        after_crop = after_img.convert("RGB").crop(box)
        diff = ImageChops.difference(before_crop, after_crop).convert("L")
        histogram = diff.histogram()
    total = max(1, sum(histogram))
    changed = sum(histogram[13:])
    mean_delta = sum(value * count for value, count in enumerate(histogram)) / total
    changed_ratio = changed / total
    stable = changed_ratio <= 0.018 and mean_delta <= 2.8
    result.update(
        {
            "crop_bbox": bbox,
            "changed_pixel_ratio": round(changed_ratio, 6),
            "mean_abs_delta": round(mean_delta, 4),
            "stable": stable,
            "thresholds": {"changed_pixel_ratio_max": 0.018, "mean_abs_delta_max": 2.8},
        }
    )
    return result


def _one_detail_scroll(
    base_url: str,
    *,
    app_name: str,
    timeout: float,
    learned_artifact: dict[str, Any] | None,
    wheel_clicks: int,
    previous_scrolls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    before_observation, before_detail = _observe_detail(base_url, app_name, timeout)
    before_observation_image = _image_path(before_observation)
    before_fp = _detail_observation_fingerprint(before_detail)
    before_line_hashes = _detail_visible_line_hashes(before_detail)
    repeated_observations = _previous_no_progress_count(previous_scrolls)
    learned_scroll = scroll_target_for_action(
        learned_artifact,
        "read_detail",
        default_pane="job_detail",
        default_container_id="seek:job_detail",
    )
    request = {
        "contract_version": "scroll_request_v2",
        "scroll_scope": "container",
        "target_pane": learned_scroll["target_pane"],
        "target_container_id": learned_scroll["target_container_id"],
        "container_bbox": _detail_container_bbox(before_detail),
        "direction": "down",
        "wheel_clicks": _adaptive_wheel_clicks(base=wheel_clicks, repeated_observations=repeated_observations, maximum=14),
        "reason": "seek_debug_read_detail_one_scroll",
        "missing_evidence": ["debug_step_more_detail_text_may_be_below_fold"],
        "expected_effect": {
            "target_container_content_should_change": True,
            "same_semantic_page_should_remain": True,
            "non_target_panes_should_remain_mostly_stable": True,
        },
        "scroll_history": list(previous_scrolls or []),
        "dry_run": False,
        "enable_verification": True,
    }
    scroll_response = _post_json(base_url, "/action/scroll", request, timeout)
    scroll_result = _result_payload(scroll_response)
    after_observation, after_detail = _observe_detail(base_url, app_name, timeout)
    after_observation_image = _image_path(after_observation)
    after_fp = _detail_observation_fingerprint(after_detail)
    after_line_hashes = _detail_visible_line_hashes(after_detail)
    before_line_hash_set = set(before_line_hashes)
    new_line_hashes = [item for item in after_line_hashes if item not in before_line_hash_set]
    before_detail_bbox = _detail_container_bbox(before_detail)
    after_detail_bbox = _detail_container_bbox(after_detail) or before_detail_bbox
    before_cards = _visible_cards_fingerprint(before_observation, exclude_detail_bbox=before_detail_bbox)
    after_cards = _visible_cards_fingerprint(after_observation, exclude_detail_bbox=after_detail_bbox)
    visual_left = _left_results_visual_stability(before_observation_image, after_observation_image, before_detail)
    left_stable = visual_left.get("stable") if isinstance(visual_left.get("stable"), bool) else None
    if before_cards["fingerprint"] or after_cards["fingerprint"]:
        semantic_left_stable = before_cards["fingerprint"] == after_cards["fingerprint"]
    else:
        semantic_left_stable = None
    effect = scroll_result.get("scroll_effect_validation") if isinstance(scroll_result, dict) else {}
    right_detail_changed = bool(after_fp and before_fp != after_fp)
    line_progress = len(new_line_hashes) >= 2
    progress = bool(right_detail_changed or line_progress)
    no_progress_count = 0 if progress else repeated_observations + 1
    target_container_id = scroll_result.get("target_container_id") or request["target_container_id"]
    left_results_stable = (
        left_stable
        if left_stable is not None
        else (semantic_left_stable if semantic_left_stable is not None else (effect or {}).get("non_target_panes_stable"))
    )
    scroll_scope_invariant = build_scroll_scope_invariant(
        target_container_id=target_container_id,
        target_changed=progress,
        non_target_changes=[
            {
                "container_id": "seek:results_list",
                "changed": left_results_stable is False,
                "semantic_stable": semantic_left_stable,
                "visual_stable": left_stable,
            }
        ],
    )
    wrong_scope = target_container_id != "seek:job_detail" or scroll_scope_invariant.get("wrong_scope_detected") is True
    recommendation = _scroll_progress_recommendation(
        progress=progress,
        no_progress_count=no_progress_count,
        left_results_stable=left_results_stable if isinstance(left_results_stable, bool) else None,
        wrong_scope=wrong_scope,
        scroll_effect_status=(effect or {}).get("status"),
        current_wheel_clicks=int(request["wheel_clicks"]),
        new_unique_line_hashes=len(new_line_hashes),
    )
    validation = {
        "contract_version": "right_detail_scroll_validation_v1",
        "target_container_id": target_container_id,
        "target_pane": scroll_result.get("target_pane") or request["target_pane"],
        "right_detail_changed": progress,
        "detail_fingerprint_changed": right_detail_changed,
        "left_results_stable": left_results_stable,
        "left_results_before": before_cards,
        "left_results_after": after_cards,
        "left_results_semantic_stable": semantic_left_stable,
        "left_results_visual_stability": visual_left,
        "before_detail_fingerprint": before_fp,
        "after_detail_fingerprint": after_fp,
        "before_visible_line_hashes": before_line_hashes,
        "after_visible_line_hashes": after_line_hashes,
        "new_unique_line_hashes": new_line_hashes,
        "new_unique_line_count": len(new_line_hashes),
        "no_progress_count": no_progress_count,
        "wrong_scope": wrong_scope,
        "scroll_scope_invariant": scroll_scope_invariant,
        "scroll_success": scroll_response.get("success") is True,
        "scroll_effect_validation": effect,
        "next_recommendation": recommendation["next_recommendation"],
        "next_allowed_steps": recommendation["next_allowed_steps"],
        "next_wheel_clicks": recommendation["next_wheel_clicks"],
    }
    if recommendation["stop_reason"]:
        validation["adaptive_stop_reason"] = recommendation["stop_reason"]
    elif validation["right_detail_changed"] is False and no_progress_count > 0:
        validation["adaptive_stop_reason"] = "right_detail_content_unchanged_after_scroll"
    return {
        "before_observation": before_observation,
        "before_detail": before_detail,
        "scroll_request": request,
        "scroll_response": scroll_response,
        "after_observation": after_observation,
        "after_detail": after_detail,
        "validation": validation,
    }


def _ocr_region(base_url: str, *, roi: dict[str, Any], timeout: float) -> dict[str, Any]:
    response = _post_json(
        base_url,
        "/vision/ocr_region",
        {"roi": roi},
        timeout,
    )
    if response.get("success") is not True:
        raise SeekTraversalError(f"ocr_region failed: {response.get('error') or response.get('message')}")
    result = _result_payload(response)
    ocr_result = result.get("ocr_result") if isinstance(result, dict) else {}
    metadata = ocr_result.get("metadata") if isinstance(ocr_result, dict) and isinstance(ocr_result.get("metadata"), dict) else {}
    return {
        "response": response,
        "result": result,
        "ocr_result": ocr_result,
        "image_path": ocr_result.get("image_path") if isinstance(ocr_result, dict) else None,
        "trace_path": result.get("trace_path") if isinstance(result, dict) else response.get("trace_path"),
        "roi": metadata.get("roi") or roi,
    }


def _read_detail_batch(
    base_url: str,
    *,
    timeout: float,
    detail: dict[str, Any],
    learned_artifact: dict[str, Any] | None,
    wheel_clicks: int,
    max_captures: int,
    stop_after_no_new_content: int,
) -> dict[str, Any]:
    bbox = _detail_container_bbox(detail) or _learned_detail_container_bbox(base_url, timeout)
    if not bbox:
        raise SeekTraversalError("read_detail_batch requires detail_container bbox or learned seek:job_detail container")
    learned_scroll = scroll_target_for_action(
        learned_artifact,
        "read_detail",
        default_pane="job_detail",
        default_container_id="seek:job_detail",
    )
    captures: list[dict[str, Any]] = []
    wrong_scope_detected = False
    no_new_content_count = 0
    for index in range(max(1, int(max_captures))):
        ocr = _ocr_region(base_url, roi=bbox, timeout=timeout)
        capture_item = {
            "index": index,
            "image_path": ocr.get("image_path"),
            "trace_path": ocr.get("trace_path"),
            "ocr_result": ocr.get("ocr_result"),
        }
        captures.append(capture_item)
        partial = build_read_region_batch_report(
            target_container_id=learned_scroll["target_container_id"],
            target_bbox=bbox,
            captures=captures,
            max_captures=max_captures,
            stop_after_no_new_content=stop_after_no_new_content,
            wrong_scope_detected=wrong_scope_detected,
        )
        if partial.get("stop_reason") in {"no_new_content", "wrong_scope_detected"}:
            break
        if index >= max_captures - 1:
            break
        last_capture = partial.get("captures", [])[-1] if partial.get("captures") else {}
        if int(last_capture.get("new_unique_line_count") or 0) == 0:
            no_new_content_count += 1
        else:
            no_new_content_count = 0
        request = {
            "contract_version": "scroll_request_v2",
            "scroll_scope": "container",
            "target_pane": learned_scroll["target_pane"],
            "target_container_id": learned_scroll["target_container_id"],
            "container_bbox": bbox,
            "direction": "down",
            "wheel_clicks": _adaptive_wheel_clicks(base=wheel_clicks, repeated_observations=no_new_content_count, maximum=20),
            "reason": "seek_debug_read_detail_batch",
            "missing_evidence": ["batch_read_needs_more_detail_text"],
            "expected_effect": {
                "target_container_content_should_change": True,
                "same_semantic_page_should_remain": True,
                "non_target_panes_should_remain_mostly_stable": True,
            },
            "dry_run": False,
            "enable_verification": True,
        }
        scroll_response = _post_json(base_url, "/action/scroll", request, timeout)
        scroll_result = _result_payload(scroll_response)
        if scroll_result.get("target_container_id") and scroll_result.get("target_container_id") != "seek:job_detail":
            wrong_scope_detected = True
        effect = scroll_result.get("scroll_effect_validation") if isinstance(scroll_result.get("scroll_effect_validation"), dict) else {}
        capture_item["scroll_trace_path"] = _result_payload(scroll_response).get("trace_path")
        capture_item["scroll_wheel_clicks"] = request["wheel_clicks"]
        capture_item["scroll_effect_status"] = effect.get("status")
        capture_item["scroll_response"] = _compact_action_response(scroll_response)
        if effect.get("status") == "bottom_reached":
            break
    return build_read_region_batch_report(
        target_container_id=learned_scroll["target_container_id"],
        target_bbox=bbox,
        captures=captures,
        max_captures=max_captures,
        stop_after_no_new_content=stop_after_no_new_content,
        wrong_scope_detected=wrong_scope_detected,
    )


def _observe_final_review_until_submit_visible(
    base_url: str,
    *,
    app_name: str,
    timeout: float,
    fill_record: dict[str, Any],
    max_scrolls: int = 3,
) -> dict[str, Any]:
    window_size = None
    try:
        window_size = _rect_size(_runtime_state(base_url, timeout)["payload"])
    except Exception:
        window_size = None
    attempts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []

    def observe_once(label: str) -> dict[str, Any]:
        before = _capture(base_url, timeout)
        observation = _observe(
            base_url,
            app_name=app_name,
            state_hint=(
                "SEEK application Review and submit page; extract visible resume, cover letter, employer answers, "
                "and Submit application blocker without clicking final submit"
            ),
            timeout=timeout,
        )
        observations.append(observation)
        flow_state = assess_seek_application_flow_state(observation)
        extraction = build_seek_final_review_extraction(
            fill_record,
            observation=observation,
            flow_state=flow_state,
            screenshot_path=before["image_path"],
        )
        attempts.append(
            {
                "label": label,
                "image_path": before.get("image_path"),
                "observe_image": _image_path(observation),
                "observe_trace": observation.get("trace_path"),
                "current_step": flow_state.get("current_step"),
                "submit_application_visible": extraction.get("submit_application_visible"),
                "status": extraction.get("status"),
                "review_missing": (extraction.get("review_reconciliation") or {}).get("missing"),
            }
        )
        return {
            "before": before,
            "observation": observation,
            "flow_state": flow_state,
            "extraction": extraction,
        }

    latest = observe_once("initial")
    for index in range(max(0, int(max_scrolls))):
        if latest["extraction"].get("submit_application_visible") is True:
            break
        scroll_response = _post_json(
            base_url,
            "/action/scroll",
            {
                "contract_version": "scroll_request_v2",
                "scroll_scope": "window",
                "direction": "down",
                "wheel_clicks": _adaptive_wheel_clicks(base=8, repeated_observations=index, maximum=14),
                "x": int((window_size or {}).get("width") or 1600) // 2,
                "y": max(420, int(((window_size or {}).get("height") or 1100) * 0.78)),
                "reason": "seek_final_review_read_until_submit_visible",
                "missing_evidence": ["submit_application_button_may_be_below_fold"],
                "expected_effect": {
                    "same_semantic_page_should_remain": True,
                    "submit_application_should_become_visible": True,
                },
                "dry_run": False,
                "enable_verification": True,
            },
            timeout,
        )
        attempts[-1]["scroll_after_attempt"] = _compact_action_response(scroll_response)
        time.sleep(0.25)
        latest = observe_once(f"after_scroll_{index + 1}")
    if latest["extraction"].get("submit_application_visible") is True and _review_missing_core_evidence(latest["extraction"]):
        for index in range(2):
            scroll_response = _post_json(
                base_url,
                "/action/scroll",
                {
                    "contract_version": "scroll_request_v2",
                    "scroll_scope": "window",
                    "direction": "up",
                    "wheel_clicks": _adaptive_wheel_clicks(base=9, repeated_observations=index, maximum=14),
                    "x": int((window_size or {}).get("width") or 1600) // 2,
                    "y": max(420, int(((window_size or {}).get("height") or 1100) * 0.55)),
                    "reason": "seek_final_review_read_top_sections_for_resume_cover_letter",
                    "missing_evidence": ["resume_or_cover_letter_review_summary_above_current_view"],
                    "expected_effect": {
                        "same_semantic_page_should_remain": True,
                        "resume_or_cover_letter_summary_should_become_visible": True,
                    },
                    "dry_run": False,
                    "enable_verification": True,
                },
                timeout,
            )
            attempts[-1]["scroll_up_after_attempt"] = _compact_action_response(scroll_response)
            time.sleep(0.25)
            latest = observe_once(f"after_scroll_up_{index + 1}")
            if not _review_missing_core_evidence(latest["extraction"]):
                break
    if len(observations) > 1:
        merged_observation = _merge_review_observations(observations)
        merged_flow_state = assess_seek_application_flow_state(merged_observation)
        latest["observation"] = merged_observation
        latest["flow_state"] = merged_flow_state
        latest["extraction"] = build_seek_final_review_extraction(
            fill_record,
            observation=merged_observation,
            flow_state=merged_flow_state,
            screenshot_path=latest["before"]["image_path"],
        )
        attempts.append(
            {
                "label": "merged_review_observations",
                "source_observation_count": len(observations),
                "submit_application_visible": latest["extraction"].get("submit_application_visible"),
                "status": latest["extraction"].get("status"),
                "review_missing": (latest["extraction"].get("review_reconciliation") or {}).get("missing"),
            }
        )
    latest["review_read_attempts"] = attempts
    return latest


def _review_missing_core_evidence(extraction: dict[str, Any]) -> bool:
    reconciliation = extraction.get("review_reconciliation") if isinstance(extraction.get("review_reconciliation"), dict) else {}
    missing = {str(item) for item in reconciliation.get("missing") or []}
    return bool({"resume", "cover_letter"} & missing)


def _merge_review_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    merged_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in observations:
        for item in _collect_visible_items(observation):
            text = " ".join(str(item.get("text") or item.get("label") or "").split())
            if not text:
                continue
            bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else None
            key = json.dumps({"text": text.casefold(), "bbox": bbox}, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            merged_items.append(
                {
                    "id": item.get("id") or f"merged_review_text_{len(merged_items)}",
                    "text": text,
                    "label": text,
                    "role": item.get("role") or "text",
                    "bbox": bbox,
                    "source": item.get("source") or item.get("collection") or "merged_review_observation",
                }
            )
    latest = observations[-1] if observations else {}
    merged = dict(latest)
    merged["contract_version"] = latest.get("contract_version") or "screen_observation_v1"
    merged["screen_inventory"] = {
        "contract_version": "screen_inventory_v1",
        "page_elements": merged_items,
        "available_actions": [],
        "cards": [],
    }
    merged["merged_review_observation"] = {
        "contract_version": "merged_review_observation_v1",
        "source_observation_count": len(observations),
        "visible_text_count": len(merged_items),
    }
    return merged


def _write_step_report(
    *,
    run_dir: Path,
    state: dict[str, Any],
    step_name: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    step_index = int(state.get("step_index") or 0) + 1
    directory = _step_dir(run_dir, step_index, step_name)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract_version": REPORT_CONTRACT,
        "step_index": step_index,
        "step_name": step_name,
        "created_at": _utcish_now(),
        "run_dir": str(run_dir),
        **report,
    }
    report_path = directory / "step_report.json"
    _write_json(report_path, payload)
    state["step_index"] = step_index
    state["phase"] = step_name
    state.setdefault("steps", []).append(
        {
            "step_index": step_index,
            "step_name": step_name,
            "report_path": str(report_path),
            "before_image": payload.get("before_image"),
            "after_image": payload.get("after_image"),
            "status": payload.get("status"),
        }
    )
    payload["report_path"] = str(report_path)
    return payload


def _write_current_job_archive(run_dir: Path, state: dict[str, Any], step_payload: dict[str, Any]) -> str | None:
    if step_payload.get("step_name") not in {
        "dry_run_card",
        "execute_card",
        "verify_detail",
        "read_detail_scroll",
        "read_detail_batch",
        "match",
        "dry_run_apply_entry",
        "execute_apply_entry",
    }:
        return None
    card = _first_dict(step_payload.get("job"), step_payload.get("card"), state.get("current_job"))
    detail = _first_dict(
        step_payload.get("detail"),
        step_payload.get("merged_detail"),
        state.get("detail"),
    )
    match_decision = _first_dict(step_payload.get("match_decision"), state.get("match_decision"))
    apply_entry = _first_dict(step_payload.get("apply_entry"), state.get("apply_entry_attempt"))
    if not card and not detail and not match_decision and not apply_entry:
        return None

    existing = state.get("current_job_archive") if isinstance(state.get("current_job_archive"), dict) else {}
    existing_path = state.get("current_job_archive_path") or existing.get("path")
    if existing_path:
        try:
            existing_from_file = _read_json(existing_path)
        except (OSError, ValueError, json.JSONDecodeError):
            existing_from_file = None
        if isinstance(existing_from_file, dict):
            existing = existing_from_file
    existing_steps = existing.get("debug_steps") if isinstance(existing.get("debug_steps"), list) else []
    archive = {
        "contract_version": JOB_ARCHIVE_CONTRACT,
        "source": "seek_debug_step_runner",
        "run_dir": str(run_dir),
        "job_id": detail.get("job_id") or card.get("job_id") or existing.get("job_id"),
        "title": detail.get("title") or card.get("title") or existing.get("title"),
        "company": detail.get("company") or card.get("company") or existing.get("company"),
        "location": detail.get("location") or card.get("location") or existing.get("location"),
        "card": card or existing.get("card"),
        "card_click": _first_dict(
            step_payload.get("action"),
            existing.get("card_click"),
        ),
        "detail_read": {
            "detail": _compact_detail_for_state(detail) or _compact_detail_for_state(_first_dict(existing.get("detail_read")).get("detail")),
            "scrolls": state.get("detail_scrolls") if isinstance(state.get("detail_scrolls"), list) else _first_dict(existing.get("detail_read")).get("scrolls", []),
        },
        "match_decision": match_decision or existing.get("match_decision"),
        "apply_entry": _trace_apply_entry_summary(apply_entry) if apply_entry else existing.get("apply_entry"),
        "debug_steps": [*existing_steps, _debug_step_archive_entry(step_payload)],
        "safety": {
            "submit_clicks": int((apply_entry or {}).get("submit_clicks") or 0) if apply_entry else 0,
            "final_submission_performed": bool((apply_entry or {}).get("final_submission_performed")) if apply_entry else False,
        },
    }
    archive_dir = run_dir / "job_archives"
    path = Path(existing.get("path") or archive_dir / _job_archive_filename(archive))
    archive["path"] = str(path)
    _write_json(path, archive)
    state["current_job_archive"] = {
        "job_id": archive.get("job_id"),
        "title": archive.get("title"),
        "company": archive.get("company"),
        "location": archive.get("location"),
        "path": str(path),
        "debug_step_count": len(archive.get("debug_steps") or []),
    }
    state["current_job_archive_path"] = str(path)
    state_archives = state.setdefault("job_archives", [])
    if not any(isinstance(item, dict) and item.get("path") == str(path) for item in state_archives):
        state_archives.append(
            {
                "job_id": archive.get("job_id"),
                "title": archive.get("title"),
                "company": archive.get("company"),
                "path": str(path),
            }
        )
    step_payload["job_archive_path"] = str(path)
    return str(path)


def _debug_step_archive_entry(step_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_index": step_payload.get("step_index"),
        "step_name": step_payload.get("step_name"),
        "status": step_payload.get("status"),
        "report_path": step_payload.get("report_path"),
        "before_image": step_payload.get("before_image"),
        "after_image": step_payload.get("after_image"),
        "observe_image": step_payload.get("observe_image"),
        "trace_paths": step_payload.get("trace_paths") or [],
    }


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _job_archive_filename(archive: dict[str, Any]) -> str:
    key_payload = {
        "job_id": archive.get("job_id"),
        "title": archive.get("title"),
        "company": archive.get("company"),
        "location": archive.get("location"),
    }
    digest = hashlib.sha1(json.dumps(key_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    return f"job_debug_{digest}.json"


CONTINUE_ALLOWED_LABELS = {"continue", "save and continue", "save & continue"}
CONTINUE_FORBIDDEN_PROFILE_LABEL_PREFIXES = ("add ", "edit ")
CONTINUE_FORBIDDEN_PROFILE_LABELS = {"more", "save", "cancel"}


def _continue_label_validation(
    point: dict[str, Any],
    *,
    dry_result: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(dry_result, dict):
        return {"allowed": False, "reason": "missing_continue_candidate_evidence"}
    pre_click = dry_result.get("pre_click_decision")
    if not isinstance(pre_click, dict):
        pre_click = (dry_result.get("agent_step_result") or {}).get("pre_click_decision")
    return validate_action_candidate_target_at_point(
        point,
        pre_click_decision=pre_click,
        allowed_labels=CONTINUE_ALLOWED_LABELS,
        forbidden_labels=CONTINUE_FORBIDDEN_PROFILE_LABELS,
        forbidden_label_prefixes=CONTINUE_FORBIDDEN_PROFILE_LABEL_PREFIXES,
    )


def _continue_click_point_validation(
    point: dict[str, Any] | None,
    *,
    window_size: dict[str, int] | None,
    dry_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(point, dict):
        return {"allowed": False, "reason": "missing_selected_click_point"}
    try:
        x = float(point.get("x"))
        y = float(point.get("y"))
    except (TypeError, ValueError):
        return {"allowed": False, "reason": "invalid_selected_click_point", "selected_click_point": point}
    width = int((window_size or {}).get("width") or 0)
    height = int((window_size or {}).get("height") or 0)
    if width > 0 and x >= width * 0.94:
        return {
            "allowed": False,
            "reason": "right_floating_control_region",
            "selected_click_point": {"x": int(round(x)), "y": int(round(y))},
            "coordinate_window_size": window_size,
        }
    if height > 0 and y <= 90:
        return {
            "allowed": False,
            "reason": "browser_or_page_header_region",
            "selected_click_point": {"x": int(round(x)), "y": int(round(y))},
            "coordinate_window_size": window_size,
        }
    if height > 0 and y >= height - 20:
        return {
            "allowed": False,
            "reason": "bottom_edge_partially_visible_region",
            "selected_click_point": {"x": int(round(x)), "y": int(round(y))},
            "coordinate_window_size": window_size,
        }
    label_validation = _continue_label_validation({"x": x, "y": y}, dry_result=dry_result)
    if label_validation.get("allowed") is not True:
        return {
            **label_validation,
            "selected_click_point": {"x": int(round(x)), "y": int(round(y))},
            "coordinate_window_size": window_size,
        }
    return {
        **label_validation,
        "allowed": True,
        "selected_click_point": {"x": int(round(x)), "y": int(round(y))},
        "coordinate_window_size": window_size,
    }


def _safe_continue_after_fill(base_url: str, *, app_name: str, timeout: float, from_step: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract_version": "seek_safe_continue_after_fill_v1",
        "attempted": True,
        "executed": False,
        "from_step": from_step,
        "continue_clicks": 0,
        "submit_clicks": 0,
        "final_submissions": 0,
        "status": "not_started",
    }
    try:
        window_size = _rect_size(_runtime_state(base_url, timeout)["payload"])
    except Exception as exc:
        window_size = None
        result["window_size_error"] = str(exc)
    payload = {
        "agent_mode": "execute",
        "goal": (
            "Click only the visible SEEK application form Continue or Save and continue button to move to the next application step. "
            "The target must be a text button inside the main SEEK application form content, not the browser toolbar, "
            "not any right-edge floating extension/chat/translate widget, and not an icon-only button. "
            "Do not click Review and submit, Submit, Send application, Complete application, or any final submission button. "
            "If the SEEK Continue button is not visible, do not choose another button."
        ),
        "app_name": app_name,
        "state_hint": (
            "SEEK application form after safe cover letter fill/profile review; find the bottom form Continue button "
            "inside the SEEK page, excluding browser chrome and right-edge floating tools; continue to the next non-final step only"
        ),
        "capture_live": True,
        "dry_run": True,
        "enable_post_click_verification": True,
        "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
        "metadata": {
            "seek_application_continue_after_fill": True,
            "forbid_final_submit": True,
            "must_have_visible_text": ["Continue", "Save and continue"],
            "excluded_regions": ["browser_toolbar", "right_edge_floating_widgets", "icon_only_buttons"],
        },
    }
    scroll_attempts = 4 if from_step == "update_seek_profile" else 2
    wheel_clicks = 7 if from_step == "update_seek_profile" else 4
    dry_response: dict[str, Any] = {}
    approved_plan_id = None
    dry_result: dict[str, Any] = {}
    attempt_records: list[dict[str, Any]] = []
    last_validation: dict[str, Any] = {"allowed": False, "reason": "not_attempted"}
    for attempt_index in range(scroll_attempts):
        scroll_response = _post_json(
            base_url,
            "/action/scroll",
            {
                "contract_version": "scroll_request_v2",
                "scroll_scope": "window",
                "direction": "down",
                "wheel_clicks": wheel_clicks,
                "x": int((window_size or {}).get("width") or 1600) // 2,
                "y": max(400, int(((window_size or {}).get("height") or 1100) * 0.76)),
                "reason": "seek_application_continue_button_should_be_fully_visible_before_click",
                "missing_evidence": ["continue_button_fully_visible"],
                "expected_effect": {
                    "same_semantic_page_should_remain": True,
                    "continue_button_should_be_visible": True,
                },
                "dry_run": False,
                "enable_verification": True,
            },
            timeout,
        )
        time.sleep(0.35)
        dry_response = _post_json(base_url, "/action/execute_recognition_plan", payload, timeout)
        dry_result = _result_payload(dry_response)
        approved_plan_id = dry_result.get("approved_plan_id") or (dry_result.get("agent_step_result") or {}).get("approved_plan_id")
        selected_point = dry_result.get("selected_click_point") or (dry_result.get("agent_step_result") or {}).get("selected_click_point")
        last_validation = _continue_click_point_validation(
            selected_point,
            window_size=window_size,
            dry_result=dry_result,
        )
        attempt_records.append(
            {
                "attempt_index": attempt_index,
                "scroll_success": scroll_response.get("success") is True,
                "scroll_trace_path": _result_payload(scroll_response).get("trace_path"),
                "dry_run_success": dry_response.get("success") is True,
                "dry_run_trace_path": _result_payload(dry_response).get("trace_path"),
                "approved_plan_id": approved_plan_id,
                "target_validation": last_validation,
            }
        )
        if dry_response.get("success") is True and approved_plan_id and last_validation.get("allowed") is True:
            break
    result["pre_continue_attempts"] = attempt_records
    result["dry_run_response"] = _compact_action_response(dry_response)
    result["target_validation"] = last_validation
    if dry_response.get("success") is not True or not approved_plan_id:
        result["status"] = "continue_dry_run_not_approved"
        result["stop_reason"] = "continue_dry_run_not_approved"
        return result
    if last_validation.get("allowed") is not True:
        result["status"] = "continue_target_rejected"
        result["stop_reason"] = "continue_target_outside_form_region"
        return result
    execute_response = _post_json(
        base_url,
        "/action/execute_recognition_plan",
        {
            **payload,
            "dry_run": False,
            "approved_plan_id": approved_plan_id,
            "write_policy": {"path_graph": False, "element_memory": True, "trace": True},
        },
        timeout,
    )
    result["execute_response"] = _compact_action_response(execute_response)
    result["executed"] = execute_response.get("success") is True
    result["continue_clicks"] = 1 if result["executed"] else 0
    if execute_response.get("success") is not True:
        result["status"] = "continue_execute_failed"
        result["stop_reason"] = "continue_execute_failed"
        return result
    time.sleep(1.5)
    observation = _observe(
        base_url,
        app_name=app_name,
        state_hint="SEEK application flow after Continue click; classify the current application step and stop before final submit",
        timeout=timeout,
    )
    flow_state = assess_seek_application_flow_state(observation)
    result["post_continue_application_flow_state"] = flow_state
    result["post_continue_trace_path"] = observation.get("trace_path")
    result["final_submit_visible"] = bool((flow_state.get("final_submit_visible_blocker") or {}).get("blocked"))
    if result["final_submit_visible"] or flow_state.get("state_type") == "final_submit_visible":
        result["status"] = "stopped_at_final_submit_visible"
        result["stop_reason"] = "final_submit_visible_stop_before_submission"
    elif from_step and flow_state.get("current_step") == from_step:
        result["status"] = "continue_no_navigation"
        result["stop_reason"] = "continue_click_did_not_change_application_step"
    elif flow_state.get("current_step") == "choose_documents" and flow_state.get("state_type") == "cover_letter_field_detected":
        result["status"] = "continue_no_navigation"
        result["stop_reason"] = "continue_click_did_not_change_application_step"
    else:
        result["status"] = "continued_to_next_step"
        result["stop_reason"] = flow_state.get("stop_reason")
    return result


def _application_flow_ready(flow_state: dict[str, Any] | None) -> bool:
    if not isinstance(flow_state, dict):
        return False
    state_type = str(flow_state.get("state_type") or "")
    current_step = str(flow_state.get("current_step") or "")
    if current_step in {"choose_documents", "answer_employer_questions", "update_seek_profile", "review_and_submit"}:
        return True
    return state_type in {
        "cover_letter_field_detected",
        "screening_questions_detected",
        "risky_application_questions",
        "final_submit_visible",
    }


def _wait_for_application_flow_after_apply(
    base_url: str,
    *,
    app_name: str,
    source_job: dict[str, Any] | None,
    initial_flow_state: dict[str, Any] | None,
    timeout: float,
    max_wait_seconds: float,
    poll_interval_seconds: float = 0.5,
) -> dict[str, Any]:
    started_at = time.monotonic()
    result: dict[str, Any] = {
        "contract_version": "seek_application_flow_wait_v1",
        "max_wait_seconds": max(0.0, float(max_wait_seconds or 0.0)),
        "poll_interval_seconds": max(0.1, float(poll_interval_seconds or 0.5)),
        "poll_count": 0,
        "status": "not_requested",
        "elapsed_seconds": 0.0,
        "application_flow_state": initial_flow_state if isinstance(initial_flow_state, dict) else None,
        "trace_path": (initial_flow_state or {}).get("trace_path") if isinstance(initial_flow_state, dict) else None,
    }
    if _application_flow_ready(initial_flow_state):
        result["status"] = "ready_from_apply_entry"
        return result
    if result["max_wait_seconds"] <= 0:
        return result

    max_polls = max(1, int(result["max_wait_seconds"] / result["poll_interval_seconds"]) + 1)
    observations: list[dict[str, Any]] = []
    for poll_index in range(max_polls):
        if poll_index > 0:
            time.sleep(result["poll_interval_seconds"])
        observation = _observe(
            base_url,
            app_name=app_name,
            state_hint="SEEK application flow after Apply click; classify the current step and stop before final submit",
            timeout=timeout,
        )
        flow_state = assess_seek_application_flow_state(observation, source_job=source_job)
        observations.append(
            {
                "poll_index": poll_index + 1,
                "trace_path": observation.get("trace_path"),
                "image_path": _image_path(observation),
                "state_type": flow_state.get("state_type"),
                "current_step": flow_state.get("current_step"),
                "application_flow_started": flow_state.get("application_flow_started"),
            }
        )
        result["poll_count"] = poll_index + 1
        result["application_flow_state"] = flow_state
        result["trace_path"] = observation.get("trace_path")
        result["image_path"] = _image_path(observation)
        if _application_flow_ready(flow_state):
            result["status"] = "ready_from_poll"
            result["observations"] = observations
            result["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
            return result

    result["status"] = "timeout"
    result["observations"] = observations
    result["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
    return result


def _safe_employer_question_fill_attempt(
    base_url: str,
    *,
    app_name: str,
    answer_preview: dict[str, Any],
    execute_fill: bool,
    timeout: float,
) -> dict[str, Any]:
    previews = [item for item in answer_preview.get("previews") or [] if isinstance(item, dict)]
    result: dict[str, Any] = {
        "contract_version": "safe_employer_question_fill_attempt_v1",
        "enabled": bool(execute_fill),
        "question_count": len(previews),
        "answered_count": 0,
        "already_selected_count": 0,
        "clicks": 0,
        "typed_fields": 0,
        "continue_clicks": 0,
        "submit_clicks": 0,
        "final_submissions": 0,
        "status": "disabled",
        "stop_reason": "employer_question_fill_disabled",
        "action_results": [],
    }
    if not previews:
        result["status"] = "no_questions"
        result["stop_reason"] = "no_employer_questions_to_fill"
        return result
    allowed_previews = [item for item in previews if item.get("runner_decision") == "allow"]
    blocked_previews = [item for item in previews if item.get("runner_decision") != "allow"]
    if answer_preview.get("status") != "ready" and not allowed_previews:
        result["status"] = "blocked_need_user_or_gpt_decision"
        result["stop_reason"] = "employer_question_preview_not_ready"
        result["blocked_questions"] = [_employer_question_action_preview(item) for item in blocked_previews]
        return result
    if not execute_fill:
        result["status"] = "dry_run_ready"
        result["stop_reason"] = (
            "employer_question_partial_fill_requires_explicit_flag"
            if blocked_previews
            else "employer_question_fill_requires_explicit_flag"
        )
        result["action_results"] = [_employer_question_action_preview(item) for item in allowed_previews]
        result["blocked_questions"] = [_employer_question_action_preview(item) for item in blocked_previews]
        return result

    for item in allowed_previews:
        action = _execute_one_employer_question_answer(base_url, app_name=app_name, item=item, timeout=timeout)
        result["action_results"].append(action)
        if action.get("status") == "already_selected":
            result["already_selected_count"] += 1
            result["answered_count"] += 1
            continue
        if action.get("filled") is True:
            result["answered_count"] += 1
            if action.get("action_type") == "click":
                result["clicks"] += 1
            elif action.get("action_type") == "multi_click":
                result["clicks"] += int(action.get("clicks") or 0)
            elif action.get("action_type") == "type_text":
                result["typed_fields"] += 1
            continue
        result["status"] = "blocked_need_user_or_gpt_decision"
        result["stop_reason"] = action.get("stop_reason") or "employer_question_action_failed"
        return result

    result["blocked_questions"] = [_employer_question_action_preview(item) for item in blocked_previews]
    if blocked_previews:
        result["status"] = "partial_until_review"
        result["stop_reason"] = "some_employer_questions_need_review"
    else:
        result["status"] = "filled_until_review"
        result["stop_reason"] = "employer_questions_filled_stop_before_navigation"
    return result


def _employer_question_action_preview(item: dict[str, Any]) -> dict[str, Any]:
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    return {
        "contract_version": "safe_employer_question_action_result_v1",
        "enabled": False,
        "question_id": item.get("question_id"),
        "question_text": item.get("question_text"),
        "planned_answer": item.get("planned_answer"),
        "action_type": target.get("action_type"),
        "filled": False,
        "stop_reason": "preview_only",
    }


def _execute_one_employer_question_answer(
    base_url: str,
    *,
    app_name: str,
    item: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    action_type = str(target.get("action_type") or "")
    result: dict[str, Any] = {
        "contract_version": "safe_employer_question_action_result_v1",
        "enabled": True,
        "question_id": item.get("question_id"),
        "question_text": item.get("question_text"),
        "planned_answer": item.get("planned_answer"),
        "action_type": action_type,
        "filled": False,
        "submit_clicks": 0,
        "final_submissions": 0,
    }
    if item.get("runner_decision") != "allow":
        result["stop_reason"] = item.get("reject_reason") or "question_preview_not_allowed"
        return result
    if action_type == "already_selected":
        result["status"] = "already_selected"
        result["filled"] = True
        result["selected_value_evidence"] = target.get("selected_value_evidence")
        return result
    if action_type == "click":
        return _execute_employer_question_click(base_url, app_name=app_name, item=item, timeout=timeout, result=result)
    if action_type == "multi_click":
        return _execute_employer_question_multi_click(base_url, app_name=app_name, item=item, timeout=timeout, result=result)
    if action_type == "type_text":
        return _execute_employer_question_type_text(base_url, app_name=app_name, item=item, timeout=timeout, result=result)
    result["stop_reason"] = "unsupported_employer_question_action_type"
    return result


def _execute_employer_question_click(
    base_url: str,
    *,
    app_name: str,
    item: dict[str, Any],
    timeout: float,
    result: dict[str, Any],
) -> dict[str, Any]:
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    candidate = target.get("candidate") if isinstance(target.get("candidate"), dict) else {}
    bbox = _candidate_bbox(candidate)
    if not bbox:
        result["stop_reason"] = "missing_click_candidate_bbox"
        return result
    point = _target_click_point(target, bbox)
    result["target_validation"] = _candidate_point_validation(point, bbox)
    if result["target_validation"].get("allowed") is not True:
        result["stop_reason"] = "employer_question_click_point_outside_candidate_bbox"
        return result
    confirmed = _execute_confirmed_candidate_point(
        base_url,
        point=point,
        bbox=bbox,
        label=f"SEEK employer question {item.get('question_id')} {item.get('planned_answer')}",
        source_trace_path=None,
        timeout=timeout,
    )
    result.update(confirmed)
    if result.get("confirmed_execute_response", {}).get("success") is not True:
        result["stop_reason"] = "employer_question_confirmed_click_execute_failed"
        return result
    result["filled"] = True
    result["status"] = "clicked"
    return result


def _execute_employer_question_multi_click(
    base_url: str,
    *,
    app_name: str,
    item: dict[str, Any],
    timeout: float,
    result: dict[str, Any],
) -> dict[str, Any]:
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    targets = [entry for entry in target.get("targets") or [] if isinstance(entry, dict)]
    result["action_results"] = []
    result["clicks"] = 0
    if not targets:
        result["stop_reason"] = "missing_multi_click_targets"
        return result
    for index, entry in enumerate(targets):
        candidate = entry.get("candidate") if isinstance(entry.get("candidate"), dict) else {}
        bbox = _candidate_bbox(candidate)
        if not bbox:
            result["stop_reason"] = "missing_multi_click_candidate_bbox"
            return result
        point = _target_click_point(entry, bbox)
        validation = _candidate_point_validation(point, bbox)
        action_result: dict[str, Any] = {
            "index": index,
            "candidate_id": candidate.get("id"),
            "label": candidate.get("label"),
            "target_validation": validation,
        }
        if validation.get("allowed") is not True:
            action_result["stop_reason"] = "employer_question_multi_click_point_outside_candidate_bbox"
            result["action_results"].append(action_result)
            result["stop_reason"] = action_result["stop_reason"]
            return result
        confirmed = _execute_confirmed_candidate_point(
            base_url,
            point=point,
            bbox=bbox,
            label=f"SEEK employer question {item.get('question_id')} multi option {candidate.get('label')}",
            source_trace_path=None,
            timeout=timeout,
        )
        action_result.update(confirmed)
        result["action_results"].append(action_result)
        if action_result.get("confirmed_execute_response", {}).get("success") is not True:
            result["stop_reason"] = "employer_question_multi_click_execute_failed"
            return result
        result["clicks"] += 1
    result["filled"] = True
    result["status"] = "clicked"
    return result


def _execute_employer_question_type_text(
    base_url: str,
    *,
    app_name: str,
    item: dict[str, Any],
    timeout: float,
    result: dict[str, Any],
) -> dict[str, Any]:
    target = item.get("target") if isinstance(item.get("target"), dict) else {}
    candidate = target.get("candidate") if isinstance(target.get("candidate"), dict) else {}
    bbox = _candidate_bbox(candidate)
    value = str(item.get("planned_answer") or "").strip()
    if not bbox:
        result["stop_reason"] = "missing_type_text_candidate_bbox"
        return result
    if not value:
        result["stop_reason"] = "missing_type_text_answer"
        return result
    point = _target_click_point(target, bbox)
    result["target_validation"] = _candidate_point_validation(point, bbox)
    if result["target_validation"].get("allowed") is not True:
        result["stop_reason"] = "employer_question_type_focus_point_outside_candidate_bbox"
        return result
    confirmed = _execute_confirmed_candidate_point(
        base_url,
        point=point,
        bbox=bbox,
        label=f"SEEK employer question {item.get('question_id')} text field",
        source_trace_path=None,
        timeout=timeout,
    )
    result.update(confirmed)
    if result.get("confirmed_execute_response", {}).get("success") is not True:
        result["stop_reason"] = "employer_question_type_confirmed_focus_execute_failed"
        return result
    type_response = _post_json(
        base_url,
        "/action/type_text",
        {
            "text": value,
            "dry_run": False,
            "click_before_typing": True,
            "x": int(point["x"]),
            "y": int(point["y"]),
            "clear_existing": True,
            "submit": False,
            "restore_clipboard": True,
        },
        timeout,
    )
    result["type_text_response"] = _compact_type_response(type_response)
    if type_response.get("success") is not True:
        result["stop_reason"] = "employer_question_type_text_failed"
        return result
    result["filled"] = True
    result["status"] = "typed"
    result["value_length"] = len(value)
    return result


def _execute_confirmed_candidate_point(
    base_url: str,
    *,
    point: dict[str, int],
    bbox: dict[str, int],
    label: str,
    source_trace_path: str | None,
    timeout: float,
) -> dict[str, Any]:
    payload = {
        "x": int(point["x"]),
        "y": int(point["y"]),
        "bbox": _confirmed_bbox_payload(bbox),
        "label": label,
        "source_trace_path": source_trace_path,
        "dry_run": True,
    }
    dry_response = _post_json(base_url, "/action/execute_confirmed_point", payload, timeout)
    result = {"confirmed_dry_run_response": _compact_confirmed_point_response(dry_response)}
    if dry_response.get("success") is not True:
        return result
    execute_response = _post_json(base_url, "/action/execute_confirmed_point", {**payload, "dry_run": False}, timeout)
    result["confirmed_execute_response"] = _compact_confirmed_point_response(execute_response)
    return result


def _compact_confirmed_point_response(response: dict[str, Any]) -> dict[str, Any]:
    payload = _result_payload(response)
    return {
        "success": response.get("success"),
        "message": response.get("message"),
        "trace_path": payload.get("trace_path") if isinstance(payload, dict) else None,
        "dry_run": (payload.get("execution_path") or {}).get("dry_run") if isinstance(payload, dict) else None,
        "confirmed_point": payload.get("confirmed_point") if isinstance(payload, dict) else None,
        "candidate_bbox": payload.get("candidate_bbox") if isinstance(payload, dict) else None,
        "action_executed": (payload.get("execution_path") or {}).get("action_executed") if isinstance(payload, dict) else None,
        "error": response.get("error"),
    }


def _confirmed_bbox_payload(bbox: dict[str, int]) -> dict[str, int]:
    return {"x": int(bbox["x"]), "y": int(bbox["y"]), "width": int(bbox["w"]), "height": int(bbox["h"])}


def _target_click_point(target: dict[str, Any], bbox: dict[str, int]) -> dict[str, int]:
    point = target.get("click_point") if isinstance(target.get("click_point"), dict) else None
    if point:
        try:
            return {"x": int(point.get("x")), "y": int(point.get("y"))}
        except (TypeError, ValueError):
            pass
    return _bbox_center_point(bbox)


def _employer_question_recognition_payload(
    *,
    app_name: str,
    item: dict[str, Any],
    target: dict[str, Any],
    goal: str,
) -> dict[str, Any]:
    return {
        "agent_mode": "execute",
        "goal": goal,
        "app_name": app_name,
        "state_hint": "SEEK application employer questions step; answer exactly one mapped question and do not navigate",
        "capture_live": True,
        "dry_run": True,
        "enable_post_click_verification": True,
        "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
        "metadata": {
            "seek_employer_question_answer": True,
            "forbid_final_submit": True,
            "question_id": item.get("question_id"),
            "question_text": item.get("question_text"),
            "planned_answer": item.get("planned_answer"),
            "target_action_type": target.get("action_type"),
            "candidate_bbox": target.get("bbox"),
        },
    }


def _approved_plan_and_point(response: dict[str, Any], compact: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    payload = _result_payload(response)
    step = payload.get("agent_step_result") if isinstance(payload.get("agent_step_result"), dict) else {}
    approved_plan_id = payload.get("approved_plan_id") or step.get("approved_plan_id") or compact.get("approved_plan_id")
    selected_point = payload.get("selected_click_point") or step.get("selected_click_point") or compact.get("selected_click_point")
    return (str(approved_plan_id) if approved_plan_id else None, selected_point if isinstance(selected_point, dict) else None)


def _candidate_bbox(candidate: dict[str, Any]) -> dict[str, int] | None:
    bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else None
    if not bbox:
        return None
    try:
        x = int(bbox.get("x"))
        y = int(bbox.get("y"))
        w = int(bbox.get("w"))
        h = int(bbox.get("h"))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _bbox_center_point(bbox: dict[str, int]) -> dict[str, int]:
    return {"x": int(bbox["x"] + bbox["w"] / 2), "y": int(bbox["y"] + bbox["h"] / 2)}


def _candidate_point_validation(point: dict[str, Any] | None, bbox: dict[str, int]) -> dict[str, Any]:
    if not isinstance(point, dict):
        return {"allowed": False, "reason": "missing_selected_click_point", "candidate_bbox": bbox}
    try:
        x = int(round(float(point.get("x"))))
        y = int(round(float(point.get("y"))))
    except (TypeError, ValueError):
        return {"allowed": False, "reason": "invalid_selected_click_point", "selected_click_point": point, "candidate_bbox": bbox}
    allowed = bbox["x"] <= x <= bbox["x"] + bbox["w"] and bbox["y"] <= y <= bbox["y"] + bbox["h"]
    return {
        "allowed": allowed,
        "reason": "inside_candidate_bbox" if allowed else "outside_candidate_bbox",
        "selected_click_point": {"x": x, "y": y},
        "candidate_bbox": bbox,
    }


def run_step(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    state = _load_state(run_dir)
    learned_artifact = _read_json(args.learned_artifact)
    step = args.step
    report: dict[str, Any]

    if step == "close_old_seek_windows":
        apps = _apps_snapshot(args.base_url, args.timeout)
        candidates = _seek_window_candidates(apps)
        closed = _close_top_level_windows(candidates) if args.allow_close_windows else []
        if closed:
            time.sleep(0.8)
        report = {
            "status": "ok",
            "old_seek_windows_detected": candidates,
            "closed_windows": closed,
            "close_policy": "explicit_allow_close_windows" if args.allow_close_windows else "detect_only",
        }
        state["next_allowed_steps"] = ["open"]
    elif step == "open":
        before = _apps_snapshot(args.base_url, args.timeout)
        old_windows = _seek_window_candidates(before)
        closed = _close_top_level_windows(old_windows) if args.allow_close_windows else []
        if closed:
            time.sleep(0.8)
        open_response = _open_seek_debug(args.base_url, url=args.url, app_name=args.app_name, timeout=args.timeout)
        opened_bound_window = (_result_payload(open_response).get("bound_window") or {}).copy() or None
        if open_response.get("success") is not True or not opened_bound_window:
            state["bound_window"] = None
            state["source_url"] = args.url
            report = {
                "status": "failed",
                "failure_contract": "seek_debug_open_bind_v1",
                "failure_reason": "open_did_not_bind_window",
                "old_seek_windows_detected": old_windows,
                "closed_windows": closed,
                "close_policy": "explicit_allow_close_windows" if args.allow_close_windows else "detect_only",
                "open_response": open_response,
                "trace_paths": _trace_paths(open_response),
            }
            state["next_allowed_steps"] = ["open", "bind_and_resize_verify"]
        else:
            resize_response = _resize_bound_window(
                args.base_url,
                width=args.window_width,
                height=args.window_height,
                timeout=args.timeout,
            )
            capture = _capture(args.base_url, args.timeout)
            state["bound_window"] = opened_bound_window
            state["source_url"] = args.url
            report = {
                "status": "ok",
                "old_seek_windows_detected": old_windows,
                "closed_windows": closed,
                "close_policy": "explicit_allow_close_windows" if args.allow_close_windows else "detect_only",
                "open_response": open_response,
                "resize_response": resize_response,
                "after_image": capture["image_path"],
                "trace_paths": _trace_paths(open_response, resize_response or {}),
            }
            state["next_allowed_steps"] = ["bind_and_resize_verify", "capture", "extract_cards"]
    elif step == "bind_and_resize_verify":
        bind_response = _bind_seek_debug_window(args.base_url, app_name=args.app_name, timeout=args.timeout)
        before_state = _runtime_state(args.base_url, args.timeout)
        resize_response = _resize_bound_window(
            args.base_url,
            width=args.window_width,
            height=args.window_height,
            timeout=args.timeout,
        )
        after_state = _runtime_state(args.base_url, args.timeout)
        capture = _capture(args.base_url, args.timeout)
        verification = _bound_window_verification(
            after_state["payload"],
            min_width=min(1100, int(args.window_width or 1100)),
            min_height=min(850, int(args.window_height or 850)),
        )
        verified = (
            verification["bound"] is True
            and verification["process_is_external_browser"] is True
            and verification["title_contains_seek"] is True
            and verification["window_size_ok"] is True
        )
        state["bound_window"] = after_state["payload"]
        state["coordinate_window_size"] = verification.get("coordinate_window_size")
        report = {
            "status": "ok" if verified else "needs_review",
            "bind_response": bind_response,
            "before_bound_state": before_state["payload"],
            "resize_response": resize_response,
            "after_bound_state": after_state["payload"],
            "bound_window_verification": verification,
            "after_image": capture["image_path"],
            "trace_paths": _trace_paths(bind_response, resize_response or {}),
        }
        state["next_allowed_steps"] = ["capture", "extract_cards"] if verified else ["bind_and_resize_verify", "open"]
    elif step == "search_keyword_submit":
        before_state = _runtime_state(args.base_url, args.timeout)
        search_submit = _submit_seek_search_query(
            args.base_url,
            query=args.search_query,
            x=args.search_x,
            y=args.search_y,
            timeout=args.timeout,
            wait_seconds=args.search_wait_seconds,
        )
        after_state = _runtime_state(args.base_url, args.timeout)
        after_capture = _capture(args.base_url, args.timeout) if args.capture_after_search else None
        state["last_search_submit"] = search_submit
        state["search_query"] = args.search_query
        report = {
            "status": search_submit["status"],
            "search_submit": search_submit,
            "before_bound_state": before_state["payload"],
            "after_bound_state": after_state["payload"],
            "after_image": after_capture["image_path"] if after_capture else None,
            "trace_paths": search_submit.get("trace_paths") or [],
        }
        state["next_allowed_steps"] = ["extract_cards", "capture"]
    elif step == "capture":
        capture = _capture(args.base_url, args.timeout)
        report = {
            "status": "ok",
            "after_image": capture["image_path"],
            "capture_payload": capture["payload"],
        }
        state["next_allowed_steps"] = ["extract_cards"]
    elif step == "extract_cards":
        capture = _capture(args.base_url, args.timeout)
        observation, cards = _observe_and_extract_cards(args.base_url, args.app_name, args.timeout)
        state["last_observation"] = observation
        state["cards_payload"] = cards
        report = {
            "status": "ok",
            "before_image": capture["image_path"],
            "observe_image": _image_path(observation),
            "observe_trace": observation.get("trace_path"),
            "cards_payload": cards,
            "visible_jobs": len(cards.get("jobs") or []),
            "trace_paths": _trace_paths(observation),
        }
        state["next_allowed_steps"] = ["dry_run_card", "execute_card"]
    elif step == "dry_run_card":
        job = _select_job(state, args.job_index)
        before = _capture(args.base_url, args.timeout)
        action = _execute_job_card(
            args.base_url,
            app_name=args.app_name,
            job=job,
            execute_clicks=False,
            timeout=args.timeout,
            learned_artifact=learned_artifact,
        )
        state["current_job"] = job
        report = {
            "status": "ok" if action.get("approved_plan_id") else "failed",
            "job_index": args.job_index,
            "job": job,
            "before_image": before["image_path"],
            "action": action,
            "trace_paths": _trace_paths(action.get("dry_run_response") or {}),
        }
        state["next_allowed_steps"] = ["execute_card"]
    elif step == "execute_card":
        job = _select_job(state, args.job_index)
        before = _capture(args.base_url, args.timeout)
        action = _execute_job_card(
            args.base_url,
            app_name=args.app_name,
            job=job,
            execute_clicks=True,
            timeout=args.timeout,
            learned_artifact=learned_artifact,
            verify_after_click=not bool(args.fast_open_detail),
            fast_confirmed_card_click=bool(args.fast_open_detail),
        )
        after = _capture(args.base_url, args.timeout)
        execute_artifacts = _execute_debug_artifacts(
            before_image=before["image_path"],
            after_image=after["image_path"],
            expected_change="detail_opened",
            target_bbox=job.get("card_bbox") if isinstance(job, dict) else None,
        )
        state["current_job"] = job
        new_detail_seed = {
            key: job.get(key)
            for key in ("job_id", "title", "company", "location", "work_type", "classification", "salary_text")
            if isinstance(job, dict) and job.get(key)
        }
        if new_detail_seed:
            put_latest_detail_snapshot(
                state,
                with_detail_snapshot(new_detail_seed, source="open_detail_seed", previous=None),
            )
        state["ui_diff_verification"] = execute_artifacts.get("ui_diff_verification")
        report = {
            "status": "ok" if action.get("opened") is True else "failed",
            "job_index": args.job_index,
            "job": job,
            "before_image": before["image_path"],
            "after_image": after["image_path"],
            "ui_diff_verification": execute_artifacts.get("ui_diff_verification"),
            "action": action,
            "trace_paths": _trace_paths(action.get("dry_run_response") or {}, action.get("execute_response") or {}),
        }
        state["next_allowed_steps"] = ["verify_detail", "read_detail_batch"]
    elif step == "verify_detail":
        before = _capture(args.base_url, args.timeout)
        observation, detail = _observe_detail(args.base_url, args.app_name, args.timeout)
        merged_detail = _merge_verified_detail(
            previous_detail=state.get("detail") if isinstance(state.get("detail"), dict) else None,
            after_detail=detail,
            current_job=state.get("current_job") if isinstance(state.get("current_job"), dict) else None,
        )
        merged_detail = _compact_detail_for_state(with_detail_snapshot(merged_detail, source="verify_detail", previous=state.get("detail") if isinstance(state.get("detail"), dict) else None)) or {}
        put_latest_detail_snapshot(state, merged_detail)
        execute_artifacts = _execute_debug_artifacts(
            observation=observation,
            before_image=before["image_path"],
            after_image=_image_path(observation),
            expected_change="detail_observed",
        )
        state["execute_observation"] = execute_artifacts.get("execute_observation")
        report = {
            "status": "ok" if merged_detail.get("title") else "needs_review",
            "before_image": before["image_path"],
            "observe_image": _image_path(observation),
            "observe_trace": observation.get("trace_path"),
            "execute_observation": execute_artifacts.get("execute_observation"),
            "detail": merged_detail,
            "raw_detail": _compact_detail_for_state(detail),
            "trace_paths": _trace_paths(observation),
        }
        state["next_allowed_steps"] = ["read_detail_batch", "match"]
    elif step == "read_detail_scroll":
        before = _capture(args.base_url, args.timeout)
        scroll = _one_detail_scroll(
            args.base_url,
            app_name=args.app_name,
            timeout=args.timeout,
            learned_artifact=learned_artifact,
            wheel_clicks=args.wheel_clicks,
            previous_scrolls=state.get("detail_scrolls") if isinstance(state.get("detail_scrolls"), list) else [],
        )
        after = _capture(args.base_url, args.timeout)
        merged_detail = _merge_scrolled_detail(
            previous_detail=state.get("detail") if isinstance(state.get("detail"), dict) else None,
            before_detail=scroll.get("before_detail") if isinstance(scroll.get("before_detail"), dict) else None,
            after_detail=scroll["after_detail"],
            current_job=state.get("current_job") if isinstance(state.get("current_job"), dict) else None,
        )
        merged_detail = _compact_detail_for_state(with_detail_snapshot(merged_detail, source="read_detail_scroll", previous=state.get("detail") if isinstance(state.get("detail"), dict) else None)) or {}
        put_latest_detail_snapshot(state, merged_detail)
        execute_artifacts = _execute_debug_artifacts(
            before_image=before["image_path"],
            after_image=after["image_path"],
            expected_change="scroll_progress",
            target_bbox=scroll["scroll_request"].get("container_bbox"),
        )
        state["ui_diff_verification"] = execute_artifacts.get("ui_diff_verification")
        state.setdefault("detail_scrolls", []).append(
            {
                "scroll_request": scroll["scroll_request"],
                "validation": scroll["validation"],
                "ui_diff_verification": execute_artifacts.get("ui_diff_verification"),
                "trace_paths": _trace_paths(scroll["scroll_response"]),
            }
        )
        report = {
            "status": "ok" if scroll["scroll_response"].get("success") is True else "failed",
            "before_image": before["image_path"],
            "after_image": after["image_path"],
            "before_detail": _compact_detail_for_state(scroll["before_detail"]),
            "after_detail": _compact_detail_for_state(scroll["after_detail"]),
            "merged_detail": merged_detail,
            "scroll_request": scroll["scroll_request"],
            "scroll_response": _compact_action_response(scroll["scroll_response"]),
            "right_detail_scroll_validation": scroll["validation"],
            "ui_diff_verification": execute_artifacts.get("ui_diff_verification"),
            "trace_paths": _trace_paths(scroll["before_observation"], scroll["scroll_response"], scroll["after_observation"]),
        }
        state["next_allowed_steps"] = scroll["validation"].get("next_allowed_steps") or ["read_detail_scroll", "match"]
    elif step == "read_detail_batch":
        detail = state.get("detail") if isinstance(state.get("detail"), dict) else {}
        if not detail and isinstance(state.get("current_job"), dict):
            current_job = state["current_job"]
            detail = {
                key: current_job.get(key)
                for key in ("job_id", "title", "company", "location", "work_type", "classification", "salary_text")
                if current_job.get(key)
            }
        batch = _read_detail_batch(
            args.base_url,
            timeout=args.timeout,
            detail=detail,
            learned_artifact=learned_artifact,
            wheel_clicks=args.wheel_clicks,
            max_captures=args.batch_max_captures,
            stop_after_no_new_content=args.batch_stop_after_no_new_content,
        )
        state["detail_batch_read"] = batch
        merged_detail = (
            _compact_detail_for_state(_merge_detail_batch_read_into_detail(detail, batch))
            if batch.get("status") == "ok"
            else None
        )
        if merged_detail is not None:
            put_latest_detail_snapshot(state, merged_detail)
        report = {
            "status": batch.get("status"),
            "read_region_batch": batch,
            "target_container_id": batch.get("target_container_id"),
            "target_bbox": batch.get("target_bbox"),
            "capture_count": batch.get("capture_count"),
            "unique_line_count": batch.get("unique_line_count"),
            "stop_reason": batch.get("stop_reason"),
            "merged_description_section_count": len((merged_detail or {}).get("description_sections") or []),
            "trace_paths": [item.get("trace_path") for item in batch.get("captures", []) if item.get("trace_path")],
        }
        state["next_allowed_steps"] = ["match", "read_detail_batch"] if batch.get("status") == "ok" else ["verify_detail", "capture"]
    elif step == "match":
        profile = load_candidate_profile(args.candidate_profile)
        card = state.get("current_job") if isinstance(state.get("current_job"), dict) else None
        detail = state.get("detail") if isinstance(state.get("detail"), dict) else None
        require_latest_detail_snapshot(state, detail)
        decision = score_seek_job(profile=profile, card=card, detail=detail, detail_complete=True)
        saved_path = save_suitable_job_record(decision=decision, card=card or {}, detail=detail or {})
        state["match_decision"] = decision
        report = {
            "status": "ok",
            "card": card,
            "detail": detail,
            "match_decision": decision,
            "saved_job_record_path": saved_path,
            "next_safe_step": decision.get("recommended_next_action"),
        }
        state["next_allowed_steps"] = ["dry_run_apply_entry"] if decision.get("decision") in {"strong_apply", "maybe_apply"} else ["extract_cards"]
    elif step in {"dry_run_apply_entry", "execute_apply_entry"}:
        profile = load_candidate_profile(args.candidate_profile)
        job, detail, decision = _require_apply_entry_context(state)
        before = _capture(args.base_url, args.timeout)
        execute = step == "execute_apply_entry"
        apply_attempt = _execute_apply_entry(
            args.base_url,
            app_name=args.app_name,
            job=job,
            detail=detail,
            match_decision=decision,
            candidate_profile=profile,
            execute_clicks=execute,
            timeout=args.timeout,
            allow_maybe_apply=bool(args.allow_maybe_apply),
            fill_safe_fields=bool(args.fill_safe_fields and execute),
            max_safe_fields_to_fill=args.max_safe_fields_to_fill,
            allow_cover_letter_fill=bool(args.allow_cover_letter_fill and execute),
        )
        post_capture_wait_seconds = float(args.post_apply_capture_wait_seconds or 0) if execute else 0.0
        post_apply_wait = (
            _wait_for_application_flow_after_apply(
                args.base_url,
                app_name=args.app_name,
                source_job={**job, **detail},
                initial_flow_state=apply_attempt.get("application_flow_state") if isinstance(apply_attempt, dict) else None,
                timeout=args.timeout,
                max_wait_seconds=post_capture_wait_seconds,
            )
            if execute and apply_attempt.get("executed") is True
            else {
                "contract_version": "seek_application_flow_wait_v1",
                "status": "not_requested",
                "max_wait_seconds": 0.0,
                "poll_count": 0,
            }
        )
        if execute and isinstance(post_apply_wait.get("application_flow_state"), dict):
            apply_attempt["application_flow_state"] = post_apply_wait["application_flow_state"]
            apply_attempt["application_flow_started"] = _application_flow_ready(post_apply_wait["application_flow_state"])
            refreshed_flow_decision = build_seek_apply_flow_decision(post_apply_wait["application_flow_state"])
            apply_attempt["apply_flow_decision"] = refreshed_flow_decision
            apply_attempt["stop_reason"] = refreshed_flow_decision.get("reason") or apply_attempt.get("stop_reason")
            apply_attempt["final_submit_visible_blocker"] = post_apply_wait["application_flow_state"].get("final_submit_visible_blocker")
        after = _capture(args.base_url, args.timeout) if execute else None
        state["apply_entry_attempt"] = apply_attempt
        report = {
            "status": apply_attempt.get("status") or ("ok" if apply_attempt.get("eligible") else "needs_review"),
            "before_image": before["image_path"],
            "after_image": after["image_path"] if after else None,
            "post_apply_capture_wait_seconds": post_capture_wait_seconds,
            "post_apply_wait": post_apply_wait,
            "job": job,
            "detail": detail,
            "match_decision": decision,
            "apply_entry": apply_attempt,
            "trace_paths": _trace_paths(
                apply_attempt.get("dry_run_response") if isinstance(apply_attempt, dict) else {},
                apply_attempt.get("execute_response") if isinstance(apply_attempt, dict) else {},
                apply_attempt.get("application_flow_state") if isinstance(apply_attempt, dict) else {},
            ),
        }
        if execute and apply_attempt.get("application_flow_started"):
            state["application_flow_state"] = apply_attempt.get("application_flow_state")
            state["application_answer_plan"] = apply_attempt.get("application_answer_plan")
            state["cover_letter_draft"] = apply_attempt.get("cover_letter_draft")
            state["next_allowed_steps"] = ["continue_application_flow", "capture"]
        elif execute:
            state["next_allowed_steps"] = ["execute_apply_entry", "match"]
        elif apply_attempt.get("eligible") is not True or apply_attempt.get("status") not in {"dry_run_ready", "ok"}:
            state["next_allowed_steps"] = ["match", "extract_cards"]
        else:
            state["next_allowed_steps"] = ["execute_apply_entry", "match"]
    elif step == "continue_application_flow":
        replay_report = _read_json(args.application_flow_replay)
        profile = load_candidate_profile(args.candidate_profile)
        job, detail, decision, application_context = _require_application_flow_context(
            state,
            learned_artifact=learned_artifact,
        )
        before = _capture(args.base_url, args.timeout)
        observation = _observe(
            args.base_url,
            app_name=args.app_name,
            state_hint="SEEK application flow current step; read form state, prepare safe fields, and stop before final submit",
            timeout=args.timeout,
        )
        flow_state = assess_seek_application_flow_state(observation, source_job={**job, **detail})
        employer_question_inventory = build_employer_question_inventory(
            flow_state,
            screen_reading=_screen_reading_from_observation(observation),
        )
        employer_question_answer_plan = build_employer_question_answer_plan(
            employer_question_inventory,
            profile=profile,
        )
        employer_question_answer_preview = build_employer_question_answer_preview(employer_question_answer_plan)
        flow_decision = build_seek_apply_flow_decision(flow_state)
        replay_context = _application_replay_context(replay_report, flow_state)
        cover_letter_draft = {"status": "not_generated"}
        answer_plan = {"status": "not_generated"}
        safe_fill_attempt = {
            "contract_version": "safe_form_fill_attempt_v1",
            "enabled": False,
            "status": "blocked_need_user_or_gpt_decision",
            "stop_reason": flow_decision.get("reason") or flow_state.get("stop_reason"),
            "fields_filled": 0,
            "final_submissions": 0,
        }
        employer_question_fill_attempt = {
            "contract_version": "safe_employer_question_fill_attempt_v1",
            "enabled": False,
            "status": "not_attempted",
            "stop_reason": "not_employer_question_transition",
            "answered_count": 0,
            "final_submissions": 0,
        }
        selected_transition = replay_context.get("selected_transition") if isinstance(replay_context.get("selected_transition"), dict) else {}
        if replay_context.get("allows_final_submit"):
            safe_fill_attempt["status"] = "blocked_final_submit_forbidden"
            safe_fill_attempt["stop_reason"] = "strict_replay_transition_would_allow_final_submit"
            employer_question_fill_attempt["status"] = "blocked_final_submit_forbidden"
            employer_question_fill_attempt["stop_reason"] = "strict_replay_transition_would_allow_final_submit"
        elif _is_answer_questions_transition(selected_transition):
            employer_question_fill_attempt = _safe_employer_question_fill_attempt(
                args.base_url,
                app_name=args.app_name,
                answer_preview=employer_question_answer_preview,
                execute_fill=bool(args.fill_safe_fields),
                timeout=args.timeout,
            )
        elif flow_decision.get("decision") == "continue_read_only":
            cover_letter_draft = build_cover_letter_draft(
                profile=profile,
                detail=detail,
                match_decision=decision,
                application_flow_state=flow_state,
                allow_maybe_apply=bool(args.allow_maybe_apply),
            )
            answer_plan = build_application_answer_plan(
                profile=profile,
                application_flow_state=flow_state,
                cover_letter_draft=cover_letter_draft,
            )
            safe_fill_attempt = _safe_form_fill_attempt(
                args.base_url,
                app_name=args.app_name,
                answer_plan=answer_plan,
                candidate_profile=profile,
                cover_letter_draft=cover_letter_draft,
                execute_fill=bool(args.fill_safe_fields),
                max_safe_fields_to_fill=args.max_safe_fields_to_fill,
                allow_cover_letter_fill=bool(args.allow_cover_letter_fill),
                timeout=args.timeout,
            )
        continue_after_fill = {
            "contract_version": "seek_safe_continue_after_fill_v1",
            "attempted": False,
            "status": "not_attempted",
            "continue_clicks": 0,
            "submit_clicks": 0,
            "final_submissions": 0,
        }
        if (
            _is_answer_questions_transition(selected_transition)
            and employer_question_fill_attempt.get("status") == "filled_until_review"
            and int(employer_question_fill_attempt.get("answered_count") or 0) > 0
        ):
            continue_after_fill = _safe_continue_after_fill(
                args.base_url,
                app_name=args.app_name,
                timeout=args.timeout,
                from_step=flow_state.get("current_step"),
            )
            if isinstance(continue_after_fill.get("post_continue_application_flow_state"), dict):
                flow_state = continue_after_fill["post_continue_application_flow_state"]
                flow_decision = build_seek_apply_flow_decision(flow_state)
        elif (
            selected_transition.get("low_level_action_type") == "type_text_and_gated_continue"
            and safe_fill_attempt.get("status") == "filled_until_review"
            and int(safe_fill_attempt.get("fields_filled") or 0) > 0
        ):
            continue_after_fill = _safe_continue_after_fill(
                args.base_url,
                app_name=args.app_name,
                timeout=args.timeout,
                from_step=flow_state.get("current_step"),
            )
            if isinstance(continue_after_fill.get("post_continue_application_flow_state"), dict):
                flow_state = continue_after_fill["post_continue_application_flow_state"]
                flow_decision = build_seek_apply_flow_decision(flow_state)
        elif (
            flow_state.get("current_step") == "update_seek_profile"
            and flow_decision.get("decision") == "continue_read_only"
            and int(safe_fill_attempt.get("final_submissions") or 0) == 0
        ):
            continue_after_fill = _safe_continue_after_fill(
                args.base_url,
                app_name=args.app_name,
                timeout=args.timeout,
                from_step=flow_state.get("current_step"),
            )
            if isinstance(continue_after_fill.get("post_continue_application_flow_state"), dict):
                flow_state = continue_after_fill["post_continue_application_flow_state"]
                flow_decision = build_seek_apply_flow_decision(flow_state)
        after = _capture(args.base_url, args.timeout)
        execute_artifacts = _execute_debug_artifacts(
            observation=observation,
            flow_state=flow_state,
            employer_question_inventory=employer_question_inventory,
            application_answer_plan=answer_plan,
            before_image=before["image_path"],
            after_image=after["image_path"],
            expected_change="step_changed" if continue_after_fill.get("executed") else "field_value_changed",
        )
        state["application_flow_state"] = flow_state
        state["apply_flow_decision"] = flow_decision
        state["cover_letter_draft"] = cover_letter_draft
        state["application_answer_plan"] = answer_plan
        state["employer_question_inventory"] = employer_question_inventory
        state["employer_question_answer_plan"] = employer_question_answer_plan
        state["employer_question_answer_preview"] = employer_question_answer_preview
        state["execute_observation"] = execute_artifacts.get("execute_observation")
        state["form_field_inventory"] = execute_artifacts.get("form_field_inventory")
        state["ui_diff_verification"] = execute_artifacts.get("ui_diff_verification")
        state["employer_question_fill_attempt"] = employer_question_fill_attempt
        state["safe_form_fill_attempt"] = safe_fill_attempt
        state["continue_after_fill"] = continue_after_fill
        state["application_replay_context"] = replay_context
        state["application_context"] = application_context
        report_status = (
            continue_after_fill.get("status")
            if continue_after_fill.get("attempted")
            else (
                employer_question_fill_attempt.get("status")
                if employer_question_fill_attempt.get("status") not in {None, "not_attempted"}
                else safe_fill_attempt.get("status") or flow_state.get("status")
            )
        )
        report = {
            "status": report_status,
            "before_image": before["image_path"],
            "after_image": after["image_path"],
            "application_flow_state": flow_state,
            "apply_flow_decision": flow_decision,
            "employer_question_inventory": employer_question_inventory,
            "application_replay_context": replay_context,
            "application_context": application_context,
            "live_strict_replay_ready": replay_context.get("can_run_live_strict_replay") is True,
            "selected_transition_id": (replay_context.get("selected_transition") or {}).get("transition_id"),
            "requires_screenshot_before": replay_context.get("requires_screenshot_before"),
            "requires_screenshot_after": replay_context.get("requires_screenshot_after"),
            "requires_safe_fill_focus": replay_context.get("requires_safe_fill_focus"),
            "requires_post_fill_verification": replay_context.get("requires_post_fill_verification"),
            "cover_letter_draft": cover_letter_draft,
            "application_answer_plan": answer_plan,
            "employer_question_answer_plan": employer_question_answer_plan,
            "employer_question_answer_preview": employer_question_answer_preview,
            "execute_observation": execute_artifacts.get("execute_observation"),
            "form_field_inventory": execute_artifacts.get("form_field_inventory"),
            "ui_diff_verification": execute_artifacts.get("ui_diff_verification"),
            "employer_question_fill_attempt": employer_question_fill_attempt,
            "safe_form_fill_attempt": safe_fill_attempt,
            "continue_after_fill": continue_after_fill,
            "form_fields_filled": safe_fill_attempt.get("fields_filled", 0),
            "employer_questions_answered": employer_question_fill_attempt.get("answered_count", 0),
            "final_submission_performed": False,
            "trace_paths": _trace_paths(observation, continue_after_fill),
        }
        if (
            continue_after_fill.get("status") == "continued_to_next_step"
            and continue_after_fill.get("final_submit_visible") is not True
            and flow_state.get("current_step") != "review_and_submit"
        ):
            state["next_allowed_steps"] = ["continue_application_flow", "capture"]
        elif flow_decision.get("decision") == "stop":
            state["next_allowed_steps"] = ["capture"]
        elif flow_decision.get("decision") == "continue_read_only":
            state["next_allowed_steps"] = ["continue_application_flow", "capture"]
        else:
            state["next_allowed_steps"] = ["capture", "match"]
        report["next_allowed_steps"] = state["next_allowed_steps"]
    elif step == "extract_final_review":
        record_path = Path(args.application_fill_record) if args.application_fill_record else run_dir / "application_fill_record.json"
        fill_record = _read_json(record_path)
        if not isinstance(fill_record, dict):
            raise SeekTraversalError(f"application fill record not found or invalid: {record_path}")
        review_read = _observe_final_review_until_submit_visible(
            args.base_url,
            app_name=args.app_name,
            timeout=args.timeout,
            fill_record=fill_record,
        )
        before = review_read["before"]
        observation = review_read["observation"]
        flow_state = review_read["flow_state"]
        extraction = review_read["extraction"]
        execute_artifacts = _execute_debug_artifacts(
            observation=observation,
            flow_state=flow_state,
            before_image=before["image_path"],
            after_image=before["image_path"],
            expected_change="review_extraction",
        )
        extraction_path = run_dir / "final_review_extraction.json"
        _write_json(extraction_path, extraction)
        state["application_flow_state"] = flow_state
        state["final_review_extraction"] = extraction
        state["final_review_extraction_path"] = str(extraction_path)
        state["execute_observation"] = execute_artifacts.get("execute_observation")
        state["form_field_inventory"] = execute_artifacts.get("form_field_inventory")
        state["next_allowed_steps"] = ["capture"]
        report = {
            "status": extraction.get("status"),
            "before_image": before["image_path"],
            "observe_image": _image_path(observation),
            "observe_trace": observation.get("trace_path"),
            "application_flow_state": flow_state,
            "execute_observation": execute_artifacts.get("execute_observation"),
            "form_field_inventory": execute_artifacts.get("form_field_inventory"),
            "final_review_extraction": extraction,
            "final_review_extraction_path": str(extraction_path),
            "review_read_attempts": review_read.get("review_read_attempts"),
            "review_reconciliation": extraction.get("review_reconciliation"),
            "submit_clicks": extraction.get("submit_clicks"),
            "final_submissions": extraction.get("final_submissions"),
            "trace_paths": _trace_paths(observation),
            "next_allowed_steps": state["next_allowed_steps"],
        }
    else:
        raise SeekTraversalError(f"unknown step: {step}")

    payload = _write_step_report(run_dir=run_dir, state=state, step_name=step, report=report)
    _write_current_job_archive(run_dir, state, payload)
    _save_state(run_dir, state)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one SEEK MVP debug step and stop.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument(
        "--step",
        required=True,
        choices=[
            "close_old_seek_windows",
            "open",
            "bind_and_resize_verify",
            "search_keyword_submit",
            "capture",
            "extract_cards",
            "dry_run_card",
            "execute_card",
            "verify_detail",
            "read_detail_scroll",
            "read_detail_batch",
            "match",
            "dry_run_apply_entry",
            "execute_apply_entry",
            "continue_application_flow",
            "extract_final_review",
        ],
    )
    parser.add_argument("--url", default=DEFAULT_SEEK_URL)
    parser.add_argument("--app-name", default="edge")
    parser.add_argument("--job-index", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--window-width", type=int, default=2560)
    parser.add_argument("--window-height", type=int, default=1400)
    parser.add_argument("--wheel-clicks", type=int, default=8)
    parser.add_argument("--search-query", default="graduate")
    parser.add_argument("--search-x", type=int, default=840)
    parser.add_argument("--search-y", type=int, default=207)
    parser.add_argument("--search-wait-seconds", type=float, default=8.0)
    parser.add_argument("--capture-after-search", action="store_true")
    parser.add_argument("--batch-max-captures", type=int, default=5)
    parser.add_argument("--batch-stop-after-no-new-content", type=int, default=2)
    parser.add_argument("--candidate-profile", default=str(DEFAULT_CANDIDATE_PROFILE))
    parser.add_argument("--learned-artifact", default="artifacts/seek/learned_seek_mvp_from_5job_smoke_20260617.json")
    parser.add_argument("--application-flow-replay", default=str(DEFAULT_APPLICATION_FLOW_REPLAY))
    parser.add_argument("--application-fill-record", default=None)
    parser.add_argument("--allow-maybe-apply", action="store_true")
    parser.add_argument(
        "--fast-open-detail",
        action="store_true",
        help="Skip the extra full-screen post-card-click verification and let read_detail_batch confirm the opened detail.",
    )
    parser.add_argument(
        "--post-apply-capture-wait-seconds",
        type=float,
        default=3.0,
        help="Maximum application-flow readiness poll after a real Apply Entry click before taking the debug screenshot.",
    )
    parser.add_argument("--fill-safe-fields", action="store_true")
    parser.add_argument("--max-safe-fields-to-fill", type=int, default=1)
    parser.add_argument("--allow-cover-letter-fill", action="store_true")
    parser.add_argument(
        "--allow-close-windows",
        action="store_true",
        help="Send WM_CLOSE to detected top-level SEEK browser windows before opening a new debug run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = run_step(args)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"success": True, "report_path": payload.get("report_path"), "result": payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
