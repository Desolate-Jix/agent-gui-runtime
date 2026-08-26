from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import psutil
import pytest

if __name__ == "__main__":
    import site

    site.addsitedir(str(Path(__file__).resolve().parents[1] / ".venv" / "Lib" / "site-packages"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.learn.hybrid.benchmark_v2_window_owner import (
    ATTESTATION_CONTRACT,
    CLEANUP_CONTRACT,
    OWNER_BINDING_CONTRACT,
    OWNER_JOURNAL_CONTRACT,
    _launch_owned_window_for_test,
    _raw_hwnd_attestation,
    attest_bound_window,
    close_owned_window,
    launch_owned_window,
)
from app.learn.hybrid.benchmark_v2_contracts import content_sha256
from app.learn.hybrid.windows_process_scope import observe_process_scope_cleanup


windows_only = pytest.mark.skipif(
    os.name != "nt", reason="real HWND contract is Windows-only"
)


def test_window_contracts_are_versioned_and_non_authorizing() -> None:
    assert OWNER_JOURNAL_CONTRACT.endswith("_v1")
    assert OWNER_BINDING_CONTRACT.endswith("_v1")
    assert ATTESTATION_CONTRACT.endswith("_v1")
    assert CLEANUP_CONTRACT.endswith("_v1")


def test_non_windows_public_contract_fails_closed_before_side_effects(
    tmp_path: Path, monkeypatch
) -> None:
    import app.learn.hybrid.benchmark_v2_window_owner as window_owner

    monkeypatch.setattr(window_owner, "_WINDOWS", False)
    image = tmp_path / "never-opened.bmp"
    journal = tmp_path / "never-created.owner.json"
    with pytest.raises(RuntimeError, match="Windows"):
        launch_owned_window(
            image_path=image,
            expected_sha256="0" * 64,
            operation_id="operation-non-windows",
            journal_path=journal,
        )
    with pytest.raises(RuntimeError, match="Windows"):
        attest_bound_window(owner={})
    with pytest.raises(RuntimeError, match="Windows"):
        close_owned_window(journal_path=journal, reason="non-windows")
    assert not image.exists()
    assert not journal.exists()


@pytest.fixture(autouse=True)
def _no_window_helper_residue(tmp_path: Path):
    yield
    residue = []
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            command = process.info["cmdline"] or []
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
        if any("portfolio_hybrid_v1_1_test_window_v2.py" in item for item in command):
            residue.append({"pid": process.info["pid"], "cmdline": command})
    assert residue == []
    runtime_files = [
        str(path)
        for path in tmp_path.rglob("*")
        if path.name.endswith(
            (".publication.json", ".publication-permit.json", ".events.lock")
        )
        or ".probe-request.json" in path.name
        or ".probe-result.json" in path.name
        or ".probe-stderr.txt" in path.name
        or path.name.endswith(".helper-stderr.txt")
        or path.name.endswith((".lease", ".pid"))
    ]
    assert runtime_files == []


def _bmp(path: Path, *, width: int = 96, height: int = 64) -> str:
    stride = (width * 3 + 3) & ~3
    pixels = bytearray()
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend(((x * 3) % 256, (y * 5) % 256, (x + y) % 256))
        row.extend(b"\0" * (stride - width * 3))
        pixels.extend(row)
    header = struct.pack(
        "<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54
    ) + struct.pack(
        "<IIIHHIIIIII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0
    )
    raw = header + pixels
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _assert_cleanup(receipt: dict[str, object]) -> None:
    assert receipt["cleanup_status"] == "verified"
    assert receipt["enum_windows_exact_hwnd_absent"] is True
    assert receipt["matching_owned_windows_after"] == []
    assert receipt["member_pids_after"] == []
    assert receipt["stable_zero_observations"] >= 3
    assert receipt["scope_absent_after_owner_close"] is True
    assert receipt["process_handle_closed"] is True
    assert receipt["job_handle_closed"] is True
    assert receipt["active_listeners_after"] == []
    assert receipt["listener_or_lease_residue"] == []
    assert receipt["content_sha256"] == content_sha256(receipt)
    if receipt["wm_close_exact_hwnd_attempted"]:
        assert receipt["wm_close_exact_hwnd_queued"] is True
        assert receipt["wm_close_error_code"] == 0


@contextmanager
def _owned(tmp_path: Path, name: str):
    image = tmp_path / f"{name}.bmp"
    digest = _bmp(image)
    journal = tmp_path / f"{name}.owner.json"
    owner = None
    try:
        owner = launch_owned_window(
            image_path=image,
            expected_sha256=digest,
            operation_id=f"operation-{name}",
            journal_path=journal,
        )
        yield owner, journal
    finally:
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_owned_bitmap_window_has_exact_job_hwnd_and_uia_binding(tmp_path: Path) -> None:
    with _owned(tmp_path, "exact") as (owner, journal):
        attested = attest_bound_window(owner=owner)
        assert attested["binding_content_sha256"] == owner["content_sha256"]
        assert attested["exact_hwnd"] == owner["hwnd"]
        assert attested["process_identity"] == owner["process_identity"]
        assert attested["job_member_pids"] == [owner["process_identity"]["pid"]]
        assert attested["screenshot_sha256"] == owner["screenshot_sha256"]
        assert attested["uia_root_identity"] == owner["uia_root_identity"]
        assert attested["pre_raw_identity_sha256"] == attested["post_raw_identity_sha256"]
        assert owner["client_rect"]["width"] == owner["image_dimensions"]["width"]
        assert owner["client_rect"]["height"] == owner["image_dimensions"]["height"]
        assert owner["artifact_is_authorization"] is False
        assert owner["execute_binding_enabled"] is False
        events = [
            json.loads(line)
            for line in Path(str(journal) + ".events.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        published = next(event for event in events if event["event_type"] == "hwnd_published")
        publication = published["payload"]["publication"]
        assert publication["journal_root_sha256"] == owner["journal_root_sha256"]
        assert publication["expected_predecessor_sha256"] == published[
            "previous_event_sha256"
        ]
        assert publication["content_sha256"] == content_sha256(publication)


@windows_only
def test_attestation_never_falls_back_to_another_test_owned_window(tmp_path: Path) -> None:
    with _owned(tmp_path, "target") as (target, _target_journal):
        with _owned(tmp_path, "decoy") as (decoy, _decoy_journal):
            result = attest_bound_window(owner=target)
            assert result["exact_hwnd"] == target["hwnd"]
            assert result["exact_hwnd"] != decoy["hwnd"]
            assert result["process_identity"] != decoy["process_identity"]


@windows_only
def test_screenshot_byte_replacement_makes_binding_stale(tmp_path: Path) -> None:
    image = tmp_path / "drift.bmp"
    digest = _bmp(image)
    original = image.read_bytes()
    journal = tmp_path / "drift.owner.json"
    try:
        owner = launch_owned_window(
            image_path=image,
            expected_sha256=digest,
            operation_id="operation-drift",
            journal_path=journal,
        )
        changed = bytearray(original)
        changed[-1] ^= 1
        image.write_bytes(changed)
        with pytest.raises(ValueError, match="screenshot|binding"):
            attest_bound_window(owner=owner)
        image.write_bytes(original)
    finally:
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_public_owner_and_attestation_have_no_action_or_point_authority(tmp_path: Path) -> None:
    forbidden = {
        "actual_point",
        "click_point",
        "confirmed_point",
        "expected_point",
        "screen_point",
        "target_point",
        "action",
        "click",
        "input_handler",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value)) if value else set()
        return set()

    with _owned(tmp_path, "no-action") as (owner, _journal):
        attestation = attest_bound_window(owner=owner)
        assert keys(owner).isdisjoint(forbidden)
        assert keys(attestation).isdisjoint(forbidden)


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("process_identity", "create_time_ns"), 1),
        (("hwnd",), 1),
        (("screenshot_sha256",), "0" * 64),
        (("scope_name",), "Local\\AgentGuiHybrid-vista-" + "0" * 64),
    ],
)
@windows_only
def test_wrong_or_stale_binding_fails_closed(
    tmp_path: Path, path: tuple[str, ...], replacement: object
) -> None:
    with _owned(tmp_path, "mutation") as (owner, _journal):
        changed = deepcopy(owner)
        parent = changed
        for part in path[:-1]:
            parent = parent[part]
        parent[path[-1]] = replacement
        changed["content_sha256"] = content_sha256(changed)
        if path[0] != "screenshot_sha256":
            with pytest.raises(ValueError, match="binding"):
                _raw_hwnd_attestation(changed)
        with pytest.raises(ValueError, match="binding"):
            attest_bound_window(owner=changed)


