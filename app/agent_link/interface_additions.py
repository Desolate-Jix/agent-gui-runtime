"""新截图与界面的成组证据校验，不赋予任何执行权限。"""
from copy import deepcopy
from typing import Any

from PIL import Image

from .contracts import AgentLinkError, canonical_hash, fail, validate_batch


def validate_interface_evidence(batch: dict, screenshots: list, interfaces: list, *, canonical: bool = False) -> tuple[list, list]:
    """只接受完整新证据集合；派生字段必须与真实 PNG 严格一致。"""
    if not screenshots or not interfaces:
        fail("invalid_reference", "new interfaces and PNG evidence must be supplied together")
    wire_shots = deepcopy(screenshots)
    if canonical:
        for shot in wire_shots:
            if (not isinstance(shot, dict) or set(shot) != {"screenshot_id", "png_base64", "sha256", "width", "height"}
                    or type(shot.get("width")) is not int or type(shot.get("height")) is not int):
                fail("invalid_png", "canonical screenshot metadata is invalid")
            for field in ("sha256", "width", "height"):
                shot.pop(field)
    try:
        normalized = validate_batch({
            "contract_version": "agent_link_v1", "idempotency_key": "candidate-evidence",
            "batch_id": "candidate-evidence", "title": "candidate evidence",
            "learning_outcome": "completed", "screenshots": wire_shots,
            "interfaces": deepcopy(interfaces), "relationships": [], "steps": [], "issues": [],
        })
    except Image.DecompressionBombError as error:
        raise AgentLinkError("invalid_png", "PNG dimensions exceed limits") from error
    shots, views = normalized["screenshots"], normalized["interfaces"]
    if canonical and canonical_hash(screenshots) != canonical_hash(shots):
        fail("invalid_png", "canonical screenshot metadata differs from PNG evidence")
    shot_ids = {item["screenshot_id"] for item in shots}
    interface_ids = {item["interface_id"] for item in views}
    region_ids = {r["region_id"] for view in views for r in view["regions"]}
    if shot_ids != {view["screenshot_id"] for view in views}:
        fail("invalid_reference", "every new PNG must belong to a supplied new interface")
    if (shot_ids & {item["screenshot_id"] for item in batch["screenshots"]}
            or interface_ids & {item["interface_id"] for item in batch["interfaces"]}
            or region_ids & {r["region_id"] for view in batch["interfaces"] for r in view["regions"]}):
        fail("invalid_reference", "new evidence identities collide with the baseline")
    if len(batch["screenshots"]) + len(shots) > 32 or len(batch["interfaces"]) + len(views) > 128:
        fail("invalid_reference", "new evidence exceeds batch limits")
    return shots, views


def interface_entities_from_diffs(batch: dict, diffs: list[dict[str, Any]]) -> tuple[list, list]:
    """原子核验分开的 screenshot/interface entity，拒绝孤立或错配证据。"""
    shots, interfaces = [], []
    old_interfaces = {view["interface_id"] for view in batch["interfaces"]}
    for diff in diffs:
        if not isinstance(diff, dict) or diff.get("field") != "entity" or diff.get("target_type") not in {"screenshot", "interface"}:
            continue
        if (set(diff) != {"target_type", "target_id", "field", "baseline", "current", "proposed"}
                or not isinstance(diff["target_id"], str) or not diff["target_id"]
                or diff["baseline"] is not None or diff["current"] is not None):
            fail("invalid_diff", "new evidence entity must be strictly absent")
        value = diff["proposed"]
        if diff["target_type"] == "screenshot":
            if not isinstance(value, dict) or value.get("screenshot_id") != diff["target_id"]:
                fail("invalid_diff", "screenshot entity identity is inconsistent")
            shots.append(value)
        else:
            if (not isinstance(value, dict) or set(value) != {"anchor_interface_id", "interface"}
                    or not isinstance(value["anchor_interface_id"], str) or value["anchor_interface_id"] not in old_interfaces
                    or not isinstance(value["interface"], dict) or value["interface"].get("interface_id") != diff["target_id"]):
                fail("invalid_diff", "new interface anchor or identity is invalid")
            interfaces.append(value["interface"])
    if not shots and not interfaces:
        return [], []
    return validate_interface_evidence(batch, shots, interfaces, canonical=True)
