"""在新目录冻结学习工作台，复用维护源码包和已有构建工具。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_component_sources import copy_component_sources


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build_learning_source(root, output):
    root = Path(root).resolve()
    resources = ['LICENSE', 'packaging/learning_workbench.spec', 'packaging/learning_readme.md']
    resources += [path.relative_to(root).as_posix() for path in
                  (root / 'app/learning_memory/translations').glob('*') if path.suffix in {'.ts', '.qm'}]
    return copy_component_sources(root, output, ['scripts/start_learning_workbench.py'],
        resources=resources, forbidden=('app/instant_mcp.py', 'scripts/run_local_step_session.py',
            'app/desktop_review/single_step_coordinator.py', 'app/execution/input_sequence.py',
            'app/execution/form_fill.py', 'app/vision/agent_command_jobs.py'))


def verify_learning_source(source, python, working):
    rows = []
    for language in ('zh-CN', 'en-US'):
        data = working / ('source-data-' + language)
        data.mkdir()
        report = working / ('source-startup-' + language + '.json')
        result = subprocess.run([str(python), '-I', '-B', '-X', 'utf8',
            str(source / 'scripts/start_learning_workbench.py'), '--data-dir', str(data),
            '--check-startup', str(report), '--check-language', language], cwd=working,
            env=clean_environment(python), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=40, check=False)
        (working / ('source-stderr-' + language + '.bin')).write_bytes(result.stderr)
        evidence = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else None
        if result.returncode != 0 or not evidence or not evidence.get('passed') or evidence.get('language') != language:
            raise RuntimeError('isolated learning entrypoint failed: ' + str(report))
        if Path(evidence['runtime_root']).resolve() != source.resolve():
            raise ValueError('learning entrypoint imported another source root')
        rows.append(evidence)
    report = working / 'source-image-feature.json'
    result = subprocess.run([str(python), '-I', '-B', '-X', 'utf8',
        str(source / 'scripts/start_learning_workbench.py'), '--check-image-feature', str(report)],
        cwd=working, env=clean_environment(python), capture_output=True, timeout=90, check=False)
    (working / 'source-image-feature-stderr.bin').write_bytes(result.stderr)
    evidence = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else None
    if result.returncode or not evidence or not evidence.get('passed'):
        raise RuntimeError('isolated learning image feature failed: ' + str(report))
    if Path(evidence['runtime_root']).resolve() != source.resolve():
        raise ValueError('learning image feature imported another source root')
    rows.append(evidence)
    return rows


def require_new_output(path, parent):
    parent = Path(parent)
    if not parent.is_absolute() or not parent.is_dir():
        raise ValueError('output parent must be an existing absolute directory')
    path, parent = Path(path).resolve(), parent.resolve()
    if path == parent or not path.is_relative_to(parent):
        raise ValueError('output must be a new child of the explicit parent')
    if path.exists():
        raise FileExistsError(str(path))
    return path


def install_source_payload(source, runtime):
    source, runtime = Path(source).resolve(), Path(runtime).resolve()
    manifest = source / 'MANIFEST.json'
    rows = json.loads(manifest.read_text(encoding='utf-8'))['files']
    copies = []
    seen = set()
    # 完整预检后再复制，不能覆盖冻结依赖或以部分源码冒充同根宿主。
    for row in rows:
        relative = Path(row['path'])
        origin, target = (source / relative).resolve(), (runtime / relative).resolve()
        if relative.is_absolute() or '..' in relative.parts or relative in seen or not origin.is_relative_to(source) or not target.is_relative_to(runtime):
            raise ValueError('invalid source manifest path')
        seen.add(relative)
        if origin.stat().st_size != row['bytes'] or sha256(origin) != row['sha256']:
            raise ValueError('source differs from its manifest')
        copies.append((origin, target))
    copies.append((manifest, runtime / 'MANIFEST.json'))
    for origin, target in copies:
        if target.exists() and (not target.is_file() or sha256(target) != sha256(origin)):
            raise FileExistsError('frozen payload conflicts with maintained source: ' + str(target))
    for origin, target in copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(origin, target)


def clean_environment(python):
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in {'PATH', 'PYTHONPATH', 'PYTHONHOME'}}
    system_value = next((value for key, value in environment.items() if key.upper() == 'SYSTEMROOT'), '')
    system = Path(system_value)
    if not system.is_absolute() or not (system / 'System32').is_dir():
        raise ValueError('SystemRoot must identify the Windows directory')
    environment.update(PATH=os.pathsep.join((str(python.parent), str(system / 'System32'), str(system))),
                       PYTHONUTF8='1', PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1',
                       TRANSFORMERS_OFFLINE='1', PIP_NO_INDEX='1')
    return environment


def build(root, output, parent, tools, python, timeout=1800):
    root, tools, python = Path(root).resolve(), Path(tools).resolve(), Path(python).resolve()
    if not tools.is_dir() or not python.is_file():
        raise FileNotFoundError('existing build tools and runtime Python are required')
    output = require_new_output(output, parent)
    output.mkdir(parents=True)
    record = {'succeeded': False, 'started_at_epoch': time.time(), 'source_root': str(root)}
    try:
        logs = output / 'logs'
        logs.mkdir()
        environment = clean_environment(python)
        environment['PYTHONPATH'] = str(tools)
        probe = subprocess.run([str(python), '-c',
            'import PyInstaller,json,sys; print(json.dumps({"pyinstaller":PyInstaller.__version__,"python":sys.version}))'],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        (logs / 'tools-stdout.bin').write_bytes(probe.stdout)
        (logs / 'tools-stderr.bin').write_bytes(probe.stderr)
        if probe.returncode != 0:
            raise RuntimeError('build-tools probe failed; inspect logs')
        record['tools'] = json.loads(probe.stdout.decode('utf-8'))
        source = output / 'source'
        record['source_bundle'] = build_learning_source(root, source)
        preflight = output / 'isolated-source-check'
        preflight.mkdir()
        record['source_entrypoints'] = verify_learning_source(source, python, preflight)
        environment['LEARNING_WORKBENCH_SOURCE'] = str(source)
        command = [str(python), '-m', 'PyInstaller', str(source / 'packaging/learning_workbench.spec'),
                   '--noconfirm', '--distpath', str(output / 'dist'), '--workpath', str(output / 'work')]
        write_json(logs / 'command.json', {'command': command, 'tools': str(tools), 'python': str(python)})
        with (logs / 'stdout.bin').open('wb') as stdout, (logs / 'stderr.bin').open('wb') as stderr:
            result = subprocess.run(command, cwd=output, env=environment,
                                    stdout=stdout, stderr=stderr, timeout=timeout, check=False)
        record['build_returncode'] = result.returncode
        portable = output / 'dist/AgentLearningWorkbench'
        executable = portable / 'AgentLearningWorkbench.exe'
        if result.returncode != 0 or not executable.is_file():
            raise RuntimeError('PyInstaller failed or executable missing; inspect preserved logs')
        frozen_report = logs / 'frozen-image-feature.json'
        probe = subprocess.run([str(executable), '--check-image-feature', str(frozen_report)],
            cwd=output, env=clean_environment(python), capture_output=True, timeout=90, check=False)
        (logs / 'frozen-image-feature-stdout.bin').write_bytes(probe.stdout)
        (logs / 'frozen-image-feature-stderr.bin').write_bytes(probe.stderr)
        evidence = json.loads(frozen_report.read_text(encoding='utf-8')) if frozen_report.is_file() else None
        if probe.returncode or not evidence or not evidence.get('passed') or not evidence.get('frozen'):
            raise RuntimeError('frozen image feature dependency check failed; inspect preserved logs')
        if Path(evidence['runtime_root']).resolve() != (portable / 'runtime').resolve():
            raise ValueError('frozen image feature imported another runtime root')
        record['frozen_image_feature'] = evidence
        shutil.copy2(source / 'packaging/learning_readme.md', portable / 'README.md')
        record['portable_root'] = str(portable)
        record['artifacts'] = [{'path': path.relative_to(portable).as_posix(), 'bytes': path.stat().st_size,
                               'sha256': sha256(path)} for path in sorted(portable.rglob('*')) if path.is_file()]
        write_json(portable / 'PORTABLE_MANIFEST.json', {'format': 'learning-workbench-portable-candidate-v2',
            'includes_models': False, 'includes_user_data': False, 'includes_execution_host': False,
            'offline_library_requires_execution': False, 'execution_attachment_requires_setup': True,
            'desktop_acceptance': 'not_run', 'files': record['artifacts']})
        record['succeeded'] = True
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        record['failure'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        record['duration_seconds'] = time.time() - record['started_at_epoch']
        write_json(output / 'build-result.json', record)
    return 0 if record['succeeded'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--output-parent', required=True, type=Path)
    parser.add_argument('--build-tools', required=True, type=Path)
    parser.add_argument('--runtime-python', type=Path, default=Path(sys.executable))
    args = parser.parse_args(argv)
    return build(Path(__file__).resolve().parents[1], args.output, args.output_parent,
                 args.build_tools, args.runtime_python)


if __name__ == '__main__':
    raise SystemExit(main())
