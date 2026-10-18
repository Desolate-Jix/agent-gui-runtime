"""沿既有 epoch 准入证明恢复新 launch 的限定关闭归属。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from app.desktop_review.external_mapping import canonical_json_bytes
from app.agent.native_identity import validate_native_identity_fact
from app.execution.session_epoch_admission import SessionEpochAdmission

_KEY = object()


def _require(value, reason):
    if not value:
        raise ValueError('launch_ownership_' + reason)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw.decode('utf-8'))
    _require(isinstance(value, dict), 'snapshot_invalid')
    return value, raw


def validate_close_ownership_request(request):
    _require(isinstance(request, dict) and set(request) == {'admission_request_id', 'launch_request_id'},
             'request_invalid')
    from app.instant_mcp import _validate_request_id
    for value in request.values():
        _require(isinstance(value, str), 'request_invalid')
        _validate_request_id(value)
    return deepcopy(request)


class _CloseProof:
    def __init__(self, key, coordinator, session, binding, identity, revalidate):
        _require(key is _KEY, 'proof_invalid')
        self.key, self.coordinator, self.session = key, coordinator, session
        self.binding, self.native, self.revalidate = binding, identity, revalidate
        self.path = session / 'launched-window-close-claims' / (_sha(canonical_json_bytes(binding)) + '.json')

    def identity(self, coordinator, handle, pid):
        _require(self.key is _KEY and self.coordinator is coordinator, 'proof_invalid')
        _require(self.native['target_window_handle'] == handle and self.native['process_id'] == pid,
                 'target_mismatch')
        self.revalidate()
        return deepcopy(self.native)

    def _confined_claim_path(self):
        # 写盘前解析目录和文件，拒绝 junction 或符号链接越出原会话。
        session = self.session.resolve()
        folder = (self.session / 'launched-window-close-claims').resolve()
        path = self.path.resolve()
        _require(session == self.session and folder != session
                 and folder.is_relative_to(session) and path.parent == folder
                 and path.is_relative_to(session), 'claim_path_outside_session')

    def claim(self, coordinator, *, resend=False):
        _require(self.coordinator is coordinator and self.key is _KEY, 'proof_invalid')
        self.revalidate()
        claims = getattr(coordinator, '_recovered_launch_close_claims', set())
        value = {'contract_version': 'launched_window_close_claim.v1',
                 'binding': deepcopy(self.binding), 'identity': deepcopy(self.native), 'status': 'started'}
        self._confined_claim_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._confined_claim_path()
        try:
            with self.path.open('xb') as stream:
                stream.write(canonical_json_bytes(value) + b'\n')
                stream.flush()
                import os
                os.fsync(stream.fileno())
        except FileExistsError:
            prior, _ = _read(self.path)
            _require(resend is True and self.path in claims and prior.get('binding') == self.binding
                     and prior.get('identity') == self.native and prior.get('status') == 'window_close_pending',
                     'claim_unresolved')
            if resend:
                from app.core.json_snapshot import write_json_snapshot
                write_json_snapshot(self.path, value)
        claims.add(self.path)
        coordinator._recovered_launch_close_claims = claims

    def finish(self, result):
        self._confined_claim_path()
        _require(result.get('status') in {'window_closed', 'window_close_pending'}, 'close_result_unknown')
        from app.core.json_snapshot import write_json_snapshot
        write_json_snapshot(self.path, {'contract_version': 'launched_window_close_claim.v1',
            'binding': deepcopy(self.binding), 'identity': deepcopy(self.native),
            'status': result['status'], 'result': deepcopy(result)})


def proof_identity(proof, coordinator, handle, pid):
    _require(type(proof) is _CloseProof and proof.key is _KEY, 'proof_invalid')
    return proof.identity(coordinator, handle, pid)


def verify_recovered_launch_ownership(session_dir, source_root, configuration, request, coordinator, *, model_directory=None):
    request = validate_close_ownership_request(request)
    session = Path(session_dir).resolve()
    facade = SimpleNamespace(data_root=session.parent, root=Path(source_root).resolve(), session=session,
        recognition_source=configuration.source, delegate_profile=configuration.delegate_profile,
        api_profile=configuration.api_profile, model_directory=model_directory)
    record_path = session.parent / 'recovery-admissions' / (request['admission_request_id'] + '.json')
    record, record_raw = _read(record_path)
    _require(record.get('phase') == 'ready', 'admission_not_ready')
    admission = SessionEpochAdmission(facade)
    old, new, _ = admission._validate(record, request['admission_request_id'], record['preview_sha256'])
    _require(new == session, 'session_mismatch')
    admission._verify_created(record)
    _require(admission._ready(record), 'host_not_ready')
    pointer, _ = _read(session.parent / 'latest-session.json')
    _require(pointer == admission._new_pointer(record), 'pointer_changed')
    admission._original_unchanged(record, published=True)
    eid = request['launch_request_id']
    cp, rp = old / 'commands' / (eid + '.json'), old / 'responses' / (eid + '.json')
    command, cb = _read(cp)
    response, rb = _read(rp)
    files = record['preview']['input_proof']['files']
    _require(files.get('commands/' + cp.name) == _sha(cb)
             and files.get('responses/' + rp.name) == _sha(rb), 'launch_snapshot_mismatch')
    from app.instant_mcp import InstantCommand
    _require(InstantCommand.model_validate(command).command() == command, 'launch_command_invalid')
    _require(command.get('kind') == 'launch' and response.get('command') == command
             and response.get('status') == 'returned', 'launch_not_proven')
    result = response.get('result') or {}
    ownership = result.get('launch_ownership') or {}
    _require(result.get('status') == 'launched_window_ready'
             and set(ownership) == {'contract_version', 'newly_launched', 'identity'}
             and ownership['contract_version'] == 'launched_window_ownership.v1'
             and ownership['newly_launched'] is True, 'new_launch_required')
    window = result.get('window') or {}
    _require(type(window.get('handle')) is int and type(window.get('process_id')) is int, 'launch_identity_mismatch')
    identity = validate_native_identity_fact(ownership['identity'], target_window_handle=window.get('handle'),
                                             expected_process_id=window.get('process_id'))
    _require(identity is not None, 'launch_identity_invalid')
    _require(result.get('process_id') == identity['process_id']
             and window.get('handle') == identity['target_window_handle'], 'launch_identity_mismatch')
    binding = {'admission_request_id': request['admission_request_id'], 'admission_sha256': _sha(record_raw),
               'launch_request_id': eid, 'command_sha256': _sha(cb), 'response_sha256': _sha(rb),
               'source_session': old.name, 'session': session.name, 'host_identity': record['new_host_identity']}
    def revalidate():
        _require(record_path.read_bytes() == record_raw and cp.read_bytes() == cb and rp.read_bytes() == rb,
                 'source_changed')
        admission._verify_created(record)
        _require(admission._ready(record), 'host_not_ready')
        current, _ = _read(session.parent / 'latest-session.json')
        _require(current == admission._new_pointer(record), 'pointer_changed')
        admission._original_unchanged(record, published=True)
        _require(record_path.read_bytes() == record_raw and cp.read_bytes() == cb and rp.read_bytes() == rb,
                 'source_changed')
    revalidate()
    return _CloseProof(_KEY, coordinator, session, binding, identity, revalidate)
