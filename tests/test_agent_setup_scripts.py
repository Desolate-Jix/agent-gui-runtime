"""验证真实 PowerShell 配置路径；仅替换联网安装边界。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which('pwsh') or shutil.which('powershell')
pytestmark = pytest.mark.skipif(os.name != 'nt' or not SHELL, reason='Windows PowerShell required')


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / 'bundle with spaces'
    (root / 'scripts').mkdir(parents=True)
    (root / 'requirements').mkdir()
    for name in ('setup_instant.ps1', 'configure_instant.ps1', 'configure_instant_mcp.py'):
        shutil.copy2(ROOT / 'scripts' / name, root / 'scripts' / name)
    shutil.copy2(ROOT / 'requirements/agent-runtime-win311.txt', root / 'requirements')
    return root


def run_script(root, name, *args):
    return subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-File',
        str(root / 'scripts' / name), *args], capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=40)


@pytest.mark.parametrize('source,profile', [('agent_current', None), ('agent_delegate', 'vision-luna')])
def test_configure_agent_source_without_model_generates_correct_route(bundle, source, profile):
    args = ['-RecognitionSource', source, '-Python', sys.executable, '-DataDirectory', str(bundle / 'data')]
    if profile:
        args += ['-DelegateProfile', profile]
    result = run_script(bundle, 'configure_instant.ps1', *args)
    assert result.returncode == 0, result.stdout + result.stderr
    config = json.loads((bundle / 'mcp-config.local.json').read_text(encoding='utf-8'))
    command = config['mcpServers']['agent-review-instant']['args']
    assert Path(command[0]).name == 'start_instant_mcp_admin.py'
    assert command[command.index('--recognition-source') + 1] == source
    assert '--model-directory' not in command
    assert '--allow-local-input' in command
    if profile:
        assert command[command.index('--delegate-profile') + 1] == profile


@pytest.mark.parametrize('args,error', [
    (['-RecognitionSource', 'agent_delegate'], 'requires -DelegateProfile'),
    (['-RecognitionSource', 'agent_current', '-DownloadModel'], 'do not accept'),
    (['-RecognitionSource', 'agent_current', '-ModelDirectory', 'unused'], 'do not accept'),
    (['-RecognitionSource', 'local'], 'requires -ModelDirectory'),
])
def test_setup_invalid_route_stops_before_installation(bundle, args, error):
    result = run_script(bundle, 'setup_instant.ps1', *args)
    assert result.returncode != 0
    assert error in result.stdout + result.stderr
    assert not (bundle / '.venv-agent').exists()
    assert not (bundle / 'mcp-config.local.json').exists()


def test_agent_setup_installs_only_light_manifest_and_preserves_local_environment(bundle, tmp_path):
    # 联网依赖安装替换为命令记录；虚拟环境与最终配置仍实际创建。
    (bundle / '.venv').mkdir()
    marker = bundle / '.venv/local-model-environment.txt'
    marker.write_text('preserve', encoding='utf-8')
    driver = tmp_path / 'install-driver.ps1'
    log = tmp_path / 'uv-calls.jsonl'
    driver.write_text('''
$ErrorActionPreference = 'Stop'
function uv {
    $a = @($args)
    [IO.File]::AppendAllText($env:UV_TEST_LOG, (ConvertTo-Json -InputObject $a -Compress) + "`n")
    if ($a[0] -eq 'venv') {
        & $env:UV_TEST_PYTHON -m venv --without-pip $a[-1]
        if ($LASTEXITCODE -ne 0) { throw 'Test venv creation failed' }
    }
    $global:LASTEXITCODE = 0
}
& $env:UV_TEST_SETUP -RecognitionSource agent_current -DataDirectory $env:UV_TEST_DATA
''', encoding='utf-8')
    env = dict(os.environ, UV_TEST_LOG=str(log), UV_TEST_PYTHON=sys.executable,
        UV_TEST_SETUP=str(bundle / 'scripts/setup_instant.ps1'), UV_TEST_DATA=str(bundle / 'data'))
    result = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-File', str(driver)],
        env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert not any(c[0] == 'sync' for c in calls)
    installation = next(c for c in calls if c[:2] == ['python', 'install'])
    assert '--no-bin' in installation and '--no-registry' in installation
    pip = next(c for c in calls if c[:2] == ['pip', 'install'])
    assert Path(pip[pip.index('-r') + 1]).name == 'agent-runtime-win311.txt'
    assert Path(pip[pip.index('--python') + 1]) == bundle / '.venv-agent/Scripts/python.exe'
    assert marker.read_text(encoding='utf-8') == 'preserve'
    config = json.loads((bundle / 'mcp-config.local.json').read_text(encoding='utf-8'))
    assert Path(config['mcpServers']['agent-review-instant']['command']) == bundle / '.venv-agent/Scripts/python.exe'


def test_agent_setup_whatif_has_no_environment_or_config_side_effect(bundle):
    result = run_script(bundle, 'setup_instant.ps1', '-RecognitionSource', 'agent_current', '-WhatIf')
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (bundle / '.venv-agent').exists()
    assert not (bundle / 'mcp-config.local.json').exists()
