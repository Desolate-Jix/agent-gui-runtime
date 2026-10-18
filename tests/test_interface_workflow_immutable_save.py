"""仅在临时根验证公共审核保存器，不加载 Panel 或运行模型。"""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image

from app.desktop_review.external_mapping import (
    build_external_workflow_review, canonical_json_bytes,
    normalize_agent_link_batch, source_image_relative_path, source_ref_for_batch,
)
from app.learn.interface_workflow_review import save_interface_workflow_review_candidate


def _review(root: Path, workflow_id: str = "immutable_fixture") -> dict:
    output = BytesIO()
    Image.new("RGB", (80, 60), "white").save(output, format="PNG")
    batch = normalize_agent_link_batch({
        "contract_version": "agent_link_v1", "batch_id": "batch", "idempotency_key": "fixture-key",
        "title": "Fixture", "learning_outcome": "completed",
        "screenshots": [{"screenshot_id": "shot", "png_base64": base64.b64encode(output.getvalue()).decode("ascii")}],
        "interfaces": [{"interface_id": "screen", "screenshot_id": "shot", "meaning": "合成审核界面", "regions": [{"region_id": "item", "name": "项目", "meaning": "只读项目", "bbox": [2, 3, 20, 15]}]}],
        "relationships": [], "steps": [], "issues": [],
    })
    source_ref = source_ref_for_batch(batch)
    source_path = root / "desktop-review" / "sources" / source_ref / "original_batch.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(canonical_json_bytes(batch) + b"\n")
    image_path = root / source_image_relative_path(source_ref, batch["screenshots"][0])
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(output.getvalue())
    review = build_external_workflow_review(batch=batch, task_id="task", source_ref=source_ref, revision=1)
    review["workflow"]["workflow_id"] = workflow_id
    return review


def test_create_only_retry_is_verified_idempotent_and_legacy_cannot_overwrite(tmp_path: Path):
    review = _review(tmp_path)
    first = save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=True)
    source = Path(first["path"])
    original_bytes = source.read_bytes()
    registry = tmp_path / "artifacts/interface-workflow-reviews/registry.json"
    registry_bytes = registry.read_bytes()
    assert save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=True) == first
    assert registry.read_bytes() == registry_bytes
    edited = deepcopy(review)
    edited["nodes"][0]["agent_description"] = "不能覆盖原审核内容"
    for create_only in (True, False):
        with pytest.raises(ValueError, match="immutable"):
            save_interface_workflow_review_candidate(edited, project_root=tmp_path, create_only=create_only)
        assert source.read_bytes() == original_bytes
    assert json.loads(original_bytes)["artifact_is_authorization"] is False


def test_create_only_retry_checks_actual_derived_bytes(tmp_path: Path):
    review = _review(tmp_path)
    first = save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=True)
    source = Path(first["path"])
    payload = json.loads(source.read_text(encoding="utf-8"))
    editable = tmp_path / payload["nodes"][0]["editable_review_source_path"]
    editable.write_bytes(editable.read_bytes() + b" ")
    with pytest.raises(ValueError, match="immutable"):
        save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=True)
    assert editable.read_bytes().endswith(b" ")


def test_partial_immutable_save_is_not_repaired_or_overwritten(tmp_path: Path, monkeypatch):
    from app.learn import interface_workflow_review as module
    review = _review(tmp_path)
    def fail_index(**_kwargs):
        raise OSError("synthetic registry failure")
    monkeypatch.setattr(module, "_index_workflow_review", fail_index)
    with pytest.raises(OSError, match="synthetic"):
        save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=True)
    destination = tmp_path / "artifacts/interface-workflow-reviews/immutable_fixture"
    before = {str(p.relative_to(destination)): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
    for create_only in (True, False):
        with pytest.raises(ValueError, match="immutable"):
            save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=create_only)
        assert {str(p.relative_to(destination)): p.read_bytes() for p in destination.rglob("*") if p.is_file()} == before


