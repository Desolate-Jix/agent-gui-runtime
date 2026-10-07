"""新学习默认只提议能区分操作前后状态的局部图像规则。"""
from hashlib import sha256
from types import SimpleNamespace

from PIL import Image, ImageDraw


def _scene(tmp_path, changed=True):
    root = tmp_path / 'library'
    directory = root / 'desktop-review/evidence-objects'
    directory.mkdir(parents=True)
    before = Image.new('RGB', (240, 140), 'white')
    after = before.copy()
    if changed:
        draw = ImageDraw.Draw(after)
        draw.rectangle((25, 30, 92, 60), outline='black', width=2)
        draw.text((32, 38), 'DETAIL', fill='black')
    hashes = []
    for index, image in enumerate((before, after)):
        path = tmp_path / f'frame-{index}.png'
        image.save(path)
        digest = sha256(path.read_bytes()).hexdigest()
        (directory / (digest + '.png')).write_bytes(path.read_bytes())
        hashes.append(digest)
    return SimpleNamespace(_artifact_root=root), hashes


def test_default_proposal_uses_a_changed_local_feature(tmp_path):
    from app.learning_memory.image_verification_proposal import propose_image_check
    library, (before, after) = _scene(tmp_path)
    check = propose_image_check(library, before, after)
    assert check is not None
    assert check['reference_sha256'] == after
    assert check['reference_size'] == [240, 140]
    x, y, width, height = check['template_bbox']
    assert x <= 25 and y <= 30 and x + width >= 92 and y + height >= 60
    assert width * height < 240 * 140 // 2


def test_unchanged_state_has_no_automatic_success_rule(tmp_path):
    from app.learning_memory.image_verification_proposal import propose_image_check
    library, (before, after) = _scene(tmp_path, changed=False)
    assert propose_image_check(library, before, after) is None


def test_missing_evidence_keeps_agent_path(tmp_path):
    from app.learning_memory.image_verification_proposal import propose_image_check
    library, (before, _after) = _scene(tmp_path)
    assert propose_image_check(library, before, '0' * 64) is None


def test_new_transition_gets_default_check_but_dynamic_output_keeps_reader(tmp_path):
    from app.learning_memory.image_verification_proposal import apply_default_image_verification
    library, (before, after) = _scene(tmp_path)
    event = {'before': {'status': 'referenced', 'sha256': before},
             'after': {'status': 'referenced', 'sha256': after}}
    step = {'action': {'kind': 'click'}, 'source_node_id': 'home', 'target_node_id': 'detail', 'outputs': []}
    assert apply_default_image_verification(library, step, event) is True
    assert step['verification']['kind'] == 'agent_judgment'
    assert step['verification']['image_check']['reference_sha256'] == after
    dynamic = {'action': {'kind': 'read_text'}, 'source_node_id': 'home', 'target_node_id': 'detail',
               'outputs': [{'name': 'current_value', 'type': 'text'}]}
    assert apply_default_image_verification(library, dynamic, event) is False
    assert 'verification' not in dynamic


def test_same_state_focus_change_is_not_a_default_jump_rule(tmp_path):
    from app.learning_memory.image_verification_proposal import apply_default_image_verification
    library, (before, after) = _scene(tmp_path)
    step = {'action': {'kind': 'click'}, 'source_node_id': 'home', 'target_node_id': 'home', 'outputs': []}
    assert apply_default_image_verification(library, step, {
        'before': {'status': 'referenced', 'sha256': before},
        'after': {'status': 'referenced', 'sha256': after}}) is False
