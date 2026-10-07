"""单宿主串行学习记录；恢复只补记落盘回执，绝不重新执行命令。"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from .receipt_adapter import RECORDED_KINDS, content_hash, project_receipt, ExecutionReceiptPending
from .projector import project_segment, validate_review, validate_event_review


CONTROL_KINDS = frozenset({"learning_start", "learning_status", "learning_stop", "learning_recover",
                           "learning_event", "learning_review", "learning_projection", "learning_import",
                           "learning_library", "learning_memory", "learning_save_interface", "learning_commit",
                           "learning_project", "learning_reuse", "learning_adopt_source", "learning_template",
                           "learning_feedback", "learning_workflow"})
OFFLINE_CONTROL_KINDS = CONTROL_KINDS - {"learning_start"}
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("learning identifiers must be 1-80 lowercase ASCII letters/digits/dashes/underscores")
    return value


def validate_control(kind, request):
    if kind not in CONTROL_KINDS or not isinstance(request, dict):
        raise ValueError("invalid learning control")
    if kind == "learning_workflow":
        from .workflow_control import validate_request
        return validate_request(request)
    if kind == "learning_feedback":
        from .feedback import validate_request
        return validate_request(request)
    if kind == "learning_template":
        from .templates import validate_request
        if "learning_id" in request:
            _id(request["learning_id"])
        return validate_request(request)
    allowed = {"scope", "title", "project_id"} if kind == "learning_start" else {"learning_id"}
    allowed = allowed | {"learning_event": {"event_id"}, "learning_review": {"review"},
                         "learning_projection": {"event_ids"},
                         "learning_import": {"event_id", "view", "regions", "recognition_text", "application_binding"},
                         "learning_adopt_source": {"event_id", "event_sha256", "review_sha256", "view",
                                                   "interface_id", "expected_revision", "expected_sha256",
                                                   "regions", "recognition_text"},
                         "learning_library": {"query", "offset", "limit"},
                         "learning_memory": {"interface_id", "version_id"},
                         "learning_save_interface": {"interface_id", "expected_revision", "expected_sha256", "changes"},
                         "learning_commit": {"expected_sha256"},
                         "learning_project": {"action", "workflow_id", "snapshot_id", "node_id", "changes", "expected_sha256"},
                         "learning_reuse": {"workflow_id", "snapshot_id", "edge_id", "variables"}
                         }.get(kind, set())
    if set(request) - allowed:
        raise ValueError("unsupported learning fields; allowed: " + ", ".join(sorted(allowed)))
    if kind == "learning_start":
        if request.get("scope") not in {"interface", "workflow"}:
            raise ValueError("learning scope must be interface or workflow")
        title = request.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("learning title must contain 1-200 characters")
        if request["scope"] == "workflow":
            _id(request.get("project_id"))
        elif "project_id" in request:
            raise ValueError("standalone interface recording must not specify a project_id")
    elif "learning_id" in request:
        _id(request["learning_id"])
    if kind == "learning_event":
        _id(request.get("event_id"))
    elif kind == "learning_review":
        validate_review(request.get("review"))
    elif kind == "learning_projection" and "event_ids" in request:
        ids = request["event_ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= 128:
            raise ValueError("event_ids must contain 1-128 unique event IDs")
        for identity in ids:
            _id(identity)
        if len(set(ids)) != len(ids):
            raise ValueError("event_ids must be unique")
    if kind in {"learning_import", "learning_adopt_source"}:
        _id(request.get("event_id"))
        if request.get("view") not in {"before", "after"}:
            raise ValueError("view must be before or after")
        if not isinstance(request.get("regions", []), list) or len(request.get("regions", [])) > 128:
            raise ValueError("regions must be a list of at most 128 entries")
        if not isinstance(request.get("recognition_text", ""), str):
            raise ValueError("recognition_text must be text")
    if kind == "learning_adopt_source":
        if not {"regions", "recognition_text"} <= set(request):
            raise ValueError("adoption requires explicit NEW regions and recognition_text; use [] and '' to clear")
        for field in ("event_sha256", "review_sha256"):
            if not isinstance(request.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", request[field]):
                raise ValueError(field + " must be copied from learning_event")
    if kind in {"learning_memory", "learning_save_interface", "learning_adopt_source"}:
        value = request.get("interface_id")
        if not isinstance(value, str) or not re.fullmatch(r"interface-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value):
            raise ValueError("interface_id must name an existing interface")
    if kind == "learning_memory" and "version_id" in request:
        if not isinstance(request["version_id"], str) or not re.fullmatch(r"interface-version-[0-9a-f]{64}", request["version_id"]):
            raise ValueError("version_id must identify an exact interface version")
    if kind in {"learning_save_interface", "learning_adopt_source"}:
        if type(request.get("expected_revision")) is not int or request["expected_revision"] < 1:
            raise ValueError("expected_revision must be a positive integer")
        if not isinstance(request.get("expected_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", request["expected_sha256"]):
            raise ValueError("expected_sha256 must be the current content digest")
        if kind == "learning_save_interface" and not isinstance(request.get("changes"), dict):
            raise ValueError("changes must be an object")
    if kind == "learning_library":
        if not isinstance(request.get("query", ""), str) or len(request.get("query", "")) > 200:
            raise ValueError("query must contain at most 200 characters")
        for field, default, lower, upper in (("offset", 0, 0, 1000000), ("limit", 20, 1, 100)):
            value = request.get(field, default)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{field} must be between {lower} and {upper}")
    if kind == "learning_project":
        shapes = {"list": set(), "read": {"workflow_id"}, "save": {"workflow_id", "expected_sha256", "changes"},
                  "memory": {"workflow_id", "snapshot_id", "node_id"},
                  "adopt_interface": {"workflow_id", "node_id", "expected_sha256"}}
        action = request.get("action")
        if not isinstance(action, str) or action not in shapes or set(request) - ({"learning_id", "action"} | shapes[action]):
            raise ValueError("learning_project fields do not match action")
        if action in {"save", "adopt_interface"} and not isinstance(request.get("expected_sha256"), str):
            raise ValueError("expected_sha256 is required")
        if action == "save" and not isinstance(request.get("changes"), dict):
            raise ValueError("changes must be an object")
        if action == "adopt_interface" and not isinstance(request.get("node_id"), str):
            raise ValueError("node_id is required")
    if kind == "learning_reuse" or (kind == "learning_project" and request.get("action") != "list"):
        if not isinstance(request.get("workflow_id"), str) or not re.fullmatch(r"workflow-[0-9a-f]{64}", request["workflow_id"]):
            raise ValueError("workflow_id is required")
    if "expected_sha256" in request and request["expected_sha256"] is not None:
        if not isinstance(request["expected_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", request["expected_sha256"]):
            raise ValueError("expected_sha256 must be a SHA-256 digest")
    if kind == "learning_reuse" or "snapshot_id" in request:
        if not isinstance(request.get("snapshot_id"), str) or not re.fullmatch(r"workflow-project-snapshot-[0-9a-f]{64}", request["snapshot_id"]):
            raise ValueError("snapshot_id must name a fixed project snapshot")
    if kind == "learning_reuse":
        if not isinstance(request.get("edge_id"), str) or not isinstance(request.get("variables", {}), dict):
            raise ValueError("edge_id and variables object are required")
    return request


def _now():
    return datetime.now(timezone.utc).isoformat()


class LearningEventStore:
    """存活时由宿主独写，退出后由持有目录锁的桥接补记；结果轮询不写入。"""

    def __init__(self, session_directory):
        self.session = Path(session_directory).resolve()
        self.root = self.session / "learning-memory"
        self.pointer = self.root / "current.json"

    def _state(self):
        state = read_json_snapshot(self.pointer) if self.pointer.is_file() else {"active_id": None, "last_id": None}
        # 段清单是停止状态的依据；指针更新失败不能使已停止的段继续接收动作。
        if state["active_id"] and self._manifest(state["active_id"])["status"] == "stopped":
            state["active_id"] = None
        return state

    def _directory(self, learning_id):
        return self.root / _id(learning_id)

    def _manifest(self, learning_id):
        return read_json_snapshot(self._directory(learning_id) / "manifest.json")

    def _put_once(self, path, value):
        if path.exists():
            if read_json_snapshot(path) != value:
                raise ValueError("learning immutable record conflict: " + path.name)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_snapshot(path, value)

    def snapshot(self, learning_id=None):
        state = self._state()
        identity = learning_id or state["active_id"] or state["last_id"]
        if identity is None:
            return {"recording_enabled": False, "learning_id": None, "status": "disabled"}
        manifest = self._manifest(identity)
        return {**manifest, "recording_enabled": state["active_id"] == identity,
                "graph_generated": bool(manifest.get("graph_reference")), "automatic_retry_allowed": False}

    def status(self, learning_id=None):
        summary = self.snapshot(learning_id)
        identity = summary["learning_id"]
        if identity is None:
            return summary
        directory = self._directory(identity)
        event_ids = {path.stem for path in (directory / "events").glob("*.json")}
        expected = {path.stem for path in (directory / "tickets").glob("*.json")}
        unbound = []
        # 只在显式查询/结束时扫描；预记账失败但原回执已写入也必须计为缺口。
        for path in (self.session / "responses").glob("*.json"):
            response = read_json_snapshot(path)
            ticket = response.get("learning_binding")
            if ticket and ticket.get("learning_id") == identity:
                expected.add(path.stem)
            elif not ticket and response.get("learning_recording_error"):
                # 无法读取活动段时不能猜归属，也不能把这次记录缺口算作完整。
                unbound.append(path.stem)
        pending = sorted(expected - event_ids)
        return {**summary,
                "event_count": len(event_ids), "pending_count": len(pending), "pending_ids": pending[:20],
                "pending_ids_truncated": len(pending) > 20,
                "unbound_recording_error_ids": sorted(unbound)[:20], "unbound_recording_error_count": len(unbound),
                "recording_complete": summary["status"] == "stopped" and not pending and not unbound,
                "automatic_retry_allowed": False}

    def control(self, kind, request, request_id):
        validate_control(kind, request)
        _id(request_id)
        if kind == "learning_workflow":
            from .workspace import MemoryWorkspace
            from .workflow_control import workflow_control
            with MemoryWorkspace(self.session.parent / "memory-library") as library:
                return workflow_control(library, self.session, request, request_id)
        if kind == "learning_template":
            from .workspace import MemoryWorkspace
            from .templates import save_template, list_templates, locate_template
            with MemoryWorkspace(self.session.parent / "memory-library") as library:
                if request["action"] == "save":
                    return save_template(library, request)
                if request["action"] == "list":
                    return list_templates(library, request)
                state = self._state()
                identity = request.get("learning_id") or state["active_id"] or state["last_id"]
                if identity is None:
                    raise ValueError("select the segment containing the current capture event")
                return locate_template(library, self, identity, request)
        if kind in {"learning_library", "learning_memory", "learning_save_interface", "learning_project", "learning_reuse", "learning_feedback"}:
            return self.library_control(kind, request, request_id)
        state = self._state()
        if kind == "learning_start":
            identity = "learning-" + content_hash([self.session.name, request_id])[:32]
            if state["active_id"] not in {None, identity}:
                raise ValueError("stop the active learning segment before starting another")
            directory = self._directory(identity)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "manifest.json"
            if path.exists():
                manifest = read_json_snapshot(path)
                if manifest["start_spec"] != request or manifest["status"] != "recording":
                    raise ValueError("learning start identity already belongs to a different or stopped segment")
            else:
                manifest = {"contract_version": "instant_learning_segment_v1", "learning_id": identity,
                    "session_id": self.session.name, "start_request_id": request_id, "start_spec": request,
                    "started_at": _now(), "status": "recording"}
                if request["scope"] == "workflow":
                    from .workspace import MemoryWorkspace
                    from .graph_source import logical_id
                    from app.desktop_review.graph_revision import GraphRevisionService
                    with MemoryWorkspace(self.session.parent / "memory-library") as library:
                        head = GraphRevisionService(library)._load_head(logical_id(request["project_id"]), required=False)
                        manifest["initial_graph_sha256"] = head["content_sha256"] if head else None
                write_json_snapshot(path, manifest)
            write_json_snapshot(self.pointer, {"active_id": identity, "last_id": identity})
            return self.status(identity)
        identity = request.get("learning_id") or state["active_id"] or state["last_id"]
        if kind == "learning_status":
            return self.status(identity)
        if identity is None:
            raise ValueError("no learning segment selected")
        if kind == "learning_recover":
            return self.recover(identity)
        if kind == "learning_event":
            event = self._event(identity, request["event_id"])
            return {"event": event, "event_sha256": content_hash(event),
                    "current_review": self._review(identity, request["event_id"]),
                    "automatic_retry_allowed": False}
        if kind == "learning_review":
            return self.review(identity, request["review"], request_id)
        if kind == "learning_projection":
            return self.projection(identity, request.get("event_ids"))
        if kind == "learning_commit":
            return self.commit_graph(identity, request.get("expected_sha256"), request_id)
        if kind in {"learning_import", "learning_adopt_source"}:
            from .workspace import MemoryWorkspace
            with MemoryWorkspace(self.session.parent / "memory-library") as library:
                if kind == "learning_adopt_source":
                    return library.adopt_observation(self, identity, request, request_id)
                return library.import_observation(self, identity, request["event_id"], request["view"],
                    regions=request.get("regions"), recognition_text=request.get("recognition_text", ""),
                    application_binding=request.get("application_binding"))
        if state["active_id"] not in {None, identity}:
            raise ValueError("learning_stop must name the active segment")
        manifest = self._manifest(identity)
        if manifest["status"] != "stopped":
            manifest.update(status="stopped", stopped_at=_now())
            write_json_snapshot(self._directory(identity) / "manifest.json", manifest)
        write_json_snapshot(self.pointer, {"active_id": None, "last_id": identity})
        if self.status(identity)["recording_complete"]:
            expected = manifest.get("graph_reference", {}).get("content_sha256", manifest.get("initial_graph_sha256"))
            self.commit_graph(identity, expected, request_id)
        result = self.status(identity)
        if result["recording_complete"] and result["start_spec"]["scope"] == "workflow":
            from .learning_synthesis import LearningSynthesisService
            from .workspace import MemoryWorkspace
            with MemoryWorkspace(self.session.parent / "memory-library") as library:
                result["synthesis"] = LearningSynthesisService(library, self.session).prepare(identity)
        return result

    def commit_graph(self, identity, expected_sha256, request_id):
        from .graph_source import persist_graph
        from .workspace import MemoryWorkspace
        status = self.status(identity)
        if status["pending_count"] or status["unbound_recording_error_count"]:
            raise ValueError("recover missing event records before committing the workflow")
        if status["start_spec"]["scope"] == "interface":
            if expected_sha256 is not None:
                raise ValueError("standalone content commit has no graph digest")
            projection = self.projection(identity)
            references = []
            with MemoryWorkspace(self.session.parent / "memory-library") as library:
                for node in projection["nodes"]:
                    observation = node["observations"][0]
                    content = library.import_observation(self, identity, observation["event_id"], observation["view"])
                    references.append({"node_id": node["node_id"], **{key: content[key] for key in
                        ("interface_id", "version_id", "content_sha256", "import_status")}})
            manifest = self._manifest(identity)
            manifest["interface_references"] = references
            manifest["content_unresolved"] = projection["unresolved"]
            write_json_snapshot(self._directory(identity) / "manifest.json", manifest)
            return {"interface_references": references, "unresolved": projection["unresolved"],
                    "graph_generated": False, "input_executed": False,
                    "task_effect_verified": None, "automatic_retry_allowed": False}
        with MemoryWorkspace(self.session.parent / "memory-library") as library:
            snapshot = persist_graph(library, self, identity, expected_sha256=expected_sha256, request_id=request_id)
        reference = {key: snapshot[key] for key in ("logical_workflow_id", "revision", "content_sha256")}
        manifest = self._manifest(identity)
        manifest["graph_reference"] = reference
        write_json_snapshot(self._directory(identity) / "manifest.json", manifest)
        return {"graph_reference": reference, "graph_generated": True, "input_executed": False,
                "unresolved": snapshot["graph"]["invalid_sources"],
                "task_effect_verified": None, "automatic_retry_allowed": False}

    def library_control(self, kind, request, request_id):
        from .workspace import MemoryWorkspace
        with MemoryWorkspace(self.session.parent / "memory-library") as library:
            if kind == "learning_feedback":
                from .feedback import feedback_control
                return feedback_control(library, request, "feedback-" + content_hash([self.session.name, request_id]))
            if kind == "learning_reuse":
                from .reader import prepare_reuse
                return prepare_reuse(library, request["workflow_id"], request["snapshot_id"],
                                     request["edge_id"], request.get("variables", {}))
            if kind == "learning_project":
                from app.desktop_review.workflow_project import WorkflowProjectService
                action = request["action"]
                if action == "list":
                    return {"projects": WorkflowProjectService(library).list_summaries()}
                if action == "read":
                    return library.load_workflow_project(request["workflow_id"])
                if action == "save":
                    return library.save_workflow_project(request["workflow_id"], request["expected_sha256"],
                        request["changes"], "edit-" + content_hash([self.session.name, request_id]))
                if action == "adopt_interface":
                    from .graph_source import adopt_interface
                    return adopt_interface(library, request["workflow_id"], request["node_id"],
                        expected_sha256=request["expected_sha256"], request_id=request_id)
                from .reader import read_project
                return read_project(library, request["workflow_id"], request.get("snapshot_id"), request.get("node_id"))
            if kind == "learning_memory":
                return library.read_memory(request["interface_id"], request.get("version_id"))
            if kind == "learning_save_interface":
                return library.save_interface_content(request["interface_id"], request["expected_revision"],
                    request["expected_sha256"], request["changes"], self.session.name + "-" + request_id)
            values = library.list_interface_contents(task_id="memory-local")
            query = request.get("query", "").casefold()
            values = [value for value in values if query in value["content"]["meaning"].casefold()]
            offset, limit = request.get("offset", 0), request.get("limit", 20)
            selected = values[offset:offset + limit]
            return {"interfaces": [{key: value[key] for key in
                        ("interface_id", "version_id", "revision", "content_sha256", "origin_status")}
                        | {"meaning": value["content"]["meaning"]} for value in selected],
                    "total": len(values), "offset": offset,
                    "next_offset": offset + limit if offset + limit < len(values) else None}

    def _event(self, identity, event_id):
        self._manifest(identity)
        event = read_json_snapshot(self._directory(identity) / "events" / (_id(event_id) + ".json"))
        receipt = self.session / "responses" / (event_id + ".json")
        response = read_json_snapshot(receipt)
        ticket = response.get("learning_binding") or {}
        if (ticket.get("learning_id") != identity or ticket.get("session_id") != self.session.name
                or ticket.get("request_id") != event_id):
            raise ValueError("learning event receipt identity mismatch")
        expected = project_receipt(event_id, response, receipt, ticket)
        if event != expected:
            raise ValueError("learning event no longer matches its original receipt")
        return event

    def _review_state(self, identity, event_id):
        directory = self._directory(identity) / "reviews" / _id(event_id)
        path = directory / "current.json"
        state = read_json_snapshot(path) if path.exists() else {"review_sha256": None, "requests": {}}
        return directory, state

    def _review(self, identity, event_id):
        directory, state = self._review_state(identity, event_id)
        digest = state["review_sha256"]
        if digest is None:
            return None
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("learning review digest is invalid")
        value = read_json_snapshot(directory / "versions" / (digest + ".json"))
        if content_hash(value) != digest or value.get("learning_id") != identity:
            raise ValueError("learning review integrity mismatch")
        if value.get("review", {}).get("event_id") != event_id:
            raise ValueError("learning review event mismatch")
        return {**value, "review_sha256": digest}

    def _verify_review_frames(self, event, review):
        for view in ("before", "after"):
            if review[view] is None:
                continue
            path = Path(event[view]["image_path"])
            if not path.is_absolute():
                path = self.session / path
            path = path.resolve()
            if not path.is_relative_to(self.session):
                raise ValueError("learning evidence must belong to the recorded session")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != review[view]["frame_sha256"]:
                raise ValueError(f"{view} evidence bytes no longer match the recorded frame")

    def review(self, identity, supplied, request_id):
        event = self._event(identity, supplied["event_id"])
        review = validate_event_review(event, supplied)
        self._verify_review_frames(event, review)
        directory, state = self._review_state(identity, event["request_id"])
        request_digest = content_hash(review)
        previous = state["requests"].get(_id(request_id))
        if previous is not None:
            if previous["request_sha256"] != request_digest:
                raise ValueError("learning review request_id conflict")
            return {"status": "recorded", "review_sha256": previous["review_sha256"],
                    "event_id": event["request_id"], "idempotent": True, "input_executed": False}
        self._review(identity, event["request_id"])
        if review["expected_review_sha256"] != state["review_sha256"]:
            raise ValueError("stale learning review; read learning_event before amending")
        value = {"contract_version": "instant_learning_review_v1", "learning_id": identity,
                 "review": review, "frame_bytes_verified_at_ingestion": True}
        digest = content_hash(value)
        self._put_once(directory / "versions" / (digest + ".json"), value)
        state["requests"][request_id] = {"request_sha256": request_digest, "review_sha256": digest}
        state["review_sha256"] = digest
        write_json_snapshot(directory / "current.json", state)
        return {"status": "recorded", "review_sha256": digest, "event_id": event["request_id"],
                "judged_by": review["reviewer"], "verdict": review["verdict"], "input_executed": False}

    def projection(self, identity, event_ids=None):
        manifest = self._manifest(identity)
        all_ids = sorted(path.stem for path in (self._directory(identity) / "events").glob("*.json"))
        selected = all_ids if event_ids is None else sorted(event_ids)
        if len(selected) > 128:
            raise ValueError("projection exceeds 128 events; supply event_ids for a bounded view")
        events = [self._event(identity, event_id) for event_id in selected]
        reviews = {event_id: self._review(identity, event_id) for event_id in selected}
        for event in events:
            record = reviews[event["request_id"]]
            if record is not None:
                self._verify_review_frames(event, record["review"])
        result = project_segment(manifest, events, reviews)
        result.update(total_event_count=len(all_ids), selected_event_count=len(selected),
                      partial_view=set(selected) != set(all_ids),
                      verified_review_frame_count=sum(
                          int(record["review"][view] is not None)
                          for record in reviews.values() if record is not None for view in ("before", "after")))
        return result

    def prepare(self, request_id, command, target):
        if command.get("kind") not in RECORDED_KINDS:
            return None
        identity = self._state()["active_id"]
        if identity is None:
            return None
        ticket = {"learning_id": identity, "session_id": self.session.name,
                  "request_id": _id(request_id), "command_sha256": content_hash(command),
                  "target_before": dict(target) if target else None}
        return ticket

    def reserve(self, ticket):
        self._put_once(self._directory(ticket["learning_id"]) / "tickets" /
                       (_id(ticket["request_id"]) + ".json"), ticket)

    def record(self, request_id, ticket):
        if ticket.get("session_id") != self.session.name or ticket.get("request_id") != request_id:
            raise ValueError("learning ticket session/request mismatch")
        receipt_path = self.session / "responses" / (_id(request_id) + ".json")
        response = read_json_snapshot(receipt_path)
        if response.get("learning_binding") != ticket:
            raise ValueError("learning receipt/ticket binding mismatch")
        self.reserve(ticket)
        try:
            event = project_receipt(request_id, response, receipt_path, ticket)
        except ExecutionReceiptPending:
            return {"status": "awaiting_execution_result", "learning_id": ticket["learning_id"],
                    "event_id": request_id, "input_replayed": False}
        self._put_once(self._directory(ticket["learning_id"]) / "events" / receipt_path.name, event)
        return {"status": "recorded", "learning_id": ticket["learning_id"], "event_id": request_id,
                "task_effect_verified": None, "graph_generated": False}

    def publish_recording_status(self, request_id, value):
        path = self.session / "learning-status" / (_id(request_id) + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_snapshot(path, value)

    def recover(self, identity):
        self._manifest(identity)
        recovered, missing, errors = 0, [], []
        directory = self._directory(identity)
        # 预记账失败时，原回执中的绑定仍可补回；不读取命令队列执行任何动作。
        for path in sorted((self.session / "responses").glob("*.json")):
            try:
                ticket = read_json_snapshot(path).get("learning_binding")
                if ticket and ticket.get("learning_id") == identity:
                    if ticket.get("session_id") != self.session.name or ticket.get("request_id") != path.stem:
                        raise ValueError("learning response identity mismatch")
                    self.reserve(ticket)
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append({"request_id": path.stem, "error_type": type(error).__name__, "message": str(error)})
        for path in sorted((directory / "tickets").glob("*.json")):
            if not (self.session / "responses" / path.name).exists():
                missing.append(path.stem)
                continue
            try:
                ticket = read_json_snapshot(path)
                if ticket.get("learning_id") != identity or ticket.get("request_id") != path.stem:
                    raise ValueError("learning ticket identity mismatch")
                was_recorded = (directory / "events" / path.name).exists()
                result = self.record(path.stem, ticket)
                self.publish_recording_status(path.stem, result)
                recovered += int(not was_recorded and result["status"] == "recorded")
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append({"request_id": path.stem, "error_type": type(error).__name__, "message": str(error)})
        return {**self.status(identity), "recovered_count": recovered,
                "missing_receipt_ids": missing[:20], "missing_receipt_count": len(missing),
                "recovery_errors": errors[:20], "recovery_error_count": len(errors), "input_replayed": False}

    def close(self):
        state = self._state()
        if state["active_id"]:
            self.control("learning_stop", {"learning_id": state["active_id"]}, "host-close")
