"""交付包必须保留当前输入路由的真实依赖，而不是只通过 MCP 发现。"""
import json
from pathlib import Path
import zipfile
import subprocess
import sys
import shutil
import pytest

from scripts.build_instant_bundle import build, archive, retained_app_source


def test_isolated_bundle_retains_input_profiles_and_excludes_retired_code(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "preview.2"
    build(root, output)
    assert (output / "FIXES.md").read_bytes() == (root / "docs/INSTANT_RELEASE_NOTES.md").read_bytes()
    for name in ("conftest.py", "test_local_editing_keys.py", "test_instant_mcp.py",
                 "test_input_controller.py", "test_text_input_guard.py",
                 "test_clipboard_transaction.py", "test_clipboard_bitmap_recovery.py",
                 "test_instant_read_text.py", "test_instant_read_text_entrypoint.py",
                 "test_recognition_click_kind.py", "test_mouse_click_sequence.py",
                 "test_launched_window_close.py", "test_ocr_word_boxes.py", "test_local_recognition_policy.py",
                 "test_execution_menu_scope.py", "test_uia_provider_pinned_snapshot.py", "test_fresh_action_risk.py"):
        assert (output / "tests" / name).is_file(), name
    for name in ("test_window_close_observation.py", "test_post_action_window_transition.py",
                 "test_keyboard_focus_diagnostics.py", "test_post_action_recovery.py",
                 "test_local_step_observation.py", "test_local_step_timings.py",
                 "test_native_menu_ownership.py", "test_capture_window_ownership.py",
                 "test_explicit_word_ocr_evidence.py", "test_execution_refine_context.py",
                 "test_execution_selected_identity.py", "test_execution_browser_chrome_scope.py",
                 "test_execution_control_text_anchor.py", "test_current_control_ocr_binding.py",
                 "test_execution_browser_document_observation.py"):
        assert (output / "tests" / name).is_file(), name
    for name in ("scroll_containers.py", "execute_observation.py", "form_inventory.py"):
        path = output / "app/application_profiles/seek" / name
        assert path.is_file(), f"missing maintained dependency: {path}"
    assert not (output / "app/seek").exists()
    assert not (output / "app/web_panel").exists()
    assert not (output / "app/api/panel.py").exists()
    # 运行产生的文件不能在归档时混入源码包。
    (output / "runtime_state").mkdir(exist_ok=True)
    (output / "runtime_state/private.txt").write_text("private", encoding="utf-8")
    from tests.test_native_model_setup import _weights
    model = _weights(tmp_path / "weights")
    (model / "model.safetensors.index.json").unlink()
    (model / "model-00001-of-00001.safetensors").rename(model / "model.safetensors")
    configured = subprocess.run([sys.executable, "-I", str(output / "scripts/configure_instant_mcp.py"),
        "--model-directory", str(model), "--data-dir", str(tmp_path / "data")],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert configured.returncode == 0, configured.stderr
    config = json.loads((output / "mcp-config.local.json").read_text(encoding="utf-8"))
    assert "--allow-local-input" not in config["mcpServers"]["agent-review-instant"]["args"]
    ps = shutil.which("pwsh") or shutil.which("powershell")
    assert ps, "Windows PowerShell is required for this delivery"
    configured = subprocess.run([ps, "-NoProfile", "-File", str(output / "scripts/configure_instant.ps1"),
        "-Python", sys.executable, "-ModelDirectory", str(model), "-DataDirectory", str(tmp_path / "data")],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert configured.returncode == 0, configured.stderr
    new_config = json.loads((output / "mcp-config.local.json").read_text(encoding="utf-8"))
    args = new_config["mcpServers"]["agent-review-instant"]["args"]
    assert args[0].endswith("start_instant_mcp_admin.py") and "--allow-local-input" in args
    assert Path(args[0]).is_file()
    (output / "verification.json").write_text('{"private": true}', encoding="utf-8")
    result = archive(output)
    assert Path(result["zip"]).name == "preview.2.zip"
    with zipfile.ZipFile(result["zip"]) as z:
        assert not any("runtime_state/private.txt" in name for name in z.namelist())
        assert not any("mcp-config.local" in name or name.endswith("/verification.json") for name in z.namelist())
        assert "preview.2/FRIEND_SETUP.md" in z.namelist()
        assert "preview.2/EXECUTION_READ_TEXT.md" in z.namelist()
        assert "preview.2/app/application_profiles/seek/scroll_containers.py" in z.namelist()
    manifest = json.loads((output / "MANIFEST.json").read_text(encoding="utf-8"))
    assert any(x["path"] == "app/application_profiles/seek/scroll_containers.py" for x in manifest["files"])
    check = json.loads((output / "entrypoint-verification.json").read_text(encoding="utf-8"))
    assert check["passed"] and check["input_executed"] is False
    assert {x["operation"] for x in check["operations"]} == {"execute_recognition_plan", "type_text", "press_key", "scroll"}
    assert {x["operation"] for x in check["observation_operations"]} == {"read_text"}
    assert set(check["editing_keys_validated"]) >= {"Shift+Left", "Shift+Right", "Shift+Up", "Shift+Down",
                                                 "Shift+Home", "Shift+End", "Ctrl+Home", "Ctrl+End"}
    # 新读取入口缺失也必须阻止交付，不允许从工作树借用模块。
    reader = output / "app/operation/screen_reading/captured_text.py"
    reader_bytes = reader.read_bytes()
    reader.unlink()
    with pytest.raises(RuntimeError, match="entrypoint validation failed"):
        archive(output)
    failure = json.loads((output / "entrypoint-verification.json").read_text(encoding="utf-8"))
    assert "captured_text" in failure["error"]
    reader.write_bytes(reader_bytes)
    # 只破坏当前测试创建的单文件，确保归档拒绝缺依赖，不能靠原工作树兜底。
    (output / "app/application_profiles/seek/scroll_containers.py").unlink()
    with pytest.raises(RuntimeError, match="entrypoint validation failed"):
        archive(output)


@pytest.mark.parametrize("relative,expected", [
    ("app/application_profiles/seek/scroll_containers.py", True),
    ("app/application_profiles/seek/form_inventory.py", True),
    ("app/seek/old.py", False),
    ("app/web_panel/old.py", False),
    ("app/api/panel.py", False),
    ("app/agent/seek_support.py", True),
])
def test_retired_paths_are_exact_not_name_filters(relative, expected):
    assert retained_app_source(Path(relative)) is expected
