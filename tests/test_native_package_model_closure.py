"""运行打包配方，核对传给冻结器的懒加载模块及二进制资源。"""
import json
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace


def test_recipe_supplies_vista_lazy_imports_and_native_dependency_assets(tmp_path, monkeypatch):
    manifest = tmp_path / "runtime-manifest.json"
    manifest.write_text(json.dumps({"packages": []}), encoding="utf-8")
    monkeypatch.setenv("AGENT_REVIEW_RUNTIME_MANIFEST", str(manifest))
    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda package, **kwargs: [("data/" + package, package)]
    hooks.collect_dynamic_libs = lambda package: [("dll/" + package, package)]
    hooks.copy_metadata = lambda package: []
    monkeypatch.setitem(sys.modules, "PyInstaller", ModuleType("PyInstaller"))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils", ModuleType("PyInstaller.utils"))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    captured = {}

    def analyze(entries, **kwargs):
        captured.update(entries=entries, **kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=kwargs["binaries"], datas=kwargs["datas"])

    root = Path(__file__).resolve().parents[1]
    runpy.run_path(str(root / "packaging/agent_review.spec"), init_globals={
        "SPECPATH": str(root / "packaging"), "Analysis": analyze,
        "PYZ": lambda *args, **kwargs: None, "EXE": lambda *args, **kwargs: None,
        "COLLECT": lambda *args, **kwargs: None,
    })
    assert {
        "transformers.models.qwen3_5.modeling_qwen3_5",
        "transformers.models.qwen3_5.configuration_qwen3_5",
        "transformers.models.qwen3_vl.processing_qwen3_vl",
        "transformers.models.qwen3_vl.video_processing_qwen3_vl",
        "transformers.models.qwen2_vl.image_processing_qwen2_vl_fast",
    }.issubset(captured["hiddenimports"])
    for package in ("tokenizers", "safetensors", "huggingface_hub", "numpy"):
        assert ("data/" + package, package) in captured["datas"]
        assert ("dll/" + package, package) in captured["binaries"]
    assert "tests" in captured["excludes"]
    assert {"app.api.application", "app.desktop_review.application", "app.vision.model_workers.vista_openai_server",
            "app.application_profiles.seek.scroll_containers", "app.api.reviewed_workflows",
            "app.learn.interface_workflow_lock", "app.learn.interface_workflow_service",
            "app.learn.learning_draft_review_service"}.issubset(captured["hiddenimports"])
    retired = ("app.main", "app.api.panel", "app.web_panel", "app.seek",
               "scripts.start_desktop_review", "scripts.model_servers.vista_openai_server")
    for module in retired:
        assert module in captured["excludes"]
        assert not any(name == module or name.startswith(module + ".") for name in captured["hiddenimports"])
