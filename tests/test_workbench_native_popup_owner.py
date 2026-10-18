"""不创建原生窗口，验证严格的 HWND 归属写入合同。"""
import pytest
from app.learning_memory import workbench_popup_ownership as module


class NativeWindows:
    def __init__(self):
        self.main = 0x123456789
        self.popup = 0x234567890
        self.identities = {self.main: (17, 29), self.popup: (17, 29)}
        self.styles = {self.main: 0, self.popup: 0}
        self.owners = {self.main: 0, self.popup: 0}
        self.roots = {self.main: self.main, self.popup: self.popup}
        self.writes = []
        self.failure = None
        self.bad_readback = False

    def valid(self, hwnd):
        return hwnd in self.identities

    def identity(self, hwnd):
        return self.identities[hwnd]

    def style(self, hwnd):
        return self.styles[hwnd]

    def owner(self, hwnd):
        return self.owners[hwnd]

    def root_owner(self, hwnd):
        return self.roots[hwnd]

    def set_owner(self, hwnd, owner):
        self.writes.append((hwnd, owner))
        if self.failure:
            raise self.failure
        if not self.bad_readback:
            self.owners[hwnd] = owner
            self.roots[hwnd] = owner


def bind(native):
    assert hasattr(module, 'bind_native_popup'), 'Qt transientParent lacks native owner verification'
    return module.bind_native_popup(native.main, native.popup, backend=native)


def test_ownerless_popup_gets_exact_64bit_owner_and_root_readback():
    native = NativeWindows()
    assert bind(native)
    assert native.writes == [(native.popup, native.main)]
    assert native.owner(native.popup) == native.main
    assert native.root_owner(native.popup) == native.main


@pytest.mark.parametrize('change', ['invalid', 'pid', 'thread', 'child', 'foreign_owner', 'foreign_main_root'])
def test_native_identity_or_foreign_root_rejected_before_write(change):
    native = NativeWindows()
    if change == 'invalid': native.identities.pop(native.popup)
    if change == 'pid': native.identities[native.popup] = (17, 99)
    if change == 'thread': native.identities[native.popup] = (99, 29)
    if change == 'child': native.styles[native.popup] = 0x40000000
    if change == 'foreign_owner':
        native.owners[native.popup] = 555
        native.roots[native.popup] = 555
    if change == 'foreign_main_root': native.roots[native.main] = 555
    assert not bind(native)
    assert native.writes == []


@pytest.mark.parametrize('failure', ['setter', 'readback'])
def test_native_failure_is_false_with_readable_diagnostic(failure, caplog):
    native = NativeWindows()
    if failure == 'setter': native.failure = OSError('denied')
    else: native.bad_readback = True
    assert not bind(native)
    assert 'popup' in caplog.text.lower()


def test_new_hwnd_rebinds_without_cached_identity():
    native = NativeWindows()
    assert bind(native)
    new = native.popup + 1
    native.identities[new] = (17, 29)
    native.styles[new] = 0
    native.owners[new] = 0
    native.roots[new] = new
    assert module.bind_native_popup(native.main, new, backend=native)
    assert native.writes[-1] == (new, native.main)


@pytest.mark.parametrize('error', [0, 5])
def test_zero_previous_owner_distinguishes_last_error(error, monkeypatch):
    import ctypes
    native = module.WindowsPopupBackend.__new__(module.WindowsPopupBackend)
    native.set_long = lambda *args: 0
    cleared = []
    monkeypatch.setattr(ctypes, 'set_last_error', lambda value: cleared.append(value))
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: error)
    if error:
        with pytest.raises(OSError): native.set_owner(0x234567890, 0x123456789)
    else:
        native.set_owner(0x234567890, 0x123456789)
    assert cleared == [0]


def test_ctypes_setter_uses_pointer_sized_signature_without_loading_user32(monkeypatch):
    import ctypes
    from types import SimpleNamespace
    class Function:
        def __call__(self, *_args): return 0
    api = SimpleNamespace(**{name: Function() for name in ('IsWindow', 'GetWindow', 'GetAncestor',
        'GetWindowThreadProcessId', 'GetWindowLongPtrW', 'SetWindowLongPtrW', 'GetWindowLongW', 'SetWindowLongW')})
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: api)
    native = module.WindowsPopupBackend()
    assert native.set_long.restype is ctypes.c_ssize_t
    assert native.set_long.argtypes[-1] is ctypes.c_ssize_t
    assert native.get_long.restype is ctypes.c_ssize_t
    expected = api.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else api.SetWindowLongW
    assert native.set_long is expected
