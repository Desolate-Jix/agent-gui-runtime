"""当前截图文字读取的公开命令、证据绑定和截断契约。"""
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from app.instant_mcp import InstantCommand
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch
from tests.test_memory_grounding_execution import timed_scene, original_timed_scene


@pytest.mark.parametrize('failure', [None, 'focus_failure', 'focus_unconfirmed', 'geometry_drift',
    'process_id', 'process_create_time', 'executable_path', 'occluded'])
def test_read_execution_prepares_exact_target_before_original_capture(timed_scene, captured, tmp_path, failure):
    from scripts.run_local_step_session import run_read_text_command
    from app.core.screenshot import CaptureVisibilityError
    co, state, _, _ = timed_scene
    if failure in {'process_id', 'process_create_time', 'executable_path'}:
        state.identity_drift = failure
    elif failure:
        setattr(state, failure, True)
    def capture():
        assert co._windows().get_bound_window().is_active is True
        state.events.append('read_capture')
        if failure == 'occluded':
            raise CaptureVisibilityError('capture_window_occluded')
        return captured
    def execute():
        return run_read_text_command(capture, {'kind': 'read_text'}, recognition_source='agent_current',
            evidence_dir=tmp_path / 'durable-read', coordinator=co, target={'handle': 321, 'process_id': 12})
    if failure:
        with pytest.raises((PermissionError, ValueError)):
            execute()
        assert state.events.count('read_capture') == (1 if failure == 'occluded' else 0)
    else:
        result, observation = execute()
        assert result['status'] == 'agent_read_required'
        assert result['action_executed'] is False
        assert Path(observation['image_path']).read_bytes() == Path(captured['image_path']).read_bytes()
        assert state.events.count('target_focus') == 1
        assert state.events.index('target_focus') < state.events.index('read_capture')
    assert 'route' not in state.events


def test_plain_read_observation_does_not_activate_target(timed_scene, captured):
    from scripts.run_local_step_session import run_read_text_command
    _, state, _, _ = timed_scene
    result, observation = run_read_text_command(lambda: captured, {}, recognition_source='agent_current')
    assert result['action_executed'] is False
    assert observation['sha256'] == captured['sha256']
    assert 'target_focus' not in state.events


def test_read_text_command_is_available_without_step_or_model_plan():
    assert InstantCommand.model_validate({'kind': 'read_text', 'max_chars': 100}).command() == {
        'kind': 'read_text', 'max_chars': 100}


@pytest.mark.parametrize('payload', [
    {'kind': 'read_text', 'max_chars': 0},
    {'kind': 'read_text', 'max_chars': 20001},
    {'kind': 'read_text', 'max_chars': True},
    {'kind': 'capture', 'max_chars': 100},
    {'kind': 'read_text', 'request': {'text': 'not-an-input'}},
])
def test_invalid_read_shape_is_rejected(payload):
    with pytest.raises(ValueError):
        InstantCommand.model_validate(payload).command()


@pytest.fixture
def captured(tmp_path):
    path = tmp_path / 'frame.png'
    Image.new('RGB', (400, 200), 'white').save(path)
    return {'image_path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'capture_id': 'fresh-1', 'window_size': {'width': 400, 'height': 200},
            'capture_visibility': {'masked': True}}


def read(captured, lines, **kwargs):
    from app.operation.screen_reading.captured_text import read_captured_text
    return read_captured_text(captured, scanner=lambda path: OCRResult(
        path, [OCRTextMatch(text, .9, OCRBoundingBox(10, y, 80, 20)) for text, y in lines],
        {'engine': 'test_ocr', 'fallback_used': False}), **kwargs)


def test_text_has_unicode_geometry_and_exact_capture_lineage(captured):
    result = read(captured, [('地点 Timaru', 20), ('搜索结果', 60)])
    assert result['text'] == '地点 Timaru\n搜索结果'
    assert result['capture']['sha256'] == captured['sha256']
    assert result['capture']['capture_id'] == 'fresh-1'
    assert result['capture']['capture_visibility']['masked'] is True
    assert result['coordinate_space'] == 'capture_image_pixels'
    assert result['lines'][1]['bbox'] == {'x': 10, 'y': 60, 'width': 80, 'height': 20}
    assert result['lines'][1]['text'] == result['text'][10:14]
    assert result['action_executed'] is False
    assert result['read_complete'] is False
    assert result['truncated'] is False


def test_character_limit_bounds_both_text_and_lines(captured):
    result = read(captured, [('甲乙😀丁', 20), ('never-returned', 60)], max_chars=3)
    assert result['text'] == '甲乙😀'
    assert len(result['lines']) == 1
    assert result['lines'][0]['text'] == '甲乙😀'
    assert result['lines'][0]['text_truncated'] is True
    assert result['truncated'] is True


def test_empty_ocr_is_not_proof_of_empty_page(captured):
    result = read(captured, [])
    assert result['status'] == 'no_text_detected'
    assert result['read_complete'] is False
    assert result['text'] == ''


def test_mismatched_capture_digest_does_not_produce_text(captured):
    captured['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='digest'):
        read(captured, [('stale', 20)])


def test_ocr_failure_is_not_empty_success(captured):
    from app.operation.screen_reading.captured_text import read_captured_text
    def failed(path):
        raise RuntimeError('OCR engine failed')
    with pytest.raises(RuntimeError, match='OCR engine failed'):
        read_captured_text(captured, scanner=failed)


def test_ocr_result_cannot_reference_another_image(captured):
    from app.operation.screen_reading.captured_text import read_captured_text
    with pytest.raises(ValueError, match='image'):
        read_captured_text(captured, scanner=lambda path: OCRResult('other.png', []))


def test_runner_reads_new_capture_each_time_and_does_not_reuse_old_text(captured, tmp_path, monkeypatch):
    from app.core.ocr_service import ocr_service
    from scripts.run_local_step_session import run_read_text_command
    next_path = tmp_path / 'next.png'
    Image.new('RGB', (400, 200), 'black').save(next_path)
    newer = {**captured, 'image_path': str(next_path), 'capture_id': 'fresh-2',
             'sha256': hashlib.sha256(next_path.read_bytes()).hexdigest()}
    captures = iter([captured, newer])
    def scan(path):
        text = 'first page' if Path(path).name == 'frame.png' else 'new page'
        return OCRResult(path, [OCRTextMatch(text, .9, OCRBoundingBox(1, 1, 80, 20))])
    monkeypatch.setattr(ocr_service, 'scan_image', scan)
    first, first_image = run_read_text_command(lambda: next(captures), {})
    second, second_image = run_read_text_command(lambda: next(captures), {})
    assert first['text'] == 'first page'
    assert second['text'] == 'new page'
    assert second_image['sha256'] != first_image['sha256']
    assert second['capture']['capture_id'] != first['capture']['capture_id']
    assert second['capture']['captured_at']


def test_runner_capture_failure_is_not_hidden_by_previous_read():
    from scripts.run_local_step_session import run_read_text_command
    def missing_target():
        raise ValueError('select a target window before observing')
    with pytest.raises(ValueError, match='target window'):
        run_read_text_command(missing_target, {})
