from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
from pathlib import Path
from typing import Any


BUFFER_SIZE = 8 * 1024 * 1024


def _read_header(path: Path) -> tuple[int, dict[str, Any]]:
    with path.open("rb") as handle:
        raw_length = handle.read(8)
        if len(raw_length) != 8:
            raise ValueError(f"Invalid safetensors header prefix: {path}")
        header_length = struct.unpack("<Q", raw_length)[0]
        header = json.loads(handle.read(header_length))
    if not isinstance(header, dict):
        raise ValueError(f"Invalid safetensors header object: {path}")
    return header_length, header


def _tensor_entries(header: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name, spec in header.items():
        if name == "__metadata__":
            continue
        if not isinstance(spec, dict) or not isinstance(spec.get("data_offsets"), list):
            raise ValueError(f"Invalid tensor entry: {name}")
        start, end = (int(value) for value in spec["data_offsets"])
        if start < 0 or end < start:
            raise ValueError(f"Invalid tensor offsets: {name}")
        entries.append({"name": name, "spec": spec, "start": start, "end": end, "size": end - start})
    return sorted(entries, key=lambda item: (item["start"], item["name"]))


def _partition(entries: list[dict[str, Any]], max_shard_bytes: int) -> list[list[dict[str, Any]]]:
    shards: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_size = 0
    for entry in entries:
        if current and current_size + entry["size"] > max_shard_bytes:
            shards.append(current)
            current = []
            current_size = 0
        current.append(entry)
        current_size += entry["size"]
    if current:
        shards.append(current)
    return shards


def _encoded_header(entries: list[dict[str, Any]], metadata: Any) -> bytes:
    header: dict[str, Any] = {}
    if isinstance(metadata, dict):
        header["__metadata__"] = metadata
    offset = 0
    for entry in entries:
        spec = {key: value for key, value in entry["spec"].items() if key != "data_offsets"}
        spec["data_offsets"] = [offset, offset + entry["size"]]
        header[entry["name"]] = spec
        offset += entry["size"]
    encoded = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    padding = (-len(encoded)) % 8
    return encoded + (b" " * padding)


def _copy_range(source, target, *, start: int, size: int, digest: hashlib._Hash) -> None:
    source.seek(start)
    remaining = size
    while remaining:
        chunk = source.read(min(BUFFER_SIZE, remaining))
        if not chunk:
            raise EOFError(f"Unexpected end of safetensors data at offset {start + size - remaining}")
        target.write(chunk)
        digest.update(chunk)
        remaining -= len(chunk)


def shard_safetensors(
    *,
    source_path: Path,
    output_dir: Path,
    max_shard_bytes: int,
    copy_support_files: bool = True,
) -> dict[str, Any]:
    source_path = source_path.resolve()
    output_dir = output_dir.resolve()
    if max_shard_bytes <= 0:
        raise ValueError("max_shard_bytes must be positive")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    header_length, header = _read_header(source_path)
    entries = _tensor_entries(header)
    shards = _partition(entries, max_shard_bytes)
    source_data_offset = 8 + header_length
    total_size = sum(entry["size"] for entry in entries)
    source_digest = hashlib.sha256()
    output_digest = hashlib.sha256()
    weight_map: dict[str, str] = {}
    shard_paths: list[str] = []

    with source_path.open("rb") as source:
        for index, shard_entries in enumerate(shards, start=1):
            shard_name = f"model-{index:05d}-of-{len(shards):05d}.safetensors"
            shard_path = output_dir / shard_name
            shard_header = _encoded_header(shard_entries, header.get("__metadata__"))
            with shard_path.open("wb") as target:
                target.write(struct.pack("<Q", len(shard_header)))
                target.write(shard_header)
                for entry in shard_entries:
                    _copy_range(
                        source,
                        target,
                        start=source_data_offset + entry["start"],
                        size=entry["size"],
                        digest=output_digest,
                    )
                    weight_map[entry["name"]] = shard_name
            shard_paths.append(str(shard_path))

        for entry in entries:
            source.seek(source_data_offset + entry["start"])
            remaining = entry["size"]
            while remaining:
                chunk = source.read(min(BUFFER_SIZE, remaining))
                if not chunk:
                    raise EOFError(f"Unexpected end of source tensor data: {entry['name']}")
                source_digest.update(chunk)
                remaining -= len(chunk)

    if source_digest.digest() != output_digest.digest():
        raise ValueError("Sharded tensor byte stream does not match the source tensor byte stream")

    index_payload = {
        "metadata": {"total_size": total_size},
        "weight_map": weight_map,
    }
    index_path = output_dir / "model.safetensors.index.json"
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if copy_support_files:
        for path in source_path.parent.iterdir():
            if not path.is_file() or path.name == source_path.name:
                continue
            if path.name == index_path.name or path.name.startswith("model-") and path.suffix == ".safetensors":
                continue
            shutil.copy2(path, output_dir / path.name)

    return {
        "contract_version": "safetensors_no_mmap_shard_report_v1",
        "source_path": str(source_path),
        "output_dir": str(output_dir),
        "tensor_count": len(entries),
        "shard_count": len(shards),
        "total_size": total_size,
        "max_tensor_size": max((entry["size"] for entry in entries), default=0),
        "source_tensor_stream_sha256": source_digest.hexdigest(),
        "output_tensor_stream_sha256": output_digest.hexdigest(),
        "index_path": str(index_path),
        "shard_paths": shard_paths,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Shard a safetensors file without memory-mapping the source file")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-shard-bytes", type=int, default=1610612736)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = shard_safetensors(
        source_path=args.source,
        output_dir=args.output_dir,
        max_shard_bytes=args.max_shard_bytes,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
