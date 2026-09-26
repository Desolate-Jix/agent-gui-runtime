"""零输入验收器必须跟随来源，不为 Agent 路线偷偷传入模型路径。"""
from pathlib import Path

import pytest

from scripts import smoke_instant_mcp as smoke


@pytest.mark.parametrize('source,profile', [('agent_current', None), ('agent_delegate', 'vision-luna')])
def test_smoke_agent_arguments_without_model(source, profile):
    args = smoke.server_arguments(Path('bundle'), None, Path('data'), False, source, profile)
    assert '--model-directory' not in args
    assert args[args.index('--recognition-source') + 1] == source
    if profile:
        assert args[args.index('--delegate-profile') + 1] == profile


def test_smoke_local_requires_model_before_start():
    with pytest.raises(ValueError, match='model'):
        smoke.server_arguments(Path('bundle'), None, Path('data'), False, 'local', None)


def test_smoke_delegate_requires_profile_before_start():
    with pytest.raises(ValueError, match='delegate'):
        smoke.server_arguments(Path('bundle'), None, Path('data'), False, 'agent_delegate', None)


def test_smoke_does_not_enable_reserved_external_api():
    with pytest.raises(ValueError, match='external_api'):
        smoke.server_arguments(Path('bundle'), None, Path('data'), False, 'external_api', None)
