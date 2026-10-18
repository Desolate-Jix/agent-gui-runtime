"""共享语义白名单只定义可审动作，不产生执行权限。"""

ACTIVITY_ACTIONS = frozenset({"start_activity", "stop_activity"})
REVIEWED_SINGLE_STEP_ACTIONS = frozenset({
    "open_detail", "open_apply_flow", "back", "close_modal", "scroll_region", "fill_field", *ACTIVITY_ACTIONS,
})
# 动作可审不等于获得权限；填写仍要求本地值、字段期望和独立确认。
READ_ONLY_REVIEW_ACTIONS = REVIEWED_SINGLE_STEP_ACTIONS
CONFIRMATION_REQUIRED_ACTIONS = frozenset({"open_apply_flow", "scroll_region", "fill_field", *ACTIVITY_ACTIONS})
