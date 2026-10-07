"""学习目标标注只使用同一张已验证原图。"""
from copy import deepcopy
import pytest
from tests.test_learning_observation_source import observation_scene, record_learning_click
from app.learning_memory.workspace import MemoryWorkspace


def test_new_graph_import_has_target_box(observation_scene):
    from app.learning_memory.graph_source import logical_id
    _, root, _, _, observation = record_learning_click(observation_scene)
    with MemoryWorkspace(root) as library:
        graph = library.load_graph_revision(logical_id("search-records"))
        contents = [library.load_interface_content(node["interface_reference"]["interface_id"],
                    node["interface_reference"]["version_id"]) for node in graph["graph"]["nodes"]]
        before = next(row for row in contents if row["source"]["view"] == "before")
        after = next(row for row in contents if row["source"]["view"] == "after")
        assert before["content"]["regions"][0]["bbox"] == [35, 25, 30, 20]
        assert before["content"]["regions"][0]["region_id"] == "region-learned-click-one"
        assert before["content"]["recognition_text"] == "Search"
        assert before["content"]["regions"][0]["learning_evidence"]["candidate"] == observation["candidate"]
        assert after["content"]["regions"] == []


def test_derived_target_requires_exact_sha_and_rejects_malformed(observation_scene):
    from app.learning_memory.learned_target_regions import derive_target_region
    _, event, observation = observation_scene
    assert derive_target_region(event, observation, "b" * 64) is None
    broken = deepcopy(observation)
    broken["candidate"]["bbox"]["x"] = -1
    with pytest.raises(ValueError, match="geometry"):
        derive_target_region(event, broken, observation["frame"]["sha256"])


def test_old_empty_interface_recovers_read_only_and_corruption_fails(observation_scene, monkeypatch):
    from app.learning_memory.graph_source import logical_id
    from app.learning_memory.learned_target_regions import read_learned_target_regions
    original = MemoryWorkspace.import_observation
    def legacy_import(self, *args, **kwargs):
        kwargs.update(regions=[], recognition_text="")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(MemoryWorkspace, "import_observation", legacy_import)
    _, root, _, _, observation = record_learning_click(observation_scene)
    with MemoryWorkspace(root) as library:
        graph = library.load_graph_revision(logical_id("search-records"))
        node = next(row for row in graph["graph"]["nodes"] if row["memory_identity"]["state_key"] == "home")
        pin = node["interface_reference"]
        before = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file() and path.name != ".owner.lock"}
        result = read_learned_target_regions(library, pin["interface_id"], pin["version_id"])
        assert result["status"] == "derived_learning_evidence"
        assert result["regions"][0]["bbox"] == [35, 25, 30, 20]
        assert result["evidence"][0]["candidate"] == observation["candidate"]
        assert before == {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file() and path.name != ".owner.lock"}
        archive = next((root / "desktop-review/learning-observations").glob("*.json"))
        archive.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="archive_changed"):
            read_learned_target_regions(library, pin["interface_id"], pin["version_id"])
