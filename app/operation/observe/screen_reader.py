from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PIL import Image

from app.core.ocr_service import ocr_service
from app.core.runtime_artifacts import write_trace
from app.operation.observe.contracts import (
    ObserveScreenReadRequest,
    ObserveScreenReadResult,
)
from app.operation.page_structure import build_page_structure
from app.operation.screen_reading import build_screen_reading
from app.operation.screen_reading.uia_provider import uia_provider
from app.vision.factory import VisionProviderFactory
from app.vision.model_io import (
    attach_model_io,
    model_io_failure_payload,
)
from app.vision.normalizer import normalizer
from app.vision.ocr_region_refiner import (
    parse_ocr_region_refine_options,
    refine_vision_regions_with_ocr,
)
from app.vision.schemas import ImageSize, VisionAnalyzeRequest

TraceWriter = Callable[..., str]


def _trace_enabled(request: ObserveScreenReadRequest) -> bool:
    return request.write_policy.trace is not False


def _execution_path(
    *,
    requested_mode: str | None,
    response_provider: str | None,
    raw_response: dict[str, Any] | None,
    ocr_region_refine_used: bool,
) -> dict[str, Any]:
    raw = raw_response or {}
    return {
        "vision_provider_requested": requested_mode,
        "vision_provider_used": response_provider,
        "vision_model_used": bool(response_provider) and raw.get("mode") != "stub",
        "page_structure_used": True,
        "ocr_region_refine_used": bool(ocr_region_refine_used),
        "coordinate_source": "page_structure_v1.click_point",
    }


def read_screen(
    request: ObserveScreenReadRequest,
    *,
    provider_factory: Any = VisionProviderFactory,
    trace_writer: TraceWriter = write_trace,
    managed_model_lease: dict[str, Any] | None = None,
    cancellation_event: Any | None = None,
) -> ObserveScreenReadResult:
    image_path = Path(request.image_path)
    if not image_path.exists():
        return ObserveScreenReadResult(
            success=False,
            message="Image path not found",
            error={
                "code": "image_not_found",
                "details": str(image_path),
            },
        )

    try:
        config = provider_factory.load_config()
        provider = provider_factory.create(
            mode=request.provider_mode,
            config=config,
        )
        if managed_model_lease is not None:
            binder = getattr(provider, "bind_managed_model_lease", None)
            if not callable(binder):
                raise RuntimeError("managed observation provider cannot bind exact Qwen lease")
            binder(managed_model_lease)
        analyze_request = VisionAnalyzeRequest(
            image_path=str(image_path),
            task=request.task,
            app_name=request.app_name,
            goal=request.goal,
            state_hint=request.state_hint,
            provider_mode=request.provider_mode,
            metadata=request.metadata,
        )

        def _analyze_attested() -> object:
            from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
                attest_managed_model_dispatch,
                current_benchmark_dispatch_context,
            )

            dispatch_context = current_benchmark_dispatch_context()
            if dispatch_context is not None:
                if managed_model_lease is None:
                    raise ValueError(
                        "benchmark incumbent Qwen dispatch requires the exact managed lease"
                    )
                attest_managed_model_dispatch(
                    model_lease=managed_model_lease,
                    dispatch_context=dispatch_context,
                )
            return provider.analyze(analyze_request)

        if cancellation_event is not None and hasattr(
            cancellation_event, "run_if_not_cancelled"
        ):
            allowed, response = cancellation_event.run_if_not_cancelled(
                "incumbent_qwen_provider_dispatch",
                _analyze_attested,
            )
            if not allowed:
                raise RuntimeError("incumbent Qwen observation cancelled")
        else:
            if cancellation_event is not None and cancellation_event.is_set():
                raise RuntimeError("incumbent Qwen observation cancelled")
            response = _analyze_attested()
        refine_options = parse_ocr_region_refine_options(request.metadata)
        ocr_result = None
        if refine_options.enabled:
            ocr_result = ocr_service.scan_image(str(image_path))
            response = refine_vision_regions_with_ocr(
                response,
                ocr_result,
                options=refine_options,
            )
        normalized = normalizer.normalize(
            response.to_dict(),
            response.provider,
        )
        if normalized.image_size is None:
            with Image.open(image_path) as image:
                normalized.image_size = ImageSize(
                    width=image.width,
                    height=image.height,
                )
        if ocr_result is None:
            ocr_result = ocr_service.scan_image(str(image_path))
        structure = build_page_structure(normalized, ocr_result)
        uia_snapshot = uia_provider.snapshot_bound_window()
        payload = build_screen_reading(
            image_path=str(image_path),
            vision=normalized,
            ocr=ocr_result,
            page_structure=structure,
            app_name=request.app_name,
            uia_snapshot=uia_snapshot,
        )
        attach_model_io(payload, response)
        payload["execution_path"] = {
            **_execution_path(
                requested_mode=request.provider_mode
                or str((config.get("vision") or {}).get("mode") or "local"),
                response_provider=response.provider,
                raw_response=response.raw_response,
                ocr_region_refine_used=refine_options.enabled,
            ),
            "screen_reading_used": True,
            "ui_provider_slots_available": True,
            "uia_provider_connected": True,
            "uia_scan_status": uia_snapshot.get("status"),
        }
        if _trace_enabled(request):
            payload["trace_path"] = trace_writer(
                category="vision",
                operation="screen_reading",
                payload={
                    "success": True,
                    "request": request.model_dump(mode="json"),
                    "result": payload,
                },
                name_hint=request.app_name or image_path.stem,
            )
        return ObserveScreenReadResult(
            success=True,
            message="Screen reading completed",
            payload=payload,
            model_io=(
                payload.get("model_io")
                if isinstance(payload.get("model_io"), dict)
                else None
            ),
        )
    except Exception as exc:
        model_io = model_io_failure_payload(exc)
        trace_path = None
        if _trace_enabled(request):
            failure_payload: dict[str, Any] = {
                "success": False,
                "request": request.model_dump(mode="json"),
                "error": str(exc),
            }
            if model_io is not None:
                failure_payload["model_io"] = model_io
            trace_path = trace_writer(
                category="vision",
                operation="screen_reading",
                payload=failure_payload,
                name_hint=request.app_name or image_path.stem,
            )
        return ObserveScreenReadResult(
            success=False,
            message="Screen reading failed",
            payload={"trace_path": trace_path} if trace_path else None,
            error={
                "code": "screen_reading_failed",
                "details": str(exc),
            },
            model_io=model_io,
        )
