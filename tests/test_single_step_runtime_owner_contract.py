import importlib
import subprocess
import sys
import threading
from contextlib import contextmanager

import pytest


@pytest.mark.parametrize("first", ["app.desktop_review", "app.execution"])
def test_owner_import_is_lazy_and_preserves_identity(first):
    code = '''
import importlib, sys, threading
before = threading.enumerate()
left = importlib.import_module(sys.argv[1] + '.single_step_runtime_owner')
right = importlib.import_module(('app.execution' if sys.argv[1] == 'app.desktop_review' else 'app.desktop_review') + '.single_step_runtime_owner')
assert left is right
assert left.__name__ == 'app.execution.single_step_runtime_owner'
for symbol in ('RuntimeOwnerError', 'RuntimeOwnerProxy', 'SerialRuntimeOwner', '_STOP', '_initialize_com', '_finalize_com'):
    assert getattr(left, symbol) is getattr(right, symbol)
assert threading.enumerate() == before
assert 'ctypes' not in sys.modules
assert not any(name.startswith(('PySide', 'PyQt')) or 'review_editor' in name or 'workflow_editor' in name for name in sys.modules)
'''
    result = subprocess.run([sys.executable, "-c", code, first], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path", ["app.desktop_review", "app.execution"])
def test_initializer_patch_and_serial_reentry_scopes_cleanup(monkeypatch, tmp_path, path):
    module = importlib.import_module(path + ".single_step_runtime_owner")
    canonical = importlib.import_module("app.execution.single_step_runtime_owner")
    from app.core.runtime_artifacts import _runtime_output_root
    runtime_output_root = _runtime_output_root.get
    events = []

    @contextmanager
    def scope():
        events.append(("enter", threading.get_ident(), runtime_output_root()))
        try:
            yield
        finally:
            events.append(("exit", threading.get_ident(), runtime_output_root()))

    monkeypatch.setattr(module, "_initialize_com", lambda: events.append(("init", threading.get_ident(), runtime_output_root())))
    monkeypatch.setattr(module, "_finalize_com", lambda: events.append(("finish", threading.get_ident(), runtime_output_root())))
    before = runtime_output_root()
    owner = canonical.SerialRuntimeOwner(output_root=tmp_path, call_scope=scope)
    failure = ValueError("call failed")
    try:
        thread = owner.call(lambda: owner.call(threading.get_ident))
        assert thread == owner.thread_id != threading.get_ident()
        with pytest.raises(ValueError) as caught:
            owner.call(lambda: (_ for _ in ()).throw(failure))
        assert caught.value is failure
        assert owner.call(lambda: 42) == 42
        with pytest.raises(canonical.RuntimeOwnerError, match="cannot join itself"):
            owner.call(owner.close)
    finally:
        owner.close()
    owner.close()
    assert runtime_output_root() == before
    assert {event[1] for event in events} == {thread}
    assert {event[2] for event in events} == {tmp_path.resolve()}
    assert sum(event[0] == "enter" for event in events) == sum(event[0] == "exit" for event in events)
    assert sum(event[0] == "init" for event in events) == 1
    assert sum(event[0] == "finish" for event in events) == 1
    assert not owner._thread.is_alive()
    with pytest.raises(canonical.RuntimeOwnerError) as closed:
        owner.call(lambda: None)
    assert closed.value.code == "runtime_owner_closed"


def test_initialization_and_finalization_failures_clean_up():
    module = importlib.import_module("app.execution.single_step_runtime_owner")
    finalizations = []

    def fail():
        raise ValueError("lifecycle failure")

    owner = module.SerialRuntimeOwner(initializer=fail, finalizer=lambda: finalizations.append(True))
    try:
        for _ in range(2):
            with pytest.raises(module.RuntimeOwnerError) as caught:
                owner.call(lambda: None)
            assert caught.value.code == "runtime_owner_initialization_failed"
    finally:
        owner.close()
    assert not owner._thread.is_alive()

    assert finalizations == []
    owner = module.SerialRuntimeOwner(initializer=lambda: None, finalizer=fail)
    assert owner.call(lambda: 7) == 7
    with pytest.raises(module.RuntimeOwnerError) as caught:
        owner.close()
    assert caught.value.code == "runtime_owner_finalization_failed"
    assert isinstance(caught.value.__cause__, ValueError)
    assert not owner._thread.is_alive()


def test_proxy_keeps_all_host_methods_on_owner_thread():
    module = importlib.import_module("app.execution.single_step_runtime_owner")
    calls = []

    class Runtime:
        def __getattr__(self, name):
            def invoke(**kwargs):
                calls.append((name, kwargs, threading.get_ident()))
                return b"image" if name == "get_local_grounded_image" else name
            return invoke

    owner = module.SerialRuntimeOwner(initializer=lambda: None, finalizer=lambda: None)
    proxy = module.RuntimeOwnerProxy(owner, Runtime())
    methods = ("get_local_grounded_confirmation", "get_local_grounded_image",
               "consume_grounded_confirmation", "cancel_grounded_review",
               "release_local_fresh_recovery")
    try:
        for name in methods:
            value = getattr(proxy, name)(token="probe")
            assert value == (b"image" if name == "get_local_grounded_image" else name)
    finally:
        owner.close()
    assert [call[0] for call in calls] == list(methods)
    assert all(call[1] == {"token": "probe"} and call[2] == owner.thread_id for call in calls)
