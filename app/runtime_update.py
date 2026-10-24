"""Explicit, transactional updates from this project's HTTPS GitHub releases.

SHA-256 binds confirmation to exact bytes; it is NOT a publisher signature.
This module never runs a downloaded installer or a metadata-supplied command.
Only unchanged-environment source payloads are admitted. Maintenance, unresolved
task admission and an independent no-input health check remain mandatory.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import time
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4
import zipfile


REPOSITORY = "Desolate-Jix/agent-gui-runtime"
RELEASES_URL = "https://api.github.com/repos/" + REPOSITORY + "/releases?per_page=100"
PYTHON_CONTRACT = "api-agent-cpython-3.11-3.12.v1"
PRODUCT_ID = "AgentGUIRuntimeExecutionPreview"
TRUST = "github_https_explicit_confirmation_unsigned"
MAX_METADATA = 2 * 1024 * 1024
MAX_PAYLOAD = 128 * 1024 * 1024
MAX_INSTALLER = 160 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_FILES = 10000
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_VERSION = re.compile(r"(0|[1-9][0-9]{0,7})\.(0|[1-9][0-9]{0,7})\.(0|[1-9][0-9]{0,7})\Z")
_RESERVED = {".component-install.json", "uninstall.exe"}
_FORBIDDEN_ROOTS = {".git", ".python", ".setup-cache", "data", "models", "weights", "sessions", "libraries", "user-data"}
_ALLOWED_ROOTS = {"app", "modules", "scripts", "requirements", "schemas", "docs", "integrations", "skills", "configs"}


class RuntimeUpdateError(ValueError):
    pass


class RuntimeRollbackError(RuntimeUpdateError):
    """Backups and the startup-blocking pending marker have been preserved."""


def _require(condition, code):
    if not condition:
        raise RuntimeUpdateError(code)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(RuntimeUpdateError("nonfinite_json")))
    except (UnicodeError, TypeError, json.JSONDecodeError, RecursionError) as error:
        raise RuntimeUpdateError("invalid_json") from error


def _read_json(path, maximum=MAX_METADATA):
    _plain(path)
    _require(path.is_file() and path.stat().st_size <= maximum, "metadata_missing_or_too_large")
    return _json(path.read_bytes())


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _version(value):
    _require(isinstance(value, str) and _VERSION.fullmatch(value) is not None, "stable_semver_required")
    return tuple(map(int, value.split(".")))


def _safe_name(name, *, metadata=False):
    _require(isinstance(name, str) and bool(name) and "\\" not in name and ":" not in name, "unsafe_payload_path")
    parts = name.split("/")
    _require(all(part and part not in {".", ".."} and not part.endswith((".", " "))
                 and not any(ord(c) < 32 or c in '<>"|?*' for c in part)
                 and re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I) is None
                 for part in parts), "unsafe_payload_path")
    _require(not PurePosixPath(name).is_absolute(), "unsafe_payload_path")
    if metadata and name.casefold() in _RESERVED:
        return name
    _require(name.casefold() not in _RESERVED, "reserved_payload_path")
    first = parts[0].casefold()
    _require(first not in _FORBIDDEN_ROOTS and not first.startswith(".venv")
             and not first.startswith(".runtime") and not first.startswith("mcp-config.local")
             and "__pycache__" not in {x.casefold() for x in parts}, "protected_payload_path")
    _require(len(parts) == 1 or first in _ALLOWED_ROOTS, "unsupported_payload_root")
    if len(parts) == 1:
        _require(first in {"license", ".gitignore", ".gitattributes", "pyproject.toml", "uv.lock",
                           "execution-installation.json", "component_source_manifest.json"}
                 or first.endswith(".md"), "unsupported_payload_root_file")
    _require(Path(name).suffix.casefold() not in {".exe", ".dll", ".pyd", ".msi", ".com", ".bat", ".cmd", ".whl"},
             "source_payload_only")
    return name


def _plain(path):
    """Reject links/junctions before resolving paths, including ancestors."""
    path = Path(path).absolute()
    for current in (path, *path.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        _require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400), "reparse_path_forbidden")
    return path


def _inside(root, name, *, metadata=False):
    _safe_name(name, metadata=metadata)
    return _plain(root.joinpath(*name.split("/")))


def _facts(rows, *, metadata=False):
    _require(isinstance(rows, list) and 0 < len(rows) <= MAX_FILES, "invalid_file_manifest")
    seen = set()
    result = []
    total = 0
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {"path", "size", "sha256"}, "invalid_file_fact")
        name = _safe_name(row["path"], metadata=metadata)
        _require(name.casefold() not in seen and type(row["size"]) is int and 0 <= row["size"] <= MAX_EXPANDED
                 and isinstance(row["sha256"], str) and _HASH.fullmatch(row["sha256"]), "invalid_file_fact")
        seen.add(name.casefold())
        total += row["size"]
        result.append(dict(row))
    _require(total <= MAX_EXPANDED, "expanded_payload_too_large")
    for name in seen:
        _require(not any(parent in seen for parent in ("/".join(name.split("/")[:i]) for i in range(1, len(name.split("/"))))),
                 "payload_file_directory_conflict")
    return sorted(result, key=lambda row: row["path"].casefold())


def _asset_url(version, filename):
    return "https://github.com/" + REPOSITORY + "/releases/download/instant-v" + version + "/" + filename


def validate_target(value):
    _require(isinstance(value, dict) and set(value) == {"schema", "component", "version", "python_contract", "files", "payload", "installer"},
             "invalid_update_target_schema")
    _require(value["schema"] == "runtime_update.v1" and value["component"] == "execution", "incompatible_update_target")
    _version(value["version"])
    _require(isinstance(value["python_contract"], str) and 0 < len(value["python_contract"]) <= 128, "invalid_python_contract")
    files = _facts(value["files"])
    for key, filename, maximum in (("payload", "AgentGUIRuntimeExecution-update.zip", MAX_PAYLOAD),
                                   ("installer", "AgentGUIRuntimeExecution-Setup.exe", MAX_INSTALLER)):
        asset = value[key]
        _require(isinstance(asset, dict) and set(asset) == {"url", "size", "sha256"}, "invalid_update_asset")
        _require(asset["url"] == _asset_url(value["version"], filename) and type(asset["size"]) is int
                 and 0 < asset["size"] <= maximum and isinstance(asset["sha256"], str)
                 and _HASH.fullmatch(asset["sha256"]), "untrusted_or_invalid_update_asset")
    return {**value, "files": files, "payload": dict(value["payload"]), "installer": dict(value["installer"])}


def target_digest(target):
    return hashlib.sha256(_canonical(validate_target(target))).hexdigest()


def dependency_fingerprint(files):
    rows = _facts(files)
    dependencies = [r for r in rows if r["path"] in {"pyproject.toml", "uv.lock"} or r["path"].startswith("requirements/")]
    _require({"pyproject.toml", "uv.lock"}.issubset({r["path"] for r in dependencies})
             and any(r["path"].startswith("requirements/") for r in dependencies), "manual_install_required_missing_environment_contract")
    return hashlib.sha256(_canonical(dependencies)).hexdigest()


def _matches(path, fact):
    _plain(path)
    return path.is_file() and path.stat().st_size == fact["size"] and _digest(path) == fact["sha256"]


def _fact(path, name):
    _plain(path)
    return {"path": name, "size": path.stat().st_size, "sha256": _digest(path)}


def _sync_directory(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _atomic_replace(source, destination):
    if os.name == "nt":
        from ctypes import wintypes
        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL
        if not move(str(source), str(destination), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(source, destination)
        _sync_directory(destination.parent)


def _atomic_json(path, value):
    _plain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(_canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    _atomic_replace(temporary, path)


def _current_sid():
    if os.name != "nt":
        return "uid:" + str(os.getuid())
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    token = wintypes.HANDLE()
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    _require(advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)), "user_identity_unavailable")
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        _require(advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)), "user_identity_unavailable")
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text = wintypes.LPWSTR()
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        _require(advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)), "user_identity_unavailable")
        try:
            return text.value
        finally:
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree.restype = ctypes.c_void_p
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel.CloseHandle(token)


def installer_resources(raw):
    """Read CLI ManifestResource blobs without loading/executing a PE assembly.

    ECMA-335 metadata row sizes are calculated through table 40. Offsets, heap
    indices, resource lengths and uniqueness are bounded before any slice.
    """
    _require(isinstance(raw, bytes) and len(raw) <= MAX_INSTALLER, "invalid_installer")
    def number(offset, size=4):
        _require(type(offset) is int and 0 <= offset <= len(raw) - size, "invalid_managed_installer")
        return int.from_bytes(raw[offset:offset + size], "little")
    def part(offset, size):
        _require(0 <= offset <= len(raw) - size, "invalid_managed_installer")
        return raw[offset:offset + size]
    _require(part(0, 2) == b"MZ", "invalid_managed_installer")
    pe = number(0x3c)
    _require(part(pe, 4) == b"PE\0\0", "invalid_managed_installer")
    sections_count, optional_size = number(pe + 6, 2), number(pe + 20, 2)
    optional = pe + 24
    magic = number(optional, 2)
    _require(magic in {0x10b, 0x20b} and 0 < sections_count <= 96, "invalid_managed_installer")
    directories = optional + (96 if magic == 0x10b else 112)
    _require(directories + 15 * 8 <= optional + optional_size, "invalid_managed_installer")
    sections = []
    for i in range(sections_count):
        row = optional + optional_size + 40 * i
        sections.append((number(row + 12), number(row + 16), number(row + 20)))
    def rva(value, size=1):
        matches = [(pointer + value - start, count - (value - start)) for start, count, pointer in sections
                   if start <= value and value + size <= start + count]
        _require(len(matches) == 1, "invalid_managed_installer")
        offset, available = matches[0]
        part(offset, size)
        return offset
    cli = rva(number(directories + 14 * 8), 72)
    metadata = rva(number(cli + 8), number(cli + 12))
    resources_size = number(cli + 28)
    resources = rva(number(cli + 24), resources_size)
    _require(number(metadata) == 0x424a5342, "invalid_managed_installer")
    cursor = metadata + 16 + number(metadata + 12)
    cursor = (cursor + 3) & ~3
    streams = number(cursor + 2, 2)
    _require(0 < streams <= 32, "invalid_managed_installer")
    cursor += 4
    heaps = {}
    for _ in range(streams):
        offset, size = number(cursor), number(cursor + 4)
        name_end = raw.find(b"\0", cursor + 8, cursor + 40)
        _require(name_end >= 0, "invalid_managed_installer")
        name = part(cursor + 8, name_end - cursor - 8).decode("ascii")
        _require(name not in heaps, "invalid_managed_installer")
        part(metadata + offset, size)
        heaps[name] = (metadata + offset, size)
        cursor = (name_end + 4) & ~3
    _require("#Strings" in heaps and "#Blob" in heaps and ("#~" in heaps or "#-" in heaps), "invalid_managed_installer")
    table, table_size = heaps.get("#~", heaps.get("#-"))
    strings, strings_size = heaps["#Strings"]
    heap_flags, valid = number(table + 6, 1), number(table + 8, 8)
    count, cursor = {}, table + 24
    for index in range(64):
        if valid & (1 << index):
            count[index] = number(cursor)
            _require(count[index] <= 1000000, "invalid_managed_installer")
            cursor += 4
    string_index = 4 if heap_flags & 1 else 2
    guid_index = 4 if heap_flags & 2 else 2
    blob_index = 4 if heap_flags & 4 else 2
    def idx(t):
        return 4 if count.get(t, 0) >= 65536 else 2
    def coded(bits, *tables):
        return 4 if max((count.get(t, 0) for t in tables), default=0) >= (1 << (16 - bits)) else 2
    typedef = coded(2, 2, 1, 27)
    implementation = coded(2, 38, 35, 39)
    sizes = {
        0: 2 + string_index + 3 * guid_index,
        1: coded(2, 0, 26, 35, 1) + 2 * string_index,
        2: 4 + 2 * string_index + typedef + idx(4) + idx(6),
        3: idx(4), 4: 2 + string_index + blob_index, 5: idx(6),
        6: 8 + string_index + blob_index + idx(8), 7: idx(8), 8: 4 + string_index,
        9: idx(2) + typedef, 10: coded(3, 2, 1, 26, 6, 27) + string_index + blob_index,
        11: 2 + coded(2, 4, 8, 23) + blob_index,
        12: coded(5, 6, 4, 1, 2, 8, 9, 10, 0, 14, 23, 20, 17, 26, 27, 32, 35, 38, 39, 40, 42, 44, 43) + coded(3, 6, 10) + blob_index,
        13: coded(1, 4, 8) + blob_index, 14: 2 + coded(2, 2, 6, 32) + blob_index,
        15: 6 + idx(2), 16: 4 + idx(4), 17: blob_index, 18: idx(2) + idx(20),
        19: idx(20), 20: 2 + string_index + typedef, 21: idx(2) + idx(23),
        22: idx(23), 23: 2 + string_index + blob_index,
        24: 2 + idx(6) + coded(1, 20, 23), 25: idx(2) + 2 * coded(1, 6, 10),
        26: string_index, 27: blob_index, 28: 2 + coded(1, 4, 6) + string_index + idx(26),
        29: 4 + idx(4), 30: 8, 31: 4, 32: 16 + blob_index + 2 * string_index,
        33: 4, 34: 12, 35: 12 + 2 * blob_index + 2 * string_index,
        36: 4 + idx(35), 37: 12 + idx(35), 38: 4 + string_index + blob_index,
        39: 8 + 2 * string_index + implementation, 40: 8 + string_index + implementation,
    }
    offsets = {}
    for i in range(41):
        offsets[i] = cursor
        cursor += count.get(i, 0) * sizes[i]
    cursor = offsets[40]
    _require(cursor + count.get(40, 0) * sizes[40] <= table + table_size, "invalid_managed_installer")
    result = {}
    for _ in range(count.get(40, 0)):
        offset = number(cursor)
        name_index = number(cursor + 8, string_index)
        external = number(cursor + 8 + string_index, implementation)
        _require(name_index < strings_size and external == 0, "external_installer_resource_forbidden")
        end = raw.find(b"\0", strings + name_index, strings + strings_size)
        _require(end >= 0, "invalid_managed_installer")
        name = part(strings + name_index, end - strings - name_index).decode("utf-8")
        _require(name not in result and offset + 4 <= resources_size, "invalid_managed_installer")
        length = number(resources + offset)
        _require(offset + 4 + length <= resources_size, "invalid_managed_installer")
        result[name] = part(resources + offset + 4, length)
        cursor += sizes[40]
    _require({"payload.zip", "payload-manifest.json"}.issubset(result), "installer_payload_resources_missing")
    def string_at(index):
        _require(index < strings_size, "invalid_managed_installer")
        end = raw.find(b"\0", strings + index, strings + strings_size)
        _require(end >= 0, "invalid_managed_installer")
        return part(strings + index, end - strings - index).decode("utf-8")
    def blob_at(index):
        blob, size = heaps["#Blob"]
        _require(index < size, "invalid_managed_installer")
        lead = number(blob + index, 1)
        if lead & 0x80 == 0:
            length, prefix = lead, 1
        elif lead & 0xc0 == 0x80:
            length, prefix = ((lead & 0x3f) << 8) | number(blob + index + 1, 1), 2
        else:
            _require(lead & 0xe0 == 0xc0, "invalid_managed_installer")
            length = ((lead & 0x1f) << 24) | (number(blob + index + 1, 1) << 16) | (number(blob + index + 2, 1) << 8) | number(blob + index + 3, 1)
            prefix = 4
        _require(index + prefix + length <= size, "invalid_managed_installer")
        return part(blob + index + prefix, length)
    identity_fields = []
    for i in range(count.get(2, 0)):
        row = offsets[2] + i * sizes[2]
        if string_at(number(row + 4, string_index)) == "Identity":
            _require(not identity_fields, "duplicate_installer_identity")
            field_offset = 4 + 2 * string_index + typedef
            start = number(row + field_offset, idx(4))
            end = (number(row + sizes[2] + field_offset, idx(4)) if i + 1 < count[2] else count.get(4, 0) + 1)
            _require(1 <= start <= end <= count.get(4, 0) + 1, "invalid_managed_installer")
            identity_fields = list(range(start, end))
    constants = {}
    for i in range(count.get(11, 0)):
        row = offsets[11] + i * sizes[11]
        parent = number(row + 2, coded(2, 4, 8, 23))
        field = parent >> 2
        if parent & 3 == 0 and field in identity_fields:
            _require(number(row, 2) == 0x0e, "invalid_installer_identity_constant")
            field_row = offsets[4] + (field - 1) * sizes[4]
            name = string_at(number(field_row + 2, string_index))
            _require(name not in constants, "duplicate_installer_identity_constant")
            constants[name] = blob_at(number(row + 2 + coded(2, 4, 8, 23), blob_index)).decode("utf-16-le")
    embedded = _json(result["payload-manifest.json"])
    _require(isinstance(embedded, dict) and all(constants.get(k) == embedded.get(k) for k in
             ("component", "product_id", "entrypoint", "display_name", "version"))
             and constants.get("manifest_sha256") == hashlib.sha256(result["payload-manifest.json"]).hexdigest()
             and constants.get("payload_sha256") == hashlib.sha256(result["payload.zip"]).hexdigest(),
             "installer_identity_constants_mismatch")
    return result


def _component_manifest(raw):
    value = _json(raw)
    _require(isinstance(value, dict) and set(value) == {"format", "component", "product_id", "entrypoint", "display_name", "version", "files"},
             "invalid_component_manifest")
    _require(value["format"] == "component-payload-v1" and value["component"] == "execution"
             and value["product_id"] == PRODUCT_ID and value["entrypoint"] == "scripts/setup_instant.ps1"
             and isinstance(value["display_name"], str), "invalid_component_identity")
    _version(value["version"])
    return {**value, "files": _facts(value["files"])}


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 1

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        _require(parts.scheme == "https" and parts.hostname in {"github.com", "release-assets.githubusercontent.com"}
                 and parts.port in {None, 443} and parts.username is None and parts.password is None, "unsafe_download_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GithubTransport:
    def fetch(self, url, max_bytes):
        _require(type(max_bytes) is int and 0 < max_bytes <= MAX_INSTALLER, "invalid_download_limit")
        parsed = urllib.parse.urlsplit(url)
        _require(url == RELEASES_URL or (parsed.scheme == "https" and parsed.netloc == "github.com"
                 and parsed.path.startswith("/" + REPOSITORY + "/releases/download/")
                 and not parsed.query and not parsed.fragment), "untrusted_download_source")
        request = urllib.request.Request(url, headers={"User-Agent": "AgentGUIRuntime-Updater/1",
            "Accept": "application/vnd.github+json" if url == RELEASES_URL else "application/octet-stream"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirects())
        start = time.monotonic()
        try:
            with opener.open(request, timeout=20) as response:
                length = response.headers.get("Content-Length")
                if length is not None:
                    _require(length.isdigit() and int(length) <= max_bytes, "download_too_large")
                result = bytearray()
                while True:
                    _require(time.monotonic() - start <= 90, "download_deadline_exceeded")
                    chunk = response.read(min(65536, max_bytes - len(result) + 1))
                    if not chunk:
                        break
                    result.extend(chunk)
                    _require(len(result) <= max_bytes, "download_too_large")
                if length is not None:
                    _require(len(result) == int(length), "truncated_download")
                return bytes(result)
        except RuntimeUpdateError:
            raise
        except (OSError, urllib.error.URLError) as error:
            raise RuntimeUpdateError("update_download_failed") from error


class WindowsRegistryBackend:
    key = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + PRODUCT_ID

    def _key(self, root, access):
        _require(os.name == "nt", "normal_install_registry_unavailable")
        import winreg
        handle = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key, 0, access)
        try:
            location, _ = winreg.QueryValueEx(handle, "InstallLocation")
            _require(Path(location).resolve() == root, "registry_installation_location_mismatch")
        except BaseException:
            handle.Close()
            raise
        return handle

    def snapshot(self, root):
        import winreg
        with self._key(root, winreg.KEY_READ) as handle:
            value, kind = winreg.QueryValueEx(handle, "DisplayVersion")
        _require(isinstance(value, str), "registry_version_invalid")
        return {"version": value, "type": kind}

    def set_version(self, root, version):
        import winreg
        with self._key(root, winreg.KEY_READ | winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, "DisplayVersion", 0, winreg.REG_SZ, version)

    def restore(self, root, snapshot):
        import winreg
        with self._key(root, winreg.KEY_READ | winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, "DisplayVersion", 0, snapshot["type"], snapshot["version"])


class RuntimeUpdater:
    def __init__(self, root, *, transport=None, registry_backend=None):
        self.root = _plain(Path(root).absolute()).resolve()
        _require(self.root.is_dir() and self.root.parent != self.root, "installation_root_missing")
        self.state = _plain(self.root.parent / ("." + self.root.name + ".runtime-updates"))
        self.transport = transport if transport is not None else GithubTransport()
        self.registry = registry_backend if registry_backend is not None else WindowsRegistryBackend()

    @contextmanager
    def _operation(self):
        _plain(self.state)
        self.state.mkdir(exist_ok=True)
        path = _plain(self.state / "operation.lock")
        with path.open("a+b") as stream:
            if stream.seek(0, 2) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeUpdateError("another_update_operation_active") from error
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def _record(self, *, directory=None):
        directory = self.root if directory is None else directory
        marker = _inside(directory, ".component-install.json", metadata=True)
        value = _read_json(marker)
        required = {"format", "component", "product_id", "version", "root", "user_sid", "mode", "files"}
        _require(isinstance(value, dict) and required.issubset(value) and set(value).issubset(required | {"state"}), "invalid_installation_record")
        _require(value["format"] == "component-install-v1" and value["component"] == "execution"
                 and value["product_id"] == PRODUCT_ID and Path(value["root"]).resolve() == self.root
                 and value["user_sid"] == _current_sid() and value["mode"] in {"normal", "check"}
                 and value.get("state", "installed") == "installed", "installation_identity_mismatch")
        _version(value["version"])
        facts = _facts(value["files"], metadata=True)
        uninstaller = _inside(directory, "Uninstall.exe", metadata=True)
        owned = next((r for r in facts if r["path"] == "Uninstall.exe"), None)
        _require(owned is not None and _matches(uninstaller, owned), "installed_uninstaller_changed")
        embedded = _component_manifest(installer_resources(uninstaller.read_bytes())["payload-manifest.json"])
        expected = embedded["files"] + [owned]
        _require(embedded["version"] == value["version"] and _facts(expected, metadata=True) == facts,
                 "installation_ownership_differs_from_frozen_installer")
        return value

    def _owned_unchanged(self, record, *, directory=None):
        directory = self.root if directory is None else directory
        for row in record["files"]:
            _require(_matches(_inside(directory, row["path"], metadata=True), row), "owned_file_modified_or_missing:" + row["path"])

    def _pending_path(self):
        from app.runtime_lifecycle import update_pending_path
        return _plain(update_pending_path(self.root))

    def _no_pending(self):
        _require(not self._pending_path().exists(), "update_recovery_required")
        journal = self._journal()
        _require(journal is None or journal["phase"] in {"committed", "rolled_back"}, "update_recovery_required")

    def _highwater(self, target, *, save):
        path = self.state / "highwater.json"
        digest = target_digest(target)
        if path.exists():
            high = _read_json(path)
            _require(set(high) == {"version", "target_digest"} and _HASH.fullmatch(high["target_digest"]), "invalid_update_highwater")
            _require(_version(target["version"]) >= _version(high["version"]), "remote_version_below_seen_highwater")
            if target["version"] == high["version"]:
                _require(digest == high["target_digest"], "same_version_different_target")
        if save:
            _atomic_json(path, {"version": target["version"], "target_digest": digest})

    def check(self):
        with self._operation():
            from app.runtime_lifecycle import InstallationLease
            with InstallationLease(self.root):
                current = self._record()["version"]
            releases = _json(self.transport.fetch(RELEASES_URL, MAX_METADATA))
            _require(isinstance(releases, list) and len(releases) <= 100, "invalid_release_list")
            choices = []
            for release in releases:
                _require(isinstance(release, dict), "invalid_release_list")
                if release.get("draft") is not False or release.get("prerelease") is not False:
                    continue
                tag = release.get("tag_name", "")
                if not isinstance(tag, str) or not tag.startswith("instant-v") or _VERSION.fullmatch(tag[9:]) is None:
                    continue
                version = tag[9:]
                if _version(version) > _version(current):
                    choices.append((version, release))
            if not choices:
                return None
            version, release = max(choices, key=lambda item: _version(item[0]))
            assets = release.get("assets")
            _require(isinstance(assets, list), "release_update_asset_missing")
            matches = [x for x in assets if isinstance(x, dict) and x.get("name") == "runtime-update.json"]
            _require(len(matches) == 1, "release_update_asset_missing")
            asset = matches[0]
            url = _asset_url(version, "runtime-update.json")
            _require(asset.get("browser_download_url") == url and type(asset.get("size")) is int
                     and 0 < asset["size"] <= MAX_METADATA, "invalid_release_update_asset")
            raw = self.transport.fetch(url, asset["size"])
            _require(isinstance(raw, bytes) and len(raw) == asset["size"], "metadata_download_size_mismatch")
            if asset.get("digest") is not None:
                _require(asset["digest"] == "sha256:" + hashlib.sha256(raw).hexdigest(), "metadata_download_hash_mismatch")
            target = validate_target(_json(raw))
            _require(target["version"] == version, "release_target_version_mismatch")
            self._highwater(target, save=True)
            return target

    def _compatible(self, old, target):
        _require(sys.implementation.name == "cpython" and sys.version_info[:2] in {(3, 11), (3, 12)},
                 "manual_install_required_running_python_contract")
        _require(_version(target["version"]) > _version(old["version"]), "newer_stable_update_required")
        # Patch updates retain this release line's HTTP/Skill contract. Crossing
        # a release line needs an explicit compatibility/migration review rather
        # than implicitly upgrading an independently versioned extension.
        _require(_version(target["version"])[:2] == _version(old["version"])[:2],
                 "manual_install_required_release_contract_changed")
        _require(target["python_contract"] == PYTHON_CONTRACT, "manual_install_required_python_contract_changed")
        old_files = [r for r in old["files"] if r["path"] != "Uninstall.exe"]
        _require({"scripts/update_runtime.py", "app/runtime_update.py", "app/runtime_lifecycle.py", "app/runtime_task_ledger.py"}
                 .issubset({r["path"] for r in old_files}), "manual_install_required_updater_bootstrap")
        _require(dependency_fingerprint(old_files) == dependency_fingerprint(target["files"]), "manual_install_required_dependencies_changed")
        old_configs = [r for r in old_files if r["path"].startswith("configs/")]
        new_configs = [r for r in target["files"] if r["path"].startswith("configs/")]
        _require(_facts(old_configs) == _facts(new_configs) if old_configs and new_configs else old_configs == new_configs,
                 "manual_install_required_configuration_changed")

    def _blob(self, asset):
        raw = self.transport.fetch(asset["url"], asset["size"])
        _require(isinstance(raw, bytes) and len(raw) == asset["size"] and hashlib.sha256(raw).hexdigest() == asset["sha256"],
                 "downloaded_asset_size_or_hash_mismatch")
        return raw

    def _validate_payload(self, target, installer, archive, destination=None):
        resources = installer_resources(installer)
        _require(resources["payload.zip"] == archive, "installer_embedded_payload_mismatch")
        embedded = _component_manifest(resources["payload-manifest.json"])
        _require(embedded["version"] == target["version"] and embedded["files"] == target["files"], "installer_embedded_manifest_mismatch")
        expected = {r["path"]: r for r in target["files"]}
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            infos = zipped.infolist()
            _require(len(infos) == len(expected), "zip_file_set_mismatch")
            seen = set()
            for info in infos:
                name = _safe_name(info.filename)
                _require(name.casefold() not in seen and name in expected and not info.is_dir()
                         and not info.flag_bits & 1 and info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                         and stat.S_IFMT(info.external_attr >> 16) != stat.S_IFLNK
                         and not (info.external_attr & 0x400), "unsafe_zip_entry")
                seen.add(name.casefold())
                fact = expected[name]
                _require(info.file_size == fact["size"], "zip_file_size_mismatch")
                with zipped.open(info) as stream:
                    raw = stream.read(fact["size"] + 1)
                _require(len(raw) == fact["size"] and hashlib.sha256(raw).hexdigest() == fact["sha256"], "zip_file_hash_mismatch")
                if destination is not None:
                    path = _inside(destination, name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
        _require("execution-installation.json" in expected, "execution_descriptor_missing")

    def _stage_path(self, digest):
        _require(isinstance(digest, str) and _HASH.fullmatch(digest), "exact_target_digest_required")
        return _plain(self.state / "staged" / digest)

    def _staged(self, digest):
        path = self._stage_path(digest)
        target = validate_target(_read_json(path / "target.json"))
        _require(target_digest(target) == digest, "staged_target_changed")
        for name, key in (("payload.zip", "payload"), ("installer.exe", "installer")):
            _require(_matches(_plain(path / name), target[key]), "staged_asset_changed")
        self._validate_payload(target, (path / "installer.exe").read_bytes(), (path / "payload.zip").read_bytes())
        for row in target["files"]:
            _require(_matches(_inside(path / "files", row["path"]), row), "staged_file_changed")
        descriptor = _read_json(path / "files" / "execution-installation.json")
        _require(isinstance(descriptor, dict) and set(descriptor) == {"schema", "component", "version", "protocol", "capabilities", "runner_entry", "files"}
                 and descriptor.get("schema") == "execution_installation.v1" and descriptor.get("component") == "execution"
                 and descriptor.get("version") == target["version"] and descriptor.get("protocol") == "workflow_queue.v1"
                 and descriptor.get("runner_entry") == "scripts/run_local_step_session.py"
                 and isinstance(descriptor.get("capabilities"), list)
                 and all(isinstance(x, str) for x in descriptor["capabilities"])
                 and "learning_workflow.v1" in descriptor["capabilities"], "execution_descriptor_version_mismatch")
        rows = descriptor["files"]
        _require(isinstance(rows, list) and len(rows) <= MAX_FILES, "invalid_execution_descriptor_files")
        expected = {r["path"]: r["sha256"] for r in target["files"] if r["path"] != "execution-installation.json"}
        actual = {}
        for row in rows:
            _require(isinstance(row, dict) and set(row) == {"path", "sha256"}, "invalid_execution_descriptor_files")
            name = _safe_name(row["path"])
            _require(name not in actual and row["sha256"] == expected.get(name), "execution_descriptor_file_hash_mismatch")
            actual[name] = row["sha256"]
        _require(actual == expected, "execution_descriptor_file_set_mismatch")
        return path, target

    def stage(self, target):
        target = validate_target(target)
        digest = target_digest(target)
        with self._operation():
            self._no_pending()
            from app.runtime_lifecycle import InstallationLease
            with InstallationLease(self.root):
                old = self._record()
                self._owned_unchanged(old)
                self._compatible(old, target)
            self._highwater(target, save=True)
            destination = self._stage_path(digest)
            if not destination.exists():
                temporary = _plain(self.state / ("stage-" + uuid4().hex))
                temporary.mkdir()
                archive, installer = self._blob(target["payload"]), self._blob(target["installer"])
                self._validate_payload(target, installer, archive, temporary / "files")
                for name, raw in (("payload.zip", archive), ("installer.exe", installer)):
                    with (temporary / name).open("xb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                _atomic_json(temporary / "target.json", target)
                destination.parent.mkdir(exist_ok=True)
                _atomic_replace(temporary, destination)
            self._staged(digest)
            result = {"status": "staged", "version": target["version"], "target_digest": digest,
                      "payload_sha256": target["payload"]["sha256"], "installer_sha256": target["installer"]["sha256"], "trust": TRUST}
            _atomic_json(self.state / "stage.json", result)
            return result

    def _journal(self):
        pointer = self.state / "current.json"
        if not pointer.exists():
            return None
        value = _read_json(pointer)
        _require(isinstance(value, dict) and set(value) == {"transaction_id"}
                 and isinstance(value["transaction_id"], str) and re.fullmatch(r"[0-9a-f]{32}", value["transaction_id"]), "invalid_update_journal_pointer")
        journal = _read_json(self.state / "transactions" / value["transaction_id"] / "journal.json", 8 * MAX_METADATA)
        _require(isinstance(journal, dict) and journal.get("schema") == "runtime_update_transaction.v1"
                 and journal.get("transaction_id") == value["transaction_id"] and journal.get("root") == str(self.root)
                 and journal.get("phase") in {"preparing", "backed_up", "applying", "verifying", "committed", "rolling_back", "rolled_back", "rollback_failed"}
                 and isinstance(journal.get("target_digest"), str) and _HASH.fullmatch(journal["target_digest"]), "invalid_update_journal")
        _require(isinstance(journal.get("operations"), list) and len(journal["operations"]) <= MAX_FILES + 2, "invalid_update_journal")
        seen = set()
        for op in journal["operations"]:
            _require(isinstance(op, dict) and set(op) == {"path", "old", "new"}, "invalid_update_journal")
            _safe_name(op["path"], metadata=True)
            _require(op["path"].casefold() not in seen, "invalid_update_journal")
            seen.add(op["path"].casefold())
            for fact in (op["old"], op["new"]):
                if fact is not None:
                    _require(fact["path"] == op["path"], "invalid_update_journal")
                    _facts([fact], metadata=True)
        return journal

    def _tx(self, journal):
        return _plain(self.state / "transactions" / journal["transaction_id"])

    def _save(self, journal):
        _atomic_json(self._tx(journal) / "journal.json", journal)

    def _publish_pending(self, journal):
        path = self._pending_path()
        value = {"schema": "runtime_update_pending.v1", "root": str(self.root), "transaction_id": journal["transaction_id"],
                 "target_digest": journal["target_digest"], "state_root": str(self.state)}
        if path.exists():
            _require(_read_json(path) == value, "foreign_or_corrupt_pending_update")
        else:
            _atomic_json(path, value)

    def _clear_pending(self, journal):
        path = self._pending_path()
        if path.exists():
            self._publish_pending(journal)
            path.unlink()
            _sync_directory(path.parent)

    def _replace(self, source, target):
        _plain(source)
        _plain(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state / ("write-" + uuid4().hex)
        with source.open("rb") as incoming, temporary.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, 65536)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        _atomic_replace(temporary, target)

    def _registry_snapshot(self, old):
        if old["mode"] == "check":
            return None
        snapshot = self.registry.snapshot(self.root)
        _require(isinstance(snapshot, dict) and set(snapshot) == {"version", "type"}
                 and snapshot["version"] == old["version"] and type(snapshot["type"]) is int, "registry_version_mismatch")
        return snapshot

    def _validate_transaction(self, journal):
        """Authenticate ownership against both frozen assemblies before writing.

        Journal paths/facts alone never grant file ownership. Every complete
        backup is checked before the first restore, not after partial writes.
        """
        tx = self._tx(journal)
        directory = self.root if journal["phase"] == "preparing" else tx / "backup"
        old = self._record(directory=directory)
        self._owned_unchanged(old, directory=directory)
        _require(journal["old_record"] == old, "journal_old_record_changed")
        stage, target = self._staged(journal["target_digest"])
        _require(journal["target_version"] == target["version"], "journal_target_version_changed")
        self._compatible(old, target)
        rows = target["files"] + [_fact(stage / "installer.exe", "Uninstall.exe")]
        new_record = {**old, "version": target["version"], "files": rows, "state": "installed"}
        _require(_read_json(tx / "new-marker.json") == new_record
                 and (tx / "new-marker.json").read_bytes() == _canonical(new_record), "journal_new_record_changed")
        old_facts = {r["path"]: r for r in old["files"]}
        old_facts[".component-install.json"] = _fact(directory / ".component-install.json", ".component-install.json")
        new_facts = {r["path"]: r for r in rows}
        new_facts[".component-install.json"] = _fact(tx / "new-marker.json", ".component-install.json")
        names = sorted((set(old_facts) | set(new_facts)) - {"Uninstall.exe", ".component-install.json"}) + ["Uninstall.exe", ".component-install.json"]
        operations = [{"path": n, "old": old_facts.get(n), "new": new_facts.get(n)} for n in names]
        rollback_digest = hashlib.sha256(_canonical({"version": old["version"], "files": _facts(list(old_facts.values()), metadata=True)})).hexdigest()
        _require(journal["operations"] == operations, "journal_operations_changed")
        _require(journal["rollback_target_digest"] == rollback_digest, "journal_rollback_target_changed")
        snapshot = journal["registry_snapshot"]
        if old["mode"] == "check":
            _require(snapshot is None, "journal_registry_snapshot_changed")
        else:
            _require(isinstance(snapshot, dict) and set(snapshot) == {"version", "type"}
                     and snapshot["version"] == old["version"] and snapshot["type"] in {1, 2}, "journal_registry_snapshot_changed")

    def _rollback(self, journal):
        original_phase = journal["phase"]
        try:
            self._validate_transaction(journal)
            if original_phase == "preparing":
                self._owned_unchanged(journal["old_record"])
                marker = next(op for op in journal["operations"] if op["path"] == ".component-install.json")
                _require(_matches(_inside(self.root, marker["path"], metadata=True), marker["old"]), "rollback_original_marker_changed")
            else:
                journal["phase"] = "rolling_back"
                self._save(journal)
                for op in reversed(journal["operations"]):
                    target = _inside(self.root, op["path"], metadata=True)
                    old, new = op["old"], op["new"]
                    if old is not None and _matches(target, old):
                        continue
                    if target.exists():
                        _require(new is not None and _matches(target, new), "rollback_refuses_modified_file:" + op["path"])
                    if old is None:
                        if target.exists():
                            target.unlink()
                            _sync_directory(target.parent)
                    else:
                        backup = _inside(self._tx(journal) / "backup", op["path"], metadata=True)
                        _require(_matches(backup, old), "rollback_backup_corrupt:" + op["path"])
                        self._replace(backup, target)
                if journal["registry_snapshot"] is not None:
                    self.registry.restore(self.root, journal["registry_snapshot"])
            self._owned_unchanged(self._record())
            journal["phase"] = "rolled_back"
            self._save(journal)
            self._clear_pending(journal)
            return {"status": "rolled_back", "version": journal["old_record"]["version"], "target_digest": journal["rollback_target_digest"]}
        except Exception as error:
            journal["phase"] = "rollback_failed"
            journal["error"] = str(error)
            self._save(journal)
            raise RuntimeRollbackError("rollback_failed_backups_preserved_startup_blocked") from error

    def apply(self, confirmed_target_digest, *, health_check: Callable[[Path], bool]):
        _require(callable(health_check), "local_health_check_required")
        with self._operation():
            from app.runtime_lifecycle import InstallationMaintenance
            from app.runtime_task_ledger import assert_settled
            with InstallationMaintenance(self.root):
                assert_settled(self.root, clear_settled=True)
                self._no_pending()
                stage_info = _read_json(self.state / "stage.json")
                _require(confirmed_target_digest == stage_info.get("target_digest"), "exact_target_confirmation_required")
                stage, target = self._staged(confirmed_target_digest)
                old = self._record()
                self._owned_unchanged(old)
                self._compatible(old, target)
                self._highwater(target, save=False)
                owned = {r["path"]: r for r in old["files"]}
                new_rows = target["files"] + [_fact(stage / "installer.exe", "Uninstall.exe")]
                for row in new_rows:
                    path = _inside(self.root, row["path"], metadata=True)
                    _require(not path.is_dir() and (not path.exists() or row["path"] in owned), "refusing_unknown_file:" + row["path"])
                new_record = {**old, "version": target["version"], "files": new_rows, "state": "installed"}
                snapshot = self._registry_snapshot(old)
                transaction = uuid4().hex
                tx = _plain(self.state / "transactions" / transaction)
                tx.mkdir(parents=True)
                _atomic_json(tx / "new-marker.json", new_record)
                old_facts = {**owned, ".component-install.json": _fact(self.root / ".component-install.json", ".component-install.json")}
                new_facts = {r["path"]: r for r in new_rows}
                new_facts[".component-install.json"] = _fact(tx / "new-marker.json", ".component-install.json")
                names = sorted((set(old_facts) | set(new_facts)) - {"Uninstall.exe", ".component-install.json"}) + ["Uninstall.exe", ".component-install.json"]
                rollback_digest = hashlib.sha256(_canonical({"version": old["version"], "files": _facts(list(old_facts.values()), metadata=True)})).hexdigest()
                journal = {"schema": "runtime_update_transaction.v1", "transaction_id": transaction, "root": str(self.root),
                           "target_digest": confirmed_target_digest, "rollback_target_digest": rollback_digest,
                           "target_version": target["version"], "phase": "preparing", "old_record": old,
                           "registry_snapshot": snapshot, "operations": [{"path": n, "old": old_facts.get(n), "new": new_facts.get(n)} for n in names]}
                self._save(journal)
                _atomic_json(self.state / "current.json", {"transaction_id": transaction})
                self._publish_pending(journal)
                try:
                    for op in journal["operations"]:
                        if op["old"] is not None:
                            source = _inside(self.root, op["path"], metadata=True)
                            backup = _inside(tx / "backup", op["path"], metadata=True)
                            backup.parent.mkdir(parents=True, exist_ok=True)
                            with source.open("rb") as incoming, backup.open("xb") as outgoing:
                                shutil.copyfileobj(incoming, outgoing, 65536)
                                outgoing.flush()
                                os.fsync(outgoing.fileno())
                            _require(_matches(backup, op["old"]), "backup_integrity_failure")
                    journal["phase"] = "backed_up"
                    self._save(journal)
                    journal["phase"] = "applying"
                    self._save(journal)
                    for op in journal["operations"]:
                        if op["old"] == op["new"]:
                            continue
                        path = _inside(self.root, op["path"], metadata=True)
                        if op["new"] is None:
                            _require(_matches(path, op["old"]), "owned_file_changed_during_apply")
                            path.unlink()
                            _sync_directory(path.parent)
                        else:
                            source = (stage / "installer.exe" if op["path"] == "Uninstall.exe" else
                                      tx / "new-marker.json" if op["path"] == ".component-install.json" else
                                      _inside(stage / "files", op["path"]))
                            _require(_matches(source, op["new"]), "staged_file_changed_during_apply")
                            _require(_matches(path, op["old"]) if op["old"] is not None else not path.exists(),
                                     "owned_or_unknown_file_changed_during_apply:" + op["path"])
                            self._replace(source, path)
                    if snapshot is not None:
                        self.registry.set_version(self.root, target["version"])
                    journal["phase"] = "verifying"
                    self._save(journal)
                    _require(health_check(self.root) is True, "health_check_failed")
                    self._owned_unchanged(self._record())
                    if snapshot is not None:
                        _require(self.registry.snapshot(self.root)["version"] == target["version"], "registry_health_check_failed")
                except Exception as error:
                    self._rollback(journal)
                    raise RuntimeUpdateError("update_failed_rolled_back:" + str(error)) from error
                journal["phase"] = "committed"
                self._save(journal)
                self._clear_pending(journal)
                return {"status": "applied", "version": target["version"], "target_digest": confirmed_target_digest,
                        "rollback_target": {"version": old["version"], "target_digest": rollback_digest}, "trust": TRUST}

    def recover(self, confirmed_target_digest):
        with self._operation():
            from app.runtime_lifecycle import InstallationMaintenance
            from app.runtime_task_ledger import assert_settled
            with InstallationMaintenance(self.root):
                assert_settled(self.root, clear_settled=True)
                journal = self._journal()
                _require(journal is not None and confirmed_target_digest == journal["target_digest"], "exact_recovery_confirmation_required")
                if not self._pending_path().exists():
                    self._validate_transaction(journal)
                    if journal["phase"] == "committed":
                        self._owned_unchanged(self._record())
                        _require(self._record() == _read_json(self._tx(journal) / "new-marker.json"), "committed_installation_record_changed")
                        if journal["registry_snapshot"] is not None:
                            _require(self.registry.snapshot(self.root)["version"] == journal["target_version"], "committed_registry_version_changed")
                    else:
                        for op in journal["operations"]:
                            path = _inside(self.root, op["path"], metadata=True)
                            _require(not path.exists() or any(fact is not None and _matches(path, fact) for fact in (op["old"], op["new"])),
                                     "recovery_current_installation_changed")
                self._publish_pending(journal)
                if journal["phase"] == "committed":
                    self._validate_transaction(journal)
                    self._owned_unchanged(self._record())
                    _require(self._record() == _read_json(self._tx(journal) / "new-marker.json"), "committed_installation_record_changed")
                    if journal["registry_snapshot"] is not None:
                        _require(self.registry.snapshot(self.root)["version"] == journal["target_version"], "committed_registry_version_changed")
                    self._clear_pending(journal)
                    return {"status": "applied", "version": journal["target_version"], "target_digest": journal["target_digest"]}
                return self._rollback(journal)

    def rollback(self, confirmed_target_digest):
        with self._operation():
            from app.runtime_lifecycle import InstallationMaintenance
            from app.runtime_task_ledger import assert_settled
            with InstallationMaintenance(self.root):
                assert_settled(self.root, clear_settled=True)
                self._no_pending()
                journal = self._journal()
                _require(journal is not None and journal["phase"] == "committed"
                         and confirmed_target_digest == journal["rollback_target_digest"], "exact_rollback_confirmation_required")
                self._validate_transaction(journal)
                self._owned_unchanged(self._record())
                _require(self._record() == _read_json(self._tx(journal) / "new-marker.json"), "rollback_current_installation_changed")
                if journal["registry_snapshot"] is not None:
                    _require(self.registry.snapshot(self.root)["version"] == journal["target_version"], "rollback_current_registry_changed")
                self._publish_pending(journal)
                return self._rollback(journal)

    def status(self):
        journal = self._journal()
        stage = _read_json(self.state / "stage.json") if (self.state / "stage.json").exists() else None
        result = {"status": journal["phase"] if journal else "staged" if stage else "idle", "staged_target": stage,
                  "recovery_required": self._pending_path().exists(), "trust": TRUST,
                  "publisher_signature_verified": False}
        try:
            result["installed_version"] = self._record()["version"]
        except Exception:
            # A partly replaced marker/uninstaller must not hide the external
            # recovery command. This field is only best-effort local identity.
            result.update(installed_version=None, install_identity_unavailable=True)
        if stage:
            result.update(version=stage["version"], target_digest=stage["target_digest"])
        if journal:
            result["pending_target_digest"] = journal["target_digest"]
            recovery_root = self.root if journal["phase"] == "preparing" else self._tx(journal) / "backup"
            result["recovery_command"] = [sys.executable, "-I", "-B", str(recovery_root / "scripts/update_runtime.py"),
                                          "--root", str(self.root), "recover", "--confirm-target", journal["target_digest"]]
            if journal["phase"] == "committed":
                result["rollback_target"] = {"version": journal["old_record"]["version"], "target_digest": journal["rollback_target_digest"]}
        return result
