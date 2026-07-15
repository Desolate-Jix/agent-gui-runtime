from __future__ import annotations

import json
import os
from pathlib import Path

from app.core.screenshot import ScreenshotService


def test_cleanup_preserves_screenshots_referenced_by_benchmark_manifests(tmp_path: Path) -> None:
    screenshot_dir = tmp_path / "artifacts" / "screenshots"
    benchmark_dir = tmp_path / "artifacts" / "benchmarks"
    screenshot_dir.mkdir(parents=True)
    benchmark_dir.mkdir(parents=True)
    protected = screenshot_dir / "golden.png"
    newest = screenshot_dir / "newest.png"
    stale = screenshot_dir / "stale.png"
    for path in (protected, newest, stale):
        path.write_bytes(path.name.encode("ascii"))
    os.utime(stale, (1, 1))
    os.utime(protected, (2, 2))
    os.utime(newest, (3, 3))
    (benchmark_dir / "manifest.json").write_text(
        json.dumps(
            {
                "cases": [
                    {"screenshot_path": "artifacts/screenshots/golden.png"},
                ]
            }
        ),
        encoding="utf-8",
    )

    service = ScreenshotService()
    service._capture_dir = screenshot_dir
    service._capture_keep_limit = 1
    service._cleanup_old_captures()

    assert protected.exists()
    assert newest.exists()
    assert not stale.exists()
