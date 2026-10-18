"""用户明确选择的执行安装：只核实协议与文件一致性，不证明发布者身份。"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


DESCRIPTOR_NAME = "execution-installation.json"
RUNNER_ENTRY = "scripts/run_local_step_session.py"
_FIELDS = {"schema", "component", "version", "protocol", "capabilities", "runner_entry", "files"}


def _require(value, code):
    if not value:
        raise ValueError("execution_installation_" + code)


def _file(root, relative):
    _require(isinstance(relative, str) and bool(relative) and "\\" not in relative
             and ":" not in relative, "file_path_invalid")
    path = PurePosixPath(relative)
    _require(not path.is_absolute() and all(part not in {".", ".."} for part in path.parts)
             and str(path) == relative, "file_path_invalid")
    target = (root / relative).resolve()
    _require(target.is_relative_to(root) and target.is_file(), "file_missing_or_outside_root")
    return target


def build_execution_installation_descriptor(root, *, version, files):
    """打包器仅对已经收集到的确切文件生成清单，不自动补依赖。"""
    root = Path(root).resolve()
    _require(isinstance(version, str) and bool(version.strip()), "version_invalid")
    paths = list(files)
    _require(bool(paths) and len(paths) == len(set(paths)) and RUNNER_ENTRY in paths, "files_invalid")
    rows = [{"path": path, "sha256": hashlib.sha256(_file(root, path).read_bytes()).hexdigest()}
            for path in sorted(paths)]
    return {"schema": "execution_installation.v1", "component": "execution", "version": version,
        "protocol": "workflow_queue.v1", "capabilities": ["learning_workflow.v1"],
        "runner_entry": RUNNER_ENTRY, "files": rows}


@dataclass(frozen=True)
class ExecutionInstallation:
    root: Path
    mode: str
    runner_entry: Path
    version: str
    manifest_sha256: str | None
    publisher_verified: bool = False

    def revalidate(self):
        current = load_execution_installation(self.root,
            source_root=self.root if self.mode == "source_dev" else None)
        _require(current == self, "changed")
        return current


def load_execution_installation(root, *, source_root=None):
    root = Path(root).resolve()
    _require(root.is_dir(), "root_missing")
    descriptor = root / DESCRIPTOR_NAME
    if not descriptor.is_file():
        _require(source_root is not None and root == Path(source_root).resolve(), "descriptor_missing")
        return ExecutionInstallation(root, "source_dev", _file(root, RUNNER_ENTRY), "source/dev", None)
    try:
        raw = descriptor.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("execution_installation_descriptor_invalid") from error
    _require(descriptor.resolve().is_relative_to(root), "descriptor_outside_root")
    _require(isinstance(value, dict) and set(value) == _FIELDS, "descriptor_invalid")
    _require(value["schema"] == "execution_installation.v1" and value["component"] == "execution"
             and value["protocol"] == "workflow_queue.v1", "incompatible")
    _require(isinstance(value["version"], str) and bool(value["version"].strip()), "version_invalid")
    capabilities = value["capabilities"]
    _require(isinstance(capabilities, list) and all(isinstance(item, str) for item in capabilities)
             and "learning_workflow.v1" in capabilities, "capability_missing")
    _require(value["runner_entry"] == RUNNER_ENTRY, "runner_entry_invalid")
    rows = value["files"]
    _require(isinstance(rows, list) and bool(rows), "files_invalid")
    paths = set()
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {"path", "sha256"}, "files_invalid")
        target = _file(root, row["path"])
        _require(row["path"] not in paths, "files_duplicate")
        paths.add(row["path"])
        _require(isinstance(row["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                 and hashlib.sha256(target.read_bytes()).hexdigest() == row["sha256"], "file_hash_mismatch")
    _require(RUNNER_ENTRY in paths, "runner_entry_unlisted")
    return ExecutionInstallation(root, "installed", _file(root, RUNNER_ENTRY), value["version"],
                                 hashlib.sha256(raw).hexdigest())
