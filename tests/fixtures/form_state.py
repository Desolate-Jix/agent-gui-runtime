"""本地表单验收记录器；不参与产品输入执行。"""
import json
from pathlib import Path
from threading import Lock


class FormState:
    def __init__(self, path: Path):
        self.path = path
        self._lock = Lock()

    def update(self, state):
        with self._lock:
            if self.path.exists() and state['seq'] < json.loads(self.path.read_text(encoding='utf-8'))['seq']:
                return
            pending = self.path.with_suffix('.pending')
            pending.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            pending.replace(self.path)
