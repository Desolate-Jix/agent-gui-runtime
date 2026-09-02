from __future__ import annotations

import hashlib
from io import BytesIO
import ctypes
import json
import os
import struct
import subprocess
import sys
import sysconfig
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import psutil
import pytest
from PIL import Image

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
    _append_event,
    _close_owned_window_for_test,
    _expected_cleanup_lineage,
    _load_events,
    _load_root,
    _raw_hwnd_attestation,
    _parse_bmp,
    _parse_owned_image,
    _run_uia_probe,
    _uia_identity,
    _native_handle_value,
    _LIVE_OWNERS,
    _ShutdownEvent,
    attest_bound_window,
    close_owned_window,
    launch_owned_window,
    snapshot_owned_window,
)
from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes, content_sha256
from app.learn.hybrid.windows_process_scope import observe_process_scope_cleanup
from scripts import portfolio_hybrid_v1_1_test_window_v2 as test_window_helper


windows_only = pytest.mark.skipif(
    os.name != "nt", reason="real HWND contract is Windows-only"
)
_REGISTERED_JOURNALS: set[Path] = set()


def _register_journal(path: Path) -> Path:
    resolved = Path(path).resolve()
    _REGISTERED_JOURNALS.add(resolved)
    return resolved


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
    journal = _register_journal(tmp_path / "never-created.owner.json")
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
    try:
        yield
    finally:
        candidates = set(_REGISTERED_JOURNALS)
        candidates.update(path.resolve() for path in tmp_path.rglob("*.owner.json"))
        for journal in sorted(candidates, key=str, reverse=True):
            if journal.exists():
                try:
                    close_owned_window(journal_path=journal, reason="autouse_finally")
                except (ValueError, RuntimeError, BaseExceptionGroup):
                    pass
        _REGISTERED_JOURNALS.difference_update(candidates)
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


def _png(path: Path, *, width: int = 7, height: int = 5) -> bytes:
    image = Image.new("RGBA", (width, height))
    image.putdata(
        [
            ((x * 31) % 256, (y * 47) % 256, ((x + y) * 19) % 256, 255)
            for y in range(height)
            for x in range(width)
        ]
    )
    image.save(path, format="PNG", optimize=False)
    return path.read_bytes()


