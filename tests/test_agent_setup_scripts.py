"""验证真实 PowerShell 配置路径；仅替换联网安装边界。"""

import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

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
    for name in ('agent-runtime-win311.txt', 'agent-runtime-api.txt', 'agent-runtime-api-win.lock.txt'):
        shutil.copy2(ROOT / 'requirements' / name, root / 'requirements')
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
    (['-RecognitionSource', 'local', '-ModelDirectory', 'unused', '-PythonVersion', '3.12'], 'requires Python 3.11'),
])
def test_setup_invalid_route_stops_before_installation(bundle, args, error):
    result = run_script(bundle, 'setup_instant.ps1', *args)
    assert result.returncode != 0
    assert error in result.stdout + result.stderr
    assert not (bundle / '.venv-agent').exists()
    assert not (bundle / 'mcp-config.local.json').exists()


@pytest.mark.parametrize('python_version', ['current', None])
def test_agent_setup_installs_only_light_manifest_and_preserves_local_environment(bundle, tmp_path, python_version):
    if python_version is None and sys.version_info[:2] != (3, 12):
        pytest.skip('The default fresh API environment is Python 3.12; run with that interpreter')
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
$setupArguments = @{RecognitionSource='agent_current'; DataDirectory=$env:UV_TEST_DATA}
if ($env:UV_TEST_VERSION) { $setupArguments.PythonVersion = $env:UV_TEST_VERSION }
& $env:UV_TEST_SETUP @setupArguments
''', encoding='utf-8')
    env = dict(os.environ, UV_TEST_LOG=str(log), UV_TEST_PYTHON=sys.executable,
        UV_TEST_SETUP=str(bundle / 'scripts/setup_instant.ps1'), UV_TEST_DATA=str(bundle / 'data'),
        UV_TEST_VERSION='.'.join(map(str, sys.version_info[:2])) if python_version else '')
    result = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-File', str(driver)],
        env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert not any(c[0] == 'sync' for c in calls)
    installation = next(c for c in calls if c[:2] == ['python', 'install'])
    assert installation[2] == ('.'.join(map(str, sys.version_info[:2])) if python_version else '3.12')
    assert '--no-bin' in installation and '--no-registry' in installation
    pip = next(c for c in calls if c[:2] == ['pip', 'install'])
    assert Path(pip[pip.index('-r') + 1]).name == 'agent-runtime-api-win.lock.txt'
    assert '--require-hashes' in pip
    assert pip[pip.index('--only-binary') + 1] == ':all:'
    assert Path(pip[pip.index('--python') + 1]) == bundle / '.venv-agent/Scripts/python.exe'
    assert marker.read_text(encoding='utf-8') == 'preserve'
    config = json.loads((bundle / 'mcp-config.local.json').read_text(encoding='utf-8'))
    assert Path(config['mcpServers']['agent-review-instant']['command']) == bundle / '.venv-agent/Scripts/python.exe'


@pytest.mark.parametrize('version_request', ['implicit', 'matching', 'different'])
def test_api_setup_preserves_existing_interpreter_and_rejects_in_place_minor_migration(bundle, tmp_path, version_request):
    environment = bundle / '.venv-agent'
    created = subprocess.run([sys.executable, '-I', '-B', '-m', 'venv', '--without-pip', str(environment)],
        capture_output=True, text=True, timeout=30)
    assert created.returncode == 0, created.stderr
    before = (environment / 'pyvenv.cfg').read_bytes()
    driver = tmp_path / 'reuse-driver.ps1'
    log = tmp_path / 'reuse-uv-calls.jsonl'
    driver.write_text('''
$ErrorActionPreference = 'Stop'
function uv {
    [IO.File]::AppendAllText($env:UV_TEST_LOG, (ConvertTo-Json -InputObject @($args) -Compress) + "`n")
    $global:LASTEXITCODE = 0
}
$setupArguments = @{RecognitionSource='agent_current'; DataDirectory=$env:UV_TEST_DATA}
if ($env:UV_TEST_VERSION) { $setupArguments.PythonVersion = $env:UV_TEST_VERSION }
& $env:UV_TEST_SETUP @setupArguments
''', encoding='utf-8')
    current = '.'.join(map(str, sys.version_info[:2]))
    selected = '' if version_request == 'implicit' else current if version_request == 'matching' else ('3.11' if current == '3.12' else '3.12')
    result = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-File', str(driver)],
        env=dict(os.environ, UV_TEST_LOG=str(log), UV_TEST_VERSION=selected,
                 UV_TEST_SETUP=str(bundle / 'scripts/setup_instant.ps1'), UV_TEST_DATA=str(bundle / 'data')),
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=40)
    assert (environment / 'pyvenv.cfg').read_bytes() == before
    if version_request == 'different':
        assert result.returncode != 0
        assert 'separate installation' in result.stdout + result.stderr
        assert not log.exists()
        assert not (bundle / 'mcp-config.local.json').exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        calls = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        assert len(calls) == 1 and calls[0][:2] == ['pip', 'install']
        assert '--require-hashes' in calls[0]
        assert (bundle / 'mcp-config.local.json').is_file()


def test_agent_setup_whatif_has_no_environment_or_config_side_effect(bundle):
    result = run_script(bundle, 'setup_instant.ps1', '-RecognitionSource', 'agent_current', '-WhatIf')
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (bundle / '.venv-agent').exists()
    assert not (bundle / 'mcp-config.local.json').exists()


def test_execution_dependency_group_excludes_qt_and_keeps_desktop():
    groups = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['dependency-groups']
    assert groups.get('execution') == ['mcp==2.1.1', 'httpx==0.28.1']
    assert groups['desktop'] == ['PySide6==6.11.2', 'mcp==2.1.1', 'httpx==0.28.1']


def test_local_setup_selects_locked_execution_and_vista_groups_without_installing(bundle, tmp_path):
    # 只记录联网边界，配置也留在隔离副本，避免生成真实运行配置。
    (bundle / 'scripts/configure_instant.ps1').write_text('''
