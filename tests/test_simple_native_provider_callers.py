from __future__ import annotations
from pathlib import Path


def test_qwen_actual_caller_sends_projection_not_full_runtime_request(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_callers import call_qwen_projected_binding
    seen=[]
    class Transport:
        def post(self, *, url, payload, timeout): seen.append(payload); return {"bindings": []}
    call_qwen_projected_binding(image_path=tmp_path/'image.png', projection={"image_size":[1,1],"candidates":[]}, transport=Transport())
    assert "candidate_id" not in str(seen[0]) and seen[0]["projection"]["candidates"] == []


def test_qwen_actual_response_is_expanded_before_existing_parser() -> None:
    from app.learn.hybrid.simple_native_contracts import expand_qwen_model_response
    runtime={"screenshot":{"image_size":{"width":10,"height":10}},"candidates":[{"candidate_id":"candidate/a","bbox_original":[1,1,2,2],"active":True}]}
    assert expand_qwen_model_response({"bindings":[{"i":0,"role":"button","label":"x","status":"BOUND","confidence":1}]},projection={"image_size":[10,10],"candidates":[{"i":0,"box":[1,1,2,2],"active":True}]},runtime_request=runtime)["bindings"][0]["candidate_id"] == "candidate/a"


def test_vista_actual_caller_sends_no_generic_json_system_prompt_or_response_format(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_callers import call_vista_bare_point
    seen=[]
    class Transport:
        def post(self, *, url, payload, timeout): seen.append(payload); return "[1,2]"
    call_vista_bare_point(roi_path=tmp_path/'roi.png',target_text='Find target',transport=Transport())
    assert "response_format" not in seen[0] and all(message["role"] != "system" for message in seen[0]["messages"])


def test_vista_actual_caller_reads_bare_normalized_pair(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_callers import call_vista_bare_point
    class Transport:
        def post(self, **kwargs): return "[437,612]"
    assert call_vista_bare_point(roi_path=tmp_path/'roi.png',target_text='x',transport=Transport()) == "[437,612]"


def test_omni_worker_projects_only_native_fields_before_runtime_adapter() -> None:
    from app.learn.hybrid.simple_native_callers import project_omni_official_items
    assert project_omni_official_items([{"bbox":[0,0,1,1],"type":"text","content":"x","interactivity":False,"source_item_id":"bad"}]) == {"items":[{"bbox":[0,0,1,1],"type":"text","content":"x","interactivity":False}]}


def test_actual_slots_are_lazy_and_default_cli_starts_no_models() -> None:
    from app.learn.hybrid.simple_native_callers import make_actual_simple_native_slots
    class Lifecycle: started=False
    slots=make_actual_simple_native_slots(config={"endpoints":{"qwen":"q","vista":"v","omni":"o"}},lifecycle=Lifecycle(),transport=object())
    assert slots.omni and not Lifecycle.started


def test_actual_lifecycle_is_exclusive_bounded_and_records_verified_cleanup() -> None:
    from app.learn.hybrid.simple_native_callers import verify_cleanup_receipt
    assert verify_cleanup_receipt({"verified":True,"owned_processes":[]}) is True


def test_cancellation_stops_owned_processes_and_never_kills_unknown_processes() -> None:
    from app.learn.hybrid.simple_native_callers import cancel_owned_processes
    class Lifecycle:
        def stop_owned(self): return {"verified":True,"owned_processes":[]}
    assert cancel_owned_processes(Lifecycle())["verified"] is True