@windows_only
def test_multiple_exact_windows_in_one_owner_process_fail_closed(tmp_path: Path) -> None:
    image = tmp_path / "multiple.bmp"
    digest = _bmp(image)
    journal = tmp_path / "multiple.owner.json"
    try:
        with pytest.raises(ValueError, match="multiple|ambiguous"):
            _launch_owned_window_for_test(
                image_path=image,
                expected_sha256=digest,
                operation_id="operation-multiple",
                journal_path=journal,
                duplicate_window=True,
            )
    finally:
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_launch_failure_before_process_transfer_closes_creator_job(tmp_path: Path) -> None:
    image = tmp_path / "pretransfer.bmp"
    digest = _bmp(image)
    journal = tmp_path / "pretransfer.owner.json"
    with pytest.raises(RuntimeError, match="pre-transfer"):
        _launch_owned_window_for_test(
            image_path=image,
            expected_sha256=digest,
            operation_id="operation-pretransfer",
            journal_path=journal,
            duplicate_window=False,
            fail_after_job_created=True,
        )
    root = json.loads(journal.read_text(encoding="utf-8"))
    cleanup = observe_process_scope_cleanup(
        root["scope_name"], terminate=True, stable_zero_observations=3
    )
    assert cleanup["cleanup_status"] == "verified"
    assert cleanup["scope_absent_after_owner_close"] is True
    _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_missing_window_fails_closed_and_close_is_idempotent(tmp_path: Path) -> None:
    image = tmp_path / "missing.bmp"
    digest = _bmp(image)
    journal = tmp_path / "missing.owner.json"
    owner = None
    try:
        owner = launch_owned_window(
            image_path=image,
            expected_sha256=digest,
            operation_id="operation-missing",
            journal_path=journal,
        )
        first = close_owned_window(journal_path=journal, reason="cancel")
        _assert_cleanup(first)
        with pytest.raises(ValueError, match="missing|binding"):
            attest_bound_window(owner=owner)
        second = close_owned_window(journal_path=journal, reason="cancel")
        assert second == first
    finally:
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_concurrent_close_has_one_canonical_terminal_receipt(tmp_path: Path) -> None:
    image = tmp_path / "concurrent-close.bmp"
    digest = _bmp(image)
    journal = tmp_path / "concurrent-close.owner.json"
    try:
        launch_owned_window(
            image_path=image,
            expected_sha256=digest,
            operation_id="operation-concurrent-close",
            journal_path=journal,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            receipts = list(
                executor.map(
                    lambda reason: close_owned_window(
                        journal_path=journal, reason=reason
                    ),
                    ("cancel-a", "cancel-b"),
                )
            )
        assert receipts[0] == receipts[1]
        _assert_cleanup(receipts[0])
        events = [
            json.loads(line)
            for line in Path(str(journal) + ".events.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        assert sum(event["event_type"] == "cleanup_verified" for event in events) == 1
    finally:
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_close_cannot_finalize_while_launch_is_publishing_ready(tmp_path: Path) -> None:
    image = tmp_path / "launch-close.bmp"
    digest = _bmp(image)
    journal = tmp_path / "launch-close.owner.json"
    ready = tmp_path / "launch.pause.ready"
    release = tmp_path / "launch.pause.release"
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            launch_future = executor.submit(
                _launch_owned_window_for_test,
                image_path=image,
                expected_sha256=digest,
                operation_id="operation-launch-close",
                journal_path=journal,
                duplicate_window=False,
                pause_after_process_created={
                    "ready_path": str(ready),
                    "release_path": str(release),
                },
            )
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists()
            close_future = executor.submit(
                close_owned_window, journal_path=journal, reason="launch_race_cancel"
            )
            time.sleep(0.1)
            assert close_future.done() is False
            release.write_text("continue", encoding="utf-8")
            owner = launch_future.result(timeout=30)
            receipt = close_future.result(timeout=30)
        assert owner["content_sha256"]
        _assert_cleanup(receipt)
        events = [
            json.loads(line)
            for line in Path(str(journal) + ".events.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        kinds = [event["event_type"] for event in events]
        assert kinds.index("ready") < kinds.index("finalization_intent")
        assert kinds[-1] == "cleanup_verified"
    finally:
        release.write_text("continue", encoding="utf-8")
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path.cwd() / ".venv" / "Lib" / "site-packages"), str(Path.cwd())]
    )
    return env


@windows_only
def test_outer_owner_death_is_reconciled_from_journal(tmp_path: Path) -> None:
    image = tmp_path / "outer.bmp"
    digest = _bmp(image)
    journal = tmp_path / "outer.owner.json"
    result = tmp_path / "outer.result.json"
    process = subprocess.Popen(
        [
            sys._base_executable,
            str(Path(__file__).resolve()),
            "--outer-owner",
            str(image),
            digest,
            str(journal),
            str(result),
        ],
        cwd=Path.cwd(),
        env=_child_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000,
    )
    try:
        deadline = time.monotonic() + 10
        while not result.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert result.exists()
        owner = json.loads(result.read_text(encoding="utf-8"))
        process.kill()
        assert process.wait(10) != 0
        receipt = close_owned_window(journal_path=journal, reason="restart_reconcile")
        _assert_cleanup(receipt)
        assert receipt["outer_owner_python_finally_observed"] is False
        assert not psutil.pid_exists(owner["process_identity"]["pid"])
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(5)
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_journal_scope_substitution_does_not_touch_unrelated_owned_window(tmp_path: Path) -> None:
    with _owned(tmp_path, "protected") as (protected, _protected_journal):
        image = tmp_path / "tampered.bmp"
        digest = _bmp(image)
        journal = tmp_path / "tampered.owner.json"
        try:
            owner = launch_owned_window(
                image_path=image,
                expected_sha256=digest,
                operation_id="operation-tampered",
                journal_path=journal,
            )
            root = json.loads(journal.read_text(encoding="utf-8"))
            root["scope_name"] = protected["scope_name"]
            root["content_sha256"] = content_sha256(root)
            journal.write_text(json.dumps(root), encoding="utf-8")
            with pytest.raises(ValueError, match="journal|content"):
                close_owned_window(journal_path=journal, reason="tampered")
            assert attest_bound_window(owner=protected)["exact_hwnd"] == protected["hwnd"]
            journal.write_text(json.dumps(owner["journal_root"]), encoding="utf-8")
        finally:
            if journal.exists():
                _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


def _outer_owner(argv: list[str]) -> None:
    image, digest, journal, result = argv
    owner = launch_owned_window(
        image_path=Path(image),
        expected_sha256=digest,
        operation_id="operation-outer-death",
        journal_path=Path(journal),
    )
    Path(result).write_text(json.dumps(owner, sort_keys=True), encoding="utf-8")
    while True:
        time.sleep(1)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--outer-owner":
    _outer_owner(sys.argv[2:])
