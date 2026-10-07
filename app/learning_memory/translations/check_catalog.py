"""盘点明确译文入口和待人工核对文字；不自动翻译用户内容或修改资源。"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from string import Formatter
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
UI_FILES = (
    'app/learning_memory/workbench_window.py',
    'app/learning_memory/workbench_navigation.py',
    'app/learning_memory/workflow_steps_pane.py',
    'app/learning_memory/workflow_rules_editor.py',
    'app/learning_memory/workflow_image_check_editor.py',
    'app/learning_memory/workflow_target_editor.py',
    'app/learning_memory/workflow_input_dialog.py',
    'app/learning_memory/template_dialog.py',
    'app/learning_memory/source_dialog.py',
    'app/learning_memory/workflow_takeover_pane.py',
    'app/learning_memory/program_graph_widget.py',
    'app/learning_memory/workflow_run_panel.py',
    'app/learning_memory/workflow_run_history.py',
    'app/learning_memory/workbench_launch.py',
    'app/desktop_review/content_library.py',
    'app/desktop_review/workflow_projects_pane.py',
    'app/desktop_review/interface_pane.py',
    'app/desktop_review/graph_review_pane.py',
    'app/desktop_review/interface_picker.py',
    'app/desktop_review/interface_relearning_dialog.py',
    'app/desktop_review/friendly_controls.py',
    'app/desktop_review/graph_view.py',
    'app/desktop_review/graph_relearn_dialog.py',
    'scripts/run_learning_memory_workbench.py',
)


def chinese(value):
    return isinstance(value, str) and any('\u4e00' <= character <= '\u9fff' for character in value)


def catalog(locale):
    tree = ET.parse(Path(__file__).with_name(locale + '.ts'))
    return {(context.findtext('name'), message.findtext('source')): message.findtext('translation')
            for context in tree.getroot().findall('context') for message in context.findall('message')}


def placeholders(text):
    return sorted((field, spec, conversion) for _, field, spec, conversion in Formatter().parse(text)
                  if field is not None)


def inspect():
    english, chinese_catalog = catalog('en-US'), catalog('zh-CN')
    problems = []
    if english.keys() != chinese_catalog.keys():
        problems.append('Locale source/context keys differ')
    for key, value in english.items():
        if not value:
            problems.append(f'Empty translation: {key!r}')
        elif chinese(value):
            problems.append(f'Chinese remains in English application translation: {key!r}')
        if placeholders(key[1]) != placeholders(value or ''):
            problems.append(f'Format placeholders differ: {key!r}')
    explicit, raw = [], []
    for relative in UI_FILES:
        tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not chinese(node.value):
                continue
            ancestor, chain = node, []
            while ancestor in parents:
                ancestor = parents[ancestor]
                chain.append(ancestor)
            if isinstance(parents.get(node), ast.Expr):
                continue
            direct = isinstance(parents.get(node), ast.Call) and isinstance(parents[node].func, ast.Name) and parents[node].func.id == 'tr' and parents[node].args[0] is node
            row = {'file': relative, 'line': node.lineno, 'text': node.value,
                   'catalogued': ('Workbench', node.value) in english}
            if direct:
                explicit.append(row)
                if not row['catalogued']:
                    problems.append(f'Missing explicit source: {relative}:{node.lineno}: {node.value}')
            elif not any(isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.func.id == 'tr' for parent in chain):
                call = next((parent for parent in chain if isinstance(parent, ast.Call)), None)
                row['call'] = ast.unparse(call.func) if call else ''
                raw.append(row)
    return {'files': list(UI_FILES), 'translation_count_per_locale': len(english),
            'explicit_sources': explicit, 'raw_literals_for_manual_review': raw,
            'problems': problems,
            'limitation': 'Static scan checks literal sources and format contracts. Dynamic user content, raw logs and backend diagnostics are not translated. Raw literals require manual classification; this scan does not prove runtime coverage.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = inspect()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'files': len(report['files']), 'messages': report['translation_count_per_locale'],
                      'explicit': len(report['explicit_sources']), 'raw_review': len(report['raw_literals_for_manual_review']),
                      'problems': report['problems']}, ensure_ascii=False))
    return bool(report['problems'])


if __name__ == '__main__':
    raise SystemExit(main())
