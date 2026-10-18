import pytest

from app.vision import model_environment as module


def test_minimal_windows_worker_env_uses_native_extension_and_actual_account(monkeypatch):
    monkeypatch.setattr(module.os, 'getlogin', lambda: 'runtime-account')
    original = {'SystemRoot': r'C:\Windows', 'PATH': 'preserved'}
    result = module.model_worker_environment(original, platform='nt')
    assert result['PATHEXT'] == '.EXE'
    assert result['USERNAME'] == 'runtime-account'
    assert result['PATH'] == 'preserved'
    assert original == {'SystemRoot': r'C:\Windows', 'PATH': 'preserved'}


@pytest.mark.parametrize('key', ['USERNAME', 'LOGNAME', 'USER', 'LNAME'])
def test_existing_user_identity_and_extensions_are_not_overridden(monkeypatch, key):
    monkeypatch.setattr(module.os, 'getlogin', lambda: pytest.fail('existing account must be retained'))
    original = {key: 'explicit-account', 'PATHEXT': '.COM;.EXE;.CMD'}
    assert module.model_worker_environment(original, platform='nt') == original


def test_non_windows_environment_is_unchanged(monkeypatch):
    monkeypatch.setattr(module.os, 'getlogin', lambda: pytest.fail('not Windows'))
    assert module.model_worker_environment({'PATH': '/usr/bin'}, platform='posix') == {'PATH': '/usr/bin'}


def test_missing_account_lookup_is_explicit_not_guessed(monkeypatch):
    def fail():
        raise OSError('account lookup unavailable')
    monkeypatch.setattr(module.os, 'getlogin', fail)
    with pytest.raises(OSError, match='account lookup unavailable'):
        module.model_worker_environment({}, platform='nt')


def test_environment_keys_are_case_insensitive_on_windows(monkeypatch):
    monkeypatch.setattr(module.os, 'getlogin', lambda: pytest.fail('existing account must be retained'))
    original = {'username': 'explicit-account', 'pathext': '.EXE'}
    assert module.model_worker_environment(original, platform='nt') == original
