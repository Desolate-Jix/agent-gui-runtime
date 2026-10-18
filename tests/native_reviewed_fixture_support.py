"""仅允许测试操作员代审自有导航夹具的已发布流程动作。"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

from app.desktop_review.grounded_preview_widget import validate_review_view, review_time
from tests.native_fixture_review_support import FixtureReviewDriver, FixtureScope


class ReviewedNavigationFixtureScope(FixtureScope):
    """把 reviewed_learning 预览绑定到确切发布资产和导航夹具状态。"""

    _ACTIONS = {
        "open_detail": ("list", "查看示例详情", "open_detail · ACTION_RECORDED"),
        "back": ("detail", "返回列表", "back · ACTION_RECORDED"),
    }

    def __init__(self, *args, asset_id, asset_content_sha256, transition_id, goal, **kwargs):
        script = Path(args[4] if len(args) > 4 else kwargs.get("script", "")).resolve()
        if script != Path(__file__).with_name("native_navigation_target.py").resolve():
            raise PermissionError("not_this_navigation_fixture")
        super().__init__(*args, **kwargs)
        if not all(isinstance(value, str) and value for value in
                   (asset_id, asset_content_sha256, transition_id, goal)):
            raise ValueError("reviewed_fixture_binding_invalid")
        if len(asset_content_sha256) != 64 or any(c not in "0123456789abcdef" for c in asset_content_sha256):
            raise ValueError("reviewed_fixture_binding_invalid")
        self.asset_id = asset_id
        self.asset_content_sha256 = asset_content_sha256
        self.transition_id = transition_id
        self.goal = goal

    def verify_review(self, view, pinned, grant):
        checked, _ = validate_review_view(view)
        if ({**checked, "phase": "pending_review"} != pinned
                or review_time(checked["expires_at"]) <= datetime.now(timezone.utc)):
            raise PermissionError("fixture_preview_changed_or_expired")
        preview = checked["preview"]
        workflow, grounding = preview["workflow"], preview["grounding_preview"]
        action = next((item for item in preview["current_observation"]["available_actions"]
                       if item.get("action_id") == self.transition_id), None)
        expected = self._ACTIONS.get(grounding.get("semantic_action"))
        explicit_goals = [value for value in (grounding.get("goal"), (action or {}).get("goal"))
                          if value is not None]
        identity = self.verify_process()
        state = json.loads((self.evidence_dir / "latest-state.json").read_text(encoding="utf-8"))
        if (checked.get("source_kind") not in (None, "reviewed_learning")
                or preview["target_window_handle"] != self.handle
                or preview["target_process_id"] != self.pid
                or workflow.get("asset_id") != self.asset_id
                or workflow.get("asset_content_sha256") != self.asset_content_sha256
                or grounding.get("asset_id") != self.asset_id
                or grounding.get("asset_content_sha256") != self.asset_content_sha256
                or grounding.get("transition_id") != self.transition_id
                or action is None or action.get("semantic_action") != grounding.get("semantic_action")
                or expected is None or expected[1] != self.goal
                or (action or {}).get("description") != expected[2]
                or any(value != self.goal for value in explicit_goals)
                or state.get("pid") != self.pid or state.get("source_file_sha256") != self.script_sha
                or state.get("state") != expected[0]
                or identity["process_id"] != self.pid):
            raise PermissionError("reviewed_fixture_binding_changed")
        required = {
            "actor": "authorized_fixture_test_operator", "human_approval": False,
            "confirmation_id": checked["confirmation_id"],
            "preview_sha256": preview["content_sha256"],
            "png_sha256": hashlib.sha256(checked["png_bytes"]).hexdigest(),
            "window_handle": self.handle, "process_id": self.pid,
            "asset_id": self.asset_id, "asset_content_sha256": self.asset_content_sha256,
            "transition_id": self.transition_id, "goal": self.goal,
        }
        if grant != required:
            raise PermissionError("fixture_operator_grant_mismatch")


class ReviewedFixtureReviewDriver(FixtureReviewDriver):
    """只改写 reviewed_learning 的语义读取，不改变真实按钮与确认链。"""

    def __init__(self, dialog, scope, view, grant_path, log_path):
        normalized = dict(view)
        if normalized.get("source_kind") == "reviewed_learning":
            normalized.pop("source_kind")
        super().__init__(dialog, scope, normalized, grant_path, log_path)

    def semantic_action(self):
        return self.pinned["preview"]["grounding_preview"]["semantic_action"]
