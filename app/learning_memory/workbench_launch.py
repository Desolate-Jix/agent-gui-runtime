"""学习工作台启动适配；目录选择不建立运行宿主。"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

from scripts import run_learning_memory_workbench


def _check_writable(path):
    if not path.is_dir():
        raise ValueError('Agent data directory must be an existing directory')
    for attempt in range(3):
        probe = path / ('.agent-workbench-write-' + uuid.uuid4().hex + '.tmp')
        try:
            descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if attempt == 2:
                raise
            continue
        # 只有独占创建成功的探针归本次检查清理；权限错误不重试。
        try:
            os.close(descriptor)
        finally:
            probe.unlink()
        return


def select_data_dir(explicit, settings, picker):
    settings = Path(settings)
    remember = False
    if explicit is not None:
        selected = Path(explicit).expanduser().resolve()
    elif settings.exists():
        try:
            value = json.loads(settings.read_text(encoding='utf-8'))
            if not isinstance(value, dict) or set(value) != {'data_dir'} or not isinstance(value['data_dir'], str) or not Path(value['data_dir']).is_absolute():
                raise ValueError('invalid settings schema')
            selected = Path(value['data_dir']).resolve()
        except (ValueError, UnicodeError) as error:
            raise ValueError('learning workbench settings are invalid') from error
    else:
        choice = picker()
        if not choice:
            return None
        selected = Path(choice).resolve()
        remember = True
    _check_writable(selected)
    if remember:
        settings.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({'data_dir': str(selected)}, ensure_ascii=False, indent=2) + '\n'
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=settings.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        try:
            os.replace(temporary, settings)
        finally:
            temporary.unlink(missing_ok=True)
    return selected


def _run_workbench(data_dir, session_dir):
    original = sys.argv
    sys.argv = [original[0], '--data-dir', str(data_dir)]
    if session_dir is not None:
        sys.argv += ['--session-dir', str(session_dir)]
    try:
        return run_learning_memory_workbench.main()
    finally:
        sys.argv = original


def _check_startup(data_dir, report_path, *, language='zh-CN'):
    if os.environ.get('QT_QPA_PLATFORM') not in (None, 'offscreen'):
        raise ValueError('check-startup requires Qt offscreen platform')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from app.learning_memory import workflow_run_client
    from .workbench_i18n import initialize_i18n
    application = QApplication.instance() or QApplication([sys.argv[0]])
    preferences = tempfile.TemporaryDirectory(prefix='learning-startup-preferences-')
    manager = initialize_i18n(application, Path(preferences.name) / 'workbench-preferences.json', language)
    client_source = Path(workflow_run_client.__file__).resolve()
    report = {'passed': False, 'platform': application.platformName(), 'error': 'startup timeout',
              'frozen': bool(getattr(sys, 'frozen', False)),
              'runtime_root': str(client_source.parents[2]),
              'workbench_entry': str(Path(run_learning_memory_workbench.__file__).resolve()),
              'workflow_client_source': str(client_source),
              'execution_attachment_required': True, 'language': manager.language}
    if application.platformName() != 'offscreen':
        raise ValueError('check-startup refuses a non-offscreen QApplication')

    def inspect():
        try:
            windows = [window for window in application.topLevelWidgets() if hasattr(window, 'steps') and hasattr(window, 'tabs')]
            if len(windows) != 1:
                return
            window = windows[0]
            panel = window.steps.run_panel
            pages = [window.tabs.tabText(index) for index in range(window.tabs.count())]
            checks = {'three_pages': window.tabs.count() == 3 and
                      [window.tabs.widget(index) for index in range(3)] == [window.steps, window.projects, window.interfaces],
                      'disconnected': panel._client is None and panel._connected_path is None,
                      'execution_disabled': all(not button.isEnabled() for button in (panel.single_button, panel.run_button, panel.continue_button, panel.cancel_button))}
            report.update(pages=pages, checks=checks, passed=all(checks.values()), error=None)
            if window.steps.is_busy or window.projects.is_busy or window.interfaces.pane.is_busy:
                return
            window.close()
            if window.isVisible():
                report.update(passed=False, error='normal close rejected')
                application.exit(2)
            else:
                report['normal_close'] = True
        except Exception as error:
            report.update(passed=False, error=f'{type(error).__name__}: {error}')
            application.exit(2)

    timer = QTimer()
    timer.timeout.connect(inspect)
    timer.start(50)

    def timeout():
        report.update(passed=False, error='startup or normal close timeout')
        application.exit(2)

    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(timeout)
    deadline.start(15000)
    try:
        result = _run_workbench(data_dir, None)
        report['exit_code'] = result
        report['passed'] = bool(report['passed'] and report.get('normal_close') and result == 0)
    except Exception as error:
        report.update(passed=False, error=f'{type(error).__name__}: {error}')
    finally:
        timer.stop()
        deadline.stop()
        destination = Path(report_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        preferences.cleanup()
    return 0 if report['passed'] else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description='Open the existing learning workbench')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--session-dir', type=Path)
    parser.add_argument('--check-startup', type=Path)
    parser.add_argument('--check-language', choices=('zh-CN', 'en-US'))
    parser.add_argument('--startup-trace', type=Path,
                        help='Optional UTF-8 JSONL diagnostics in an absolute new file')
    args = parser.parse_args(argv)
    if args.check_startup and (args.data_dir is None or args.session_dir is not None):
        parser.error('--check-startup requires explicit --data-dir and forbids --session-dir')
    if args.check_language and not args.check_startup:
        parser.error('--check-language requires --check-startup')
    if args.check_startup:
        try:
            if args.check_language:
                return _check_startup(args.data_dir.resolve(), args.check_startup, language=args.check_language)
            return _check_startup(args.data_dir.resolve(), args.check_startup)
        except Exception as error:
            destination = args.check_startup.resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps({'passed': False,
                'error': f'{type(error).__name__}: {error}'}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            return 2
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from .workbench_i18n import initialize_i18n, tr
    application = QApplication.instance() or QApplication([sys.argv[0]])
    try:
        if args.startup_trace is not None:
            from .workbench_startup_trace import StartupTrace
            context = StartupTrace(application, args.startup_trace)
        else:
            context = nullcontext(None)
        with context as trace:
            if trace is not None:
                trace.record('qapplication_ready')
            local = Path(os.environ.get('LOCALAPPDATA', ''))
            if not local.is_absolute():
                raise ValueError('LOCALAPPDATA must be an absolute directory')
            initialize_i18n(application, local / 'AgentGUIRuntime' / 'workbench-preferences.json')
            if trace is not None:
                trace.record('directory_selection_before', explicit=args.data_dir is not None)

            def picker():
                if trace is not None:
                    trace.record('directory_picker_before')
                choice = QFileDialog.getExistingDirectory(None, str(tr('选择或新建学习数据目录')))
                if trace is not None:
                    trace.record('directory_picker_after', selected=bool(choice))
                return choice

            if args.data_dir is not None:
                data_dir = select_data_dir(args.data_dir, Path(), lambda: '')
            else:
                data_dir = select_data_dir(None, local / 'AgentGUIRuntime' / 'learning-workbench.json', picker)
            if trace is not None:
                trace.record('directory_selection_after', selected=data_dir is not None)
            if data_dir is None:
                return 0
            if trace is not None:
                trace.record('workbench_enter')
            result = _run_workbench(data_dir, args.session_dir)
            if trace is not None:
                trace.exit_code = result
                trace.record('workbench_return', exit_code=result)
            return result
    except (OSError, ValueError, RuntimeError) as error:
        QMessageBox.critical(None, str(tr('学习工作台启动失败')),
            str(tr('无法打开学习工作台，请检查目录和设置。')) + '\n' + str(error))
        return 2
