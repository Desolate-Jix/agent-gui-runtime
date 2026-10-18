"""字段原值仅留在本地不可变快照；公开证据只保留身份、摘要和结果。"""
from dataclasses import dataclass, field
from hashlib import sha256
import math
import json
import re
from collections.abc import Mapping

from .text_execution import text_execution_reference, validate_text_execution_reference
from .text_parameters import ResolvedTextParameters, validate_text_value, validate_text_parameter_reference


def _positive(value):
    return type(value) is int and value > 0


@dataclass(frozen=True, slots=True)
class TextFieldIdentity:
    target_field_id: str
    window_handle: int
    process_id: int
    process_create_time: float
    runtime_id: tuple[int, ...]
    window_rect: tuple[int, int, int, int]
    control_bbox: tuple[int, int, int, int]

    def __post_init__(self):
        if (not isinstance(self.target_field_id, str) or not self.target_field_id.strip()
                or len(self.target_field_id) > 256 or not _positive(self.window_handle)
                or not _positive(self.process_id) or type(self.process_create_time) not in (float, int)
                or not math.isfinite(self.process_create_time) or self.process_create_time <= 0):
            raise ValueError("text field process identity is invalid")
        if (type(self.runtime_id) is not tuple or not 1 <= len(self.runtime_id) <= 64
                or any(type(item) is not int for item in self.runtime_id)):
            raise ValueError("text field runtime identity is unavailable")
        for rect in (self.window_rect, self.control_bbox):
            if type(rect) is not tuple or len(rect) != 4 or any(type(item) is not int for item in rect) or min(rect[2:]) <= 0:
                raise ValueError("text field geometry is invalid")
        x, y, width, height = self.control_bbox
        if min(x, y) < 0 or x + width > self.window_rect[2] or y + height > self.window_rect[3]:
            raise ValueError("text field is outside the bound window")

    def to_reference(self):
        return {"target_field_id": self.target_field_id, "window_handle": self.window_handle,
                "process_id": self.process_id, "process_create_time": self.process_create_time,
                "runtime_id": list(self.runtime_id), "window_rect": list(self.window_rect),
                "control_bbox": list(self.control_bbox)}


@dataclass(frozen=True, slots=True)
class TextFieldSnapshot:
    identity: TextFieldIdentity
    capture_id: str
    read_id: str
    observed_at_ns: int
    source: str
    value: str = field(repr=False)
    selection: tuple[int, int] | None

    def __post_init__(self):
        if (type(self.identity) is not TextFieldIdentity or not _positive(self.observed_at_ns)
                or any(not isinstance(item, str) or not item or len(item) > 256 for item in (self.capture_id, self.read_id))
                or self.source not in {"uia_value", "uia_text"}):
            raise ValueError("text field snapshot identity is invalid")
        validate_text_value(self.value)
        selected = self.selection
        if selected is not None and (type(selected) is not tuple or len(selected) != 2
                or any(type(item) is not int for item in selected)
                or not 0 <= selected[0] <= selected[1] <= len(self.value)):
            raise ValueError("text field selection is invalid")

    def to_reference(self):
        return {"contract_version": "text_field_snapshot_reference_v1", "identity": self.identity.to_reference(),
                "capture_id": self.capture_id, "read_id": self.read_id, "observed_at_ns": self.observed_at_ns,
                "source": self.source, "value_sha256": sha256(self.value.encode("utf-8")).hexdigest(),
                "value_length": len(self.value), "selection": list(self.selection) if self.selection is not None else None}


def _expected_value(before, parameters):
    if type(before) is not TextFieldSnapshot or type(parameters) is not ResolvedTextParameters:
        raise ValueError("text field expectation requires immutable local inputs")
    if before.identity.target_field_id != parameters.reviewed.target_field_id:
        raise ValueError("text field does not match reviewed target")
    if parameters.reviewed.clear_existing:
        return parameters.text
    if before.selection is None:
        raise ValueError("text insertion requires the complete current selection")
    start, end = before.selection
    return validate_text_value(before.value[:start] + parameters.text + before.value[end:])


@dataclass(frozen=True, slots=True)
class TextFieldExpectation:
    before: TextFieldSnapshot = field(repr=False)
    parameters: ResolvedTextParameters = field(repr=False)
    expected_value: str = field(repr=False)

    def __post_init__(self):
        if self.expected_value != _expected_value(self.before, self.parameters):
            raise ValueError("text field expected value differs from the reviewed mode")

    def to_reference(self):
        return {"contract_version": "text_field_expectation_reference_v1", "before": self.before.to_reference(),
                "text_execution_ref": text_execution_reference(self.parameters),
                "expected_value_sha256": sha256(self.expected_value.encode("utf-8")).hexdigest(),
                "expected_value_length": len(self.expected_value)}


def prepare_text_field_expectation(before, parameters):
    return TextFieldExpectation(before, parameters, _expected_value(before, parameters))


