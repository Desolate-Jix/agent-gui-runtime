from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_learning_draft_editor_state_machine() -> None:
    result = subprocess.run(
        ["node", "--test", "tests/js/learning_draft_editor.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
