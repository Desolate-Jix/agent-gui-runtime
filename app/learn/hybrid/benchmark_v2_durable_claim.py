"""Crash-safe local dual-anchor claim for the Benchmark-v2 holdout."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator, Mapping


RELEASE = "portfolio_hybrid_v1_1_benchmark_v2_release_1"
CORPUS = "8503010496a426893456e903b9d768f2a281ef0509f11230d312b073c0760757"
IDENTITY = {
    "benchmark_release_id": RELEASE,
    "corpus_parent_seal_sha256": CORPUS,
    "partition": "holdout",
}
SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "display_only": True,
}
EXACT_ARM_ORDER = (
    "qwen_only",
    "omni_only_discovery",
    "omni_to_qwen",
    "omni_to_qwen_vista",
)
EXACT_HOLDOUT_COMMAND = (
    "uv",
    "run",
    "python",
    "scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py",
    "--partition",
    "holdout",
)
EXACT_RUN_ORDER = ("sealed-regression", "sealed-holdout")
PROVIDER_MANIFEST_CONTRACT = "portfolio_hybrid_benchmark_v2_provider_manifest_v1"

_PRODUCTION_BASE = (
    Path(os.environ["LOCALAPPDATA"]) / "AgentGuiRuntime" / "PortfolioHybridBenchmarkV2"
).resolve()
PRODUCTION_FILE_ROOT = (_PRODUCTION_BASE / "Claims").resolve()
PRODUCTION_REGISTRY_ROOT = r"Software\AgentGuiRuntime\PortfolioHybridBenchmarkV2\Claims"
_SHA = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_UUID = re.compile(r"[0-9a-f]{32}")

_GENERIC_WRITE = 0x40000000
_FILE_READ_ATTRIBUTES = 0x80
_SYNCHRONIZE = 0x100000
_FILE_SHARE_READ = 0x1
_CREATE_NEW = 1
_FILE_ATTRIBUTE_READONLY = 0x1
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_FLAG_WRITE_THROUGH = 0x80000000
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x80
_INFINITE = 0xFFFFFFFF


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def claim_id(identity: Mapping[str, str]) -> str:
    if dict(identity) != IDENTITY:
        raise ValueError("holdout claim identity is not frozen")
    return hashlib.sha256(canonical_bytes(dict(identity))).hexdigest()


def envelope(contract: str, payload: Mapping[str, object]) -> tuple[dict[str, object], str]:
    body = dict(payload)
    wrapped = {
        "contract_version": contract,
        "payload": body,
        "payload_sha256": hashlib.sha256(canonical_bytes(body)).hexdigest(),
    }
    return wrapped, hashlib.sha256(canonical_bytes(wrapped)).hexdigest()


def _closed_sha_map(value: object, *, profile: bool = False) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    for key, digest in value.items():
        if not isinstance(key, str) or not isinstance(digest, str) or _SHA.fullmatch(digest) is None:
            return False
        if profile:
            if _ID.fullmatch(key) is None:
                return False
        else:
            path = PurePosixPath(key)
            if (
                not key
                or "\\" in key
                or path.is_absolute()
                or any(part in {"", ".", ".."} for part in path.parts)
                or str(path) != key
            ):
                return False
    return True


def _validate_authorization_shape(payload: Mapping[str, object]) -> None:
    required = {
        "contract_version",
        "claim_identity",
        "claim_id",
        "ledger_identity",
        "fixed_authorization_path",
        "provider_manifest_sha256",
        "provider_manifest_contract_version",
        "code_sha256_by_path",
        "config_sha256_by_path",
        "profile_sha256_by_id",
        "arm_order",
        "exact_holdout_command",
        "exact_run_order",
        "absolute_owner_journal_root",
    }
    if set(payload) != required:
        raise ValueError("holdout authorization field set invalid")
    if payload["contract_version"] != "portfolio_hybrid_benchmark_v2_holdout_authorization_payload_v1":
        raise ValueError("holdout authorization contract invalid")
    if payload["claim_identity"] != IDENTITY or payload["claim_id"] != claim_id(IDENTITY):
        raise ValueError("holdout authorization claim identity invalid")
    ledger = payload["ledger_identity"]
    if not isinstance(ledger, dict) or set(ledger) != {
        "absolute_ledger_root",
        "holdout_events_path",
        "genesis_envelope_sha256",
    }:
        raise ValueError("holdout authorization ledger identity invalid")
    for key in ("absolute_ledger_root", "holdout_events_path"):
        if not isinstance(ledger[key], str) or not Path(ledger[key]).is_absolute():
            raise ValueError("holdout authorization ledger path invalid")
    if not isinstance(ledger["genesis_envelope_sha256"], str) or _SHA.fullmatch(
        ledger["genesis_envelope_sha256"]
    ) is None:
        raise ValueError("holdout authorization genesis ref invalid")
    if not isinstance(payload["fixed_authorization_path"], str) or not Path(
        payload["fixed_authorization_path"]
    ).is_absolute():
        raise ValueError("holdout authorization fixed path invalid")
    if not isinstance(payload["absolute_owner_journal_root"], str) or not Path(
        payload["absolute_owner_journal_root"]
    ).is_absolute():
        raise ValueError("holdout authorization owner root invalid")
    if not isinstance(payload["provider_manifest_sha256"], str) or _SHA.fullmatch(
        payload["provider_manifest_sha256"]
    ) is None:
        raise ValueError("holdout authorization provider SHA invalid")
    if payload["provider_manifest_contract_version"] != PROVIDER_MANIFEST_CONTRACT:
        raise ValueError("holdout authorization provider contract invalid")
    if not _closed_sha_map(payload["code_sha256_by_path"]):
        raise ValueError("holdout authorization code map invalid")
    if not _closed_sha_map(payload["config_sha256_by_path"]):
        raise ValueError("holdout authorization config map invalid")
    if not _closed_sha_map(payload["profile_sha256_by_id"], profile=True):
        raise ValueError("holdout authorization profile map invalid")
    if payload["arm_order"] != list(EXACT_ARM_ORDER):
        raise ValueError("holdout authorization arm order invalid")
    if payload["exact_holdout_command"] != list(EXACT_HOLDOUT_COMMAND):
        raise ValueError("holdout authorization command invalid")
    if payload["exact_run_order"] != list(EXACT_RUN_ORDER):
        raise ValueError("holdout authorization run order invalid")


def authorization_envelope(payload: Mapping[str, object]) -> tuple[dict[str, object], str]:
    _validate_authorization_shape(payload)
    return envelope("portfolio_hybrid_benchmark_v2_holdout_authorization_envelope_v1", payload)


@dataclass(frozen=True)
class _Backend:
    file_root: Path
    registry_root: str
    ledger_root: Path
    owner_journal_root: Path
    test_capability: str | None = None


def _overlaps(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _registry_overlaps(left: str, right: str) -> bool:
    lparts = tuple(part.casefold() for part in left.strip("\\").split("\\"))
    rparts = tuple(part.casefold() for part in right.strip("\\").split("\\"))
    shortest = min(len(lparts), len(rparts))
    return lparts[:shortest] == rparts[:shortest]


def _test_backend(
    *, file_root: Path, registry_root: str, ledger_root: Path, capability: str
) -> _Backend:
    raw_file = Path(file_root)
    raw_ledger = Path(ledger_root)
    if not capability or not raw_file.is_absolute() or not raw_ledger.is_absolute():
        raise ValueError("test backend capability/root invalid")
    file_path = raw_file.resolve()
    ledger_path = raw_ledger.resolve()
    base = file_path.parent
    token = base.name
    expected_registry = rf"Software\AgentGuiRuntime\Tests\PortfolioHybridBenchmarkV2\{token}\Claims"
    temp_root = Path(tempfile.gettempdir()).resolve()
    local_root = Path(os.environ["LOCALAPPDATA"]).resolve()
    schema_ok = (
        file_path == base / "Claims"
        and ledger_path == base / "Ledger"
        and base.parent.name == "PortfolioHybridBenchmarkV2"
        and base.parent.parent.name == "Tests"
        and base.parent.parent.parent.name == "AgentGuiRuntime"
        and _UUID.fullmatch(token) is not None
        and capability == token
        and registry_root == expected_registry
        and str(raw_file) == str(file_path)
        and str(raw_ledger) == str(ledger_path)
        and (base.is_relative_to(temp_root) or base.is_relative_to(local_root))
    )
    production_paths = (
        PRODUCTION_FILE_ROOT,
        PRODUCTION_FILE_ROOT / "ledger",
        PRODUCTION_FILE_ROOT / "owner",
    )
    test_paths = (file_path, ledger_path, base / "OwnerJournal")
    if (
        not schema_ok
        or any(_overlaps(test, production) for test in test_paths for production in production_paths)
        or _registry_overlaps(registry_root, PRODUCTION_REGISTRY_ROOT)
        or any(_overlaps(left, right) for index, left in enumerate(test_paths) for right in test_paths[index + 1 :])
    ):
        raise ValueError("test backend overlaps production or violates fixed schema")
    return _Backend(
        file_root=file_path,
        registry_root=expected_registry,
        ledger_root=ledger_path,
        owner_journal_root=(base / "OwnerJournal").resolve(),
        test_capability=capability,
    )


def _production_backend() -> _Backend:
    return _Backend(
        file_root=PRODUCTION_FILE_ROOT,
        registry_root=PRODUCTION_REGISTRY_ROOT,
        ledger_root=(PRODUCTION_FILE_ROOT / "ledger").resolve(),
        owner_journal_root=(PRODUCTION_FILE_ROOT / "owner").resolve(),
    )


def _validate_authorization_for_backend(
    backend: _Backend, payload: Mapping[str, object]
) -> None:
    _validate_authorization_shape(payload)
    cid = claim_id(IDENTITY)
    ledger = payload["ledger_identity"]
    expected = {
        "fixed_authorization_path": backend.file_root / f"{cid}.authorization.json",
        "absolute_ledger_root": backend.ledger_root,
        "holdout_events_path": backend.ledger_root / "holdout" / "events.jsonl",
        "absolute_owner_journal_root": backend.owner_journal_root,
    }
    actual = {
        "fixed_authorization_path": payload["fixed_authorization_path"],
        "absolute_ledger_root": ledger["absolute_ledger_root"],
        "holdout_events_path": ledger["holdout_events_path"],
        "absolute_owner_journal_root": payload["absolute_owner_journal_root"],
    }
    expected_text = {key: str(value) for key, value in expected.items()}
    mismatched = {
        key: (actual[key], expected_text[key])
        for key in expected
        if actual[key] != expected_text[key]
    }
    if mismatched:
        raise ValueError(f"holdout authorization paths are not bound to backend: {mismatched}")


def _current_user_sid() -> str:
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return win32security.ConvertSidToStringSid(sid)
    finally:
        token.Close()


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


def _control_matches(
    control: Mapping[str, object] | None, key: str, label: str
) -> bool:
    return dict(control or {}).get(key) == label


class _SecurityBuffer:
    def __init__(
        self,
        kind: str,
        label: str,
        control: Mapping[str, object] | None,
    ) -> None:
        rights = {"file": "FA", "registry": "KA", "mutex": "GA"}[kind]
        sddl = f"D:P(A;;{rights};;;SY)(A;;{rights};;;{_current_user_sid()})"
        self._label = label
        self._control = control
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._pointer = ctypes.c_void_p()
        self._closed = False
        self._advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        )
        self._advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
            wintypes.BOOL
        )
        if not self._advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(self._pointer), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        self._attributes = _SECURITY_ATTRIBUTES(
            ctypes.sizeof(_SECURITY_ATTRIBUTES), self._pointer, False
        )

    @property
    def pointer(self) -> ctypes.POINTER(_SECURITY_ATTRIBUTES):
        if self._closed:
            raise RuntimeError("security buffer is closed")
        return ctypes.pointer(self._attributes)

    def close(self) -> None:
        if self._closed:
            return
        self._kernel.LocalFree.argtypes = (ctypes.c_void_p,)
        self._kernel.LocalFree.restype = ctypes.c_void_p
        self._kernel.SetLastError.argtypes = (wintypes.DWORD,)
        if _control_matches(
            self._control, "security_clobber_last_error_for", self._label
        ):
            self._kernel.SetLastError(5)
        remaining = self._kernel.LocalFree(self._pointer)
        free_error = ctypes.get_last_error()
        if remaining:
            retry_remaining = self._kernel.LocalFree(remaining)
            retry_error = ctypes.get_last_error()
            if retry_remaining:
                raise BaseExceptionGroup(
                    f"{self._label} security cleanup failed",
                    [ctypes.WinError(free_error), ctypes.WinError(retry_error)],
                )
            self._closed = True
            raise ctypes.WinError(free_error)
        self._closed = True
        if _control_matches(
            self._control, "security_cleanup_failure_for", self._label
        ):
            raise OSError(995, f"{self._label} security cleanup failure")


def _raise_wrapper_failures(
    primary: BaseException | None, cleanup: list[BaseException]
) -> None:
    if primary is not None and cleanup:
        raise BaseExceptionGroup("wrapper cleanup failed", [primary, *cleanup])
    if primary is not None:
        raise primary
    if cleanup:
        raise BaseExceptionGroup("wrapper cleanup failed", cleanup)


def _close_kernel_handle(
    kernel: object,
    handle: int,
    *,
    label: str,
    control: Mapping[str, object] | None,
) -> None:
    try:
        _close_handle_checked(kernel, handle)
    except BaseException as first:
        try:
            _close_handle_checked(kernel, handle)
        except BaseException as second:
            raise BaseExceptionGroup(
                f"{label} handle cleanup failed", [first, second]
            )
        raise first
    if _control_matches(control, "close_failure_for", label):
        raise OSError(6, f"{label} injected close failure")


def _lock_name(kind: str, material: str) -> str:
    digest = hashlib.sha256(material.casefold().encode("utf-8")).hexdigest()
    return f"Local\\AgentGuiBenchmarkV2-{kind}-{digest}"


@contextmanager
def _named_mutex(
    name: str, *, test_control: Mapping[str, object] | None = None
) -> Iterator[None]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    security = _SecurityBuffer("mutex", "mutex", test_control)
    handle = None
    acquired = False
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        handle = kernel.CreateMutexW(security.pointer, False, name)
        create_error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(create_error)
        wait = int(kernel.WaitForSingleObject(handle, _INFINITE))
        if wait not in {_WAIT_OBJECT_0, _WAIT_ABANDONED}:
            raise OSError(wait, "WaitForSingleObject mutex failed")
        acquired = True
        yield
    except BaseException as error:
        primary = error
    finally:
        if acquired:
            try:
                if not kernel.ReleaseMutex(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            except BaseException as error:
                cleanup.append(error)
        if handle:
            try:
                _close_kernel_handle(
                    kernel,
                    handle,
                    label="mutex",
                    control=test_control,
                )
            except BaseException as error:
                cleanup.append(error)
        try:
            security.close()
        except BaseException as error:
            cleanup.append(error)
    _raise_wrapper_failures(primary, cleanup)


def _claim_mutex_name(backend: _Backend) -> str:
    return _lock_name("claim", backend.registry_root + "\\" + claim_id(IDENTITY))


def _ledger_mutex_name(path: Path) -> str:
    return _lock_name("ledger", str(Path(path).resolve()))


def _close_handle_checked(kernel: object, handle: int) -> None:
    if not kernel.CloseHandle(handle):
        raise OSError(ctypes.get_last_error(), "CloseHandle failed")


def _dacl_is_exact(security_descriptor: object, *, kind: str) -> bool:
    import win32security

    control, _ = security_descriptor.GetSecurityDescriptorControl()
    if not control & win32security.SE_DACL_PROTECTED:
        return False
    dacl = security_descriptor.GetSecurityDescriptorDacl()
    if dacl is None or dacl.GetAceCount() != 2:
        return False
    expected_mask = 0x1F01FF if kind == "file" else 0xF003F
    expected_sids = {_current_user_sid(), "S-1-5-18"}
    found: set[str] = set()
    for index in range(dacl.GetAceCount()):
        header, mask, sid = dacl.GetAce(index)
        if header[0] != win32security.ACCESS_ALLOWED_ACE_TYPE or header[1] != 0:
            return False
        if int(mask) != expected_mask:
            return False
        found.add(win32security.ConvertSidToStringSid(sid))
    return found == expected_sids


def _file_anchor_exact(path: Path, *, size: int, raw: bytes | None = None) -> bool:
    import win32security

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetFileAttributesW.argtypes = (wintypes.LPCWSTR,)
    kernel.GetFileAttributesW.restype = wintypes.DWORD
    attributes = int(kernel.GetFileAttributesW(str(path)))
    if attributes == 0xFFFFFFFF:
        return False
    if not attributes & _FILE_ATTRIBUTE_READONLY or attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    try:
        if path.stat().st_size != size:
            return False
        if raw is not None and path.read_bytes() != raw:
            return False
        descriptor = win32security.GetNamedSecurityInfo(
            str(path), win32security.SE_FILE_OBJECT, win32security.DACL_SECURITY_INFORMATION
        )
    except (OSError, ValueError):
        return False
    return _dacl_is_exact(descriptor, kind="file")


def _write_secure_new_file(
    path: Path, raw: bytes, *, test_control: Mapping[str, object] | None = None
) -> bool:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    kernel.FlushFileBuffers.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    security = _SecurityBuffer("file", "authorization", test_control)
    handle = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    result: bool | None = None
    try:
        handle = kernel.CreateFileW(
            str(path),
            _GENERIC_WRITE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
            _FILE_SHARE_READ,
            security.pointer,
            _CREATE_NEW,
            _FILE_ATTRIBUTE_READONLY | _FILE_FLAG_WRITE_THROUGH,
            None,
        )
        create_error = ctypes.get_last_error()
        if handle == _INVALID_HANDLE:
            handle = None
            if create_error in {80, 183}:
                result = False
            else:
                raise ctypes.WinError(create_error)
        else:
            pause = dict(test_control or {}).get("pause_after_authorization_create")
            if isinstance(pause, Mapping):
                Path(str(pause["ready_path"])).write_text("created", encoding="utf-8")
                release = Path(str(pause["release_path"]))
                deadline = time.monotonic() + 20
                while not release.exists():
                    if time.monotonic() >= deadline:
                        raise TimeoutError(release)
                    time.sleep(0.01)
            if _control_matches(test_control, "body_failure_for", "authorization"):
                raise ValueError("authorization injected body failure")
            if raw:
                buffer = ctypes.create_string_buffer(raw)
                written = wintypes.DWORD()
                if not kernel.WriteFile(
                    handle, buffer, len(raw), ctypes.byref(written), None
                ) or int(written.value) != len(raw):
                    raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.FlushFileBuffers(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            result = True
    except BaseException as error:
        primary = error
    finally:
        if handle:
            try:
                _close_kernel_handle(
                    kernel,
                    handle,
                    label="authorization",
                    control=test_control,
                )
            except BaseException as error:
                cleanup.append(error)
        try:
            security.close()
        except BaseException as error:
            cleanup.append(error)
    _raise_wrapper_failures(primary, cleanup)
    assert result is not None
    return result


def _authorization_ref(
    backend: _Backend, wrapped: Mapping[str, object], digest: str
) -> dict[str, str]:
    cid = claim_id(IDENTITY)
    return {
        "authorization_id": f"holdout-authorization/{cid}",
        "envelope_sha256": digest,
        "fixed_authorization_path": str(
            (backend.file_root / f"{cid}.authorization.json").resolve()
        ),
    }


def _create_authorization(
    backend: _Backend,
    wrapped: Mapping[str, object],
    digest: str,
    *,
    test_control: Mapping[str, object] | None,
) -> dict[str, str]:
    path = (backend.file_root / f"{claim_id(IDENTITY)}.authorization.json").resolve()
    backend.file_root.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(wrapped)
    created = _write_secure_new_file(path, raw, test_control=test_control)
    if not created and not _file_anchor_exact(path, size=len(raw), raw=raw):
        raise ValueError("permanent_refusal: authorization byte or security drift")
    if created and not _file_anchor_exact(path, size=len(raw), raw=raw):
        raise ValueError("permanent_refusal: authorization publication invalid")
    return _authorization_ref(backend, wrapped, digest)


def _sentinel_create(
    path: Path,
    failpoint: str | None,
    *,
    test_control: Mapping[str, object] | None = None,
) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    kernel.FlushFileBuffers.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    security = _SecurityBuffer("file", "sentinel", test_control)
    handle = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    result: bool | None = None
    try:
        handle = kernel.CreateFileW(
            str(path),
            _GENERIC_WRITE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
            _FILE_SHARE_READ,
            security.pointer,
            _CREATE_NEW,
            _FILE_ATTRIBUTE_READONLY | _FILE_FLAG_WRITE_THROUGH,
            None,
        )
        create_error = ctypes.get_last_error()
        if handle == _INVALID_HANDLE:
            handle = None
            if create_error in {80, 183}:
                result = False
            else:
                raise ctypes.WinError(create_error)
        else:
            if failpoint == "sentinel_before_flush":
                os._exit(89)
            if _control_matches(test_control, "body_failure_for", "sentinel"):
                raise ValueError("sentinel injected body failure")
            if not kernel.FlushFileBuffers(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            result = True
    except BaseException as error:
        primary = error
    finally:
        if handle:
            try:
                _close_kernel_handle(
                    kernel,
                    handle,
                    label="sentinel",
                    control=test_control,
                )
            except BaseException as error:
                cleanup.append(error)
        try:
            security.close()
        except BaseException as error:
            cleanup.append(error)
    _raise_wrapper_failures(primary, cleanup)
    assert result is not None
    if result and not _file_anchor_exact(path, size=0):
        raise ValueError("sentinel attributes or security invalid")
    return result


_REG_VALUES = {
    "ContractVersion": 1,
    "ClaimId": 1,
    "AuthorizationEnvelopeSha256": 1,
    "ClaimEnvelope": 3,
    "ClaimEnvelopeSha256": 1,
}


def _registry_security_exact(key: object) -> bool:
    import win32security

    try:
        descriptor = win32security.GetSecurityInfo(
            int(key), win32security.SE_REGISTRY_KEY, win32security.DACL_SECURITY_INFORMATION
        )
    except OSError:
        return False
    return _dacl_is_exact(descriptor, kind="registry")


def _registry_read(backend: _Backend, cid: str) -> dict[str, object] | None:
    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            backend.registry_root + "\\" + cid,
            0,
            winreg.KEY_READ | 0x20000 | winreg.KEY_WOW64_64KEY,
        )
    except FileNotFoundError:
        return None
    try:
        if not _registry_security_exact(key):
            raise ValueError("permanent_refusal: registry security mismatch")
        found: dict[str, tuple[object, int]] = {}
        index = 0
        while True:
            try:
                name, value, kind = winreg.EnumValue(key, index)
            except OSError:
                break
            found[name] = (value, kind)
            index += 1
        if set(found) != set(_REG_VALUES) or any(
            found[key][1] != kind for key, kind in _REG_VALUES.items()
        ):
            raise ValueError("permanent_refusal: registry schema mismatch")
        return {key: found[key][0] for key in found}
    finally:
        winreg.CloseKey(key)


def _registry_create(
    backend: _Backend,
    cid: str,
    values: Mapping[str, object],
    failpoint: str | None,
    *,
    test_control: Mapping[str, object] | None = None,
) -> bool:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    handle = wintypes.HKEY()
    disposition = wintypes.DWORD()
    advapi.RegCreateKeyExW.argtypes = (
        wintypes.HKEY,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.HKEY),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi.RegSetValueExW.argtypes = (
        wintypes.HKEY,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    advapi.RegFlushKey.argtypes = (wintypes.HKEY,)
    advapi.RegCloseKey.argtypes = (wintypes.HKEY,)
    subkey = backend.registry_root + "\\" + cid
    security = _SecurityBuffer("registry", "registry", test_control)
    acquired = False
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    result: bool | None = None
    try:
        rc = advapi.RegCreateKeyExW(
            0x80000001,
            subkey,
            0,
            None,
            0,
            0x1 | 0x2 | 0x4 | 0x20000 | 0x100,
            security.pointer,
            ctypes.byref(handle),
            ctypes.byref(disposition),
        )
        if rc:
            raise OSError(rc, "RegCreateKeyExW failed")
        acquired = True
        if disposition.value != 1:
            result = False
        else:
            if failpoint == "registry_create":
                os._exit(91)
            if _control_matches(test_control, "body_failure_for", "registry"):
                raise ValueError("registry injected body failure")
            for name in (
                "ContractVersion",
                "ClaimId",
                "AuthorizationEnvelopeSha256",
                "ClaimEnvelope",
                "ClaimEnvelopeSha256",
            ):
                value = values[name]
                if isinstance(value, bytes):
                    buffer = ctypes.create_string_buffer(value)
                    kind = 3
                    size = len(value)
                else:
                    buffer = ctypes.create_unicode_buffer(str(value))
                    kind = 1
                    size = ctypes.sizeof(buffer)
                rc = advapi.RegSetValueExW(
                    handle,
                    name,
                    0,
                    kind,
                    ctypes.cast(buffer, ctypes.c_void_p),
                    size,
                )
                if rc:
                    raise OSError(rc, "RegSetValueExW failed")
                if failpoint == "registry_record" and name == "ClaimEnvelope":
                    os._exit(92)
            if failpoint == "registry_flush":
                os._exit(93)
            rc = advapi.RegFlushKey(handle)
            if rc:
                raise OSError(rc, "RegFlushKey failed")
            result = True
    except BaseException as error:
        primary = error
    finally:
        if acquired:
            try:
                rc = advapi.RegCloseKey(handle)
                if rc:
                    retry_rc = advapi.RegCloseKey(handle)
                    if retry_rc:
                        raise BaseExceptionGroup(
                            "registry handle cleanup failed",
                            [
                                OSError(rc, "RegCloseKey failed"),
                                OSError(retry_rc, "RegCloseKey retry failed"),
                            ],
                        )
                    raise OSError(rc, "RegCloseKey failed before successful retry")
                if _control_matches(test_control, "close_failure_for", "registry"):
                    raise OSError(6, "registry injected close failure")
            except BaseException as error:
                cleanup.append(error)
        try:
            security.close()
        except BaseException as error:
            cleanup.append(error)
    _raise_wrapper_failures(primary, cleanup)
    assert result is not None
    return result


def _claim_payload(
    auth_ref: Mapping[str, str], authorization_payload: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, object], str]:
    cid = claim_id(IDENTITY)
    attempt = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + cid
            + "\0"
            + auth_ref["envelope_sha256"]
        ).encode("utf-8")
    ).hexdigest()
    payload = {
        "claim_id": cid,
        "authorization_ref": dict(auth_ref),
        "attempt_id": attempt,
        "provider_manifest_sha256": authorization_payload["provider_manifest_sha256"],
        "absolute_owner_journal_root": authorization_payload["absolute_owner_journal_root"],
        "state": "consumed",
    }
    wrapped, digest = envelope(
        "portfolio_hybrid_benchmark_v2_holdout_claim_envelope_v1", payload
    )
    return payload, wrapped, digest


def _mirror_claim(
    backend: _Backend,
    auth_ref: Mapping[str, str],
    claim_ref: Mapping[str, str],
    *,
    require_existing_genesis: bool,
) -> None:
    from app.learn.hybrid.benchmark_v2_holdout import (
        _append_locked,
        _chain,
        _ledger_lock,
        _validate_genesis_ref,
    )

    path = backend.ledger_root / "holdout" / "events.jsonl"
    with _ledger_lock(path):
        chain = _chain(path)
        if not chain:
            if require_existing_genesis:
                raise ValueError("holdout exact genesis is required before first claim")
            _validate_genesis_ref(backend.ledger_root, auth_ref)
            event = {
                "partition": "holdout",
                "sequence": 0,
                "event_type": "authorized_genesis",
                "previous_envelope_sha256": "0" * 64,
                "event_payload": {
                    "claim_id": claim_id(IDENTITY),
                    "authorization_ref": dict(auth_ref),
                    "safety": dict(SAFETY),
                },
            }
            _append_locked(path, event)
            chain = _chain(path)
        expected = {
            "claim_id": claim_id(IDENTITY),
            "authorization_ref": dict(auth_ref),
            "safety": SAFETY,
        }
        if (
            chain[0]["event"]["event_type"] != "authorized_genesis"
            or chain[0]["event"]["event_payload"] != expected
        ):
            raise ValueError("holdout genesis mismatch")
        claims = [
            item for item in chain[1:] if item["event"]["event_type"] == "claim_consumed"
        ]
        expected_claim = {"claim_ref": dict(claim_ref), "safety": SAFETY}
        if claims:
            if len(claims) != 1 or claims[0]["event"]["event_payload"] != expected_claim:
                raise ValueError("holdout claim mirror mismatch")
            return
        previous = hashlib.sha256(canonical_bytes(chain[-1])).hexdigest()
        _append_locked(
            path,
            {
                "partition": "holdout",
                "sequence": len(chain),
                "event_type": "claim_consumed",
                "previous_envelope_sha256": previous,
                "event_payload": {
                    "claim_ref": dict(claim_ref),
                    "safety": dict(SAFETY),
                },
            },
        )


def _require_fresh_genesis(backend: _Backend, auth_ref: Mapping[str, str]) -> None:
    from app.learn.hybrid.benchmark_v2_holdout import _chain, _ledger_lock

    path = backend.ledger_root / "holdout" / "events.jsonl"
    with _ledger_lock(path):
        chain = _chain(path)
        expected = {
            "claim_id": claim_id(IDENTITY),
            "authorization_ref": dict(auth_ref),
            "safety": SAFETY,
        }
        if (
            len(chain) != 1
            or chain[0]["event"]["event_type"] != "authorized_genesis"
            or chain[0]["event"]["event_payload"] != expected
        ):
            raise ValueError("holdout exact zero-claim genesis required")


def _inspect(
    backend: _Backend,
    auth_ref: Mapping[str, str],
    expected_values: Mapping[str, object],
) -> str:
    cid = claim_id(IDENTITY)
    sentinels = list(backend.file_root.glob(f"{cid}--*.claim"))
    exact = backend.file_root / f"{cid}--{auth_ref['envelope_sha256']}.claim"
    try:
        registry = _registry_read(backend, cid)
    except ValueError:
        return "permanent_refusal"
    if len(sentinels) > 1 or any(
        path != exact or not _file_anchor_exact(path, size=0) for path in sentinels
    ):
        return "permanent_refusal"
    sentinel = bool(sentinels)
    if registry is not None and registry != expected_values:
        return "permanent_refusal"
    if sentinel and registry is not None:
        return "consumed"
    if sentinel or registry is not None:
        return "consumed_incomplete"
    return "fresh"


def _expected_claim_values(
    backend: _Backend, authorization: Mapping[str, object]
) -> tuple[dict[str, str], dict[str, object], dict[str, object], str, dict[str, object]]:
    wrapped, digest = authorization_envelope(authorization)
    auth_ref = _authorization_ref(backend, wrapped, digest)
    payload, claim_wrapped, claim_digest = _claim_payload(auth_ref, authorization)
    expected = {
        "ContractVersion": "portfolio_hybrid_benchmark_v2_holdout_claim_envelope_v1",
        "ClaimId": payload["claim_id"],
        "AuthorizationEnvelopeSha256": auth_ref["envelope_sha256"],
        "ClaimEnvelope": canonical_bytes(claim_wrapped),
        "ClaimEnvelopeSha256": claim_digest,
    }
    return auth_ref, payload, claim_wrapped, claim_digest, expected


def _claim_with_backend(
    *,
    backend: _Backend,
    authorization: Mapping[str, object],
    failpoint: str | None = None,
    test_control: Mapping[str, object] | None = None,
) -> dict[str, object]:
    _validate_authorization_for_backend(backend, authorization)
    wrapped, digest = authorization_envelope(authorization)
    with _named_mutex(_claim_mutex_name(backend)):
        auth_ref = _create_authorization(
            backend, wrapped, digest, test_control=test_control
        )
        _, payload, _, claim_digest, expected = _expected_claim_values(
            backend, authorization
        )
        state = _inspect(backend, auth_ref, expected)
        if state != "fresh":
            return {
                "state": state,
                "claim_id": payload["claim_id"],
                "attempt_id": payload["attempt_id"],
                "newly_created": False,
                "safety": dict(SAFETY),
            }
        claim_ref = {
            "id": f"holdout-claim/{payload['claim_id']}",
            "envelope_sha256": claim_digest,
        }
        _require_fresh_genesis(backend, auth_ref)
        sentinel = (
            backend.file_root
            / f"{payload['claim_id']}--{auth_ref['envelope_sha256']}.claim"
        )
        if not _sentinel_create(
            sentinel, failpoint, test_control=test_control
        ):
            return {
                "state": "consumed_incomplete",
                "claim_id": payload["claim_id"],
                "attempt_id": payload["attempt_id"],
                "newly_created": False,
                "safety": dict(SAFETY),
            }
        if failpoint == "sentinel_create":
            os._exit(90)
        created = _registry_create(
            backend,
            str(payload["claim_id"]),
            expected,
            failpoint,
            test_control=test_control,
        )
        state = _inspect(backend, auth_ref, expected)
        if state == "consumed":
            _mirror_claim(
                backend, auth_ref, claim_ref, require_existing_genesis=False
            )
        return {
            "state": state,
            "claim_id": payload["claim_id"],
            "attempt_id": payload["attempt_id"],
            "claim_ref": claim_ref,
            "newly_created": bool(created and state == "consumed"),
            "safety": dict(SAFETY),
        }


def _claim_with_backend_for_test(
    *,
    backend: _Backend,
    authorization: Mapping[str, object],
    failpoint: str | None = None,
    test_control: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if backend.test_capability is None:
        raise ValueError("explicit test backend capability required")
    return _claim_with_backend(
        backend=backend,
        authorization=authorization,
        failpoint=failpoint,
        test_control=test_control,
    )


def _recover_with_backend(
    *, backend: _Backend, authorization: Mapping[str, object]
) -> dict[str, object]:
    _validate_authorization_for_backend(backend, authorization)
    wrapped, digest = authorization_envelope(authorization)
    with _named_mutex(_claim_mutex_name(backend)):
        auth_ref, payload, _, claim_digest, expected = _expected_claim_values(
            backend, authorization
        )
        path = Path(auth_ref["fixed_authorization_path"])
        raw = canonical_bytes(wrapped)
        if not _file_anchor_exact(path, size=len(raw), raw=raw):
            state = "permanent_refusal"
        else:
            state = _inspect(backend, auth_ref, expected)
        if state == "consumed":
            _mirror_claim(
                backend,
                auth_ref,
                {
                    "id": f"holdout-claim/{payload['claim_id']}",
                    "envelope_sha256": claim_digest,
                },
                require_existing_genesis=False,
            )
        return {
            "state": state,
            "claim_id": payload["claim_id"],
            "attempt_id": payload["attempt_id"],
            "safety": dict(SAFETY),
        }


def _recover_with_backend_for_test(
    *, backend: _Backend, authorization: Mapping[str, object]
) -> dict[str, object]:
    if backend.test_capability is None:
        raise ValueError("explicit test backend capability required")
    return _recover_with_backend(backend=backend, authorization=authorization)


def recover_with_backend_for_test(
    *, backend: _Backend, authorization: Mapping[str, object]
) -> dict[str, object]:
    return _recover_with_backend_for_test(backend=backend, authorization=authorization)


def _set_file_dacl_for_test(path: Path, sddl: str) -> None:
    import win32security

    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1)
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        descriptor.GetSecurityDescriptorDacl(),
        None,
    )


def _set_registry_dacl_for_test(backend: _Backend, cid: str, sddl: str) -> None:
    import win32security
    import winreg

    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1)
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        backend.registry_root + "\\" + cid,
        0,
        0x40000 | winreg.KEY_WOW64_64KEY,
    )
    try:
        win32security.SetSecurityInfo(
            int(key),
            win32security.SE_REGISTRY_KEY,
            win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            descriptor.GetSecurityDescriptorDacl(),
            None,
        )
    finally:
        winreg.CloseKey(key)


__all__ = ["claim_id", "authorization_envelope", "SAFETY"]
