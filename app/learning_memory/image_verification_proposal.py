"""新学习默认提议可区分前后状态的局部规则，仍需审核。"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .image_verification import match_image_check, load_reference_image


def propose_image_check(library, before_sha256, after_sha256):
    if before_sha256 == after_sha256:
        return None
    directory = Path(library._artifact_root) / 'desktop-review/evidence-objects'
    frames, paths = [], []
    for digest in (before_sha256, after_sha256):
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest):
            return None
        path = directory / (digest + '.png')
        if not path.is_file():
            return None
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != digest:
            raise ValueError('image_proposal_reference_changed')
        with Image.open(BytesIO(raw)) as image:
            if image.format != 'PNG':
                return None
            frames.append(np.array(image.convert('RGB')))
        paths.append(path)
    before, after = frames
    if before.shape != after.shape:
        return None
    height, width = after.shape[:2]
    changed = (np.abs(after.astype(np.int16) - before.astype(np.int16)).mean(axis=2) > 24).astype(np.uint8)
    changed = cv2.dilate(changed, np.ones((5, 5), dtype=np.uint8))
    count, _labels, stats, _centers = cv2.connectedComponentsWithStats(changed, 8)
    candidates = sorted(stats[1:count], key=lambda row: int(row[4]), reverse=True)
    for cx, cy, cw, ch, _area in candidates[:20]:
        x, y = max(0, int(cx)-4), max(0, int(cy)-4)
        w, h = min(width, int(cx+cw)+4)-x, min(height, int(cy+ch)+4)-y
        if w < 24 or h < 12 or w*h >= width*height//2:
            continue
        check = {'contract_version': 'workflow_image_check.v1', 'reference_sha256': after_sha256,
            'reference_size': [width, height], 'template_bbox': [x, y, w, h],
            'search_roi': [x, y, w, h], 'threshold': .95}
        try:
            reference = load_reference_image(library, check)
        except ValueError as error:
            if str(error) == 'workflow_image_template_low_texture':
                continue
            raise
        proofs = []
        for path, digest in zip(paths, (before_sha256, after_sha256)):
            frame = {'capture_id': 'proposal:' + digest, 'sha256': digest, 'image_path': str(path),
                'image_size': {'width': width, 'height': height}, 'window_rect': [0, 0, width, height]}
            proofs.append(match_image_check(check, reference, frame))
        if proofs[1]['matched'] and proofs[0]['reason'] == 'image_not_matched':
            return check
    return None


def apply_default_image_verification(library, step, event):
    rule = step.get('verification')
    if (step.get('outputs') or 'read_spec' in step or step['action']['kind'] == 'read_text'
            or step['source_node_id'] == step['target_node_id']
            or rule is not None and (rule.get('kind') != 'agent_judgment' or 'image_check' in rule)):
        return False
    before, after = event.get('before') or {}, event.get('after') or {}
    if before.get('status') != 'referenced' or after.get('status') != 'referenced':
        return False
    check = propose_image_check(library, before.get('sha256'), after.get('sha256'))
    if check is None:
        return False
    step['verification'] = {'kind': 'agent_judgment', 'image_check': check}
    return True


__all__ = ['propose_image_check', 'apply_default_image_verification']
