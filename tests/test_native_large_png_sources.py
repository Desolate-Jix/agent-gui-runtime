"""可信本地原图的大 PNG 预算必须贯通保存与重开，不能由修改自授。"""

from copy import deepcopy
import base64
from hashlib import sha256
from io import BytesIO
import random
from time import perf_counter

from PIL import Image
import pytest

from app.agent.fresh_learning_archive import FreshLearningObservationArchive
from app.desktop_review.external_mapping import ExternalMappingError, normalize_agent_link_batch, source_ref_for_batch
from app.desktop_review.graph_revision import GraphRevisionService
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.workspace import DesktopReviewError
from tests.test_formal_fresh_graph_source import REVIEWER, _stage
from tests.test_formal_fresh_learning_observation import _owner, _bound, _WindowManager, _UIAProvider


@pytest.fixture(scope="module")
def large_png():
    stream = BytesIO()
    Image.frombytes("RGB", (1050, 700), random.Random(20260914).randbytes(1050 * 700 * 3)).save(stream, format="PNG")
    raw = stream.getvalue()
    assert 2 * 1024 * 1024 < len(raw) < 32 * 1024 * 1024
    return raw


def _batch(raw):
    return {
        "contract_version": "agent_link_v1", "idempotency_key": "large-native-source",
        "batch_id": "large-native-source", "title": "Synthetic large screen",
        "learning_outcome": "partial", "outcome_reason": "Observation only",
        "screenshots": [{"screenshot_id": "capture", "png_base64": base64.b64encode(raw).decode("ascii")}],
        "interfaces": [{"interface_id": "observed-screen", "screenshot_id": "capture", "meaning": "Synthetic screen", "regions": []}],
        "relationships": [], "steps": [], "issues": [],
    }


def _packet(root, raw):
    class SyntheticScreenshot:
        def capture_window(self, **kwargs):
            root.mkdir(parents=True, exist_ok=True)
            path = root / "synthetic.png"
            path.write_bytes(raw)
            return {"image_path": str(path), "image_width": 1050, "image_height": 700,
                    "roi": None, "window_size": {"width": 1050, "height": 700}}

    return _owner(root, screenshot=SyntheticScreenshot(),
                  manager=_WindowManager(*[_bound(width=1050, height=700) for _ in range(3)]),
                  uia=_UIAProvider(width=1050, height=700)).observe(target_window_handle=4242, target_process_id=9001)


def test_external_normalization_does_not_trust_self_reported_png_digest(large_png):
    value = _batch(large_png)
    value["screenshots"][0].update(sha256=sha256(large_png).hexdigest(), width=1050, height=700)
    with pytest.raises(ExternalMappingError):
        normalize_agent_link_batch(value)


def test_explicit_original_allowlist_preserves_strict_png_derivations(large_png):
    value = _batch(large_png)
    before = deepcopy(value)
    allowed = frozenset({sha256(large_png).hexdigest()})
    normalized = normalize_agent_link_batch(value, existing_png_sha256=allowed)
    assert value == before
    assert normalized["screenshots"][0]["sha256"] in allowed
    assert normalized["screenshots"][0]["width"] == 1050
    for field, bad in (("sha256", "0" * 64), ("width", 100), ("height", 100)):
        changed = deepcopy(normalized)
        changed["screenshots"][0][field] = bad
        with pytest.raises(ExternalMappingError):
            normalize_agent_link_batch(changed, existing_png_sha256=allowed)


def test_large_fresh_original_survives_native_saves_and_all_reopens(tmp_path, large_png):
    packet = _packet(tmp_path / "capture", large_png)
    host, connection, _segment, _packet_value, args, staged = _stage(tmp_path, packet=packet)
    task, batch_id = connection["task_id"], staged["batch_id"]
    try:
        facade = host.facade
        second = host.fresh_learning.stage(**{**args, "idempotency_key": "second-large-source", "meaning": "Another interpretation"})
        graph = facade.load_graph_revision(second["logical_workflow_id"])
        assert len(graph["graph"]["nodes"]) == 2
        loaded = facade.load_batch(task, batch_id)
        edited = deepcopy(loaded["batch"])
        edited["interfaces"][0]["meaning"] = "Reviewed synthetic screen"
        saved = facade.save_revision(task, batch_id, 0, edited)
        edited["title"] = "Second local revision"
        saved = facade.save_revision(task, batch_id, 1, edited)
        interface = facade.import_interface_content(task, batch_id, "observed-screen")
        interface = facade.save_interface_content(interface["interface_id"], interface["revision"],
            interface["content_sha256"], {"meaning": "Independent synthetic screen"}, "large-save")
        graph_service = GraphRevisionService(facade)
        imported = graph_service._imported_workspace(task, batch_id, saved["source_ref"], saved)
        graph = facade.load_graph_revision(staged["logical_workflow_id"])
        refs = {**graph["source_refs"], "imported_workspace": imported}
        assert graph_service._validate_imported_workspace(refs, loaded["batch"]) == saved
    finally:
        host.close()

    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        assert reopened.facade.load_batch(task, batch_id) == saved
        assert reopened.facade.load_interface_content(interface["interface_id"]) == interface
        image = reopened.facade.load_interface_content_evidence(interface["interface_id"])
        assert image["sha256"] == sha256(large_png).hexdigest()
        assert (tmp_path / "review" / image["image_path"]).read_bytes() == large_png
        actual = reopened.facade.load_graph_revision(staged["logical_workflow_id"])
        assert actual == graph
        node = actual["graph"]["nodes"][0]
        evidence = reopened.facade.load_graph_node_evidence(actual["logical_workflow_id"], actual["revision"], actual["content_sha256"], node["node_id"])
        assert evidence["screenshot"]["png_bytes"] == large_png
    finally:
        reopened.close()


