from __future__ import annotations

import json
from pathlib import Path

from app.schemas.transition import TransitionRecord

TRANSITIONS_DIR = Path("logs/app-transitions")
TRANSITIONS_DIR.mkdir(parents=True, exist_ok=True)


class TransitionMemory:
    def __init__(self, base_dir: Path = TRANSITIONS_DIR) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: TransitionRecord) -> str:
        path = self.base_dir / f"{record.transition_id}.json"
        path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.resolve())


transition_memory = TransitionMemory()
