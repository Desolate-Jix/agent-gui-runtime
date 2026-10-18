import json
from types import SimpleNamespace
import pytest
from app.operation.screen_reading.control_semantics import collect_control_semantics


class Legacy:
    CurrentDefaultAction = "Open"

    def __init__(self, value="https://user:pw@example.com:8443/a?token=x#frag"):
        self.value = value
        self.reads = 0

    @property
    def CurrentValue(self):
        self.reads += 1
        return self.value


class W:
    def __init__(self, typ, parent=None, *, handle=0, pid=20, password=False,
                 role="", popup="", modal=False):
        self.element_info = SimpleNamespace(control_type=typ, element=SimpleNamespace(
            CurrentControlType=50005, CurrentAriaRole=role,
            CurrentAriaProperties=popup, CurrentHelpText="打开新窗口",
            CurrentIsPassword=password))
        self.iface_legacy_iaccessible = Legacy()
        self.iface_window = SimpleNamespace(CurrentIsModal=modal)
        self._parent = parent
        self.handle = handle
        self.pid = pid

    def process_id(self):
        return self.pid

    def parent(self):
        return self._parent

    def legacy_properties(self):
        raise AssertionError("不得批量读取 Legacy 值")


BOUND = SimpleNamespace(handle=10, process_id=20)


def test_real_com_shapes_and_exact_root():
    root = W("Window", handle=10)
    dialog = W("Window", root, modal=True, role="dialog")
    link = W("Hyperlink", dialog, role="link", popup="checked=false;haspopup=dialog")
    result = collect_control_semantics(link, BOUND)
    assert result["complete"] is True
    assert result["control"]["control_type"] == "Hyperlink"
    assert result["control"]["aria_role"] == "link"
    assert result["control"]["haspopup"] == "dialog"
    assert result["ancestry"][0]["modal"] is True
    assert result["navigation"]["destination"] == "https://example.com:8443/a"
    assert result["navigation"]["observation_only"] is True
    assert "打开新窗口" in json.dumps(result, ensure_ascii=False, allow_nan=False)
    assert collect_control_semantics(root, BOUND)["complete"] is True


@pytest.mark.parametrize("pid", [None, -1, 0, True, "20"])
def test_invalid_bound_identity_is_rejected_before_value_reads(pid):
    root = W("Hyperlink", handle=10)
    with pytest.raises(ValueError, match="positive integers"):
        collect_control_semantics(root, SimpleNamespace(handle=10, process_id=pid))
    assert root.iface_legacy_iaccessible.reads == 0


def test_foreign_pid_cycle_and_depth_are_not_complete():
    root = W("Window", handle=10, pid=21)
    child = W("Hyperlink", root)
    assert collect_control_semantics(child, BOUND)["complete"] is False
    assert child.iface_legacy_iaccessible.reads == 0
    root._parent = child
    assert "ancestry_cycle" in collect_control_semantics(child, BOUND)["errors"]
    chain = W("Text", W("Pane", W("Window", handle=10)))
    result = collect_control_semantics(chain, BOUND, max_ancestry=1)
    assert result["complete"] is False and "ancestry_limit_exceeded" in result["errors"]
    assert collect_control_semantics(chain, BOUND, max_ancestry=2)["complete"] is True


@pytest.mark.parametrize("typ,password", [("Edit", False), ("Edit", True), ("Hyperlink", True), ("Hyperlink", None)])
def test_values_never_read_from_edits_passwords_or_unknown_password_state(typ, password):
    root = W("Window", handle=10)
    child = W(typ, root, password=password)
    result = collect_control_semantics(child, BOUND)
    assert child.iface_legacy_iaccessible.reads == 0
    assert result["navigation"]["destination"] is None


@pytest.mark.parametrize("value,expected", [
    ("https://u:p@[::1]:8443/a?key=secret#x", "https://[::1]:8443/a"),
    ("https://host/a?key=secret#x", "https://host/a"),
    ("javascript:alert(1)", None), ("file:///x", None),
    ("https://host:bad/x", None), ("https://host:99999/x", None),
    ("https://ho\nst/x", None), ("https://host\\@evil/x", None),
])
def test_navigation_is_sanitized_observation_not_permission(value, expected):
    child = W("Hyperlink", W("Window", handle=10))
    child.iface_legacy_iaccessible.value = value
    result = collect_control_semantics(child, BOUND)
    assert result["navigation"]["destination"] == expected
    assert result["navigation"]["available"] is (expected is not None)


def test_unknown_and_com_errors_do_not_leak_text_or_fake_aria_role():
    class Broken:
        @property
        def CurrentAriaRole(self):
            raise RuntimeError("secret-token-private-url")
    child = W("Button", W("Window", handle=10))
    child.element_info.element = Broken()
    child.element_info.localized_control_type = "按钮"
    result = collect_control_semantics(child, BOUND)
    assert result["control"]["aria_role"] is None
    assert result["control"]["is_password"] is None
    assert "aria_role_error" in result["errors"]
    assert "secret-token" not in json.dumps(result)


def test_description_does_not_become_navigation():
    child = W("Hyperlink", W("Window", handle=10))
    child.iface_legacy_iaccessible.value = None
    child.iface_legacy_iaccessible.CurrentDescription = "https://example.com/"
    assert collect_control_semantics(child, BOUND)["navigation"]["available"] is False
