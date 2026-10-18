"""配置快照经过实际运行时构造和识别 API；仅模型与 OCR 系统边界使用替身。"""
import json
from pathlib import Path

from PIL import Image
import pytest

from app.agent.live_controller import ServerWorkflowBinding
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.desktop_review.single_step_coordinator import _production_runtime_factory
from app.vision.configuration import load_formal_vision_configuration
from app.vision.factory import VisionProviderFactory
from app.vision.local_provider import LocalVisionProvider
from app.vision.schemas import ImageSize, VisionAnalyzeResponse
from modules.ocr.contracts import OCRResult
from tests.test_native_vision_configuration import _config


@pytest.fixture
def runtime_owner(tmp_path):
    from app.desktop_review.single_step_runtime_owner import SerialRuntimeOwner
    owner = SerialRuntimeOwner(initializer=lambda: None, finalizer=lambda: None,
                               output_root=tmp_path / "owned-runtime-output")
    try:
        yield owner
    finally:
        owner.close()


@pytest.mark.parametrize("vista", [False, True])
def test_owned_snapshot_reaches_actual_recognition_factory_without_cwd_or_disk_reread(tmp_path, monkeypatch, vista, runtime_owner):
    from app.api import vision
    from app.vision import configuration

    source = _config(tmp_path / "selected/vision.json", "owned-model")
    if vista:
        config = json.loads(source.read_text(encoding="utf-8"))
        config["vision"]["local"].update(runtime="transformers", output_contract="vista_point_v1", model_path="weights/owned")
        source.write_text(json.dumps(config), encoding="utf-8")
    snapshot = load_formal_vision_configuration(source)
    _config(source, "later-disk-model")
    empty = tmp_path / "unrelated"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.setattr(configuration, "_source_project_root", lambda: empty)
    capture = tmp_path / "capture.png"
    Image.new("RGB", (20, 10), (3, 5, 7)).save(capture)
    seen = []
    providers = []

    def record(provider):
        providers.append(provider)
        seen.append((provider.model_name, provider.endpoint))
        active = VisionProviderFactory.load_config()["vision"]["local"]
        assert active["model_name"] == provider.model_name
        if vista:
            assert Path(active["model_path"]).is_absolute()
            assert active["model_path"] == str(source.parent / ("weights/second" if provider.model_name == "second-owned-model" else "weights/owned"))

    def analyze(provider, request):
        assert not vista, "VISTA must use the actual point endpoint path"
        record(provider)
        return VisionAnalyzeResponse(provider="local", screen_summary="synthetic", state_guess=None,
            image_size=ImageSize(20, 10))

    def point_endpoint(provider, image_path, prompt, **kwargs):
        assert vista
        assert Path(image_path) == capture or Path(image_path).is_relative_to(tmp_path / "owned-runtime-output")
        record(provider)
        return {"choices": [{"message": {"content": "[500, 500]"}}]}

    monkeypatch.setattr(LocalVisionProvider, "analyze", analyze)
    monkeypatch.setattr(LocalVisionProvider, "_call_openai_compatible_endpoint", point_endpoint)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=path, matches=[]))
    monkeypatch.setattr(vision, "VISTA_DIRECT_IMAGES_DIR", tmp_path / "processed-captures")
    selection = RuntimeSessionSelection("asset-config", "a" * 64, 4242, 9001)
    callsite = _production_runtime_factory(project_root=tmp_path / "reviews", selection=selection,
        window_manager=object(), vision_configuration=snapshot)
    controller = callsite._controller_factory(ServerWorkflowBinding(
        workflow_id="config-workflow", asset_id="asset-config",
        application_identity_key="native:editor.exe:notepad", target_window_handle=4242))
    runner = controller._observation_source._recognition_runner
    for _ in range(2):
        # 正式桌面调用由串行拥有者绑定输出目录，不能在测试中绕开该调用边界。
        result = runtime_owner.call(lambda: runner(image_path=str(capture), goal="synthetic target", provider_mode="local",
            uia_snapshot={"status": "ok", "window": {"handle": 4242, "process_id": 9001}, "controls": []}))
        assert result["image_path"] == str(capture)
        assert result["execution_path"]["action_executed"] is False
        assert not result["trace_path"]
        assert "vision_configuration" not in json.dumps(result)
    # 当前默认仅完整图定位一次；显式细化由独立图像策略测试覆盖。
    per_request = 1
    assert seen == [("owned-model", "http://127.0.0.1:9/inference")] * (2 * per_request)
    second_config = snapshot.to_dict()
    second_config["vision"]["local"].update(model_name="second-owned-model", endpoint="http://127.0.0.1:10/inference")
    if vista:
        second_config["vision"]["local"]["model_path"] = "weights/second"
    second_path = source.parent / "second.json"
    second_path.write_text(json.dumps(second_config), encoding="utf-8")
    second_snapshot = load_formal_vision_configuration(second_path)
    second = _production_runtime_factory(project_root=tmp_path / "second-reviews", selection=selection,
        window_manager=object(), vision_configuration=second_snapshot)
    second_controller = second._controller_factory(ServerWorkflowBinding(
        workflow_id="config-workflow", asset_id="asset-config",
        application_identity_key="native:editor.exe:notepad", target_window_handle=4242))
    for active_runner in (second_controller._observation_source._recognition_runner, runner):
        runtime_owner.call(lambda: active_runner(image_path=str(capture), goal="synthetic target", provider_mode="local",
            uia_snapshot={"status": "ok", "window": {"handle": 4242, "process_id": 9001}, "controls": []}))
    assert seen[2 * per_request:] == (
        [("second-owned-model", "http://127.0.0.1:10/inference")] * per_request
        + [("owned-model", "http://127.0.0.1:9/inference")] * per_request)
    assert len({id(item) for item in providers}) == 4 * per_request
    assert not list(empty.iterdir())
    if vista:
        assert list((tmp_path / "owned-runtime-output" / "artifacts/recognition-crops").glob("*.png"))
    with pytest.raises(FileNotFoundError):
        VisionProviderFactory.load_config()


def test_direct_formal_builder_requires_own_root_config_before_windows_import(tmp_path, monkeypatch):
    import app.agent.live_runtime_composition as composition
    from app.vision.configuration import VisionConfigurationError

    monkeypatch.setattr(composition, "WindowsUIAOriginReader", lambda **kwargs: pytest.fail("missing config must not create window readers"))
    with pytest.raises(VisionConfigurationError) as error:
        composition.ExistingWindowsCurrentEvidenceAdapter(
            project_root=tmp_path, application_identity_key="native:editor.exe:notepad")
    assert error.value.code == "vision_config_missing"
    assert not (tmp_path / "configs").exists()
