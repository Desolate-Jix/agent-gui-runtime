from __future__ import annotations

import copy
import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse


class VisionConfigurationError(ValueError):
    """不暴露配置内容的配置错误。"""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code.replace("_", " "))


@dataclass(frozen=True)
class VisionConfigurationSnapshot:
    path: Path
    mode: str
    _canonical_json: str = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(json.loads(self._canonical_json))


_pinned_configuration: ContextVar[VisionConfigurationSnapshot | None] = ContextVar(
    "pinned_vision_configuration", default=None
)


def _source_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_vision_config_path(
    path: str | Path | None = None, *, project_root: str | Path | None = None
) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    root = Path(project_root).expanduser().resolve() if project_root is not None else _source_project_root()
    return (root / "configs" / "vision.json").resolve()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise VisionConfigurationError("vision_config_invalid", "Vision configuration could not be read") from exc
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise VisionConfigurationError("vision_config_invalid", "Vision configuration is invalid") from exc
    if not isinstance(value, dict):
        raise VisionConfigurationError("vision_config_invalid", "Vision configuration has an invalid shape")
    vision = value.get("vision")
    if vision is not None and not isinstance(vision, dict):
        raise VisionConfigurationError("vision_config_invalid", "Vision configuration has an invalid shape")
    return value


def load_vision_config(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        pinned = _pinned_configuration.get()
        if pinned is not None:
            return pinned.to_dict()
    return _load_json(resolve_vision_config_path(path))


def _configuration_error_for_missing(path: Path) -> VisionConfigurationError:
    return VisionConfigurationError("vision_config_missing", "Vision configuration is missing")


def _select_mode(vision_cfg: dict[str, Any], provider_mode: object) -> str:
    if provider_mode is None and "mode" not in vision_cfg:
        return "local"
    mode = vision_cfg.get("mode") if provider_mode is None else provider_mode
    if not isinstance(mode, str) or not mode.strip():
        raise VisionConfigurationError("vision_config_invalid", "Vision provider mode is invalid")
    return mode.strip().lower()


def _select_local_config(vision_cfg: dict[str, Any], selected_mode: str) -> dict[str, Any]:
    if selected_mode == "local_understanding":
        return vision_cfg.get("local_understanding") or vision_cfg.get("local_small") or vision_cfg.get("local") or {}
    if selected_mode == "local_grounding":
        return vision_cfg.get("local_grounding") or vision_cfg.get("local_large") or vision_cfg.get("local") or {}
    return vision_cfg.get("local") or {}


def _validate_timeout(vision_cfg: dict[str, Any]) -> None:
    if "timeout_seconds" not in vision_cfg or vision_cfg["timeout_seconds"] is None:
        return
    timeout = vision_cfg["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise VisionConfigurationError("vision_config_invalid", "Vision timeout is invalid")


def _is_http_endpoint(value: object) -> bool:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return False
    try:
        parsed = urlparse(value.strip())
        # 读取端口会校验诸如 ':abc' 的错误端口。
        port = parsed.port
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and (port is None or port > 0)


def _validate_local_provider(local_cfg: object) -> None:
    if not isinstance(local_cfg, dict):
        raise VisionConfigurationError("vision_config_invalid", "Selected vision configuration is invalid")
    model_name = local_cfg.get("model_name")
    if (
        not _is_http_endpoint(local_cfg.get("endpoint"))
        or not isinstance(model_name, str)
        or not model_name.strip()
        or model_name.strip().lower() in {"stub", "local_stub", "api_stub"}
    ):
        raise VisionConfigurationError("vision_provider_not_configured", "Vision provider is not configured")


def _resolve_model_paths(config: dict[str, Any], source_path: Path) -> None:
    vision_cfg = config["vision"]
    # 仅已知的项目默认配置沿用旧资源根；独立配置不按文件夹名称猜测根目录。
    source_root = _source_project_root()
    resource_root = source_root if source_path == (source_root / "configs/vision.json").resolve() else source_path.parent
    for section_name in ("local", "local_understanding", "local_grounding", "local_small", "local_large"):
        section = vision_cfg.get(section_name)
        if section is None or not isinstance(section, dict) or "model_path" not in section:
            continue
        model_path = section["model_path"]
        if model_path is None:
            continue
        if not isinstance(model_path, str):
            raise VisionConfigurationError("vision_config_invalid", "Vision model path is invalid")
        if model_path:
            expanded_path = Path(model_path).expanduser()
            section["model_path"] = str(
                (resource_root / expanded_path).resolve()
                if not expanded_path.is_absolute()
                else expanded_path.resolve()
            )


def load_formal_vision_configuration(
    path: str | Path, *, provider_mode: str | None = None
) -> VisionConfigurationSnapshot:
    source_path = resolve_vision_config_path(path)
    try:
        config = _load_json(source_path)
    except FileNotFoundError as exc:
        raise _configuration_error_for_missing(source_path) from exc
    vision_cfg = config.get("vision")
    if not isinstance(vision_cfg, dict):
        raise VisionConfigurationError("vision_config_invalid", "Vision configuration has an invalid shape")

    selected_mode = _select_mode(vision_cfg, provider_mode)
    if selected_mode == "api":
        raise VisionConfigurationError("vision_provider_unimplemented", "API vision provider is not implemented")
    if selected_mode not in {"local", "local_understanding", "local_grounding"}:
        raise VisionConfigurationError("vision_provider_unsupported", "Vision provider mode is unsupported")

    _validate_timeout(vision_cfg)
    selected_config = _select_local_config(vision_cfg, selected_mode)
    _validate_local_provider(selected_config)
    _resolve_model_paths(config, source_path)
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return VisionConfigurationSnapshot(path=source_path, mode=selected_mode, _canonical_json=canonical)


@contextmanager
def pinned_vision_configuration(snapshot: VisionConfigurationSnapshot) -> Iterator[VisionConfigurationSnapshot]:
    if not isinstance(snapshot, VisionConfigurationSnapshot):
        raise TypeError("snapshot must be a VisionConfigurationSnapshot")
    token = _pinned_configuration.set(snapshot)
    try:
        yield snapshot
    finally:
        _pinned_configuration.reset(token)
