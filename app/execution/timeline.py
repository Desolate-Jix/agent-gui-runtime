"""汇总同一时钟的执行区间；不派发动作，不从查询或交接推断动作与推理耗时。"""
from __future__ import annotations


_LAYERS = frozenset({"startup", "caller", "vision", "uia", "capture", "input", "wait",
    "decision", "cleanup", "handoff", "unknown"})
_KINDS = frozenset({"span", "action", "handoff", "query"})


def summarize_execution_timeline(events: list[dict]) -> dict:
    """读取 layer/started_ns/ended_ns，以及可选 kind、clock_id；不修改原事件。

    kind=action 是动作包围区间，query 仅记录查询自身，handoff 始终独列。
    HTTP、服务端和服务计时均可标为 decision，同层嵌套按并集计时。
    缺少动作包围区间时只报告已观察区间，action_total_ms 保持未知。
    """
    if type(events) is not list:
        raise TypeError("execution timeline events must be a list")
    spans = []
    unknown = []
    for index, event in enumerate(events):
        if type(event) is not dict:
            unknown.append({"event_index": index, "reason": "invalid_event"})
            continue
        kind = event.get("kind", "span")
        if type(kind) is not str or kind not in _KINDS:
            unknown.append({"event_index": index, "reason": "invalid_kind"})
            continue
        if "started_ns" not in event or "ended_ns" not in event:
            unknown.append({"event_index": index, "reason": "missing_timestamps"})
            continue
        start, end = event["started_ns"], event["ended_ns"]
        if (type(start) is not int or type(end) is not int
                or not 0 <= start <= end < 2 ** 63):
            unknown.append({"event_index": index, "reason": "invalid_timestamps"})
            continue
        clock = event.get("clock_id", "monotonic")
        if type(clock) is not str or not clock or len(clock) > 64:
            unknown.append({"event_index": index, "reason": "invalid_clock"})
            continue
        if kind in {"handoff", "query"}:
            layer = kind
        else:
            layer = event.get("layer", "unknown")
            if type(layer) is not str or layer not in _LAYERS:
                layer = "unknown"
                unknown.append({"event_index": index, "reason": "unknown_layer"})
        spans.append({"event_index": index, "kind": kind, "layer": layer, "clock_id": clock,
            "started_ns": start, "ended_ns": end, "elapsed_ms": (end - start) / 1_000_000})

    actions = [item for item in spans if item["kind"] == "action"]
    envelopes = {(item["clock_id"], item["started_ns"], item["ended_ns"]) for item in actions}
    action = next(iter(envelopes)) if len(envelopes) == 1 else None
    if len(envelopes) > 1:
        unknown.extend({"event_index": item["event_index"], "reason": "ambiguous_action_envelopes"}
            for item in actions)
    measured = [item for item in spans if item["kind"] not in {"query", "action"}]
    clocks = {item["clock_id"] for item in measured}
    clock = action[0] if action else next(iter(clocks)) if len(clocks) == 1 else None
    included = []
    for item in measured:
        if clock is None or item["clock_id"] != clock:
            unknown.append({"event_index": item["event_index"], "reason": "incomparable_clock"})
        else:
            included.append(item)
    if action:
        bounds = action[1:]
    elif included:
        bounds = (min(item["started_ns"] for item in included), max(item["ended_ns"] for item in included))
    else:
        bounds = None

    nested = []
    for index, first in enumerate(included):
        for second in included[index + 1:]:
            if first["started_ns"] == second["started_ns"] and first["ended_ns"] == second["ended_ns"]:
                nested.append({"relation": "coincident", "event_indices": [first["event_index"], second["event_index"]]})
            else:
                for outer, inner in ((first, second), (second, first)):
                    if outer["started_ns"] <= inner["started_ns"] and inner["ended_ns"] <= outer["ended_ns"]:
                        nested.append({"relation": "nested", "outer_event_index": outer["event_index"],
                            "inner_event_index": inner["event_index"]})
                        break

    disjoint = []
    layer_ns = {}
    unknown_ns = overlap_ns = measured_ns = unmeasured_ns = 0
    if bounds is not None:
        start, end = bounds
        clipped = []
        for item in included:
            if action and (item["started_ns"] < start or item["ended_ns"] > end):
                unknown.append({"event_index": item["event_index"], "reason": "outside_action_envelope"})
            left, right = max(start, item["started_ns"]), min(end, item["ended_ns"])
            if left < right:
                clipped.append((left, right, item))
        edges = sorted({start, end, *(left for left, _, _ in clipped), *(right for _, right, _ in clipped)})
        for left, right in zip(edges, edges[1:]):
            active = [item for begin, finish, item in clipped if begin <= left and right <= finish]
            layers = sorted({item["layer"] for item in active})
            layer = layers[0] if len(layers) == 1 else "overlap" if layers else "unknown"
            elapsed = right - left
            if active:
                measured_ns += elapsed
            else:
                unmeasured_ns += elapsed
            if layer == "unknown":
                unknown_ns += elapsed
            elif layer == "overlap":
                overlap_ns += elapsed
            else:
                layer_ns[layer] = layer_ns.get(layer, 0) + elapsed
            disjoint.append({"started_ns": left, "ended_ns": right, "elapsed_ms": elapsed / 1_000_000,
                "layer": layer, "layers": layers, "event_indices": [item["event_index"] for item in active]})

    # 所有累计都先保留整数纳秒，包含关系和交叉重叠不重复相加。
    total = (action[2] - action[1]) / 1_000_000 if action else None
    return {"contract_version": "execution_timeline.v1",
        "status": "complete" if action and not unknown and not unknown_ns and not overlap_ns else "partial",
        "scope": "action_envelope" if action else "observed_spans_only", "clock_id": clock,
        "action_total_ms": total,
        "observed_range_ms": (bounds[1] - bounds[0]) / 1_000_000 if bounds is not None else None,
        "measured_span_union_ms": measured_ns / 1_000_000 if bounds is not None else None,
        "layers_ms": {layer: elapsed / 1_000_000 for layer, elapsed in sorted(layer_ns.items())},
        "unknown_ms": unknown_ns / 1_000_000 if bounds is not None else None,
        "unmeasured_ms": unmeasured_ns / 1_000_000 if bounds is not None else None,
        "overlap_ms": overlap_ns / 1_000_000 if bounds is not None else None,
        "nested_timings_additive": False, "handoff_is_pure_inference": False,
        "query_included_in_action_duration": False,
        "spans": spans, "disjoint_spans": disjoint, "nested_events": nested, "unknown_events": unknown}
