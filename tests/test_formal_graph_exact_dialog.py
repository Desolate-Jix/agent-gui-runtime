from copy import deepcopy
import time

from PySide6.QtWidgets import QApplication, QCheckBox

from app.desktop_review.exact_dialog import ExactReviewDialog
from app.agent.workflow_versions import PUBLICATION_FIELDS, make_record
from test_formal_graph_exact_review import _runtime, _correct_graph

_APP = QApplication.instance() or QApplication([])


def _wait(dialog):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        time.sleep(0.01)
        _APP.processEvents()
        if not dialog._busy and not dialog._jobs:
            return
    raise AssertionError('graph exact dialog worker did not finish')


def test_graph_dialog_prepares_reviews_and_compiles_the_pinned_graph(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    graph = _correct_graph(facade, 'native-graph-dialog')
    dialog = None
    try:
        dialog = ExactReviewDialog(facade, graph)
        assert str(graph['revision']) in dialog.pin_label.text()
        assert graph['content_sha256'] in dialog.pin_label.text()
        assert dialog.step_relationship_table.isHidden()
        dialog.application_display_name.setText('Fresh Editor')
        dialog.application_identity.setText('fresh-editor.exe')
        dialog.prepare()
        _wait(dialog)
        assert dialog.review is not None, dialog.status_label.text()
        assert dialog.review['contract_version'] == 'desktop_graph_exact_review_v1'
        assert dialog.review['graph_sha256'] == graph['content_sha256']
        assert not any(item['confirmed'] for item in dialog.review['subjects'])
        for row in range(dialog.subject_table.rowCount()):
            check = dialog.subject_table.cellWidget(row, 0)
            assert isinstance(check, QCheckBox)
            check.setChecked(True)
        dialog.record_decisions()
        _wait(dialog)
        assert all(item['confirmed'] for item in dialog.review['subjects'])
        dialog.compile_review()
        _wait(dialog)
        assert dialog.review['status'] == 'compiled', dialog.status_label.text()
        assert dialog.review['compile_receipt_id']
        assert facade.load_graph_revision(graph['logical_workflow_id']) == graph
        dialog._published({'status': 'current', 'logical_workflow_id': 'workflow-' + '0' * 64})
        assert '\u4e0d\u5339\u914d' in dialog.status_label.text()
        dialog.publish_review()
        _wait(dialog)
        assert '\u5df2\u6536\u5230\u5165\u5e93\u56de\u6267' in dialog.status_label.text()
        published = facade.publish_exact_review(dialog.review['compile_receipt_id'])
        for field, wrong_value in (
            ('graph_sha256', '0' * 64), ('graph_revision', False),
            ('approval_revision', False), ('review_ref', '0' * 64),
            ('version_id', 'version-' + '0' * 64), ('artifact_is_authorization', True),
            ('execute_binding_enabled', True), ('current', False),
        ):
            invalid_receipt = deepcopy(published)
            invalid_receipt[field] = wrong_value
            dialog._published(invalid_receipt)
            assert '\u4e0d\u5339\u914d' in dialog.status_label.text(), field
        unrelated_asset_receipt = {
            **published,
            **make_record({key: published[key] for key in PUBLICATION_FIELDS}, 'unrelated_asset', '0' * 64),
        }
        dialog._published(unrelated_asset_receipt)
        assert '\u4e0d\u5339\u914d' in dialog.status_label.text()
        before = deepcopy(dialog.review)
        invalid = deepcopy(before)
        invalid['graph_sha256'] = '0' * 64
        dialog._compiled(invalid, before['approval_revision'])
        assert dialog.review == before
        assert '\u4e0d\u5339\u914d' in dialog.status_label.text()
    finally:
        if dialog is not None:
            _wait(dialog)
            dialog.close()
        facade.close()
        store.close()
