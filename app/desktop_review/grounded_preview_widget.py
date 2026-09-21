"""同一 owner 的只读定位截图与预检身份，不产生批准或输入权限。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import re
import struct

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget

from app.agent.fresh_learning_action_preview import FreshLearningActionPreview
from app.agent.automatic_safety_policy import preview_action_selection, preview_automatic_safety_interception
from app.agent.fresh_learning_recording import fresh_preview_geometry
from app.agent.grounded_action_preview import GroundedActionPreview
from app.agent.text_execution import validate_local_text_preview
from app.agent.text_field_evidence import TextFieldExpectation
from .geometry_comparison import _ReadonlyGraphicsView


_VIEW_KEYS = {"phase", "confirmation_id", "preview", "requested_at", "expires_at", "owner_is_current", "png_bytes"}
_FRESH_VIEW_KEYS = _VIEW_KEYS | {"source_kind"}


def review_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid review timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("review timestamp must be UTC")
    return result


def _validate_png(raw, *, screenshot_sha256, viewport) -> QImage:
    if (type(raw) is not bytes or not 33 <= len(raw) <= 32 * 1024 * 1024
            or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR"
            or hashlib.sha256(raw).hexdigest() != screenshot_sha256):
        raise ValueError("invalid review PNG hash")
    width, height = struct.unpack(">II", raw[16:24])
    if (not 0 < width <= 32768 or not 0 < height <= 32768 or width * height > 64_000_000
            or (width, height) != (viewport["width"], viewport["height"])):
        raise ValueError("invalid review PNG viewport")
    image = QImage.fromData(raw, "PNG")
    if image.isNull() or (image.width(), image.height()) != (width, height):
        raise ValueError("invalid review PNG pixels")
    return image


def _fresh_geometry(preview: dict) -> tuple[dict, str, dict, dict]:
    """从已验证的首次预览恢复可显示的候选几何，不产生新的定位。"""

    evidence = preview["observation_evidence"]
    capture = evidence["capture"]
    viewport = capture["viewport_size"]
    decision = preview["pre_click_decision"]
    risk = preview["risk"]
    geometry = fresh_preview_geometry(FreshLearningActionPreview.from_dict(preview))
    selection = preview_action_selection(preview)
    candidate_id = selection.get("selected_candidate_id")
    interception = preview_automatic_safety_interception(preview)
    if (not isinstance(candidate_id, str) or not candidate_id
            or (interception and (decision.get("allowed") is not True or risk.get("hard_blocked") is not False))
            or geometry.get("viewport_size") != viewport
            or geometry.get("target_window_handle") != evidence["target"]["window_handle"]
            or geometry.get("target_process_id") != evidence["target"]["process_id"]):
        raise ValueError("fresh preview candidate or risk is invalid")
    bbox = geometry.get("bbox")
    click_point = geometry.get("click_point")
    point = (None if not isinstance(click_point, list) or len(click_point) != 2 else {
        "x": click_point[0], "y": click_point[1],
    })
    if (not isinstance(bbox, dict) or set(bbox) != {"x", "y", "w", "h"}
            or not isinstance(point, dict) or set(point) != {"x", "y"}
            or any(type(bbox[key]) is not int for key in bbox)
            or any(type(point[key]) is not int for key in point)
            or bbox["w"] <= 0 or bbox["h"] <= 0
            or bbox["x"] < 0 or bbox["y"] < 0
            or bbox["x"] + bbox["w"] > viewport["width"]
            or bbox["y"] + bbox["h"] > viewport["height"]
            or not bbox["x"] <= point["x"] <= bbox["x"] + bbox["w"]
            or not bbox["y"] <= point["y"] <= bbox["y"] + bbox["h"]):
        raise ValueError("fresh preview geometry is invalid")
    return evidence, candidate_id, bbox, point


def _validate_fresh_review_view(value: dict) -> tuple[dict, QImage]:
    if not isinstance(value, dict):
        raise ValueError("invalid fresh review identity")
    preview = FreshLearningActionPreview.from_dict(value.get("preview")).to_dict()
    is_text = preview["intent"]["semantic_action"] == "fill_field"
    local_keys = {"text_input_local", "text_field_local"} if is_text else set()
    if (set(value) != _FRESH_VIEW_KEYS | local_keys
            or value.get("source_kind") != "fresh_learning"
            or value.get("phase") not in ("pending_review", "approved")
            or value.get("owner_is_current") is not True
            or not isinstance(value.get("confirmation_id"), str)
            or re.fullmatch(r"grounded-confirmation\.[0-9a-f]{64}", value["confirmation_id"]) is None):
        raise ValueError("invalid fresh review identity")
    if is_text:
        validate_local_text_preview(preview, value["text_input_local"])
        local = value["text_field_local"]
        if (type(local) is not TextFieldExpectation or local.parameters != value["text_input_local"]
                or local.to_reference() != preview["text_field_expectation_ref"]):
            raise ValueError("local fresh text field expectation differs from preview")
    requested, expires = review_time(value["requested_at"]), review_time(value["expires_at"])
    if expires - requested != timedelta(seconds=300):
        raise ValueError("invalid review TTL")
    evidence, _candidate_id, _bbox, _point = _fresh_geometry(preview)
    capture = evidence["capture"]
    image = _validate_png(value["png_bytes"], screenshot_sha256=capture["screenshot_sha256"],
                         viewport=capture["viewport_size"])
    return deepcopy(value), image


def validate_review_view(value: dict) -> tuple[dict, QImage]:
    try:
        if isinstance(value, dict) and value.get("source_kind") == "fresh_learning":
            return _validate_fresh_review_view(value)
        is_text = (isinstance(value, dict) and isinstance(value.get("preview"), dict)
                   and isinstance(value["preview"].get("review_selection"), dict)
                   and value["preview"]["review_selection"].get("semantic_action") == "fill_field")
        has_field_expectation = is_text and "text_field_expectation_ref" in value["preview"]
        local_keys = {"text_input_local"} if is_text else set()
        if has_field_expectation:
            local_keys.add("text_field_local")
        if (not isinstance(value, dict) or set(value) != _VIEW_KEYS | local_keys
                or value["phase"] not in ("pending_review", "approved")
                or value["owner_is_current"] is not True
                or not isinstance(value["confirmation_id"], str)
                or re.fullmatch(r"grounded-confirmation\.[0-9a-f]{64}", value["confirmation_id"]) is None):
            raise ValueError("invalid review identity")
        preview = GroundedActionPreview.from_dict(value["preview"]).to_dict()
        if is_text:
            validate_local_text_preview(preview, value["text_input_local"])
        if has_field_expectation:
            local = value["text_field_local"]
            if (type(local) is not TextFieldExpectation
                    or local.parameters != value["text_input_local"]
                    or local.to_reference() != preview["text_field_expectation_ref"]):
                raise ValueError("local text field expectation differs from preview")
        requested, expires = review_time(value["requested_at"]), review_time(value["expires_at"])
        if expires - requested != timedelta(seconds=300):
            raise ValueError("invalid review TTL")
        lineage = preview["grounding_preview"]["capture_lineage"]
        image = _validate_png(value["png_bytes"], screenshot_sha256=lineage["screenshot_sha256"],
                             viewport=lineage["viewport_size"])
        return deepcopy(value), image
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError, struct.error):
        raise ValueError("单步预检的身份、截图、几何框或有效期校验失败。") from None


class GroundedPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._review = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        label = QLabel("定位预览 · 只读", self)
        label.setTextFormat(Qt.TextFormat.PlainText)
        controls.addWidget(label)
        controls.addStretch()
        self.zoom_out_button = QPushButton("缩小", self)
        self.zoom_in_button = QPushButton("放大", self)
        self.fit_button = QPushButton("适配", self)
        for button in (self.zoom_out_button, self.zoom_in_button, self.fit_button):
            button.setAutoDefault(False)
            controls.addWidget(button)
        layout.addLayout(controls)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.view = _ReadonlyGraphicsView(self)
        self.view.setAccessibleName("真实预检截图、识别框与十字点击点，只读")
        self.view.setMinimumSize(280, 220)
        self.metadata_text = QPlainTextEdit(self)
        self.metadata_text.setReadOnly(True)
        self.metadata_text.setAccessibleName("单步预检完整身份与证据")
        self.metadata_text.setMinimumWidth(240)
        details = QWidget(self)
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addWidget(self.metadata_text, 2)
        self.text_value_label = QLabel("本次完整文本 · 本地只读", self)
        self.text_value_editor = QPlainTextEdit(self)
        self.text_value_editor.setReadOnly(True)
        self.text_value_editor.setAccessibleName("本次已冻结实际文本，只读")
        details_layout.addWidget(self.text_value_label)
        details_layout.addWidget(self.text_value_editor, 1)
        self.text_before_label = QLabel("原值 · 本地只读", self)
        self.text_before_editor = QPlainTextEdit(self)
        self.text_before_editor.setReadOnly(True)
        self.text_before_editor.setAccessibleName("字段原值，只读")
        self.text_expected_label = QLabel("预计最终内容 · 本地只读", self)
        self.text_expected_editor = QPlainTextEdit(self)
        self.text_expected_editor.setReadOnly(True)
        self.text_expected_editor.setAccessibleName("字段预计最终内容，只读")
        details_layout.addWidget(self.text_before_label)
        details_layout.addWidget(self.text_before_editor, 1)
        details_layout.addWidget(self.text_expected_label)
        details_layout.addWidget(self.text_expected_editor, 1)
        splitter.addWidget(self.view)
        splitter.addWidget(details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([680, 340])
        layout.addWidget(splitter, 1)
        self.zoom_out_button.clicked.connect(self.view.zoom_out)
        self.zoom_in_button.clicked.connect(self.view.zoom_in)
        self.fit_button.clicked.connect(self.view.fit_image)
        self.clear()

    @property
    def review(self):
        return deepcopy(self._review)

    @property
    def expired(self):
        return self._review is None or datetime.now(timezone.utc) >= review_time(self._review["expires_at"])

    def clear(self):
        self._review = None
        self.text_value_editor.clear()
        self.text_value_editor.hide()
        self.text_value_label.hide()
        self.text_before_editor.clear()
        self.text_before_editor.hide()
        self.text_before_label.hide()
        self.text_expected_editor.clear()
        self.text_expected_editor.hide()
        self.text_expected_label.hide()
        self.view.scene().clear()
        self.view.scene().setSceneRect(QRectF())
        self.metadata_text.setPlainText("尚无预检截图，也没有批准或执行权限。\n\n请选择已发布流程和目标窗口，然后进行预检。")

    def set_review(self, value):
        self.clear()
        checked, image = validate_review_view(value)
        if checked.get("source_kind") == "fresh_learning":
            self._set_fresh_review(checked, image)
            return
        preview = checked["preview"]
        ground = preview["grounding_preview"]
        scene = self.view.scene()
        scene.addPixmap(QPixmap.fromImage(image))
        bbox, point = ground["bbox"], ground["click_point"]
        pen = QPen(QColor("#147d92"), 2.0)
        pen.setCosmetic(True)
        rect = scene.addRect(0, 0, bbox["w"], bbox["h"], pen, QColor(20, 125, 146, 28))
        rect.setPos(bbox["x"], bbox["y"])
        rect.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        rect.setZValue(1)
        cross_pen = QPen(QColor("#aa3b13"), 2.0)
        cross_pen.setCosmetic(True)
        x, y = point["x"], point["y"]
        for coords in ((x - 8, y, x + 8, y), (x, y - 8, x, y + 8)):
            cross = scene.addLine(*coords, cross_pen)
            cross.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            cross.setZValue(2)
        scene.setSceneRect(QRectF(0, 0, image.width(), image.height()))
        self.view.fit_image()
        lineage = ground["capture_lineage"]
        scroll_details = ""
        point_label = "点击点"
        if ground["semantic_action"] == "scroll_region":
            parameters = ground["scroll_parameters"]
            direction = {"up": "向上", "down": "向下"}[parameters["direction"]]
            point_label = "滚动位置"
            scroll_details = (
                f"滚动容器：{parameters['target_container_id']}\n"
                f"方向：{direction}\n"
                f"滚轮档数：{parameters['wheel_clicks']}\n"
                f"单位：{parameters['unit']}\n\n"
            )
        elif ground["semantic_action"] == "fill_field":
            point_label = "字段聚焦点"
            scroll_details = self._show_local_text(checked, ground["text_parameters_ref"])
        self.metadata_text.setPlainText(
            f"动作：{ground['semantic_action']}\n目标：{ground['element_ref']}\n"
            f"状态：{ground['source_state_id']} → {ground['target_state_id']}\n\n"
            f"{scroll_details}"
            f"HWND：{preview['target_window_handle']}\nPID：{preview['target_process_id']}\n"
            f"资产：{ground['asset_id']}\n资产 SHA-256：{ground['asset_content_sha256']}\n"
            f"审核限定：{ground['reviewed_revision_hash']}\n\n"
            f"capture：{lineage['capture_id']}\n截图 SHA-256：{lineage['screenshot_sha256']}\n"
            f"视口尺寸：{image.width()} × {image.height()}\n识别框：{bbox}\n{point_label}：{point}\n"
            f"confidence：{ground['confidence']}\nscore_margin：{ground['score_margin']}\n\n"
            f"Gate 已验证（无额外理由文本）：\n{ground['gate_decision_ref']}\n\n"
            f"confirmation：{checked['confirmation_id']}\n预检 SHA-256：{preview['content_sha256']}\n"
            f"请求时间：{checked['requested_at']}\n到期时间：{checked['expires_at']}\n\n"
            "识别不正确：取消本次，回审核工作区修改或交给 Agent 重学。\n批准不执行；执行仍须新截图、Gate 和执行后验证。"
        )
        self._review = checked

    def _show_local_text(self, checked, reference):
        """两类来源共用本地只读原值与准确新值展示。"""
        resolved = checked["text_input_local"]
        mode = "清空后替换" if reference["clear_existing"] else "保留原内容，在字段光标处插入（不保证是追加）"
        source = "固定内容" if reference["source_kind"] == "literal" else f"变量 {reference['variable_name']}"
        self.text_value_editor.setPlainText(resolved.text)
        self.text_value_editor.show()
        self.text_value_label.show()
        if "text_field_local" in checked:
            expected = checked["text_field_local"]
            self.text_before_editor.setPlainText(expected.before.value)
            self.text_expected_editor.setPlainText(expected.expected_value)
            self.text_before_editor.show()
            self.text_before_label.show()
            self.text_expected_editor.show()
            self.text_expected_label.show()
        return f"字段：{reference['target_field_id']}\n来源：{source}\n写入方式：{mode}\n本次字符数：{len(resolved.text)}\n空值：{'是' if not resolved.text else '否'}\n不按 Enter，不提交。\n\n"

    def _set_fresh_review(self, checked: dict, image: QImage) -> None:
        """显示首次学习的原始证据，明确它不是审核资产或执行授权。"""

        preview = checked["preview"]
        evidence, candidate_id, bbox, point = _fresh_geometry(preview)
        scene = self.view.scene()
        scene.addPixmap(QPixmap.fromImage(image))
        pen = QPen(QColor("#147d92"), 2.0)
        pen.setCosmetic(True)
        rect = scene.addRect(0, 0, bbox["w"], bbox["h"], pen, QColor(20, 125, 146, 28))
        rect.setPos(bbox["x"], bbox["y"])
        rect.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        rect.setZValue(1)
        cross_pen = QPen(QColor("#aa3b13"), 2.0)
        cross_pen.setCosmetic(True)
        x, y = point["x"], point["y"]
        for coords in ((x - 8, y, x + 8, y), (x, y - 8, x, y + 8)):
            cross = scene.addLine(*coords, cross_pen)
            cross.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            cross.setZValue(2)
        scene.setSceneRect(QRectF(0, 0, image.width(), image.height()))
        self.view.fit_image()
        capture = evidence["capture"]
        target = evidence["target"]
        application = evidence["application"]
        if application.get("kind") == "web":
            application_label = f"应用来源（Web）：{application['canonical_origin']}"
        elif application.get("kind") == "native":
            application_label = f"应用程序（Native）：{application['executable_path']}"
        else:
            raise ValueError("fresh preview application identity is invalid")
        intent = preview["intent"]
        decision = preview["pre_click_decision"]
        risk = preview["risk"]
        interception = preview_automatic_safety_interception(preview)
        safety_details = ("自动安全拦截：开启\n" if interception else
            "⚠ 自动安全拦截：已关闭（策略观察模式）\n"
            "下方保留原始策略判断，仅作提示；仍需操作者批准后单步执行。\n")
        reasons = ", ".join(risk.get("reasons", [])) or "无"
        text_details = self._show_local_text(checked, intent["text_parameters_ref"]) if intent["semantic_action"] == "fill_field" else ""
        if intent["semantic_action"] == "scroll_region":
            scroll = intent["scroll_parameters"]
            direction = "向上" if scroll["direction"] == "up" else "向下"
            text_details = (f"滚动容器：{scroll['target_container_id']}\n方向：{direction}\n"
                f"滚轮刻度：{scroll['wheel_clicks']}（wheel_detent）\n框为本次容器范围；不点击，不缩放地图。\n\n")
        learned_details = ''
        if 'learned_control' in intent:
            learned = intent['learned_control']
            selected = learned['reference']
            learned_details = (f"复用控件：{learned['region']['name']}\n"
                f"控件含义：{learned['region']['meaning']}\n"
                f"界面：{selected['interface_id']}\n版本：{selected['version_id']}\n"
                f"区域：{selected['region_id']}\n绑定 SHA-256：{learned['binding_sha256']}\n"
                '位置按当前画面重新定位，不直接使用学习时的坐标。\n\n')
        self.metadata_text.setPlainText(
            "首次学习 · 操作预览\n"
            "此预览来自当前观察，只供核对本次操作。保存学习内容不等于执行授权。\n\n"
            f"{safety_details}\n"
            f"Agent 目标：{intent['goal']}\n动作：{intent['semantic_action']}\n"
            f"{text_details}"
            f"{learned_details}"
            f"来源 SHA-256：{preview['source_sha256']}\n\n"
            f"{application_label}\nHWND：{target['window_handle']}\nPID：{target['process_id']}\n"
            f"capture：{capture['capture_id']}\n截图 SHA-256：{capture['screenshot_sha256']}\n"
            f"视口尺寸：{image.width()} × {image.height()}\n\n"
            f"候选：{candidate_id}\n识别框：{bbox}\n点击点：{point}\n"
            f"原始 Gate 判断：{'允许' if decision['allowed'] else '建议拦截'}\n"
            f"风险类别：{risk.get('risk_class', 'unknown')}\n原始风险拦截判断：{'是' if risk['hard_blocked'] else '否'}\n"
            f"风险事实：{reasons}\n\n"
            f"confirmation：{checked['confirmation_id']}\n预览 SHA-256：{preview['preview_sha256']}\n"
            f"请求时间：{checked['requested_at']}\n到期时间：{checked['expires_at']}\n\n"
            "批准不执行；当前模式已冻结在预览中，执行后事实与策略判断分别记录。"
        )
        self._review = checked
