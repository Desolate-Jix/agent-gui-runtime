"""按真实导入闭合组件源码；禁止靠排除依赖掩盖漏包。"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil


def _inside(root, relative):
    relative = Path(relative)
    path = (root / relative).resolve()
    if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root):
        raise ValueError('component path escapes source root: ' + str(relative))
    return path


def collect_module_sources(root, entries, *, forbidden=()):
    root = Path(root).resolve()
    excluded = tuple(Path(value) for value in forbidden)
    pending = [_inside(root, entry) for entry in entries]
    for path in pending:
        if not path.is_file():
            raise FileNotFoundError(str(path))
    found = set()

    def add_module(name):
        if not name:
            return
        parts = name.split('.')
        module = root.joinpath(*parts).with_suffix('.py')
        package = root.joinpath(*parts, '__init__.py')
        candidate = module if module.is_file() else package
        if candidate.is_file():
            pending.append(candidate.resolve())
        for count in range(1, len(parts)):
            initializer = root.joinpath(*parts[:count], '__init__.py')
            if initializer.is_file():
                pending.append(initializer.resolve())

    while pending:
        path = pending.pop()
        if path in found:
            continue
        relative = path.relative_to(root)
        if any(relative == prefix or relative.is_relative_to(prefix) for prefix in excluded):
            raise ValueError('forbidden component dependency: ' + relative.as_posix())
        found.add(path)
        if path.suffix != '.py':
            raise ValueError('entry must be a Python source: ' + relative.as_posix())
        parts = list(relative.with_suffix('').parts)
        package = parts[:-1]
        for count in range(1, len(package) + 1):
            initializer = root.joinpath(*package[:count], '__init__.py')
            if initializer.is_file():
                pending.append(initializer.resolve())
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    add_module(alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = package[:len(package) - node.level + 1] if node.level else []
                if node.level > len(package) + 1:
                    raise ValueError('invalid relative import: ' + relative.as_posix())
                module = '.'.join(base + (node.module.split('.') if node.module else []))
                add_module(module)
                for alias in node.names:
                    if alias.name != '*':
                        add_module('.'.join(filter(None, (module, alias.name))))
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.func, ast.Name) and node.func.id == '__import__':
                    add_module(node.args[0].value) if isinstance(node.args[0].value, str) else None
                elif isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                    if isinstance(node.args[0].value, str) and not node.args[0].value.startswith('.'):
                        add_module(node.args[0].value)
    return sorted(found)


def copy_component_sources(root, output, entries, *, resources=(), forbidden=()):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(str(output))
    sources = collect_module_sources(root, entries, forbidden=forbidden)
    assets = [_inside(root, relative) for relative in resources]
    for path in assets:
        if not path.is_file():
            raise FileNotFoundError(str(path))
    output.mkdir(parents=True)
    rows = []
    for source in sorted(set(sources + assets)):
        relative = source.relative_to(root)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        rows.append({'path': relative.as_posix(), 'bytes': target.stat().st_size,
                     'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    manifest = {'schema': 'component_source.v1', 'includes_models': False,
                'includes_user_data': False, 'files': rows}
    (output / 'COMPONENT_SOURCE_MANIFEST.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest
