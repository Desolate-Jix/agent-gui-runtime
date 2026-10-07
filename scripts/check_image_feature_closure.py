"""隔离载荷真实图像与程序契约检查；合成回执不派发桌面输入。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import importlib.metadata
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

import numpy as np
from PIL import Image
from app.learning_memory.image_verification import load_reference_image, match_image_check
from app.learning_memory.workflow_trial import _command
from app.learning_memory.workflow_execution_strategy import command_step


def check():
    with tempfile.TemporaryDirectory(prefix='image-closure-') as temporary:
        root = Path(temporary)
        pixels = np.random.default_rng(42).integers(0, 256, (60, 80, 3), dtype=np.uint8)
        stream = BytesIO()
        Image.fromarray(pixels).save(stream, format='PNG')
        raw = stream.getvalue()
        digest = sha256(raw).hexdigest()
        config = dict(contract_version='workflow_image_check.v1', reference_sha256=digest,
            reference_size=[80, 60], template_bbox=[10, 10, 20, 20],
            search_roi=[0, 0, 80, 60], threshold=.95)
        path = root / 'desktop-review/evidence-objects' / (digest + '.png')
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
        frame = dict(image_path=str(path), sha256=digest, image_size={'width': 80, 'height': 60},
            capture_id='isolated-fresh', window_identity={'handle': 1, 'process_id': 2,
            'process_create_time': 3}, window_rect=[0, 0, 80, 60])
        library = SimpleNamespace(_artifact_root=root)
        reference = load_reference_image(library, config)
        proof = match_image_check(config, reference, frame)
        if not proof.get('matched') or proof.get('bbox') != [10, 10, 20, 20]:
            raise ValueError('isolated PNG matching failed')
        commands = []
        for kind, action in [('click', {'goal': 'Open detail'}),
            ('input_sequence', {'field_goal': 'Query', 'text': {'source': 'constant', 'value': 'value'},
                                'clear_existing': True, 'submit_search': False}),
            ('scroll', {'goal': 'Results', 'direction': 'down', 'amount': 1})]:
            step = {'action': {'kind': kind, **action}, 'review_status': 'reviewed',
                    'verification': {'kind': 'agent_judgment', 'image_check': config}}
            original = deepcopy(step)
            learned = _command(command_step(library, step, {'execution_strategy': 'learned'}), {}, {})
            ordinary = _command(command_step(library, step, {'execution_strategy': 'steps_only'}), {}, {})
            if learned.get('observation_wait_ms') != 0 or 'observation_wait_ms' in ordinary or step != original:
                raise ValueError('isolated image wait strategy mismatch: ' + kind)
            commands.append(kind)
        return {'passed': True, 'png_match': proof, 'command_kinds': commands,
                'strategies': ['learned', 'steps_only'], 'input_executed': False,
                'recovery_consumption': check_recovery(root / 'recovery'),
                'dependencies': {name: importlib.metadata.version(name)
                                 for name in ('numpy', 'opencv-python', 'Pillow')}}


def check_recovery(root):
    from app.learning_memory.workflow_trial import TrialService
    from app.learning_memory.workflow_target_bindings import load_workflow_target_bindings
    from app.learning_memory.workflow_recovery_history import verify_recovery_history
    rows = []
    for strategy in ('learned', 'steps_only'):
        directory = root / strategy
        directory.mkdir(parents=True)
        session, library_root, draft, _ = _fresh_learning(directory)
        workflow = draft['workflow_id']
        with MemoryWorkspace(library_root) as library:
            baseline = library.load_workflow_program(workflow)
            saved = library.save_workflow_program(workflow, baseline['content_sha256'], draft['definition'],
                'closure-save', target_recipes=[item['recipe'] for item in draft['proposed_target_recipes']])
            definition = deepcopy(saved['definition'])
            definition['steps'][0]['review_status'] = 'reviewed'
            saved = library.save_workflow_program(workflow, saved['content_sha256'], definition, 'closure-review')
            trials = TrialService(library, session)
            step = saved['definition']['steps'][0]
            run = trials.start(workflow, saved['program_id'], step['step_id'], {}, 'closure-start', execution_strategy=strategy)
            ticket = trials.prepare(run['run_id'], 'closure-prepare')
            command = ticket['suggested_command']
            assert ('observation_wait_ms' in command) is (strategy == 'learned')
        if strategy == 'learned':
            binding = load_workflow_target_bindings(library_root, session,
                execution_request_id=ticket['execution_request_id'], command=command)
            assert binding['step_id'] == step['step_id']
        with MemoryWorkspace(library_root) as library:
            trials = TrialService(library, session)
            assert _command(command_step(library, step, run), {}, {}) == command
            # 合成终态只检查消费与恢复，绝不调用动作处理器。
            click_response(session, ticket)
            trials.review(run['run_id'], 'closure-agent-review', ticket['execution_request_id'], 'success', {}, {})
            state = trials.status(run['run_id'])
            hashes = {path.relative_to(session).as_posix(): sha256(path.read_bytes()).hexdigest()
                      for path in session.rglob('*') if path.is_file()}
            assert verify_recovery_history(library, session, state, saved, file_hashes=hashes)
            rows.append({'strategy': strategy, 'verified': True, 'synthetic_receipt': True})
    return rows

from PIL import ImageDraw
from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.receipt_adapter import content_hash
from app.learning_memory.workspace import MemoryWorkspace


def observation_scene(tmp_path):
    image = tmp_path / "before.png"
    Image.new("RGB", (160, 100), "white").save(image)
    identity = {"handle": 17, "process_id": 29, "process_create_time": 123.0}
    frame = {"capture_id": "before-1", "image_path": str(image),
             "sha256": sha256(image.read_bytes()).hexdigest(),
             "image_size": {"width": 160, "height": 100}, "window_identity": identity,
             "window_rect": [20, 30, 180, 130],
             "application": {"executable_name": "fixture.exe", "window_class": "Fixture"}}
    event = {"request_id": "click-one", "command_sha256": "a" * 64,
             "before": {"status": "referenced", "capture_id": "before-1",
                        "sha256": frame["sha256"], "image_path": str(image),
                        "window_size": frame["image_size"]}}
    controls = [{"name": "Record desk", "control_type": "Text", "runtime_id": [1],
                 "visible": True, "enabled": True, "bbox": {"x": 1, "y": 1, "w": 80, "h": 15}},
                {"name": "Search", "control_type": "Button", "runtime_id": [2],
                 "visible": True, "enabled": True, "bbox": {"x": 35, "y": 25, "w": 30, "h": 20}}]
    snapshot = {"status": "ok", "scan_scope": "bound_window", "scan_complete": True,
                "truncated": False, "window": {"handle": 17, "process_id": 29},
                "capture_id": "before-1", "window_identity": identity, "controls": controls}
    observation = {"contract_version": "learning_target_observation.v1", "event_id": "click-one",
                   "command_sha256": event["command_sha256"], "observation_stage": "before",
                   "frame": frame, "uia": {"status": "ok", "capture_id": "before-1",
                                             "window_identity": identity, "snapshot": snapshot},
                   "candidate": {"capture_id": "before-1", "viewport_size": frame["image_size"],
                                 "source": "agent_visual", "bbox": controls[1]["bbox"],
                                 "click_point": {"x": 50, "y": 35}, "freshness": "current_capture"}}
    return tmp_path / "library", event, observation

def _fresh_learning(tmp_path, with_output=False):
    _root, _event, observation = observation_scene(tmp_path)
    session = tmp_path / 'new-image-learning'
    (session / 'responses').mkdir(parents=True)
    store = LearningEventStore(session)
    started = store.control('learning_start', {'scope': 'workflow',
        'title': '图像核验新合成任务', 'project_id': 'new-image-journey'}, 'start')
    command = {'kind': 'step', 'operation': 'execute_recognition_plan',
        'request': {'goal': 'Search', 'click_kind': 'single'}}
    ticket = store.prepare('open-detail', command, None)
    before_path, after_path = session / 'before.png', session / 'after.png'
    Image.new('RGB', (160, 100), 'white').save(before_path)
    image = Image.new('RGB', (160, 100), 'white')
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((80, 40, 145, 70), fill='#124e87')
    drawing.text((84, 45), 'DETAIL 731', fill='white')
    drawing.line((84, 64, 140, 64), fill='yellow', width=2)
    image.save(after_path)
    observation = deepcopy(observation)
    observation.update(event_id='open-detail', command_sha256=ticket['command_sha256'])
    observation['frame'].update(image_path=str(before_path), sha256=sha256(before_path.read_bytes()).hexdigest())
    after = {'image_path': str(after_path), 'sha256': sha256(after_path.read_bytes()).hexdigest(),
        'capture_id': 'new-after', 'window_size': {'width': 160, 'height': 100}}
    result = {'phase': 'returned', 'capture': after, 'observation': {'capture': after},
        'response': {'success': True, 'data': {'result': {
            'execution_path': {'action_executed': True}, 'learning_observation': observation}}}}
    write_json_snapshot(session / 'responses/open-detail.json', {
        'command': command, 'status': 'returned', 'learning_binding': ticket, 'result': result})
    store.record('open-detail', ticket)
    event = store.control('learning_event', {'event_id': 'open-detail'}, 'read')['event']
    store.control('learning_review', {'review': {
        'event_id': 'open-detail', 'event_sha256': content_hash(event), 'verdict': 'success',
        'reviewer': 'synthetic-ui-test', 'reason': '新合成离屏证据，不派发桌面输入',
        'before': {'interface_key': 'desk', 'state_key': 'home', 'meaning': '查询页',
            'frame_sha256': observation['frame']['sha256']},
        'after': {'interface_key': 'desk', 'state_key': 'detail', 'meaning': '详情页',
            'frame_sha256': after['sha256']}}}, 'review')
    stopped = store.control('learning_stop', {}, 'stop')
    request = stopped['synthesis']['synthesis_request']
    annotation = {'title': '打开详情', 'verification': {'kind': 'agent_judgment'}}
    if with_output:
        annotation['outputs'] = [{'name': 'detail', 'type': 'text'}]
    reply = store.control('learning_workflow', {'action': 'synthesis_complete',
        'synthesis_id': request['synthesis_id'], 'source_sha256': request['source_sha256'],
        'parameter_bindings': {}, 'annotations': {'open-detail': annotation}}, 'synthesis')
    assert reply['status'] == 'draft_ready', reply
    return session, tmp_path / 'memory-library', reply['draft'], after

def click_response(session, ticket):
    path = session / "responses" / (ticket["execution_request_id"] + ".json")
    commands = session / "commands"
    commands.mkdir(exist_ok=True)
    (commands / path.name).write_text(json.dumps(ticket["suggested_command"], ensure_ascii=False), encoding="utf-8")
    path.write_text(json.dumps({"status": "returned", "command": ticket["suggested_command"],
        "result": {"contract_version": "local_direct_step_v1", "phase": "returned",
                   "response": {"success": True, "data": {"execution_path": {"action_executed": True}}}}}, ensure_ascii=False), encoding="utf-8")
