"""Guarded actual caller seams; importing this module never starts a model."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots


class SimpleNativeActualBlocked(RuntimeError):
    """缺少精确受管 provider 生命周期时，在构造前 fail closed。"""


def actual_lifecycle_blocker_message() -> str:
    return (
        "BLOCKED: actual simple-native diagnostic needs a managed compact Qwen "
        "ordinal-run API and a managed VISTA acquire/run/release API that return "
        "exact per-provider cleanup observations; repository APIs do not expose "
        "those two boundaries without recreating a supervisor"
    )

class HTTPTransport(Protocol):
    def post(self, *, url: str, payload: Mapping[str, object], timeout: float) -> object: ...

def _response_value(value: object) -> object:
    if isinstance(value, Mapping) and 'content' in value: return value['content']
    return value

def call_qwen_projected_binding(*, image_path: Path, projection: Mapping[str, object], transport: HTTPTransport) -> object:
    """Send only the short projection; full runtime request remains with the runner."""
    payload={'projection': dict(projection), 'image_path': str(image_path), 'instruction':'Return closed ordinal bindings only.'}
    return _response_value(transport.post(url='qwen', payload=payload, timeout=120.0))

def call_vista_bare_point(*, roi_path: Path, target_text: str, transport: HTTPTransport) -> str:
    """Dedicated native VISTA transport: no generic system message/JSON response format."""
    payload={'messages':[{'role':'user','content':f'{target_text}\nReturn only [x,y] normalized to 0..1000.'}], 'image_path':str(roi_path)}
    result=_response_value(transport.post(url='vista', payload=payload, timeout=120.0))
    if not isinstance(result,str): raise ValueError('VISTA transport must return raw text')
    return result

def project_omni_official_items(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Remove all worker/runtime fields before the native contract boundary."""
    return {'items':[{'bbox':item.get('bbox'),'type':item.get('type'),'content':item.get('content'),'interactivity':item.get('interactivity')} for item in items]}

def make_actual_simple_native_slots(*, config: Mapping[str, object], lifecycle: object, transport: HTTPTransport) -> SimpleNativeSlots:
    """精确受管 API 缺失时拒绝 generic lifecycle。"""
    del config, lifecycle, transport
    raise SimpleNativeActualBlocked(actual_lifecycle_blocker_message())

def verify_cleanup_receipt(receipt: Mapping[str, object]) -> bool:
    return receipt.get('verified') is True and receipt.get('owned_processes') == []

def cancel_owned_processes(lifecycle: object) -> Mapping[str, object]:
    stop=getattr(lifecycle,'stop_owned',None)
    if not callable(stop): raise ValueError('lifecycle cannot prove owned-process cleanup')
    receipt=stop()
    if not isinstance(receipt,Mapping) or not verify_cleanup_receipt(receipt): raise ValueError('owned process cleanup is not verified')
    return receipt
