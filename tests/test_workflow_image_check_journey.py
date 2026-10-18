"""新学习原图经真实编辑门面保存重开，关闭设置持久保留。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import os

from PIL import Image, ImageDraw
from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.editor_client import MemoryEditorClient
from app.learning_memory.receipt_adapter import content_hash
from app.learning_memory.workspace import MemoryWorkspace
from test_learning_observation_source import observation_scene
from test_workflow_steps_ui import qt_app, _wait


def _fresh_learning(tmp_path, with_output=False):
    _root, _event, observation = observation_scene.__wrapped__(tmp_path)
    session = tmp_path / 'new-image-learning'
    (session / 'responses').mkdir(parents=True)
    store = LearningEventStore(session)
    started = store.control('learning_start', {'scope': 'workflow',
        'title': '图像核验新合成任务', 'project_id': 'new-image-journey'}, 'start')
    command = {'kind': 'step', 'operation': 'execute_recognition_plan',
        'request': {'goal': 'Search', 'click_kind': 'single'}}
    ticket = store.prepare('open-detail', command, None)
    before_path, after_path = session / 'before.png', session / 'after.png'
    Image.new('RGB', (160, 100), 'white').save(before_path)
    image = Image.new('RGB', (160, 100), 'white')
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((80, 40, 145, 70), fill='#124e87')
    drawing.text((84, 45), 'DETAIL 731', fill='white')
    drawing.line((84, 64, 140, 64), fill='yellow', width=2)
    image.save(after_path)
    observation = deepcopy(observation)
    observation.update(event_id='open-detail', command_sha256=ticket['command_sha256'])
    observation['frame'].update(image_path=str(before_path), sha256=sha256(before_path.read_bytes()).hexdigest())
    after = {'image_path': str(after_path), 'sha256': sha256(after_path.read_bytes()).hexdigest(),
        'capture_id': 'new-after', 'window_size': {'width': 160, 'height': 100}}
    result = {'phase': 'returned', 'capture': after, 'observation': {'capture': after},
        'response': {'success': True, 'data': {'result': {
            'execution_path': {'action_executed': True}, 'learning_observation': observation}}}}
    write_json_snapshot(session / 'responses/open-detail.json', {
        'command': command, 'status': 'returned', 'learning_binding': ticket, 'result': result})
    store.record('open-detail', ticket)
    event = store.control('learning_event', {'event_id': 'open-detail'}, 'read')['event']
    store.control('learning_review', {'review': {
        'event_id': 'open-detail', 'event_sha256': content_hash(event), 'verdict': 'success',
        'reviewer': 'synthetic-ui-test', 'reason': '新合成离屏证据，不派发桌面输入',
        'before': {'interface_key': 'desk', 'state_key': 'home', 'meaning': '查询页',
            'frame_sha256': observation['frame']['sha256']},
        'after': {'interface_key': 'desk', 'state_key': 'detail', 'meaning': '详情页',
            'frame_sha256': after['sha256']}}}, 'review')
    stopped = store.control('learning_stop', {}, 'stop')
    request = stopped['synthesis']['synthesis_request']
    annotation = {'title': '打开详情', 'verification': {'kind': 'agent_judgment'}}
    if with_output:
        annotation['outputs'] = [{'name': 'detail', 'type': 'text'}]
    reply = store.control('learning_workflow', {'action': 'synthesis_complete',
        'synthesis_id': request['synthesis_id'], 'source_sha256': request['source_sha256'],
        'parameter_bindings': {}, 'annotations': {'open-detail': annotation}}, 'synthesis')
    assert reply['status'] == 'draft_ready', reply
    return session, tmp_path / 'memory-library', reply['draft'], after


def _open(app, root, session, workflow_id):
    from app.learning_memory.workflow_steps_pane import WorkflowStepsPane
    pane = WorkflowStepsPane(MemoryEditorClient(root), session)
    pane.resize(1500, 1000); pane.show()
    _wait(app, lambda: pane.snapshot is not None and not pane.is_busy)
    assert pane.snapshot['workflow_id'] == workflow_id
    pane.editor_tabs.setCurrentIndex(3)
    app.processEvents()
    return pane


def test_fresh_image_source_editor_save_reopen_and_disable(qt_app, tmp_path):
    from app.learning_memory.workbench_i18n import initialize_i18n
    language = initialize_i18n(qt_app, tmp_path / 'image-ui-preferences.json', 'zh-CN')
    session, root, draft, after = _fresh_learning(tmp_path)
    config = draft['definition']['steps'][0]['verification']['image_check']
    assert config['reference_sha256'] == after['sha256']
    pane = _open(qt_app, root, session, draft['workflow_id'])
    _wait(qt_app, lambda: pane.open_learning_button.isEnabled())
    pane.open_learning_button.click()
    image_editor = pane.rules_editor.image_check_editor
    assert image_editor.enabled.isChecked()
    assert image_editor.source.currentData()['reference_sha256'] == after['sha256']
    assert image_editor.canvas._pixmap_item is not None
    assert pane.snapshot['project_snapshot_id']
    pane.save_button.click()
    assert not pane.dirty, pane.status.text()
    original = deepcopy(pane.snapshot)
    assert '结果规则 1/1' in pane.definition_summary.text()
    assert '图像核验 1 步' in pane.definition_summary.text()
    assert '未匹配时由 Agent 审核' in pane.definition_summary.text()
    assert image_editor.mapTo(pane.rules_editor, image_editor.rect().topLeft()).y() < 150
    language.set_language('en-US'); qt_app.processEvents()
    assert 'image verification 1 steps' in pane.definition_summary.text()
    assert 'Agent review when unmatched' in pane.definition_summary.text()
    assert image_editor.enabled.text() == 'Local image verification (optional)'
    assert pane.snapshot == original and not pane.dirty
    language.set_language('zh-CN'); qt_app.processEvents()
    image_editor.threshold.setValue(.91)
    original_box = image_editor.box('template_bbox')
    adjusted = [original_box[0] + 1, original_box[1], original_box[2] - 1, original_box[3]]
    image_editor.set_box('template_bbox', adjusted)
    pane.save_button.click()
    assert not pane.dirty, pane.status.text()
    revised = deepcopy(pane.snapshot)
    assert revised['program_id'] != original['program_id']
    assert revised['definition']['steps'][0]['verification']['image_check']['template_bbox'] == adjusted
    capture = os.environ.get('IMAGE_CHECK_JOURNEY_CAPTURE')
    if capture:
        from PySide6.QtGui import QColor, QPalette
        palette = pane.rules_editor.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor('white'))
        pane.rules_editor.setPalette(palette)
        pane.rules_editor.setAutoFillBackground(True)
        qt_app.processEvents()
        assert pane.rules_editor.grab().save(capture)
        assert pane.grab().save(str(Path(capture).with_name('image-check-page.png')))
    pane.close(); pane.facade.close()
    reopened = _open(qt_app, root, session, draft['workflow_id'])
    assert reopened.snapshot == revised
    assert reopened.rules_editor.image_check_editor.enabled.isChecked()
    assert reopened.rules_editor.image_check_editor.threshold.value() == .91
    reopened.rules_editor.image_check_editor.enabled.setChecked(False)
    reopened.save_button.click()
    assert not reopened.dirty, reopened.status.text()
    disabled = deepcopy(reopened.snapshot)
    assert disabled['definition']['steps'][0]['verification'] == {'kind': 'agent_judgment'}
    reopened.close(); reopened.facade.close()
    final = _open(qt_app, root, session, draft['workflow_id'])
    assert final.snapshot == disabled
    assert not final.rules_editor.image_check_editor.enabled.isChecked()
    assert not final.dirty
    final.close(); final.facade.close()
    with MemoryWorkspace(root) as library:
        assert library.load_workflow_program(draft['workflow_id'], original['program_id']) == original
        assert library.load_workflow_program(draft['workflow_id'], revised['program_id']) == revised
    assert not list((session / 'commands').glob('*.json'))


def test_output_draft_has_no_forced_image_configuration(qt_app, tmp_path):
    session, root, draft, _after = _fresh_learning(tmp_path, with_output=True)
    assert draft['definition']['steps'][0]['verification'] == {'kind': 'agent_judgment'}
    pane = _open(qt_app, root, session, draft['workflow_id'])
    _wait(qt_app, lambda: pane.open_learning_button.isEnabled())
    pane.open_learning_button.click()
    editor = pane.rules_editor.image_check_editor
    assert not editor.enabled.isChecked()
    assert not editor.enabled.isEnabled()
    assert pane.rules_editor.rules('click')[0] == {'kind': 'agent_judgment'}
    assert pane.rules_editor.validation_error is None
    pane.save_button.click()
    assert not pane.dirty, pane.status.text()
    saved = deepcopy(pane.snapshot)
    pane.close(); pane.facade.close()
    reopened = _open(qt_app, root, session, draft['workflow_id'])
    assert reopened.snapshot == saved
    assert reopened.definition['steps'][0]['outputs'] == [{'name': 'detail', 'type': 'text'}]
    assert not reopened.rules_editor.image_check_editor.enabled.isEnabled()
    reopened.close(); reopened.facade.close()
