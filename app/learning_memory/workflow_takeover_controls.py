"""只排除同预览事务的确切接管控制，不忽略其他未完成命令。"""
from hashlib import sha256
from pathlib import Path

from app.core.instant_command_queue import _request_id
from app.core.json_snapshot import read_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from app.execution.session_input_terminal import inspect_session_input_terminal
from .workflow_control import validate_request


def _require(value):
    if not value:
        raise ValueError('workflow_takeover_control_binding_invalid')


def preview_path(session_dir, request_id):
    session = Path(session_dir).resolve()
    path = session / 'workflow-takeover-previews' / (_request_id(request_id) + '.json')
    _require(path.resolve().is_relative_to(session) and path.resolve().parent == path.parent)
    return path


def validate_scope(scope):
    _require(isinstance(scope, dict) and set(scope) == {'preview_request_id', 'admission_request_id', 'source_run_id'})
    for value in scope.values():
        _request_id(value)
    return scope


def read_preview(session_dir, request_id):
    document = read_json_snapshot(preview_path(session_dir, request_id))
    _require(isinstance(document, dict) and set(document) == {'contract_version', 'payload', 'preview_sha256'}
             and document['contract_version'] == 'workflow_takeover_preview.v1')
    payload = document['payload']
    _require(isinstance(payload, dict) and set(payload) == {'request_id', 'admission_request_id', 'source_run_id', 'prepared', 'observation'}
             and payload['request_id'] == request_id
             and document['preview_sha256'] == sha256(canonical_json_bytes(payload)).hexdigest())
    validate_scope({key: payload['request_id'] if key == 'preview_request_id' else payload[key]
                    for key in ('preview_request_id', 'admission_request_id', 'source_run_id')})
    _require(isinstance(payload['prepared'], dict) and isinstance(payload['observation'], dict))
    return document


def _matches(session, request_id, command, scope):
    if command.get('kind') != 'learning_workflow':
        return False
    request = command.get('request') or {}
    if request.get('action') == 'takeover_preview':
        match = (request_id == scope['preview_request_id']
                 and request.get('admission_request_id') == scope['admission_request_id']
                 and request.get('source_run_id') == scope['source_run_id'])
    elif request.get('action') == 'takeover_commit' and request.get('preview_request_id') == scope['preview_request_id']:
        document = read_preview(session, scope['preview_request_id'])
        payload = document['payload']
        match = (payload['admission_request_id'] == scope['admission_request_id']
                 and payload['source_run_id'] == scope['source_run_id']
                 and request.get('preview_sha256') == document['preview_sha256'])
    else:
        return False
    if match:
        validate_request(request)
        if request.get('action') == 'takeover_preview' and preview_path(session, request_id).exists():
            from .workflow_recovery_resolution import marker_resolution, validate_resolution
            prepared = read_preview(session, request_id)['payload']['prepared']
            state = prepared.get('trial_state')
            marker = state.get('recovery_import') if isinstance(state, dict) else None
            match = marker_resolution(marker) == validate_resolution(request.get('resolution', 'adopt_success'))
    return match


def validate_current_control(session_dir, request_id, request, scope):
    session = Path(session_dir).resolve()
    scope = validate_scope(scope)
    path = session / 'commands' / (_request_id(request_id) + '.json')
    raw = path.read_bytes()
    command = read_json_snapshot(path)
    _require(command == {'kind': 'learning_workflow', 'request': request}
             and _matches(session, request_id, command, scope) and path.read_bytes() == raw)


def _report_fingerprint(session, files, controls):
    path = session / 'report.json'
    raw = path.read_bytes()
    _require(sha256(raw).hexdigest() == files['report.json'])
    report = read_json_snapshot(path)
    _require(isinstance(report, dict) and path.read_bytes() == raw)
    receipts = {}
    for request_id in controls:
        relative = 'responses/' + request_id + '.json'
        if relative not in files:
            continue
        receipt_path = session / relative
        receipt_raw = receipt_path.read_bytes()
        _require(sha256(receipt_raw).hexdigest() == files[relative])
        receipt = read_json_snapshot(receipt_path)
        _require(receipt_path.read_bytes() == receipt_raw)
        receipts[request_id + '.json'] = receipt
    # 只去掉已核对原回执的同事务聚合投影，身份和其他报告字段仍绑定。
    if 'completed_commands' in report:
        completed = report['completed_commands']
        _require(isinstance(completed, list))
        retained = []
        seen = set()
        for row in completed:
            _require(isinstance(row, dict) and set(row) == {'name', 'status'}
                     and isinstance(row['name'], str) and row['name'] not in seen)
            seen.add(row['name'])
            if row['name'] in {request_id + '.json' for request_id in controls}:
                receipt = receipts.get(row['name'])
                _require(isinstance(receipt, dict) and row['status'] == receipt['status'])
            else:
                retained.append(row)
        if retained:
            report['completed_commands'] = retained
        else:
            report.pop('completed_commands')
    if 'workflow_run' in report and any(isinstance(receipt.get('result'), dict)
            and report['workflow_run'] == receipt['result'] for receipt in receipts.values()):
        report.pop('workflow_run')
    _require(path.read_bytes() == raw)
    return sha256(canonical_json_bytes(report)).hexdigest()


def scoped_input_files(session_dir, library_root, scope, *, current_request_id=None):
    scope = validate_scope(scope)
    session = Path(session_dir).resolve()
    binding = None
    if current_request_id is not None:
        _request_id(current_request_id)
        path = session / 'commands' / (current_request_id + '.json')
        _require(_matches(session, current_request_id, read_json_snapshot(path), scope))
        binding = {'request_id': current_request_id, 'command_sha256': sha256(path.read_bytes()).hexdigest()}
    proof = inspect_session_input_terminal(session, library_root, current_workflow_control=binding)
    excluded = set()
    controls = set()
    for request_id in proof['commands']:
        relative = 'commands/' + request_id + '.json'
        path = session / relative
        raw = path.read_bytes()
        _require(sha256(raw).hexdigest() == proof['files'][relative])
        command = read_json_snapshot(path)
        _require(sha256(path.read_bytes()).hexdigest() == proof['files'][relative])
        if _matches(session, request_id, command, scope):
            controls.add(request_id)
            excluded.update((relative, 'responses/' + request_id + '.json'))
    files = {path: value for path, value in proof['files'].items()
             if path not in excluded and not path.startswith(('workflow-trials/', 'workflow-runners/'))}
    if 'report.json' in files:
        files['report.json'] = _report_fingerprint(session, proof['files'], controls)
    return files
