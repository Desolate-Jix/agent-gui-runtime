from __future__ import annotations

import json
from pathlib import Path

from app.schemas.replay_case import ReplayCase

REPLAY_CASES_DIR = Path("logs/replay-cases")
REPLAY_CASES_DIR.mkdir(parents=True, exist_ok=True)


class ReplayCaseStore:
    def __init__(self, base_dir: Path = REPLAY_CASES_DIR) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, case: ReplayCase) -> str:
        path = self.base_dir / f"{case.case_id}.json"
        path.write_text(json.dumps(case.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.resolve())


replay_case_store = ReplayCaseStore()