def validate_text_field_precondition(expected, current):
    if (type(expected) is not TextFieldExpectation or type(current) is not TextFieldSnapshot
            or current.identity != expected.before.identity or current.source != expected.before.source
            or current.value != expected.before.value or current.read_id == expected.before.read_id
            or current.observed_at_ns <= expected.before.observed_at_ns
            or (not expected.parameters.reviewed.clear_existing and current.selection != expected.before.selection)):
        raise ValueError("text field precondition changed or is unavailable")


def _same_field_instance_reference(first, second):
    keys = {'target_field_id', 'window_handle', 'process_id', 'process_create_time',
            'runtime_id', 'window_rect', 'control_bbox'}
    return (set(first) == keys and set(second) == keys
            and all(first[key] == second[key] for key in keys - {'control_bbox'}))


def same_text_field_instance(first, second):
    """仅供执行后读取：实例身份不随控件布局变化，实际新几何仍须保留。"""
    return (type(first) is TextFieldIdentity and type(second) is TextFieldIdentity
            and _same_field_instance_reference(first.to_reference(), second.to_reference()))


def _result_contract(before, actual):
    # 旧回执继续按原严格几何策略校验，不用新规则静默改判历史。
    changed_layout = (actual is not None and _same_field_instance_reference(before['identity'], actual['identity'])
                      and before['identity']['control_bbox'] != actual['identity']['control_bbox'])
    return 'text_field_verification_v2' if changed_layout else 'text_field_verification_v1'


def verify_text_field_result(expected, current):
    if type(expected) is not TextFieldExpectation:
        raise ValueError("text field verification requires a frozen expectation")
    if type(current) is not TextFieldSnapshot:
        reason = "text_field_unavailable"
    elif not same_text_field_instance(current.identity, expected.before.identity) or current.source != expected.before.source:
        reason = "text_field_identity_changed"
    elif (current.read_id == expected.before.read_id or current.capture_id == expected.before.capture_id
          or current.observed_at_ns <= expected.before.observed_at_ns):
        reason = "text_field_read_not_new"
    elif current.value != expected.expected_value:
        reason = "text_value_mismatch"
    else:
        reason = "none"
    actual = current.to_reference() if type(current) is TextFieldSnapshot else None
    return {"contract_version": _result_contract(expected.before.to_reference(), actual), "status": "verified" if reason == "none" else "not_verified",
            "reason_code": reason, "expected": expected.to_reference(),
            "actual": actual,
            "artifact_is_authorization": False}


def validate_text_field_expectation_reference(value, declaration_reference):
    """严格核对不含原文的期望引用，供预览、消费和重启后验共用。"""
    declaration = validate_text_parameter_reference(declaration_reference)
    try:
        if not isinstance(value, Mapping):
            raise ValueError()
        result = json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))
        if set(result) != {'contract_version', 'before', 'text_execution_ref', 'expected_value_sha256', 'expected_value_length'}:
            raise ValueError()
        if result['contract_version'] != 'text_field_expectation_reference_v1':
            raise ValueError()
        before = result['before']
        if not isinstance(before, dict) or set(before) != {'contract_version', 'identity', 'capture_id', 'read_id', 'observed_at_ns', 'source', 'value_sha256', 'value_length', 'selection'}:
            raise ValueError()
        if before['contract_version'] != 'text_field_snapshot_reference_v1':
            raise ValueError()
        identity = before['identity']
        if not isinstance(identity, dict) or set(identity) != {'target_field_id', 'window_handle', 'process_id', 'process_create_time', 'runtime_id', 'window_rect', 'control_bbox'}:
            raise ValueError()
        typed_identity = TextFieldIdentity(**{**identity, 'runtime_id': tuple(identity['runtime_id']),
            'window_rect': tuple(identity['window_rect']), 'control_bbox': tuple(identity['control_bbox'])})
        if typed_identity.target_field_id != declaration['target_field_id']:
            raise ValueError()
        if (not _positive(before['observed_at_ns']) or before['source'] not in {'uia_value', 'uia_text'}
                or any(not isinstance(before[k], str) or not before[k] or len(before[k]) > 256 for k in ('capture_id', 'read_id'))):
            raise ValueError()
        for item, hash_key, length_key in ((before, 'value_sha256', 'value_length'), (result, 'expected_value_sha256', 'expected_value_length')):
            if (not isinstance(item[hash_key], str) or re.fullmatch(r'[0-9a-f]{64}', item[hash_key]) is None
                    or type(item[length_key]) is not int or not 0 <= item[length_key] <= 32768
                    or (item[length_key] == 0 and item[hash_key] != sha256(b'').hexdigest())):
                raise ValueError()
        selected = before['selection']
        if selected is not None and (not isinstance(selected, list) or len(selected) != 2
                or any(type(n) is not int for n in selected) or not 0 <= selected[0] <= selected[1] <= before['value_length']):
            raise ValueError()
        execution = validate_text_execution_reference(result['text_execution_ref'], declaration)
        if declaration['clear_existing']:
            if result['expected_value_sha256'] != execution['text_sha256'] or result['expected_value_length'] != execution['text_length']:
                raise ValueError()
        elif (selected is None or result['expected_value_length'] != before['value_length'] - (selected[1] - selected[0]) + execution['text_length']):
            raise ValueError()
        return result
    except (TypeError, ValueError, KeyError, OverflowError):
        raise ValueError('text field expectation reference is invalid') from None