def test_png_owned_window_input_preserves_exact_file_and_decoded_pixel_sha(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "owned.png"
    raw = _png(image_path)
    expected_pixels = Image.open(BytesIO(raw)).convert("RGBA").tobytes("raw", "BGRA")

    owner_facts = _parse_owned_image(raw)
    helper_facts = test_window_helper._parse_owned_image(raw)

    assert owner_facts["image_format"] == "png"
    assert owner_facts["raw_file_sha256"] == hashlib.sha256(raw).hexdigest()
    assert owner_facts["bitmap_pixel_sha256"] == hashlib.sha256(
        expected_pixels
    ).hexdigest()
    assert owner_facts["dimensions"] == {"width": 7, "height": 5}
    assert helper_facts["raw_file_sha256"] == owner_facts["raw_file_sha256"]
    assert helper_facts["bitmap_pixel_sha256"] == owner_facts[
        "bitmap_pixel_sha256"
    ]


def test_png_byte_tamper_is_rejected_before_owned_window_launch(tmp_path: Path) -> None:
    image_path = tmp_path / "tampered.png"
    raw = bytearray(_png(image_path))
    idat = raw.find(b"IDAT")
    assert idat > 8
    raw[idat + 4] ^= 0x01
    with pytest.raises(ValueError, match="PNG|checksum|image"):
        _parse_owned_image(bytes(raw))
    with pytest.raises(ValueError, match="PNG|checksum|image"):
        test_window_helper._parse_owned_image(bytes(raw))


def test_snapshot_owned_window_seals_exact_probe_and_attestation_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_window_owner as window_owner

    owner = {
        "owner_id": "owner-1",
        "operation_id": "operation-1",
        "content_sha256": "a" * 64,
        "hwnd": 101,
        "process_identity": {"pid": 202, "create_time_ns": 303},
        "screenshot_sha256": "b" * 64,
        "uia_root_identity": {"content_sha256": "c" * 64},
    }
    raw = {
        "identity_sha256": "d" * 64,
        "job_member_pids": [202],
    }
    snapshot = {
        "provider": "windows_uia",
        "provider_version": "windows_uia_provider_v1",
        "status": "ok",
        "window": {
            "handle": 101,
            "title": "Fixture",
            "process_id": 202,
            "process_name": "python.exe",
            "bbox": {"x": 0, "y": 0, "w": 7, "h": 5},
        },
        "control_count": 1,
        "controls": [{"control_id": "root"}],
    }
    probe = {"snapshot": snapshot}
    monkeypatch.setattr(window_owner, "_WINDOWS", True)
    monkeypatch.setattr(window_owner, "_validate_binding", lambda value: dict(value))
    monkeypatch.setattr(window_owner, "_raw_hwnd_attestation", lambda value: dict(raw))
    monkeypatch.setattr(window_owner, "_run_uia_probe", lambda value: dict(probe))
    monkeypatch.setattr(
        window_owner,
        "_uia_identity",
        lambda value, bound: dict(bound["uia_root_identity"]),
    )

    result = snapshot_owned_window(owner=owner)

    assert result["uia_snapshot"] == snapshot
    assert result["owner_binding_ref"] == {
        "id": "owner-1",
        "content_sha256": "a" * 64,
    }
    assert result["pre_raw_identity_sha256"] == "d" * 64
    assert result["post_raw_identity_sha256"] == "d" * 64
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    assert result["display_only"] is True
    assert result["content_sha256"] == content_sha256(result)


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
    assert receipt["shutdown_event_handle_closed"] is True


@contextmanager
def _owned(tmp_path: Path, name: str):
    image = tmp_path / f"{name}.bmp"
    digest = _bmp(image)
    journal = _register_journal(tmp_path / f"{name}.owner.json")
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
        assert _native_handle_value(owner["hwnd"]) == owner["hwnd"]
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
        assert publication["raw_file_sha256"] == owner["screenshot_sha256"]
        assert publication["bitmap_pixel_sha256"] == owner["bitmap_pixel_sha256"]
        assert publication["expected_predecessor_sha256"] == published[
            "previous_event_sha256"
        ]
        assert publication["content_sha256"] == content_sha256(publication)
        root_raw = journal.read_bytes()
        assert root_raw == canonical_json_bytes(json.loads(root_raw))
        assert Path(owner["journal_root"]["root_anchor_path"]).read_bytes() == root_raw
        event_raw = Path(str(journal) + ".events.jsonl").read_bytes()
        assert event_raw == b"".join(
            canonical_json_bytes(json.loads(line)) + b"\n"
            for line in event_raw.splitlines()
        )


def test_window_helper_child_env_uses_active_runtime_site_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_window_owner as window_owner

    snapshot_root = tmp_path / "sealed-snapshot"
    snapshot_root.mkdir()
    snapshot_module = (
        snapshot_root / "app" / "learn" / "hybrid" / "benchmark_v2_window_owner.py"
    )
    monkeypatch.setattr(window_owner, "__file__", str(snapshot_module))

    child_env = window_owner._child_env()
    python_paths = child_env["PYTHONPATH"].split(os.pathsep)
    assert Path(python_paths[0]).resolve() == Path(
        sysconfig.get_path("purelib")
    ).resolve()
    assert Path(python_paths[1]).resolve() == snapshot_root.resolve()

    completed = subprocess.run(
        [sys._base_executable, "-c", "from PIL import Image"],
        cwd=snapshot_root,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@windows_only
def test_attestation_never_falls_back_to_another_test_owned_window(tmp_path: Path) -> None:
    with _owned(tmp_path, "target") as (target, _target_journal):
        with _owned(tmp_path, "decoy") as (decoy, _decoy_journal):
            result = attest_bound_window(owner=target)
            assert result["exact_hwnd"] == target["hwnd"]
            assert result["exact_hwnd"] != decoy["hwnd"]
            assert result["process_identity"] != decoy["process_identity"]


def test_native_handle_conversion_preserves_pointer_width() -> None:
    high = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8 - 1)) + 0x12345
    assert _native_handle_value(high) == high


