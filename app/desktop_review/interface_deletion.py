"""界面库删除事务：仅隐藏库入口，保留所有历史和流程引用。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from .graph_revision import GraphRevisionService
from .interface_content import InterfaceContentService, _interface_id, _is_sha256
from .workspace import DesktopReviewError


class InterfaceDeletionService:
    """复用 façade 锁，整批验证后只原子提交一次墓碑注册表。"""

    def __init__(self, facade):
        self.facade = facade
        self.contents = InterfaceContentService(facade)

    def preview(self, interfaces: list[dict]) -> dict:
        registry, selected = self._validate(interfaces)
        references = self._references(selected)
        return self._result(registry, selected, references, deleted=False)

    def delete(self, interfaces: list[dict]) -> dict:
        registry, selected = self._validate(interfaces)
        references = self._references(selected)
        result = self._result(registry, selected, references, deleted=True)
        tombstones = registry.setdefault("tombstones", {})
        now = datetime.now(timezone.utc).isoformat()
        changed = False
        for item in selected:
            identity = item["interface_id"]
            if identity not in tombstones:
                tombstones[identity] = {key: item[key] for key in ("interface_id", "revision", "content_sha256")}
                tombstones[identity]["deleted_at"] = now
                changed = True
        if changed:
            self.contents._write_registry(registry)
        return result

    def _validate(self, interfaces: list[dict]) -> tuple[dict, list[dict]]:
        if not isinstance(interfaces, list) or not interfaces:
            raise DesktopReviewError("interface_deletion_selection_invalid: 请先选择界面")
        registry, selected, seen, failures = self.contents._registry(), [], set(), []
        for request in interfaces:
            if not isinstance(request, dict) or set(request) != {"interface_id", "expected_revision", "expected_sha256"}:
                raise DesktopReviewError("interface_deletion_selection_invalid: 删除请求字段无效")
            identity = _interface_id(request["interface_id"])
            if identity in seen:
                raise DesktopReviewError("interface_deletion_selection_duplicate: 请勿重复选择同一界面")
            seen.add(identity)
            if (type(request["expected_revision"]) is not int or request["expected_revision"] < 1
                    or not _is_sha256(request["expected_sha256"])):
                raise DesktopReviewError("interface_deletion_selection_invalid: 删除版本无效")
            if identity not in registry["interface_ids"]:
                failures.append(f"{identity}：界面不存在")
                continue
            current = self.contents.load(identity, None)
            if (current["revision"] != request["expected_revision"]
                    or current["content_sha256"] != request["expected_sha256"]):
                failures.append(f"{current['content']['meaning']}：stale_revision，请刷新并选择最新版本")
            selected.append(current)
        if failures:
            raise DesktopReviewError("整批未删除：" + "；".join(failures))
        return registry, selected

    def _references(self, selected: list[dict]) -> dict[str, list[dict]]:
        result = {item["interface_id"]: [] for item in selected}
        graphs = GraphRevisionService(self.facade)
        if not graphs._root.exists():
            return result
        evidence = {item["interface_id"]: self.contents.evidence(item["interface_id"], item["version_id"])
                    for item in selected}
        for directory in sorted(graphs._root.iterdir()):
            if not directory.is_dir():
                continue
            current = graphs.load(directory.name, None)
            title = current["graph"]["workflow"].get("goal", directory.name)
            matches: dict[str, list[int]] = {}
            snapshot = current
            while True:
                for item in selected:
                    identity = item["interface_id"]
                    for node in snapshot["graph"].get("nodes", []):
                        ref = node.get("interface_reference") or {}
                        source = node.get("evidence") or {}
                        explicit = ref.get("interface_id") == identity
                        indirect = (node.get("external_interface_id") == item["source"]["external_interface_id"]
                            and source.get("source_screenshot_path") == evidence[identity]["image_path"]
                            and source.get("source_screenshot_sha256") == evidence[identity]["sha256"])
                        if explicit or indirect:
                            matches.setdefault(identity, []).append(snapshot["revision"])
                            break
                if snapshot["parent_sha256"] is None:
                    break
                snapshot = graphs._load_revision(directory.name, snapshot["parent_sha256"])
            for identity, revisions in matches.items():
                result[identity].append({"logical_workflow_id": directory.name, "title": title,
                    "revisions": sorted(revisions), "current_reference": current["revision"] in revisions})
        return result

    @staticmethod
    def _result(registry: dict, selected: list[dict], references: dict, *, deleted: bool) -> dict:
        items = []
        for value in selected:
            identity = value["interface_id"]
            already_deleted = identity in registry.get("tombstones", {})
            items.append({"interface_id": identity, "meaning": value["content"]["meaning"],
                "status": "already_deleted" if already_deleted else ("deleted" if deleted else "ready"),
                "references": deepcopy(references[identity])})
        return {"contract_version": "desktop_interface_deletion_v1", "items": items,
            "deleted_count": sum(item["status"] == "deleted" for item in items),
            "already_deleted_count": sum(item["status"] == "already_deleted" for item in items),
            "history_preserved": True, "screenshots_preserved": True, "graph_references_preserved": True}
