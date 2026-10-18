"""原宿主提供只读预览及现场复核后的暂停接管，不派发旧输入。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.workspace import _write_immutable
from .workflow_recovery_import import (prepare_recovery_import, commit_recovery_import,
    _prepared_marker, _claim_path, _require)
from .workflow_takeover_controls import preview_path, read_preview, scoped_input_files, validate_current_control
from .workflow_takeover_observation import collect_takeover_effect
from .workflow_recovery_resolution import marker_resolution, validate_resolution
from .workflow_runner import _exclusive
from .workflow_trial import TrialService, _read
from .workspace import MemoryWorkspace


def _scope(payload):
    return {'preview_request_id': payload['request_id'], 'admission_request_id': payload['admission_request_id'],
            'source_run_id': payload['source_run_id']}


def _signature(envelope):
    evidence = envelope.get('native_evidence')
    _require(isinstance(evidence, dict) and 'selected_control' in evidence, 'semantic_scope_not_verified')
    control = evidence['selected_control']
    if control is None:
        _require(envelope['observation']['source'] == 'presence'
                 and envelope['observation']['values'] == {'target_present': False}, 'semantic_scope_not_verified')
        identity = envelope['effect']['window_identity']
        for key in ('before_uia_snapshot', 'after_uia_snapshot'):
            snapshot = evidence.get(key)
            _require(isinstance(snapshot, dict) and snapshot.get('status') == 'ok'
                     and snapshot.get('provider') == 'windows_uia' and snapshot.get('scan_complete') is True
                     and snapshot.get('truncated') is False and snapshot.get('provider_tree_valid') is True
                     and snapshot.get('scan_scope', 'bound_window') == 'bound_window'
                     and isinstance(snapshot.get('controls'), list) and isinstance(snapshot.get('window'), dict)
                     and snapshot['window'].get('handle') == identity['handle']
                     and snapshot['window'].get('process_id') == identity['process_id'], 'semantic_scope_not_verified')
        _require((evidence.get('visual_stability') or {}).get('scope') == 'full_window'
                 and evidence['visual_stability'].get('matched') is True, 'semantic_scope_not_verified')
    else:
        from .verification_observation import _geometry_current
        _require(isinstance(control, dict) and set(control) == {'control_id', 'runtime_id', 'bbox', 'name', 'control_type', 'automation_id'}
                 and isinstance(control['control_id'], str) and bool(control['control_id'].strip())
                 and isinstance(control['control_type'], str) and bool(control['control_type'].strip())
                 and isinstance(control['runtime_id'], list) and 1 <= len(control['runtime_id']) <= 64
                 and all(type(value) is int for value in control['runtime_id'])
                 and all(control[key] is None or isinstance(control[key], str) for key in ('name', 'automation_id'))
                 and _geometry_current(control, envelope['frame']), 'semantic_scope_not_verified')
    return {'window_identity': envelope['effect']['window_identity'], 'scope_id': envelope['effect']['scope_id'],
        'source': envelope['observation']['source'], 'values': envelope['observation']['values'],
        'control': deepcopy(evidence['selected_control']), 'window_rect': envelope['frame'].get('window_rect'),
        'application': envelope['frame'].get('application'), 'verdict': envelope['verification']['verdict'],
        'outputs': envelope['verification']['outputs']}


def _view(document):
    payload, prepared = document['payload'], document['payload']['prepared']
    state = prepared['trial_state']
    return {'status': 'preview_ready', 'preview_request_id': payload['request_id'],
        'preview_sha256': document['preview_sha256'], 'source_run_id': payload['source_run_id'],
        'admission_request_id': payload['admission_request_id'], 'new_run_id': state['run_id'],
        'next_step_id': state['current_step_id'], 'inputs': deepcopy(state['inputs']),
        'outputs': deepcopy(state['outputs']), 'effect': deepcopy(payload['observation']),
        'resolution': marker_resolution(_prepared_marker(prepared)),
        'automatic_retry_allowed': False, 'input_dispatched': False}


def takeover_preview(runtime, request, request_id):
    resolution = validate_resolution(request.get('resolution', 'adopt_success'))
    session, root = runtime.session, runtime.runner.library_root
    scope = {'preview_request_id': request_id, 'admission_request_id': request['admission_request_id'],
             'source_run_id': request['source_run_id']}
    path = preview_path(session, request_id)
    with _exclusive(path.parent / 'previews.lock'):
        validate_current_control(session, request_id, request, scope)
        if path.exists():
            document = read_preview(session, request_id)
            _require(_scope(document['payload']) == scope
                     and marker_resolution(_prepared_marker(document['payload']['prepared'])) == resolution,
                     'preview_request_conflict')
            return _view(document)
        scoped_input_files(session, root, scope, current_request_id=request_id)
        capture_id = 'takeover-effect-' + sha256(('preview:' + request_id).encode('utf-8')).hexdigest()
        observed = collect_takeover_effect(runtime.coordinator, session_dir=session,
            admission_request_id=scope['admission_request_id'], source_run_id=scope['source_run_id'], request_id=capture_id)
        if observed.get('status') == 'verification_required':
            return observed
        envelope = observed['envelope']
        _signature(envelope)
        prepared = prepare_recovery_import(root, session, admission_request_id=scope['admission_request_id'],
            source_run_id=scope['source_run_id'], effect_evidence_ref=observed['evidence_ref'], request_id=request_id,
            control_scope=scope, control_request_id=request_id, resolution=resolution)
        payload = {'request_id': request_id, 'admission_request_id': scope['admission_request_id'],
            'source_run_id': scope['source_run_id'], 'prepared': prepared, 'observation': envelope}
        document = {'contract_version': 'workflow_takeover_preview.v1', 'payload': payload,
            'preview_sha256': sha256(canonical_json_bytes(payload)).hexdigest()}
        _write_immutable(path, canonical_json_bytes(document))
        return _view(document)


def takeover_commit(runtime, request, request_id):
    session, root = runtime.session, runtime.runner.library_root
    document = read_preview(session, request['preview_request_id'])
    _require(document['preview_sha256'] == request['preview_sha256'], 'preview_hash_mismatch')
    payload = document['payload']
    resolution = marker_resolution(_prepared_marker(payload['prepared']))
    scope = _scope(payload)
    validate_current_control(session, request_id, request, scope)
    path = session / 'workflow-takeover-commits' / (payload['request_id'] + '.json')
    _require(path.resolve().is_relative_to(session) and path.resolve().parent == path.parent, 'commit_path_invalid')
    expected = {'contract_version': 'workflow_takeover_commit.v1', 'preview_request_id': payload['request_id'],
        'preview_sha256': request['preview_sha256'], 'mode': request['mode'],
        'vision_capabilities': deepcopy(request.get('vision_capabilities'))}
    with _exclusive(path.parent / 'commits.lock'):
        existing = _read(path) if path.exists() else None
        if existing is not None:
            _require(set(existing) == set(expected) | {'prepared'}
                     and {key: existing[key] for key in expected} == expected, 'commit_request_conflict')
            prepared = existing['prepared']
            marker = _prepared_marker(prepared)
            claim_path = _claim_path(session, marker['claim_id'])
            ready = claim_path.exists() and _read(claim_path).get('phase') == 'ready'
        else:
            prepared, ready = None, False
        if not ready:
            scoped_input_files(session, root, scope, current_request_id=request_id)
            # 每个未完成的外层提交都重新观察；已 ready 的回读不消费旧现场。
            capture_id = 'takeover-effect-' + sha256(('commit:' + request_id).encode('utf-8')).hexdigest()
            observed = collect_takeover_effect(runtime.coordinator, session_dir=session,
                admission_request_id=scope['admission_request_id'], source_run_id=scope['source_run_id'],
                request_id=capture_id)
            _require('envelope' in observed, 'current_effect_requires_review')
            _require(_signature(observed['envelope']) == _signature(payload['observation']), 'semantic_scope_changed')
            if prepared is None:
                prepared = prepare_recovery_import(root, session,
                    admission_request_id=scope['admission_request_id'], source_run_id=scope['source_run_id'],
                    effect_evidence_ref=observed['evidence_ref'], request_id=payload['request_id'],
                    control_scope=scope, control_request_id=request_id, resolution=resolution)
                _require(prepared['new_input_files'] == payload['prepared']['new_input_files'], 'new_input_changed')
                _write_immutable(path, canonical_json_bytes({**expected, 'prepared': prepared}))
            else:
                reference = prepared['trial_state']['recovery_import']['effect_evidence_ref']
                original_effect = _read(session / reference)
                _require(_signature(observed['envelope']) == _signature(original_effect), 'semantic_scope_changed')
        with MemoryWorkspace(root) as library:
            snapshot = commit_recovery_import(TrialService(library, session), runtime.runner, prepared,
                mode=expected['mode'], vision_capabilities=expected['vision_capabilities'], control_request_id=request_id)
        if not ready:
            runtime.stop()
        return snapshot