@windows_only
def test_sealed_bmp_read_blocks_path_replacement_and_binds_dib_digest(tmp_path: Path) -> None:
    image = tmp_path / "sealed.bmp"
    digest = _bmp(image)
    alternate = tmp_path / "alternate.bmp"
    _bmp(alternate)
    alternate_raw = bytearray(alternate.read_bytes())
    alternate_raw[-1] ^= 0xFF
    alternate.write_bytes(alternate_raw)
    journal = _register_journal(tmp_path / "sealed.owner.json")
    ready = tmp_path / "sealed.read.ready"
    release = tmp_path / "sealed.read.release"
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _launch_owned_window_for_test,
                image_path=image,
                expected_sha256=digest,
                operation_id="operation-sealed-read",
                journal_path=journal,
                duplicate_window=False,
                bmp_read_barrier={"ready_path": str(ready), "release_path": str(release)},
            )
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists()
            with pytest.raises(PermissionError):
                os.replace(alternate, image)
            release.write_text("continue", encoding="utf-8")
            owner = future.result(timeout=30)
        expected_pixels = _parse_bmp(image.read_bytes())["bitmap_pixel_sha256"]
        assert owner["bitmap_pixel_sha256"] == expected_pixels
        assert owner["journal_root"]["bitmap_pixel_sha256"] == expected_pixels
    finally:
        release.write_text("continue", encoding="utf-8")
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_same_operation_and_screenshot_different_journals_have_distinct_owners(tmp_path: Path) -> None:
    image = tmp_path / "shared.bmp"
    digest = _bmp(image)
    first_journal = _register_journal(tmp_path / "first.owner.json")
    second_journal = _register_journal(tmp_path / "second.owner.json")
    try:
        first = launch_owned_window(
            image_path=image, expected_sha256=digest, operation_id="same-operation",
            journal_path=first_journal,
        )
        second = launch_owned_window(
            image_path=image, expected_sha256=digest, operation_id="same-operation",
            journal_path=second_journal,
        )
        assert first["owner_id"] != second["owner_id"]
        assert first["scope_name"] != second["scope_name"]
        _assert_cleanup(close_owned_window(journal_path=first_journal, reason="first"))
        assert attest_bound_window(owner=second)["exact_hwnd"] == second["hwnd"]
    finally:
        for journal in (first_journal, second_journal):
            if journal.exists():
                _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_shutdown_event_never_sends_generic_close_to_decoy(tmp_path: Path) -> None:
    with _owned(tmp_path, "shutdown-target") as (target, target_journal):
        with _owned(tmp_path, "shutdown-decoy") as (decoy, _decoy_journal):
            _assert_cleanup(close_owned_window(journal_path=target_journal, reason="event-only"))
            assert attest_bound_window(owner=decoy)["exact_hwnd"] == decoy["hwnd"]
            source = Path("app/learn/hybrid/benchmark_v2_window_owner.py").read_text(
                encoding="utf-8"
            )
            assert "PostMessageW" not in source


@windows_only
def test_destroyed_target_before_shutdown_never_closes_live_decoy(tmp_path: Path) -> None:
    with _owned(tmp_path, "destroyed-target") as (target, target_journal):
        with _owned(tmp_path, "reuse-decoy") as (decoy, _decoy_journal):
            target_process = psutil.Process(target["process_identity"]["pid"])
            target_process.kill()
            target_process.wait(10)
            _assert_cleanup(
                close_owned_window(journal_path=target_journal, reason="destroy-race")
            )
            assert attest_bound_window(owner=decoy)["exact_hwnd"] == decoy["hwnd"]


