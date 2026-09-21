"""默认等待完全相同的像素；填写可使用本地强类型保护域，不派发输入。"""
from __future__ import annotations

import hashlib
import logging
import time


class TransientCapturePixelsChanged(ValueError):
    """身份与时钟合格但像素不同；只允许被动重拍，不允许使用该帧。"""


def require_exact_fresh_capture(*, original, current, png_bytes, text_visual_scope=None, current_uia_snapshot=None):
    before, after = original["capture"], current["capture"]
    actual_hash = hashlib.sha256(png_bytes).hexdigest()
    checks = {key + "_unchanged": current[key] == original[key] for key in ("target", "application", "uia")}
    checks.update(viewport_unchanged=after["viewport_size"] == before["viewport_size"],
        png_integrity=actual_hash == after["screenshot_sha256"],
        clock_unchanged=after["capture_clock_id"] == before["capture_clock_id"],
        capture_id_new=after["capture_id"] != before["capture_id"],
        capture_newer=after["capture_started_ns"] > before["observed_at_ns"])
    if text_visual_scope is not None:
        from app.agent.text_visual_stability import TextVisualStabilityScope, TextVisualPixelsChanged
        if type(text_visual_scope) is not TextVisualStabilityScope:
            raise ValueError("text visual scope must be a local typed expectation")
    # 填写 scope 会对两份完整 UIA 及保护域重算；无 scope 的路径仍须整树相同。
    if not all(value for key, value in checks.items() if key != 'uia_unchanged' or text_visual_scope is None):
        # 只记录布尔判据，保留拒绝顺序，不泄漏窗口或控件原值。
        logging.getLogger(__name__).warning("fresh_capture_binding_rejected %s", checks)
        raise ValueError("fresh action identity or capture integrity changed before input")
    if text_visual_scope is not None:
        try:
            proof = text_visual_scope.validate(current_evidence=current, current_png_bytes=png_bytes,
                current_uia_snapshot=current_uia_snapshot)
        except TextVisualPixelsChanged as error:
            raise TransientCapturePixelsChanged(str(error)) from error
        except ValueError:
            logging.getLogger(__name__).warning("fresh_capture_text_scope_rejected %s", checks)
            raise
        proof.validate_binding(original, current, text_visual_scope.expectation_reference,
            automatic_safety_interception=text_visual_scope.automatic_safety_interception)
        return proof
    if actual_hash != before["screenshot_sha256"]:
        raise TransientCapturePixelsChanged("fresh action pixels changed before input")


def check_fresh_capture_pixels(*, original, observe, validate_source, allow_transient_retry=False):
    before = original["capture"]
    attempts = 7 if allow_transient_retry else 1
    seen_ids = {before["capture_id"]}
    last_observed_ns = before["observed_at_ns"]
    for attempt in range(1, attempts + 1):
        validate_source()
        packet = observe()
        validate_source()
        current = packet.evidence()
        after = current["capture"]
        if (after["capture_id"] in seen_ids
                or after["capture_started_ns"] <= last_observed_ns):
            raise ValueError("passive retry requires a newer capture")
        seen_ids.add(after["capture_id"])
        last_observed_ns = after["observed_at_ns"]
        try:
            require_exact_fresh_capture(original=original, current=current, png_bytes=packet.png_bytes)
        except TransientCapturePixelsChanged:
            if attempt < attempts:
                time.sleep(0.1)
                continue
            raise
        return {"attempts": attempt, "capture_id": after["capture_id"], "screenshot_sha256": after["screenshot_sha256"]}
    raise ValueError("fresh action pixels changed before input")
