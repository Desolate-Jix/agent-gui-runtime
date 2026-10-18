"""正式图修订的原生查看、证据核对与显式编辑面板。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .canvas import ReviewCanvas
from .graph_view import NativeWorkflowGraphView, friendly_action_label
from .graph_relearn_dialog import GraphRelearnDialog
from .jobs import FacadeJob, make_job
from .transitions import SubtleFadeTransition
from .friendly_controls import DetailsSection


class GraphReviewPane(QWidget):
    """只通过图 façade 读写；面板不拥有 façade 生命周期。"""

    revisionChanged = Signal(object)
    busyChanged = Signal(bool)
    dirtyChanged = Signal(bool)
    errorRaised = Signal(str)
    reviewRequested = Signal(object)

    def __init__(self, facade: Any, parent: QWidget | None = None, *, read_only: bool = False) -> None:
        super().__init__(parent)
        self.facade = facade
        self.read_only = bool(read_only)
        self._snapshot: dict[str, Any] | None = None
        self._selection: tuple[str, str] | None = None
        self._selected_region_id: str | None = None
        self._jobs: set[FacadeJob] = set()
        self._request_id = 0
        self._busy = False
        self._dirty = False
        self._evidence_valid = False
        self._updating_ui = False
        self._relearn_dialog: GraphRelearnDialog | None = None
        self._animations_enabled = True
        self._focus_workspace_sizes: list[int] | None = None
        self._focus_center_sizes: list[int] | None = None
        self.setObjectName("graphReviewPane")
        self._build_ui()
        self._selection_transition = SubtleFadeTransition(self.selection_title)
        self._set_controls()

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def animations_enabled(self) -> bool:
        return self._animations_enabled

    def set_animations_enabled(self, enabled: bool) -> None:
        """启停非阻塞文字过渡，不改变截图和审核状态。"""

        self._animations_enabled = bool(enabled)
        self._selection_transition.set_enabled(self._animations_enabled)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.identity_label = QLabel("尚未加载正式图修订")
        self.identity_label.setObjectName("graphRevisionIdentity")
        explaining = QLabel("① 查看界面与跳转    →    ② 修改并保存    →    ③ 人工审核后入库")
        self.explaining_label = explaining
        explaining.setProperty("role", "muted")
        explaining.setWordWrap(True)
        root.addWidget(self.identity_label)
        root.addWidget(explaining)
        self.guide_label = QLabel()
        self.guide_label.setObjectName("reviewNextStep")
        self.guide_label.setWordWrap(True)
        root.addWidget(self.guide_label)

        outer = QSplitter(Qt.Orientation.Horizontal)
        outer.setObjectName("graphWorkspaceSplitter")
        self.workspace_splitter = outer
        center = QSplitter(Qt.Orientation.Vertical)
        center.setObjectName("graphCenterSplitter")
        self.center_splitter = center
        graph_box = QGroupBox()
        graph_box.setObjectName("graphCard")
        self.graph_box = graph_box
        graph_layout = QVBoxLayout(graph_box)
        graph_header = QHBoxLayout()
        graph_title = QLabel("流程图")
        graph_title.setProperty("role", "sectionTitle")
        graph_fit = QPushButton("适合窗口")
        graph_fit.setObjectName("fitGraphButton")
        graph_fit.setMaximumWidth(84)
        graph_header.addWidget(graph_title)
        graph_header.addStretch(1)
        readable = QPushButton("清晰字号")
        readable.setObjectName("readableGraphButton")
        readable.setMaximumWidth(84)
        readable.setToolTip("放大至清晰字号，中键拖动平移；点适合窗口恢复完整概览")
        readable.clicked.connect(lambda: self.graph_view.readable_zoom())
        graph_header.addWidget(readable)
        graph_header.addWidget(graph_fit)
        graph_layout.addLayout(graph_header)
        self.graph_view = NativeWorkflowGraphView()
        self.graph_view.setObjectName("graphView")
        self.graph_view.setMinimumHeight(200)
        graph_layout.addWidget(self.graph_view, 1)
        graph_fit.clicked.connect(self.graph_view.fit_graph)
        center.addWidget(graph_box)

        evidence_splitter = QSplitter(Qt.Orientation.Horizontal)
        evidence_splitter.setObjectName("graphEvidenceSplitter")
        self.before_box, self.before_canvas, self.before_title_label = self._canvas_box(
            "原始截图", "beforeCanvas",
        )
        self.after_box, self.after_canvas, self.after_title_label = self._canvas_box(
            "动作后", "afterCanvas",
        )
        evidence_splitter.addWidget(self.before_box)
        evidence_splitter.addWidget(self.after_box)
        evidence_splitter.setChildrenCollapsible(False)
        evidence_splitter.setSizes([600, 600])
        self.after_box.hide()
        center.addWidget(evidence_splitter)
        center.setChildrenCollapsible(False)
        center.setStretchFactor(0, 2)
        center.setStretchFactor(1, 3)
        center.setSizes([265, 430])
        outer.addWidget(center)

        inspector_wrapper = QWidget()
        inspector_wrapper.setObjectName("graphInspectorWrapper")
        inspector_wrapper.setMinimumWidth(300)
        inspector_wrapper.setMaximumWidth(430)
        self.inspector_wrapper = inspector_wrapper
        inspector_wrapper_layout = QVBoxLayout(inspector_wrapper)
        inspector_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        inspector_wrapper_layout.setSpacing(0)

        inspector_scroll = QScrollArea()
        inspector_scroll.setObjectName("graphInspectorScroll")
        self.inspector_scroll = inspector_scroll
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inspector_scroll.setMinimumWidth(0)
        inspector = QWidget()
        inspector.setObjectName("graphInspector")
        inspector.setMinimumWidth(0)
        detail_layout = QVBoxLayout(inspector)
        detail_layout.setContentsMargins(14, 8, 14, 10)

        self.selection_title = QLabel("请选择节点或边")
        self.selection_title.setObjectName("graphSelectionTitle")
        self.selection_title.setWordWrap(True)
        detail_layout.addWidget(self.selection_title)
        self.editor_stack = QStackedWidget()
        self.editor_stack.setObjectName("graphEditorStack")
        self.editor_stack.setMinimumWidth(0)
        self.empty_editor = QLabel("先点上方的一个界面。这里会显示它的说明和可以修改的内容。")
        self.empty_editor.setProperty("role", "muted")
        self.empty_editor.setWordWrap(True)
        self.editor_stack.addWidget(self.empty_editor)
        self.editor_stack.addWidget(self._node_editor())
        self.editor_stack.addWidget(self._edge_editor())
        detail_layout.addWidget(self.editor_stack, 3)
        inspector_scroll.setWidget(inspector)
        inspector_wrapper_layout.addWidget(inspector_scroll, 1)

        footer = QWidget()
        footer.setObjectName("graphInspectorFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(14, 8, 14, 10)
        controls = QVBoxLayout()
        self.save_all_button = QPushButton("保存修改")
        self.save_all_button.setObjectName("saveAllGraphEditsButton")
        self.save_all_button.setProperty("role", "primary")
        self.save_all_button.setToolTip("一起保存当前界面或跳转的修改；任何一项无效都不写入")
        self.save_all_button.clicked.connect(self.save_all_changes)
        self.revert_button = QPushButton("放弃修改")
        self.revert_button.setObjectName("revertGraphEditsButton")
        self.revert_button.setToolTip("放弃未保存修改")
        self.revert_button.clicked.connect(self.revert_edits)
        self.review_graph_button = QPushButton("审核当前图")
        self.review_graph_button.setObjectName("reviewCurrentGraphButton")
        self.review_graph_button.setProperty("role", "primary")
        self.review_graph_button.clicked.connect(self.request_review)
        self.graph_relearn_button = QPushButton("标记问题 / 比较候选")
        self.graph_relearn_button.setObjectName("openGraphRelearnButton")
        self.graph_relearn_button.clicked.connect(self.open_graph_relearn)
        save_row = QHBoxLayout()
        save_row.addWidget(self.save_all_button, 2)
        save_row.addWidget(self.revert_button, 1)
        controls.addLayout(save_row)
        controls.addWidget(self.graph_relearn_button)
        controls.addWidget(self.review_graph_button)
        footer_layout.addLayout(controls)
        self.status_label = QLabel("尚未加载流程图")
        self.status_label.setObjectName("graphReviewStatus")
        self.status_label.setProperty("role", "muted")
        self.status_label.setWordWrap(True)
        footer_layout.addWidget(self.status_label)
        inspector_wrapper_layout.addWidget(footer, 0)
        outer.addWidget(inspector_wrapper)
        outer.setChildrenCollapsible(False)
        outer.setStretchFactor(0, 1)
        outer.setStretchFactor(1, 0)
        outer.setSizes([900, 340])
        root.addWidget(outer, 1)

        self.graph_view.nodeSelected.connect(self._node_selected)
        self.graph_view.edgeSelected.connect(self._edge_selected)
        self.before_canvas.regionSelected.connect(self._before_region_selected)
        self.before_canvas.regionGeometryChanged.connect(self._before_region_changed)
        self.after_canvas.regionGeometryChanged.connect(self._restore_after_region)
        if self.read_only:
            for button in (self.save_all_button, self.revert_button, self.review_graph_button, self.graph_relearn_button):
                button.hide()
            self.before_canvas.setInteractive(False)
            self.after_canvas.setInteractive(False)

    def _canvas_box(
        self, title: str, object_name: str,
    ) -> tuple[QGroupBox, ReviewCanvas, QLabel]:
        box = QGroupBox()
        box.setObjectName(f"{object_name}Card")
        layout = QVBoxLayout(box)
        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setProperty("role", "sectionTitle")
        title_label.setToolTip("当前图绑定的原始截图证据")
        title_label.setMinimumWidth(0)
        title_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        actual = QPushButton("100%")
        actual.setObjectName(f"{object_name}ActualSizeButton")
        actual.setMinimumWidth(64)
        actual.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        fit = QPushButton("适合")
        fit.setObjectName(f"{object_name}FitButton")
        fit.setMinimumWidth(52)
        fit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header.addWidget(title_label)
        header.addStretch(1)
        if object_name == "beforeCanvas":
            self.focus_screenshot_button = QPushButton("专注截图")
            self.focus_screenshot_button.setObjectName("focusScreenshotButton")
            self.focus_screenshot_button.setAccessibleName("切换专注截图视图")
            self.focus_screenshot_button.setCheckable(True)
            self.focus_screenshot_button.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed,
            )
            self.focus_screenshot_button.toggled.connect(self._toggle_screenshot_focus)
            header.addWidget(self.focus_screenshot_button)
        header.addWidget(actual)
        header.addWidget(fit)
        layout.addLayout(header)
        canvas = ReviewCanvas()
        canvas.setObjectName(object_name)
        canvas.setMinimumHeight(220)
        layout.addWidget(canvas, 1)
        actual.clicked.connect(canvas.show_actual_size)
        fit.clicked.connect(canvas.fit_image)
        return box, canvas, title_label

    def _toggle_screenshot_focus(self, checked: bool) -> None:
        """只调整现有控件可见性；不请求、替换或修改证据。"""

        if checked:
            self._focus_workspace_sizes = self.workspace_splitter.sizes()
            self._focus_center_sizes = self.center_splitter.sizes()
            self.graph_box.hide()
            self.inspector_wrapper.hide()
            self.focus_screenshot_button.setText("返回审核")
            return
        self.graph_box.show()
        self.inspector_wrapper.show()
        if self._focus_workspace_sizes:
            self.workspace_splitter.setSizes(self._focus_workspace_sizes)
        if self._focus_center_sizes:
            self.center_splitter.setSizes(self._focus_center_sizes)
        self.focus_screenshot_button.setText("专注截图")

    def _node_editor(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("nodeEditor")
        form = QFormLayout(widget)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.node_id_label = QLabel(widget)
        self.node_id_label.hide()
        self.node_id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.node_id_display_label = QLabel()
        self.node_id_display_label.setObjectName("nodeIdentityDisplay")
        self.node_id_display_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.node_id_display_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.node_meaning_edit = QLineEdit()
        self.node_meaning_edit.setObjectName("nodeMeaningEdit")
        self.node_region_combo = QComboBox()
        self.node_region_combo.setObjectName("nodeRegionCombo")
        self.node_region_bbox_edit = QLineEdit()
        self.node_region_bbox_edit.setObjectName("nodeRegionBboxEdit")
        self.node_region_bbox_edit.setPlaceholderText("x, y, width, height")
        self.node_recognition_text_edit = QLineEdit()
        self.node_recognition_text_edit.setObjectName("nodeRecognitionTextEdit")
        self.node_recognition_text_edit.setPlaceholderText("原始截图中实际可见的文字")
        self.node_recognition_bbox_edit = QLineEdit()
        self.node_recognition_bbox_edit.setObjectName("nodeRecognitionBboxEdit")
        self.node_recognition_bbox_edit.setPlaceholderText("x, y, width, height")
        self.save_node_meaning_button = QPushButton("保存节点含义")
        self.save_node_meaning_button.setObjectName("saveNodeMeaningButton")
        self.save_region_bbox_button = QPushButton("保存区域框")
        self.save_region_bbox_button.setObjectName("saveRegionBboxButton")
        self.save_node_recognition_button = QPushButton("保存识别文字")
        self.save_node_recognition_button.setObjectName("saveNodeRecognitionButton")
        form.addRow("这个界面是什么？", self.node_meaning_edit)
        form.addRow("检查哪个按钮 / 区域？", self.node_region_combo)
        hint = QLabel("选中截图里的框，拖动内部改位置，拖边角改大小。改完统一保存。")
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        form.addRow(hint)
        recognition = QWidget()
        recognition_form = QFormLayout(recognition)
        recognition_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        recognition_form.addRow("截图里真实可见的文字", self.node_recognition_text_edit)
        recognition_form.addRow("文字位置（x, y, 宽, 高）", self.node_recognition_bbox_edit)
        self.node_recognition_section = DetailsSection("修正识别文字（可选）", recognition)
        form.addRow(self.node_recognition_section)
        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        advanced_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        advanced_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        advanced_form.addRow("节点 ID", self.node_id_display_label)
        advanced_form.addRow("区域位置（x, y, 宽, 高）", self.node_region_bbox_edit)
        self.node_advanced = DetailsSection("精确坐标与技术信息", advanced)
        form.addRow(self.node_advanced)
        buttons = QWidget()
        buttons.setObjectName("nodeEditorButtons")
        row = QVBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.save_node_meaning_button)
        row.addWidget(self.save_region_bbox_button)
        row.addWidget(self.save_node_recognition_button)
        buttons.setParent(widget)
        buttons.hide()
        self.node_meaning_edit.textChanged.connect(self._refresh_dirty)
        self.node_region_bbox_edit.textChanged.connect(self._refresh_dirty)
        self.node_recognition_text_edit.textChanged.connect(self._refresh_dirty)
        self.node_recognition_bbox_edit.textChanged.connect(self._refresh_dirty)
        self.node_region_combo.currentIndexChanged.connect(self._node_region_changed)
        self.save_node_meaning_button.clicked.connect(self.save_node_meaning)
        self.save_region_bbox_button.clicked.connect(self.save_region_bbox)
        self.save_node_recognition_button.clicked.connect(self.save_node_recognition)
        return widget

    def _edge_editor(self) -> QWidget:
        body = QWidget()
        body.setObjectName("edgeEditor")
        form = QFormLayout(body)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.edge_id_label = QLabel(body)
        self.edge_id_label.hide()
        self.edge_id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.edge_id_display_label = QLabel()
        self.edge_id_display_label.setObjectName("edgeIdentityDisplay")
        self.edge_id_display_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.edge_id_display_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.edge_action_label = QLabel()
        self.edge_target_node_combo = QComboBox()
        self.edge_target_node_combo.setObjectName("edgeTargetNodeCombo")
        self.edge_target_region_combo = QComboBox()
        self.edge_target_region_combo.setObjectName("edgeTargetRegionCombo")
        self.edge_prerequisites_edit = QPlainTextEdit()
        self.edge_prerequisites_edit.setObjectName("edgePrerequisitesEdit")
        self.edge_prerequisites_edit.setMaximumHeight(64)
        self.edge_conditions_plain = QPlainTextEdit()
        self.edge_conditions_plain.setObjectName("edgeConditionsPlain")
        self.edge_conditions_plain.setPlaceholderText("一行一个条件，例如：资料列表已经加载")
        self.edge_conditions_plain.setMaximumHeight(82)
        self.edge_conditions_plain.textChanged.connect(self._plain_conditions_changed)
        self.edge_prerequisites_edit.textChanged.connect(self._json_conditions_changed)
        self.edge_expected_result_edit = QLineEdit()
        self.edge_expected_result_edit.setObjectName("edgeExpectedResultEdit")
        self.edge_stop_condition_edit = QLineEdit()
        self.edge_stop_condition_edit.setObjectName("edgeStopConditionEdit")
        self.edge_relationship_kinds_edit = QPlainTextEdit()
        self.edge_relationship_kinds_edit.setObjectName("edgeRelationshipKindsEdit")
        self.edge_relationship_kinds_edit.setMaximumHeight(72)
        self.stale_semantics_label = QLabel()
        self.stale_semantics_label.setObjectName("staleGraphSemanticsWarning")
        self.stale_semantics_label.setWordWrap(True)
        self.save_edge_target_button = QPushButton("保存目标节点")
        self.save_edge_target_button.setObjectName("saveEdgeTargetButton")
        self.save_edge_semantics_button = QPushButton("保存边语义")
        self.save_edge_semantics_button.setObjectName("saveEdgeSemanticsButton")
        form.addRow("这一步做什么", self.edge_action_label)
        form.addRow("完成后到哪个界面？", self.edge_target_node_combo)
        form.addRow("查看操作位置（只高亮）", self.edge_target_region_combo)
        form.addRow("开始前需要什么？（一行一条）", self.edge_conditions_plain)
        form.addRow("怎样算完成？", self.edge_expected_result_edit)
        form.addRow("遇到什么情况要停下？", self.edge_stop_condition_edit)
        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        advanced_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        advanced_form.addRow("边 ID", self.edge_id_display_label)
        advanced_form.addRow("前置条件（JSON 数组）", self.edge_prerequisites_edit)
        advanced_form.addRow("关系类别（JSON 对象）", self.edge_relationship_kinds_edit)
        self.edge_advanced = DetailsSection("技术信息与关系配置", advanced)
        advanced_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow(self.edge_advanced)
        form.addRow(self.stale_semantics_label)
        buttons = QWidget()
        buttons.setObjectName("edgeEditorButtons")
        row = QVBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.save_edge_target_button)
        row.addWidget(self.save_edge_semantics_button)
        buttons.setParent(body)
        buttons.hide()
        for signal in (
            self.edge_target_node_combo.currentIndexChanged,
            self.edge_prerequisites_edit.textChanged,
            self.edge_expected_result_edit.textChanged,
            self.edge_stop_condition_edit.textChanged,
            self.edge_relationship_kinds_edit.textChanged,
        ):
            signal.connect(self._refresh_dirty)
        self.edge_target_region_combo.currentIndexChanged.connect(self._edge_region_changed)
        self.save_edge_target_button.clicked.connect(self.save_edge_target)
        self.save_edge_semantics_button.clicked.connect(self.save_edge_semantics)
        return body

    def _plain_conditions_changed(self) -> None:
        if self._updating_ui:
            return
        values = [line.strip() for line in self.edge_conditions_plain.toPlainText().splitlines() if line.strip()]
        self.edge_prerequisites_edit.blockSignals(True)
        self.edge_prerequisites_edit.setPlainText(json.dumps(values, ensure_ascii=False))
        self.edge_prerequisites_edit.blockSignals(False)
        self._refresh_dirty()

    def _json_conditions_changed(self) -> None:
        if self._updating_ui:
            return
        try:
            values = json.loads(self.edge_prerequisites_edit.toPlainText())
        except json.JSONDecodeError:
            self.edge_conditions_plain.setEnabled(False)
            return
        valid = isinstance(values, list) and all(isinstance(value, str) for value in values)
        self.edge_conditions_plain.setEnabled(valid and not self.read_only)
        if valid:
            self.edge_conditions_plain.blockSignals(True)
            self.edge_conditions_plain.setPlainText("\n".join(values))
            self.edge_conditions_plain.blockSignals(False)

    def load_graph(self, logical_workflow_id: str) -> None:
        if self._busy:
            self._error("已有图操作正在进行，请稍候。")
            return
        if self._dirty:
            self._error("存在未保存修改；请先保存或放弃，再加载其他图。")
            return
        self._start(
            lambda: self.facade.load_graph_revision(logical_workflow_id, None),
            lambda result: self.set_revision(result),
            "正在加载正式图修订…",
        )

    def set_revision(
        self, snapshot: dict[str, Any], *, initial_selection: tuple[str, str] | None = None,
    ) -> bool:
        if self._busy:
            self._error("图操作仍在进行；拒绝并发替换当前正式修订。")
            return False
        if self._dirty:
            self._error("存在未保存修改；拒绝替换当前图，请先保存或放弃修改。")
            return False
        if initial_selection is not None:
            if (not isinstance(initial_selection, tuple) or len(initial_selection) != 2
                    or initial_selection[0] not in {"node", "edge"}
                    or not isinstance(initial_selection[1], str) or not isinstance(snapshot, dict)):
                self._error("初始图对象选择无效；当前内容未替换。")
                return False
            kind, identity = initial_selection
            graph = snapshot.get("graph")
            objects = graph.get("nodes" if kind == "node" else "edges", []) if isinstance(graph, dict) else []
            if not isinstance(objects, list) or not any(
                isinstance(item, dict) and item.get(kind + "_id") == identity for item in objects
            ):
                self._error("初始图对象不属于该修订；当前内容未替换。")
                return False
        return self._install_revision(snapshot, initial_selection=initial_selection)

    def _install_revision(
        self, snapshot: dict[str, Any], *, initial_selection: tuple[str, str] | None = None,
    ) -> bool:
        previous = initial_selection if initial_selection is not None else self._selection
        try:
            self.graph_view.set_revision(snapshot)
        except (TypeError, ValueError) as error:
            self._error(f"图修订响应无效：{error}")
            return False
        self._snapshot = deepcopy(snapshot)
        action_only = snapshot.get("source_refs", {}).get("kind") == "recorded_actions"
        label = "操作证据图" if action_only else "正式流程图"
        self.identity_label.setText(f"{label} · 修订 {snapshot['revision']}")
        self.explaining_label.setText(
            "① 查看操作前后原图    →    ② 修改说明并保存 · 不等于已学会完整界面"
            if action_only else "① 查看界面与跳转    →    ② 修改并保存    →    ③ 人工审核后入库"
        )
        self.identity_label.setToolTip(
            f"{snapshot['logical_workflow_id']} · 修订 {snapshot['revision']} · {snapshot['content_sha256']}"
        )
        self._set_dirty(False)
        selection = previous if self._selection_exists(previous) else self._default_selection()
        self.revisionChanged.emit(deepcopy(self._snapshot))
        if selection is None:
            self._selection = None
            self.editor_stack.setCurrentIndex(0)
            self._invalidate_evidence(clear=True)
            return True
        self._activate_selection(selection, request_evidence=True)
        return True

    def request_review(self) -> None:
        if self.read_only:
            self._error("这是已发布版本的只读查看，不会审核或修改。")
            return
        if self._snapshot is None or self._busy:
            return
        if not self._evidence_valid:
            self._error("当前选择没有通过校验的原始截图证据，不能进入审核。")
            return
        if self._dirty:
            self._error("存在未保存修改；请先保存或放弃，再审核当前图。")
            return
        self.reviewRequested.emit(deepcopy(self._snapshot))

    def open_graph_relearn(self) -> None:
        if self.read_only:
            self._error("这是已发布版本的只读查看，不会提交重学。")
            return
        if self._snapshot is None or self._selection is None:
            self._error("请先加载图并选择节点或边。")
            return
        if self._busy:
            self._error("已有图操作正在进行，请稍候。")
            return
        if self._dirty:
            self._error("存在未保存修改；请先保存或放弃，再标记图内问题。")
            return
        if not self._evidence_valid:
            self._error("当前选择没有通过校验的原始截图证据，不能标记图内问题。")
            return
        if self._relearn_dialog is not None:
            self._relearn_dialog.raise_()
            self._relearn_dialog.activateWindow()
            return
        dialog = GraphRelearnDialog(
            self.facade,
            deepcopy(self._snapshot),
            self._selection,
            self,
        )
        self._relearn_dialog = dialog
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.revisionAdopted.connect(self._relearn_adopted)
        dialog.finished.connect(
            lambda _result, owned=dialog: self._relearn_closed(owned)
        )
        dialog.open()

    def _relearn_adopted(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict):
            self._error("图重学采用返回格式无效；当前图未替换。")
            return
        self._install_revision(snapshot)
        self.status_label.setText("已采用候选并加载新的图草稿；仍未审核、发布或执行。")

    def _relearn_closed(self, dialog: GraphRelearnDialog) -> None:
        if self._relearn_dialog is dialog:
            self._relearn_dialog = None
        dialog.deleteLater()

    def revert_edits(self) -> None:
        if self._snapshot is None or self._selection is None:
            return
        self._activate_selection(self._selection, request_evidence=False)
        self.status_label.setText("已放弃未保存修改；正式图修订未改变。")

    def save_node_meaning(self) -> None:
        node = self._selected_node()
        if node is None or self._busy:
            return
        if not self._evidence_valid:
            self._error("当前节点证据不可用，拒绝保存。")
            return
        if self._region_dirty(node) or self._recognition_dirty(node):
            self._error("区域框或识别文字有未保存修改；一次只保存一种图修改，请先保存或放弃其他字段。")
            return
        meaning = self.node_meaning_edit.text().strip()
        if not meaning:
            self._error("节点含义不能为空。")
            return
        if meaning == str(node.get("display_name") or ""):
            return
        self._apply({"type": "update_node_meaning", "node_id": node["node_id"], "meaning": meaning})

    def save_region_bbox(self) -> None:
        node = self._selected_node()
        if node is None or self._busy:
            return
        if not self._evidence_valid:
            self._error("当前节点证据不可用，拒绝保存。")
            return
        if self._meaning_dirty(node) or self._recognition_dirty(node):
            self._error("节点含义或识别文字有未保存修改；一次只保存一种图修改，请先保存或放弃其他字段。")
            return
        region_id = self.node_region_combo.currentData()
        try:
            bbox = _parse_bbox(self.node_region_bbox_edit.text())
        except ValueError as error:
            self._error(str(error))
            return
        if not isinstance(region_id, str):
            self._error("请选择要保存的区域。")
            return
        self._apply({"type": "update_region_bbox", "node_id": node["node_id"], "region_id": region_id, "bbox": bbox})

    def save_node_recognition(self) -> None:
        node = self._selected_node()
        if node is None or self._busy:
            return
        if not self._evidence_valid:
            self._error("当前节点证据不可用，拒绝保存识别文字。")
            return
        if self._meaning_dirty(node) or self._region_dirty(node):
            self._error("节点含义或区域框有未保存修改；一次只保存一种图修改。")
            return
        text = self.node_recognition_text_edit.text().strip()
        if not text:
            self._error("识别文字不能为空。")
            return
        if len(text) > 4000:
            self._error("识别文字不能超过 4000 个字符。")
            return
        try:
            bbox = _parse_bbox(self.node_recognition_bbox_edit.text())
        except ValueError as error:
            self._error(str(error))
            return
        if not self._bbox_is_in_current_image(bbox):
            self._error("识别文字框必须位于当前已验证的原始截图内。")
            return
        source = self._recognition_source(node)
        if source is None:
            self._error("当前节点原始截图绑定不可用或已过期，拒绝保存识别文字。")
            return
        if text == node.get("recognition_text") and bbox == _recognition_bbox(node):
            return
        path, digest = source
        self._apply({
            "type": "update_node_recognition_text",
            "node_id": node["node_id"],
            "recognition_text": text,
            "source_screenshot_path": path,
            "source_screenshot_sha256": digest,
            "bbox": bbox,
        })

    def save_edge_target(self) -> None:
        edge = self._selected_edge()
        if edge is None or self._busy:
            return
        if not self._evidence_valid:
            self._error("当前边两端证据不可用，拒绝保存。")
            return
        if self._edge_semantics_dirty(edge):
            self._error("边语义也有未保存修改；一次只保存一种图修改，请先保存或放弃语义。")
            return
        target = self.edge_target_node_combo.currentData()
        if not isinstance(target, str):
            self._error("请选择目标节点。")
            return
        if target == edge.get("target_node_id"):
            return
        self._apply({"type": "update_edge_target", "edge_id": edge["edge_id"], "target_node_id": target})

    def save_edge_semantics(self) -> None:
        edge = self._selected_edge()
        if edge is None or self._busy:
            return
        if not self._evidence_valid:
            self._error("当前边两端证据不可用，拒绝保存。")
            return
        if self.edge_target_node_combo.currentData() != edge.get("target_node_id"):
            self._error("目标节点也有未保存修改；一次只保存一种图修改，请先保存或放弃目标节点。")
            return
        try:
            prerequisites = json.loads(self.edge_prerequisites_edit.toPlainText())
            relationships = json.loads(self.edge_relationship_kinds_edit.toPlainText())
        except json.JSONDecodeError as error:
            self._error(f"边语义 JSON 无效：{error.msg}")
            return
        if not isinstance(prerequisites, list) or any(not isinstance(item, str) for item in prerequisites):
            self._error("前置条件必须是字符串 JSON 数组。")
            return
        if not isinstance(relationships, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in relationships.items()):
            self._error("关系类别必须是字符串到字符串的 JSON 对象。")
            return
        expected = self.edge_expected_result_edit.text().strip()
        stopped = self.edge_stop_condition_edit.text().strip()
        if not expected or not stopped:
            self._error("预期结果和停止条件不能为空。")
            return
        self._apply({
            "type": "update_edge_semantics",
            "edge_id": edge["edge_id"],
            "expected_result": expected,
            "stop_condition": stopped,
            "prerequisites": prerequisites,
            "relationship_kinds": relationships,
        })

    def _apply(self, operation: dict[str, Any]) -> None:
        if self.read_only:
            self._error("这是已发布版本的只读查看，不能保存修改。")
            return
        snapshot = self._snapshot
        if snapshot is None:
            return
        logical_id = snapshot["logical_workflow_id"]
        revision = snapshot["revision"]
        digest = snapshot["content_sha256"]
        self._start(
            lambda: self.facade.apply_graph_edit(
                logical_id, revision, digest, deepcopy(operation), uuid4().hex,
            ),
            self._edit_completed,
            "正在保存一项图修改…",
        )

    def save_all_changes(self) -> None:
        if self.read_only:
            self._error("这是已发布版本的只读查看，不能保存修改。")
            return
        if self._busy or self._snapshot is None or not self._dirty:
            return
        if not self._evidence_valid:
            self._error("截图证据尚未就绪，不能保存；当前输入会保留。")
            return
        try:
            operations = self._pending_operations()
        except (ValueError, TypeError) as error:
            self._error(f"尚未保存：{error}。请修正后重试，当前输入已保留。")
            return
        if not operations:
            return
        save = getattr(self.facade, "apply_graph_edits", None)
        if not callable(save):
            self._error("当前宿主尚未支持统一保存，请更新宿主；不会退回部分保存。")
            return
        snapshot = self._snapshot
        self._start(
            lambda: save(snapshot["logical_workflow_id"], snapshot["revision"],
                         snapshot["content_sha256"], deepcopy(operations), uuid4().hex),
            self._edit_completed, "正在一起保存当前修改…",
        )

    def _pending_operations(self) -> list[dict[str, Any]]:
        operations = []
        node = self._selected_node()
        edge = self._selected_edge()
        if node is not None:
            node_id = node["node_id"]
            if self._meaning_dirty(node):
                meaning = self.node_meaning_edit.text().strip()
                if not meaning:
                    raise ValueError("界面说明不能为空")
                operations.append({"type": "update_node_meaning", "node_id": node_id, "meaning": meaning})
            if self._region_dirty(node):
                bbox = _parse_bbox(self.node_region_bbox_edit.text())
                if not self._bbox_is_in_current_image(bbox):
                    raise ValueError("区域框超出了当前原图")
                operations.append({"type": "update_region_bbox", "node_id": node_id,
                                   "region_id": self.node_region_combo.currentData(), "bbox": bbox})
            if self._recognition_dirty(node):
                text = self.node_recognition_text_edit.text().strip()
                if not text or len(text) > 4000:
                    raise ValueError("识别文字需要填写 1–4000 个原图中可见的字符")
                bbox = _parse_bbox(self.node_recognition_bbox_edit.text())
                source = self._recognition_source(node)
                if not self._bbox_is_in_current_image(bbox) or source is None:
                    raise ValueError("识别文字框或截图来源无效")
                operations.append({"type": "update_node_recognition_text", "node_id": node_id,
                                   "recognition_text": text, "bbox": bbox,
                                   "source_screenshot_path": source[0], "source_screenshot_sha256": source[1]})
        elif edge is not None:
            if self.edge_target_node_combo.currentData() != edge.get("target_node_id"):
                operations.append({"type": "update_edge_target", "edge_id": edge["edge_id"],
                                   "target_node_id": self.edge_target_node_combo.currentData()})
            if self._edge_semantics_dirty(edge):
                prerequisites = json.loads(self.edge_prerequisites_edit.toPlainText())
                relationships = json.loads(self.edge_relationship_kinds_edit.toPlainText())
                if not isinstance(prerequisites, list) or any(not isinstance(item, str) for item in prerequisites):
                    raise ValueError("前置条件必须是一组文字条件")
                if not isinstance(relationships, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in relationships.items()):
                    raise ValueError("高级关系配置必须是文字键和值")
                expected = self.edge_expected_result_edit.text().strip()
                stopped = self.edge_stop_condition_edit.text().strip()
                if not expected or not stopped:
                    raise ValueError("完成结果和停止条件不能为空")
                operations.append({"type": "update_edge_semantics", "edge_id": edge["edge_id"],
                                   "prerequisites": prerequisites, "relationship_kinds": relationships,
                                   "expected_result": expected, "stop_condition": stopped})
        return operations

    def _edit_completed(self, result: dict[str, Any]) -> None:
        self._install_revision(result)
        if self._snapshot is result or self._snapshot == result:
            self.status_label.setText("图修改已保存为新的正式修订。")

    def _node_selected(self, node_id: str) -> None:
        self._selection_requested(("node", node_id))

    def _edge_selected(self, edge_id: str) -> None:
        self._selection_requested(("edge", edge_id))

    def _selection_requested(self, selection: tuple[str, str]) -> None:
        if self._busy:
            self._restore_graph_selection()
            self._error("正在读取或保存当前内容，请完成后再切换。")
            return
        if self._dirty:
            self._restore_graph_selection()
            self._error("当前字段有未保存修改；请保存或点击“放弃未保存修改”后再切换。")
            return
        self._activate_selection(selection, request_evidence=True)

    def _activate_selection(self, selection: tuple[str, str], *, request_evidence: bool) -> None:
        if not self._selection_exists(selection):
            self._error("所选图对象在当前修订中不存在。")
            return
        changed = selection != self._selection
        self._selection = selection
        if changed:
            self._invalidate_evidence(clear=True)
        elif request_evidence:
            self._invalidate_evidence(clear=False)
        if selection[0] == "node":
            self.graph_view.select_node(selection[1])
            self._populate_node(self._selected_node())
        else:
            self.graph_view.select_edge(selection[1])
            self._populate_edge(self._selected_edge())
        self._set_dirty(False)
        if request_evidence:
            self._request_selection_evidence()
        else:
            self._set_controls()

    def _request_selection_evidence(self) -> None:
        snapshot, selection = self._snapshot, self._selection
        if snapshot is None or selection is None or self._busy:
            return
        logical_id, revision, digest = (
            snapshot["logical_workflow_id"], snapshot["revision"], snapshot["content_sha256"],
        )
        if selection[0] == "node":
            node_id = selection[1]
            operation = lambda: {
                "kind": "node",
                "selection": selection,
                "evidence": self.facade.load_graph_node_evidence(logical_id, revision, digest, node_id),
            }
        else:
            edge = self._selected_edge()
            if edge is None:
                return
            source_id, target_id = edge["source_node_id"], edge["target_node_id"]
            operation = lambda: {
                "kind": "edge",
                "selection": selection,
                "source": self.facade.load_graph_node_evidence(logical_id, revision, digest, source_id),
                "target": self.facade.load_graph_node_evidence(logical_id, revision, digest, target_id),
            }
        self._invalidate_evidence(clear=False)
        self._start(
            operation, self._evidence_completed,
            "正在读取当前图绑定的原始截图…", evidence_request=True,
        )

    def _evidence_completed(self, result: dict[str, Any]) -> None:
        if result.get("selection") != self._selection:
            self._error("截图响应已过期，未替换当前证据。")
            return
        if result.get("kind") == "node":
            evidence = self._validated_evidence(result.get("evidence"), self._selection[1])
            self._show_evidence(self.before_canvas, evidence)
            self.before_canvas.select_region(self._selected_region_id)
            self.after_canvas.clear_canvas()
        elif result.get("kind") == "edge":
            edge = self._selected_edge()
            if edge is None:
                raise ValueError("edge evidence has no selected edge")
            source = self._validated_evidence(result.get("source"), edge["source_node_id"])
            target = self._validated_evidence(result.get("target"), edge["target_node_id"])
            self._show_evidence(self.before_canvas, source)
            self._show_evidence(self.after_canvas, target)
            self._edge_region_changed()
        else:
            raise ValueError("graph evidence response kind is invalid")
        self._evidence_valid = True
        self._set_controls()
        self.status_label.setText("已加载当前图修订绑定的原始截图和区域。")
        self._selection_transition.play()

    def _invalidate_evidence(self, *, clear: bool) -> None:
        self._evidence_valid = False
        if clear:
            self.before_canvas.clear_canvas()
            self.after_canvas.clear_canvas()
        self._set_controls()

    def _validated_evidence(self, value: Any, node_id: str) -> dict[str, Any]:
        fields = {
            "contract_version", "logical_workflow_id", "graph_revision", "graph_sha256",
            "node", "screenshot", "artifact_is_authorization", "execute_binding_enabled",
        }
        snapshot = self._snapshot
        if not isinstance(value, dict) or set(value) != fields or snapshot is None:
            raise ValueError("graph node evidence shape is invalid")
        expected_node = self._node_by_id(node_id)
        if (
            value.get("contract_version") != "formal_graph_node_evidence_v1"
            or value.get("logical_workflow_id") != snapshot["logical_workflow_id"]
            or value.get("graph_revision") != snapshot["revision"]
            or value.get("graph_sha256") != snapshot["content_sha256"]
            or value.get("node") != expected_node
            or value.get("artifact_is_authorization") is not False
            or value.get("execute_binding_enabled") is not False
        ):
            raise ValueError("graph node evidence identity is invalid")
        shot = value.get("screenshot")
        if not isinstance(shot, dict) or set(shot) != {"screenshot_id", "sha256", "width", "height", "png_bytes"}:
            raise ValueError("graph screenshot evidence shape is invalid")
        raw = shot.get("png_bytes")
        if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != shot.get("sha256"):
            raise ValueError("graph screenshot digest is invalid")
        image = QImage.fromData(raw, "PNG")
        if (
            image.isNull() or isinstance(shot.get("width"), bool) or isinstance(shot.get("height"), bool)
            or shot.get("width") != image.width() or shot.get("height") != image.height()
        ):
            raise ValueError("graph screenshot dimensions are invalid")
        source_refs = snapshot.get("source_refs", {})
        if "interface_reference" in expected_node:
            # 独立界面按精确版本绑定原图，不冒充旧批次截图引用。
            ref = expected_node["interface_reference"]
            members = source_refs.get(
                "interfaces" if source_refs.get("kind") == "interface_composition" else "interface_composition", []
            )
            pinned = expected_node.get("interface_evidence", {})
            origin = expected_node.get("evidence", {})
            if (
                not isinstance(members, list) or members.count(ref) != 1
                or not isinstance(pinned, dict) or not isinstance(origin, dict)
                or not pinned.get("image_path")
                or pinned.get("image_path") != origin.get("source_screenshot_path")
                or shot["screenshot_id"] != origin.get("source_screenshot_id")
                or shot["sha256"] != origin.get("source_screenshot_sha256")
                or any(shot[key] != pinned.get(key) for key in ("sha256", "width", "height"))
            ):
                raise ValueError("graph interface screenshot source binding is invalid")
            _validate_regions(expected_node.get("regions"), image.width(), image.height())
            return deepcopy(value)
        refs = list(source_refs.get("screenshots", []))
        for source in source_refs.get("additional_sources", []):
            if isinstance(source, dict):
                refs.extend(source.get("screenshots", []))
        for source in source_refs.get("action_sources", []):
            if isinstance(source, dict):
                refs.extend(source.get("screenshots", []))
        source_path = expected_node.get("evidence", {}).get("source_screenshot_path")
        references = [item for item in refs if isinstance(item, dict) and item.get("path") == source_path]
        # 多个动作可共享同一像素原件；重复引用必须完全一致，不能合并冲突元数据。
        if (not references or any(item != references[0] for item in references[1:])
                or any(shot.get(key) != references[0].get(key) for key in ("screenshot_id", "sha256", "width", "height"))):
            raise ValueError("graph screenshot source binding is invalid")
        _validate_regions(expected_node.get("regions"), image.width(), image.height())
        return deepcopy(value)

    def _show_evidence(self, canvas: ReviewCanvas, evidence: dict[str, Any]) -> None:
        shot, node = evidence["screenshot"], evidence["node"]
        canvas.set_image(
            shot["png_bytes"], node.get("regions", []),
            (evidence["logical_workflow_id"], node["node_id"], shot["screenshot_id"]),
        )

    def _populate_node(self, node: dict[str, Any] | None) -> None:
        if node is None:
            return
        self._updating_ui = True
        try:
            self.editor_stack.setCurrentIndex(1)
            self._set_evidence_mode("node")
            self.selection_title.setText(
                f"界面：{node.get('display_name') or _compact_identity(node['node_id'])}"
            )
            self.selection_title.setToolTip(node["node_id"])
            self.node_id_label.setText(node["node_id"])
            self.node_id_display_label.setText(_compact_identity(node["node_id"]))
            self.node_id_display_label.setToolTip(node["node_id"])
            self.node_meaning_edit.setText(str(node.get("display_name") or ""))
            self.node_recognition_text_edit.setText(str(node.get("recognition_text") or ""))
            self.node_recognition_bbox_edit.setText(_bbox_text(_recognition_bbox(node)))
            self.node_region_combo.clear()
            for region in node.get("regions", []):
                self.node_region_combo.addItem(
                    str(
                        region.get("name") or region.get("semantic_name")
                        or _compact_identity(region["region_id"])
                    ),
                    region["region_id"],
                )
            if self.node_region_combo.count():
                wanted = self._selected_region_id
                index = self.node_region_combo.findData(wanted) if wanted else 0
                self.node_region_combo.setCurrentIndex(max(0, index))
                self._selected_region_id = self.node_region_combo.currentData()
                self._set_node_bbox_text()
            else:
                self._selected_region_id = None
                self.node_region_bbox_edit.clear()
        finally:
            self._updating_ui = False
        self._set_controls()

    def _populate_edge(self, edge: dict[str, Any] | None) -> None:
        if edge is None or self._snapshot is None:
            return
        nodes = self._snapshot["graph"]["nodes"]
        source = self._node_by_id(edge["source_node_id"])
        self._updating_ui = True
        try:
            self.editor_stack.setCurrentIndex(2)
            self._set_evidence_mode("edge")
            raw_action = str(edge.get("external_declared_action_type") or edge.get("action_type") or "")
            action_name = friendly_action_label(raw_action)
            self.selection_title.setText(
                f"跳转：{edge.get('display_name') or action_name}"
            )
            self.selection_title.setToolTip(edge["edge_id"])
            self.edge_id_label.setText(edge["edge_id"])
            self.edge_id_display_label.setText(_compact_identity(edge["edge_id"]))
            self.edge_id_display_label.setToolTip(edge["edge_id"])
            declared_only = edge.get("action_type") != raw_action
            self.edge_action_label.setText(action_name + ("（Agent 声明，待核对）" if declared_only else ""))
            self.edge_action_label.setWordWrap(True)
            self.edge_action_label.setToolTip(raw_action)
            self.edge_target_node_combo.clear()
            for node in nodes:
                self.edge_target_node_combo.addItem(
                    str(node.get("display_name") or _compact_identity(node["node_id"])),
                    node["node_id"],
                )
            self.edge_target_node_combo.setCurrentIndex(self.edge_target_node_combo.findData(edge["target_node_id"]))
            self.edge_target_region_combo.clear()
            for region in source.get("regions", []):
                self.edge_target_region_combo.addItem(
                    str(
                        region.get("name") or region.get("semantic_name")
                        or _compact_identity(region["region_id"])
                    ),
                    region["region_id"],
                )
            target_region = edge.get("target_region_id") or edge.get("target_control_id")
            index = self.edge_target_region_combo.findData(target_region)
            self.edge_target_region_combo.setCurrentIndex(index if index >= 0 else -1)
            self.edge_prerequisites_edit.setPlainText(_json(edge.get("preconditions") or []))
            self.edge_conditions_plain.setPlainText("\n".join(edge.get("preconditions") or []))
            self.edge_expected_result_edit.setText(_first_text(edge.get("success_conditions")))
            self.edge_stop_condition_edit.setText(_first_text(edge.get("failure_conditions")))
            relationships = {
                item["relationship_id"]: item.get("kind", "")
                for item in edge.get("external_relationships", [])
            }
            self.edge_relationship_kinds_edit.setPlainText(_json(relationships))
            stale = (
                edge.get("target_semantics_status") == "stale_after_retarget"
                or edge.get("requires_semantic_review") is True
            )
            self.stale_semantics_label.setText(
                "目标节点已变更，需要修正边语义后再审核。" if stale else "边语义已与当前目标绑定。"
            )
        finally:
            self._updating_ui = False
        self._set_controls()

    def _set_evidence_mode(self, kind: str) -> None:
        """节点使用单张大图，边才显示前后两张原件。"""

        edge = kind == "edge"
        self.before_title_label.setText("动作前" if edge else "原始截图")
        self.before_title_label.setToolTip(
            "当前连线动作前绑定的原始截图证据" if edge else "当前界面绑定的原始截图证据"
        )
        self.after_title_label.setText("动作后")
        self.after_title_label.setToolTip("当前连线动作后绑定的原始截图证据")
        self.after_box.setVisible(edge)
        if edge:
            self.findChild(QSplitter, "graphEvidenceSplitter").setSizes([600, 600])

    def _node_region_changed(self) -> None:
        if self._updating_ui:
            return
        node = self._selected_node()
        if node is None:
            return
        if self._selected_region_id is not None and self._region_dirty_for(node, self._selected_region_id):
            self._updating_ui = True
            self.node_region_combo.setCurrentIndex(self.node_region_combo.findData(self._selected_region_id))
            self._updating_ui = False
            self._error("当前区域框有未保存修改；请先保存或放弃，再查看其他区域。")
            return
        self._selected_region_id = self.node_region_combo.currentData()
        self._set_node_bbox_text()
        self.before_canvas.select_region(self._selected_region_id)
        self._refresh_dirty()

    def _set_node_bbox_text(self) -> None:
        node = self._selected_node()
        region_id = self.node_region_combo.currentData()
        region = _find(node.get("regions", []) if node else [], "region_id", region_id)
        self.node_region_bbox_edit.setText(_bbox_text(region.get("bbox")) if region else "")

    def _before_region_selected(self, region_id: str) -> None:
        if self._selection is None:
            return
        combo = self.node_region_combo if self._selection[0] == "node" else self.edge_target_region_combo
        index = combo.findData(region_id)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _before_region_changed(self, region_id: str, bbox: list[float]) -> None:
        node = self._selected_node()
        if node is not None and (self.read_only or "interface_reference" in node):
            region = _find(node.get("regions", []), "region_id", region_id)
            if region:
                self.before_canvas.set_region_bbox(region_id, region["bbox"])
            return
        if self._selection is None or self._selection[0] != "node":
            self._restore_before_region(region_id)
            return
        if self.node_region_combo.currentData() != region_id:
            self.node_region_combo.setCurrentIndex(self.node_region_combo.findData(region_id))
        self.node_region_bbox_edit.setText(_bbox_text(bbox))

    def _restore_before_region(self, region_id: str) -> None:
        edge = self._selected_edge()
        if edge is None:
            return
        source = self._node_by_id(edge["source_node_id"])
        region = _find(source.get("regions", []), "region_id", region_id)
        if region:
            self.before_canvas.set_region_bbox(region_id, region["bbox"])

    def _restore_after_region(self, region_id: str, _bbox: list[float]) -> None:
        edge = self._selected_edge()
        if edge is None:
            return
        target = self._node_by_id(edge["target_node_id"])
        region = _find(target.get("regions", []), "region_id", region_id)
        if region:
            self.after_canvas.set_region_bbox(region_id, region["bbox"])

    def _edge_region_changed(self) -> None:
        if self._updating_ui:
            return
        region_id = self.edge_target_region_combo.currentData()
        self.before_canvas.select_region(region_id if isinstance(region_id, str) else None)

    def _restore_graph_selection(self) -> None:
        if self._selection is None:
            return
        if self._selection[0] == "node":
            self.graph_view.select_node(self._selection[1])
        else:
            self.graph_view.select_edge(self._selection[1])

    def _selected_node(self) -> dict[str, Any] | None:
        if self._selection is None or self._selection[0] != "node":
            return None
        return self._node_by_id(self._selection[1])

    def _selected_edge(self) -> dict[str, Any] | None:
        if self._selection is None or self._selection[0] != "edge" or self._snapshot is None:
            return None
        return _find(self._snapshot["graph"]["edges"], "edge_id", self._selection[1])

    def _node_by_id(self, node_id: str) -> dict[str, Any]:
        if self._snapshot is None:
            raise ValueError("graph revision is not loaded")
        node = _find(self._snapshot["graph"]["nodes"], "node_id", node_id)
        if node is None:
            raise ValueError("graph node is not present")
        return node

    def _selection_exists(self, selection: tuple[str, str] | None) -> bool:
        if selection is None or self._snapshot is None:
            return False
        collection = self._snapshot["graph"]["nodes" if selection[0] == "node" else "edges"]
        field = "node_id" if selection[0] == "node" else "edge_id"
        return _find(collection, field, selection[1]) is not None

    def _default_selection(self) -> tuple[str, str] | None:
        if self._snapshot is None:
            return None
        nodes = self._snapshot["graph"]["nodes"]
        return ("node", nodes[0]["node_id"]) if nodes else None

    def _meaning_dirty(self, node: dict[str, Any]) -> bool:
        return self.node_meaning_edit.text().strip() != str(node.get("display_name") or "")

    def _region_dirty(self, node: dict[str, Any]) -> bool:
        return self._region_dirty_for(node, self.node_region_combo.currentData())

    def _region_dirty_for(self, node: dict[str, Any], region_id: Any) -> bool:
        region = _find(node.get("regions", []), "region_id", region_id)
        if region is None:
            return False
        try:
            return _parse_bbox(self.node_region_bbox_edit.text()) != [float(value) for value in region["bbox"]]
        except (TypeError, ValueError):
            return self.node_region_bbox_edit.text().strip() != _bbox_text(region.get("bbox"))

    def _recognition_dirty(self, node: dict[str, Any]) -> bool:
        text = self.node_recognition_text_edit.text().strip()
        if text != str(node.get("recognition_text") or ""):
            return True
        try:
            return _parse_bbox(self.node_recognition_bbox_edit.text()) != _recognition_bbox(node)
        except ValueError:
            return self.node_recognition_bbox_edit.text().strip() != _bbox_text(_recognition_bbox(node))

    def _recognition_source(self, node: dict[str, Any]) -> tuple[str, str] | None:
        evidence = node.get("evidence")
        if not isinstance(evidence, dict):
            return None
        path = evidence.get("source_screenshot_path")
        digest = evidence.get("source_screenshot_sha256")
        if not isinstance(path, str) or not path or not isinstance(digest, str) or len(digest) != 64:
            return None
        refs = []
        source_refs = self._snapshot.get("source_refs", {}) if self._snapshot else {}
        refs.extend(source_refs.get("screenshots", []))
        for key in ("additional_sources", "action_sources"):
            for source in source_refs.get(key, []):
                if isinstance(source, dict):
                    refs.extend(source.get("screenshots", []))
        matches = [item for item in refs if isinstance(item, dict) and item.get("path") == path]
        if (not matches or any(item != matches[0] for item in matches[1:])
                or matches[0].get("sha256") != digest):
            return None
        return path, digest

    def _bbox_is_in_current_image(self, bbox: list[float]) -> bool:
        item = self.before_canvas._pixmap_item
        if item is None:
            return False
        image = item.pixmap()
        return bbox[0] + bbox[2] <= image.width() and bbox[1] + bbox[3] <= image.height()

    def _edge_semantics_dirty(self, edge: dict[str, Any]) -> bool:
        try:
            prerequisites = json.loads(self.edge_prerequisites_edit.toPlainText())
            relationships = json.loads(self.edge_relationship_kinds_edit.toPlainText())
        except json.JSONDecodeError:
            return True
        expected_relationships = {
            item["relationship_id"]: item.get("kind", "")
            for item in edge.get("external_relationships", [])
        }
        return any((
            prerequisites != (edge.get("preconditions") or []),
            self.edge_expected_result_edit.text().strip() != _first_text(edge.get("success_conditions")),
            self.edge_stop_condition_edit.text().strip() != _first_text(edge.get("failure_conditions")),
            relationships != expected_relationships,
        ))

    def _refresh_dirty(self) -> None:
        if self._updating_ui:
            return
        dirty = False
        node = self._selected_node()
        edge = self._selected_edge()
        if node is not None:
            dirty = (
                self._meaning_dirty(node)
                or self._region_dirty(node)
                or self._recognition_dirty(node)
            )
        elif edge is not None:
            dirty = (
                self.edge_target_node_combo.currentData() != edge.get("target_node_id")
                or self._edge_semantics_dirty(edge)
            )
        self._set_dirty(dirty)

    def _set_dirty(self, value: bool) -> None:
        value = bool(value)
        if value != self._dirty:
            self._dirty = value
            self.dirtyChanged.emit(value)
        self._set_controls()

    def _set_busy(self, value: bool) -> None:
        value = bool(value)
        if value != self._busy:
            self._busy = value
            self.busyChanged.emit(value)
        self._set_controls()

    def _set_controls(self) -> None:
        loaded = self._snapshot is not None
        # 忙碌时拒绝新选择，但仍接收鼠标释放，避免按下回调遗留场景抓取。
        self.graph_view.setEnabled(True)
        self.revert_button.setEnabled(loaded and self._dirty and not self._busy)
        ready = loaded and self._evidence_valid and not self._busy
        sources = self._snapshot.get("source_refs", {}) if loaded else {}
        action_only = sources.get("kind") == "recorded_actions"
        composed = sources.get("kind") == "interface_composition" or bool(sources.get("interface_composition"))
        reference_node = "interface_reference" in (self._selected_node() or {})
        self.save_all_button.setEnabled(ready and self._dirty and not self.read_only)
        self.review_graph_button.setEnabled(ready and not self._dirty and not self.read_only and not composed and not action_only)
        self.graph_relearn_button.setEnabled(
            ready and not self._dirty and self._selection is not None and not self.read_only and not composed and not action_only
        )
        node = loaded and self._selection is not None and self._selection[0] == "node"
        edge = loaded and self._selection is not None and self._selection[0] == "edge"
        node_ready = bool(node and ready and not self.read_only and not reference_node)
        edge_ready = bool(edge and ready and not self.read_only)
        for widget in (
            self.node_meaning_edit, self.node_region_combo, self.node_region_bbox_edit,
            self.node_recognition_text_edit, self.node_recognition_bbox_edit,
        ):
            widget.setEnabled(node_ready)
        for widget in (
            self.edge_target_node_combo, self.edge_target_region_combo,
            self.edge_prerequisites_edit, self.edge_expected_result_edit,
            self.edge_stop_condition_edit, self.edge_relationship_kinds_edit,
        ):
            widget.setEnabled(edge_ready)
        try:
            conditions = json.loads(self.edge_prerequisites_edit.toPlainText())
            plain_editable = isinstance(conditions, list) and all(isinstance(item, str) for item in conditions)
        except (ValueError, TypeError):
            plain_editable = False
        self.edge_conditions_plain.setEnabled(edge_ready and plain_editable)
        self.edge_conditions_plain.setToolTip(
            "每行写一个执行前条件" if plain_editable else "请先在高级选项中修正条件格式，当前输入会保留。"
        )
        self.before_canvas.setEnabled(bool(ready))
        self.before_canvas.setInteractive(node_ready or bool(edge_ready))
        self.after_canvas.setEnabled(bool(ready and edge))
        self.after_canvas.setInteractive(bool(edge_ready))
        for widget in (
            self.save_node_meaning_button, self.save_region_bbox_button,
            self.save_node_recognition_button,
        ):
            widget.setEnabled(node_ready)
        for widget in (self.save_edge_target_button, self.save_edge_semantics_button):
            widget.setEnabled(edge_ready)
        if self.read_only and action_only:
            self.guide_label.setText("操作证据 · 只读核对原图；不是已发布流程，排列不代表动作间的执行顺序。")
        elif self.read_only:
            self.guide_label.setText("已发布版本 · 只读查看，可以选择界面和跳转检查原图；不会修改或执行。")
        elif self._busy:
            self.guide_label.setText("正在处理当前内容，请稍候…")
        elif self._dirty:
            self.guide_label.setText("有未保存修改 · 完成后点“保存修改”，再检查下一处。保存不会自动审核。")
        elif ready and action_only:
            self.guide_label.setText("操作证据可持续修改；每条边只证明自身前后画面，不自动推断不同动作间的衔接。")
        elif ready and reference_node:
            self.guide_label.setText("引用版本 · 只读查看原图；请在界面库修改并审核独立内容。加入流程不等于已学会跳转。")
        elif ready and composed:
            self.guide_label.setText("组合草稿 · 可检查已有内容；新增界面引用尚不能直接发布执行或发起整图重学。")
        elif ready:
            self.guide_label.setText("已保存 · 点界面看原图，点连线看前后变化；全部检查后再审核当前图。")
        else:
            self.guide_label.setText("先选择一个流程，等原始截图读取完成后开始检查。")

    def _start(
        self, operation: Callable[[], dict[str, Any]],
        completed: Callable[[dict[str, Any]], None], status: str,
        *, evidence_request: bool = False,
    ) -> None:
        if self._busy:
            self._error("已有图操作正在进行，请稍候。")
            return
        self._request_id += 1
        request_id = self._request_id
        self._set_busy(True)
        self.status_label.setText(status)
        job = make_job(request_id, operation, self)
        self._jobs.add(job)
        job.succeeded.connect(
            lambda result_id, result: self._job_succeeded(
                result_id, result, completed, evidence_request,
            )
        )
        job.failed.connect(
            lambda result_id, message: self._job_failed(
                result_id, message, evidence_request,
            )
        )
        job.finished.connect(lambda: self._jobs.discard(job))
        job.finished.connect(job.deleteLater)
        job.start()

    def _job_succeeded(
        self, request_id: int, result: object,
        completed: Callable[[dict[str, Any]], None], evidence_request: bool,
    ) -> None:
        if request_id != self._request_id:
            return
        self._set_busy(False)
        if not isinstance(result, dict):
            if evidence_request:
                self._invalidate_evidence(clear=True)
            self._error("图操作返回格式无效；当前正式修订和未保存字段均已保留。")
            return
        try:
            completed(result)
        except (KeyError, TypeError, ValueError) as error:
            if evidence_request:
                self._invalidate_evidence(clear=True)
            self._error(f"图操作响应无效；未替换当前正式修订：{error}")

    def _job_failed(self, request_id: int, message: str, evidence_request: bool) -> None:
        if request_id != self._request_id:
            return
        self._set_busy(False)
        if evidence_request:
            self._invalidate_evidence(clear=True)
        self._error(f"图操作失败；当前正式修订和未保存字段均已保留：{message}")

    def _error(self, message: str) -> None:
        self.status_label.setText(message)
        self.errorRaised.emit(message)


def _find(values: Any, key: str, identity: Any) -> dict[str, Any] | None:
    if not isinstance(values, list):
        return None
    found = [item for item in values if isinstance(item, dict) and item.get(key) == identity]
    return found[0] if len(found) == 1 else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _first_text(value: Any) -> str:
    return str(value[0]) if isinstance(value, list) and value else ""


def _compact_identity(value: Any, *, limit: int = 26) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:12]}…{text[-8:]}"


def _bbox_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return ", ".join(str(number) for number in value)


def _parse_bbox(value: str) -> list[float]:
    try:
        numbers = [float(item.strip()) for item in value.split(",")]
    except ValueError as error:
        raise ValueError("区域框必须是四个逗号分隔的数字。") from error
    if len(numbers) != 4 or any(not math.isfinite(item) for item in numbers):
        raise ValueError("区域框必须是四个有限数字。")
    if numbers[0] < 0 or numbers[1] < 0 or numbers[2] <= 0 or numbers[3] <= 0:
        raise ValueError("区域框必须位于原图内且宽高为正。")
    return numbers


def _recognition_bbox(node: dict[str, Any]) -> list[float] | None:
    anchor = node.get("recognition_anchor")
    if not isinstance(anchor, dict):
        return None
    bbox = anchor.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in bbox):
        return None
    return [float(value) for value in bbox]


def _validate_regions(value: Any, width: int, height: int) -> None:
    if not isinstance(value, list):
        raise ValueError("graph node regions are invalid")
    seen: set[str] = set()
    for region in value:
        if not isinstance(region, dict) or not isinstance(region.get("region_id"), str) or not region["region_id"] or region["region_id"] in seen:
            raise ValueError("graph node region identity is invalid")
        seen.add(region["region_id"])
        bbox = region.get("bbox")
        if (
            not isinstance(bbox, list) or len(bbox) != 4
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in bbox)
            or bbox[0] < 0 or bbox[1] < 0 or bbox[2] <= 0 or bbox[3] <= 0
            or bbox[0] + bbox[2] > width or bbox[1] + bbox[3] > height
        ):
            raise ValueError("graph node region bbox is invalid")
