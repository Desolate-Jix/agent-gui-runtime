"""R3 精确人审：只接受已保存外部草稿，所有确认均由服务端重算。"""
from __future__ import annotations

from app.agent.action_semantics import REVIEWED_SINGLE_STEP_ACTIONS
from app.agent.scroll_parameters import SCROLL_SEMANTIC_ACTION
from app.agent.text_parameters import TEXT_SEMANTIC_ACTION

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
from app.agent import workflow_versions
from app.agent.native_identity import normalize_windows_executable_path
from app.agent.reviewed_workflow_compiler import (
    _granular_review_revision,
    compile_reviewed_workflow_asset_v2,
)
from app.learn.application_identity import normalize_application_identity
from app.learn.interface_workflow_review import (
    INTERFACE_NODE_HUMAN_REVIEW_CONFIRMATION_CONTRACT,
    build_interface_node_review_revision,
    save_interface_workflow_review_candidate,
)

from .external_mapping import (
    ExternalMappingError, canonical_json_bytes, normalize_step_relationships,
)


_CONTRACT = "desktop_exact_review_v1"
_GRAPH_CONTRACT = "desktop_graph_exact_review_v1"
_SAFE = REVIEWED_SINGLE_STEP_ACTIONS | {SCROLL_SEMANTIC_ACTION, TEXT_SEMANTIC_ACTION}
_DECLARATIONS = {"observe", "safe_stop"}
_GRANULAR = {
    "region": "interface_target_control_human_review_confirmation_v1",
    "control": "interface_target_control_human_review_confirmation_v1",
    "action": "interface_action_candidate_human_review_confirmation_v1",
    "edge": "interface_workflow_edge_human_review_confirmation_v1",
}
_PREPARATION_FIELDS = (
    "contract_version",
    "preparation_key",
    "review_ref",
    "task_id",
    "batch_id",
    "source_ref",
    "workspace_revision",
    "application_identity",
    "options",
    "staging_path",
    "staging_sha256",
    "dependencies",
    "subjects",
)
_GRAPH_PREPARATION_FIELDS = (
    "contract_version", "preparation_key", "review_ref", "task_id", "batch_id",
    "source_ref", "logical_workflow_id", "graph_revision", "graph_sha256",
    "application_identity", "options", "staging_path", "staging_sha256",
    "dependencies", "subjects",
)
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ExactReviewError(RuntimeError):
    pass


