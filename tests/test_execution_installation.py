"""执行安装描述核实文件一致性，不把自声明摘要当发布者信任。"""
import hashlib
import json

import pytest

from app.learning_memory import execution_installation as installation


def _installation(tmp_path):
    root = tmp_path / "execution"
    entry = root / "scripts/run_local_step_session.py"
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b"print('fixture')\n")
    descriptor = {"schema": "execution_installation.v1", "component": "execution",
        "version": "0.1.0-test.8", "protocol": "workflow_queue.v1",
        "capabilities": ["learning_workflow.v1"],
        "runner_entry": "scripts/run_local_step_session.py",
        "files": [{"path": "scripts/run_local_step_session.py",
                   "sha256": hashlib.sha256(entry.read_bytes()).hexdigest()}]}
    _write(root, descriptor)
    return root, descriptor


def _write(root, descriptor):
    (root / "execution-installation.json").write_text(
        json.dumps(descriptor, ensure_ascii=False), encoding="utf-8")


def test_explicit_execution_root_verifies_exact_entry_and_files(tmp_path):
    root, _ = _installation(tmp_path)
    verified = installation.load_execution_installation(root)
    assert verified.mode == "installed"
    assert verified.root == root.resolve()
    assert verified.runner_entry == (root / "scripts/run_local_step_session.py").resolve()
    assert verified.version == "0.1.0-test.8"
    assert verified.publisher_verified is False


@pytest.mark.parametrize("change", ["protocol", "component", "capabilities", "entry", "escape", "missing", "digest", "version", "duplicate"])
def test_incompatible_or_corrupt_installation_rejected(tmp_path, change):
    root, descriptor = _installation(tmp_path)
    if change in {"protocol", "component"}:
        descriptor[change] = "unrelated"
    elif change == "capabilities":
        descriptor[change] = []
    elif change == "entry":
        descriptor["runner_entry"] = "other.py"
    elif change == "escape":
        descriptor["files"][0]["path"] = "../outside.py"
    elif change == "missing":
        descriptor["files"].append({"path": "missing.py", "sha256": "0" * 64})
    elif change == "digest":
        (root / descriptor["runner_entry"]).write_bytes(b"changed")
    elif change == "version":
        descriptor["version"] = ""
    else:
        descriptor["files"] *= 2
    _write(root, descriptor)
    with pytest.raises(ValueError, match="execution_installation_"):
        installation.load_execution_installation(root)


def test_missing_descriptor_is_only_allowed_for_implicit_source_root(tmp_path):
    root = tmp_path / "source"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts/run_local_step_session.py").write_bytes(b"source")
    with pytest.raises(ValueError, match="execution_installation_descriptor_missing"):
        installation.load_execution_installation(root)
    assert installation.load_execution_installation(root, source_root=root).mode == "source_dev"
    with pytest.raises(ValueError):
        installation.load_execution_installation(root, source_root=tmp_path / "other")


def test_descriptor_builder_roundtrip_and_mutation_detection(tmp_path):
    root, _ = _installation(tmp_path)
    descriptor = installation.build_execution_installation_descriptor(
        root, version="0.1.0-test.8", files=["scripts/run_local_step_session.py"])
    _write(root, descriptor)
    verified = installation.load_execution_installation(root)
    verified.revalidate()
    (root / "scripts/run_local_step_session.py").write_bytes(b"upgrade")
    with pytest.raises(ValueError, match="execution_installation_"):
        verified.revalidate()
