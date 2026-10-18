"""用于原生导航语义验收的无害 Qt 目标窗口。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget


class NativeNavigationTarget(QWidget):
    """仅通过真实 Qt 按钮信号在列表页和详情页之间切换。"""

    def __init__(self, evidence_dir: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Agent Review Test Target - List")
        self.setFixedSize(900, 560)
        self._evidence_dir = Path(evidence_dir).expanduser().resolve() if evidence_dir is not None else None
        if self._evidence_dir is not None:
            self._evidence_dir.mkdir(parents=True, exist_ok=True)
        self._stack = QStackedWidget(self)
        self.open_button = QPushButton("查看示例详情")
        self.back_button = QPushButton("返回列表")
        self._build_pages()
        layout = QVBoxLayout(self)
        layout.addWidget(self._stack)
        self.open_button.clicked.connect(self._open_detail)
        self.back_button.clicked.connect(self._back_to_list)
        self._set_state("list")

    @property
    def state_name(self) -> str:
        return "detail" if self._stack.currentIndex() == 1 else "list"

    def _build_pages(self) -> None:
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        heading = QLabel("列表页")
        heading.setObjectName("listHeading")
        heading.setStyleSheet("font-size: 24px; font-weight: 600;")
        text = QLabel("S45-001 · 中性示例条目")
        list_layout.addWidget(heading)
        list_layout.addWidget(text)
        list_layout.addWidget(self.open_button, alignment=Qt.AlignmentFlag.AlignLeft)
        list_layout.addStretch()

        detail_page = QWidget()
        detail_layout = QVBoxLayout(detail_page)
        detail_heading = QLabel("详情页")
        detail_heading.setObjectName("detailHeading")
        detail_heading.setStyleSheet("font-size: 24px; font-weight: 600;")
        detail_layout.addWidget(detail_heading)
        detail_layout.addWidget(QLabel("S45-001 · 中性示例详情"))
        detail_layout.addWidget(self.back_button, alignment=Qt.AlignmentFlag.AlignLeft)
        detail_layout.addStretch()
        self._stack.addWidget(list_page)
        self._stack.addWidget(detail_page)

    def _open_detail(self) -> None:
        self._stack.setCurrentIndex(1)
        self.setWindowTitle("Agent Review Test Target - Detail")
        self._set_state("detail")

    def _back_to_list(self) -> None:
        self._stack.setCurrentIndex(0)
        self.setWindowTitle("Agent Review Test Target - List")
        self._set_state("list")

    def _set_state(self, state: str) -> None:
        if self._evidence_dir is None:
            return
        source_file = Path(__file__).resolve()
        event = {"timestamp": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
                 "source": "test_target_widget", "source_file_sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
                 "state": state, "framework_action_proof": False}
        with (self._evidence_dir / "state-transitions.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        (self._evidence_dir / "latest-state.json").write_text(
            json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    # 每次 CLI 运行必须使用全新的证据目录，避免重跑混入旧状态。
    args.evidence_dir = args.evidence_dir.expanduser().resolve()
    args.evidence_dir.mkdir(parents=True, exist_ok=False)
    app = QApplication(sys.argv)
    window = NativeNavigationTarget(args.evidence_dir)
    from PySide6.QtGui import QFont
    window.setFont(QFont("Microsoft YaHei", 11))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