class ExactReviewService:
    def __init__(self, facade) -> None:
        self.facade = facade
        self.project_root = facade._artifact_root.resolve()
        self.root = self.project_root / "desktop-review" / "exact-reviews"

    def prepare(
        self,
        task_id: str,
        batch_id: str,
        expected_revision: int,
        application_binding: Any,
        step_relationships: Any = None,
        stop_interface_ids: Any = None,
    ) -> dict:
        snapshot = self._current(task_id, batch_id, expected_revision)
        binding = _binding(application_binding)
        batch = snapshot["batch"]
        options = {
            "application_binding": binding,
            "step_relationships": _relations(batch, step_relationships),
            "stop_interface_ids": _stops(batch, stop_interface_ids),
        }
        key = _preparation_key(snapshot, options)
        record_dir = self.root / key
        index = record_dir / "current.json"
        if index.is_file():
            record = _json_object(index, "exact review current record")
            self._validate_current(record, snapshot, record_dir)
            return self._view(record)

        review = self._staging_review(snapshot, options, key)
        try:
            result = save_interface_workflow_review_candidate(
                review,
                project_root=self.project_root,
                out_dir=Path("desktop-review") / "exact-staging" / key,
                create_only=True,
            )
        except (OSError, TypeError, ValueError) as error:
            raise ExactReviewError(f"exact review staging save failed: {error}") from error
        staging_path = _result_relative_path(self.project_root, result, "staging")
        staged_path = _project_path(self.project_root, staging_path, "staging_path")
        staged = _json_object(staged_path, "staged workflow")
        dependencies = _dependencies(self.project_root, staged, staged_path)
        review_ref = _review_ref(key, staged_path, dependencies)
        subjects = _subjects(staged, batch, options["stop_interface_ids"])
        record = {
            "contract_version": _CONTRACT,
            "preparation_key": key,
            "review_ref": review_ref,
            "task_id": task_id,
            "batch_id": batch_id,
            "source_ref": snapshot["source_ref"],
            "workspace_revision": snapshot["revision"],
            "application_identity": binding,
            "options": options,
            "staging_path": staging_path,
            "staging_sha256": _sha(staged_path.read_bytes()),
            "dependencies": dependencies,
            "subjects": subjects,
            "approval_revision": 0,
            "confirmed_subject_ids": [],
            "compile_receipt_id": None,
            "status": "prepared",
        }
        _immutable(record_dir / "prepared.json", record)
        _atomic(index, record)
        return self._view(record)

    def prepare_graph(self, logical_workflow_id: str, expected_revision: int, expected_graph_sha256: str, application_binding: Any, stop_node_ids: Any = None) -> dict:
        snapshot = self._graph_current(logical_workflow_id, expected_revision, expected_graph_sha256)
        if snapshot["source_refs"].get("kind") == "recorded_actions":
            raise ExactReviewError("纯动作图可查看、编辑并供 Agent 读取，但旧批次发布审核暂不支持")
        if snapshot["source_refs"].get("kind") == "interface_composition" or snapshot["source_refs"].get("interface_composition"):
            raise ExactReviewError("引用成员不等于已学习的跳转；请先独立审核界面，当前组合草稿不支持直接发布或执行。")
        binding = _binding(application_binding)
        stops = _graph_stops(snapshot["graph"], stop_node_ids)
        options = {"application_binding": binding, "stop_node_ids": stops}
        key = _graph_preparation_key(snapshot, options)
        record_dir, index = self.root / key, self.root / key / "current.json"
        if index.is_file():
            record = _json_object(index, "graph exact review current record")
            self._validate_current(record, snapshot, record_dir)
            return self._view(record)
        review = self._graph_staging_review(snapshot, options, key)
        try:
            result = save_interface_workflow_review_candidate(
                review, project_root=self.project_root,
                out_dir=Path("desktop-review") / "exact-staging" / key,
                create_only=True,
            )
        except (OSError, TypeError, ValueError) as error:
            raise ExactReviewError(f"graph exact review staging save failed: {error}") from error
        staging_path = _result_relative_path(self.project_root, result, "graph staging")
        staged_path = _project_path(self.project_root, staging_path, "staging_path")
        staged = _json_object(staged_path, "graph staged workflow")
        dependencies = _dependencies(self.project_root, staged, staged_path)
        review_ref = _review_ref(key, staged_path, dependencies)
        from .graph_exact_projection import graph_subjects
        refs = snapshot["source_refs"]
        record = {
            "contract_version": _GRAPH_CONTRACT, "preparation_key": key,
            "review_ref": review_ref, "task_id": refs["task_id"], "batch_id": refs["batch_id"],
            "source_ref": refs["batch_sha256"], "logical_workflow_id": snapshot["logical_workflow_id"],
            "graph_revision": snapshot["revision"], "graph_sha256": snapshot["content_sha256"],
            "application_identity": binding, "options": options,
            "staging_path": staging_path, "staging_sha256": _sha(staged_path.read_bytes()),
            "dependencies": dependencies, "subjects": graph_subjects(staged, stops),
            "approval_revision": 0, "confirmed_subject_ids": [],
            "compile_receipt_id": None, "status": "prepared",
        }
        _immutable(record_dir / "prepared.json", record)
        _atomic(index, record)
        return self._view(record)

    def record(self, review_ref: str, expected: int, ids: Any) -> dict:
        record, record_dir = self._record(review_ref)
        snapshot = self._source_for_record(record)
        self._validate_current(record, snapshot, record_dir)
        if expected != record["approval_revision"]:
            raise ExactReviewError("stale exact-review approval revision")
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
            raise ExactReviewError("confirmed_subject_ids must be strings")
        wanted = sorted(set(ids))
        valid = {item["subject_id"] for item in record["subjects"]}
        if set(wanted) - valid:
            raise ExactReviewError("unknown exact-review subject")
        if wanted == record["confirmed_subject_ids"]:
            return self._view(record)
        updated = self._next_approval_record(record, record_dir, wanted)
        _atomic(record_dir / "current.json", updated)
        return self._view(updated)

    def compile(self, review_ref: str, expected: int) -> dict:
        record, record_dir = self._record(review_ref)
        snapshot = self._source_for_record(record)
        self._validate_current(record, snapshot, record_dir)
        if expected != record["approval_revision"]:
            raise ExactReviewError("stale exact-review approval revision")
        missing = [
            item
            for item in record["subjects"]
            if item["subject_id"] not in record["confirmed_subject_ids"]
        ]
        if missing:
            return {
                **self._view(record),
                "status": "blocked",
                "blocked_reasons": [
                    {
                        "code": "human_review_incomplete",
                        "message": "explicit subjects remain unconfirmed",
                    }
                ],
                "compile_receipt_id": None,
            }

        existing_id = record.get("compile_receipt_id")
        if existing_id is not None:
            receipt = self._receipt(existing_id, record_dir)
            self._validate_receipt(receipt, record, record_dir)
            store = ReviewedWorkflowAssetStore(project_root=self.project_root)
            registry = store.registry()
            active_sha = registry.get("active_by_asset", {}).get(receipt["asset_id"])
            already_published = active_sha == receipt["asset_sha256"]
            if record.get("contract_version") == _GRAPH_CONTRACT:
                version = workflow_versions.make_record(
                    {key: record[key] for key in workflow_versions.PUBLICATION_FIELDS},
                    receipt["asset_id"], receipt["asset_sha256"],
                )
                # 对象已存在不代表当前图的审核版本已登记。
                already_published = version["version_id"] in registry.get("workflow_versions", {})
            if (
                not already_published
                and registry.get("registry_revision") != receipt["expected_registry_revision"]
            ):
                receipt = deepcopy(receipt)
                receipt["expected_registry_revision"] = registry["registry_revision"]
                receipt["receipt_id"] = _receipt_id(receipt)
                _immutable(
                    record_dir / f"receipt-{receipt['receipt_id']}.json", receipt
                )
                updated = deepcopy(record)
                updated["compile_receipt_id"] = receipt["receipt_id"]
                _atomic(record_dir / "current.json", updated)
                record = updated
                existing_id = receipt["receipt_id"]
            return {
                **self._view(record),
                "status": "compiled",
                "blocked_reasons": [],
                "compile_receipt_id": existing_id,
                **({"asset_id": receipt["asset_id"], "asset_sha256": receipt["asset_sha256"]}
                   if record.get("contract_version") == _GRAPH_CONTRACT else {}),
            }

        final_path = self._materialize_final(record)
        final = _json_object(final_path, "final workflow")
        final_sha = _sha(final_path.read_bytes())
        compiled = self._compile_source(final_path, final_sha)
        if compiled.get("status") != "compiled":
            return {
                **self._view(record),
                "status": "blocked",
                "blocked_reasons": deepcopy(compiled.get("blocked_reasons", [])),
                "compile_receipt_id": None,
            }
        asset = compiled.get("asset")
        if not isinstance(asset, dict):
            raise ExactReviewError("compiler returned an invalid asset")
        registry = ReviewedWorkflowAssetStore(project_root=self.project_root).registry()
        receipt = {
            "review_ref": review_ref,
            "approval_revision": expected,
            "final_path": _relative(self.project_root, final_path, "final_path"),
            "final_sha256": final_sha,
            "final_dependencies": _dependencies(self.project_root, final, final_path),
            "asset": asset,
            "asset_id": asset.get("asset_id"),
            "asset_sha256": _sha(canonical_json_bytes(asset)),
            "expected_registry_revision": registry.get("registry_revision"),
        }
        if record.get("contract_version") == _GRAPH_CONTRACT:
            receipt.update({
                "source_contract_version": _GRAPH_CONTRACT,
                "logical_workflow_id": record["logical_workflow_id"],
                "graph_revision": record["graph_revision"],
                "graph_sha256": record["graph_sha256"],
                "task_id": record["task_id"], "batch_id": record["batch_id"],
                "source_ref": record["source_ref"],
            })
        receipt["receipt_id"] = _receipt_id(receipt)
        _immutable(record_dir / f"receipt-{receipt['receipt_id']}.json", receipt)
        updated = deepcopy(record)
        updated["compile_receipt_id"] = receipt["receipt_id"]
        updated["status"] = "compiled"
        _atomic(record_dir / "current.json", updated)
        return {
            **self._view(updated),
            "status": "compiled",
            "blocked_reasons": [],
            "compile_receipt_id": receipt["receipt_id"],
            **({"asset_id": receipt["asset_id"], "asset_sha256": receipt["asset_sha256"]}
               if record.get("contract_version") == _GRAPH_CONTRACT else {}),
        }

    def publish(self, receipt_id: str) -> dict:
        if not isinstance(receipt_id, str) or not _HEX_SHA256.fullmatch(receipt_id):
            raise ExactReviewError("compile receipt id is invalid")
        receipt, record_dir = self._find_receipt(receipt_id)
        review_ref = receipt.get("review_ref")
        if not isinstance(review_ref, str):
            raise ExactReviewError("compile receipt review identity is invalid")
        record, current_dir = self._record(review_ref)
        if current_dir != record_dir:
            raise ExactReviewError("compile receipt record identity is invalid")
        snapshot = self._source_for_record(record)
        self._validate_current(record, snapshot, record_dir)
        if (
            record.get("compile_receipt_id") != receipt_id
            or record["approval_revision"] != receipt.get("approval_revision")
        ):
            raise ExactReviewError("compile receipt is stale")
        self._validate_receipt(receipt, record, record_dir)
        try:
            if record.get("contract_version") == _GRAPH_CONTRACT:
                return ReviewedWorkflowAssetStore(project_root=self.project_root).publish_version(
                    receipt["asset"],
                    publication={
                        "logical_workflow_id": record["logical_workflow_id"],
                        "graph_revision": record["graph_revision"],
                        "graph_sha256": record["graph_sha256"],
                        "review_ref": record["review_ref"],
                        "approval_revision": record["approval_revision"],
                    },
                    expected_registry_revision=receipt["expected_registry_revision"],
                )
            return ReviewedWorkflowAssetStore(project_root=self.project_root).publish(
                asset=receipt["asset"],
                expected_registry_revision=receipt["expected_registry_revision"],
            )
        except (OSError, TypeError, ValueError) as error:
            raise ExactReviewError(f"reviewed asset publish failed: {error}") from error

    def assets(self) -> list[dict]:
        store = ReviewedWorkflowAssetStore(project_root=self.project_root)
        registry = store.registry()
        result = []
        for asset_id in sorted(registry.get("active_by_asset", {})):
            asset = store.load_active(asset_id)
            app = asset.get("application") if isinstance(asset.get("application"), dict) else {}
            kind = app.get("kind")
            application = (
                app.get("executable")
                if kind == "native"
                else app.get("canonical_origin")
            )
            fallback_name = (
                app.get("product_identity") or app.get("executable")
                if kind == "native"
                else app.get("canonical_domain") or app.get("canonical_origin")
            )
            display_name = fallback_name
            try:
                source_identity = _verified_asset_source_identity(
                    self.project_root, asset, app
                )
            except ExactReviewError:
                source_identity = None
            if source_identity is not None:
                display_name = source_identity.get("display_name") or fallback_name
            row = {
                    "asset_id": asset_id,
                    "content_sha256": _sha(canonical_json_bytes(asset)),
                    "application": str(application or ""),
                    "display_name": str(display_name or asset_id),
                }
            # 仅暴露 registry 中真实绑定该资产 hash 的发布版本；不从名称推断。
            versions = []
            asset_sha = row["content_sha256"]
            for version in registry.get("workflow_versions", {}).values():
                if not isinstance(version, dict):
                    continue
                if version.get("asset_id") != asset_id or version.get("asset_sha256") != asset_sha:
                    continue
                versions.append({key: version[key] for key in (
                    "version_id", "logical_workflow_id", "graph_revision", "graph_sha256",
                    "asset_id", "asset_sha256", "review_ref", "approval_revision",
                )})
            if versions:
                row["published_graph_versions"] = sorted(versions, key=lambda item: item["version_id"])
            result.append(row)
        return result

    def _current(self, task: Any, batch: Any, expected: Any) -> dict:
        if not isinstance(task, str) or not isinstance(batch, str):
            raise ExactReviewError("exact review task or batch identity is invalid")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
            raise ExactReviewError("saved workspace revision is required and current")
        original = self.facade._load_source_batch(task, batch)
        from .external_mapping import source_ref_for_batch

        current = self.facade._load_current(task, batch, source_ref_for_batch(original))
        if current is None or current["revision"] != expected:
            raise ExactReviewError("saved workspace revision is required and current")
        return current

    def _source_for_record(self, record: dict) -> dict:
        contract = record.get("contract_version")
        if contract == _CONTRACT:
            return self._current(
                record.get("task_id"), record.get("batch_id"),
                record.get("workspace_revision"),
            )
        if contract == _GRAPH_CONTRACT:
            return self._graph_current(
                record.get("logical_workflow_id"), record.get("graph_revision"),
                record.get("graph_sha256"),
            )
        raise ExactReviewError("exact review record contract is invalid")

    def _graph_current(self, logical_workflow_id: Any, expected_revision: Any, expected_sha256: Any) -> dict:
        if (
            not isinstance(logical_workflow_id, str)
            or isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 1
            or not isinstance(expected_sha256, str)
            or not _HEX_SHA256.fullmatch(expected_sha256)
        ):
            raise ExactReviewError("graph exact review source identity is invalid")
        from .graph_revision import GraphRevisionService

        try:
            current = GraphRevisionService(self.facade).load(logical_workflow_id, None)
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            raise ExactReviewError(f"graph exact review source could not be loaded: {error}") from error
        if (
            current.get("revision") != expected_revision
            or current.get("content_sha256") != expected_sha256
        ):
            raise ExactReviewError("graph exact review source or revision changed")
        return current

    def _record(self, review_ref: str) -> tuple[dict, Path]:
        if not isinstance(review_ref, str) or not _HEX_SHA256.fullmatch(review_ref):
            raise ExactReviewError("review_ref is invalid")
        for path in sorted(self.root.glob("*/current.json")):
            record = _json_object(path, "exact review current record")
            if record.get("review_ref") == review_ref:
                return record, path.parent
        raise ExactReviewError("review_ref not found")

    def inspect_published_version(self, publication: dict) -> dict:
        """复核已发布历史版本的封存来源，不改变当前图、审批或注册表。"""
        from .graph_revision import GraphRevisionService

        graph = GraphRevisionService(self.facade).load(
            publication["logical_workflow_id"], publication["graph_revision"],
        )
        current, record_dir = self._record(publication["review_ref"])
        approval = _json_object(
            record_dir / f"approval-{publication['approval_revision']}.json",
            "published approval record",
        )
        if approval.get("contract_version") != _GRAPH_CONTRACT or any(
            approval.get(key) != publication[key] for key in workflow_versions.PUBLICATION_FIELDS
        ):
            raise ExactReviewError("published version approval identity changed")
        self._validate_graph_current(approval, graph, record_dir, verify_only=True)
        if set(approval["confirmed_subject_ids"]) != {item["subject_id"] for item in approval["subjects"]}:
            raise ExactReviewError("published version does not have complete historical approval")
        found = False
        for path in sorted(record_dir.glob("receipt-*.json")):
            receipt = _json_object(path, "published compile receipt")
            if receipt.get("approval_revision") != approval["approval_revision"]:
                continue
            if any(receipt.get(key) != publication[key] for key in workflow_versions.PUBLICATION_FIELDS):
                raise ExactReviewError("published version compile binding changed")
            record = {**approval, "compile_receipt_id": receipt.get("receipt_id"), "status": "compiled"}
            self._validate_receipt(receipt, record, record_dir, verify_only=True)
            if (path.name != f"receipt-{receipt['receipt_id']}.json"
                    or receipt["asset_id"] != publication["asset_id"]
                    or receipt["asset_sha256"] != publication["asset_sha256"]
                    or _canonical(receipt["asset"]) != _canonical(publication["asset"])):
                raise ExactReviewError("published version asset differs from its verified compile receipt")
            found = True
        if not found:
            raise ExactReviewError("published version compile receipt is missing")
        return {"graph_snapshot": graph, "application_identity": deepcopy(approval["application_identity"]),
                "approval_current": current.get("approval_revision") == publication["approval_revision"]}

    def _find_receipt(self, receipt_id: str) -> tuple[dict, Path]:
        matches = list(self.root.glob(f"*/receipt-{receipt_id}.json"))
        if len(matches) != 1:
            raise ExactReviewError("compile receipt not found")
        return _json_object(matches[0], "compile receipt"), matches[0].parent

    def _receipt(self, receipt_id: Any, record_dir: Path) -> dict:
        if not isinstance(receipt_id, str) or not _HEX_SHA256.fullmatch(receipt_id):
            raise ExactReviewError("compile receipt id is invalid")
        path = record_dir / f"receipt-{receipt_id}.json"
        if not path.is_file():
            raise ExactReviewError("compile receipt not found")
        return _json_object(path, "compile receipt")

    def _next_approval_record(
        self, record: dict, record_dir: Path, wanted: list[str]
    ) -> dict:
        next_revision = record["approval_revision"] + 1
        path = record_dir / f"approval-{next_revision}.json"
        if path.exists():
            orphan = _json_object(path, "orphan exact review approval record")
            fields = _preparation_fields(record)
            same_preparation = all(
                _canonical(orphan.get(key)) == _canonical(record.get(key))
                for key in fields
            )
            recorded_at = orphan.get("recorded_at")
            if not (
                same_preparation
                and orphan.get("approval_revision") == next_revision
                and orphan.get("confirmed_subject_ids") == wanted
                and orphan.get("reviewer_role") == "local_human_reviewer"
                and isinstance(recorded_at, str)
                and bool(recorded_at.strip())
                and orphan.get("compile_receipt_id") is None
                and orphan.get("status") == "prepared"
            ):
                raise ExactReviewError("conflicting orphan exact review approval record")
            return orphan
        updated = deepcopy(record)
        updated["approval_revision"] = next_revision
        updated["confirmed_subject_ids"] = wanted
        updated["compile_receipt_id"] = None
        updated["status"] = "prepared"
        updated["reviewer_role"] = "local_human_reviewer"
        updated["recorded_at"] = datetime.now(timezone.utc).isoformat()
        _immutable(path, updated)
        return updated

    def _validate_current(self, record: dict, snapshot: dict, record_dir: Path) -> None:
        if record.get("contract_version") == _GRAPH_CONTRACT:
            self._validate_graph_current(record, snapshot, record_dir)
            return
        if record.get("contract_version") != _CONTRACT:
            raise ExactReviewError("exact review record contract is invalid")
        for key in ("task_id", "batch_id", "source_ref"):
            if record.get(key) != snapshot.get(key):
                raise ExactReviewError("exact review source or revision changed")
        if record.get("workspace_revision") != snapshot.get("revision"):
            raise ExactReviewError("exact review source or revision changed")
        prepared = _json_object(record_dir / "prepared.json", "exact review preparation seal")
        if any(_canonical(prepared.get(key)) != _canonical(record.get(key)) for key in _PREPARATION_FIELDS):
            raise ExactReviewError("exact review preparation record changed")

        options = record.get("options")
        if not isinstance(options, dict) or set(options) != {
            "application_binding", "step_relationships", "stop_interface_ids"
        }:
            raise ExactReviewError("exact review preparation options are invalid")
        binding = options.get("application_binding")
        if not isinstance(binding, dict) or binding != record.get("application_identity"):
            raise ExactReviewError("exact review preparation application identity changed")
        try:
            normalized = normalize_application_identity(binding)
        except (TypeError, ValueError) as error:
            raise ExactReviewError("exact review preparation application identity is invalid") from error
        if normalized != binding or binding.get("identity_status") != "resolved":
            raise ExactReviewError("exact review preparation application identity is invalid")
        try:
            relationships = _relations(snapshot["batch"], options.get("step_relationships"))
            stops = _stops(snapshot["batch"], options.get("stop_interface_ids"))
        except ExactReviewError as error:
            raise ExactReviewError(f"exact review preparation options are invalid: {error}") from error
        canonical_options = {
            "application_binding": binding,
            "step_relationships": relationships,
            "stop_interface_ids": stops,
        }
        if canonical_options != options:
            raise ExactReviewError("exact review preparation options are not canonical")
        key = _preparation_key(snapshot, canonical_options)
        if record.get("preparation_key") != key or record_dir.name != key:
            legacy_key = _preparation_key(snapshot, canonical_options, legacy_projection=True)
            if key != legacy_key and record.get("preparation_key") == legacy_key and record_dir.name == legacy_key:
                raise ExactReviewError(
                    "exact review projection upgrade required; prepare a new review and confirm its subjects"
                )
            raise ExactReviewError("exact review preparation key changed")

        staged_path = _project_path(
            self.project_root, record.get("staging_path"), "staging_path"
        )
        staged = _json_object(staged_path, "staged workflow")
        actual_dependencies = _dependencies(self.project_root, staged, staged_path)
        if (
            _sha(staged_path.read_bytes()) != record.get("staging_sha256")
            or actual_dependencies != record.get("dependencies")
        ):
            raise ExactReviewError("exact review staging dependencies changed")
        if _review_ref(key, staged_path, actual_dependencies) != record.get("review_ref"):
            raise ExactReviewError("exact review reference changed")
        expected_subjects = _subjects(staged, snapshot["batch"], stops)
        if _canonical(expected_subjects) != _canonical(record.get("subjects")):
            raise ExactReviewError("exact review subject closure changed")
        confirmed = record.get("confirmed_subject_ids")
        valid_ids = {item["subject_id"] for item in expected_subjects}
        if (
            not isinstance(confirmed, list)
            or any(not isinstance(item, str) for item in confirmed)
            or confirmed != sorted(set(confirmed))
            or set(confirmed) - valid_ids
        ):
            raise ExactReviewError("exact review recorded subjects are invalid")
        if isinstance(record.get("approval_revision"), bool) or not isinstance(record.get("approval_revision"), int) or record["approval_revision"] < 0:
            raise ExactReviewError("exact review approval revision is invalid")
        approval_revision = record["approval_revision"]
        if approval_revision == 0:
            if confirmed or record.get("reviewer_role") is not None or record.get("recorded_at") is not None:
                raise ExactReviewError("exact review confirmation has no approval record")
        else:
            approval = _json_object(
                record_dir / f"approval-{approval_revision}.json",
                "exact review approval record",
            )
            if any(
                _canonical(approval.get(key)) != _canonical(record.get(key))
                for key in (*_preparation_fields(record), "approval_revision", "confirmed_subject_ids", "reviewer_role", "recorded_at")
            ):
                raise ExactReviewError("exact review approval record changed")
            if approval.get("status") != "prepared" or approval.get("compile_receipt_id") is not None:
                raise ExactReviewError("exact review approval record is invalid")
        self._revalidate_staging(snapshot, canonical_options, key, staged_path)

    def _validate_graph_current(self, record: dict, snapshot: dict, record_dir: Path, *, verify_only: bool = False) -> None:
        refs = snapshot.get("source_refs")
        if not isinstance(refs, dict):
            raise ExactReviewError("graph exact review source references are invalid")
        expected_identity = {
            "task_id": refs.get("task_id"), "batch_id": refs.get("batch_id"),
            "source_ref": refs.get("batch_sha256"),
            "logical_workflow_id": snapshot.get("logical_workflow_id"),
            "graph_revision": snapshot.get("revision"),
            "graph_sha256": snapshot.get("content_sha256"),
        }
        if any(record.get(key) != value for key, value in expected_identity.items()):
            raise ExactReviewError("graph exact review source or revision changed")
        if "workspace_revision" in record:
            raise ExactReviewError("graph exact review record contains legacy revision identity")
        prepared = _json_object(record_dir / "prepared.json", "graph exact review preparation seal")
        if any(
            _canonical(prepared.get(key)) != _canonical(record.get(key))
            for key in _GRAPH_PREPARATION_FIELDS
        ):
            raise ExactReviewError("graph exact review preparation record changed")

        options = record.get("options")
        if not isinstance(options, dict) or set(options) != {"application_binding", "stop_node_ids"}:
            raise ExactReviewError("graph exact review preparation options are invalid")
        binding = options.get("application_binding")
        if not isinstance(binding, dict) or binding != record.get("application_identity"):
            raise ExactReviewError("graph exact review preparation application identity changed")
        try:
            normalized = normalize_application_identity(binding)
            stops = _graph_stops(snapshot["graph"], options.get("stop_node_ids"))
        except (TypeError, ValueError, ExactReviewError) as error:
            raise ExactReviewError(f"graph exact review preparation options are invalid: {error}") from error
        if normalized != binding or binding.get("identity_status") != "resolved":
            raise ExactReviewError("graph exact review preparation application identity is invalid")
        canonical_options = {"application_binding": binding, "stop_node_ids": stops}
        if canonical_options != options:
            raise ExactReviewError("graph exact review preparation options are not canonical")
        key = _graph_preparation_key(snapshot, canonical_options)
        if record.get("preparation_key") != key or record_dir.name != key:
            raise ExactReviewError("graph exact review preparation key changed")

        staged_path = _project_path(self.project_root, record.get("staging_path"), "staging_path")
        staged = _json_object(staged_path, "graph staged workflow")
        actual_dependencies = _dependencies(self.project_root, staged, staged_path)
        if (
            _sha(staged_path.read_bytes()) != record.get("staging_sha256")
            or actual_dependencies != record.get("dependencies")
        ):
            raise ExactReviewError("graph exact review staging dependencies changed")
        if _review_ref(key, staged_path, actual_dependencies) != record.get("review_ref"):
            raise ExactReviewError("graph exact review reference changed")
        from .graph_exact_projection import graph_subjects

        expected_subjects = graph_subjects(staged, stops)
        if _canonical(expected_subjects) != _canonical(record.get("subjects")):
            raise ExactReviewError("graph exact review subject closure changed")
        confirmed = record.get("confirmed_subject_ids")
        valid_ids = {item["subject_id"] for item in expected_subjects}
        if (
            not isinstance(confirmed, list)
            or any(not isinstance(item, str) for item in confirmed)
            or confirmed != sorted(set(confirmed))
            or set(confirmed) - valid_ids
        ):
            raise ExactReviewError("graph exact review recorded subjects are invalid")
        approval_revision = record.get("approval_revision")
        if isinstance(approval_revision, bool) or not isinstance(approval_revision, int) or approval_revision < 0:
            raise ExactReviewError("graph exact review approval revision is invalid")
        if approval_revision == 0:
            if confirmed or record.get("reviewer_role") is not None or record.get("recorded_at") is not None:
                raise ExactReviewError("graph exact review confirmation has no approval record")
        else:
            approval = _json_object(record_dir / f"approval-{approval_revision}.json", "graph exact review approval record")
            if any(
                _canonical(approval.get(field)) != _canonical(record.get(field))
                for field in (*_GRAPH_PREPARATION_FIELDS, "approval_revision", "confirmed_subject_ids", "reviewer_role", "recorded_at")
            ):
                raise ExactReviewError("graph exact review approval record changed")
            if approval.get("status") != "prepared" or approval.get("compile_receipt_id") is not None:
                raise ExactReviewError("graph exact review approval record is invalid")
        self._graph_revalidate_staging(snapshot, canonical_options, key, staged_path, verify_only=verify_only)

    def _validate_receipt(self, receipt: dict, record: dict, record_dir: Path, *, verify_only: bool = False) -> None:
        expected_id = record.get("compile_receipt_id")
        if receipt.get("receipt_id") != expected_id:
            raise ExactReviewError("compile receipt identity changed")
        if receipt.get("review_ref") != record.get("review_ref"):
            raise ExactReviewError("compile receipt review source changed")
        if receipt.get("approval_revision") != record.get("approval_revision"):
            raise ExactReviewError("compile receipt approval source changed")
        graph_fields = (
            "logical_workflow_id", "graph_revision", "graph_sha256",
            "task_id", "batch_id", "source_ref",
        )
        if record.get("contract_version") == _GRAPH_CONTRACT:
            if receipt.get("source_contract_version") != _GRAPH_CONTRACT or any(
                receipt.get(key) != record.get(key) for key in graph_fields
            ):
                raise ExactReviewError("compile receipt graph source changed")
        elif "source_contract_version" in receipt or any(key in receipt for key in graph_fields):
            raise ExactReviewError("legacy compile receipt contains graph source identity")
        final_path = _project_path(self.project_root, receipt.get("final_path"), "final_path")
        final = _json_object(final_path, "final workflow")
        final_sha = _sha(final_path.read_bytes())
        final_dependencies = _dependencies(self.project_root, final, final_path)
        if final_sha != receipt.get("final_sha256") or final_dependencies != receipt.get("final_dependencies"):
            raise ExactReviewError("compile receipt final dependency changed")
        expected_final_path = self._materialize_final(record, verify_only=verify_only)
        if expected_final_path != final_path:
            raise ExactReviewError("compile receipt final source identity changed")
        compiled = self._compile_source(final_path, final_sha)
        if compiled.get("status") != "compiled" or not isinstance(compiled.get("asset"), dict):
            codes = ",".join(
                str(item.get("code"))
                for item in compiled.get("blocked_reasons", [])
                if isinstance(item, dict)
            )
            raise ExactReviewError(f"compile receipt source no longer compiles: {codes}")
        actual_asset = compiled["asset"]
        actual_asset_sha = _sha(canonical_json_bytes(actual_asset))
        if (
            _canonical(receipt.get("asset")) != _canonical(actual_asset)
            or receipt.get("asset_id") != actual_asset.get("asset_id")
            or receipt.get("asset_sha256") != actual_asset_sha
        ):
            raise ExactReviewError("compile receipt asset identity changed")
        revision = receipt.get("expected_registry_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ExactReviewError("compile receipt registry revision is invalid")
        if _receipt_id(receipt) != receipt.get("receipt_id"):
            raise ExactReviewError("compile receipt identity hash changed")
        expected_path = record_dir / f"receipt-{receipt['receipt_id']}.json"
        if not expected_path.is_file():
            raise ExactReviewError("compile receipt file identity changed")

    def _staging_review(self, snapshot: dict, options: dict, key: str) -> dict:
        review = self._review(snapshot, options["application_binding"], options)
        review["workflow"]["workflow_id"] = "exact_stage_" + key[:40]
        return review

    def _graph_staging_review(self, snapshot: dict, options: dict, key: str) -> dict:
        from .graph_exact_projection import project_graph_exact_review

        try:
            review = project_graph_exact_review(
                snapshot, options["application_binding"], options["stop_node_ids"],
                _SAFE, _DECLARATIONS,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ExactReviewError(f"graph exact review projection failed: {error}") from error
        review["workflow"]["workflow_id"] = "exact_stage_" + key[:40]
        return review

    def _revalidate_staging(self, snapshot: dict, options: dict, key: str, expected: Path) -> None:
        try:
            result = save_interface_workflow_review_candidate(
                self._staging_review(snapshot, options, key),
                project_root=self.project_root,
                out_dir=Path("desktop-review") / "exact-staging" / key,
                create_only=True,
            )
        except (OSError, TypeError, ValueError) as error:
            raise ExactReviewError(f"exact review staging seal validation failed: {error}") from error
        actual = _project_path(
            self.project_root,
            _result_relative_path(self.project_root, result, "staging"),
            "staging_path",
        )
        if actual != expected:
            raise ExactReviewError("exact review staging saver identity changed")

    def _graph_revalidate_staging(self, snapshot: dict, options: dict, key: str, expected: Path, *, verify_only: bool = False) -> None:
        try:
            result = save_interface_workflow_review_candidate(
                self._graph_staging_review(snapshot, options, key),
                project_root=self.project_root,
                out_dir=Path("desktop-review") / "exact-staging" / key,
                create_only=True,
                verify_only=verify_only,
            )
        except (OSError, TypeError, ValueError) as error:
            raise ExactReviewError(f"graph exact review staging seal validation failed: {error}") from error
        actual = _project_path(
            self.project_root,
            _result_relative_path(self.project_root, result, "graph staging"),
            "staging_path",
        )
        if actual != expected:
            raise ExactReviewError("graph exact review staging saver identity changed")

    def _materialize_final(self, record: dict, *, verify_only: bool = False) -> Path:
        staged_path = _project_path(self.project_root, record.get("staging_path"), "staging_path")
        final = _approve(_json_object(staged_path, "staged workflow"), record)
        final["workflow"]["workflow_id"] = _final_workflow_id(
            record["review_ref"], record["approval_revision"]
        )
        try:
            result = save_interface_workflow_review_candidate(
                final, project_root=self.project_root, create_only=True, verify_only=verify_only
            )
        except (OSError, TypeError, ValueError) as error:
            raise ExactReviewError(f"exact review final seal validation failed: {error}") from error
        relative = _result_relative_path(self.project_root, result, "final")
        return _project_path(self.project_root, relative, "final_path")

    def _compile_source(self, path: Path, expected_sha: str) -> dict:
        try:
            return compile_reviewed_workflow_asset_v2(
                project_root=self.project_root,
                source_workflow_path=_relative(self.project_root, path, "source_workflow_path"),
                expected_source_workflow_sha256=expected_sha,
            )
        except (OSError, TypeError, ValueError) as error:
            raise ExactReviewError(f"exact review compiler failed: {error}") from error

    def _view(self, record: dict) -> dict:
        confirmed = set(record["confirmed_subject_ids"])
        subjects = [
            {**deepcopy(item), "confirmed": item["subject_id"] in confirmed}
            for item in record["subjects"]
        ]
        staged_path = _project_path(self.project_root, record.get("staging_path"), "staging_path")
        staged = _json_object(staged_path, "staged workflow")
        unsafe = [
            edge
            for edge in staged.get("edges", [])
            if isinstance(edge, dict)
            and str(edge.get("action_type") or "").casefold() not in _SAFE
        ]
        blockers = [
            {
                "code": "unsafe_or_unknown_action",
                "message": "external action remains non-compilable",
            }
            for _ in unsafe
        ]
        view = {
            "contract_version": record["contract_version"],
            "review_ref": record["review_ref"],
            "task_id": record["task_id"],
            "batch_id": record["batch_id"],
            "source_ref": record["source_ref"],
            "approval_revision": record["approval_revision"],
            "application_identity": deepcopy(record["application_identity"]),
            "subjects": subjects,
            "blocked_reasons": blockers,
            "status": record["status"],
            "compile_receipt_id": record["compile_receipt_id"],
        }
        if record.get("contract_version") == _GRAPH_CONTRACT:
            view.update({
                "logical_workflow_id": record["logical_workflow_id"],
                "graph_revision": record["graph_revision"],
                "graph_sha256": record["graph_sha256"],
            })
        else:
            view["workspace_revision"] = record["workspace_revision"]
        return view

    def _review(self, snapshot: dict, binding: dict, options: dict) -> dict:
        from .external_mapping import build_external_workflow_review

        review = build_external_workflow_review(
            batch=snapshot["batch"],
            task_id=snapshot["task_id"],
            source_ref=snapshot["source_ref"],
            revision=snapshot["revision"],
            step_relationships=options["step_relationships"],
        )
        review["workflow"]["application_identity"] = binding
        node_by_external_id = {
            node["external_interface_id"]: node for node in review["nodes"]
        }
        steps = {item["step_id"]: item for item in snapshot["batch"]["steps"]}
        declaration_ids = {
            item["step_id"]
            for item in snapshot["batch"]["steps"]
            if str(item.get("action_type") or "").strip().casefold() in _DECLARATIONS
        }
        for node in review["nodes"]:
            for region in node.get("regions", []):
                if isinstance(region, dict):
                    region.update(
                        {
                            "review_status": "needs_human_review",
                            "reviewed_by_human": False,
                            "display_only": True,
                            "artifact_is_authorization": False,
                            "execute_binding_enabled": False,
                        }
                    )
            node["action_candidates"] = [
                item
                for item in node.get("action_candidates", [])
                if item.get("external_step_id") not in declaration_ids
            ]
            if node["external_interface_id"] in options["stop_interface_ids"]:
                node["review_status"] = "needs_learning"

        executable_edges = []
        for edge in review["edges"]:
            step = steps[edge["external_step_id"]]
            action = str(step["action_type"]).strip().casefold()
            if action in _DECLARATIONS:
                continue
            if action in _SAFE:
                edge.update(
                    {
                        "action_type": action,
                        "semantic_action": action,
                        "external_stop_boundary": False,
                    }
                )
                source = node_by_external_id[step["start_state"]]
                for candidate in source["action_candidates"]:
                    if candidate["external_step_id"] == step["step_id"]:
                        edge["action_template_id"] = candidate["action_template_id"]
                        candidate.update(
                            {
                                "semantic_action": action,
                                "action_type": action,
                                "target_node_id": edge["target_node_id"],
                            }
                        )
                        break
            else:
                edge.setdefault("blocked_reason", "unsafe_or_unknown_external_action")
            executable_edges.append(edge)
        review["edges"] = executable_edges
        review["workflow"]["edge_ids"] = [item["edge_id"] for item in executable_edges]
        return review


def _binding(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ExactReviewError("application binding must be object")
    kind = value.get("kind")
    allowed = {
        "native": {"kind", "display_name", "executable_identity", "product_name"},
        "web": {"kind", "display_name", "canonical_origin"},
    }
    if (
        kind not in allowed
        or set(value) - allowed[kind]
        or not isinstance(value.get("display_name"), str)
        or not value["display_name"].strip()
    ):
        raise ExactReviewError("application binding fields are invalid")
    if kind == "native" and (
        not isinstance(value.get("executable_identity"), str)
        or not value["executable_identity"].strip()
    ):
        raise ExactReviewError("native executable_identity is required")
    if kind == "web" and (
        not isinstance(value.get("canonical_origin"), str)
        or not value["canonical_origin"].strip()
    ):
        raise ExactReviewError("web canonical_origin is required")
    try:
        identity = normalize_application_identity(value)
    except (TypeError, ValueError) as error:
        raise ExactReviewError("application binding is invalid") from error
    if identity.get("identity_status") != "resolved":
        raise ExactReviewError("application binding is unresolved")
    return identity


def _subjects(review: dict, batch: dict, stops: list[str]) -> list[dict]:
    identity = review["workflow"]["application_identity"]
    out = [_subject("application", "application", identity.get("display_name") or "Application", identity)]
    for node in review["nodes"]:
        node_id = node["node_id"]
        node_label = node.get("display_name") or node.get("external_interface_id") or node_id
        out.append(_subject(f"node:{node_id}", "node", node_label, node))
        out.append(_subject(f"observation:{node_id}", "observation", f"{node_label} observation", node.get("evidence", {})))
        for key, kind, id_key in (
            ("regions", "region", "region_id"),
            ("controls", "control", "control_id"),
            ("action_candidates", "action", "action_template_id"),
        ):
            for item in node.get(key, []):
                item_id = item[id_key]
                label = (
                    item.get("display_name")
                    or item.get("semantic_name")
                    or item.get("name")
                    or item.get("label")
                    or item.get("external_step_id")
                    or item_id
                )
                out.append(_subject(f"{kind}:{node_id}:{item_id}", kind, label, item))
    for edge in review["edges"]:
        label = edge.get("display_name") or edge.get("external_step_id") or edge["edge_id"]
        out.append(_subject(f"edge:{edge['edge_id']}", "edge", label, edge))
    for step in batch["steps"]:
        out.append(_subject(f"step:{step['step_id']}", "step", step["step_id"], step))
    for relationship in batch["relationships"]:
        out.append(
            _subject(
                f"relationship:{relationship['relationship_id']}",
                "relationship",
                relationship.get("meaning") or relationship["relationship_id"],
                relationship,
            )
        )
    for interface_id in stops:
        out.append(
            _subject(
                f"stop:{interface_id}",
                "stop",
                interface_id,
                {"interface_id": interface_id},
            )
        )
    return out


def _subject(subject_id: str, kind: str, label: Any, content: Any) -> dict:
    return {
        "subject_id": subject_id,
        "kind": kind,
        "label": str(label),
        "content": deepcopy(content),
        "confirmed": False,
    }


def _relations(batch: dict, value: Any) -> dict:
    try:
        return normalize_step_relationships(batch, value)
    except ExternalMappingError as error:
        raise ExactReviewError(str(error)) from error


def _stops(batch: dict, value: Any) -> list[str]:
    if value is None:
        value = []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ExactReviewError("stop_interface_ids must be an array")
    known = {item["interface_id"] for item in batch["interfaces"]}
    if set(value) - known:
        raise ExactReviewError("unknown stop interface")
    return sorted(set(value))


def _graph_stops(graph: dict, value: Any) -> list[str]:
    if value is None:
        value = []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ExactReviewError("stop_node_ids must be an array")
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        raise ExactReviewError("graph nodes are invalid")
    known = {
        item.get("node_id") for item in nodes
        if isinstance(item, dict) and isinstance(item.get("node_id"), str)
    }
    if set(value) - known:
        raise ExactReviewError("unknown stop node")
    return sorted(set(value))


def _approve(review: dict, record: dict) -> dict:
    approved = deepcopy(review)
    confirmed = set(record["confirmed_subject_ids"])
    for node in approved["nodes"]:
        node_id = node["node_id"]
        for key, kind, id_key in (
            ("regions", "region", "region_id"),
            ("controls", "control", "control_id"),
            ("action_candidates", "action", "action_template_id"),
        ):
            for item in node.get(key, []):
                if f"{kind}:{node_id}:{item[id_key]}" in confirmed:
                    item.update(
                        {
                            "review_status": "human_approved",
                            "reviewed_by_human": True,
                            "human_review_confirmation": {
                                "contract_version": _GRANULAR[kind],
                                "revision": _granular_review_revision(item),
                            },
                        }
                    )
        if f"node:{node_id}" in confirmed and node.get("review_status") != "needs_learning":
            node.update({"review_status": "human_approved", "reviewed_by_human": True})
    for edge in approved["edges"]:
        if f"edge:{edge['edge_id']}" in confirmed:
            edge.update(
                {
                    "review_status": "human_approved",
                    "reviewed_by_human": True,
                    "human_review_confirmation": {
                        "contract_version": _GRANULAR["edge"],
                        "revision": _granular_review_revision(edge),
                    },
                }
            )
    for node in approved["nodes"]:
        if node.get("reviewed_by_human"):
            node["human_review_confirmation"] = {
                "contract_version": INTERFACE_NODE_HUMAN_REVIEW_CONFIRMATION_CONTRACT,
                "revision": build_interface_node_review_revision(
                    approved, node_id=node["node_id"]
                ),
            }
    return approved


def _dependencies(root: Path, review: dict, workflow_path: Path) -> dict[str, str]:
    references = {workflow_path}
    _collect_paths(root, review, references)
    result = {}
    for path in references:
        relative = _relative(root, path, "workflow dependency")
        if not path.is_file():
            raise ExactReviewError(f"workflow dependency is missing: {relative}")
        try:
            result[relative] = _sha(path.read_bytes())
        except OSError as error:
            raise ExactReviewError(f"workflow dependency could not be read: {relative}") from error
    return dict(sorted(result.items()))


def _collect_paths(
    root: Path, value: Any, result: set[Path], location: tuple[str, ...] = ()
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                location == ("workflow", "application_identity")
                and value.get("kind") == "native"
                and key == "executable_path"
            ):
                # 程序身份不是项目文件依赖；仅豁免这一已知字段，仍要求绝对路径。
                if normalize_windows_executable_path(item) is None:
                    raise ExactReviewError("native executable_path must be an absolute Windows path")
                continue
            if isinstance(key, str) and key.endswith("_path"):
                if item in (None, ""):
                    continue
                if not isinstance(item, str):
                    raise ExactReviewError(f"workflow dependency path is invalid: {key}")
                result.add(_project_path(root, item, key))
            elif isinstance(key, str) and key.endswith("_paths"):
                if not isinstance(item, list) or any(not isinstance(path, str) for path in item):
                    raise ExactReviewError(f"workflow dependency paths are invalid: {key}")
                for path in item:
                    result.add(_project_path(root, path, key))
            else:
                _collect_paths(root, item, result, (*location, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_paths(root, item, result, (*location, str(index)))


def _verified_asset_source_identity(
    root: Path, asset: dict, compiled_application: dict
) -> dict | None:
    lineage = asset.get("source_review_lineage")
    if not isinstance(lineage, dict):
        return None
    source_path = _project_path(
        root, lineage.get("source_workflow_path"), "asset source_workflow_path"
    )
    expected_sha = lineage.get("source_workflow_sha256")
    if not isinstance(expected_sha, str) or _sha(source_path.read_bytes()) != expected_sha:
        raise ExactReviewError("reviewed asset source workflow hash changed")
    review = _json_object(source_path, "reviewed asset source workflow")
    workflow = review.get("workflow")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("application_identity"), dict):
        raise ExactReviewError("reviewed asset source application identity is missing")
    try:
        identity = normalize_application_identity(workflow["application_identity"])
    except (TypeError, ValueError) as error:
        raise ExactReviewError("reviewed asset source application identity is invalid") from error
    if identity.get("identity_status") != "resolved" or identity.get("kind") != compiled_application.get("kind"):
        raise ExactReviewError("reviewed asset source application identity changed")
    if identity["kind"] == "native":
        matches = (
            identity.get("executable_identity") == compiled_application.get("executable")
            and identity.get("product_identity") == compiled_application.get("product_identity")
        )
    else:
        matches = (
            identity.get("canonical_origin") == compiled_application.get("canonical_origin")
            and identity.get("canonical_domain") == compiled_application.get("canonical_domain")
        )
    if not matches:
        raise ExactReviewError("reviewed asset compiled application identity changed")
    return identity


def _preparation_key(snapshot: dict, options: dict, *, legacy_projection: bool = False) -> str:
    identity = {
        "task_id": snapshot["task_id"],
        "batch_id": snapshot["batch_id"],
        "source": snapshot["source_ref"],
        "revision": snapshot["revision"],
        "options": options,
    }
    # 只有非空绑定改变投影；无绑定的旧审核保持原身份。
    if not legacy_projection and any(options["step_relationships"].values()):
        identity["projection_contract"] = "external_relationship_projection_v1"
    return _sha(canonical_json_bytes(identity))


def _graph_preparation_key(snapshot: dict, options: dict) -> str:
    refs = snapshot["source_refs"]
    return _sha(
        canonical_json_bytes(
            {
                "contract_version": _GRAPH_CONTRACT,
                "logical_workflow_id": snapshot["logical_workflow_id"],
                "graph_revision": snapshot["revision"],
                "graph_sha256": snapshot["content_sha256"],
                "task_id": refs["task_id"],
                "batch_id": refs["batch_id"],
                "source_ref": refs["batch_sha256"],
                "options": options,
            }
        )
    )


def _preparation_fields(record: dict) -> tuple[str, ...]:
    if record.get("contract_version") == _GRAPH_CONTRACT:
        return _GRAPH_PREPARATION_FIELDS
    return _PREPARATION_FIELDS

def _review_ref(key: str, path: Path, dependencies: dict[str, str]) -> str:
    return _sha(
        canonical_json_bytes(
            {"key": key, "workflow": _sha(path.read_bytes()), "dependencies": dependencies}
        )
    )


def _final_workflow_id(review_ref: str, approval_revision: int) -> str:
    digest = _sha(
        canonical_json_bytes(
            {"review_ref": review_ref, "approval": approval_revision}
        )
    )
    return "exact_final_" + digest[:40]


def _receipt_id(receipt: dict) -> str:
    identity = {
        "review_ref": receipt.get("review_ref"),
        "approval_revision": receipt.get("approval_revision"),
        "final_path": receipt.get("final_path"),
        "final_sha256": receipt.get("final_sha256"),
        "final_dependencies": receipt.get("final_dependencies"),
        "asset_id": receipt.get("asset_id"),
        "asset_sha256": receipt.get("asset_sha256"),
        "expected_registry_revision": receipt.get("expected_registry_revision"),
    }
    if receipt.get("source_contract_version") == _GRAPH_CONTRACT:
        identity.update({
            "source_contract_version": _GRAPH_CONTRACT,
            "logical_workflow_id": receipt.get("logical_workflow_id"),
            "graph_revision": receipt.get("graph_revision"),
            "graph_sha256": receipt.get("graph_sha256"),
            "task_id": receipt.get("task_id"),
            "batch_id": receipt.get("batch_id"),
            "source_ref": receipt.get("source_ref"),
        })
    return _sha(canonical_json_bytes(identity))


def _result_relative_path(root: Path, result: Any, label: str) -> str:
    if not isinstance(result, dict) or not isinstance(result.get("path"), str):
        raise ExactReviewError(f"{label} saver returned an invalid path")
    path = Path(result["path"])
    if not path.is_absolute():
        path = root / path
    return _relative(root, path, f"{label} saver path")


def _project_path(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ExactReviewError(f"{field} must be a project-relative path")
    path = (root / value).resolve(strict=False)
    _relative(root, path, field)
    return path


def _relative(root: Path, path: Path, field: str) -> str:
    try:
        return path.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except (OSError, ValueError) as error:
        raise ExactReviewError(f"{field} resolves outside project root") from error


def _json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ExactReviewError(f"{label} is missing") from error
    except OSError as error:
        raise ExactReviewError(f"{label} could not be read") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExactReviewError(f"{label} is invalid JSON") from error
    if not isinstance(value, dict):
        raise ExactReviewError(f"{label} must be an object")
    return value


def _canonical(value: Any) -> bytes:
    try:
        return canonical_json_bytes(value)
    except (TypeError, ValueError) as error:
        raise ExactReviewError("exact review record contains non-canonical data") from error


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value) + b"\n"
    descriptor, name = tempfile.mkstemp(prefix=".exact-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except OSError as error:
        raise ExactReviewError(f"exact review record write failed: {path.name}") from error
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _immutable(path: Path, value: dict) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ExactReviewError("immutable exact-review record conflict")
        return
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ExactReviewError("immutable exact-review record conflict")
    except OSError as error:
        raise ExactReviewError(f"immutable exact-review record write failed: {path.name}") from error
