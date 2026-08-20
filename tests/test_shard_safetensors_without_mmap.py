from __future__ import annotations

import json
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file

from scripts.shard_safetensors_without_mmap import shard_safetensors


def test_shard_safetensors_preserves_tensor_values_and_index(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    source_path = source_dir / "model.safetensors"
    tensors = {
        "a.weight": torch.arange(24, dtype=torch.float32).reshape(6, 4),
        "b.weight": torch.arange(16, dtype=torch.int64).reshape(4, 4),
        "c.bias": torch.arange(8, dtype=torch.float16),
    }
    save_file(tensors, source_path, metadata={"format": "pt"})
    (source_dir / "config.json").write_text('{"model_type":"demo"}', encoding="utf-8")

    report = shard_safetensors(
        source_path=source_path,
        output_dir=output_dir,
        max_shard_bytes=100,
    )

    assert report["shard_count"] >= 2
    assert report["source_tensor_stream_sha256"] == report["output_tensor_stream_sha256"]
    index = json.loads((output_dir / "model.safetensors.index.json").read_text(encoding="utf-8"))
    assert set(index["weight_map"]) == set(tensors)
    assert (output_dir / "config.json").exists()
    restored = {}
    for shard_name in sorted(set(index["weight_map"].values())):
        restored.update(load_file(output_dir / shard_name))
    assert set(restored) == set(tensors)
    for name, expected in tensors.items():
        assert torch.equal(restored[name], expected)
