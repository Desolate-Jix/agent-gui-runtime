from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agent.navigation_decision_provider import (
    OpenAICompatibleNavigationDecisionProvider,
)
from app.agent.navigation_reading_controller import (
    run_navigation_reading_controller,
)
from app.agent.navigation_reading_live_runtime import (
    BufferedNavigationRuntimeObserver,
    RuntimeNavigationOperationAdapter,
)
from app.agent.navigation_reading_observation import (
    build_navigation_runtime_observation,
)
from app.learn.agent_evidence import (
    PersistedReviewRevision,
    build_agent_evidence_context,
)
from app.learn.continuous_workflow_projection import (
    persist_continuous_session_workflow_candidate,
)


LIVE_SUITE_CONTRACT = "navigation_reading_live_suite_v1"
LIVE_REPORT_CONTRACT = "navigation_reading_live_smoke_report_v1"


class _ReviewedNavigationSuiteMemoryStore:
    def __init__(self, suite: dict[str, Any]) -> None:
        self._suite = suite

    def registry(self) -> dict[str, Any]:
        return {
            "active_by_interface": {
                interface_id: str(evidence.get("source_asset_sha256") or interface_id)
                for interface_id, evidence in self._suite["evidence_by_interface"].items()
            }
        }

    def load_active(self, interface_id: str) -> dict[str, Any]:
        evidence = deepcopy(self._suite["evidence_by_interface"][interface_id])
        interface = evidence.get("interface") if isinstance(evidence.get("interface"), dict) else {}
        content_descriptors = [
            deepcopy(item)
            for item in [
                *(evidence.get("identity_anchors") or []),
                *(evidence.get("dynamic_content") or []),
            ]
            if isinstance(item, dict)
        ]
        controls = [
            deepcopy(item)
            for item in evidence.get("semantic_controls") or []
            if isinstance(item, dict)
        ]
        actions = []
        for item in evidence.get("available_actions") or []:
            if not isinstance(item, dict):
                continue
            action = deepcopy(item)
            action["target_control_id"] = str(action.get("source_control_id") or "")
            actions.append(action)
        return {
            "contract_version": "reviewed_interface_memory_v1",
            "interface_id": interface_id,
            "source": {
                "reviewed_candidate_path": self._suite["asset_paths"][interface_id],
                "screenshot_path": "",
                "screenshot_sha256": str(evidence.get("source_asset_sha256") or ""),
            },
            "review": {
                "reviewed_by_human": True,
                "review_status": str(interface.get("review_status") or "human_reviewed"),
            },
            "agent_description": str(interface.get("responsibility") or "").strip(),
            "manual_revision": {
                "semantic_description": str(interface.get("responsibility") or "").strip(),
            },
            "content_descriptors": content_descriptors,
            "states": [
                {
                    "state_id": interface_id,
                    "display_name": str(interface.get("display_name") or interface_id),
                    "surface_type": str(interface.get("surface_type") or "unknown_surface"),
                }
            ],
            "elements": controls,
            "actions": actions,
            "verification_rules": deepcopy(evidence.get("verification_rules") or []),
            "blockers": deepcopy(evidence.get("blockers") or []),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }


