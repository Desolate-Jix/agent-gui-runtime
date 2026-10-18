"""用于原生文本填写验收的无害 Qt 目标窗口。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget


class NativeTextTarget(QWidget):
    """只有一个普通文本框，不提供提交或其他系统操作。"""

    def __init__(self, evidence_dir: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Agent Review Test Target - Text")
        self.setFixedSize(900, 560)
        self._evidence_dir = Path(evidence_dir).resolve() if evidence_dir is not None else None
        if self._evidence_dir is not None:
            self._evidence_dir.mkdir(parents=True, exist_ok=True)
        self.heading = QLabel("文本填写测试界面")
        self.label = QLabel("搜索词")
        self.search_query = QLineEdit()
        self.search_query.setObjectName("searchQuery")
        self.search_query.setAccessibleName("搜索词")
        self.current_value = QLabel("当前内容：")
        self.current_value.setObjectName("currentValue")
        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.label)
        layout.addWidget(self.search_query)
        layout.addWidget(self.current_value)
        layout.addStretch()
        self.search_query.textChanged.connect(self._on_text_changed)
        self._record(self.search_query.text())

    def _on_text_changed(self, value: str) -> None:
        self.current_value.setText("当前内容：" + value)
        self._record(value)

    def _record(self, value: str) -> None:
        if self._evidence_dir is None:
            return
        event = {"pid": os.getpid(), "source": "native_text_target",
                 "source_file_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 "state": "text", "value": value,
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "framework_action_proof": False}
        with (self._evidence_dir / "state-transitions.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        (self._evidence_dir / "latest-state.json").write_text(
            json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    args.evidence_dir = args.evidence_dir.resolve()
    args.evidence_dir.mkdir(parents=True, exist_ok=False)
    app = QApplication(sys.argv)
    window = NativeTextTarget(args.evidence_dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
