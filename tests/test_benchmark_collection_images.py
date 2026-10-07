"""采集后可仅从归档证据复算，不借用现存文件或声明的覆盖。"""
import asyncio
import base64
from copy import deepcopy
import json

import pytest

from tests.test_benchmark_collection import ASSESSMENT, ConnectedClient, frozen, module
from tests.test_benchmark_provenance import verified_execution


def completed_collection(tmp_path, *, image_check=False):
    api = module()
    root, original = frozen(tmp_path)
    manifest = json.loads(original.read_text(encoding="utf-8"))
    spec = {key: manifest[key] for key in ("benchmark_id", "model", "cases", "artifacts")}
    if image_check:
        from tests.test_benchmark_provenance import image_execution
        binding, program, trial, files = image_execution(tmp_path)
    else:
        binding, program, trial, files = verified_execution()
    artifact = tmp_path / "reviewed-program.json"
    artifact.write_text(json.dumps(program, ensure_ascii=False), encoding="utf-8")
    binding["artifact_path"] = str(artifact.resolve())
    spec["artifacts"] = [{"kind": "workflow", "path": str(artifact.resolve()), "version": binding["program_id"]}]
    spec["cases"][0]["c_workflow"] = binding
    trial["inputs"] = {item["name"]: deepcopy(spec["cases"][0]["inputs"][item["name"]])
                       for item in program["definition"]["inputs"]
                       if item["name"] in spec["cases"][0]["inputs"]}
    target = tmp_path / "complete-manifest.json"
    api.freeze_manifest(spec, root=root, destination=target)
    client = ConnectedClient(tmp_path / "session")
    client.data_root = tmp_path / "runtime"
    run = api.BenchmarkCollection(manifest_path=target, root=root,
                                 directory=tmp_path / "collection", client=client)
    run.begin(case_id=spec["cases"][0]["case_id"], route="C")

    def call(request_id, request, result):
        client.result = {"status": "returned", "result": deepcopy(result)}
        return asyncio.run(run.call("instant_run", {"request_id": request_id,
            "command": {"kind": "learning_workflow", "request": request}}))

    call("read-program", {"action": "read", "workflow_id": binding["workflow_id"],
                           "program_id": binding["program_id"]}, program)
    call("start-program", {"action": "start", **{key: binding[key] for key in (
        "workflow_id", "program_id", "start_step_id")}, "inputs": trial["inputs"]},
        {**trial, "status": "ready", "history": []})
    for item in files:
        path = (client.data_root / "memory-library" / item["ref"][len("library/"):] if item["ref"].startswith("library/")
                else tmp_path / "session" / item["ref"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if "data_base64" in item:
            path.write_bytes(base64.b64decode(item["data_base64"]))
        elif item["ref"].startswith("workflow-observations/"):
            envelope = json.loads(item["text"])
            envelope["frame"]["image_path"] = str((tmp_path / "session/workflow-observations/after.png").resolve())
            path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        else:
            path.write_text(item["text"], encoding="utf-8")
    call("final-status", {"action": "status", "run_id": trial["run_id"]}, {**trial, "text": "current"})
    assert run.finish(request_id="final-status", assessment=ASSESSMENT)["completed"]
    return api, run, artifact


def test_image_reference_is_archived_from_declared_library_and_replayed(tmp_path):
    api, run, _ = completed_collection(tmp_path, image_check=True)
    result = api.compare_collection(run.directory)
    provenance = result["workflow_provenance"][0]
    assert provenance["coverage"]["eligible_for_full_rule_comparison"]
    reference = [item for item in provenance["evidence_files"] if item["ref"].startswith("library/desktop-review/evidence-objects/")]
    assert len(reference) == 1
    (tmp_path / "runtime/memory-library" / reference[0]["ref"][len("library/"):]).write_bytes(b"changed later")
    assert api.compare_collection(run.directory)["workflow_provenance"] == result["workflow_provenance"]


def test_original_json_and_image_bytes_are_archived_and_replayed_offline(tmp_path):
    api, run, artifact = completed_collection(tmp_path)
    result = api.compare_collection(run.directory)
    assert result["workflow_provenance"][0]["coverage"]["eligible_for_full_rule_comparison"]
    assert result["c_route_contract"]["eligible_for_full_rule_comparison"]
    assert result["comparison"]["routes"]["C"]["model_calls"]["total"] is None
    assert result["empirical_acceptance"] is False
    artifact.write_text("unrelated later content", encoding="utf-8")
    (tmp_path / "session/workflow-observations/after.png").write_bytes(b"changed later")
    assert api.compare_collection(run.directory)["workflow_provenance"] == result["workflow_provenance"]


def test_snapshot_image_mismatch_cannot_keep_full_rule_qualification(tmp_path):
    from tests.test_benchmark_collection_provenance import rehash_journal
    api, run, _ = completed_collection(tmp_path)

    def edit(events):
        provenance = next(event for event in events if event["kind"] == "finish")["payload"]["workflow_provenance"]
        image = next(item for item in provenance["evidence_files"] if "data_base64" in item)
        image["data_base64"] = base64.b64encode(b"invented image").decode("ascii")

    rehash_journal(run.directory, edit)
    with pytest.raises(ValueError, match="coverage.*changed"):
        api.compare_collection(run.directory)