def load_reviewed_navigation_suite(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    manifest = _read_json(manifest_path)
    if manifest.get("contract_version") != LIVE_SUITE_CONTRACT:
        raise ValueError(f"{LIVE_SUITE_CONTRACT} is required")

    specs = [
        deepcopy(item)
        for item in manifest.get("interface_specs") or []
        if isinstance(item, dict)
    ]
    spec_ids = [_required_text(item.get("interface_id"), "interface_id") for item in specs]
    if len(spec_ids) != len(set(spec_ids)):
        raise ValueError("interface_specs contains duplicate interface_id values")
    initial_interface_id = _required_text(
        manifest.get("initial_interface_id"),
        "initial_interface_id",
    )
    if initial_interface_id not in set(spec_ids):
        raise ValueError("initial_interface_id must reference an interface spec")

    transitions = [
        deepcopy(item)
        for item in manifest.get("transitions") or []
        if isinstance(item, dict)
    ]
    evidence_by_interface: dict[str, dict[str, Any]] = {}
    asset_paths: dict[str, str] = {}
    for reference in manifest.get("interface_assets") or []:
        if not isinstance(reference, dict):
            continue
        interface_id = _required_text(reference.get("interface_id"), "interface_id")
        raw_path = Path(_required_text(reference.get("path"), "asset path"))
        asset_path = raw_path if raw_path.is_absolute() else manifest_path.parent / raw_path
        if not asset_path.is_file():
            raise FileNotFoundError(f"reviewed interface asset not found: {asset_path}")
        content = asset_path.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        expected_sha = _required_text(reference.get("sha256"), "asset sha256").casefold()
        if actual_sha != expected_sha:
            raise ValueError(
                f"stale reviewed interface asset {interface_id}: "
                f"expected {expected_sha}, actual {actual_sha}"
            )
        asset = json.loads(content.decode("utf-8-sig"))
        if (
            not isinstance(asset, dict)
            or asset.get("contract_version") != "single_interface_asset_v1"
            or str(asset.get("interface_id") or "") != interface_id
        ):
            raise ValueError(f"invalid reviewed interface asset: {interface_id}")
        persisted_review_revision = _load_persisted_review_revision(
            reference,
            interface_id=interface_id,
            asset=asset,
            asset_sha256=actual_sha,
        )
        outgoing = [
            item
            for item in transitions
            if str(item.get("source_interface_id") or "") == interface_id
        ]
        evidence = build_agent_evidence_context(
            asset,
            outgoing_transitions=outgoing,
            persisted_review_revision=persisted_review_revision,
        )
        if evidence["readiness"]["status"] != "agent_usable":
            raise ValueError(
                f"reviewed interface is not agent_usable: {interface_id}; "
                f"missing={evidence['readiness']['missing_fields']}"
            )
        evidence["source_asset_sha256"] = actual_sha
        evidence_by_interface[interface_id] = evidence
        asset_paths[interface_id] = str(asset_path.resolve())

    missing_assets = sorted(set(spec_ids) - set(evidence_by_interface))
    if missing_assets:
        raise ValueError(
            "interface specs missing reviewed assets: " + ", ".join(missing_assets)
        )

    return {
        "contract_version": LIVE_SUITE_CONTRACT,
        "suite_id": _required_text(manifest.get("suite_id"), "suite_id"),
        "goal": _required_text(manifest.get("goal"), "goal"),
        "app_name": _required_text(manifest.get("app_name"), "app_name"),
        "initial_interface_id": initial_interface_id,
        "interface_specs": specs,
        "transitions": transitions,
        "evidence_by_interface": evidence_by_interface,
        "asset_paths": asset_paths,
        "application_identity": _suite_application_identity(
            app_name=_required_text(manifest.get("app_name"), "app_name"),
            evidence_by_interface=evidence_by_interface,
        ),
        "manifest_path": str(manifest_path),
        "artifact_is_authorization": False,
    }


def capture_navigation_runtime_record(
    *,
    post_json: Callable[[str, dict[str, Any]], dict[str, Any]],
    app_name: str,
    interface_specs: list[dict[str, Any]],
    expected_interface_id: str | None = None,
) -> dict[str, Any]:
    capture = _required_api_data(
        post_json("/state/capture_window", {"save_image": True}),
        "capture current window",
    )
    image_path = _required_text(capture.get("image_path"), "image_path")
    reading = _required_api_result(
        post_json(
            "/vision/screen_reading",
            {
                "image_path": image_path,
                "task": "screen_reading",
                "app_name": app_name,
                "goal": (
                    "Identify the current reviewed interface and read the visible "
                    "content using only the current screenshot."
                ),
                "provider_mode": "local_understanding",
                "metadata": {
                    "source": "navigation_reading_live_smoke",
                    "trace": True,
                },
            },
        ),
        "screen reading",
    )
    return build_navigation_runtime_observation(
        capture=capture,
        screen_reading=reading,
        interface_specs=interface_specs,
        expected_interface_id=expected_interface_id,
    )


def run_navigation_reading_live_smoke(
    *,
    suite_path: str | Path,
    out_dir: str | Path,
    workflow_project_root: str | Path | None = None,
    runtime_endpoint: str,
    decision_endpoint: str,
    decision_model: str,
    max_steps: int = 18,
    request_timeout_seconds: float = 90.0,
    decision_timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    suite = load_reviewed_navigation_suite(suite_path)
    return run_navigation_reading_live_suite(
        suite=suite,
        out_dir=out_dir,
        workflow_project_root=workflow_project_root,
        runtime_endpoint=runtime_endpoint,
        decision_endpoint=decision_endpoint,
        decision_model=decision_model,
        max_steps=max_steps,
        request_timeout_seconds=request_timeout_seconds,
        decision_timeout_seconds=decision_timeout_seconds,
        persist_session_workflow=True,
    )


def run_navigation_reading_live_suite(
    *,
    suite: dict[str, Any],
    out_dir: str | Path,
    workflow_project_root: str | Path | None = None,
    runtime_endpoint: str,
    decision_endpoint: str,
    decision_model: str,
    max_steps: int = 18,
    request_timeout_seconds: float = 90.0,
    decision_timeout_seconds: float = 45.0,
    persist_session_workflow: bool = True,
) -> dict[str, Any]:
    """运行已经编译好的多界面 suite，不把学习资产视为执行授权。"""

    if suite.get("artifact_is_authorization") is not False:
        raise ValueError("live navigation suite must not authorize execution")
    post_json = _http_post_json(
        runtime_endpoint,
        timeout_seconds=request_timeout_seconds,
    )

    observer = BufferedNavigationRuntimeObserver(
        capture_current=lambda expected_interface_id=None: capture_navigation_runtime_record(
            post_json=post_json,
            app_name=suite["app_name"],
            interface_specs=suite["interface_specs"],
            expected_interface_id=expected_interface_id,
        )
    )
    initial_record = observer.capture_initial()
    initial_observation = initial_record["observation"]
    expected_initial_interface_id = suite["initial_interface_id"]
    actual_initial_interface_id = initial_observation["interface_id"]
    initial_state_check = {
        "status": (
            "matched"
            if actual_initial_interface_id == expected_initial_interface_id
            else "mismatch"
        ),
        "expected_interface_id": expected_initial_interface_id,
        "actual_interface_id": actual_initial_interface_id,
        "capture_id": initial_observation["capture_id"],
        "screenshot_sha256": initial_observation["screenshot_sha256"],
        "trace_path": initial_observation["trace_path"],
    }

    if initial_state_check["status"] == "mismatch":
        controller_report = {
            "contract_version": "navigation_reading_controller_report_v1",
            "goal": suite["goal"],
            "workflow_id": suite["suite_id"],
            "session_id": f"live:{suite['suite_id']}",
            "final_status": "needs_human_review",
            "stop_reason": "initial_interface_mismatch",
            "visited_interfaces": [],
            "interface_visit_history": [],
            "steps": [],
            "decision_source_breakdown": {},
            "actual_model_call_count": 0,
            "session": None,
            "safety": {
                "final_submit_forbidden": True,
                "final_submit_executed": False,
                "artifact_is_authorization": False,
            },
        }
    else:
        operation = RuntimeNavigationOperationAdapter(
            post_json=post_json,
            observer=observer,
            app_name=suite["app_name"],
        )
        decision_provider = OpenAICompatibleNavigationDecisionProvider(
            endpoint=decision_endpoint,
            model_name=decision_model,
            timeout_seconds=decision_timeout_seconds,
            temperature=0.0,
            max_tokens=256,
        )
        controller_report = run_navigation_reading_controller(
            goal=suite["goal"],
            workflow_id=suite["suite_id"],
            session_id=f"live:{suite['suite_id']}",
            observe_current=observer.observe_current,
            load_interface_evidence=lambda interface_id: deepcopy(
                suite["evidence_by_interface"][interface_id]
            ),
            decide=decision_provider.decide,
            execute_operation=operation.execute,
            max_steps=max_steps,
        )

    out_path = Path(out_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    report_path = out_path / "navigation_reading_live_smoke_report.json"
    session = controller_report.get("session")
    if not persist_session_workflow:
        multi_interface_workflow = {
            "contract_version": "reviewed_multi_interface_runtime_source_v1",
            "status": "source_workflow_reused",
            "path": str(suite.get("manifest_path") or ""),
            "node_count": len(suite["evidence_by_interface"]),
            "edge_count": len(suite["transitions"]),
            "multi_interface_requirement_met": (
                len(suite["evidence_by_interface"]) >= 2
            ),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    elif isinstance(session, dict):
        workflow_runtime_report = deepcopy(controller_report)
        workflow_runtime_report["source_report_path"] = str(report_path)
        workflow_runtime_report["trace_path"] = str(report_path)
        multi_interface_workflow = persist_continuous_session_workflow_candidate(
            session=session,
            runtime_report=workflow_runtime_report,
            application_identity=suite["application_identity"],
            goal=suite["goal"],
            memory_store=_ReviewedNavigationSuiteMemoryStore(suite),
            project_root=(
                Path(workflow_project_root).resolve()
                if workflow_project_root is not None
                else out_path
            ),
        )
    else:
        multi_interface_workflow = {
            "contract_version": "continuous_workflow_projection_result_v1",
            "status": "not_covered",
            "reason": "continuous_session_not_available",
            "node_count": 0,
            "edge_count": 0,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    generated_workflow_id = str(
        multi_interface_workflow.get("workflow_id") or ""
    ).strip()
    generated_workflow_path = str(
        multi_interface_workflow.get("path") or ""
    ).strip()
    source_workflow_id = str(suite.get("suite_id") or "").strip()
    workflow_lineage = {
        "contract_version": "learned_workflow_lineage_v1",
        "source_workflow_id": source_workflow_id,
        "source_manifest_path": str(suite.get("manifest_path") or ""),
        "generated_workflow_id": generated_workflow_id,
        "generated_workflow_path": generated_workflow_path,
        "source_and_generated_are_distinct": bool(
            generated_workflow_id
            and generated_workflow_id != source_workflow_id
        ),
        "relation": (
            "derived_from_live_traversal"
            if generated_workflow_id
            else "source_only"
        ),
        "artifact_is_authorization": False,
    }
    report = {
        "contract_version": LIVE_REPORT_CONTRACT,
        "source": str(suite.get("source") or "reviewed_navigation_suite_manifest"),
        "suite_id": suite["suite_id"],
        "goal": suite["goal"],
        "controller": controller_report,
        "multi_interface_workflow": multi_interface_workflow,
        "workflow_lineage": workflow_lineage,
        "initial_state_check": initial_state_check,
        "reviewed_asset_paths": deepcopy(suite["asset_paths"]),
        "interpretation": (
            "Controlled live GUI navigation, finite information reading, and scoped "
            "scrolling only. No form filling and no final submission."
        ),
        "safety": {
            "live_fill_attempted": False,
            "live_submit_attempted": False,
            "final_submit_forbidden": True,
            "artifact_is_authorization": False,
        },
        "report_path": str(report_path),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _suite_application_identity(
    *,
    app_name: str,
    evidence_by_interface: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    identity_keys = {
        str((evidence.get("interface") or {}).get("application_identity_key") or "").strip()
        for evidence in evidence_by_interface.values()
        if isinstance(evidence.get("interface"), dict)
    }
    identity_keys.discard("")
    if len(identity_keys) != 1:
        raise ValueError("reviewed suite must use one application identity")
    identity_key = next(iter(identity_keys))
    kind, separator, identifier = identity_key.partition(":")
    if not separator or not identifier:
        raise ValueError("reviewed suite application identity is invalid")
    if kind == "web":
        return {
            "kind": "web",
            "domain": identifier,
            "display_name": app_name,
        }
    return {
        "kind": "native",
        "product_name": app_name,
        "display_name": app_name,
    }


def _http_post_json(
    endpoint: str,
    *,
    timeout_seconds: float,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    base = _required_text(endpoint, "runtime endpoint").rstrip("/")

    def post_json(path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{base}/{path.lstrip('/')}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"runtime endpoint returned HTTP {exc.code}: {details}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"failed to reach runtime endpoint: {exc.reason}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("runtime endpoint returned a non-object response")
        return result

    return post_json


def _required_api_data(response: dict[str, Any], operation_name: str) -> dict[str, Any]:
    if not isinstance(response, dict) or response.get("success") is not True:
        error = response.get("error") if isinstance(response, dict) else response
        raise RuntimeError(f"{operation_name} failed: {error}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"{operation_name} returned no data")
    return deepcopy(data)


def _required_api_result(
    response: dict[str, Any],
    operation_name: str,
) -> dict[str, Any]:
    data = _required_api_data(response, operation_name)
    result = data.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"{operation_name} returned no result")
    return deepcopy(result)


def _load_persisted_review_revision(
    reference: dict[str, Any],
    *,
    interface_id: str,
    asset: dict[str, Any],
    asset_sha256: str,
) -> PersistedReviewRevision:
    raw = reference.get("persisted_review_revision")
    if not isinstance(raw, dict):
        raise ValueError(f"missing_persisted_review_revision: {interface_id}")
    revision = raw.get("revision")
    if not isinstance(revision, dict):
        raise ValueError(f"invalid_persisted_review_revision: {interface_id}")
    revision_hash = str(raw.get("revision_hash") or "").strip().casefold()
    source_asset_sha256 = str(
        raw.get("source_asset_sha256") or ""
    ).strip().casefold()
    if revision_hash != _sha256_json(revision):
        raise ValueError(f"invalid_persisted_review_revision: {interface_id}")
    if source_asset_sha256 != asset_sha256:
        raise ValueError(f"stale_persisted_review_revision: {interface_id}")
    evidence = asset.get("evidence") if isinstance(asset.get("evidence"), dict) else {}
    if (
        str(revision.get("interface_id") or "").strip() != interface_id
        or str(revision.get("audit_evidence_sha256") or "").strip().casefold()
        != _sha256_json(evidence)
    ):
        raise ValueError(f"stale_persisted_review_revision: {interface_id}")
    return PersistedReviewRevision(
        revision=deepcopy(revision),
        revision_hash=revision_hash,
        source_asset_sha256=source_asset_sha256,
    )


def _sha256_json(value: dict[str, Any]) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