@windows_only
@pytest.mark.parametrize(
    "mutation", ["bound_title", "window_bbox", "root_name", "root_class", "root_bbox"]
)
def test_uia_projection_mutations_fail_closed(tmp_path: Path, mutation: str) -> None:
    with _owned(tmp_path, f"uia-{mutation}") as (owner, _journal):
        mutated = deepcopy(_run_uia_probe(owner))
        if mutation == "bound_title":
            mutated["bound"]["title"] = "wrong"
        elif mutation == "window_bbox":
            mutated["snapshot"]["window"]["bbox"]["w"] += 1
        elif mutation == "root_name":
            mutated["snapshot"]["controls"][0]["name"] = "wrong"
        elif mutation == "root_class":
            mutated["snapshot"]["controls"][0]["class_name"] = "wrong"
        else:
            mutated["snapshot"]["controls"][0]["screen_bbox"]["x"] += 1
        mutated["content_sha256"] = content_sha256(mutated)
        with pytest.raises(ValueError, match="UIA|projection|exact"):
            _uia_identity(mutated, owner)


@windows_only
def test_screenshot_byte_replacement_makes_binding_stale(tmp_path: Path) -> None:
    image = tmp_path / "drift.bmp"
    digest = _bmp(image)
    original = image.read_bytes()
    journal = _register_journal(tmp_path / "drift.owner.json")
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
    journal = _register_journal(tmp_path / "multiple.owner.json")
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
    journal = _register_journal(tmp_path / "pretransfer.owner.json")
    try:
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
    finally:
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_missing_window_fails_closed_and_close_is_idempotent(tmp_path: Path) -> None:
    image = tmp_path / "missing.bmp"
    digest = _bmp(image)
    journal = _register_journal(tmp_path / "missing.owner.json")
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
    journal = _register_journal(tmp_path / "concurrent-close.owner.json")
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
    journal = _register_journal(tmp_path / "launch-close.owner.json")
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
    journal = _register_journal(tmp_path / "outer.owner.json")
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
    process_handle_closed = False
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
        if getattr(process, "_handle", None) is not None:
            process._handle.Close()
            process_handle_closed = True
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))
    assert process_handle_closed is True


@windows_only
def test_journal_scope_substitution_does_not_touch_unrelated_owned_window(tmp_path: Path) -> None:
    with _owned(tmp_path, "protected") as (protected, _protected_journal):
        image = tmp_path / "tampered.bmp"
        digest = _bmp(image)
        journal = _register_journal(tmp_path / "tampered.owner.json")
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
            journal.write_bytes(canonical_json_bytes(owner["journal_root"]))
        finally:
            if journal.exists():
                _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_full_root_and_event_chain_remint_cannot_replace_immutable_anchor(tmp_path: Path) -> None:
    with _owned(tmp_path, "remint-protected") as (protected, _protected_journal):
        image = tmp_path / "remint.bmp"
        digest = _bmp(image)
        journal = _register_journal(tmp_path / "remint.owner.json")
        original_root = original_events = None
        try:
            owner = launch_owned_window(
                image_path=image, expected_sha256=digest,
                operation_id="operation-remint", journal_path=journal,
            )
            original_root = journal.read_bytes()
            events_path = Path(str(journal) + ".events.jsonl")
            original_events = events_path.read_bytes()
            forged_root = json.loads(original_root)
            forged_root["scope_name"] = protected["scope_name"]
            forged_root["content_sha256"] = content_sha256(forged_root)
            forged_raw = canonical_json_bytes(forged_root)
            forged_events = []
            previous = "0" * 64
            anchor_sha = hashlib.sha256(forged_raw).hexdigest()
            for line in original_events.splitlines():
                event = json.loads(line)
                event["root_anchor_sha256"] = anchor_sha
                event["previous_event_sha256"] = previous
                event["content_sha256"] = content_sha256(event)
                previous = event["content_sha256"]
                forged_events.append(canonical_json_bytes(event))
            journal.write_bytes(forged_raw)
            events_path.write_bytes(b"\n".join(forged_events) + b"\n")
            with pytest.raises(ValueError, match="anchor|journal"):
                _load_root(journal)
            assert attest_bound_window(owner=protected)["exact_hwnd"] == protected["hwnd"]
        finally:
            if original_root is not None:
                journal.write_bytes(original_root)
            if original_events is not None:
                Path(str(journal) + ".events.jsonl").write_bytes(original_events)
            if journal.exists():
                _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_fabricated_terminal_receipt_cannot_precede_os_cleanup(tmp_path: Path) -> None:
    image = tmp_path / "fake-terminal.bmp"
    digest = _bmp(image)
    journal = _register_journal(tmp_path / "fake-terminal.owner.json")
    owner = None
    try:
        owner = launch_owned_window(
            image_path=image, expected_sha256=digest,
            operation_id="operation-fake-terminal", journal_path=journal,
        )
        _append_event(
            journal, owner_id=owner["owner_id"], event_type="finalization_intent",
            payload={"reason": "forged"},
        )
        lineage = _expected_cleanup_lineage(
            owner["journal_root"],
            _load_events(journal, owner_id=owner["owner_id"]),
        )
        fake = {
            "contract_version": CLEANUP_CONTRACT,
            **lineage,
            "cleanup_status": "verified",
            "shutdown_event_signaled": True, "shutdown_event_error_code": 0,
            "shutdown_event_handle_closed": True, "enum_windows_exact_hwnd_absent": True,
            "matching_owned_windows_after": [], "member_pids_after": [],
            "stable_zero_observations": 3, "scope_absent_after_owner_close": True,
            "process_handle_closed": True, "job_handle_closed": True,
            "active_listeners_after": [], "listener_or_lease_residue": [],
            "outer_owner_python_finally_observed": True,
            "artifact_is_authorization": False, "execute_binding_enabled": False,
        }
        fake["content_sha256"] = content_sha256(fake)
        _append_event(
            journal, owner_id=owner["owner_id"], event_type="cleanup_verified", payload=fake
        )
        with pytest.raises(BaseExceptionGroup, match="indeterminate"):
            close_owned_window(journal_path=journal, reason="must-reobserve")
        assert not psutil.pid_exists(owner["process_identity"]["pid"])
    finally:
        if journal.exists():
            close_owned_window(journal_path=journal, reason="test_finally")


