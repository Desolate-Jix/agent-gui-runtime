"""宿主旧请求结算后只读更新状态，不重发输入。"""
from tests.test_workflow_run_panel import panel, connect, wait


def test_visible_idle_host_pending_without_run_refreshes_original_status(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget.show()
    widget._timer.stop()
    client.pending_ids = ['original-input-id']
    client.report = None
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    widget._timer.stop()
    assert widget._run is None and widget._pending is None
    assert widget._host_pending_ids == ['original-input-id']
    assert not widget.run_button.isEnabled()
    assert not widget.vision_checkbox.isEnabled()
    before = client.connect_calls
    widget._poll_visible()
    wait(app, lambda: not widget.is_busy)
    widget._timer.stop()
    assert client.connect_calls == before + 1
    assert widget._host_pending_ids == ['original-input-id']
    assert not widget.run_button.isEnabled()
    client.pending_ids = []
    widget._poll_visible()
    wait(app, lambda: not widget.is_busy)
    widget._timer.stop()
    assert client.connect_calls == before + 2
    assert widget._host_pending_ids == []
    assert '旧请求未完成' not in widget.status_label.text()
    assert widget.vision_checkbox.isEnabled()
    assert not client.calls
    widget.close_client()
    widget.close()


def test_hidden_closing_busy_host_pending_does_not_refresh(tmp_path, monkeypatch):
    app, widget, clients = panel(tmp_path)
    connect(app, widget, clients)
    widget._timer.stop()
    widget._host_pending_ids = ['original-input-id']
    calls = []
    monkeypatch.setattr(widget, 'refresh', lambda: calls.append('refresh'))
    widget.hide()
    widget._poll_visible()
    widget.show()
    widget._close_requested = True
    widget._poll_visible()
    widget._close_requested = False
    monkeypatch.setattr(type(widget), 'is_busy', property(lambda self: True))
    widget._poll_visible()
    assert calls == []
    widget.close_client()
    widget.close()
