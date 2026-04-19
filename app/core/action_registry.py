from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.schemas.action_target import ActionTarget
from app.schemas.state import AppState
from app.schemas.validator_profile import ValidatorProfile

ACTIONS_DIR = Path("logs/app-actions")
ACTIONS_DIR.mkdir(parents=True, exist_ok=True)
VALIDATORS_DIR = ACTIONS_DIR / "validators"
VALIDATORS_DIR.mkdir(parents=True, exist_ok=True)
STATES_DIR = Path("logs/app-states")
STATES_DIR.mkdir(parents=True, exist_ok=True)


class ActionRegistry:
    def __init__(
        self,
        actions_dir: Path = ACTIONS_DIR,
        validators_dir: Path = VALIDATORS_DIR,
        states_dir: Path = STATES_DIR,
    ) -> None:
        self.actions_dir = actions_dir
        self.validators_dir = validators_dir
        self.states_dir = states_dir
        self.actions_dir.mkdir(parents=True, exist_ok=True)
        self.validators_dir.mkdir(parents=True, exist_ok=True)
        self.states_dir.mkdir(parents=True, exist_ok=True)

    def action_path(self, action_id: str) -> Path:
        return self.actions_dir / f"{action_id}.json"

    def validator_path(self, validator_profile_id: str) -> Path:
        return self.validators_dir / f"{validator_profile_id}.json"

    def state_path(self, state_id: str) -> Path:
        return self.states_dir / f"{state_id}.json"

    def save_action(self, action: ActionTarget) -> str:
        path = self.action_path(action.action_id)
        path.write_text(json.dumps(action.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.resolve())

    def load_action(self, action_id: str) -> Optional[ActionTarget]:
        path = self.action_path(action_id)
        if not path.exists():
            return None
        return ActionTarget.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_validator(self, profile: ValidatorProfile) -> str:
        path = self.validator_path(profile.validator_profile_id)
        path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.resolve())

    def load_validator(self, validator_profile_id: str) -> Optional[ValidatorProfile]:
        path = self.validator_path(validator_profile_id)
        if not path.exists():
            return None
        return ValidatorProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_state_hint(self, state: AppState) -> str:
        path = self.state_path(state.state_id)
        path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.resolve())

    def load_state_hint(self, state_id: str) -> Optional[AppState]:
        path = self.state_path(state_id)
        if not path.exists():
            return None
        return AppState.from_dict(json.loads(path.read_text(encoding="utf-8")))


action_registry = ActionRegistry()
