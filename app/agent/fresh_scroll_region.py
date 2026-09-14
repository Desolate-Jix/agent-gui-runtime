"""新学习滚动复用已有参数、窗口身份与空间变化验证，不派发输入。"""
from copy import deepcopy

from app.agent.scroll_parameters import ReviewedScrollParameters, ScrollDispatchParameters
from app.gate.scroll_evidence import measure_scroll_spatial_evidence


def current_scroll_container(controls, point, *, axis="vertical", target_container_id=None):
    from app.gate.fresh_action_risk import _bbox, _contains, _normalized, _actionable, _ancestor_chain

    if axis not in {"vertical", "horizontal"}:
        raise ValueError("scroll axis is invalid")
    if (not isinstance(controls, list) or not isinstance(point, dict) or set(point) != {"x", "y"}
            or any(type(v) is not int for v in point.values())):
        raise ValueError("scroll UIA or point is invalid")
    ids = [c.get("control_id") for c in controls if isinstance(c, dict)]
    if len(ids) != len(controls) or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("scroll container identities are ambiguous")
    index = dict(zip(ids, controls))

    matches = []
    for control in controls:
        if not isinstance(control, dict):
            raise ValueError("scroll UIA control is invalid")
        if control.get("visible") is False:
            continue
        bbox = _bbox(control.get("bbox"), "scroll control bbox")
        if not _contains(bbox, point):
            continue
        patterns = control.get("patterns", [])
        scrollable = isinstance(patterns, (list, tuple)) and any(_normalized(p) in {"scroll", "scrollpattern"} for p in patterns)
        kind = _normalized(control.get("control_type"))
        container_kind = kind in {"pane", "document", "group", "list", "datagrid", "tree"}
        # 无交互图片/文字可以是容器背景；滚轮不会点击它们，不能据此判定输入遮挡。
        if (not container_kind and (_actionable(control) or kind in {"edit", "spinner", "slider", "combobox"})):
            raise ValueError("scroll point overlaps a non-container input control")
        if not scrollable or not container_kind:
            continue
        if "scroll_axes" in control:
            axes = control["scroll_axes"]
            if not isinstance(axes, dict) or set(axes) != {"current_vertical", "current_horizontal"}:
                raise ValueError("scroll axis evidence is invalid")
            value = axes["current_" + axis]
            if value is False:
                continue
            if value is not True:
                raise ValueError("scroll axis evidence is unavailable")
        if control.get("enabled") is not True or control.get("visible") is not True:
            raise ValueError("scroll container state is unavailable")
        matches.append(control)

    def confirmed_ancestor(parent, child):
        chain = _ancestor_chain(child)
        if not chain or child["control_id"] in chain or parent["control_id"] not in chain:
            return False
        for offset, ident in enumerate(chain):
            if ident not in index or _ancestor_chain(index[ident]) != chain[offset + 1:]:
                return False
        outer, inner = parent["bbox"], child["bbox"]
        return (outer["x"] <= inner["x"] and outer["y"] <= inner["y"]
            and inner["x"] + inner["w"] <= outer["x"] + outer["w"]
            and inner["y"] + inner["h"] <= outer["y"] + outer["h"])

    deepest = [c for c in matches if not any(c is not other and confirmed_ancestor(c, other) for other in matches)]
    if (len(deepest) != 1 or (target_container_id is not None and deepest[0]["control_id"] != target_container_id)):
        raise ValueError("scroll container is missing or ambiguous")
    return deepcopy(deepest[0])


