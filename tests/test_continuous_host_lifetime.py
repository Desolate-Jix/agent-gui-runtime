import ast
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest


RUNNER = Path(__file__).resolve().parents[1] / "scripts/run_local_step_session.py"


def run_lifecycle(parent_times):
    # 只执行真实循环的寿命条件、父进程检查和关闭分支，不加载桌面服务。
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    loop = next(n for n in ast.walk(main) if isinstance(n, ast.While)
                and any(isinstance(x, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "paths"
                    for t in x.targets) for x in n.body))
    parent_check = next(n for n in loop.body if isinstance(n, ast.If)
                        and ast.unparse(n.test) == "args.parent_pid")
    close_check = next(n for n in loop.body if isinstance(n, ast.If)
                       and ast.unparse(n.test) == "kind == 'close'")
    deadlines = [copy.deepcopy(n) for n in ast.walk(main) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "deadline" for t in n.targets)
                 and "3600" in ast.unparse(n.value)]
    projected = copy.deepcopy(loop)
    projected.body = [copy.deepcopy(parent_check), *ast.parse("kind = handle_command()").body,
                      copy.deepcopy(close_check)]
    program = ast.fix_missing_locations(ast.Module(body=deadlines + [projected], type_ignores=[]))
    clock = [0.0]
    handled = []
    identities = iter(parent_times)

    class NoSuchProcess(Exception):
        pass

    def process(pid):
        identity = next(identities)
        if identity is None:
            raise NoSuchProcess(pid)
        return SimpleNamespace(create_time=lambda: identity)

    def handle_command():
        handled.append(clock[0])
        clock[0] = 3601.0
        return "close" if len(handled) == 2 else "capture"

    namespace = {"time": SimpleNamespace(monotonic=lambda: clock[0]),
                 "args": SimpleNamespace(parent_pid=700), "parent_created": 10.0,
                 "psutil": SimpleNamespace(Process=process, NoSuchProcess=NoSuchProcess),
                 "handle_command": handle_command}
    exec(compile(program, str(RUNNER), "exec"), namespace)
    return handled


def test_live_parent_accepts_command_after_one_hour_and_explicit_close():
    assert run_lifecycle([10.0, 10.0]) == [0.0, 3601.0]


@pytest.mark.parametrize("identity", [None, 11.0])
def test_missing_or_reused_parent_stops_before_next_command(identity):
    assert run_lifecycle([10.0, identity]) == [0.0]


def test_parent_identity_failure_is_not_retried():
    with pytest.raises(StopIteration):
        run_lifecycle([])
