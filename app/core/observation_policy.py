"""跨应用的动作后渲染宽限；等待不是加载完成或动作成功的证明。"""

DEFAULT_NAVIGATION_RENDER_GRACE_MS = 2000
MAX_RENDER_GRACE_MS = 2000

_NAVIGATION_ACTIONS = frozenset({
    "open_detail", "open_apply_flow", "back", "close_modal",
    "execute_recognition_plan", "press_enter",
})


def resolve_render_grace_ms(action: str, override: int | None = None) -> int:
    if override is not None:
        if type(override) is not int or not 0 <= override <= MAX_RENDER_GRACE_MS:
            raise ValueError("observation_wait_ms must be an integer between 0 and 2000")
        return override
    return DEFAULT_NAVIGATION_RENDER_GRACE_MS if action in _NAVIGATION_ACTIONS else 0


def local_action_observation_kind(operation: str, request: dict) -> str:
    # 只选择观察时机，不校验动作或赋予按键权限。
    return "press_enter" if operation == "press_key" and request.get("key") == "Enter" else operation
