from __future__ import annotations

import json
from difflib import unified_diff
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.runtime_artifacts import write_trace


AGENT_PROMPT_DIR = Path("artifacts/agent_prompts")


class AgentPromptTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["agent_prompt_template_v1"]
    prompt_id: str
    title: str
    task: str
    version: str
    language: str = "zh-CN"
    template: str
    variables: list[str] = Field(default_factory=list)
    output_contract: str
    safety_notes: list[str] = Field(default_factory=list)
    app_profile_refs: list[str] = Field(default_factory=list)
    source_path: str | None = None

    @field_validator("prompt_id", "title", "task", "version", "template", "output_contract")
    @classmethod
    def _required_text(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned


class PromptVersionSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["agent_prompt_version_save_v1"] = "agent_prompt_version_save_v1"
    template: str = Field(min_length=1)
    version: str = Field(min_length=1)
    change_note: str = Field(default="")
    author: str = Field(default="user")


class PromptRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["agent_prompt_rollback_v1"] = "agent_prompt_rollback_v1"
    target_version: str = Field(min_length=1)
    new_version: str = Field(min_length=1)
    change_note: str = Field(default="")
    author: str = Field(default="user")


def list_agent_prompts(prompt_dir: str | Path = AGENT_PROMPT_DIR) -> list[dict[str, object]]:
    root = Path(prompt_dir)
    if not root.exists():
        return []
    prompts: list[dict[str, object]] = []
    for path in sorted(root.glob("*.json")):
        try:
            prompt = _load_prompt_path(path)
        except Exception as exc:
            prompts.append({"path": str(path), "valid": False, "error": str(exc)})
            continue
        prompts.append(_prompt_summary(prompt, path))
    return prompts


def get_agent_prompt(prompt_id: str, prompt_dir: str | Path = AGENT_PROMPT_DIR) -> tuple[AgentPromptTemplate, Path]:
    normalized = _safe_prompt_id(prompt_id)
    if not normalized:
        raise ValueError("prompt_id is required")
    root = Path(prompt_dir)
    candidates = [
        root / f"{normalized}.json",
        *sorted(root.glob(f"{normalized}__*.json")),
    ]
    existing = [path for path in candidates if path.exists()]
    if existing:
        return _load_prompt_path(existing[-1]), existing[-1]
    for path in sorted(root.glob("*.json")):
        prompt = _load_prompt_path(path)
        if _safe_prompt_id(prompt.prompt_id) == normalized:
            return prompt, path
    raise FileNotFoundError(f"Agent prompt not found: {prompt_id}")


def list_agent_prompt_versions(prompt_id: str, prompt_dir: str | Path = AGENT_PROMPT_DIR) -> list[dict[str, object]]:
    versions: list[dict[str, object]] = []
    for path in _prompt_paths(prompt_id, prompt_dir):
        payload = _read_prompt_payload(path)
        try:
            prompt = _prompt_from_payload(payload, path)
        except Exception as exc:
            versions.append({"path": str(path), "valid": False, "error": str(exc)})
            continue
        summary = _prompt_summary(prompt, path)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        summary["metadata"] = metadata
        summary["template_length"] = len(prompt.template)
        versions.append(summary)
    if not versions:
        raise FileNotFoundError(f"Agent prompt not found: {prompt_id}")
    return versions


def get_agent_prompt_version(
    prompt_id: str,
    version: str,
    prompt_dir: str | Path = AGENT_PROMPT_DIR,
) -> tuple[AgentPromptTemplate, Path]:
    wanted = str(version or "").strip()
    if not wanted:
        raise ValueError("version is required")
    wanted_slug = _safe_prompt_id(wanted)
    for path in _prompt_paths(prompt_id, prompt_dir):
        payload = _read_prompt_payload(path)
        prompt = _prompt_from_payload(payload, path)
        path_slug = _safe_prompt_id(path.stem.split("__", 1)[1] if "__" in path.stem else prompt.version)
        if prompt.version == wanted or _safe_prompt_id(prompt.version) == wanted_slug or path_slug == wanted_slug:
            return prompt, path
    raise FileNotFoundError(f"Agent prompt version not found: {prompt_id}@{version}")


def diff_agent_prompt_versions(
    prompt_id: str,
    from_version: str,
    to_version: str,
    *,
    prompt_dir: str | Path = AGENT_PROMPT_DIR,
) -> dict[str, object]:
    from_prompt, from_path = get_agent_prompt_version(prompt_id, from_version, prompt_dir)
    to_prompt, to_path = get_agent_prompt_version(prompt_id, to_version, prompt_dir)
    diff_lines = list(
        unified_diff(
            from_prompt.template.splitlines(),
            to_prompt.template.splitlines(),
            fromfile=f"{from_prompt.prompt_id}@{from_prompt.version}",
            tofile=f"{to_prompt.prompt_id}@{to_prompt.version}",
            lineterm="",
        )
    )
    return {
        "contract_version": "agent_prompt_diff_v1",
        "prompt_id": from_prompt.prompt_id,
        "from_version": from_prompt.version,
        "to_version": to_prompt.version,
        "from_path": str(from_path),
        "to_path": str(to_path),
        "changed": from_prompt.template != to_prompt.template,
        "diff": "\n".join(diff_lines),
    }


def rollback_agent_prompt_version(
    prompt_id: str,
    request: PromptRollbackRequest,
    *,
    prompt_dir: str | Path = AGENT_PROMPT_DIR,
) -> tuple[AgentPromptTemplate, Path, str]:
    target_prompt, _target_path = get_agent_prompt_version(prompt_id, request.target_version, prompt_dir)
    return save_agent_prompt_version(
        prompt_id,
        PromptVersionSave(
            template=target_prompt.template,
            version=request.new_version,
            change_note=request.change_note or f"Rollback to {target_prompt.version}",
            author=request.author,
        ),
        prompt_dir=prompt_dir,
    )


def save_agent_prompt_version(
    prompt_id: str,
    request: PromptVersionSave,
    *,
    prompt_dir: str | Path = AGENT_PROMPT_DIR,
) -> tuple[AgentPromptTemplate, Path, str]:
    base_prompt, _base_path = get_agent_prompt(prompt_id, prompt_dir)
    root = Path(prompt_dir)
    root.mkdir(parents=True, exist_ok=True)
    normalized = _safe_prompt_id(base_prompt.prompt_id)
    version_slug = _safe_prompt_id(request.version) or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    target_path = root / f"{normalized}__{version_slug}.json"
    if target_path.exists():
        raise FileExistsError(f"Prompt version already exists: {target_path}")
    updated = base_prompt.model_copy(
        update={
            "version": request.version.strip(),
            "template": request.template,
            "source_path": str(target_path),
        }
    )
    payload = updated.model_dump(exclude_none=True)
    payload["metadata"] = {
        "change_note": request.change_note,
        "saved_by": request.author,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trace_path = write_trace(
        category="agent_prompts",
        operation="save_prompt_version",
        payload={
            "success": True,
            "prompt_id": base_prompt.prompt_id,
            "version": request.version,
            "path": str(target_path),
            "change_note": request.change_note,
        },
        name_hint=base_prompt.prompt_id,
    )
    return _load_prompt_path(target_path), target_path, trace_path


def _load_prompt_path(path: Path) -> AgentPromptTemplate:
    return _prompt_from_payload(_read_prompt_payload(path), path)


def _read_prompt_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Prompt payload must be an object: {path}")
    return payload


def _prompt_from_payload(payload: dict[str, object], path: Path) -> AgentPromptTemplate:
    data = dict(payload)
    data.pop("metadata", None)
    data.setdefault("source_path", str(path))
    return AgentPromptTemplate.model_validate(data)


def _prompt_paths(prompt_id: str, prompt_dir: str | Path = AGENT_PROMPT_DIR) -> list[Path]:
    normalized = _safe_prompt_id(prompt_id)
    if not normalized:
        raise ValueError("prompt_id is required")
    root = Path(prompt_dir)
    paths = []
    base = root / f"{normalized}.json"
    if base.exists():
        paths.append(base)
    paths.extend(path for path in sorted(root.glob(f"{normalized}__*.json")) if path not in paths)
    if not paths:
        for path in sorted(root.glob("*.json")):
            try:
                prompt = _load_prompt_path(path)
            except Exception:
                continue
            if _safe_prompt_id(prompt.prompt_id) == normalized:
                paths.append(path)
    return paths


def _prompt_summary(prompt: AgentPromptTemplate, path: Path) -> dict[str, object]:
    return {
        "contract_version": prompt.contract_version,
        "prompt_id": prompt.prompt_id,
        "title": prompt.title,
        "task": prompt.task,
        "version": prompt.version,
        "language": prompt.language,
        "output_contract": prompt.output_contract,
        "path": str(path),
        "valid": True,
        "variable_count": len(prompt.variables),
        "safety_note_count": len(prompt.safety_notes),
        "app_profile_refs": list(prompt.app_profile_refs),
    }


def _safe_prompt_id(value: str) -> str:
    cleaned = str(value or "").strip().lower().replace(" ", "_")
    return "".join(ch for ch in cleaned if ch.isalnum() or ch in {"_", "-"})
