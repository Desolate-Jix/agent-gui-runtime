"""从固定目标状态的成功学习证据列出可选结果原图。"""
from hashlib import sha256
from io import BytesIO

from PIL import Image

from .graph_source import bundle_segments, read_source
from .projector import validate_event_review
from .reader import read_project


def read_workflow_image_options(library, workflow_id, project_snapshot_id, target_node_id):
    memory = read_project(library, workflow_id, project_snapshot_id)
    matches = [node for node in memory['graph']['nodes'] if node['node_id'] == target_node_id]
    if len(matches) != 1:
        raise ValueError('image_check_target_not_in_snapshot')
    source = library.load_graph_revision(workflow_id, memory['source_revision'])
    source_node = next((node for node in source['graph']['nodes'] if node['node_id'] == target_node_id), {})
    identity = source_node.get('memory_identity')
    if source['source_refs'].get('kind') != 'execution_memory' or not identity:
        return []
    bundle = read_source(library, source['source_refs'])
    options, seen = [], set()
    for segment in bundle_segments(bundle):
        for event in segment['events']:
            record = segment['reviews'].get(event['request_id'])
            if not record or record['review'].get('verdict') != 'success':
                continue
            review = validate_event_review(event, record['review'])
            after = review.get('after')
            if (not after or any(after[key] != identity[key] for key in ('interface_key', 'state_key'))
                    or event.get('status') != 'returned'
                    or event.get('after', {}).get('status') != 'referenced'
                    or (event.get('terminal_receipt') or {}).get('status', 'completed') != 'completed'):
                continue
            digest = after['frame_sha256']
            if digest in seen:
                continue
            path = library._artifact_file(f'desktop-review/evidence-objects/{digest}.png', '学习结果原图')
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != digest:
                raise ValueError('image_check_reference_hash_changed')
            with Image.open(BytesIO(raw)) as image:
                if image.format != 'PNG':
                    raise ValueError('image_check_reference_not_png')
                size = list(image.size)
                image.verify()
            seen.add(digest)
            options.append({'reference_sha256': digest, 'reference_size': size,
                'image_path': str(path.resolve()), 'label': after['meaning'] + ' · ' + event['request_id']})
    return options


__all__ = ['read_workflow_image_options']
