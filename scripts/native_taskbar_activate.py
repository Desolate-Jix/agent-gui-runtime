"""本地开发入口：先保存真实任务栏预览，再等待独立确认；不直接下发鼠标。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.desktop_backend import ExistingWindowsBackendAdapter
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.taskbar_activation import TaskbarActivationCallsite
from app.desktop_review.taskbar_activation_source import WindowsTaskbarActivationSource


def save(path: Path, value) -> None:
    with path.open('x', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-handle', type=int, required=True)
    parser.add_argument('--process-id', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--wait-for-local-confirmation', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = WindowsTaskbarActivationSource(output_dir=output / 'captures',
        destination_window_handle=args.window_handle, destination_process_id=args.process_id)
    owner = TaskbarActivationCallsite(source=source, backend=ExistingWindowsBackendAdapter(),
        journal_dir=output / 'activation')
    host = None
    report = {'phase': 'preparing', 'execution_requested': False, 'host_closed': False}
    try:
        preview = owner.prepare()
        save(output / 'preview.json', preview)
        print(json.dumps({'phase': 'preview_ready', 'preview_path': str(output / 'preview.json'),
            'image_path': preview['source']['image_path'], 'preview_sha256': preview['preview_sha256'],
            'confirmation_id': preview['confirmation_id']}, ensure_ascii=False), flush=True)
        if not args.wait_for_local_confirmation:
            owner.cancel_grounded_review(session_id=preview['session_id'])
            report['phase'] = 'preview_only_cancelled'
            return
        deadline = time.monotonic() + 90
        approval_path = output / 'local-decision.json'
        while not approval_path.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not approval_path.exists():
            owner.cancel_grounded_review(session_id=preview['session_id'])
            report['phase'] = 'confirmation_timed_out'
            return
        decision = json.loads(approval_path.read_text(encoding='utf-8'))
        if (not isinstance(decision, dict) or set(decision) != {'confirmation_id', 'preview_sha256', 'approved'}
                or decision['confirmation_id'] != preview['confirmation_id']):
            raise ValueError('local taskbar confirmation shape or identity differs')
        owner.record_decision(preview_sha256=decision['preview_sha256'], approved=decision['approved'])
        if decision['approved'] is not True:
            report['phase'] = 'denied'
            return
        host = DesktopReviewHost(output / 'inbox.json', output / 'reviews', secrets.token_urlsafe(32))
        host.start()
        host.attach_grounded_runtime(owner, confirmation_id=preview['confirmation_id'])
        report['execution_requested'] = True
        result = host.single_step.execute(confirmation_id=preview['confirmation_id'])
        save(output / 'response.json', result)
        report['phase'] = 'terminal'
        report['response'] = result
        report['destination_after'] = source.read_destination_foreground()
        host.release_grounded_runtime(confirmation_id=preview['confirmation_id'])
    except Exception as error:
        report['phase'] = 'failed'
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        if host is not None:
            try:
                host.close()
                report['host_closed'] = True
            except Exception as error:
                report['cleanup_error'] = {'type': type(error).__name__, 'message': str(error)}
        save(output / 'result.json', report)
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
