from pathlib import Path

import pytest

from app.desktop_review.exact_review import ExactReviewError, _collect_paths


def test_native_executable_identity_is_not_a_project_file_dependency(tmp_path: Path) -> None:
    dependencies: set[Path] = set()
    review = {
        "workflow": {
            "application_identity": {
                "kind": "native",
                "executable_path": r"D:\Lonlife\lonlife_acc.exe",
            }
        },
        "screenshot_path": "screenshots/current.png",
    }

    _collect_paths(tmp_path, review, dependencies)

    assert dependencies == {(tmp_path / "screenshots/current.png").resolve()}


@pytest.mark.parametrize("review", [
    {"executable_path": r"D:\Lonlife\lonlife_acc.exe"},
    {"other": {"application_identity": {"kind": "native", "executable_path": r"D:\Lonlife\lonlife_acc.exe"}}},
    {"workflow": {"application_identity": {"kind": "web", "executable_path": r"D:\Lonlife\lonlife_acc.exe"}}},
    {"workflow": {"application_identity": {"kind": "native", "executable_path": "relative.exe"}}},
    {"workflow": {"application_identity": {"kind": "native", "screenshot_path": r"D:\outside.png"}}},
])
def test_native_identity_exception_cannot_admit_other_external_dependencies(tmp_path: Path, review: dict) -> None:
    with pytest.raises(ExactReviewError):
        _collect_paths(tmp_path, review, set())
