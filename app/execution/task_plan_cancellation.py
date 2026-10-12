"""只读取消队列门禁；不消费控制、不改账本、不授予输入权限。"""
from pathlib import Path

from app.core.instant_command_queue import CommandQueueBusy, _request_id, command_queue_lock
from app.core.json_snapshot import read_json_snapshot


class TaskPlanCancelPending(CommandQueueBusy):
    def __init__(self, request_id):
        super().__init__((request_id,))
        self.args = ("task_plan_cancel_pending:" + request_id,)


def assert_no_queued_plan_cancel(session_dir, run_id, *, ignore_request_ids=()):
    session = Path(session_dir).resolve()
    ignored = set(ignore_request_ids)
    with command_queue_lock(session):
        for path in sorted((session / "commands").glob("*.json")):
            if path.stem in ignored or (session / "responses" / path.name).is_file():
                continue
            try:
                _request_id(path.stem)
                if not path.resolve(strict=True).is_relative_to(session / "commands"):
                    raise ValueError("command_outside_session")
                command = read_json_snapshot(path)
                from app.instant_mcp import InstantCommand
                if InstantCommand.model_validate(command).command() != command:
                    raise ValueError("command_normalization_mismatch")
            except (OSError, ValueError, TypeError, UnicodeError) as error:
                raise ValueError("task_plan_queued_command_invalid:" + path.stem + ":" + type(error).__name__) from None
            request = command.get("request") or {}
            if (command["kind"] == "task_plan" and request.get("action") == "cancel"
                    and request.get("run_id") == run_id):
                raise TaskPlanCancelPending(path.stem)


__all__ = ["TaskPlanCancelPending", "assert_no_queued_plan_cancel"]