@windows_only
@pytest.mark.parametrize("field", ["reason", "process_identity", "exact_hwnd"])
def test_post_absence_terminal_lineage_mutations_fail_closed(
    tmp_path: Path, field: str
) -> None:
    image = tmp_path / f"terminal-{field}.bmp"
    digest = _bmp(image)
    journal = _register_journal(tmp_path / f"terminal-{field}.owner.json")
    original_events = None
    try:
        owner = launch_owned_window(
            image_path=image, expected_sha256=digest,
            operation_id=f"operation-terminal-{field}", journal_path=journal,
        )
        _assert_cleanup(close_owned_window(journal_path=journal, reason="exact-reason"))
        events_path = Path(str(journal) + ".events.jsonl")
        original_events = events_path.read_bytes()
        events = [json.loads(line) for line in original_events.splitlines()]
        payload = events[-1]["payload"]
        if field == "reason":
            payload[field] = "wrong-reason"
        elif field == "process_identity":
            payload[field] = {
                "pid": owner["process_identity"]["pid"] + 100_000,
                "create_time_ns": owner["process_identity"]["create_time_ns"],
            }
        else:
            payload[field] = 0
        payload["content_sha256"] = content_sha256(payload)
        events[-1]["content_sha256"] = content_sha256(events[-1])
        events_path.write_bytes(
            b"".join(canonical_json_bytes(event) + b"\n" for event in events)
        )
        with pytest.raises((ValueError, BaseExceptionGroup)):
            close_owned_window(journal_path=journal, reason="exact-reason")
    finally:
        if original_events is not None:
            Path(str(journal) + ".events.jsonl").write_bytes(original_events)
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="exact-reason"))


@windows_only
def test_pre_ready_cleanup_has_explicit_non_window_subject(tmp_path: Path) -> None:
    image = tmp_path / "pre-ready-schema.bmp"
    digest = _bmp(image)
    journal = _register_journal(tmp_path / "pre-ready-schema.owner.json")
    try:
        with pytest.raises(RuntimeError, match="pre-transfer"):
            _launch_owned_window_for_test(
                image_path=image, expected_sha256=digest,
                operation_id="operation-pre-ready-schema", journal_path=journal,
                duplicate_window=False, fail_after_job_created=True,
            )
        receipt = close_owned_window(journal_path=journal, reason="schema-replay")
        assert receipt["cleanup_subject_kind"] == "no_process"
        assert receipt["ready_event_sha256"] is None
        assert receipt["publication_content_sha256"] is None
        assert receipt["process_identity"] == {"pid": 0, "create_time_ns": 0}
        assert receipt["exact_hwnd"] == 0
    finally:
        if journal.exists():
            close_owned_window(journal_path=journal, reason="schema-replay")


