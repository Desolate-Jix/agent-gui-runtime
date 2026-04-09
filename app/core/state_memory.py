from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.schemas.state import AppState

STATES_DIR = Path("logs/app-states")
STATES_DIR.mkdir(parents=True, exist_ok=True)


class StateMemory:
    def __init__(self, base_dir: Path = STATES_DIR) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def state_path(self, state_id: str) -> Path:
        return self.base_dir / f"{state_id}.json"

    def save(self, state: AppState) -> str:
        path = self.state_path(state.state_id)
        path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.resolve())

    def load(self, state_id: str) -> Optional[AppState]:
        path = self.state_path(state_id)
        if not path.exists():
            return None
        return AppState.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_states(self) -> list[AppState]:
        results: list[AppState] = []
        for path in sorted(self.base_dir.glob("*.json")):
            try:
                results.append(AppState.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return results


state_memory = StateMemory()
