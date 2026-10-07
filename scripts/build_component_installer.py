"""构建两个独立的用户级安装器；每次只写全新输出目录。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

COMPONENTS = {
    'learning': {'product_id': 'AgentLearningWorkbenchPreview', 'entrypoint': 'AgentLearningWorkbench.exe',
                 'display_name': 'Agent Learning Workbench Preview'},
    'execution': {'product_id': 'AgentGUIRuntimeExecutionPreview', 'entrypoint': 'scripts/setup_instant.ps1',
                  'display_name': 'Agent GUI Runtime Execution Preview'},
}
CSC = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
RESERVED = {'.component-install.json', 'Uninstall.exe'}


def safe_path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('unsafe manifest path')
    for part in value.split('/'):
        if (not part or part in {'.', '..'} or part.endswith(('.', ' '))
                or any(ord(c) < 32 or c in '<>"|?*' for c in part)
                or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)):
            raise ValueError('unsafe manifest path: ' + value)
    if value.casefold() in {v.casefold() for v in RESERVED}:
        raise ValueError('installer metadata name is reserved')
    return value


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reparse(path):
    return bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def validate(payload, manifest):
    raw = json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
    if not isinstance(raw, dict) or set(raw) != {'files'} or not isinstance(raw['files'], list) or not raw['files']:
        raise ValueError('manifest must contain only a nonempty files list')
    rows, seen = [], set()
    for row in raw['files']:
        if not isinstance(row, dict) or set(row) != {'path', 'size', 'sha256'}:
            raise ValueError('manifest row must have path,size,sha256 only')
        name = safe_path(row['path'])
        if (name.casefold() in seen or type(row['size']) is not int or row['size'] < 0
                or not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
            raise ValueError('duplicate path or invalid file facts')
        seen.add(name.casefold())
        source = payload.joinpath(*name.split('/'))
        if not source.is_file() or source.stat().st_size != row['size'] or digest(source) != row['sha256']:
            raise ValueError('payload differs from manifest: ' + name)
        rows.append(dict(row))
    actual = set()
    for path in payload.rglob('*'):
        if reparse(path):
            raise ValueError('payload reparse points are not supported')
        if path.is_file():
            actual.add(safe_path(path.relative_to(payload).as_posix()).casefold())
    if actual != seen:
        raise ValueError('manifest omits payload files')
    names = sorted(seen)
    if any(other.startswith(name + '/') for name in names for other in names if name != other):
        raise ValueError('manifest file/directory conflict')
    return sorted(rows, key=lambda row: row['path'])


def build(*, component, version, payload_dir, manifest, output_dir, csc=CSC):
    if component not in COMPONENTS or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,3}(?:-[A-Za-z0-9.-]+)?', version):
        raise ValueError('invalid fixed component or version')
    payload, output = Path(payload_dir).absolute(), Path(output_dir).absolute()
    if output.exists():
        raise FileExistsError(str(output))
    if not output.parent.is_dir() or not payload.is_dir() or reparse(payload):
        raise ValueError('existing payload and output parent are required')
    for ancestor in (payload, *payload.parents, output.parent, *output.parent.parents):
        if reparse(ancestor):
            raise ValueError('reparse ancestor is forbidden')
    if output == payload or output.is_relative_to(payload):
        raise ValueError('output must be outside payload')
    rows = validate(payload, manifest)
    config = {**COMPONENTS[component], 'component': component, 'version': version}
    if config['entrypoint'].casefold() not in {r['path'].casefold() for r in rows}:
        raise ValueError('component entrypoint missing from manifest')
    if not Path(csc).is_file():
        raise FileNotFoundError('existing .NET compiler is required')
    output.mkdir()
    archive = output / 'payload.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for row in rows:
            zipped.write(payload.joinpath(*row['path'].split('/')), row['path'])
    canonical = {'format': 'component-payload-v1', **config, 'files': rows}
    manifest_path = output / 'payload-manifest.json'
    manifest_path.write_text(json.dumps(canonical, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    source = Path(__file__).resolve().parents[1] / 'packaging/component_installer.cs'
    generated = output / 'ComponentIdentity.cs'
    constants = {**config, 'manifest_sha256': digest(manifest_path), 'payload_sha256': digest(archive)}
    generated.write_text('internal static class Identity {\n' + ''.join(
        'internal const string ' + key + ' = ' + json.dumps(value, ensure_ascii=True) + ';\n'
        for key, value in constants.items()) + '}\n', encoding='utf-8')
    setup = output / (config['product_id'] + '-Setup.exe')
    windows_manifest = output / 'asInvoker.manifest'
    windows_manifest.write_text('<?xml version="1.0" encoding="UTF-8"?><assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0"><trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo></assembly>', encoding='utf-8')
    framework = Path(csc).parent
    command = [str(csc), '/nologo', '/target:winexe', '/optimize+', '/platform:anycpu', '/out:' + str(setup),
               '/win32manifest:' + str(windows_manifest),
               '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
               '/reference:' + str(framework / 'System.IO.Compression.dll'),
               '/reference:System.Web.Extensions.dll', '/resource:' + str(archive) + ',payload.zip',
               '/resource:' + str(manifest_path) + ',payload-manifest.json', str(source), str(generated)]
    result = subprocess.run(command, capture_output=True, timeout=120)
    (output / 'compile-stdout.bin').write_bytes(result.stdout)
    (output / 'compile-stderr.bin').write_bytes(result.stderr)
    if result.returncode != 0:
        raise RuntimeError('installer compilation failed; inspect preserved compiler bytes in ' + str(output))
    record = {'component': component, 'version': version, 'setup_path': str(setup),
              'setup_sha256': digest(setup), 'payload_sha256': digest(archive),
              'manifest_sha256': digest(manifest_path), 'signed': False, 'command': command}
    (output / 'build-result.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component', choices=COMPONENTS, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--payload-dir', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(**vars(args)), ensure_ascii=False))


if __name__ == '__main__':
    main()
