"""新界面候选的只读证据视图：不虚构旧截图，不产生输入权限。"""
from copy import deepcopy

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen, QPixmap
from PySide6.QtWidgets import QComboBox, QGraphicsRectItem, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.agent_link.contracts import AgentLinkError
from app.agent_link.interface_additions import interface_entities_from_diffs
from .geometry_comparison import _ReadonlyGraphicsView, _validate_comparison, _validate_workspace, _validated_png


class InterfaceComparisonWidget(QWidget):
    """验证完整补充证据集合后，只在 Agent 候选栏绘制图像与框。"""

    def __init__(self, workspace: dict, comparison: dict, parent=None):
        super().__init__(parent)
        validated = _validate_workspace(workspace)
        compared = _validate_comparison(comparison, validated)
        try:
            shots, interfaces = interface_entities_from_diffs(workspace["batch"], compared["diffs"])
        except AgentLinkError as error:
            raise ValueError("新界面候选证据无效：" + error.message) from error
        if not interfaces:
            raise ValueError("比较中没有完整的新界面证据")
        self._interfaces = deepcopy(interfaces)
        self._shots = {shot["screenshot_id"]: {**shot, "image": _validated_png(shot)} for shot in shots}
        self._anchors = {diff["target_id"]: diff["proposed"]["anchor_interface_id"] for diff in compared["diffs"]
                         if diff.get("target_type") == "interface" and diff.get("field") == "entity"}
        layout = QVBoxLayout(self)
        self.absent_label = QLabel("重学基线：不存在　｜　当前人工版本：不存在\n下方只显示 Agent 提议的新界面；尚未采用、批准或执行。")
        self.absent_label.setWordWrap(True); layout.addWidget(self.absent_label)
        self.interface_selector = QComboBox()
        self.interface_selector.setObjectName("newInterfaceEvidenceSelector")
        layout.addWidget(self.interface_selector)
        self.metadata_label = QLabel()
        self.metadata_label.setWordWrap(True); layout.addWidget(self.metadata_label)
        controls = QHBoxLayout()
        self.zoom_out_button, self.zoom_in_button, self.fit_button = QPushButton("缩小"), QPushButton("放大"), QPushButton("适配")
        for button in (self.zoom_out_button, self.zoom_in_button, self.fit_button): controls.addWidget(button)
        controls.addStretch(); layout.addLayout(controls)
        self.proposed_view = _ReadonlyGraphicsView()
        self.proposed_view.setObjectName("newInterfaceEvidenceCanvas")
        layout.addWidget(self.proposed_view, 1)
        self.zoom_out_button.clicked.connect(self.proposed_view.zoom_out)
        self.zoom_in_button.clicked.connect(self.proposed_view.zoom_in)
        self.fit_button.clicked.connect(self.proposed_view.fit_image)
        self.interface_selector.currentIndexChanged.connect(self._show_interface)
        for interface in interfaces:
            self.interface_selector.addItem(f"{interface['meaning']} · {interface['interface_id']}")
        self._show_interface(0)

    def _show_interface(self, index):
        if not 0 <= index < len(self._interfaces): return
        interface = self._interfaces[index]
        shot = self._shots[interface["screenshot_id"]]
        self.metadata_label.setText(
            f"关联既有界面：{self._anchors[interface['interface_id']]} · 新截图：{shot['screenshot_id']} · "
            f"{shot['width']} × {shot['height']} px · {len(interface['regions'])} 个识别框\nSHA-256：{shot['sha256']}"
        )
        scene = self.proposed_view.scene(); scene.clear()
        scene.addPixmap(QPixmap.fromImage(shot["image"]))
        for region in interface["regions"]:
            x, y, width, height = region["bbox"]
            rect = QGraphicsRectItem(0, 0, width, height)
            rect.setPos(x, y); rect.setPen(QPen(QColor("#d1495b"), 2))
            rect.setBrush(QColor(209, 73, 91, 24)); rect.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            rect.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
            rect.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
            rect.setToolTip(f"{region['region_id']} · {region['meaning']}")
            rect.setZValue(2); scene.addItem(rect)
        scene.setSceneRect(QRectF(0, 0, shot["width"], shot["height"]))
        self.proposed_view.fit_image()
