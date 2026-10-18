"""操作方明确选择图片后的共用包装逻辑；不生成或提交学习语义。"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from .artifacts import MAX_ARTIFACT_BUNDLE_BYTES, validate_artifact_bundle
from .contracts import MAX_PNG_BYTES


def prepare_bundle(images: Mapping[str, Path], *, connection_id: str, task_id: str, output: Path) -> dict:
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("artifact bundle output already exists")
    if not images or len(images) > 32:
        raise ValueError("provide between one and 32 explicitly selected PNG files")
    entries, references = [], []
    for identity, source in images.items():
        with Path(source).open("rb") as stream:
            raw = stream.read(MAX_PNG_BYTES + 1)
        if not raw or len(raw) > MAX_PNG_BYTES:
            raise ValueError("selected PNG is empty or exceeds the byte limit")
        digest = hashlib.sha256(raw).hexdigest()
        entries.append({"artifact_id": identity, "sha256": digest, "png_base64": base64.b64encode(raw).decode("ascii")})
        references.append({"screenshot_id": identity, "artifact_id": identity, "sha256": digest})
    bundle = {"contract_version": "agent_link_artifact_bundle_v1", "connection_id": connection_id, "task_id": task_id, "artifacts": entries}
    validate_artifact_bundle(bundle, connection_id=connection_id, task_id=task_id)
    raw_json = json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    if len(raw_json) > MAX_ARTIFACT_BUNDLE_BYTES:
        raise ValueError("artifact bundle exceeds the file byte limit")
    descriptor, temporary = tempfile.mkstemp(prefix=".agent-link-bundle-", suffix=".tmp", dir=output.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw_json); stream.flush(); os.fsync(stream.fileno())
        # 同目录硬链接原子创建，输出已存在时失败，绝不覆盖旧包。
        os.link(temporary_path, output)
    finally:
        temporary_path.unlink()
    with output.open("rb") as stream:
        verified = stream.read(MAX_ARTIFACT_BUNDLE_BYTES + 1)
    if verified != raw_json:
        raise RuntimeError("written artifact bundle did not match the prepared bytes")
    return {"contract_version": "agent_link_artifact_references_v1", "connection_id": connection_id, "task_id": task_id, "bundle_path": str(output.resolve()), "bundle_sha256": hashlib.sha256(raw_json).hexdigest(), "screenshots": references}
