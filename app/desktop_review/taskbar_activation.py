"""本地任务栏预览与单次批准；输入仍由既有 canonical 控制面和后端执行。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.agent.desktop_backend import (
    BackendDispatchReceipt, DesktopDispatchCommand, TaskbarExecutionSourceLineage, _mint_execution_authority,
)
from app.agent.taskbar_activation_guard import TaskbarActivationExpectation, TaskbarActivationGuard


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value) -> str:
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class TaskbarActivationClaim:
    confirmation_id: str
    session_id: str
    phase: str
    preview_json: str

    @property
    def preview(self) -> dict:
        return json.loads(self.preview_json)


class TaskbarActivationReceipt(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    contract_version: Literal['taskbar_activation_receipt_v1'] = 'taskbar_activation_receipt_v1'
    source_kind: Literal['taskbar_activation'] = 'taskbar_activation'
    confirmation_id: str = Field(pattern=r'^grounded-confirmation\.[0-9a-f]{64}$')
    session_id: str
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    preview_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    fresh_source_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    target_window_handle: int = Field(gt=0)
    destination_window_handle: int = Field(gt=0)
    destination_process_id: int = Field(gt=0)
    status: Literal['dispatched', 'not_started', 'indeterminate']
    reason_code: str
    backend_receipt_ref: str | None = None
    artifact_is_authorization: Literal[False] = False
    grants_action_authority: Literal[False] = False


@dataclass(frozen=True)
class TaskbarActivationDecision:
    status: str
    reason_code: str
    confirmation_id: str


class TaskbarActivationCallsite:
    """拥有本地批准记录，不暴露 Agent 批准能力，不处理任何原始鼠标输入。"""

    def __init__(self, *, source, backend, journal_dir: Path) -> None:
        self._source, self._backend = source, backend
        self._root = Path(journal_dir)
        self._root.mkdir(parents=True, exist_ok=False)
        self._lock = RLock()
        self._phase = 'created'
        self._preview: dict | None = None
        self._receipt: TaskbarActivationReceipt | None = None
        self._audit: dict = {}
        self._persist()

    def _persist(self, **extra) -> None:
        self._audit.update(extra)
        state = {'contract_version': 'taskbar_activation_journal_v1', 'phase': self._phase,
                 'preview': self._preview,
                 'receipt': self._receipt.model_dump(mode='json') if self._receipt else None, **self._audit}
        temporary = self._root / ('state-' + uuid4().hex + '.tmp')
        with temporary.open('x', encoding='utf-8', newline='\n') as output:
            output.write(_json(state) + '\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self._root / 'state.json')

    def prepare(self) -> dict:
        with self._lock:
            if self._phase != 'created':
                raise ValueError('taskbar preview already created')
            evidence = TaskbarActivationExpectation.from_dict(self._source()).to_dict()
            session_id = 'taskbar-session.' + uuid4().hex
            identity = 'grounded-confirmation.' + _digest({'session_id': session_id, 'source': evidence['source_sha256']})
            preview = {'contract_version': 'taskbar_activation_preview_v1', 'source_kind': 'taskbar_activation',
                       'session_id': session_id, 'confirmation_id': identity, 'semantic_action': 'taskbar_activate',
                       'source': evidence, 'artifact_is_authorization': False, 'grants_action_authority': False}
            preview['preview_sha256'] = _digest(preview)
            self._preview = preview
            self._phase = 'pending'
            self._persist()
            return json.loads(_json(preview))

    def record_decision(self, *, preview_sha256: str, approved: bool) -> TaskbarActivationClaim:
        with self._lock:
            if type(approved) is not bool or self._phase != 'pending' or self._preview is None:
                raise ValueError('taskbar confirmation is not pending')
            if preview_sha256 != self._preview['preview_sha256']:
                raise ValueError('taskbar preview digest differs')
            self._phase = 'approved' if approved else 'cancelled'
            self._persist(decision={'approved': approved, 'preview_sha256': preview_sha256})
            return self.get_local_grounded_confirmation(confirmation_id=self._preview['confirmation_id'])

    def _require_identity(self, confirmation_id: str) -> dict:
        if self._preview is None or confirmation_id != self._preview['confirmation_id']:
            raise ValueError('taskbar confirmation identity differs')
        return self._preview

    def get_local_grounded_confirmation(self, *, confirmation_id: str) -> TaskbarActivationClaim:
        with self._lock:
            preview = self._require_identity(confirmation_id)
            return TaskbarActivationClaim(confirmation_id, preview['session_id'], self._phase, _json(preview))

    def cancel_grounded_review(self, *, session_id: str) -> TaskbarActivationClaim:
        with self._lock:
            if self._preview is None or session_id != self._preview['session_id']:
                raise ValueError('taskbar session identity differs')
            if self._phase not in {'pending', 'approved', 'cancelled'}:
                raise ValueError('taskbar dispatch cannot be cancelled after consume began')
            self._phase = 'cancelled'
            self._persist()
            return self.get_local_grounded_confirmation(confirmation_id=self._preview['confirmation_id'])

    def consume_grounded_confirmation(self, *, confirmation_id: str):
        with self._lock:
            preview = self._require_identity(confirmation_id)
            if self._receipt is not None:
                return self._receipt
            if self._phase in {'pending', 'cancelled'}:
                return TaskbarActivationDecision('REJECTED', 'grounded_confirmation_not_approved', confirmation_id)
            if self._phase != 'approved':
                raise RuntimeError('taskbar consume outcome unknown; input retry is forbidden')
            # 先持久化消费开始；即使随后崩溃，也不重新铸造可点击的授权。
            self._phase = 'consume_started'
            self._persist()
            fresh = None
            backend_receipt_ref = None
            status, reason = 'not_started', 'taskbar_preflight_failed'
            try:
                approved = TaskbarActivationExpectation.from_dict(preview['source'])
                fresh = TaskbarActivationExpectation.from_dict(self._source())
                TaskbarActivationGuard(approved, lambda: fresh.to_dict(), max_age_seconds=120).verify_current()
                guard = TaskbarActivationGuard(fresh, self._source)
                command = DesktopDispatchCommand(semantic_action='taskbar_activate', capture_id=fresh.capture_id,
                    candidate_id=fresh.candidate_id, click_point=fresh.window_point,
                    target_window_handle=fresh.taskbar_handle, taskbar_guard=guard)
                decision = {'contract_version': 'pre_click_decision_v1', 'semantic_action': 'taskbar_activate',
                    'goal': 'activate_exact_destination_window', 'confirmation_id': confirmation_id,
                    'approved_preview_sha256': preview['preview_sha256'], 'capture_id': fresh.capture_id,
                    'source_sha256': fresh.source_sha256, 'candidate_id': fresh.candidate_id,
                    'confidence': 1.0, 'confidence_basis': 'unique_uia_identity_and_geometry',
                    'click_point': list(fresh.window_point), 'screen_point': list(fresh.screen_point),
                    'allowed': True, 'created_at_monotonic': time.monotonic()}
                consume = {'confirmation_id': confirmation_id, 'preview_sha256': preview['preview_sha256'],
                    'fresh_source_sha256': fresh.source_sha256, 'pre_click_decision': decision}
                lineage = TaskbarExecutionSourceLineage(source_sha256=fresh.source_sha256,
                    preview_sha256=preview['preview_sha256'], confirmation_id=confirmation_id,
                    consume_content_sha256=_digest(consume))
                authority = _mint_execution_authority(session_id=preview['session_id'],
                    observation_id=fresh.capture_id, intent_id=confirmation_id, semantic_action='taskbar_activate',
                    capture_id=fresh.capture_id, candidate_id=fresh.candidate_id, click_point=fresh.window_point,
                    target_window_handle=fresh.taskbar_handle, gate_decision_ref='taskbar-gate.' + _digest(decision),
                    taskbar_source_lineage=lineage, taskbar_guard=guard)
                self._persist(consume=consume, fresh_source=fresh.to_dict())
            except (ValueError, TypeError, RuntimeError, OSError) as error:
                reason = 'taskbar_preflight_failed:' + type(error).__name__
                self._persist(preflight_error={'type': type(error).__name__, 'message': str(error)})
            else:
                self._phase = 'dispatch_started'
                self._persist(consume=consume, fresh_source=fresh.to_dict())
                # 调用既有后端；异常后绝不二次点击。
                try:
                    result = self._backend.dispatch(command, authority=authority)
                    if (type(result) is not BackendDispatchReceipt
                            or (result.status, result.reason_code) not in {
                                ('dispatched', 'none'), ('not_started', 'backend_failed'),
                                ('indeterminate', 'backend_result_lost')}
                            or not isinstance(result.receipt_ref, str) or not result.receipt_ref):
                        raise ValueError('taskbar backend receipt is invalid')
                    status, reason, backend_receipt_ref = result.status, result.reason_code, result.receipt_ref
                except Exception:
                    status, reason = 'indeterminate', 'taskbar_backend_result_unknown'
            source = preview['source']
            receipt = TaskbarActivationReceipt(confirmation_id=confirmation_id, session_id=preview['session_id'],
                source_sha256=source['source_sha256'], preview_sha256=preview['preview_sha256'],
                fresh_source_sha256=fresh.source_sha256 if fresh else None,
                target_window_handle=source['taskbar']['handle'],
                destination_window_handle=source['destination']['handle'],
                destination_process_id=source['destination']['pid'], status=status,
                reason_code=reason, backend_receipt_ref=backend_receipt_ref)
            self._receipt = receipt
            self._phase = 'terminal'
            self._persist()
            return receipt


__all__ = ['TaskbarActivationCallsite', 'TaskbarActivationClaim', 'TaskbarActivationReceipt']
