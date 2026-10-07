"""正式只读回执原图独立于截图缓存淘汰。"""
import hashlib
import json
import inspect
import os
from pathlib import Path

import pytest
from PIL import Image

from app.core.screenshot import ScreenshotService
from app.core.session_input_terminal import inspect_session_input_terminal
from scripts.run_local_step_session import run_read_text_command


def produce(capture, source, destination):
    options = {'recognition_source': source}
    if 'evidence_dir' in inspect.signature(run_read_text_command).parameters:
        options['evidence_dir'] = destination
    return run_read_text_command(capture, {}, **options)


@pytest.mark.parametrize('source', ['agent_current', 'local'])
def test_original_read_receipt_survives_real_cache_cleanup(tmp_path, monkeypatch, source):
    root = tmp_path / 'session-fresh'
    cache = root / 'captures'
    cache.mkdir(parents=True)
    image = cache / 'original.png'
    Image.new('RGB', (16, 12), 'white').save(image)
    raw = image.read_bytes()
    frame = {'image_path': str(image), 'sha256': hashlib.sha256(raw).hexdigest(),
             'capture_id': 'actual-capture', 'captured_at': '2026-10-07T00:00:00Z',
             'window_size': {'width': 16, 'height': 12}, 'identity': {'process_id': 123}}
    if source == 'local':
        from app.core.ocr_service import ocr_service
        from modules.ocr.contracts import OCRResult
        monkeypatch.setattr(ocr_service, 'scan_image', lambda p: OCRResult(p, []))
    result, observation = produce(lambda: dict(frame), source, root / 'read-text-evidence')
    response = root / 'responses/read-original.json'
    response.parent.mkdir()
    (root / 'commands').mkdir()
    (root / 'commands/read-original.json').write_text(json.dumps({'kind': 'read_text'}), encoding='utf-8')
    response.write_text(json.dumps({'request_id': 'read-original', 'command': {'kind': 'read_text'},
        'status': 'returned', 'result': result, 'observation': observation}), encoding='utf-8')
    receipt_bytes = response.read_bytes()
    os.utime(image, (1, 1))
    service = ScreenshotService(capture_dir=cache)
    for index in range(41):
        newer = cache / f'new-{index}.png'
        newer.write_bytes(raw)
        os.utime(newer, (index + 2, index + 2))
    service._cleanup_old_captures()
    assert not image.exists() and len(list(cache.glob('*.png'))) == 40
    retained = Path(observation['image_path'])
    assert retained.parent == root / 'read-text-evidence'
    assert retained.read_bytes() == raw
    assert {k: observation[k] for k in frame if k != 'image_path'} == {k: v for k, v in frame.items() if k != 'image_path'}
    proof = inspect_session_input_terminal(root, tmp_path / 'memory-library')
    assert proof
    assert response.read_bytes() == receipt_bytes
    if source == 'local':
        assert result['capture']['image_path'] == str(retained)


@pytest.mark.parametrize('failure', ['digest', 'directory', 'write'])
@pytest.mark.parametrize('source', ['agent_current', 'local'])
def test_failed_persistence_never_delivers_agent_read(tmp_path, monkeypatch, failure, source):
    image = tmp_path / 'source.png'
    Image.new('RGB', (5, 5)).save(image)
    frame = {'image_path': str(image), 'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
    destination = tmp_path / 'read-text-evidence'
    if failure == 'digest':
        frame['sha256'] = '0' * 64
    elif failure == 'directory':
        destination.write_bytes(b'blocked')
    else:
        original_open = Path.open
        def blocked(path, *args, **kwargs):
            if path.parent == destination and args and args[0] == 'xb':
                raise OSError('evidence write denied')
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', blocked)
    with pytest.raises((ValueError, OSError)):
        produce(lambda: frame, source, destination)
