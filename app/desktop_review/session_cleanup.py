"""清理失败保留原 owner，显式重试只调用 shutdown，不重放动作。"""
from copy import deepcopy
import time


def shutdown_retaining_owner(coordinator, report, save_report, retry_token, *, wait=time.sleep):
    def read_token():
        try:
            value = retry_token()
            report.pop('cleanup_signal_error', None)
            return value
        except (OSError, ValueError) as error:
            report['cleanup_signal_error'] = type(error).__name__
            return None

    def publish():
        try:
            report.pop('cleanup_report_error', None)
            save_report()
        except (OSError, ValueError) as error:
            report['cleanup_report_error'] = type(error).__name__

    consumed = read_token()
    while True:
        try:
            coordinator.shutdown()
            report['cleanup_errors'] = []
            report.pop('cleanup_next', None)
            return
        except Exception as error:
            entry = {'operation': 'shutdown', 'error_type': type(error).__name__}
            code = getattr(error, 'code', None)
            if isinstance(code, str):
                entry['error_code'] = code
            diagnostics = getattr(error, 'diagnostics', None)
            if isinstance(diagnostics, dict) and diagnostics.get('contract_version') in {
                    'model_service_cleanup_diagnostics_v1', 'model_service_startup_diagnostics_v1'}:
                entry['diagnostics'] = deepcopy(diagnostics)
            report['phase'] = 'cleanup_pending'
            report['cleanup_errors'] = [entry]
            report.setdefault('cleanup_attempts', []).append(deepcopy(entry))
            report.pop('finished_at', None)
            report['cleanup_next'] = 'Inspect cleanup diagnostics, resolve the blocker, then call instant_stop to retry cleanup only.'
            publish()
        ticks = 0
        while True:
            current = read_token()
            if current is not None and current != consumed:
                consumed = current
                break
            wait(.25)
            ticks += 1
            if ticks % 4 == 0 and report.get('cleanup_report_error'):
                publish()
