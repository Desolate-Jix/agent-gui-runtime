"""首次使用时写入 VISTA 本地配置；该模块绝不启动模型服务。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any

from app.vision.configuration import _source_project_root


class ModelSetupError(ValueError):
    """向桌面调用方暴露稳定错误代码与中文消息。"""
    def __init__(self, code: str, message: str, *, destination_published: bool = False) -> None:
        self.code = code
        self.message = message
        self.destination_published = destination_published
        super().__init__(f"{code}: {message}")


def _template_path() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent / "_internal"))
    else:
        root = _source_project_root()
    path = root / "configs" / "model_profiles" / "vista_4b_transformers.json"
    if not path.is_file():
        raise ModelSetupError("model_setup_template_missing", "未找到 VISTA-4B 配置模板。")
    return path


def _json_object(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelSetupError(code, "模型元数据无效。") from error
    if not isinstance(value, dict):
        raise ModelSetupError(code, "模型元数据无效。")
    return value


def _model_directory(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute() or not raw.exists() or not raw.is_dir():
        raise ModelSetupError("model_setup_model_directory_invalid", "请选择存在的绝对模型目录。")
    root = raw.resolve()
    config = _json_object(root / "config.json", "model_setup_model_metadata_invalid")
    if config.get("model_type") != "qwen3_5":
        raise ModelSetupError("model_setup_model_metadata_invalid", "模型配置不是受支持的 VISTA 元数据。")
    _json_object(root / "tokenizer_config.json", "model_setup_model_metadata_invalid")
    tokenizer = root / "tokenizer.json"
    if not tokenizer.is_file() or tokenizer.stat().st_size == 0:
        raise ModelSetupError("model_setup_model_metadata_invalid", "模型 tokenizer.json 缺失或为空。")
    processor = root / "processor_config.json"
    if not processor.is_file():
        processor = root / "preprocessor_config.json"
    _json_object(processor, "model_setup_model_metadata_invalid")
    index_path = root / "model.safetensors.index.json"
    if index_path.exists() or index_path.is_symlink():
        # 已有索引必须有效，不能借单文件隐藏缺失或损坏的分片。
        index = _json_object(index_path, "model_setup_model_metadata_invalid")
        mapping = index.get("weight_map")
        if not isinstance(mapping, dict) or not mapping:
            raise ModelSetupError("model_setup_model_metadata_invalid", "模型权重索引无效。")
        names = mapping.values()
    else:
        names = ["model.safetensors"]
    for name in names:
        if not isinstance(name, str) or not name.endswith(".safetensors"):
            raise ModelSetupError("model_setup_model_metadata_invalid", "模型权重索引无效。")
        candidate = (root / name).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ModelSetupError("model_setup_model_metadata_invalid", "模型权重索引越出了所选目录。") from error
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            raise ModelSetupError("model_setup_model_metadata_invalid", "模型权重文件缺失或为空。")
    return root


def _publish_exclusive(destination: Path, payload: bytes) -> None:
    stage = destination.parent / ("." + destination.name + "." + secrets.token_hex(12) + ".stage")
    stage_owned = False
    published = False
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with stage.open("xb") as handle:
            stage_owned = True
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(stage, destination)
        published = True
    except FileExistsError as error:
        raise ModelSetupError("model_setup_config_exists", "配置文件已存在，未覆盖原文件。") from error
    except OSError as error:
        raise ModelSetupError("model_setup_publish_failed", "配置写入未完成。") from error
    finally:
        try:
            if stage_owned:
                stage.unlink(missing_ok=True)
        except OSError as error:
            raise ModelSetupError(
                "model_setup_cleanup_pending", "暂存文件清理未完成，请检查配置目录。",
                destination_published=published,
            ) from error


def initialize_vista_configuration(config_path: str | Path, model_directory: str | Path, port: int = 13244) -> dict[str, Any]:
    """验证用户选择的本地权重并首次发布可由既有运行时读取的配置。"""
    config = Path(config_path).expanduser()
    if config.exists() or config.is_symlink():
        raise ModelSetupError("model_setup_config_exists", "配置文件已存在，未覆盖原文件。")
    if not config.is_absolute():
        config = config.resolve()
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ModelSetupError("model_setup_port_invalid", "端口必须在 1 到 65535 之间。")
    model_root = _model_directory(model_directory)
    template = _json_object(_template_path(), "model_setup_template_invalid")
    profile = dict(template)
    profile.update({
        "model_path": str(model_root), "host": "127.0.0.1", "port": port,
        "endpoint": f"http://127.0.0.1:{port}/v1/chat/completions",
        "request_cancel_endpoint": f"http://127.0.0.1:{port}/v1/cancel",
    })
    if getattr(sys, "frozen", False):
        for key in ("python_path", "start_script", "stop_script", "pid_file"):
            profile.pop(key, None)
    else:
        root = _source_project_root()
        profile["start_script"] = str((root / profile["start_script"]).resolve())
        profile["stop_script"] = str((root / profile["stop_script"]).resolve())
        profile["pid_file"] = str((config.parent / "logs" / "vista-4b-transformers-server.pid").resolve())
    profile_path = config.parent / "model_profiles" / ("vista_4b_" + secrets.token_hex(12) + ".json")
    profile_bytes = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    vision = {"vision": {"mode": "local_grounding", "timeout_seconds": 600,
        "local_grounding": {key: profile[key] for key in ("model_name", "endpoint", "profile_id", "runtime", "output_contract", "provider_mode", "input_format", "supports_ocr_anchors", "model_path")}}}
    # 必须关联刚生成的 profile；只有端点会被当成外部服务，不会托管本地模型。
    vision["vision"]["local_grounding"]["model_service"] = {
        "mode": "managed", "profile_path": str(profile_path.absolute()), "readiness_timeout_seconds": 180,
    }
    config_bytes = json.dumps(vision, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    _publish_exclusive(profile_path, profile_bytes)
    try:
        _publish_exclusive(config, config_bytes)
    except BaseException as error:
        # 配置已发布时仍引用此 profile；清理失败不能撤掉已生效的依赖。
        if getattr(error, "destination_published", False):
            raise
        try:
            profile_path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            raise ModelSetupError("model_setup_cleanup_pending", "配置写入未完成，新增模型配置清理也未完成。") from cleanup_error
        raise
    return {"config_path": str(config), "profile_path": str(profile_path), "model_directory": str(model_root), "port": port,
            "status": "configured_unverified", "model_loaded": False, "service_started": False}