[CmdletBinding(SupportsShouldProcess = $true)]
param([string]$ModelDirectory,[string]$RecognitionSource,[string]$DataDirectory,[string]$Python)
if ($PSCmdlet.ShouldProcess($PSScriptRoot, 'Record isolated configuration arguments')) {
    [IO.File]::WriteAllText($env:UV_TEST_CONFIG, (ConvertTo-Json -Compress @{ModelDirectory=$ModelDirectory;RecognitionSource=$RecognitionSource;Python=$Python}), [Text.UTF8Encoding]::new($false))
}
''', encoding='utf-8')
    driver = tmp_path / 'local-driver.ps1'
    log = tmp_path / 'local-uv-calls.jsonl'
    configuration = tmp_path / 'isolated-config.json'
    driver.write_text('''
$ErrorActionPreference = 'Stop'
function uv {
    [IO.File]::AppendAllText($env:UV_TEST_LOG, (ConvertTo-Json -InputObject @($args | ForEach-Object { [string]$_ }) -Compress) + "`n", [Text.UTF8Encoding]::new($false))
    $global:LASTEXITCODE = 0
}
& $env:UV_TEST_SETUP -RecognitionSource local -ModelDirectory $env:UV_TEST_MODEL
''', encoding='utf-8')
    env = dict(os.environ, UV_TEST_LOG=str(log), UV_TEST_CONFIG=str(configuration),
               UV_TEST_SETUP=str(bundle / 'scripts/setup_instant.ps1'), UV_TEST_MODEL=str(tmp_path / 'new-model-directory'))
    result = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-File', str(driver)],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert calls == [['python', 'install', '3.11', '--no-bin', '--no-registry'],
                     ['sync', '--frozen', '--group', 'execution', '--group', 'vista']]
    assert json.loads(configuration.read_text(encoding='utf-8'))['RecognitionSource'] == 'local'
    assert not (bundle / '.venv').exists()
    assert not (bundle / '.venv-agent').exists()


def test_local_setup_whatif_and_powershell_syntax_have_no_install_side_effect(bundle):
    # AST 解析只检查语法，不执行安装或配置。
    parsed = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-Command',
        '$tokens=$null; $errors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($env:SETUP_SCRIPT,[ref]$tokens,[ref]$errors); if($errors.Count) { $errors | Out-String | Write-Error; exit 1 }'],
        env=dict(os.environ, SETUP_SCRIPT=str(bundle / 'scripts/setup_instant.ps1')),
        capture_output=True, text=True, encoding='utf-8', timeout=40)
    assert parsed.returncode == 0, parsed.stdout + parsed.stderr
    result = run_script(bundle, 'setup_instant.ps1', '-RecognitionSource', 'local',
                        '-ModelDirectory', str(bundle / 'unused-model'), '-DownloadModel', '-WhatIf')
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (bundle / '.venv').exists()
    assert not (bundle / '.venv-agent').exists()
    assert not (bundle / '.python').exists()
    assert not (bundle / '.setup-cache').exists()
    assert not (bundle / 'unused-model').exists()
    assert not (bundle / 'mcp-config.local.json').exists()


@pytest.mark.parametrize('groups', [
    ['--only-group', 'execution'],
    ['--no-default-groups', '--group', 'execution', '--group', 'vista'],
])
def test_frozen_execution_exports_exclude_qt_without_lock_or_environment_changes(groups):
    uv = shutil.which('uv')
    assert uv, 'existing uv is required for frozen group verification'
    before = (ROOT / 'uv.lock').read_bytes()
    result = subprocess.run([uv, 'export', '--frozen', '--offline', '--no-python-downloads',
                             '--no-hashes', *groups], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    packages = {name.lower() for name in re.findall(r'(?m)^([a-zA-Z0-9_.-]+)==', result.stdout)}
    assert {'mcp', 'httpx'}.issubset(packages)
    assert not packages.intersection({'pyside6', 'pyside6-addons', 'pyside6-essentials', 'shiboken6'})
    assert (ROOT / 'uv.lock').read_bytes() == before
