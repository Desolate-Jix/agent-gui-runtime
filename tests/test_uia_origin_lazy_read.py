"""地址读取只遍历当前有用前缀，不复用先前 URL。"""

from types import SimpleNamespace

from app.agent.windows_uia_origin_reader import WindowsUIAOriginReader


class Edit:
    def __init__(self, value):
        self.value = value
        self.reads = 0

    def get_value(self):
        self.reads += 1
        return self.value

    def window_text(self):
        return ""


class LazyRoot:
    def __init__(self, controls):
        self.controls = controls
        self.visited = 0
        self.scans = 0

    def descendants(self, **kwargs):
        raise AssertionError("full enumeration must not be requested")

    def iter_descendants(self, **kwargs):
        assert kwargs == {"control_type": "Edit"}
        self.scans += 1
        for control in self.controls:
            self.visited += 1
            if isinstance(control, Exception):
                raise control
            yield control


def reader_for(root):
    manager = SimpleNamespace(get_bound_window=lambda: SimpleNamespace(handle=4242, process_id=9001))
    desktop = SimpleNamespace(window=lambda **kwargs: root)
    return WindowsUIAOriginReader(window_manager=manager, desktop_factory=lambda **kwargs: desktop)


def test_large_edit_tree_stops_at_first_valid_url():
    first = Edit("https://www.google.com/maps?private=query")
    root = LazyRoot([first] + [Edit("not an address") for _ in range(9999)])

    result = reader_for(root).read_origin(4242)

    assert result["status"] == "observed"
    assert result["origin"] == "https://www.google.com"
    assert result["edit_control_count"] == 1
    assert result["edit_control_count_scope"] == "inspected_prefix"
    assert root.visited == 1
    assert sum(control.reads for control in root.controls) == 1
    assert "private" not in str(result)


def test_invalid_prefix_keeps_original_first_valid_selection():
    root = LazyRoot([Edit("not a URL"), Edit("ftp://invalid.example"),
                     Edit("https://first.example"), Edit("https://later.example")])
    result = reader_for(root).read_origin(4242)
    assert result["origin"] == "https://first.example"
    assert result["edit_control_count"] == root.visited == 3


def test_every_check_reads_live_value_and_new_control_tree():
    field = Edit("https://first.example/a")
    root = LazyRoot([field])
    reader = reader_for(root)
    assert reader.read_origin(4242)["origin"] == "https://first.example"
    field.value = "https://second.example/b"
    assert reader.read_origin(4242)["origin"] == "https://second.example"
    root.controls = [Edit("https://third.example/c")]
    assert reader.read_origin(4242)["origin"] == "https://third.example"
    assert root.scans == 3
    assert field.reads == 2


def test_no_url_exhausts_current_tree_and_refuses():
    root = LazyRoot([Edit("not a URL"), Edit("https://user:secret@example.com")])
    result = reader_for(root).read_origin(4242)
    assert result["status"] == "unavailable"
    assert result["reason"] == "no_http_origin"
    assert result["edit_control_count"] == root.visited == 2
    assert "secret" not in str(result)


def test_iterator_failure_is_not_hidden_by_another_scan():
    root = LazyRoot([Edit("not a URL"), RuntimeError("private data"), Edit("https://later.example")])
    result = reader_for(root).read_origin(4242)
    assert result["status"] == "unavailable"
    assert result["reason"] == "uia_read_failed"
    assert result["error_type"] == "RuntimeError"
    assert result["edit_control_count"] == 1
    assert root.scans == 1
    assert "private" not in str(result)
