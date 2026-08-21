from __future__ import annotations

import pytest

from app.core import input_controller as input_controller_module
from app.core import runtime_input_authority


def test_raw_input_controller_rejects_calls_outside_runtime_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = input_controller_module.InputController()
    monkeypatch.setattr(input_controller_module, "WINDOWS_INPUT_AVAILABLE", True)

    with pytest.raises(PermissionError, match="LiveController authority"):
        controller._ensure_windows_input()


def test_runtime_backend_scope_is_process_private_and_short_lived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = input_controller_module.InputController()
    monkeypatch.setattr(input_controller_module, "WINDOWS_INPUT_AVAILABLE", True)

    with runtime_input_authority._runtime_backend_input_scope():
        controller._ensure_windows_input()

    with pytest.raises(PermissionError, match="LiveController authority"):
        controller._ensure_windows_input()