def test_supported_process_writers_preserve_every_registry_record(tmp_path: Path):
    review = _review(tmp_path)
    input_path = tmp_path / "synthetic-input.json"
    input_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    code = "\n".join([
        "import json,sys",
        "from pathlib import Path",
        "from app.learn.interface_workflow_review import save_interface_workflow_review_candidate",
        "root = Path(sys.argv[1])",
        "review = json.loads((root/'synthetic-input.json').read_text(encoding='utf-8'))",
        "for index in range(4):",
        "    review['workflow']['workflow_id'] = 'process_' + sys.argv[2] + '_' + str(index)",
        "    result = save_interface_workflow_review_candidate(review, project_root=root)",
        "    assert Path(result['path']).is_file()",
        "print('writer finished')",
    ])
    children = [subprocess.Popen([sys.executable, "-c", code, str(tmp_path), str(index)], cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") for index in range(4)]
    try:
        for child in children:
            stdout, stderr = child.communicate(timeout=30)
            assert child.returncode == 0, stderr
            assert "writer finished" in stdout
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
    registry = json.loads((tmp_path / "artifacts/interface-workflow-reviews/registry.json").read_text(encoding="utf-8"))
    assert len(registry["workflows"]) == 16
    assert registry["registry_revision"] == 16
    for record in registry["workflows"].values():
        assert hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest() == record["source_asset_sha256"]


@pytest.mark.skipif(os.name != "nt", reason="Windows mandatory byte-range locking regression")
def test_writer_waits_for_locked_empty_file_without_unlocked_initialization(tmp_path: Path):
    import msvcrt

    lock_path = tmp_path / ".review-write.lock"
    code = "\n".join([
        "import sys", "from pathlib import Path",
        "from app.learn.review_write_guard import review_writer_lock",
        "print('contender ready', flush=True)",
        "with review_writer_lock(Path(sys.argv[1])):",
        "    print('acquired', flush=True)",
    ])
    # Windows 可锁定 EOF 之外的字节；竞争者不得在取得锁前写入该区域。
    with lock_path.open("a+b") as owner:
        msvcrt.locking(owner.fileno(), msvcrt.LK_NBLCK, 1)
        child = subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path)],
            cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        try:
            assert child.stdout.readline().strip() == "contender ready"
            try:
                early_stdout, early_stderr = child.communicate(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
            else:
                pytest.fail(f"writer exited while another process held its lock: {child.returncode}; {early_stdout}; {early_stderr}")
        finally:
            owner.seek(0)
            msvcrt.locking(owner.fileno(), msvcrt.LK_UNLCK, 1)
            try:
                stdout, stderr = child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)
                raise
        assert child.returncode == 0, stderr
        assert "acquired" in stdout


def test_dependency_drift_before_seal_never_publishes_registry(tmp_path: Path, monkeypatch):
    from app.learn import review_write_guard as guard
    review = _review(tmp_path)
    actual = guard._input_dependencies
    calls = 0
    def drift(*args):
        nonlocal calls
        calls += 1
        result = actual(*args)
        if calls > 1:
            result["synthetic-drift"] = "changed"
        return result
    monkeypatch.setattr(guard, "_input_dependencies", drift)
    with pytest.raises(ValueError, match="dependency changed"):
        save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=True)
    assert not (tmp_path / "artifacts/interface-workflow-reviews/registry.json").exists()


def test_immutable_retry_rejects_registry_lineage_drift_without_repair(tmp_path: Path):
    review = _review(tmp_path)
    save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=True)
    registry = tmp_path / "artifacts/interface-workflow-reviews/registry.json"
    value = json.loads(registry.read_text(encoding="utf-8"))
    value["workflows"].clear()
    registry.write_text(json.dumps(value), encoding="utf-8")
    tampered = registry.read_bytes()
    with pytest.raises(ValueError, match="immutable"):
        save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=True)
    assert registry.read_bytes() == tampered


@pytest.mark.parametrize("node_ids", [("node/a", "node_a"), ("Node", "node"), ("CON", "other")])
def test_create_only_rejects_unsafe_or_colliding_node_paths(tmp_path: Path, node_ids):
    review = _review(tmp_path)
    review["nodes"] *= 2
    review["nodes"] = [deepcopy(node) for node in review["nodes"]]
    for node, node_id in zip(review["nodes"], node_ids):
        node["node_id"] = node_id
    review["workflow"].update(node_ids=list(node_ids), entry_node_id=node_ids[0])
    with pytest.raises(ValueError, match="immutable"):
        save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=True)
    assert not (tmp_path / "artifacts/interface-workflow-reviews/registry.json").exists()


def test_process_exit_before_seal_leaves_no_current_registry(tmp_path: Path):
    review = _review(tmp_path, "interrupted_fixture")
    (tmp_path / "synthetic-input.json").write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    code = "\n".join([
        "import json, os, sys", "from pathlib import Path",
        "from app.learn.interface_workflow_review import save_interface_workflow_review_candidate",
        "original = Path.write_bytes",
        "def interrupted(path, content):",
        "    if path.name == '.immutable-seal.json': os._exit(23)",
        "    return original(path, content)",
        "Path.write_bytes = interrupted", "root = Path(sys.argv[1])",
        "save_interface_workflow_review_candidate(json.loads((root/'synthetic-input.json').read_text(encoding='utf-8')), project_root=root, create_only=True)",
    ])
    child = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert child.returncode == 23, child.stderr
    assert not (tmp_path / "artifacts/interface-workflow-reviews/registry.json").exists()
    with pytest.raises(ValueError, match="immutable"):
        save_interface_workflow_review_candidate(review, project_root=tmp_path, create_only=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-path namespace regression")
def test_output_containment_handles_resolved_windows_namespace_without_allowing_escape(tmp_path: Path, monkeypatch):
    from app.learn.interface_workflow_review import _resolve_review_output_dir
    inside = tmp_path / "new-output"
    outside = tmp_path.parent / "outside-output"
    original = Path.resolve
    def namespace_result(path, *args, **kwargs):
        resolved = original(path, *args, **kwargs)
        return Path("\\\\?\\" + str(resolved)) if path in (inside, outside) else resolved
    monkeypatch.setattr(Path, "resolve", namespace_result)
    assert _resolve_review_output_dir(tmp_path, inside) == inside
    with pytest.raises(ValueError, match="inside project root"):
        _resolve_review_output_dir(tmp_path, outside)
