"""交付白名单与清单边界，不启动输入宿主。"""
import hashlib
import json
from pathlib import Path
import re
import zipfile

import pytest

from scripts import build_instant_bundle as bundle


def seed(root):
    for name in bundle.ROOT_FILES + bundle.SCRIPTS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    for name in ("app/application_profiles/seek/scroll_containers.py", "app/seek/old.py",
                 "app/web_panel/old.py", "app/main.py", "app/api/panel.py",
                 "app/desktop_review/input_sequence.py", "app/__pycache__/x.pyc",
                 "tests/test_current.py", "docs/verification/current.md",
                 "models/weights.bin", "logs/private.json", "mcp-config.local.json",
                 "scripts/model_servers/runtime.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")


def test_source_selection_retains_dependencies_not_old_ui_or_private_data(tmp_path):
    root = tmp_path / "seek" / "source"
    seed(root)
    found = {p.relative_to(root).as_posix() for p in bundle.collect_sources(root)}
    assert "app/application_profiles/seek/scroll_containers.py" in found
    assert "app/desktop_review/input_sequence.py" in found
    assert "docs/verification/current.md" in found
    assert "tests/test_current.py" in found
    assert not any(x in found for x in ("app/seek/old.py", "app/web_panel/old.py",
        "app/main.py", "app/api/panel.py", "logs/private.json", "models/weights.bin", "mcp-config.local.json"))


def test_missing_required_source_fails_before_output(tmp_path):
    with pytest.raises(FileNotFoundError):
        bundle.build(tmp_path / "missing", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_source_selection_preserves_current_readme_guide_links(tmp_path):
    seed(tmp_path)
    references = ["docs/EXECUTION_MODULE_BOUNDARIES.md",
                  "docs/WORKFLOW_DEFINITION_AND_RUN_EVIDENCE.md"]
    (tmp_path / "README.md").write_text("\n".join(f"[guide]({name})" for name in references),
                                      encoding="utf-8")
    for name in references:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("guide", encoding="utf-8")
    found = {p.relative_to(tmp_path).as_posix() for p in bundle.collect_sources(tmp_path)}
    linked = re.findall(r"\]\((docs/[^)]+)\)", (tmp_path / "README.md").read_text(encoding="utf-8"))
    assert set(linked) <= found


def test_fresh_source_current_trial_links_do_not_require_local_status(tmp_path):
    source = Path(__file__).resolve().parents[1]
    guides = ("README.md", "docs/WORKFLOW_EDITOR.md", "AGENT_GUIDE.md")
    current_targets = {"docs/verification/LEARNING_TRIAL_READINESS.md",
        "docs/superpowers/plans/2026-10-03-learning-trial-closeout.md",
        "docs/superpowers/plans/2026-10-01-learning-mainline-refocus.md",
        "docs/WORKFLOW_INTERRUPTION_CONTRACT.md", "CURRENT_STATE.md", "NEXT_STEPS.md"}
    seed(tmp_path)
    for name in ("CURRENT_STATE.md", "NEXT_STEPS.md"):
        path = tmp_path / name
        if path.exists():
            path.unlink()
    linked = set()
    for name in guides:
        text = (source / name).read_text(encoding="utf-8")
        (tmp_path / name).write_text(text, encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if re.match(r"^[A-Za-z]+:|^#", target):
                continue
            path = (tmp_path / name).parent / target.split("#", 1)[0]
            if path.resolve().is_relative_to(tmp_path.resolve()):
                relative = path.resolve().relative_to(tmp_path.resolve()).as_posix()
                if relative in current_targets:
                    linked.add(relative)
                    if relative not in {"CURRENT_STATE.md", "NEXT_STEPS.md"}:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text((source / relative).read_text(encoding="utf-8"), encoding="utf-8")
    found = {path.relative_to(tmp_path).as_posix() for path in bundle.collect_sources(tmp_path)}
    assert linked == current_targets - {"CURRENT_STATE.md", "NEXT_STEPS.md"}
    assert linked <= found
    assert not {"CURRENT_STATE.md", "NEXT_STEPS.md"} & found


def test_delivery_includes_referenced_development_docs_not_private_evidence(tmp_path):
    seed(tmp_path)
    for name in ('docs/development/EXTERNAL_VISION_API.md', 'docs/development/AGENT_VISION_IMPLEMENTATION.md',
                 'docs/development/private-capture.png', 'docs/development/private-config.json'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    found = {p.relative_to(tmp_path).as_posix() for p in bundle.collect_sources(tmp_path)}
    assert 'docs/development/EXTERNAL_VISION_API.md' in found
    assert 'docs/development/AGENT_VISION_IMPLEMENTATION.md' in found
    assert 'docs/development/private-capture.png' not in found
    assert 'docs/development/private-config.json' not in found


@pytest.mark.parametrize("entrypoint", (
    "app/desktop_review/entrypoint.py", "app/desktop_review/application.py",
    "app/agent_link/mcp_bridge.py",
))
def test_execution_bundle_excludes_learning_entrypoints_not_shared_runtime(tmp_path, entrypoint):
    seed(tmp_path)
    shared = ("app/desktop_review/host.py", "app/desktop_review/workspace.py",
              "app/agent_link/host.py", "app/agent_link/http_app.py", "app/agent_link/service.py",
              "app/learn/hybrid/windows_process_scope.py")
    for name in (entrypoint, *shared):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    found = {p.relative_to(tmp_path).as_posix() for p in bundle.collect_sources(tmp_path)}
    assert entrypoint not in found
    assert set(shared) <= found


def test_build_and_archive_only_ship_manifest_not_generated_junk(tmp_path, monkeypatch):
    source, out = tmp_path / "source", tmp_path / "delivery"
    seed(source)
    monkeypatch.setattr(bundle, "verify_entrypoints", lambda root: (root / "entrypoint-verification.json").write_text('{"passed":true}', encoding="utf-8"))
    bundle.build(source, out)
    (out / "private-session.json").write_text("secret", encoding="utf-8")
    result = bundle.archive(out)
    with zipfile.ZipFile(result["zip"]) as archive:
        assert archive.testzip() is None
        assert not any("private-session" in name for name in archive.namelist())
        assert "delivery/docs/verification/current.md" in archive.namelist()
    assert result["sha256"] == hashlib.sha256(Path(result["zip"]).read_bytes()).hexdigest()


def test_archive_rejects_mutated_payload(tmp_path, monkeypatch):
    source, out = tmp_path / "source", tmp_path / "delivery"
    seed(source)
    monkeypatch.setattr(bundle, "verify_entrypoints", lambda root: (root / "entrypoint-verification.json").write_text('{"passed":true}', encoding="utf-8"))
    bundle.build(source, out)
    (out / "README.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        bundle.archive(out)


def test_build_never_overwrites_existing_delivery(tmp_path):
    with pytest.raises(FileExistsError):
        bundle.build(tmp_path, tmp_path)
