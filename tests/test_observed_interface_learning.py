from __future__ import annotations

import pytest
from threading import RLock

from app.agent_link.contracts import AgentLinkError
from app.desktop_review.observed_interface_learning import submit_observed_interface_learning


class _Store:
    def __init__(self, segment):
        self.segment = segment

    def read(self, callback):
        return callback({"connections": {"c1": {"task_id": "t1", "learning_segments": {"s1": self.segment}}}})


class _Service:
    def __init__(self, segment):
        self._store = _Store(segment)


class _Facade:
    def __init__(self, root):
        from pathlib import Path
        self._workspace_root = Path(root)
        self._guard = RLock()
        self._service = _Service({"task_id": "t1", "status": "active", "observations": [{"batch_id": "b1"}]})
        self.saved = None

    def _load_source_batch(self, task_id, batch_id):
        assert (task_id, batch_id) == ("t1", "b1")
        return {"interfaces": [{"interface_id": "observed-screen", "regions": []}], "screenshots": []}

    def import_interface_content(self, task_id, batch_id, external):
        return {"interface_id": "interface-12345678-1234-1234-1234-123456789abc", "revision": 1,
                "content_sha256": "a" * 64, "content": {"regions": []}, "review_status": "draft"}

    def save_interface_content(self, *args):
        self.saved = args
        return {"interface_id": args[0], "revision": 2, "content_sha256": "b" * 64}


def test_observed_interface_learning_saves_stable_region_ids(tmp_path, monkeypatch):
    facade = _Facade(tmp_path)
    monkeypatch.setattr("app.desktop_review.interface_content.InterfaceContentService._current", lambda self, _: {"requests": {}})
    monkeypatch.setattr("app.desktop_review.interface_content.InterfaceContentService._record_initial_learning_completion",
                        lambda self, interface_id, *, request_sha256: {"interface_id": interface_id, "revision": 2})
    result = submit_observed_interface_learning(
        facade, connection_id="c1", task_id="t1", segment_id="s1", batch_id="b1",
        expected_revision=1, expected_sha256="a" * 64, meaning="列表页",
        recognition_text="标题", regions=[{"bbox": [1, 2, 10, 10], "name": "按钮", "kind": "button", "meaning": "打开"}],
        idempotency_key="k1",
    )
    assert result["revision"] == 2
    assert facade.saved[3]["regions"][0]["region_id"].startswith("region-user-")


def test_observed_interface_learning_rejects_cross_segment_batch(tmp_path):
    facade = _Facade(tmp_path)
    with pytest.raises(AgentLinkError) as error:
        submit_observed_interface_learning(
            facade, connection_id="c1", task_id="t1", segment_id="s1", batch_id="other",
            expected_revision=1, expected_sha256="a" * 64, meaning="x", recognition_text=None,
            regions=[{"bbox": [1, 2, 10, 10], "name": "按钮", "kind": "button", "meaning": "打开"}], idempotency_key="k1",
        )
    assert error.value.code == "not_found"
