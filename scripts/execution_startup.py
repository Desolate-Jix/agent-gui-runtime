"""复用维护客户端的选窗后计划入口，不另建输入执行器。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path


def selection_ready(response, selection):
    try:
        command = selection["command"]
        result, image = response["result"], response["observation"]
        expected = {"handle": command["handle"], "process_id": command["process_id"]}
        original = response["preparation_preview"]["identity"]
        identity = {**expected, "process_create_time": original["process_create_time"]}
        if (command["kind"] != "select" or response["request_id"] != selection["request_id"]
                or response["status"] != "returned" or response["operation_succeeded"] is not True
                or response["client_state"] != "terminal" or result["status"] != "focused"
                or any(result["window"][key] != value for key, value in expected.items())
                or original["target_window_handle"] != expected["handle"]
                or original["process_id"] != expected["process_id"]
                or image["window_identity"] != identity
                or image["capture_visibility"]["allowed"] is not True
                or image["capture_visibility"]["bound_window_handle"] != expected["handle"]):
            return False
        path = Path(image["image_path"])
        return path.is_absolute() and path.is_file() and sha256(path.read_bytes()).hexdigest() == image["sha256"]
    except (KeyError, TypeError, ValueError, OSError):
        return False


async def run_selected_plan(client, selection, plan):
    if (selection.get("command", {}).get("kind") != "select"
            or plan.get("command", {}).get("kind") != "task_plan"
            or plan["command"].get("request", {}).get("action") != "start"):
        raise ValueError("execution_startup_commands_invalid")
    # 只消费本次完整成功的选窗证据，不按内部 focused 或旧图启动动作。
    response = await client.execute({**deepcopy(selection), "detail": "full"})
    if not selection_ready(response, selection):
        return {"stage": "selection", "plan_submitted": False, "response": response}
    return {"stage": "plan", "plan_submitted": True, "selection": response,
        "response": await client.execute(deepcopy(plan))}
