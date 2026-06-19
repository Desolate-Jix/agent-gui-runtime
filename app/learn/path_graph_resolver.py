from __future__ import annotations

from typing import Any


PATH_GRAPH_RESOLUTION_CONTRACT = "path_graph_resolution_v1"


def resolve_runtime_path_graph(
    runtime_path_graph: dict[str, Any] | None,
    *,
    screen_inventory: dict[str, Any] | None = None,
    scroll_containers: dict[str, Any] | list[dict[str, Any]] | None = None,
    requested_state_id: str | None = None,
    safety: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Conservatively decide whether a runtime path graph may guide the current page."""

    graph = runtime_path_graph if isinstance(runtime_path_graph, dict) else {}
    safety_payload = safety if isinstance(safety, dict) else {}
    reject_reasons: list[str] = []
    evidence: list[str] = []
    if graph.get("contract_version") != "runtime_path_graph_v1":
        reject_reasons.append("invalid_runtime_path_graph_contract")

    container_ids = _container_ids(graph, scroll_containers)
    required_regions = set(_list(_dict(graph.get("state_match_policy")).get("required_regions")))
    graph_region_ids = {str(item.get("region_id") or "") for item in graph.get("regions") or [] if isinstance(item, dict)}
    missing_regions = sorted(item for item in required_regions if item and item not in graph_region_ids)
    if missing_regions:
        reject_reasons.append("missing_required_graph_regions:" + ",".join(missing_regions))
    else:
        if "results_list" in graph_region_ids:
            evidence.append("results_list_region_found")
        if "job_detail" in graph_region_ids:
            evidence.append("job_detail_region_found")

    required_container_ids = _required_container_ids(graph)
    missing_containers = sorted(item for item in required_container_ids if item not in container_ids)
    if missing_containers:
        reject_reasons.append("missing_scroll_containers:" + ",".join(missing_containers))
    else:
        for container_id in sorted(required_container_ids):
            evidence.append(f"{container_id}_container_found")

    blocked_terms = _final_submit_terms(graph)
    if safety_payload.get("forbid_final_submit", True) and _inventory_contains_any(screen_inventory, blocked_terms):
        reject_reasons.append("final_submit_visible")

    if safety_payload.get("allow_apply_entry") is False:
        evidence.append("apply_entry_disabled_by_request")
    if safety_payload.get("allow_safe_fill") is False:
        evidence.append("safe_fill_disabled_by_request")

    state_id = requested_state_id or _infer_state_id(graph, screen_inventory)
    state_ids = {str(item.get("state_id") or "") for item in graph.get("states") or [] if isinstance(item, dict)}
    if state_id and state_id not in state_ids:
        reject_reasons.append("requested_state_not_in_graph")

    matched = not reject_reasons
    return {
        "contract_version": PATH_GRAPH_RESOLUTION_CONTRACT,
        "graph_id": graph.get("graph_id"),
        "app_id": graph.get("app_id"),
        "page_type": graph.get("page_type"),
        "matched": matched,
        "state_id": state_id if matched else None,
        "confidence": 0.91 if matched else 0.0,
        "usage_allowed": matched,
        "artifact_is_authorization": False,
        "matched_evidence": evidence,
        "reject_reasons": reject_reasons,
    }


def _infer_state_id(graph: dict[str, Any], screen_inventory: dict[str, Any] | None) -> str | None:
    labels = _inventory_labels(screen_inventory)
    has_apply_or_save = any("apply" in item or "save" in item for item in labels)
    state_ids = {str(item.get("state_id") or "") for item in graph.get("states") or [] if isinstance(item, dict)}
    if has_apply_or_save and "seek_search_results_with_selected_job" in state_ids:
        return "seek_search_results_with_selected_job"
    if "seek_search_results_empty_detail" in state_ids:
        return "seek_search_results_empty_detail"
    return next(iter(state_ids), None)


def _required_container_ids(graph: dict[str, Any]) -> set[str]:
    required = set()
    for item in graph.get("scroll_containers") or []:
        if isinstance(item, dict) and item.get("container_id") in {"seek:results_list", "seek:job_detail"}:
            required.add(str(item["container_id"]))
    return required


def _container_ids(graph: dict[str, Any], scroll_containers: dict[str, Any] | list[dict[str, Any]] | None) -> set[str]:
    container_ids = {
        str(item.get("container_id") or "")
        for item in graph.get("scroll_containers") or []
        if isinstance(item, dict) and item.get("container_id")
    }
    if isinstance(scroll_containers, dict):
        items = scroll_containers.get("containers") or scroll_containers.get("scroll_containers") or []
    elif isinstance(scroll_containers, list):
        items = scroll_containers
    else:
        items = []
    for item in items:
        if isinstance(item, dict) and item.get("container_id"):
            container_ids.add(str(item["container_id"]))
    return container_ids


def _final_submit_terms(graph: dict[str, Any]) -> list[str]:
    safety = _dict(graph.get("safety_policy"))
    terms = list(safety.get("forbidden_actions") or [])
    for rule in graph.get("verification_rules") or []:
        if isinstance(rule, dict) and rule.get("rule_id") == "final_submit_forbidden":
            terms.extend(str(item) for item in rule.get("forbidden_terms") or [])
    return sorted({item.lower() for item in terms if item})


def _inventory_contains_any(screen_inventory: dict[str, Any] | None, terms: list[str]) -> bool:
    if not terms:
        return False
    return any(any(term in label for term in terms) for label in _inventory_labels(screen_inventory))


def _inventory_labels(screen_inventory: dict[str, Any] | None) -> list[str]:
    inventory = screen_inventory if isinstance(screen_inventory, dict) else {}
    labels: list[str] = []
    for key in ("available_actions", "page_elements", "cards"):
        for item in inventory.get(key) or []:
            if not isinstance(item, dict):
                continue
            for field in ("label", "text", "title", "name"):
                value = item.get(field)
                if value:
                    labels.append(str(value).strip().lower())
    return labels


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