@windows_only
@pytest.mark.parametrize(
    "failure_stage",
    [
        "kill", "wait", "process_close", "scope_close", "event_close",
        "observe", "observe_final", "enum_after", "unlink",
    ],
)
def test_cleanup_failure_injection_preserves_retry_until_verified(
    tmp_path: Path, failure_stage: str
) -> None:
    image = tmp_path / f"cleanup-{failure_stage}.bmp"
    digest = _bmp(image)
    journal = _register_journal(tmp_path / f"cleanup-{failure_stage}.owner.json")
    try:
        launch_owned_window(
            image_path=image, expected_sha256=digest,
            operation_id=f"operation-cleanup-{failure_stage}", journal_path=journal,
        )
        with pytest.raises(BaseExceptionGroup, match="indeterminate"):
            _close_owned_window_for_test(
                journal_path=journal, reason="inject", failure_stage=failure_stage
            )
        events = _load_events(journal, owner_id=_load_root(journal)["owner_id"])
        assert all(event["event_type"] != "cleanup_verified" for event in events)
        _assert_cleanup(close_owned_window(journal_path=journal, reason="retry"))
    finally:
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
@pytest.mark.parametrize("failure_stage", ["signal", "signal_close"])
def test_partial_live_separate_signal_handle_is_closed_or_retained_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    image = tmp_path / f"partial-signal-{failure_stage}.bmp"
    digest = _bmp(image)
    journal = _register_journal(tmp_path / f"partial-signal-{failure_stage}.owner.json")
    closed_handles: list[int] = []
    original_close = _ShutdownEvent.close

    def tracked_close(self: _ShutdownEvent) -> None:
        original_close(self)
        closed_handles.append(id(self))

    try:
        launch_owned_window(
            image_path=image, expected_sha256=digest,
            operation_id=f"operation-partial-signal-{failure_stage}", journal_path=journal,
        )
        live = _LIVE_OWNERS[str(journal)]
        assert live.shutdown_event is not None
        live.shutdown_event.close()
        live.shutdown_event = None
        monkeypatch.setattr(_ShutdownEvent, "close", tracked_close)
        with pytest.raises(BaseExceptionGroup, match="indeterminate"):
            _close_owned_window_for_test(
                journal_path=journal, reason="partial", failure_stage=failure_stage
            )
        events = _load_events(journal, owner_id=_load_root(journal)["owner_id"])
        assert all(event["event_type"] != "cleanup_verified" for event in events)
        live = _LIVE_OWNERS[str(journal)]
        if failure_stage == "signal":
            assert closed_handles
            assert live.shutdown_event is None
        else:
            assert live.shutdown_event is not None
        _assert_cleanup(close_owned_window(journal_path=journal, reason="retry"))
    finally:
        monkeypatch.setattr(_ShutdownEvent, "close", original_close)
        if journal.exists():
            _assert_cleanup(close_owned_window(journal_path=journal, reason="test_finally"))