def verify_text_field_result_reference(expected, current, *, declaration_reference):
    """重启后仅靠已封存引用做只读后验，不恢复原文或重新派发。"""
    expected = validate_text_field_expectation_reference(expected, declaration_reference)
    actual = current.to_reference() if type(current) is TextFieldSnapshot else None
    before = expected['before']
    if actual is None:
        reason = 'text_field_unavailable'
    elif not _same_field_instance_reference(actual['identity'], before['identity']) or actual['source'] != before['source']:
        reason = 'text_field_identity_changed'
    elif (actual['read_id'] == before['read_id'] or actual['capture_id'] == before['capture_id']
          or actual['observed_at_ns'] <= before['observed_at_ns']):
        reason = 'text_field_read_not_new'
    elif actual['value_sha256'] != expected['expected_value_sha256'] or actual['value_length'] != expected['expected_value_length']:
        reason = 'text_value_mismatch'
    else:
        reason = 'none'
    return {'contract_version': _result_contract(before, actual), 'status': 'verified' if reason == 'none' else 'not_verified',
            'reason_code': reason, 'expected': expected, 'actual': actual, 'artifact_is_authorization': False}


def validate_text_field_snapshot_reference(value):
    """回执中的实际字段摘要仍须有完整可核对的身份与偏移形状。"""
    try:
        if not isinstance(value, Mapping):
            raise ValueError()
        value = json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))
        if set(value) != {'contract_version', 'identity', 'capture_id', 'read_id', 'observed_at_ns', 'source', 'value_sha256', 'value_length', 'selection'}:
            raise ValueError()
        if value['contract_version'] != 'text_field_snapshot_reference_v1':
            raise ValueError()
        identity = value['identity']
        if set(identity) != {'target_field_id', 'window_handle', 'process_id', 'process_create_time', 'runtime_id', 'window_rect', 'control_bbox'}:
            raise ValueError()
        TextFieldIdentity(**{**identity, 'runtime_id': tuple(identity['runtime_id']),
            'window_rect': tuple(identity['window_rect']), 'control_bbox': tuple(identity['control_bbox'])})
        if (not _positive(value['observed_at_ns']) or value['source'] not in {'uia_value', 'uia_text'}
                or any(not isinstance(value[k], str) or not value[k] or len(value[k]) > 256 for k in ('capture_id', 'read_id'))
                or not isinstance(value['value_sha256'], str) or re.fullmatch(r'[0-9a-f]{64}', value['value_sha256']) is None
                or type(value['value_length']) is not int or not 0 <= value['value_length'] <= 32768
                or (value['value_length'] == 0 and value['value_sha256'] != sha256(b'').hexdigest())):
            raise ValueError()
        selected = value['selection']
        if selected is not None and (not isinstance(selected, list) or len(selected) != 2
                or any(type(n) is not int for n in selected) or not 0 <= selected[0] <= selected[1] <= value['value_length']):
            raise ValueError()
        return value
    except (TypeError, ValueError, KeyError, OverflowError):
        raise ValueError('text field snapshot reference is invalid') from None


def validate_text_field_verification_reference(value, declaration_reference):
    """从引用重算后验结果，不能只信调用方给出的 verified 标签。"""
    try:
        if not isinstance(value, Mapping):
            raise ValueError()
        value = json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))
        if (set(value) != {'contract_version', 'status', 'reason_code', 'expected', 'actual', 'artifact_is_authorization'}
                or value['contract_version'] not in {'text_field_verification_v1', 'text_field_verification_v2'}
                or value['artifact_is_authorization'] is not False):
            raise ValueError()
        expected = validate_text_field_expectation_reference(value['expected'], declaration_reference)
        actual = validate_text_field_snapshot_reference(value['actual']) if value['actual'] is not None else None
        before = expected['before']
        same_identity = (actual is not None and (actual['identity'] == before['identity']
            if value['contract_version'] == 'text_field_verification_v1'
            else _same_field_instance_reference(actual['identity'], before['identity'])))
        if actual is None:
            reason = 'text_field_unavailable'
        elif not same_identity or actual['source'] != before['source']:
            reason = 'text_field_identity_changed'
        elif (actual['read_id'] == before['read_id'] or actual['capture_id'] == before['capture_id']
              or actual['observed_at_ns'] <= before['observed_at_ns']):
            reason = 'text_field_read_not_new'
        elif actual['value_sha256'] != expected['expected_value_sha256'] or actual['value_length'] != expected['expected_value_length']:
            reason = 'text_value_mismatch'
        else:
            reason = 'none'
        if value['reason_code'] != reason or value['status'] != ('verified' if reason == 'none' else 'not_verified'):
            raise ValueError()
        return value
    except (TypeError, ValueError, KeyError, OverflowError):
        raise ValueError('text field verification reference is invalid') from None
