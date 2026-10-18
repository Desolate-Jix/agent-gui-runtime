"""验收状态必须完整可读，并且不被晚到的旧事件覆盖。"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from tests.fixtures.form_state import FormState


def test_reader_never_sees_half_written_state(tmp_path, monkeypatch):
    target = tmp_path / 'state.json'
    store = FormState(target)
    store.update({'seq': 0, 'text': 'initial'})
    original = Path.write_text
    observed = []
    def interrupted_write(path, data, **kwargs):
        original(path, data[:len(data)//2], **kwargs)
        observed.append(json.loads(target.read_text(encoding='utf-8')))
        return original(path, data, **kwargs)
    monkeypatch.setattr(Path, 'write_text', interrupted_write)
    store.update({'seq': 1, 'text': '\u6d4b\u8bd5'})
    assert observed == [{'seq': 0, 'text': 'initial'}]
    assert json.loads(target.read_text(encoding='utf-8')) == {'seq': 1, 'text': '\u6d4b\u8bd5'}


def test_concurrent_events_preserve_highest_sequence(tmp_path):
    target = tmp_path / 'state.json'
    store = FormState(target)
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(lambda seq: store.update({'seq': seq, 'data': str(seq)*200}), range(200)))
    assert json.loads(target.read_text(encoding='utf-8'))['seq'] == 199
    store.update({'seq': 1, 'data': 'late'})
    assert json.loads(target.read_text(encoding='utf-8'))['seq'] == 199
