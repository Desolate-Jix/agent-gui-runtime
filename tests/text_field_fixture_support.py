"""合成字段边界供原生审核测试使用，不读取实际 UIA 或剪贴板。"""
import time

from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot


class SyntheticTextFieldReader:
    def __init__(self, value='原字段内容', selection=(0, 0)):
        self.value = value
        self.selection = selection
        self.calls = []

    def read_field(self, **request):
        self.calls.append(request)
        identity = TextFieldIdentity(request['target_field_id'], request['target_window_handle'],
            request['target_process_id'], request['process_create_time'], (42, 12),
            request['window_rect'], request['target_bbox'])
        return TextFieldSnapshot(identity, request['capture_id'], f'field-{len(self.calls)}',
            time.perf_counter_ns(), 'uia_value', self.value, self.selection)
