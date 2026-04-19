from __future__ import annotations

from pathlib import Path

from app.core.action_registry import ActionRegistry
from app.schemas.state import AppState
from app.schemas.validator_profile import ValidatorProfile


def test_action_registry_can_round_trip_state_hint(tmp_path: Path) -> None:
    registry = ActionRegistry(
        actions_dir=tmp_path / "actions",
        validators_dir=tmp_path / "validators",
        states_dir=tmp_path / "states",
    )
    state = AppState(
        state_id="state-1",
        app_name="TestApp",
        state_name="main",
        window_size_bucket="100x100",
        fingerprint=None,
    )
    registry.save_state_hint(state)
    loaded = registry.load_state_hint("state-1")
    assert loaded is not None
    assert loaded.state_id == "state-1"
    assert loaded.fingerprint is None


def test_validator_profile_accepts_name_alias() -> None:
    profile = ValidatorProfile(
        validator_profile_id="validator-1",
        name="Counter Validator",
        ocr_roi=None,
    )
    assert profile.name == "Counter Validator"
    assert profile.target_name == "Counter Validator"
