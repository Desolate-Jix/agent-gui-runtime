"""公共只读内容入口：来源绑定、区域选择与不可变文本快照。"""

from copy import deepcopy
from hashlib import sha256
import json
import re
from types import SimpleNamespace

from app.agent.fresh_learning_runtime_source import load_fresh_learning_runtime_source
from app.agent_link.contracts import AgentLinkError, canonical_hash
from app.operation.screen_reading.uia_content import WindowsUIAContentReader
from .workspace import _atomic_write_bytes, _write_immutable


CONTENT_CAPABILITY = {
    "contract_version": "agent_learning_content_v1",
    "operations": ["inspect_learning_content", "read_learning_content"],
}
_FLAGS = {"artifact_is_authorization": False, "execute_binding_enabled": False, "action_executed": False}


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fail(code):
    raise AgentLinkError(code, code)


def _identity(connection_id, task_id, segment_id):
    value = {"connection_id": connection_id, "task_id": task_id, "segment_id": segment_id}
    if any(not isinstance(x, str) or not x or len(x) > 500 for x in value.values()):
        _fail("content_invalid_arguments")
    return value


def _surface(packet):
    value = packet.evidence()
    return {"target": value["target"], "application": value["application"], "uia": value["uia"],
            "screenshot_sha256": value["capture"]["screenshot_sha256"],
            "viewport_size": value["capture"]["viewport_size"]}


def _bound(packet):
    target = packet.evidence()["target"]
    rect = target["rect"]
    return SimpleNamespace(handle=target["window_handle"], process_id=target["process_id"],
        rect=SimpleNamespace(left=rect["x"], top=rect["y"], right=rect["x"] + rect["width"], bottom=rect["y"] + rect["height"]))


