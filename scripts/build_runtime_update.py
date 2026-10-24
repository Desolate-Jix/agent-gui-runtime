"""Generate fixed-source updater assets from an already verified installer build."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build(installer_build, output):
    from app.runtime_update import PYTHON_CONTRACT, validate_target
    source, output = Path(installer_build).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("new_update_output_directory_required")
    metadata = json.loads((source / "payload-manifest.json").read_text(encoding="utf-8"))
    if metadata.get("component") != "execution" or metadata.get("format") != "component-payload-v1":
        raise ValueError("execution_installer_build_required")
    version = metadata["version"]
    base = "https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v" + version + "/"
    archive, installer = source / "payload.zip", source / "AgentGUIRuntimeExecution-Setup.exe"
    def asset(path, name):
        return {"url": base + name, "size": path.stat().st_size, "sha256": sha256(path.read_bytes()).hexdigest()}
    target = {"schema": "runtime_update.v1", "component": "execution", "version": version,
              "python_contract": PYTHON_CONTRACT, "files": metadata["files"],
              "payload": asset(archive, "AgentGUIRuntimeExecution-update.zip"),
              "installer": asset(installer, installer.name)}
    validate_target(target)
    output.mkdir(parents=True)
    shutil.copyfile(archive, output / "AgentGUIRuntimeExecution-update.zip")
    (output / "runtime-update.json").write_text(json.dumps(target, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"manifest": str(output / "runtime-update.json"), "payload": str(output / "AgentGUIRuntimeExecution-update.zip"),
            "installer": str(installer), "version": version, "published": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.installer_build, args.output), ensure_ascii=False))
