"""工作台离屏真实编辑保存重开探针；不连接执行宿主。"""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import time
import sys


def check():
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    from app.learning_memory.editor_client import MemoryEditorClient
    from app.learning_memory.workflow_steps_pane import WorkflowStepsPane
    from scripts.check_image_feature_closure import _fresh_learning, check as check_images
    image_evidence = check_images()
    app = QApplication.instance() or QApplication([])

    def wait(predicate):
        deadline = time.monotonic() + 15
        while not predicate():
            app.processEvents()
            if time.monotonic() >= deadline:
                raise TimeoutError('offline image editor did not become ready')
            time.sleep(.01)

    with tempfile.TemporaryDirectory(prefix='learning-image-closure-') as directory:
        session, root, draft, after = _fresh_learning(Path(directory))

        def open_page(load_draft=False):
            pane = WorkflowStepsPane(MemoryEditorClient(root), session)
            wait(lambda: pane.snapshot is not None and not pane.is_busy)
            if load_draft:
                wait(lambda: pane.open_learning_button.isEnabled())
                pane.open_learning_button.click()
            app.processEvents()
            return pane

        pane = open_page(True)
        try:
            editor = pane.rules_editor.image_check_editor
            assert editor.enabled.isChecked()
            assert editor.source.currentData()['reference_sha256'] == after['sha256']
            assert editor.canvas._pixmap_item is not None
            editor.threshold.setValue(.91)
            pane.save_button.click()
            assert not pane.dirty, pane.status.text()
            saved = deepcopy(pane.snapshot)
        finally:
            pane.close(); pane.facade.close()
        pane = open_page()
        try:
            assert pane.snapshot == saved
            assert pane.rules_editor.image_check_editor.threshold.value() == .91
            pane.rules_editor.image_check_editor.enabled.setChecked(False)
            pane.save_button.click()
            assert not pane.dirty, pane.status.text()
            disabled = deepcopy(pane.snapshot)
            assert disabled['definition']['steps'][0]['verification'] == {'kind': 'agent_judgment'}
        finally:
            pane.close(); pane.facade.close()
        pane = open_page()
        try:
            assert pane.snapshot == disabled
            assert not pane.rules_editor.image_check_editor.enabled.isChecked()
        finally:
            pane.close(); pane.facade.close()
    runtime_root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])).resolve()
    for name, module in tuple(sys.modules.items()):
        if name.startswith(('app.', 'modules.', 'scripts.')) and getattr(module, '__file__', None):
            if not Path(module.__file__).resolve().is_relative_to(runtime_root):
                raise ValueError('original source leaked into learning image feature: ' + name)
    return {'passed': True, 'check': 'learning_image_feature.v1',
            'png_match': image_evidence['png_match'], 'dependencies': image_evidence['dependencies'],
            'source_preview': True, 'save_reopen': True, 'disable_persisted': True,
            'input_executed': False, 'host_started': False}
