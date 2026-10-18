"""真实旅程编排的画布修改窄检查；系统输入保持隔离。"""
import pytest

from app.desktop_review.window import ensure_application
from tests.native_learned_reference_journey import edit_learned_region
from tests.test_fresh_learning_action_preview import _setup
from tests.test_learned_control_reference import _saved, _close


def test_canvas_edit_save_reload_keeps_original_and_exact_region(tmp_path):
    app = ensure_application()
    host, _, runtime, backend, _, source, session, _ = _setup(tmp_path)
    try:
        _, saved, selection = _saved(host, source)
        result = edit_learned_region(app=app, host=host, memory=saved, goal='View details', out=tmp_path, prefix='check')
        assert result['region_id'] == selection['region_id']
        assert result['saved']['content']['regions'][0]['bbox'][2] == 118
        assert result['saved']['version_id'] != saved['version_id']
        assert result['panel_save_and_reload'] and not result['application_restart_verified']
        assert backend.commands == []
        assert (tmp_path / 'check-panel.png').is_file()
    finally:
        _close(host, runtime, session)


def test_missing_target_fails_before_editing(tmp_path):
    app = ensure_application()
    host, _, runtime, backend, _, source, session, _ = _setup(tmp_path)
    try:
        _, saved, _ = _saved(host, source)
        with pytest.raises(AssertionError, match='uniquely'):
            edit_learned_region(app=app, host=host, memory=saved, goal='Other button', out=tmp_path, prefix='wrong')
        assert host.facade.load_interface_content(saved['interface_id']) == saved
        assert backend.commands == []
    finally:
        _close(host, runtime, session)