@windows_only
def test_premature_terminal_reconciliation_retains_failed_process_handle(tmp_path: Path) -> None:
    image = tmp_path / "terminal-retry.bmp"
    digest = _bmp(image)
    journal = _register_journal(tmp_path / "terminal-retry.owner.json")
    try:
        owner = launch_owned_window(
            image_path=image, expected_sha256=digest,
            operation_id="operation-terminal-retry", journal_path=journal,
        )
        _append_event(
            journal, owner_id=owner["owner_id"], event_type="finalization_intent",
            payload={"reason": "terminal-retry"},
        )
        lineage = _expected_cleanup_lineage(
            owner["journal_root"], _load_events(journal, owner_id=owner["owner_id"])
        )
        fake = {
            "contract_version": CLEANUP_CONTRACT, **lineage,
            "cleanup_status": "verified", "shutdown_event_signaled": True,
            "shutdown_event_error_code": 0, "shutdown_event_handle_closed": True,
            "enum_windows_exact_hwnd_absent": True, "matching_owned_windows_after": [],
            "member_pids_after": [], "stable_zero_observations": 3,
            "scope_absent_after_owner_close": True, "process_handle_closed": True,
            "job_handle_closed": True, "active_listeners_after": [],
            "listener_or_lease_residue": [], "outer_owner_python_finally_observed": True,
            "artifact_is_authorization": False, "execute_binding_enabled": False,
        }
        fake["content_sha256"] = content_sha256(fake)
        _append_event(
            journal, owner_id=owner["owner_id"], event_type="cleanup_verified", payload=fake
        )
        with pytest.raises(BaseExceptionGroup, match="indeterminate"):
            _close_owned_window_for_test(
                journal_path=journal, reason="ignored", failure_stage="process_close"
            )
        assert str(journal) in _LIVE_OWNERS
        assert _LIVE_OWNERS[str(journal)].process is not None
        replay = close_owned_window(journal_path=journal, reason="ignored")
        assert replay == fake
    finally:
        if journal.exists():
            close_owned_window(journal_path=journal, reason="ignored")


@windows_only
def test_wrong_lineage_live_terminal_still_runs_retryable_cleanup(tmp_path: Path) -> None:
    image = tmp_path / "wrong-live-terminal.bmp"
    digest = _bmp(image)
    journal = _register_journal(tmp_path / "wrong-live-terminal.owner.json")
    prefix = None
    try:
        owner = launch_owned_window(
            image_path=image, expected_sha256=digest,
            operation_id="operation-wrong-live-terminal", journal_path=journal,
        )
        _append_event(
            journal, owner_id=owner["owner_id"], event_type="finalization_intent",
            payload={"reason": "wrong-live"},
        )
        events_path = Path(str(journal) + ".events.jsonl")
        prefix = events_path.read_bytes()
        lineage = _expected_cleanup_lineage(
            owner["journal_root"], _load_events(journal, owner_id=owner["owner_id"])
        )
        lineage["process_identity"] = {
            "pid": owner["process_identity"]["pid"] + 100_000,
            "create_time_ns": owner["process_identity"]["create_time_ns"],
        }
        fake = {
            "contract_version": CLEANUP_CONTRACT, **lineage,
            "cleanup_status": "verified", "shutdown_event_signaled": True,
            "shutdown_event_error_code": 0, "shutdown_event_handle_closed": True,
            "enum_windows_exact_hwnd_absent": True, "matching_owned_windows_after": [],
            "member_pids_after": [], "stable_zero_observations": 3,
            "scope_absent_after_owner_close": True, "process_handle_closed": True,
            "job_handle_closed": True, "active_listeners_after": [],
            "listener_or_lease_residue": [], "outer_owner_python_finally_observed": True,
            "artifact_is_authorization": False, "execute_binding_enabled": False,
        }
        fake["content_sha256"] = content_sha256(fake)
        with pytest.raises(ValueError, match="cleanup|lineage"):
            _append_event(
                journal, owner_id=owner["owner_id"], event_type="cleanup_verified", payload=fake
            )
        with pytest.raises(BaseExceptionGroup, match="indeterminate"):
            close_owned_window(journal_path=journal, reason="ignored")
        assert not psutil.pid_exists(owner["process_identity"]["pid"])
        assert str(journal) in _LIVE_OWNERS
        events_path.write_bytes(prefix)
        _assert_cleanup(close_owned_window(journal_path=journal, reason="ignored"))
    finally:
        if prefix is not None:
            events_path = Path(str(journal) + ".events.jsonl")
            try:
                _load_events(journal, owner_id=_load_root(journal)["owner_id"])
            except ValueError:
                events_path.write_bytes(prefix)
        if journal.exists():
            close_owned_window(journal_path=journal, reason="ignored")


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
