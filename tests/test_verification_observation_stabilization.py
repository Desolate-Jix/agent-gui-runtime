"""字段只读核验遇到光标闪烁时重新夹读，不能拼接旧值或忽略变动。"""
from copy import deepcopy
from hashlib import sha256

from PIL import Image
import pytest

from app.learning_memory import verification_observation as module
from tests.test_verification_observation import captured, coordinator


def frames(tmp_path, pixels):
    rows = []
    for index, active in enumerate(pixels):
        frame, observation = captured(f'capture-{index}')
        control = observation['uia']['snapshot']['controls'][0]
        control.update(control_type='Edit', automation_id='field')
        image = Image.new('RGB', (800, 600), 'white')
        if active:
            for y in range(33, 48):
                image.putpixel((80, y), (0, 0, 0))
        path = tmp_path / f'{index}.png'
        image.save(path)
        frame.update(image_path=str(path), sha256=sha256(path.read_bytes()).hexdigest())
        rows.append((frame, observation))
    return rows


def install(monkeypatch, rows):
    captures, reads = [], []
    stream = iter(rows)
    def capture(*args, **kwargs):
        result = next(stream)
        captures.append(result[0]['capture_id'])
        return deepcopy(result)
    def field(coordinator, target, frame, control):
        reads.append(frame['capture_id'])
        value = '当前新值' if len(reads) > 1 else '较早的值'
        return value, None, {'capture_id': frame['capture_id'], 'selection': [4, 4],
                            'value_sha256': sha256(value.encode('utf-8')).hexdigest()}
    monkeypatch.setattr(module, 'capture_memory_observation', capture)
    monkeypatch.setattr(module, '_read_control_value', field)
    return captures, reads


def observe():
    return module.read_step_observation(coordinator(), target={'handle': 91, 'process_id': 42},
                                        selector={'control_type': 'Edit', 'automation_id': 'field'}, method='uia_value')


def test_caret_blink_reacquires_complete_pair_and_uses_only_new_value(monkeypatch, tmp_path):
    captures, reads = install(monkeypatch, frames(tmp_path, [False, True, True, True]))
    result = observe()
    assert result['status'] == 'ok'
    assert result['values'] == {'field_value': '当前新值'}
    assert result['capture_id'] == 'capture-3'
    assert captures == ['capture-0', 'capture-1', 'capture-2', 'capture-3']
    assert reads == ['capture-0', 'capture-2']
    attempts = result['evidence']['observation_attempts']
    assert len(attempts) == 2
    assert attempts[0]['reason'] == 'frame_changed_between_reads'
    assert attempts[0]['evidence']['before_frame']['capture_id'] == 'capture-0'
    assert attempts[0]['evidence']['visual_stability']['matched'] is False
    assert attempts[1]['status'] == 'ok'


def test_continuously_changing_field_exhausts_three_pairs_without_value(monkeypatch, tmp_path):
    captures, reads = install(monkeypatch, frames(tmp_path, [False, True] * 3))
    result = observe()
    assert result['status'] == 'unavailable'
    assert result['values'] == {}
    assert result['reason'] == 'frame_changed_between_reads'
    assert len(captures) == 6 and len(reads) == 3
    assert len(result['evidence']['observation_attempts']) == 3


@pytest.mark.parametrize('change', ['window', 'target'])
def test_new_attempt_cannot_switch_original_target(monkeypatch, tmp_path, change):
    rows = frames(tmp_path, [False, True, True, True])
    for frame, observation in rows[2:]:
        if change == 'window':
            frame['window_identity']['process_create_time'] += 1
            observation['uia']['window_identity']['process_create_time'] += 1
        else:
            observation['uia']['snapshot']['controls'][0]['runtime_id'] = [42, 8]
    captures, reads = install(monkeypatch, rows)
    result = observe()
    assert result['status'] == 'unavailable'
    assert result['values'] == {}
    assert result['reason'] == f'{"frame" if change == "window" else "target"}_changed_between_observation_attempts'
    assert len(captures) == 4


def test_invalid_frame_bytes_do_not_trigger_reacquisition(monkeypatch, tmp_path):
    rows = frames(tmp_path, [False, True])
    rows[0][0]['sha256'] = '0' * 64
    captures, reads = install(monkeypatch, rows)
    result = observe()
    assert result['status'] == 'unavailable'
    assert result['values'] == {}
    assert len(captures) == 2
    assert result['evidence']['visual_stability']['reason'] == 'capture_evidence_unavailable'
