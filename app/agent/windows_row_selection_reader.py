"""原生列表行的只读选中与编辑状态；不读取文本值或执行输入。"""
from copy import deepcopy
from hashlib import sha256
import json

from . import windows_form_control_reader as shared
from .native_identity import WindowsNativeIdentityReader

MAX_ROW_SCAN_EDGES = shared.MAX_FORM_SCAN_EDGES


class RowSelectionReadError(ValueError):
    """仅向调用方暴露稳定原因码。"""
    def __init__(self, reason_code, *, failure_evidence=None):
        self.failure_evidence = deepcopy(failure_evidence)
        self.reason_code = reason_code
        super().__init__(reason_code)


def _fail(reason):
    raise RowSelectionReadError('row_selection_' + reason)



SCAN_DIFFERENCE_VERSION = 'row_selection_scan_difference_v1'
MAX_FAILURE_EVIDENCE_BYTES = 16384
_SCAN_FIELDS = ('description', 'list', 'topology', 'selected', 'editing', 'editors', 'scan')


def _bounded_fact(value, depth=0):
    # 证据只保留有界 JSON 基本值，不传递 COM 对象。
    if value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, str):
        return value[:256]
    if depth >= 4:
        return None
    if isinstance(value, (list, tuple)):
        return [_bounded_fact(item, depth + 1) for item in value[:16]]
    if isinstance(value, dict):
        return {key: _bounded_fact(item, depth + 1) for key, item in list(value.items())[:16]
                if isinstance(key, str) and len(key) <= 64}
    return None


def _scan_difference(before, after, identity, window):
    def description(value):
        return {key: _bounded_fact(value.get(key)) for key in ('runtime_id', 'bbox', 'label', 'control_type')}
    def summary(scan):
        topology = scan['topology']
        digest = sha256(json.dumps(topology, ensure_ascii=False, separators=(',', ':'),
                                   allow_nan=False).encode('utf-8')).hexdigest()
        return {'row': description(scan['description']), 'list': description(scan['list']),
                'selected': scan['selected'], 'editing': scan['editing'],
                'editors': [description(item) for item in scan['editors'][:1]],
                'topology': {'count': len(topology), 'sha256': digest},
                'scan': _bounded_fact(scan['scan'])}
    return {'contract_version': SCAN_DIFFERENCE_VERSION,
            'changed_fields': [key for key in _SCAN_FIELDS if before.get(key) != after.get(key)],
            'window_binding': {'identity': _bounded_fact(identity), 'window_rect': list(window)},
            'before': summary(before), 'after': summary(after)}


def row_selection_failure_evidence(error):
    # 仅接受本读取器的特定失败，不复制任意异常上的原始字典。
    if type(error) is not RowSelectionReadError or error.reason_code != 'row_selection_state_changed':
        return None
    value = error.failure_evidence
    if (not isinstance(value, dict) or set(value) != {'contract_version', 'changed_fields', 'window_binding', 'before', 'after'}
            or value.get('contract_version') != SCAN_DIFFERENCE_VERSION
            or not isinstance(value.get('changed_fields'), list)
            or not value['changed_fields'] or any(item not in _SCAN_FIELDS for item in value['changed_fields'])):
        return None
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_FAILURE_EVIDENCE_BYTES:
            return None
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError):
        return None


def _boolean(value):
    return bool(value) if type(value) in (bool, int) and value in (0, 1) else None


def _value_readonly(node):
    # 仅专用无模式异常证明不存在；供应方读取失败不能解释为虚拟名称控件。
    from pywinauto.uia_defines import NoPatternInterfaceError
    try:
        pattern = node.iface_value
    except NoPatternInterfaceError:
        return False, None
    except Exception:
        _fail('editor_pattern_unavailable')
    try:
        value = _boolean(pattern.CurrentIsReadOnly)
    except Exception:
        _fail('editor_pattern_unavailable')
    if value is None:
        _fail('editor_pattern_unavailable')
    return True, value


def read_row_selection(coordinator, target, row_name, *, expected_runtime_id=None):
    """COM创建、有限扫描和双读复验均限定于原所有者线程。"""
    try:
        if (not isinstance(target, dict)
                or any(type(target.get(key)) is not int or target[key] <= 0 for key in ('handle', 'process_id'))
                or not isinstance(row_name, str) or not row_name.strip() or len(row_name) > 1024):
            _fail('request_invalid')
        expected = None if expected_runtime_id is None else shared._runtime_id(expected_runtime_id)
        return coordinator._owner.call(lambda: _read_on_owner(
            coordinator, target['handle'], target['process_id'], row_name, expected))
    except RowSelectionReadError:
        raise
    except shared.FormControlReadError as error:
        reason = error.reason_code.removeprefix('form_control_')
        raise RowSelectionReadError('row_selection_' + reason) from None
    except Exception:
        raise RowSelectionReadError('row_selection_provider_unavailable') from None


