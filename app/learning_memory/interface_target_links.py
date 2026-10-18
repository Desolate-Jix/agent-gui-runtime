"""界面库只读投影当前工作流目标，保留各动作截图和确切程序引用。"""
from copy import deepcopy

from .target_recipe import load_target_recipe
from .workflow_target_editor_service import read_target_edit_context


def read_interface_target_links(library, interface_id, version_id=None):
    content = library.load_interface_content(interface_id, version_id)
    targets, issues = [], []
    if content['source'].get('kind') != 'execution_memory_v1':
        return {'targets': targets, 'issues': issues}
    for project in library.list_workflow_projects():
        program = library.load_workflow_program(project['logical_workflow_id'])
        if program['program_id'] is None:
            continue
        for step in program['definition']['steps']:
            reference = step.get('action', {}).get('target_memory')
            if reference is None:
                continue
            recipe = load_target_recipe(library, reference)
            if recipe['interface_id'] != interface_id:
                continue
            if recipe['contract_version'] == 'target_recipe.v1':
                issues.append({'step_id': step['step_id'], 'reason': 'target_edit_action_observation_unsupported'})
                continue
            context = read_target_edit_context(library, reference)
            targets.append({'workflow_id': program['workflow_id'], 'program_id': program['program_id'],
                'program_sha256': program['content_sha256'], 'step_id': step['step_id'],
                'step_title': step['title'], 'workflow_title': program['definition']['title'],
                'reference': deepcopy(reference), 'interface_version_id': recipe['interface_version_id'],
                'selected_version_matches': recipe['interface_version_id'] == content['version_id'],
                'frame': context['frame'], 'target_boxes': context.get('target_boxes', []),
                'box_issues': context.get('box_issues', []), 'evidence_scope': 'learning_capture'})
    return {'targets': targets, 'issues': issues}
