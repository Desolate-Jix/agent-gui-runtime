"""Guarded actual caller seams; importing this module never starts a model."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots

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
    """Create closures only; the first invocation proves exclusive ownership before transport."""
    endpoints=config.get('endpoints') if isinstance(config.get('endpoints'),Mapping) else {}
    started = False
    def ensure_started() -> None:
        nonlocal started
        if started: return
        start = getattr(lifecycle, 'start_exclusive', None) or getattr(lifecycle, 'start', None)
        if not callable(start): raise ValueError('actual lifecycle must provide exclusive start')
        result = start()
        if result is False: raise RuntimeError('actual lifecycle did not prove exclusive ownership')
        started = True
    def omni(image: Path) -> object:
        ensure_started()
        response=transport.post(url=str(endpoints.get('omni','omni')),payload={'image_path':str(image)},timeout=120.0)
        return _response_value(response)
    def qwen(image: Path, projection: Mapping[str, object]) -> object:
        ensure_started(); return call_qwen_projected_binding(image_path=image,projection=projection,transport=transport)
    def vista(image: Path, target: str) -> str:
        ensure_started(); return call_vista_bare_point(roi_path=image,target_text=target,transport=transport)
    return SimpleNativeSlots(omni=omni,qwen=qwen,vista=vista,cleanup=lambda: cancel_owned_processes(lifecycle))

def verify_cleanup_receipt(receipt: Mapping[str, object]) -> bool:
    return receipt.get('verified') is True and receipt.get('owned_processes') == []

def cancel_owned_processes(lifecycle: object) -> Mapping[str, object]:
    stop=getattr(lifecycle,'stop_owned',None)
    if not callable(stop): raise ValueError('lifecycle cannot prove owned-process cleanup')
    receipt=stop()
    if not isinstance(receipt,Mapping) or not verify_cleanup_receipt(receipt): raise ValueError('owned process cleanup is not verified')
    return receipt
