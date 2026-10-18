"""读取一张确切截图中的文字；不把 OCR 输出当作整页内容或动作成功证明。"""
from copy import deepcopy
import hashlib
from pathlib import Path
import time
from PIL import Image


def read_captured_text(capture, *, max_chars=10000, scanner=None):
    if type(max_chars) is not int or not 1 <= max_chars <= 20000:
        raise ValueError('max_chars must be an integer from 1 to 20000')
    path = Path(capture['image_path']).resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != capture.get('sha256'):
        raise ValueError('capture digest does not match image')
    with Image.open(path) as image:
        width, height = image.size
    if scanner is None:
        from app.core.ocr_service import ocr_service
        scanner = ocr_service.scan_image
    started = time.perf_counter()
    result = scanner(str(path))
    ocr_ms = round((time.perf_counter() - started) * 1000, 3)
    if not result.image_path or Path(result.image_path).resolve() != path:
        raise ValueError('OCR result references another image')
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('capture digest changed during OCR')
    text, lines, truncated = '', [], False
    # 保留引擎顺序，不能据此声称多栏文章已恢复正确阅读顺序。
    for match in result.matches:
        if not match.text:
            continue
        separator = '\n' if lines else ''
        available = max_chars - len(text) - len(separator)
        if available <= 0:
            truncated = True
            break
        value = match.text[:available]
        text += separator
        start = len(text)
        text += value
        partial = len(value) != len(match.text)
        lines.append({'text': value, 'score': float(match.score), 'bbox': match.bbox.to_dict(),
                      'text_start': start, 'text_end': len(text), 'text_truncated': partial})
        if partial:
            truncated = True
            break
    return {
        'contract_version': 'captured_text_v1',
        'status': 'text_observed' if lines else 'no_text_detected',
        'text': text, 'lines': lines, 'truncated': truncated, 'max_chars': max_chars,
        'read_complete': False, 'scope': 'captured_visible_pixels_only',
        'reading_order': 'ocr_engine_order', 'coordinate_space': 'capture_image_pixels',
        'image_size': {'width': width, 'height': height},
        'capture': deepcopy(capture), 'provider': deepcopy(result.metadata),
        'ocr_ms': ocr_ms,
        'action_executed': False, 'task_effect_verified': None,
        'limitations': ['OCR can omit or misread text; inspect the original image.',
                        'Offscreen, masked and not-yet-rendered content is not read.',
                        'Browser chrome and visible overlays may be included; this is not a DOM or article extractor.',
                        'No text detected does not prove that the page is empty.'],
    }
