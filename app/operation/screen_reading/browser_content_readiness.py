"""只在浏览器文本字段首轮空正文时准备可访问性；不重放识别或输入。"""
from copy import deepcopy
import re
import time

from app.core.local_input_policy import require_local_operator_input
from app.operation.recognition.control_target import _field_target_label
from app.operation.recognition.text_match import explicit_target_label
from app.operation.screen_reading.uia_provider import HARD_UIA_MAX_CONTROLS, browser_document_observation, uia_provider

_clock = time.monotonic
_wait = time.sleep
_BROWSERS = {"chrome.exe", "msedge.exe", "chromium.exe"}


def _snapshot(bound):
    # 准备采样不能读取调用方上下文中已固定的旧快照。
    return uia_provider.snapshot_window(bound, max_controls=HARD_UIA_MAX_CONTROLS)


class BrowserContentReadinessError(RuntimeError):
    def __init__(self, reason, report):
        super().__init__(reason)
        self.reason_code = reason
        self.report = deepcopy(report)


def _window_key(bound):
    rect = bound.rect
    return (bound.handle, bound.process_id, str(bound.process_name).casefold(),
        rect.left, rect.top, rect.right, rect.bottom)


class BrowserContentPreparation:
    def __init__(self, manager, bound):
        self.manager = manager
        self.window_key = _window_key(bound)
        self.root_signature = None
        self.started = _clock()
        self.report = {"contract_version": "browser_content_readiness_v1", "status": "sampling",
            "samples": [], "page_ready_verified": None, "automatic_retry_allowed": False}

    def fail(self, reason):
        self.report.update(status="unavailable", reason=reason,
            elapsed_ms=round((_clock() - self.started) * 1000, 3))
        raise BrowserContentReadinessError(reason, self.report)

    def checked_bound(self):
        try:
            if not require_local_operator_input(self.manager):
                self.fail("browser_content_identity_changed")
            bound = self.manager.get_bound_window()
            if bound is None or _window_key(bound) != self.window_key:
                self.fail("browser_content_identity_changed")
            return bound
        except BrowserContentReadinessError:
            raise
        except Exception:
            self.fail("browser_content_identity_changed")

    def sample(self, stage):
        bound = self.checked_bound()
        try:
            snapshot = _snapshot(bound)
        except Exception:
            self.fail("browser_content_provider_failed")
        self.checked_bound()
        if "initial_snapshot" not in self.report:
            self.report["initial_snapshot"] = deepcopy(snapshot)
        observation = browser_document_observation(snapshot)
        self.report["samples"].append({"stage": stage, **observation,
            "elapsed_ms": round((_clock() - self.started) * 1000, 3),
            "scan_visited_count": snapshot.get("scan_visited_count")})
        alias_count, cycle_count = snapshot.get("alias_count"), snapshot.get("cycle_count")
        # 经 COM 身份与规范父边验证的别名不是完整树，但仍可构成完整规范图。
        normalized_graph = (snapshot.get("provider_tree_valid") is False
            and snapshot.get("graph_scan_complete") is True
            and type(alias_count) is int and alias_count > 0
            and type(cycle_count) is int and 0 <= cycle_count <= alias_count
            and snapshot.get("traversal_errors") == [])
        if (snapshot.get("status") != "ok" or snapshot.get("scan_complete") is not True
                or snapshot.get("truncated") is not False or snapshot.get("traversal_errors")
                or not (snapshot.get("provider_tree_valid") is True or normalized_graph)
                or snapshot.get("scan_scope", "bound_window") != "bound_window"):
            self.fail("browser_content_scan_incomplete")
        window = snapshot.get("window") or {}
        handle, pid, process, left, top, right, bottom = self.window_key
        if (window.get("handle") != handle or window.get("process_id") != pid
                or str(window.get("process_name")).casefold() != process
                or window.get("bbox") != {"x": 0, "y": 0, "w": right - left, "h": bottom - top}):
            self.fail("browser_content_identity_changed")
        controls = snapshot.get("controls") or []
        root = controls[0] if controls else {}
        signature = (root.get("runtime_id"), root.get("class_name"))
        if (stage == "initial" and root.get("control_type") == "Window" and signature[0]
                and signature[1] == "#32770"):
            # 浏览器进程所属的原生对话框不是浏览器正文；后续仍走本帧普通识别安全门。
            self.report.update(status="not_applicable", reason="native_dialog_root")
            return snapshot, None
        if (root.get("control_type") != "Window" or not signature[0]
                or signature[1] != "Chrome_WidgetWin_1"):
            self.fail("browser_content_root_unavailable")
        if self.root_signature is None:
            self.root_signature = deepcopy(signature)
        elif signature != self.root_signature:
            self.fail("browser_content_identity_changed")
        return snapshot, observation["document_count"] > 0

    def prepare(self):
        _, observed = self.sample("initial")
        if observed is None:
            return None
        budget_started = _clock()
        self.report["initial_scan_ms"] = round((budget_started - self.started) * 1000, 3)
        for _ in range(15):
            if observed:
                break
            remaining = 1.5 - (_clock() - budget_started)
            if remaining <= 0:
                break
            _wait(min(.1, remaining))
            if _clock() - budget_started >= 1.5:
                break
            _, observed = self.sample("pre_capture_readiness")
        if not observed:
            self.fail("browser_content_not_observed")
        self.report.update(status="observed", elapsed_ms=round((_clock() - self.started) * 1000, 3))
        return self

    def capture_snapshot(self, capture):
        _, _, _, left, top, right, bottom = self.window_key
        if (not capture.get("image_path") or capture.get("roi") is not None
                or capture.get("window_size") != {"width": right - left, "height": bottom - top}):
            self.fail("browser_content_capture_mismatch")
        # 准备期的任何树都不能供定位使用；新截图之后再读一次，缺失不再等待。
        snapshot, observed = self.sample("after_fresh_capture")
        if not observed:
            self.fail("browser_content_not_observed")
        self.report["capture_binding"] = {"image_path": str(capture["image_path"]),
            "viewport_size": deepcopy(capture["window_size"]), "sample_stage": "after_fresh_capture"}
        return snapshot


def prepare_browser_content(manager, goal):
    # 明确命名字段与泛型网页字段共用既有解析；工具栏、菜单和框内文字不是字段动作。
    label = _field_target_label(goal)
    page_scope = re.search(r"\b(?:of|in|on)\s+(?:the\s+)?web\s*page\b", goal, re.I)
    page_field = bool(page_scope and not re.search(r"\b(?:not|except)\s*$", goal[:page_scope.start()], re.I))
    if (label is None or not (label or explicit_target_label(goal) or page_field)
            or re.search(r"\b(?:browser|address\s+bar|toolbar|omnibox)\b", goal, re.I)):
        return None
    bound = manager.get_bound_window()
    if bound is None or str(bound.process_name).casefold() not in _BROWSERS:
        return None
    return BrowserContentPreparation(manager, bound).prepare()