class LearningContentProvider:
    def __init__(self, observation_provider, reader=None):
        self.observer = observation_provider
        self.source_owner = observation_provider.source_owner
        self.reader = reader or WindowsUIAContentReader()
        self.root = self.source_owner.archive.project_root / "runtime_state" / "learning-content-v1"

    def record_source_context(self, packet, uia):
        """封存同帧原树；不从后来的当前树补造历史上下文。"""
        evidence = packet.evidence()
        if (sha256(packet.png_bytes).hexdigest() != evidence['capture']['screenshot_sha256']
                or canonical_hash(uia) != evidence['uia']['snapshot_sha256']):
            raise ValueError('content source context differs from its capture')
        key = canonical_hash(evidence)
        record = {'contract_version': 'learning_content_source_context_v1',
                  'evidence_sha256': key, 'uia': deepcopy(uia)}
        _write_immutable(self.root / 'source-contexts' / (key + '.json'), _bytes(record))

    def _source_context(self, packet):
        key = canonical_hash(packet.evidence())
        path = self.root / 'source-contexts' / (key + '.json')
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if (set(record) != {'contract_version', 'evidence_sha256', 'uia'}
                    or record['contract_version'] != 'learning_content_source_context_v1'
                    or record['evidence_sha256'] != key
                    or canonical_hash(record['uia']) != packet.evidence()['uia']['snapshot_sha256']):
                raise ValueError('content source context is corrupt')
            return record['uia']
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise AgentLinkError('content_source_stale', 'original content context is unavailable') from error

    def _source(self, scope, batch_id):
        if not isinstance(batch_id, str) or not batch_id or len(batch_id) > 200:
            _fail("content_invalid_arguments")
        try:
            return load_fresh_learning_runtime_source(self.source_owner, **scope, batch_id=batch_id)
        except (ValueError, OSError, KeyError) as error:
            raise AgentLinkError("learning_source_unavailable", "learning source is unavailable") from error

    def _capture(self, source):
        from app.agent.fresh_learning_factory import create_fresh_learning_observation_owner
        from .learning_observation import _safe_visibility_reason
        ref = source.reference()
        try:
            owner = create_fresh_learning_observation_owner(project_root=source.project_root,
                application_identity=ref["application_identity"], target_window_handle=ref["target_window_handle"],
                target_process_id=ref["target_process_id"])
            bundle = owner.observe_with_uia(target_window_handle=ref["target_window_handle"], target_process_id=ref["target_process_id"])
            packet = bundle.packet
        except Exception as error:
            reason = _safe_visibility_reason(error)
            raise AgentLinkError(reason or "content_read_failed", reason or "passive content observation failed") from error
        proof = {'contract_version': 'learning_content_surface_v1', 'policy': 'exact_surface',
                 'original_capture_id': source.packet.evidence()['capture']['capture_id'],
                 'current_capture_id': packet.evidence()['capture']['capture_id']}
        if _surface(packet) != _surface(source.packet):
            from app.agent.content_uia_stability import compare_content_context
            try:
                proof = compare_content_context(original_packet=source.packet, current_packet=packet,
                    original_uia=self._source_context(source.packet), current_uia=bundle.uia_snapshot())
            except (ValueError, TypeError, KeyError) as error:
                raise AgentLinkError('content_source_stale', 'content context changed') from error
        return packet, proof

    def _save(self, category, scope, value):
        digest = canonical_hash(value)
        path = self.root / canonical_hash(scope) / category / (digest + ".json")
        _write_immutable(path, _bytes(value))
        return digest

    def _load(self, category, scope, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            _fail("content_invalid_arguments")
        try:
            value = json.loads((self.root / canonical_hash(scope) / category / (digest + ".json")).read_text(encoding="utf-8"))
            if canonical_hash(value) != digest or value["scope"] != scope:
                _fail("content_inspection_unavailable")
            return value
        except (OSError, ValueError, KeyError) as error:
            raise AgentLinkError("content_inspection_unavailable", "content inspection is unavailable") from error

    def _enter(self):
        if not self.observer._capture_guard.acquire(blocking=False):
            _fail("learning_busy")

    def inspect(self, *, connection_id, task_id, segment_id, batch_id):
        scope = _identity(connection_id, task_id, segment_id)
        self._enter()
        try:
            source = self._source(scope, batch_id)
            before, before_proof = self._capture(source)
            regions = self.reader.inspect_regions(_bound(before))
            after, after_proof = self._capture(source)
            self._source(scope, batch_id)
            record = {"scope": scope, "batch_id": batch_id, "source_sha256": source.reference()["source_sha256"],
                      "regions": regions, "before": before.evidence(), "after": after.evidence(),
                      "surface_proofs": [before_proof, after_proof]}
            inspection_id = self._save("inspections", scope, record)
            return {**CONTENT_CAPABILITY, **_FLAGS, "inspection_id": inspection_id, "batch_id": batch_id,
                    "source_sha256": record["source_sha256"], "capture": before.evidence()["capture"],
                    "regions": [{k: v for k, v in region.items() if k != "reference"} for region in regions["regions"]],
                    "truncated": regions["truncated"], "scope": "selected_region_only"}
        except AgentLinkError:
            raise
        except Exception as error:
            raise AgentLinkError("content_read_failed", "content inspection failed") from error
        finally:
            self.observer._capture_guard.release()

    def read(self, *, connection_id, task_id, segment_id, inspection_id, region_id, idempotency_key, max_chars=200000):
        scope = _identity(connection_id, task_id, segment_id)
        if (type(max_chars) is not int or not 1 <= max_chars <= 200000 or not isinstance(region_id, str)
                or not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 160):
            _fail("content_invalid_arguments")
        self._enter()
        try:
            inspection = self._load("inspections", scope, inspection_id)
            source = self._source(scope, inspection["batch_id"])
            if source.reference()["source_sha256"] != inspection["source_sha256"]:
                _fail("content_source_stale")
            regions = [r for r in inspection["regions"]["regions"] if r["region_id"] == region_id]
            if len(regions) != 1:
                _fail("content_region_unavailable")
            request = {"inspection_id": inspection_id, "region_id": region_id, "max_chars": max_chars}
            ledger = self.root / canonical_hash(scope) / "requests" / (canonical_hash({"key": idempotency_key}) + ".json")
            previous = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else None
            if previous and previous["request"] != request:
                _fail("idempotency_conflict")
            before, before_proof = self._capture(source)
            result = self.reader.read_region(_bound(before), regions[0]["reference"], max_chars=max_chars)
            after, after_proof = self._capture(source)
            confirmation = self.reader.read_region(_bound(after), regions[0]["reference"], max_chars=max_chars)
            if confirmation != result:
                _fail("content_source_stale")
            final, final_proof = self._capture(source)
            self._source(scope, inspection["batch_id"])
            if (not isinstance(result.get("text"), str) or len(result["text"]) > max_chars
                    or result.get("region_reference") != regions[0]["reference"]
                    or type(result.get("truncated")) is not bool or type(result.get("read_complete")) is not bool
                    or (result["truncated"] and result["read_complete"])
                    or (result["read_complete"] and result.get("method") != "text_pattern_document_range")):
                _fail("content_read_failed")
            public = {k: v for k, v in result.items() if k != "region_reference"}
            content_sha = canonical_hash(public)
            if previous:
                saved = self._load("snapshots", scope, previous["snapshot_id"])
                if saved["content_sha256"] != content_sha:
                    _fail("content_source_stale")
                response = saved["response"]
            else:
                sequence = max((json.loads(p.read_text(encoding="utf-8"))["sequence"]
                                for p in ledger.parent.glob("*.json")), default=0) + 1
                response = {**CONTENT_CAPABILITY, **_FLAGS, **public, **request, "batch_id": inspection["batch_id"],
                    "source_sha256": inspection["source_sha256"], "text_sha256": sha256(result["text"].encode("utf-8")).hexdigest(),
                    "content_sha256": content_sha, "capture": before.evidence()["capture"],
                    "scope": "selected_region_only", "scroll_performed": False}
                saved = {"scope": scope, "sequence": sequence, "content_sha256": content_sha, "request": request, "response": response,
                         "before": before.evidence(), "after": after.evidence(), "final": final.evidence(),
                         "surface_proofs": [before_proof, after_proof, final_proof]}
                snapshot_id = self._save("snapshots", scope, saved)
                previous = {"request": request, "snapshot_id": snapshot_id, "sequence": sequence}
                _write_immutable(ledger, _bytes(previous))
            # 崩溃后补齐最新指针，但旧幂等请求不得覆盖更晚的读取。
            if "snapshot_id" not in response:
                response = {**response, "snapshot_id": previous["snapshot_id"]}
            latest = self.root / canonical_hash(scope) / "latest.json"
            current_latest = json.loads(latest.read_text(encoding="utf-8")) if latest.exists() else {"sequence": 0}
            if saved["sequence"] > current_latest["sequence"]:
                _atomic_write_bytes(latest, _bytes({"snapshot_id": previous["snapshot_id"], "sequence": saved["sequence"], "batch_id": inspection["batch_id"]}))
            return deepcopy(response)
        except AgentLinkError:
            raise
        except Exception as error:
            raise AgentLinkError("content_read_failed", "content reading failed") from error
        finally:
            self.observer._capture_guard.release()
