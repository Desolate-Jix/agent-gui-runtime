from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse, Response
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from app.core.runtime_artifacts import write_trace
from app.core.model_server import load_model_profiles
from app.core.model_server import model_base_url
from app.models.response import APIResponse, ErrorModel

PANEL_DIR = Path(__file__).resolve().parents[1] / "web_panel"
PANEL_INDEX = PANEL_DIR / "index.html"
ROOT_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = ROOT_DIR / "artifacts" / "web-panel" / "uploads"
SETTINGS_PANEL_ARTIFACT_DIR = ROOT_DIR / "artifacts" / "settings-panel"
VISION_CONFIG_PATH = ROOT_DIR / "configs" / "vision.json"
PANEL_CONFIG_PATH = ROOT_DIR / "configs" / "settings_panel.json"

router = APIRouter(tags=["panel"])


class PanelImageUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    content_type: Optional[str] = None


class PanelManualBoxRequest(BaseModel):
    image_path: str = Field(min_length=1)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    label: Optional[str] = None


class PanelInterfaceAssetCropRequest(BaseModel):
    source_image_path: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    label: Optional[str] = None
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    padding_px: int = Field(default=6, ge=0, le=80)
    context_padding_px: int = Field(default=16, ge=0, le=160)


class PanelApplyModelProfileRequest(BaseModel):
    stage: str = Field(pattern="^(observe|locate)$")
    profile_id: str = Field(min_length=1)
    timeout_seconds: int = Field(default=600, ge=1, le=1800)
    language: str = "zh-CN"
    observe_prompt: Optional[str] = None
    locate_prompt: Optional[str] = None


class PanelModelTestRequest(BaseModel):
    profile_id: str = Field(min_length=1)
    stage: str = Field(default="observe", pattern="^(observe|locate)$")
    prompt: str = Field(min_length=1)
    image_path: Optional[str] = None
    max_tokens: int = Field(default=2048, ge=1, le=8192)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)


@router.get("/panel", include_in_schema=False)
def web_panel() -> FileResponse:
    """Serve the browser-based local test panel."""
    return FileResponse(PANEL_INDEX, media_type="text/html; charset=utf-8")