def _scan(root, walker, wrap, handle, pid, window, row_name):
    diagnostics = {}
    nodes = list(shared._descendants(root, walker, wrap, limit=MAX_ROW_SCAN_EDGES, diagnostics=diagnostics))
    if diagnostics.get('graph_scan_complete') is not True:
        _fail('scan_incomplete')
    lists = [node for node in nodes if node.element_info.control_type == 'List']
    if len(lists) != 1:
        _fail('list_ambiguous' if lists else 'list_not_found')
    listing = lists[0]
    element = listing.element_info.element
    hwnd = getattr(element, 'CurrentNativeWindowHandle', None)
    if (getattr(element, 'CurrentFrameworkId', None) != 'Win32'
            or getattr(element, 'CurrentClassName', None) != 'SysListView32'
            or type(hwnd) is not int or hwnd <= 0):
        _fail('provider_unsupported')
    list_description = shared._describe(listing, handle, pid, window)
    list_id = shared._runtime_id(listing.element_info.runtime_id)
    rows = [node for node in nodes if node.element_info.control_type == 'ListItem'
            and node.element_info.name == row_name]
    if len(rows) != 1:
        _fail('ambiguous' if rows else 'not_found')
    row = rows[0]
    if shared._tree_parent(row, walker, wrap) != list_id:
        _fail('row_scope_unavailable')
    description = shared._describe(row, handle, pid, window)
    selected = _boolean(shared._pattern_property(row, 'iface_selection_item', 'CurrentIsSelected'))
    if selected is None:
        _fail('state_unavailable')
    row_id = shared._runtime_id(row.element_info.runtime_id)
    parent_ids = {shared._runtime_id(node.element_info.runtime_id): shared._tree_parent(node, walker, wrap)
                  for node in [root, *nodes]}
    root_id = shared._runtime_id(root.element_info.runtime_id)
    row_ids = {shared._runtime_id(node.element_info.runtime_id) for node in nodes
               if node.element_info.control_type == 'ListItem'
               and parent_ids[shared._runtime_id(node.element_info.runtime_id)] == list_id}

    def in_list(runtime_id):
        # 仅沿本次已完整校验的父边映射判断归属，不再次遍历供应方。
        seen = set()
        while runtime_id is not None:
            if runtime_id == list_id:
                return True
            # 本次扫描以绑定窗口为根；外部Desktop父边只保留事实，不越界判断归属。
            if runtime_id == root_id:
                return False
            if runtime_id in seen or runtime_id not in parent_ids:
                _fail('editor_scope_unavailable')
            seen.add(runtime_id)
            runtime_id = parent_ids[runtime_id]
        return False

    editors = []
    for node in nodes:
        if node.element_info.control_type != 'Edit':
            continue
        parent = shared._tree_parent(node, walker, wrap)
        if not in_list(shared._runtime_id(node.element_info.runtime_id)):
            continue
        edit = node.element_info.element
        native = getattr(edit, 'CurrentNativeWindowHandle', None)
        has_value, readonly = _value_readonly(node)
        # 行下无原生句柄及Value模式的虚拟名称Edit不是活动重命名框，焦点不能改变此事实。
        if (parent in row_ids and (native is None or type(native) is int and native == 0)
                and not has_value and getattr(edit, 'CurrentClassName', None) == ''
                and getattr(edit, 'CurrentFrameworkId', None) == 'Win32'):
            continue
        if (parent != list_id or type(native) is not int or native <= 0
                or getattr(edit, 'CurrentClassName', None) != 'Edit'
                or getattr(edit, 'CurrentFrameworkId', None) != 'Win32'
                or readonly is not False
                or _boolean(getattr(edit, 'CurrentHasKeyboardFocus', None)) is not True):
            _fail('editor_unavailable')
        editor = shared._describe(node, handle, pid, window)
        box, row_box = editor['bbox'], description['bbox']
        if not (row_box['x'] <= box['x'] and row_box['y'] <= box['y']
                and box['x'] + box['w'] <= row_box['x'] + row_box['w']
                and box['y'] + box['h'] <= row_box['y'] + row_box['h']):
            _fail('editor_scope_unavailable')
        editors.append(editor)
    if len(editors) > 1:
        _fail('editor_ambiguous')
    topology = [(shared._tree_identity(node), shared._tree_parent(node, walker, wrap)) for node in [root, *nodes]]
    return {'description': description, 'list': list_description, 'topology': topology,
            'selected': selected, 'editing': bool(editors), 'editors': editors,
            'scan': {'graph_scan_complete': True, 'provider_tree_valid': diagnostics['provider_tree_valid'],
                     'edge_count': diagnostics['edge_count'], 'alias_count': diagnostics['alias_count']}}


def _read_on_owner(coordinator, handle, pid, row_name, expected):
    windows = coordinator._windows()
    native = WindowsNativeIdentityReader(window_manager=windows)
    identity, window = shared._window_snapshot(windows, native, handle, pid)
    desktop, walker, wrap = shared._uia_factory()
    root = desktop.window(handle=handle).wrapper_object()
    if shared._top_window_handle(root) != handle or root.element_info.process_id != pid:
        _fail('window_mismatch')
    before = _scan(root, walker, wrap, handle, pid, window, row_name)
    if expected is not None and tuple(before['description']['runtime_id']) != expected:
        _fail('identity_changed')
    if (identity, window) != shared._window_snapshot(windows, native, handle, pid):
        _fail('window_changed')
    after = _scan(root, walker, wrap, handle, pid, window, row_name)
    if before != after:
        raise RowSelectionReadError('row_selection_state_changed',
            failure_evidence=_scan_difference(before, after, identity, window))
    if (identity, window) != shared._window_snapshot(windows, native, handle, pid):
        _fail('window_changed')
    return {'source': 'windows_uia', 'kind': 'row_selection', **after['description'],
            'label': row_name, 'container_runtime_id': after['list']['runtime_id'],
            'window_identity': identity, 'window_rect': list(window),
            'selected': after['selected'], 'editing': after['editing'], 'state_available': True,
            'scan': after['scan']}


__all__ = ['RowSelectionReadError', 'read_row_selection']
