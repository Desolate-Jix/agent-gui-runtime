"""学习附着复用共享队列合同，不加载执行器或拥有宿主。"""
import subprocess
import sys


def test_attachment_transport_import_does_not_load_execution_or_instant_server():
    script = (
        "import sys; from app.core.instant_attachment_transport import InstantAttachmentTransport; "
        "assert 'app.instant_mcp' not in sys.modules; "
        "assert not any(n.startswith('app.execution.') for n in sys.modules); "
        "assert not hasattr(InstantAttachmentTransport, 'start'); "
        "assert not hasattr(InstantAttachmentTransport, 'stop'); "
        "assert not hasattr(InstantAttachmentTransport, '_lock')"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_instant_and_attachment_share_live_admission_and_receipt_contracts():
    from app.core.instant_attachment_transport import InstantAttachmentTransport
    from app.instant_mcp import InstantSession, InstantAdmissionError
    from app.core.instant_attachment_transport import InstantAdmissionError as SharedError
    assert InstantSession.status is InstantAttachmentTransport.status
    assert InstantSession.result is InstantAttachmentTransport.result
    assert InstantSession._live_submit is InstantAttachmentTransport._live_submit
    assert InstantAdmissionError is SharedError


def test_learning_connect_poll_and_queue_remain_lightweight_and_do_not_own_host():
    script = '''
import json, os, sys, tempfile
from pathlib import Path
import psutil
from app.learning_memory.workflow_run_client import WorkflowRunClient
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    session = root / ('session-' + 'a' * 32)
    session.mkdir()
    for name in ('commands', 'responses'):
        (session / name).mkdir()
    library = root / 'memory-library'
    library.mkdir()
    identity = {'pid': os.getpid(), 'created': psutil.Process().create_time()}
    pointer = {'name': session.name, 'host_identity': identity,
               'recognition_source': 'agent_delegate', 'delegate_profile': 'fixture', 'api_profile': None}
    (root / 'latest-session.json').write_text(json.dumps(pointer), encoding='utf-8')
    (session / 'report.json').write_text(json.dumps({'runner_pid': os.getpid(), 'phase': 'ready'}), encoding='utf-8')
    client = WorkflowRunClient(session, library)
    assert client.connect()['host_alive']
    receipt = client.control({'action': 'status', 'run_id': 'fixture'}, 'status-original')
    assert receipt['status'] == 'pending'
    assert client.result('status-original')['status'] == 'pending'
    client.close()
    assert not (root / 'owner.lock').exists()
    assert not (session / 'closing.json').exists()
    assert len(list((session / 'commands').glob('*.json'))) == 1
assert 'app.instant_mcp' not in sys.modules
for name in ('app.execution.input_sequence', 'app.execution.form_fill',
             'app.execution.session_epoch_admission', 'app.execution.session_resource_recovery',
             'app.vision.agent_command_jobs'):
    assert name not in sys.modules, name
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