@router.get("/panel/file", include_in_schema=False)
def panel_file(path: str) -> Response:
    """Serve a local artifact/log image path for browser-panel preview."""
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = ROOT_DIR / resolved
    resolved = resolved.resolve()
    allowed_roots = [(ROOT_DIR / "artifacts").resolve(), (ROOT_DIR / "logs").resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        return PlainTextResponse("Not found", status_code=404)
    if not resolved.exists() or not resolved.is_file():
        return PlainTextResponse("Not found", status_code=404)
    response = FileResponse(resolved)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@router.get("/panel/list_traces", include_in_schema=False)
def list_traces(limit: int = 50, include_tests: bool = False, mode: Optional[str] = None) -> APIResponse:
    """List recent trace files from logs/traces/."""
    try:
        mode_filter = str(mode or "").strip().lower()
        if mode_filter not in {"", "learn", "execute"}:
            return APIResponse(success=False, message="Invalid trace mode", data=None, error=ErrorModel(code="invalid_trace_mode", details=mode))
        traces_dir = ROOT_DIR / "logs" / "traces"
        if not traces_dir.exists():
            return APIResponse(success=True, message="No traces yet", data={"traces": []}, error=None)
        files = []
        for category_dir in sorted(traces_dir.iterdir(), reverse=True):
            if not category_dir.is_dir():
                continue
            for tf in sorted(category_dir.iterdir(), reverse=True):
                if tf.suffix != ".json":
                    continue
                if not include_tests and _trace_references_pytest_temp(tf):
                    continue
                meta = _trace_list_metadata(tf)
                if mode_filter and meta.get("agent_mode") != mode_filter:
                    continue
                stat = tf.stat()
                files.append({
                    "name": tf.name,
                    "path": str(tf.resolve()),
                    "category": category_dir.name,
                    **meta,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
        files.sort(key=lambda f: f["modified"], reverse=True)
        return APIResponse(success=True, message=f"{len(files)} traces", data={"traces": files[:limit]}, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="List failed", data=None, error=ErrorModel(code="trace_list_failed", details=str(exc)))


def _trace_list_metadata(path: Path) -> dict[str, str]:
    parts = path.stem.split("__")
    operation = parts[1] if len(parts) > 1 else ""
    metadata: dict[str, str] = {"operation": operation, "agent_mode": "", "mode_contract_version": "", "contract_version": ""}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return metadata
    trace = payload.get("result") if isinstance(payload, dict) and isinstance(payload.get("result"), dict) else payload
    request = payload.get("request") if isinstance(payload, dict) and isinstance(payload.get("request"), dict) else {}
    if isinstance(trace, dict):
        metadata["agent_mode"] = str(trace.get("agent_mode") or request.get("agent_mode") or "")
        metadata["mode_contract_version"] = str(trace.get("mode_contract_version") or "")
        metadata["contract_version"] = str(trace.get("contract_version") or "")
        plan = trace.get("recognition_plan")
        if not metadata["agent_mode"] and isinstance(plan, dict):
            metadata["agent_mode"] = str(plan.get("agent_mode") or "")
            metadata["mode_contract_version"] = str(plan.get("mode_contract_version") or "")
    return metadata


def _trace_references_pytest_temp(path: Path) -> bool:
    """Return True for traces generated by tests with deleted pytest temp assets."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        return False
    normalized = text.replace("\\\\", "\\").replace("/", "\\").casefold()
    return "\\pytest-of-" in normalized or "\\pytest-" in normalized


@router.get("/panel/inspect_trace", include_in_schema=False)
def inspect_trace(path: str) -> APIResponse:
    """Read a trace JSON and return a parsed summary for the inspector panel."""
    try:
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = ROOT_DIR / resolved
        resolved = resolved.resolve()
        if not resolved.exists() or not resolved.is_file():
            return APIResponse(success=False, message="Trace file not found", data=None, error=ErrorModel(code="trace_not_found", details=str(path)))
        raw_trace = json.loads(resolved.read_text(encoding="utf-8-sig"))
        trace = raw_trace.get("result") if isinstance(raw_trace, dict) and isinstance(raw_trace.get("result"), dict) else raw_trace

        parsed: dict[str, Any] = {
            "file": resolved.name,
            "path": str(resolved),
            "sections": {},  # raw trace sections keyed by stage id
            "flow_stages": [],
        }

        # Timings
        timings = trace.get("timings") or trace.get("runtime_timing_v1") or {}
        if isinstance(timings, dict):
            steps = timings.get("steps") or []
            total_ms = timings.get("total_ms") or 0
            parsed["total_time"] = f"{total_ms / 1000:.1f}s" if total_ms else ""
            parsed["stages"] = [{"name": s.get("name") or "unknown_step", "ms": s.get("elapsed_ms") or s.get("duration_ms") or 0} for s in steps[:20]]
            parsed["sections"]["timings"] = timings
        else:
            parsed["total_time"] = ""
            parsed["stages"] = []

        # Contract / task
        parsed["contract"] = trace.get("contract_version") or trace.get("task") or ""

        # Request info (鈫?goal stage)
        request = raw_trace.get("request") or trace.get("request") or {}
        if isinstance(request, dict):
            parsed["goal"] = request.get("goal") or trace.get("goal") or ""
            parsed["app_name"] = request.get("app_name") or trace.get("app_name") or ""
            parsed["state_hint"] = request.get("state_hint") or trace.get("state_hint") or ""
            parsed["provider"] = request.get("provider_mode") or trace.get("provider_mode") or ""
            if not parsed["contract"]:
                parsed["contract"] = request.get("task") or ""
            parsed["sections"]["goal"] = request

        # Capture info
        parsed["sections"]["capture"] = trace.get("live_capture") or trace.get("capture") or {
            "image_path": trace.get("image_path") or (request.get("image_path") if isinstance(request, dict) else "") or "",
        }
        plan = trace.get("recognition_plan") or (trace if trace.get("candidate_result") or trace.get("pre_click_decision") else {})
        if not isinstance(plan, dict):
            plan = {}
        plan_image_path = plan.get("image_path") or trace.get("image_path") or parsed["sections"].get("capture", {}).get("image_path")
        parse_result = trace.get("parse_result") if isinstance(trace.get("parse_result"), dict) else {}
        if not parse_result and isinstance(plan.get("parse_result"), dict):
            parse_result = plan["parse_result"]
        model_io = _first_dict(
            trace.get("model_io"),
            plan.get("model_io"),
            raw_trace.get("model_io") if isinstance(raw_trace, dict) else None,
            ((trace.get("degraded_reason") or {}).get("model_io")) if isinstance(trace.get("degraded_reason"), dict) else None,
            ((trace.get("raw_refs") or {}).get("model_io")) if isinstance(trace.get("raw_refs"), dict) else None,
        )
        if model_io:
            parsed["model_io_status"] = model_io.get("status") or ""
            parsed["model_io_attempt_count"] = int(model_io.get("attempt_count") or len(model_io.get("attempts") or []))
            parsed["sections"]["model_io"] = model_io

        if trace.get("output_path") or trace.get("candidate_count") is not None or trace.get("decision_count") is not None:
            parsed["sections"]["overlay"] = {
                "trace_path": trace.get("trace_path"),
                "image_path": trace.get("image_path"),
                "output_path": trace.get("output_path"),
                "candidate_count": trace.get("candidate_count"),
                "decision_count": trace.get("decision_count"),
                "narrow_result_count": trace.get("narrow_result_count"),
                "selected_candidate_id": trace.get("selected_candidate_id"),
            }
            if not parsed["contract"]:
                parsed["contract"] = "recognition_overlay_trace"
        coordinate_preview = trace.get("recognition_plan_overlay")
        if isinstance(coordinate_preview, dict):
            parsed["sections"]["coordinate_preview"] = coordinate_preview
            parsed["coordinate_preview_output_path"] = coordinate_preview.get("output_path") or coordinate_preview.get("overlay_path")
            parsed["coordinate_preview_candidate_count"] = coordinate_preview.get("candidate_count")
            parsed["coordinate_preview_decision_count"] = coordinate_preview.get("decision_count")

        # OCR result
        ocr = parse_result.get("ocr_result") or trace.get("ocr_result") or {}
        parsed["ocr_count"] = _ocr_count(ocr)
        if _meaningful_trace_section(ocr):
            parsed["sections"]["ocr"] = {"image_path": plan_image_path, **ocr} if isinstance(ocr, dict) else {"image_path": plan_image_path, "raw": ocr}

        # Vision
        vision_section = {
            "image_path": plan_image_path,
            "vision_regions": parse_result.get("vision_regions") or trace.get("vision_regions"),
            "vision_provider": trace.get("execution_path", {}).get("vision_provider_used") or trace.get("vision_provider_used") or "",
            "vision_model_used": trace.get("execution_path", {}).get("vision_model_used") or trace.get("vision_model_used") or False,
        }
        if vision_section["vision_regions"] or vision_section["vision_provider"] or vision_section["vision_model_used"]:
            parsed["sections"]["vision"] = vision_section

        # Recognition plan
        if isinstance(plan, dict) and plan:
            candidate_result = plan.get("candidate_result") or {}
            parsed["candidates"] = candidate_result.get("summary", {}).get("returned_count", 0)
            parsed["has_recommendation"] = bool(
                candidate_result.get("has_recommendation") or candidate_result.get("summary", {}).get("has_recommendation")
            )
            parsed["sections"]["candidates"] = {"image_path": plan_image_path, **candidate_result}

            pre_click = plan.get("pre_click_decision") or trace.get("pre_click_decision") or {}
            parsed["gate_allowed"] = pre_click.get("allowed")
            parsed["gate_reason"] = _gate_reason_text(pre_click)
            parsed["sections"]["gate"] = {
                "image_path": plan_image_path,
                "located_point": trace.get("located_point"),
                "located_bbox": trace.get("located_bbox"),
                "candidate_result": candidate_result,
                **pre_click,
            }

            parsed["selected_point"] = pre_click.get("selected_click_point") or trace.get("selected_click_point") or trace.get("located_point")
            parsed["sections"]["target"] = {
                "image_path": plan_image_path,
                "selected_click_point": parsed["selected_point"],
                "located_point": trace.get("located_point"),
                "located_bbox": trace.get("located_bbox"),
                "recommended_target": trace.get("recommended_target") or plan.get("recommended_target"),
                "location_status": trace.get("location_status"),
            }
            path_map_review = trace.get("path_map_review")
            if isinstance(path_map_review, dict):
                summary = path_map_review.get("summary") if isinstance(path_map_review.get("summary"), dict) else {}
                parsed["path_map_review_additions"] = int(summary.get("addition_count") or len(path_map_review.get("additions") or []))
                parsed["path_map_review_removals"] = int(summary.get("removal_count") or len(path_map_review.get("removals") or []))
                parsed["path_map_review_status"] = path_map_review.get("status") or ""
                parsed["sections"]["path_review"] = path_map_review
            path_graph_recall = trace.get("path_graph_recall") or plan.get("path_graph_recall")
            if isinstance(path_graph_recall, dict):
                summary = path_graph_recall.get("summary") if isinstance(path_graph_recall.get("summary"), dict) else {}
                parsed["path_graph_recall_count"] = int(summary.get("recalled_count") or len(path_graph_recall.get("candidates") or []))
                parsed["path_graph_recall_status"] = path_graph_recall.get("status") or ""
                state_match = path_graph_recall.get("state_match") if isinstance(path_graph_recall.get("state_match"), dict) else {}
                parsed["path_graph_recall_state"] = state_match.get("state_id") or ""
                parsed["sections"]["path_recall"] = path_graph_recall
            visual_asset_recall = trace.get("visual_asset_recall") or plan.get("visual_asset_recall")
            if isinstance(visual_asset_recall, dict):
                parsed["visual_asset_recall_status"] = visual_asset_recall.get("status") or ""
                parsed["visual_asset_fast_lane_used"] = bool(
                    visual_asset_recall.get("fast_lane_allowed")
                    or (trace.get("execution_path") or {}).get("visual_asset_fast_lane_used")
                    or (plan.get("execution_path") or {}).get("visual_asset_fast_lane_used")
                )
                parsed["visual_asset_matched_count"] = int(
                    visual_asset_recall.get("matched_count")
                    or len([item for item in visual_asset_recall.get("matches") or [] if isinstance(item, dict) and item.get("matched")])
                )
                parsed["sections"]["visual_asset_recall"] = visual_asset_recall
            fallback_plan = trace.get("fallback_plan")
            if isinstance(fallback_plan, dict):
                parsed["fallback_status"] = fallback_plan.get("status") or ""
                parsed["fallback_step_count"] = len(fallback_plan.get("steps") or []) if isinstance(fallback_plan.get("steps"), list) else 0
                parsed["fallback_reason"] = fallback_plan.get("failure_reason") or ""
                parsed["sections"]["fallback"] = fallback_plan
            agent_guidance = trace.get("agent_execution_guidance")
            if isinstance(agent_guidance, dict):
                parsed["agent_guidance_status"] = agent_guidance.get("status") or ""
                parsed["agent_guidance_next_action"] = agent_guidance.get("next_action") or ""
                parsed["sections"]["agent_guidance"] = agent_guidance
            memory_writeback = trace.get("element_memory_writeback")
            if isinstance(memory_writeback, dict):
                parsed["memory_status"] = memory_writeback.get("status") or ""
                parsed["memory_transition_id"] = memory_writeback.get("transition_id") or ""
                parsed["sections"]["memory"] = memory_writeback

            parsed["sections"]["click"] = plan.get("execution") or trace.get("click_result") or trace.get("execution_path") or {}
            parsed["sections"]["verify"] = trace.get("post_click_verification") or trace.get("semantic_post_click_verification") or {}

        path_map_review = trace.get("path_map_review")
        if isinstance(path_map_review, dict) and "path_review" not in parsed["sections"]:
            summary = path_map_review.get("summary") if isinstance(path_map_review.get("summary"), dict) else {}
            parsed["path_map_review_additions"] = int(summary.get("addition_count") or len(path_map_review.get("additions") or []))
            parsed["path_map_review_removals"] = int(summary.get("removal_count") or len(path_map_review.get("removals") or []))
            parsed["path_map_review_status"] = path_map_review.get("status") or ""
            learn_all_targets = trace.get("learn_all_targets") if isinstance(trace.get("learn_all_targets"), dict) else {}
            parsed["sections"]["path_review"] = {
                **path_map_review,
                "learn_all_targets": learn_all_targets,
                "coordinate_overlay_path": trace.get("coordinate_overlay_path") or learn_all_targets.get("overlay_path"),
                "coordinate_overlay": trace.get("coordinate_overlay") or learn_all_targets.get("overlay"),
            }

        # Screen understanding
        screen = trace.get("screen_reading") or trace.get("parse_result", {}).get("screen_reading") or {}
        if not screen and trace.get("contract_version") == "screen_reading_v1":
            screen = trace
        if isinstance(screen, dict):
            parsed["screen_summary"] = str(screen.get("screen_summary") or "")[:400]
            parsed["state_guess"] = screen.get("state_guess") or ""
            parsed["sections"]["screen"] = screen
            screen_inventory = _first_dict(
                trace.get("screen_inventory"),
                plan.get("screen_inventory"),
                parse_result.get("screen_inventory"),
                screen.get("screen_inventory"),
            )
            if screen_inventory and screen_inventory.get("contract_version") == "screen_inventory_v1":
                inventory_summary = screen_inventory.get("summary") if isinstance(screen_inventory.get("summary"), dict) else {}
                quality = screen_inventory.get("quality") if isinstance(screen_inventory.get("quality"), dict) else {}
                parsed["screen_inventory_action_count"] = int(
                    inventory_summary.get("available_action_count")
                    or len(screen_inventory.get("available_actions") or [])
                )
                parsed["screen_inventory_page_element_count"] = int(
                    inventory_summary.get("page_element_count")
                    or len(screen_inventory.get("page_elements") or [])
                )
                parsed["screen_inventory_card_count"] = int(
                    inventory_summary.get("card_count")
                    or len(screen_inventory.get("cards") or [])
                )
                parsed["screen_inventory_coordinate_coverage"] = quality.get("coordinate_coverage")
                parsed["sections"]["screen_inventory"] = screen_inventory

        # Observe-screen semantic map / navigation path seed.
        screen_map = trace.get("screen_map") or {}
        if isinstance(screen_map, dict) and screen_map.get("contract_version") == "screen_map_v1":
            candidates = screen_map.get("candidates") if isinstance(screen_map.get("candidates"), list) else []
            summary = screen_map.get("summary") if isinstance(screen_map.get("summary"), dict) else {}
            parsed["path_map_count"] = len(candidates)
            parsed["path_map_state_id"] = screen_map.get("state_id") or ""
            parsed["path_map_summary"] = (
                summary.get("screen_summary")
                or screen_map.get("state_hint")
                or parsed.get("screen_summary")
                or ""
            )
            parsed["sections"]["path_map"] = screen_map
        path_graph_deep_review = trace.get("path_graph_deep_review")
        if isinstance(path_graph_deep_review, dict):
            summary = path_graph_deep_review.get("summary") if isinstance(path_graph_deep_review.get("summary"), dict) else {}
            parsed["path_graph_deep_status"] = path_graph_deep_review.get("status") or ""
            parsed["path_graph_deep_additions"] = int(summary.get("missing_text_addition_count") or 0)
            parsed["path_graph_deep_removals"] = int(summary.get("duplicate_count") or 0)
            parsed["path_graph_deep_output_count"] = int(summary.get("output_candidate_count") or 0)
            parsed["sections"]["path_deep"] = {
                **path_graph_deep_review,
                "path_graph_delta": trace.get("path_graph_delta") if isinstance(trace.get("path_graph_delta"), dict) else None,
                "element_memory_init_plan": trace.get("element_memory_init_plan") if isinstance(trace.get("element_memory_init_plan"), dict) else None,
            }

        # Execution
        exec_path = trace.get("execution_path") or {}
        parsed["action_executed"] = exec_path.get("action_executed", False)

        # Verification
        verify = trace.get("post_click_verification") or trace.get("semantic_post_click_verification")
        if isinstance(verify, dict):
            parsed["verified"] = not (verify.get("verified") is False or verify.get("success") is False)
            parsed["verification_detail"] = str(verify.get("detail") or verify.get("message") or "")[:200]

        # Errors
        errors = []
        if trace.get("error"):
            errors.append(str(trace["error"])[:200])
        if isinstance(plan, dict) and plan.get("error"):
            errors.append(str(plan["error"])[:200])
        parsed["errors"] = errors
        if errors:
            parsed["sections"]["error"] = {"errors": errors}

        # Model info
        parsed["model_used"] = exec_path.get("vision_model_used") or trace.get("vision_model_used") or False
        parsed["model_provider"] = exec_path.get("vision_provider_used") or trace.get("vision_provider_used") or ""
        if isinstance(trace.get("layers"), list):
            flow_stages = _layer_flow_stages(trace["layers"])
        else:
            flow_stages = _trace_flow_stages(parsed)
        if not flow_stages:
            flow_stages = [{
                "id": "raw",
                "label": "Raw Trace",
                "value": parsed.get("contract") or resolved.name,
                "status": "done",
                "summary": "No known contract-specific stages matched; showing the full trace JSON.",
                "raw": trace,
            }]
        parsed["flow_stages"] = flow_stages

        return APIResponse(success=True, message="Trace parsed", data=parsed, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="Trace parse error", data=None, error=ErrorModel(code="trace_parse_error", details=str(exc)))


@router.post("/panel/upload_image", response_model=APIResponse)
def upload_panel_image(request: PanelImageUploadRequest) -> APIResponse:
    """Store an image dragged into the browser panel and return a runtime image path."""
    try:
        suffix = Path(request.filename).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            suffix = ".png"
        safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in Path(request.filename).stem)[:80]
        safe_name = f"{safe_stem or 'upload'}{suffix}"
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        payload = base64.b64decode(request.content_base64, validate=True)
        output = UPLOAD_DIR / safe_name
        if output.exists():
            output = UPLOAD_DIR / f"{safe_stem or 'upload'}-{len(list(UPLOAD_DIR.glob((safe_stem or 'upload') + '*')))}{suffix}"
        output.write_bytes(payload)
        image_path = str(output.resolve())
        return APIResponse(
            success=True,
            message="Image uploaded",
            data={
                "image_path": image_path,
                "image_url": f"/panel/file?path={image_path}",
                "content_type": request.content_type,
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Image upload failed",
            data=None,
            error=ErrorModel(code="panel_image_upload_failed", details=str(exc)),
        )


@router.post("/panel/manual_box", response_model=APIResponse)
def render_manual_box(request: PanelManualBoxRequest) -> APIResponse:
    """Render an operator-provided candidate box onto the current screenshot."""
    try:
        source_path = Path(request.image_path).expanduser()
        if not source_path.is_absolute():
            source_path = ROOT_DIR / source_path
        source_path = source_path.resolve()
        allowed_roots = [(ROOT_DIR / "artifacts").resolve(), (ROOT_DIR / "logs").resolve()]
        if not any(source_path == root or root in source_path.parents for root in allowed_roots):
            raise ValueError("Image path is outside artifacts/logs")
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(str(source_path))

        SETTINGS_PANEL_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        output = SETTINGS_PANEL_ARTIFACT_DIR / f"manual-box-{time.strftime('%Y%m%d-%H%M%S')}.png"
        label = (request.label or "target").strip() or "target"
        image = Image.open(source_path).convert("RGB")
        draw = ImageDraw.Draw(image)
        x2 = request.x + request.width
        y2 = request.y + request.height
        draw.rectangle([request.x, request.y, x2, y2], outline=(255, 0, 80), width=4)
        draw.text((request.x + 4, max(0, request.y - 18)), label, fill=(255, 0, 80))
        image.save(output)
        overlay_path = str(output.resolve())
        return APIResponse(
            success=True,
            message="Manual candidate box rendered",
            data={
                "manual_overlay_path": overlay_path,
                "image_path": overlay_path,
                "image_url": f"/panel/file?path={overlay_path}",
                "bbox": {"x": request.x, "y": request.y, "w": request.width, "h": request.height},
                "label": label,
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Manual candidate box failed",
            data=None,
            error=ErrorModel(code="panel_manual_box_failed", details=str(exc)),
        )


@router.post("/panel/crop_interface_asset", response_model=APIResponse)
def crop_interface_asset(request: PanelInterfaceAssetCropRequest) -> APIResponse:
    try:
        source_path = _resolve_allowed_artifact(request.source_image_path)
        crop_dir = INTERFACE_MAP_DIR / "crops"
        crop_dir.mkdir(parents=True, exist_ok=True)
        safe_asset = _safe_file_stem(request.asset_id)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        with Image.open(source_path) as image:
            width, height = image.size
            bbox = _clip_xywh(request.x, request.y, request.width, request.height, width, height)
            if bbox is None:
                raise ValueError("crop bbox is outside source image")
            tight_box = _expand_box(bbox, width, height, request.padding_px)
            context_box = _expand_box(bbox, width, height, request.context_padding_px)
            tight_crop = image.crop(tight_box)
            context_crop = image.crop(context_box)
            tight_path = crop_dir / f"{safe_asset}-{stamp}.tight.png"
            context_path = crop_dir / f"{safe_asset}-{stamp}.context.png"
            tight_crop.save(tight_path)
            context_crop.save(context_path)
        tight_ref = str(tight_path.resolve())
        context_ref = str(context_path.resolve())
        bbox_payload = _box_to_xywh(bbox)
        click_point = {"x": bbox_payload["x"] + bbox_payload["w"] // 2, "y": bbox_payload["y"] + bbox_payload["h"] // 2}
        trace_payload = {
            "contract_version": "learned_interface_map_asset_crop_trace_v1",
            "asset_id": request.asset_id,
            "label": request.label or "",
            "source_image_path": str(source_path),
            "tight_crop_ref": tight_ref,
            "context_crop_ref": context_ref,
            "bbox": bbox_payload,
            "click_point": click_point,
            "padding_px": request.padding_px,
            "context_padding_px": request.context_padding_px,
            "artifact_is_authorization": False,
            "can_authorize_click": False,
        }
        trace_path = write_trace(category="panel", operation="crop-interface-asset", payload=trace_payload, name_hint=safe_asset)
        return APIResponse(
            success=True,
            message="Interface asset cropped",
            data={
                "contract_version": "learned_interface_map_asset_crop_v1",
                "asset_id": request.asset_id,
                "source_image_path": str(source_path),
                "tight_crop_ref": tight_ref,
                "context_crop_ref": context_ref,
                "tight_crop_url": f"/panel/file?path={tight_ref}",
                "context_crop_url": f"/panel/file?path={context_ref}",
                "bbox": bbox_payload,
                "click_point": click_point,
                "padding_px": request.padding_px,
                "context_padding_px": request.context_padding_px,
                "trace_path": trace_path,
                "artifact_is_authorization": False,
                "can_authorize_click": False,
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Interface asset crop failed",
            data=None,
            error=ErrorModel(code="interface_asset_crop_failed", details=str(exc)),
        )


@router.post("/panel/apply_model_profile", response_model=APIResponse)
def apply_panel_model_profile(request: PanelApplyModelProfileRequest) -> APIResponse:
    """Persist a selected browser-panel model profile into the runtime config files."""
    try:
        profiles = load_model_profiles()
        profile = next((item for item in profiles if item.get("profile_id") == request.profile_id), None)
        if not profile:
            raise ValueError(f"Model profile not found: {request.profile_id}")

        vision_config = _load_json(VISION_CONFIG_PATH, {"vision": {}})
        vision = vision_config.setdefault("vision", {})
        vision["mode"] = "local"
        vision["timeout_seconds"] = request.timeout_seconds
        target_key = "local_understanding" if request.stage == "observe" else "local_grounding"
        target = {
            "model_name": str(profile.get("model_name") or Path(str(profile.get("model_path") or "")).name),
            "endpoint": profile.get("endpoint") or None,
        }
        for key in (
            "profile_id",
            "runtime",
            "output_contract",
            "provider_mode",
            "input_format",
            "supports_ocr_anchors",
            "model_path",
        ):
            if key in profile:
                target[key] = profile.get(key)
        vision[target_key] = target
        if request.stage == "locate":
            vision["local"] = dict(target)
        elif "local" not in vision and target_key == "local_grounding":
            vision["local"] = dict(target)
        _save_json(VISION_CONFIG_PATH, vision_config)

        panel_config = _load_json(PANEL_CONFIG_PATH, {})
        panel_config["language"] = request.language
        panel_config["runtime_base_url"] = panel_config.get("runtime_base_url") or "http://127.0.0.1:8000"
        prompts = panel_config.setdefault("prompt_overrides", {})
        if request.observe_prompt is not None:
            prompts["observe_additional_rules"] = request.observe_prompt
        if request.locate_prompt is not None:
            prompts["locate_additional_rules"] = request.locate_prompt
        scripts = panel_config.setdefault("model_scripts", {})
        scripts["start"] = str(profile.get("start_script") or scripts.get("start") or "scripts/model_servers/start_llama_vision_server.ps1")
        scripts["stop"] = str(profile.get("stop_script") or scripts.get("stop") or "scripts/model_servers/stop_local_vision_server.ps1")
        label = str(profile.get("label") or profile.get("profile_id") or request.profile_id)
        if request.stage == "observe":
            panel_config["observe_model_profile"] = label
        else:
            panel_config["locate_model_profile"] = label
        _save_json(PANEL_CONFIG_PATH, panel_config)

        return APIResponse(
            success=True,
            message="Model profile applied",
            data={
                "stage": request.stage,
                "profile": profile,
                "vision_config_path": str(VISION_CONFIG_PATH),
                "panel_config_path": str(PANEL_CONFIG_PATH),
                "vision": vision,
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Model profile apply failed",
            data=None,
            error=ErrorModel(code="panel_apply_model_profile_failed", details=str(exc)),
        )


@router.post("/panel/model_test", response_model=APIResponse)
def panel_model_test(request: PanelModelTestRequest) -> APIResponse:
    """Send a prompt, optionally with an image, to a configured vision model profile."""
    try:
        profile = next((item for item in load_model_profiles() if item.get("profile_id") == request.profile_id), None)
        if not profile:
            raise ValueError(f"Model profile not found: {request.profile_id}")

        messages: list[dict[str, Any]] = [{"role": "user", "content": request.prompt}]
        image_payload = None
        if request.image_path:
            image_path = _resolve_allowed_artifact(request.image_path)
            content_type = _image_content_type(image_path)
            image_payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
            messages[0]["content"] = [
                {"type": "text", "text": request.prompt},
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{image_payload}"}},
            ]

        model_name = str(profile.get("model_name") or Path(str(profile.get("model_path") or "local-model")).name)
        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        endpoint = f"{model_base_url(profile).rstrip('/')}/chat/completions"
        http_request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=600) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
                response_status = response.status
        except urllib.error.HTTPError as exc:
            raw_text = exc.read().decode("utf-8", errors="replace")
            model_io = {
                "contract_version": "model_io_trace_v1",
                "status": "failed",
                "provider": "panel_model_test",
                "model_name": model_name,
                "endpoint": endpoint,
                "attempt_count": 1,
                "attempts": [
                    {
                        "status": "failed",
                        "http_status": exc.code,
                        "model_io": {
                            "contract_version": "model_io_attempt_v1",
                            "input": {
                                "prompt": request.prompt,
                                "image_path": request.image_path,
                                "max_tokens": request.max_tokens,
                                "temperature": request.temperature,
                            },
                            "output": {"raw_text": raw_text, "raw_response": raw_text},
                        },
                    }
                ],
            }
            trace_path = write_trace(
                category="vision",
                operation="panel_model_test",
                payload={"success": False, "request": request.model_dump(), "model_io": model_io, "error": raw_text},
                name_hint=request.profile_id,
            )
            return APIResponse(
                success=False,
                message="Model request failed",
                data={"endpoint": endpoint, "status": exc.code, "raw_response": raw_text, "model_io": model_io, "trace_path": trace_path},
                error=ErrorModel(code="panel_model_test_http_error", details=raw_text[:1000]),
            )

        try:
            raw_json = json.loads(raw_text)
        except json.JSONDecodeError:
            raw_json = None
        content = _extract_chat_content(raw_json) if isinstance(raw_json, dict) else raw_text
        model_io = {
            "contract_version": "model_io_trace_v1",
            "status": "success",
            "provider": "panel_model_test",
            "model_name": model_name,
            "endpoint": endpoint,
            "raw_text": content,
            "raw_response": raw_json if raw_json is not None else raw_text,
            "attempt_count": 1,
            "attempts": [
                {
                    "status": "success",
                    "http_status": response_status,
                    "model_io": {
                        "contract_version": "model_io_attempt_v1",
                        "input": {
                            "prompt": request.prompt,
                            "image_path": request.image_path,
                            "max_tokens": request.max_tokens,
                            "temperature": request.temperature,
                        },
                        "output": {
                            "raw_text": content,
                            "raw_response": raw_json if raw_json is not None else raw_text,
                        },
                    },
                }
            ],
        }
        trace_path = write_trace(
            category="vision",
            operation="panel_model_test",
            payload={"success": True, "request": request.model_dump(), "model_io": model_io},
            name_hint=request.profile_id,
        )
        return APIResponse(
            success=True,
            message="Model response received",
            data={
                "endpoint": endpoint,
                "profile_id": request.profile_id,
                "stage": request.stage,
                "model": model_name,
                "status": response_status,
                "content": content,
                "raw_response": raw_json if raw_json is not None else raw_text,
                "image_attached": image_payload is not None,
                "model_io": model_io,
                "trace_path": trace_path,
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Model test failed",
            data=None,
            error=ErrorModel(code="panel_model_test_failed", details=str(exc)),
        )


PATH_GRAPH_DIR = ROOT_DIR / "artifacts" / "path-graphs"
INTERFACE_MAP_DIR = ROOT_DIR / "artifacts" / "interface-maps"


@router.post("/panel/open_trace_folder", include_in_schema=False)
def open_trace_folder() -> APIResponse:
    """Open the logs/traces folder in Explorer."""
    import os
    import subprocess
    import sys

    folder = ROOT_DIR / "logs" / "traces"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
        return APIResponse(success=True, message=f"Opened {folder}", data={"folder": str(folder)}, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="Could not open folder", data=None, error=ErrorModel(code="folder_open_failed", details=str(exc)))


@router.post("/panel/open_path_folder", include_in_schema=False)
def open_path_folder() -> APIResponse:
    """Open the path-graph save folder in Explorer."""
    import os
    import subprocess
    import sys

    PATH_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(PATH_GRAPH_DIR))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(PATH_GRAPH_DIR)], check=False)
        else:
            subprocess.run(["xdg-open", str(PATH_GRAPH_DIR)], check=False)
        return APIResponse(success=True, message=f"Opened {PATH_GRAPH_DIR}", data={"folder": str(PATH_GRAPH_DIR)}, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="Could not open folder", data=None, error=ErrorModel(code="folder_open_failed", details=str(exc)))


@router.post("/panel/save_path_graph", include_in_schema=False)
def save_path_graph_to_disk(request: dict) -> APIResponse:
    """Persist a path graph JSON to artifacts/path-graphs/ with a custom filename."""
    try:
        PATH_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
        file_name = str(request.get("file_name") or "unnamed_path_graph.json")
        payload = request.get("payload") or request
        safe_name = "".join(c if c.isalnum() or c in "_.-" else "_" for c in file_name)
        if not safe_name.endswith(".json"):
            safe_name += ".json"
        filepath = PATH_GRAPH_DIR / safe_name
        filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return APIResponse(success=True, message=f"Saved to {filepath.name}", data={"path": str(filepath)}, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="Save failed", data=None, error=ErrorModel(code="path_graph_save_failed", details=str(exc)))


@router.post("/panel/save_interface_map", include_in_schema=False)
def save_interface_map_to_disk(request: dict) -> APIResponse:
    try:
        INTERFACE_MAP_DIR.mkdir(parents=True, exist_ok=True)
        file_name = str(request.get("file_name") or "learned_interface_map.json")
        payload = request.get("payload")
        if not isinstance(payload, dict):
            return APIResponse(
                success=False,
                message="Save failed",
                data=None,
                error=ErrorModel(code="invalid_interface_map_payload", details="payload must be an object"),
            )
        safe_name = "".join(c if c.isalnum() or c in "_.-" else "_" for c in file_name)
        if not safe_name.endswith(".json"):
            safe_name += ".json"
        filepath = INTERFACE_MAP_DIR / safe_name
        filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        trace_payload = {
            "contract_version": "learned_interface_map_edit_trace_v1",
            "source_path": request.get("source_path") or "",
            "saved_path": str(filepath.resolve()),
            "edited_at": time.time(),
            "edit_summary": request.get("edit_summary") or {},
            "payload_summary": {
                "contract_version": payload.get("contract_version"),
                "app_id": payload.get("app_id"),
                "region_count": len(payload.get("regions") or []),
                "fixed_visual_asset_count": len(payload.get("fixed_visual_assets") or []),
                "dynamic_area_count": len(payload.get("dynamic_areas") or []),
                "danger_zone_count": len(payload.get("danger_zones") or []),
            },
        }
        trace_path = write_trace(category="panel", operation="save-interface-map", payload=trace_payload, name_hint=safe_name)
        return APIResponse(success=True, message=f"Saved to {filepath.name}", data={"path": str(filepath), "trace_path": trace_path}, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="Save failed", data=None, error=ErrorModel(code="interface_map_save_failed", details=str(exc)))


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_allowed_artifact(path: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = ROOT_DIR / resolved
    resolved = resolved.resolve()
    allowed_roots = [(ROOT_DIR / "artifacts").resolve(), (ROOT_DIR / "logs").resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ValueError("Image path is outside artifacts/logs")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return resolved


def _image_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".bmp":
        return "image/bmp"
    return "image/png"


def _safe_file_stem(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in str(value))
    return safe.strip("._")[:96] or "interface_asset"


def _clip_xywh(x: int, y: int, width: int, height: int, image_width: int, image_height: int) -> tuple[int, int, int, int] | None:
    left = max(0, min(int(x), image_width))
    top = max(0, min(int(y), image_height))
    right = max(0, min(int(x) + int(width), image_width))
    bottom = max(0, min(int(y) + int(height), image_height))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _expand_box(box: tuple[int, int, int, int], image_width: int, image_height: int, padding: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    pad = max(0, int(padding))
    return (
        max(0, left - pad),
        max(0, top - pad),
        min(image_width, right + pad),
        min(image_height, bottom + pad),
    )


def _box_to_xywh(box: tuple[int, int, int, int]) -> dict[str, int]:
    left, top, right, bottom = box
    return {"x": int(left), "y": int(top), "w": int(right - left), "h": int(bottom - top)}


def _extract_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict):
                            text = item.get("text")
                            if isinstance(text, str):
                                parts.append(text)
                    if parts:
                        return "\n".join(parts)
            text = first.get("text")
            if isinstance(text, str):
                return text
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _ocr_count(ocr: Any) -> int:
    if not isinstance(ocr, dict):
        return 0
    metadata = ocr.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("match_count"), int):
        return int(metadata["match_count"])
    matches = ocr.get("matches")
    if isinstance(matches, list):
        return len(matches)
    return 0


def _gate_reason_text(pre_click: Any) -> str:
    if not isinstance(pre_click, dict):
        return ""
    parts: list[str] = []
    if pre_click.get("reason"):
        parts.append(str(pre_click["reason"]))
    reasons = pre_click.get("reasons")
    if isinstance(reasons, list) and reasons:
        parts.append("reasons: " + ", ".join(str(item) for item in reasons[:6]))
    summary = pre_click.get("summary")
    if isinstance(summary, dict):
        summary_bits = []
        for key in ("candidate_count", "allowed_candidate_count", "top_margin_ok", "margin_to_second"):
            if key in summary:
                summary_bits.append(f"{key}={summary[key]}")
        if summary_bits:
            parts.append("summary: " + ", ".join(summary_bits))
    decisions = pre_click.get("candidate_decisions")
    if isinstance(decisions, list):
        for decision in decisions[:3]:
            if not isinstance(decision, dict):
                continue
            decision_reasons = decision.get("reasons")
            reason_text = ", ".join(str(item) for item in decision_reasons[:6]) if isinstance(decision_reasons, list) else ""
            candidate_id = decision.get("candidate_id") or decision.get("element_id") or "candidate"
            allowed = decision.get("allowed")
            click_point = decision.get("click_point")
            parts.append(f"{candidate_id}: allowed={allowed}, click_point={click_point}, reasons={reason_text}")
    return " | ".join(part for part in parts if part)[:1200]


def _trace_flow_stages(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    sections = parsed.get("sections") if isinstance(parsed.get("sections"), dict) else {}

    def add(stage_id: str, label: str, value: str = "", status: str = "done") -> dict[str, Any] | None:
        raw = sections.get(stage_id)
        if not _meaningful_trace_section(raw):
            return None
        return {
            "id": stage_id,
            "label": label,
            "value": value,
            "status": status,
            "summary": _stage_summary(stage_id, parsed),
            "raw": raw,
        }

    stages = [
        add("goal", "Request", str(parsed.get("goal") or parsed.get("contract") or "")),
        add("capture", "Capture", str(parsed.get("app_name") or "image")),
        add("overlay", "Overlay", _overlay_label(sections.get("overlay"))),
        add("ocr", "OCR", f"{parsed.get('ocr_count') or 0} anchors"),
        add("vision", "Vision", str(parsed.get("model_provider") or parsed.get("provider") or "")),
        add("model_io", "Model IO", _model_io_label(sections.get("model_io")), "done" if parsed.get("model_io_status") != "failed" else "error"),
        add("screen", "Screen", str(parsed.get("state_guess") or "")),
        add("screen_inventory", "Inventory", _screen_inventory_label(sections.get("screen_inventory"))),
        add("path_map", "Path Map", _path_map_label(sections.get("path_map"))),
        add("path_deep", "Path Deep", _path_deep_label(sections.get("path_deep"))),
        add("path_recall", "Path Recall", _path_recall_label(sections.get("path_recall"))),
        add("visual_asset_recall", "Visual Assets", _visual_asset_recall_label(sections.get("visual_asset_recall"))),
        add("path_review", "Path Review", _path_review_label(sections.get("path_review"))),
        add("candidates", "Candidates", f"{parsed.get('candidates') or 0} returned"),
        add("coordinate_preview", "Coordinate Preview", _coordinate_preview_label(sections.get("coordinate_preview"))),
        add(
            "gate",
            "Gate",
            "ALLOW" if parsed.get("gate_allowed") is True else "BLOCK" if parsed.get("gate_allowed") is False else "",
            "done" if parsed.get("gate_allowed") is True else "blocked" if parsed.get("gate_allowed") is False else "done",
        ),
        add("target", "Target", _point_label(parsed.get("selected_point"))) if parsed.get("selected_point") else None,
        add("agent_guidance", "Agent Guidance", _agent_guidance_label(sections.get("agent_guidance"))),
        add("click", "Action", "executed" if parsed.get("action_executed") else "dry-run"),
        add("memory", "Memory", _memory_label(sections.get("memory"))),
        add(
            "verify",
            "Verify",
            "PASS" if parsed.get("verified") is True else "FAIL" if parsed.get("verified") is False else "",
            "done" if parsed.get("verified") is not False else "error",
        ),
        add("fallback", "Fallback", _fallback_label(sections.get("fallback")), "blocked"),
        add("error", "Error", f"{len(parsed.get('errors') or [])} error(s)", "error"),
        add("timings", "Timings", str(parsed.get("total_time") or "")),
    ]
    return [stage for stage in stages if stage is not None]


def _layer_flow_stages(layers: list[Any]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            continue
        layer_name = str(layer.get("layer") or f"layer_{index + 1}")
        status = "done" if layer.get("ok") is not False else "error"
        summary = layer.get("summary")
        value = _compact_value(summary) or ("ok" if status == "done" else "error")
        stages.append(
            {
                "id": f"layer_{index + 1}",
                "label": layer_name,
                "value": value,
                "status": status,
                "summary": json.dumps(summary, ensure_ascii=False, indent=2) if isinstance(summary, dict) else str(summary or ""),
                "raw": layer,
            }
        )
    return stages


def _meaningful_trace_section(raw: Any) -> bool:
    if raw in (None, {}, []):
        return False
    if isinstance(raw, dict):
        if any(key in raw for key in ("allowed", "ok", "verified", "success")):
            return True
        return any(value not in (None, "", [], {}, False) for value in raw.values())
    return True


def _first_dict(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _overlay_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    count = raw.get("candidate_count")
    decision_count = raw.get("decision_count")
    parts = []
    if count is not None:
        parts.append(f"{count} candidates")
    if decision_count is not None:
        parts.append(f"{decision_count} decisions")
    return ", ".join(parts)


def _path_map_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    count = summary.get("candidate_count")
    if count is None and isinstance(raw.get("candidates"), list):
        count = len(raw["candidates"])
    state_id = raw.get("state_id")
    parts = []
    if count is not None:
        parts.append(f"{count} candidates")
    if state_id:
        parts.append(str(state_id))
    return ", ".join(parts)


def _screen_inventory_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    action_count = summary.get("available_action_count")
    if action_count is None and isinstance(raw.get("available_actions"), list):
        action_count = len(raw["available_actions"])
    page_count = summary.get("page_element_count")
    if page_count is None and isinstance(raw.get("page_elements"), list):
        page_count = len(raw["page_elements"])
    card_count = summary.get("card_count")
    if card_count is None and isinstance(raw.get("cards"), list):
        card_count = len(raw["cards"])
    parts = []
    if action_count is not None:
        parts.append(f"{action_count} actions")
    if page_count is not None:
        parts.append(f"{page_count} text")
    if card_count is not None:
        parts.append(f"{card_count} cards")
    return ", ".join(parts)


def _model_io_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    status = str(raw.get("status") or "")
    attempts = raw.get("attempt_count")
    if attempts is None and isinstance(raw.get("attempts"), list):
        attempts = len(raw["attempts"])
    provider = str(raw.get("provider") or raw.get("model_name") or "")
    parts = []
    if status:
        parts.append(status)
    if attempts is not None:
        parts.append(f"{attempts} attempt(s)")
    if provider:
        parts.append(provider)
    return ", ".join(parts)


def _path_recall_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    count = summary.get("recalled_count")
    if count is None and isinstance(raw.get("candidates"), list):
        count = len(raw["candidates"])
    state_match = raw.get("state_match") if isinstance(raw.get("state_match"), dict) else {}
    parts = []
    if count is not None:
        parts.append(f"{count} recalled")
    if state_match.get("state_id"):
        parts.append(str(state_match["state_id"]))
    return ", ".join(parts)


def _visual_asset_recall_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    status = str(raw.get("status") or "")
    matched = raw.get("matched_count")
    if matched is None and isinstance(raw.get("matches"), list):
        matched = len([item for item in raw["matches"] if isinstance(item, dict) and item.get("matched")])
    fast_lane = raw.get("fast_lane_allowed")
    selected = raw.get("selected_asset_id") or raw.get("selected_candidate_id")
    parts = []
    if status:
        parts.append(status)
    if matched is not None:
        parts.append(f"{matched} matched")
    if fast_lane is not None:
        parts.append("fast lane" if fast_lane else "gate only")
    if selected:
        parts.append(str(selected)[:32])
    return ", ".join(parts)


def _path_deep_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    additions = summary.get("missing_text_addition_count")
    removals = summary.get("duplicate_count")
    if additions is None:
        delta = raw.get("path_graph_delta") if isinstance(raw.get("path_graph_delta"), dict) else {}
        additions = len(delta.get("additions") or []) if isinstance(delta.get("additions"), list) else 0
    if removals is None:
        delta = raw.get("path_graph_delta") if isinstance(raw.get("path_graph_delta"), dict) else {}
        removals = len(delta.get("removals") or []) if isinstance(delta.get("removals"), list) else 0
    return f"+{additions} / -{removals}"


def _path_review_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    additions = summary.get("addition_count")
    removals = summary.get("removal_count")
    if additions is None:
        additions = len(raw.get("additions") or []) if isinstance(raw.get("additions"), list) else 0
    if removals is None:
        removals = len(raw.get("removals") or []) if isinstance(raw.get("removals"), list) else 0
    return f"+{additions} / -{removals}"


def _coordinate_preview_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    count = raw.get("candidate_count")
    decisions = raw.get("decision_count")
    selected = raw.get("selected_candidate_id")
    parts = []
    if count is not None:
        parts.append(f"{count} candidates")
    if decisions is not None:
        parts.append(f"{decisions} decisions")
    if selected:
        parts.append(str(selected)[:24])
    return ", ".join(parts)


def _agent_guidance_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    return ", ".join(str(item) for item in [raw.get("status"), raw.get("next_action")] if item)


def _memory_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    status = str(raw.get("status") or "")
    transition_id = str(raw.get("transition_id") or "")
    return ", ".join(part for part in [status, transition_id[:12]] if part)


def _fallback_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    steps = raw.get("steps") if isinstance(raw.get("steps"), list) else []
    reason = str(raw.get("failure_reason") or "")
    parts = []
    if reason:
        parts.append(reason)
    parts.append(f"{len(steps)} step(s)")
    return ", ".join(parts)


def _compact_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ["contract_version", "provider", "region_count", "element_count", "text_count", "status"]:
            if key in value:
                return f"{key}: {value[key]}"
        return f"{len(value)} fields"
    if isinstance(value, list):
        return f"{len(value)} items"
    return str(value or "")


def _stage_summary(stage_id: str, parsed: dict[str, Any]) -> str:
    if stage_id == "goal":
        return str(parsed.get("goal") or parsed.get("state_hint") or parsed.get("contract") or "")
    if stage_id == "ocr":
        return f"OCR anchors: {parsed.get('ocr_count') or 0}"
    if stage_id == "vision":
        return str(parsed.get("screen_summary") or parsed.get("model_provider") or "")
    if stage_id == "model_io":
        status = parsed.get("model_io_status") or ""
        attempts = parsed.get("model_io_attempt_count") or 0
        return f"Model IO {status}: {attempts} attempt(s) with full input prompt and raw model output in raw JSON.".strip()
    if stage_id == "screen":
        return str(parsed.get("screen_summary") or parsed.get("state_guess") or "")
    if stage_id == "screen_inventory":
        actions = parsed.get("screen_inventory_action_count") or 0
        page_elements = parsed.get("screen_inventory_page_element_count") or 0
        cards = parsed.get("screen_inventory_card_count") or 0
        coverage = parsed.get("screen_inventory_coordinate_coverage")
        coverage_text = f"; coordinate coverage: {coverage:.2f}" if isinstance(coverage, (int, float)) else ""
        return f"Screen inventory: {actions} action(s), {page_elements} page element(s), {cards} card(s){coverage_text}"
    if stage_id == "path_map":
        count = parsed.get("path_map_count") or 0
        state_id = parsed.get("path_map_state_id") or ""
        summary = parsed.get("path_map_summary") or ""
        prefix = f"Path map candidates: {count}"
        if state_id:
            prefix += f"; state: {state_id}"
        return f"{prefix}\n{summary}".strip()
    if stage_id == "path_recall":
        count = parsed.get("path_graph_recall_count") or 0
        status = parsed.get("path_graph_recall_status") or ""
        state_id = parsed.get("path_graph_recall_state") or ""
        suffix = f"; state: {state_id}" if state_id else ""
        return f"Path recall {status}: {count} candidate(s){suffix}".strip()
    if stage_id == "visual_asset_recall":
        status = parsed.get("visual_asset_recall_status") or ""
        matched = parsed.get("visual_asset_matched_count") or 0
        fast_lane = parsed.get("visual_asset_fast_lane_used")
        lane = "; fast lane" if fast_lane else ""
        return f"Visual asset recall {status}: {matched} matched asset(s){lane}".strip()
    if stage_id == "path_deep":
        status = parsed.get("path_graph_deep_status") or ""
        output_count = parsed.get("path_graph_deep_output_count") or 0
        additions = parsed.get("path_graph_deep_additions") or 0
        removals = parsed.get("path_graph_deep_removals") or 0
        return f"Path deep {status}: {output_count} candidate(s), +{additions}, -{removals}".strip()
    if stage_id == "path_review":
        additions = parsed.get("path_map_review_additions") or 0
        removals = parsed.get("path_map_review_removals") or 0
        status = parsed.get("path_map_review_status") or ""
        return f"Path review {status}: +{additions}, -{removals}".strip()
    if stage_id == "coordinate_preview":
        path = parsed.get("coordinate_preview_output_path") or ""
        count = parsed.get("coordinate_preview_candidate_count")
        decisions = parsed.get("coordinate_preview_decision_count")
        return f"Pre-rendered coordinate overlay: {count} candidate(s), {decisions} decision(s). {path}".strip()
    if stage_id == "candidates":
        return f"Candidates returned: {parsed.get('candidates') or 0}; recommendation: {bool(parsed.get('has_recommendation'))}"
    if stage_id == "gate":
        return str(parsed.get("gate_reason") or "")
    if stage_id == "target":
        return _point_label(parsed.get("selected_point"))
    if stage_id == "agent_guidance":
        return f"{parsed.get('agent_guidance_status') or ''}: {parsed.get('agent_guidance_next_action') or ''}".strip()
    if stage_id == "click":
        return "Action executed" if parsed.get("action_executed") else "Dry run or not executed"
    if stage_id == "memory":
        status = parsed.get("memory_status") or ""
        transition_id = parsed.get("memory_transition_id") or ""
        return f"ElementMemory writeback {status}: {transition_id}".strip()
    if stage_id == "verify":
        return str(parsed.get("verification_detail") or "")
    if stage_id == "fallback":
        reason = parsed.get("fallback_reason") or ""
        count = parsed.get("fallback_step_count") or 0
        return f"Fallback planned for {reason}: {count} step(s)".strip()
    if stage_id == "error":
        return "\n".join(parsed.get("errors") or [])
    return ""


def _point_label(point: Any) -> str:
    if not isinstance(point, dict):
        return ""
    x = point.get("x")
    y = point.get("y")
    if x is None or y is None:
        return ""
    return f"({round(float(x))}, {round(float(y))})"
