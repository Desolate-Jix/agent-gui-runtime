"""新记忆入口复用原生内容服务；不构造旧 inbox、确认链或执行器。"""
from copy import deepcopy
import errno
import os
from pathlib import Path
from threading import RLock
from time import monotonic, sleep

from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.interface_content import InterfaceContentService, _origin_region, _content_binding
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade, _write_immutable
from .content_source import make_source, image_path, descriptor_path


_LOCK_WAIT_SECONDS = 1.0
_LOCK_POLL_SECONDS = 0.02


class MemoryWorkspace:
    pinned_interface_references = True

    def load_workflow_program(self, workflow_id, program_id=None):
        from .workflow_program import WorkflowProgramService
        with self._guard:
            self._require_open()
            return WorkflowProgramService(self).load(workflow_id, program_id)

    def read_workflow_image_options(self, workflow_id, project_snapshot_id, target_node_id):
        from .image_verification_sources import read_workflow_image_options
        with self._guard:
            self._require_open()
            return read_workflow_image_options(self, workflow_id, project_snapshot_id, target_node_id)

    def save_workflow_program(self, workflow_id, expected_sha256, definition, request_id, *, target_recipes=None):
        from .workflow_program import WorkflowProgramService
        with self._guard:
            self._require_open()
            return WorkflowProgramService(self).save(workflow_id, expected_sha256, definition, request_id,
                                                     target_recipes=target_recipes)

    def read_workflow_learning(self, session_dir):
        from .workflow_learning_review import read_workflow_learning
        with self._guard:
            self._require_open()
            return read_workflow_learning(self, session_dir)

    def read_target_edit_context(self, reference, *, proposed_recipe=None):
        from .workflow_target_editor_service import read_target_edit_context
        with self._guard:
            self._require_open()
            return read_target_edit_context(self, reference, proposed_recipe=proposed_recipe)

    def read_interface_target_links(self, interface_id, version_id=None):
        from .interface_target_links import read_interface_target_links
        with self._guard:
            self._require_open()
            return read_interface_target_links(self, interface_id, version_id)

    def read_learned_target_regions(self, interface_id, version_id=None):
        from .learned_target_regions import read_learned_target_regions
        with self._guard:
            self._require_open()
            return read_learned_target_regions(self, interface_id, version_id)

    def propose_target_box_edit(self, reference, action, strategies, strategy_index, bbox, *,
                                proposed_recipe=None, preview_inputs=None, preview_outputs=None):
        from .workflow_target_editor_service import propose_target_box_edit
        with self._guard:
            self._require_open()
            return propose_target_box_edit(self, reference, action, strategies, strategy_index, bbox,
                proposed_recipe=proposed_recipe, preview_inputs=preview_inputs,
                preview_outputs=preview_outputs)

    def propose_target_edit(self, reference, action, strategies, *, proposed_recipe=None,
                            preview_inputs=None, preview_outputs=None):
        from .workflow_target_editor_service import propose_target_edit
        with self._guard:
            self._require_open()
            return propose_target_edit(self, reference, action, strategies,
                proposed_recipe=proposed_recipe, preview_inputs=preview_inputs,
                preview_outputs=preview_outputs)

    def start_workflow_trial(self, session_dir, workflow_id, program_id, start_step_id, inputs, request_id, *, execution_strategy="learned"):
        from .workflow_trial import TrialService
        with self._guard:
            self._require_open()
            return TrialService(self, session_dir).start(workflow_id, program_id, start_step_id, inputs, request_id,
                                                        execution_strategy=execution_strategy)

    def prepare_workflow_trial(self, session_dir, run_id, request_id, observations=None, vision_capabilities=None):
        from .workflow_trial import TrialService
        with self._guard:
            self._require_open()
            return TrialService(self, session_dir).prepare(run_id, request_id, observations,
                                                         vision_capabilities=vision_capabilities)

    def status_workflow_trial(self, session_dir, run_id):
        from .workflow_trial import TrialService
        with self._guard:
            self._require_open()
            return TrialService(self, session_dir).status(run_id)

    def cancel_workflow_trial(self, session_dir, run_id, request_id):
        from .workflow_trial import TrialService
        with self._guard:
            self._require_open()
            return TrialService(self, session_dir).cancel(run_id, request_id)

    # 仅复用存储、锁和编辑方法，不继承旧服务的执行/发布入口。
    _artifact_file = NativeReviewFacade._artifact_file
    def _acquire_owner_lock(self):
        handle = self._lock_handle
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = monotonic() + _LOCK_WAIT_SECONDS
        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError as error:
                busy = error.errno in ({errno.EACCES} if os.name == "nt" else {errno.EACCES, errno.EAGAIN})
                if not busy:
                    raise
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise DesktopReviewError("另一桌面审核宿主已占用该工作区；记忆库短事务等待超时") from error
                sleep(min(_LOCK_POLL_SECONDS, remaining))
    _require_open = NativeReviewFacade._require_open
    close = NativeReviewFacade.close
    list_interface_contents = NativeReviewFacade.list_interface_contents
    list_interface_contents_for_reference = NativeReviewFacade.list_interface_contents_for_reference
    load_interface_content = NativeReviewFacade.load_interface_content
    load_interface_content_evidence = NativeReviewFacade.load_interface_content_evidence
    save_interface_content = NativeReviewFacade.save_interface_content
    get_interface_memory = NativeReviewFacade.get_interface_memory
    request_interface_relearning = NativeReviewFacade.request_interface_relearning
    list_interface_relearning = NativeReviewFacade.list_interface_relearning
    read_interface_relearning = NativeReviewFacade.read_interface_relearning
    compare_interface_relearning = NativeReviewFacade.compare_interface_relearning
    adopt_interface_relearning = NativeReviewFacade.adopt_interface_relearning
    reject_interface_relearning = NativeReviewFacade.reject_interface_relearning
    withdraw_interface_relearning = NativeReviewFacade.withdraw_interface_relearning
    list_interface_relearning_feedback = NativeReviewFacade.list_interface_relearning_feedback
    get_interface_relearning_feedback = NativeReviewFacade.get_interface_relearning_feedback
    submit_interface_relearning_candidate = NativeReviewFacade.submit_interface_relearning_candidate
    preview_interface_content_deletion = NativeReviewFacade.preview_interface_content_deletion
    delete_interface_contents = NativeReviewFacade.delete_interface_contents
    load_graph_revision = NativeReviewFacade.load_graph_revision
    create_workflow_graph = NativeReviewFacade.create_workflow_graph
    attach_interface_to_workflow = NativeReviewFacade.attach_interface_to_workflow
    attach_interfaces_to_workflow = NativeReviewFacade.attach_interfaces_to_workflow
    list_workflow_projects = NativeReviewFacade.list_workflow_projects
    list_workflow_project_summaries = NativeReviewFacade.list_workflow_project_summaries

    def list_source_candidates(self, interface_id):
        from .source_candidates import list_candidates
        with self._guard:
            self._require_open()
            return list_candidates(self, interface_id)

    def preview_source_candidate(self, interface_id, candidate):
        from .source_candidates import preview_candidate
        with self._guard:
            self._require_open()
            return preview_candidate(self, interface_id, candidate)

    def adopt_source_candidate(self, interface_id, candidate, expected_revision, expected_sha256, request_id):
        from .source_candidates import adopt_candidate
        with self._guard:
            self._require_open()
            return adopt_candidate(self, interface_id, candidate, expected_revision, expected_sha256, request_id)

    def save_control_template(self, request):
        from .templates import validate_request, save_template
        with self._guard:
            self._require_open()
            validate_request(request)
            if request["action"] != "save":
                raise ValueError("template editor save requires action=save")
            return save_template(self, request)

    def list_control_templates(self, interface_id, version_id):
        from .templates import validate_request, list_templates
        with self._guard:
            self._require_open()
            request = {"action": "list", "interface_id": interface_id, "version_id": version_id}
            validate_request(request)
            return list_templates(self, request)

    def load_control_template_evidence(self, template_id):
        from .templates import template_evidence
        with self._guard:
            self._require_open()
            return template_evidence(self, template_id)

    def list_workflow_graphs(self):
        """目录只校验图头与图文件；完整来源和图片在打开项目时校验。"""
        import hashlib
        from app.core.json_snapshot import read_json_snapshot
        from app.desktop_review.graph_revision import GraphRevisionService
        with self._guard:
            self._require_open()
            graphs = GraphRevisionService(self)
            rows = []
            for path in sorted(graphs._root.glob("*/draft_head.json")):
                identity = graphs._validate_logical_id(path.parent.name)
                head = read_json_snapshot(path)
                if head.get("logical_workflow_id") != identity:
                    raise ValueError("memory catalog identity mismatch")
                version = graphs._revision_path(identity, head["content_sha256"])
                raw = version.read_bytes()
                if hashlib.sha256(raw).hexdigest() != head["snapshot_sha256"]:
                    raise ValueError("memory catalog graph file digest mismatch")
                snapshot = read_json_snapshot(version)
                if (snapshot["logical_workflow_id"] != identity or snapshot["revision"] != head["revision"]
                        or snapshot["content_sha256"] != head["content_sha256"]
                        or graphs._content_sha(snapshot) != head["content_sha256"]):
                    raise ValueError("memory catalog graph content mismatch")
                rows.append({"logical_workflow_id": identity, "title": snapshot["graph"]["workflow"]["goal"],
                    "task_id": snapshot["source_refs"]["task_id"], "revision": snapshot["revision"],
                    "content_sha256": snapshot["content_sha256"], "node_count": len(snapshot["graph"]["nodes"]),
                    "detail_verified": False})
            return rows

    def load_workflow_project(self, workflow_id):
        from app.desktop_review.workflow_project import WorkflowProjectService
        with self._guard:
            self._require_open()
            return WorkflowProjectService(self).load(workflow_id)

    def save_workflow_project(self, workflow_id, expected_sha256, changes, idempotency_key):
        from app.desktop_review.workflow_project import WorkflowProjectService
        with self._guard:
            self._require_open()
            return WorkflowProjectService(self).save(workflow_id, expected_sha256, changes, idempotency_key)

    def adopt_project_interface(self, workflow_id, node_id, expected_sha256):
        from uuid import uuid4
        from .graph_source import adopt_interface
        with self._guard:
            self._require_open()
            adopt_interface(self, workflow_id, node_id, expected_sha256=expected_sha256,
                            request_id="adopt-" + uuid4().hex)
            return self.load_workflow_project(workflow_id)

    def detach_interface_from_workflow(self, workflow_id, interface_id, version_id,
                                       expected_revision, expected_sha256, idempotency_key):
        kwargs = dict(workflow_id=workflow_id, interface_id=interface_id, version_id=version_id,
                      expected_revision=expected_revision, expected_sha256=expected_sha256,
                      idempotency_key=idempotency_key)
        with self._guard:
            self._require_open()
            current = self.load_graph_revision(kwargs["workflow_id"])
            if current["revision"] != kwargs["expected_revision"] or current["content_sha256"] != kwargs["expected_sha256"]:
                raise ValueError("stale workflow membership revision")
            if current["source_refs"].get("kind") == "execution_memory":
                for node in current["graph"]["nodes"]:
                    reference = node.get("interface_reference", {})
                    if (node.get("memory_identity") and reference.get("interface_id") == kwargs["interface_id"]
                            and reference.get("version_id") == kwargs["version_id"]):
                        from .graph_source import exclude_state
                        return exclude_state(self, current, node["node_id"], kwargs["idempotency_key"])
            return NativeReviewFacade.detach_interface_from_workflow(self, **kwargs)

    def __init__(self, artifact_root):
        self._artifact_root = Path(artifact_root).resolve()
        self._workspace_root = self._artifact_root / "desktop-review"
        self._guard = RLock()
        self._closed = False
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self._lock_handle = (self._workspace_root / ".owner.lock").open("a+b")
        try:
            self._acquire_owner_lock()
        except Exception:
            self._lock_handle.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()

    def import_observation(self, events, learning_id, event_id, view, *, regions=None,
                           recognition_text="", application_binding=None):
        with self._guard:
            self._require_open()
            if view not in {"before", "after"}:
                raise ValueError("view must be before or after")
            event = events._event(learning_id, event_id)
            record = events._review(learning_id, event_id)
            if record is None:
                raise ValueError("review this event before importing its interface identity")
            events._verify_review_frames(event, record["review"])
            source, descriptor = make_source("memory-local", event, record, view)
            contents = InterfaceContentService(self)
            existing = contents.find_execution_identity(source["task_id"], source["interface_key"], source["state_key"])
            if existing is not None:
                # 未明确采用的重学来源只留在原事件中，不复制一份无人引用的图片。
                return {**existing, "import_status": "existing_identity_not_overwritten",
                        "incoming_source_ref": source["source_ref"], "incoming_source_archived": False,
                        "source_replacement_supported": True,
                        "next": "Use learning_adopt_source with the exact event/review digests, current interface revision, and explicit NEW regions/OCR. Ordinary save never replaces image provenance."}
            content = {"meaning": record["review"][view]["meaning"],
                       "recognition_text": recognition_text,
                       "regions": [_origin_region(item, recognition_text) for item in (regions or [])],
                       "application_binding": _content_binding(application_binding)}
            # 图片按摘要仅存一份；所有修订和流程共享，不复制到每个节点。
            frame = Path(event[view]["image_path"])
            if not frame.is_absolute():
                frame = events.session / frame
            raw = frame.read_bytes()
            import hashlib
            if hashlib.sha256(raw).hexdigest() != source["screenshot_sha256"]:
                raise ValueError("observation changed during import")
            _write_immutable(self._artifact_root / image_path(source), raw)
            _write_immutable(self._artifact_root / descriptor_path(source), canonical_json_bytes(descriptor) + b"\n")
            return contents.import_execution_memory(source, content)

    def adopt_observation(self, events, learning_id, request, request_id):
        with self._guard:
            self._require_open()
            event = events._event(learning_id, request["event_id"])
            record = events._review(learning_id, request["event_id"])
            from .receipt_adapter import content_hash
            if content_hash(event) != request["event_sha256"]:
                raise ValueError("event digest changed; reread learning_event")
            if record is None or record["review_sha256"] != request["review_sha256"]:
                raise ValueError("review digest changed; reread learning_event")
            events._verify_review_frames(event, record["review"])
            source, descriptor = make_source("memory-local", event, record, request["view"])
            contents = InterfaceContentService(self)
            current = contents.find_execution_identity(source["task_id"], source["interface_key"], source["state_key"])
            if current is None or current["interface_id"] != request["interface_id"]:
                raise ValueError("new evidence must have the same explicit interface/state identity")
            # 新图必须明确提供新框；空列表表示清空，不能悄悄沿用旧坐标。
            regions = [_origin_region(item, request["recognition_text"]) for item in request["regions"]]
            frame = Path(event[request["view"]]["image_path"])
            raw = (frame if frame.is_absolute() else events.session / frame).read_bytes()
            import hashlib
            if hashlib.sha256(raw).hexdigest() != source["screenshot_sha256"]:
                raise ValueError("observation changed during adoption")
            _write_immutable(self._artifact_root / image_path(source), raw)
            _write_immutable(self._artifact_root / descriptor_path(source), canonical_json_bytes(descriptor) + b"\n")
            value = contents.adopt_execution_source(request["interface_id"], source, regions,
                request["recognition_text"], request["expected_revision"], request["expected_sha256"],
                "source-" + content_hash([events.session.name, request_id]))
            return {**value, "source_adoption_status": "adopted", "workflow_references_updated": False,
                    "next": "Existing workflows still pin their old versions. Explicitly adopt the new version in each desired project."}

    def read_memory(self, interface_id, version_id=None):
        with self._guard:
            self._require_open()
            result = InterfaceContentService(self).memory("memory-local", interface_id, version_id)
            # 历史框留在编辑/证据层；Agent 的默认读取只给语义线索，不给旧点击坐标。
            content = result["content"]
            content["regions"] = [{key: deepcopy(region[key]) for key in
                ("region_id", "name", "kind", "meaning", "recognition_text") if key in region}
                for region in content["regions"]]
            result.update(locator_scope="semantic_hints_only", current_grounding_required=True,
                          next="Use the existing instant executor with a fresh observation; never replay stored coordinates.")
            return result