def fresh_scroll_dispatch(intent, risk, evidence):
    parameters = ReviewedScrollParameters.from_payload(intent.scroll_parameters)
    target = risk["scroll_target"]
    axes = target.get("scroll_axes")
    if axes is not None and axes.get("current_" + parameters.axis) is not True:
        raise ValueError("requested scroll axis is not currently scrollable")
    projected = (evidence.get("recognition") or {}).get("result") or {}
    for candidate in (projected.get("candidate_result") or {}).get("candidates", []):
        if candidate.get("candidate_id") != risk["candidate_id"]:
            continue
        binding = ((candidate.get("element") or {}).get("evidence") or {}).get("current_scroll_container_binding")
        if isinstance(binding, dict) and binding.get("scroll_parameters") != parameters.to_payload():
            raise ValueError("scroll parameters differ from current grounded request")
    # 未关联记忆时引用当前 UIA 容器；记忆关联使用确切版本区域 ID，几何仍来自当前容器。
    expected = intent.learned_control["region"]["region_id"] if intent.learned_control is not None else target["control_id"]
    if parameters.target_container_id != expected:
        raise ValueError("scroll parameters reference a different target container")
    box, viewport = target["bbox"], evidence["capture"]["viewport_size"]
    return ScrollDispatchParameters(parameters,
        tuple(box[k] for k in ("x", "y", "w", "h")), tuple(viewport[k] for k in ("width", "height")))


def read_fresh_scroll_capture(owner, archive, packet, scope):
    from app.agent.fresh_learning_observation import _bound_rect, _public_application
    from app.agent.native_identity import validate_native_identity_fact

    data = packet.evidence()
    capture, target, application = data["capture"], data["target"], data["application"]
    bound = owner._window_manager.get_bound_window()
    if (bound is None or bound.handle != target["window_handle"] or bound.process_id != target["process_id"]
            or _bound_rect(bound) != target["rect"]):
        raise ValueError("scroll capture window binding changed")
    fact = validate_native_identity_fact(owner._native_identity_reader.read_identity(target["window_handle"]),
        target_window_handle=target["window_handle"], expected_process_id=target["process_id"])
    if fact is None:
        raise ValueError("scroll capture native process identity is unavailable")
    if application["kind"] == "native" and (
            fact["executable_path"] != application["executable_path"]
            or fact["process_create_time"] != application["process_create_time"]):
        raise ValueError("scroll capture native identity differs from observation")
    if _public_application(owner.application, owner._read_application_fact(target["window_handle"], target["process_id"])) != application:
        raise ValueError("scroll capture application changed")
    reference = archive.record(packet, **scope)
    archive.read(reference, **scope)
    return {"contract_version": "scroll_capture_snapshot_v1", "captured": True, "capture_status": "observed",
        "capture_id": capture["capture_id"], "capture_clock_id": capture["capture_clock_id"],
        "capture_started_ns": capture["capture_started_ns"], "captured_at_ns": capture["captured_at_ns"],
        "roi": None, "window_handle": target["window_handle"], "window_rect": deepcopy(target["rect"]),
        "native_identity": fact, "viewport_size": deepcopy(capture["viewport_size"]),
        "image_path": str(archive.png_root / (capture["screenshot_sha256"] + ".png")),
        "image_sha256": capture["screenshot_sha256"]}


def fresh_scroll_proof(parameters, target_bbox, before, after):
    return {"contract_version": "fresh_scroll_verification_v1", "scroll_parameters": parameters.to_payload(),
        "target_bbox": dict(zip(("x", "y", "width", "height"), target_bbox)),
        "before": deepcopy(before), "after": deepcopy(after),
        "spatial": measure_scroll_spatial_evidence(before=before, after=after,
            target_bbox=dict(zip(("x", "y", "width", "height"), target_bbox)),
            target_container_id=parameters.target_container_id)}


def validate_fresh_scroll_proof(value):
    if not isinstance(value, dict) or set(value) != {"contract_version", "scroll_parameters", "target_bbox", "before", "after", "spatial"} or value["contract_version"] != "fresh_scroll_verification_v1":
        raise ValueError("fresh scroll proof is invalid")
    parameters = ReviewedScrollParameters.from_payload(value["scroll_parameters"])
    box = value["target_bbox"]
    if not isinstance(box, dict) or set(box) != {"x", "y", "width", "height"}:
        raise ValueError("fresh scroll proof geometry is invalid")
    expected = fresh_scroll_proof(parameters, tuple(box[k] for k in ("x", "y", "width", "height")), value["before"], value["after"])
    if value != expected:
        raise ValueError("fresh scroll proof differs from actual spatial evidence")
    return deepcopy(value)