@pytest.mark.parametrize("replacement", ["different_large", "new_large", "derived_hash", "metadata"])
def test_native_save_cannot_expand_original_png_allowlist(tmp_path, large_png, replacement):
    host, connection, _, _, _, staged = _stage(tmp_path, packet=_packet(tmp_path / "capture", large_png))
    try:
        task, batch_id = connection["task_id"], staged["batch_id"]
        loaded = host.facade.load_batch(task, batch_id)
        edited = deepcopy(loaded["batch"])
        shot = edited["screenshots"][0]
        if replacement in {"different_large", "new_large"}:
            stream = BytesIO()
            image = Image.open(BytesIO(large_png))
            image.putpixel((0, 0), (1, 2, 3))
            image.save(stream, format="PNG")
            changed = stream.getvalue()
            new = {"screenshot_id": "new-capture" if replacement == "new_large" else "capture",
                   "png_base64": base64.b64encode(changed).decode("ascii"),
                   "sha256": sha256(changed).hexdigest(), "width": 1050, "height": 700}
            if replacement == "new_large":
                edited["screenshots"].append(new)
            else:
                edited["screenshots"][0] = new
        elif replacement == "derived_hash":
            shot["sha256"] = "0" * 64
        else:
            shot["trusted_local"] = True
        with pytest.raises(DesktopReviewError):
            host.facade.save_revision(task, batch_id, 0, edited)
        assert host.facade.load_batch(task, batch_id) == loaded
    finally:
        host.close()


def test_native_large_original_requires_archive_and_authoritative_batch(tmp_path, large_png):
    host, connection, _, _, _, staged = _stage(tmp_path, packet=_packet(tmp_path / "capture", large_png))
    try:
        task, batch_id = connection["task_id"], staged["batch_id"]
        facade = host.facade
        original = facade.load_batch(task, batch_id)
        saved = facade.save_revision(task, batch_id, 0, original["batch"])
        interface = facade.import_interface_content(task, batch_id, "observed-screen")

        changed = deepcopy(original["batch"])
        changed["title"] = "Self-rehashed source is not authority"
        with pytest.raises(DesktopReviewError):
            facade._normalize_source_copy(changed, task, batch_id, source_ref_for_batch(changed))

        png_path = host.fresh_learning.archive.png_root / f"{sha256(large_png).hexdigest()}.png"
        png_path.write_bytes(b"not the archived PNG")
        for read in (
            lambda: facade.load_batch(task, batch_id),
            lambda: facade.load_interface_content(interface["interface_id"]),
            lambda: facade.load_graph_revision(staged["logical_workflow_id"]),
        ):
            with pytest.raises(DesktopReviewError):
                read()
        png_path.write_bytes(large_png)
        assert facade.load_batch(task, batch_id) == saved
    finally:
        host.close()


def test_large_original_does_not_gain_budget_from_metadata_without_archive(tmp_path, large_png, monkeypatch):
    host, connection, _, _, _, staged = _stage(tmp_path, packet=_packet(tmp_path / "capture", large_png))
    try:
        task, batch_id = connection["task_id"], staged["batch_id"]
        facade = host.facade
        detail = facade._reviewer("get_batch", {"task_id": task, "batch_id": batch_id})
        without_source = deepcopy(detail)
        without_source.pop("fresh_learning_source")
        monkeypatch.setattr(facade, "_reviewer", lambda *_args: deepcopy(without_source))
        with pytest.raises(DesktopReviewError):
            facade._load_source_batch(task, batch_id)
        wrong_source = deepcopy(detail)
        wrong_source["fresh_learning_source"]["reference"]["source_id"] = "missing-source"
        monkeypatch.setattr(facade, "_reviewer", lambda *_args: deepcopy(wrong_source))
        with pytest.raises(DesktopReviewError):
            facade._load_source_batch(task, batch_id)
    finally:
        host.close()


def test_large_graph_source_verifies_archive_once_per_read_without_cross_request_cache(tmp_path, large_png, monkeypatch):
    host, _, _, _, _, staged = _stage(tmp_path, packet=_packet(tmp_path / "capture", large_png))
    try:
        facade = host.facade
        graph = facade.load_graph_revision(staged["logical_workflow_id"])
        real_archive, real_reviewer = FreshLearningObservationArchive.read, facade._reviewer
        calls = {"archive": 0, "reviewer": 0}

        def read_archive(self, *args, **kwargs):
            calls["archive"] += 1
            return real_archive(self, *args, **kwargs)

        def read_reviewer(*args, **kwargs):
            calls["reviewer"] += 1
            return real_reviewer(*args, **kwargs)

        monkeypatch.setattr(FreshLearningObservationArchive, "read", read_archive)
        monkeypatch.setattr(facade, "_reviewer", read_reviewer)
        service = GraphRevisionService(facade)
        started = perf_counter()
        service._validate_source_ref_bytes(graph["source_refs"])
        elapsed = perf_counter() - started
        assert calls == {"archive": 1, "reviewer": 1}
        service._validate_source_ref_bytes(graph["source_refs"])
        assert calls == {"archive": 2, "reviewer": 2}
        print(f"large source validation: {len(large_png)} bytes, 1 archive + 1 reviewer, {elapsed * 1000:.3f} ms")
        png_path = host.fresh_learning.archive.png_root / f"{sha256(large_png).hexdigest()}.png"
        png_path.write_bytes(b"changed between requests")
        with pytest.raises(DesktopReviewError):
            service._validate_source_ref_bytes(graph["source_refs"])
        assert calls == {"archive": 3, "reviewer": 3}
    finally:
        host.close()
