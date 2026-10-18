"""图标原生命中能力只存在于当前截图所有者的只读识别调用中。"""
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import time

from app.agent.native_field_hit_context import _crop_rgb
from app.operation.recognition.native_control_hit_binding import current_icon_control, validated_hit_control

_collector = ContextVar('current_native_control_hit_collector', default=None)


@contextmanager
def pinned_control_hit_collector(callback):
    if callback is not None and not callable(callback):
        raise ValueError('control hit collector must be callable')
    token = _collector.set(callback)
    try:
        yield
    finally:
        _collector.reset(token)


def collect_current_control_hit(*, image_path, uia_snapshot, point):
    callback = _collector.get()
    return None if callback is None else callback(image_path=image_path, uia_snapshot=uia_snapshot, point=point)


def make_control_hit_collector(owner, *, image_path, image_bytes, uia_snapshot, capture_id,
                               capture_started_ns, captured_at_ns, application_fact,
                               target_window_handle, target_process_id, window_rect):
    """只固定来源，实际需要图标证据时才增加两次局部像素和原生只读检查。"""
    from .fresh_learning_observation import _bound_rect, _canonical_bytes, _require_uia_rect
    from .live_runtime_composition import _bound_identity, _validated_saved_capture, _validated_uia_snapshot
    from .windows_control_hit_reader import WindowsControlHitReader

    source_path = Path(image_path).resolve()
    source_bytes = bytes(image_bytes)
    source_sha = sha256(source_bytes).hexdigest()
    snapshot = deepcopy(uia_snapshot)
    fact, rect = deepcopy(application_fact), deepcopy(window_rect)

    def collect(*, image_path, uia_snapshot, point):
        if _collector.get() is not collect:
            raise ValueError('control hit collector is outside its owned observation scope')
        if (not isinstance(rect, Mapping) or set(rect) != {'x','y','width','height'}
                or any(type(v) is not int for v in rect.values()) or min(rect['width'],rect['height']) <= 0
                or not isinstance(fact, Mapping) or not isinstance(capture_id, str) or not capture_id
                or type(capture_started_ns) is not int or type(captured_at_ns) is not int
                or not 0 < capture_started_ns <= captured_at_ns <= time.perf_counter_ns()):
            raise ValueError('control hit source binding is invalid')
        size = rect['width'], rect['height']
        identity = target_window_handle, target_process_id, size
        checked = _validated_uia_snapshot(snapshot, expected_identity=identity)
        _require_uia_rect(checked, rect)
        uia_sha = sha256(_canonical_bytes(checked)).hexdigest()
        if (Path(image_path).resolve() != source_path
                or sha256(_canonical_bytes(uia_snapshot)).hexdigest() != uia_sha):
            raise ValueError('control hit request differs from the owned source')
        control = current_icon_control(checked, point)
        if control is None:
            return None
        created = fact.get('process_create_time')
        if type(created) not in (float,int) or not 0 < created < float('inf'):
            raise ValueError('control hit process identity is unavailable')
        bbox = control['bbox']
        source_rgb = sha256(_crop_rgb(source_bytes, size, bbox).tobytes()).hexdigest()
        seen = {source_path}

        def verify_binding():
            bound = owner._window_manager.get_bound_window()
            if (_bound_identity(bound, target_window_handle=target_window_handle) != identity
                    or _bound_rect(bound) != rect
                    or owner._read_application_fact(target_window_handle,target_process_id) != fact
                    or sha256(source_path.read_bytes()).hexdigest() != source_sha):
                raise ValueError('control hit native owner or original capture changed')

        def fresh_pixels():
            verify_binding()
            capture = owner._screenshot_service.capture_window(save_image=True, focus_window=False,
                purpose='learning-control-hit-proof')
            verify_binding()
            path, payload, _ = _validated_saved_capture(capture, expected_size=size)
            if path in seen:
                raise ValueError('control hit reused an evidence path')
            seen.add(path)
            digest = sha256(_crop_rgb(payload, size, bbox).tobytes()).hexdigest()
            if digest != source_rgb:
                raise ValueError('control hit target pixels changed')
            return digest

        before_rgb = fresh_pixels()
        reader = WindowsControlHitReader(window_manager=owner._window_manager,
            native_identity_reader=owner._native_identity_reader)
        before_ns = time.perf_counter_ns()
        hit = reader.observe_control_hit(window_handle=target_window_handle, process_id=target_process_id,
            process_create_time=created, window_rect=tuple(rect[k] for k in ('x','y','width','height')),
            capture_id=capture_id, control_id=control['control_id'], point=(point['x'],point['y']),
            expected_runtime_id=tuple(control['runtime_id']), expected_control_type=control['control_type'],
            expected_bbox=tuple(bbox[k] for k in ('x','y','w','h')))
        after_ns = time.perf_counter_ns()
        after_rgb = fresh_pixels()
        proof = {'contract_version':'current_control_hit_binding_v1', 'capture_id':capture_id,
            'screenshot_sha256':source_sha,'uia_snapshot_sha256':uia_sha,
            'capture_started_ns':capture_started_ns,'captured_at_ns':captured_at_ns,
            'before_hit_ns':before_ns,'after_hit_ns':after_ns,
            'target':{'window_handle':target_window_handle,'process_id':target_process_id,
                'process_create_time':created,'window_rect':[rect[k] for k in ('x','y','width','height')]},
            'hit':deepcopy(hit),'pixels':{'bbox':dict(bbox),'source_rgb_sha256':source_rgb,
                'before_rgb_sha256':before_rgb,'after_rgb_sha256':after_rgb}}
        if validated_hit_control(proof, checked, point, source_sha) is None:
            raise ValueError('native control hit differs from owned source')
        return proof

    return collect
