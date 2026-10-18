"""从宿主记忆库解析当前目标，交还原动作执行器。"""
from copy import deepcopy
from pathlib import Path

from app.core.memory_grounding_target import MemoryGroundingTarget
from .target_recipe import action_semantics_sha256, load_target_recipe, validate_target_reference
from .target_resolution import resolve_target_recipe
from .workspace import MemoryWorkspace


def prepare_memory_grounding(coordinator, *, request, handle, pid, action=None, memory_bindings=None):
    from .memory_observation import capture_memory_observation

    root = getattr(coordinator, "_memory_library_root", None)
    if root is None or not Path(root).is_dir():
        raise ValueError("memory_library_unavailable")
    root = Path(root).resolve()
    reference = validate_target_reference(request.get("target_memory"))
    if memory_bindings is not None:
        from .workflow_target_bindings import contextual_target_goal
        if (not isinstance(memory_bindings, dict) or not isinstance(memory_bindings.get("action"), dict)
                or memory_bindings["action"].get("target_memory") != reference):
            raise ValueError("workflow_target_bindings_invalid")
        bound_action = deepcopy(memory_bindings["action"])
        if action is not None and any(bound_action.get(key) != value for key, value in action.items()):
            raise ValueError("workflow_target_action_mismatch")
        action = bound_action
    else:
        action = deepcopy(action) if action is not None else {
            "kind": "click", "goal": request.get("goal"), "click_kind": request.get("click_kind", "single")}
        if request.get('selection_intent') is not None:
            action['selection_intent'] = request['selection_intent']
    goal = action.get("field_goal") if action.get("kind") == "input_sequence" else action.get("goal")
    if goal != request.get("goal"):
        raise ValueError("memory_action_goal_mismatch")
    if action.get("kind") == "click" and action.get("click_kind", "single") != request.get("click_kind", "single"):
        raise ValueError("memory_action_click_kind_mismatch")
    if action.get('selection_intent') != request.get('selection_intent'):
        raise ValueError('memory_action_selection_intent_mismatch')
    with MemoryWorkspace(root) as library:
        recipe = load_target_recipe(library, reference)
        if action_semantics_sha256(action, scope=recipe["scope"], strategies=recipe["strategies"]) != recipe["action_semantics_sha256"]:
            raise ValueError("action_semantics_changed")
    dynamic = any(row["kind"] == "visible_row" for row in recipe["strategies"])
    if dynamic and memory_bindings is None:
        raise ValueError("workflow_target_bindings_required")
    grounding_goal = contextual_target_goal(recipe, memory_bindings) if memory_bindings is not None else goal
    resolver_bindings = ({key: deepcopy(memory_bindings[key]) for key in ("action", "run_id", "inputs", "outputs")}
                         if memory_bindings is not None else {"action": action})
    manager = coordinator._windows()
    bound = manager.bind_window_by_handle(handle)
    if bound is None or bound.handle != handle or bound.process_id != pid:
        raise ValueError("memory_window_binding_changed")

    def read_current(image_path=None):
        # 原生读取期间释放库锁，每次匹配重新校验不可变文件及其证据。
        frame, observations = capture_memory_observation(coordinator, handle, pid,
            image_path=image_path, recipe=recipe)
        with MemoryWorkspace(root) as library:
            result = resolve_target_recipe(library, reference, frame=frame,
                observations=observations, bindings=resolver_bindings)
        if result["status"] not in {"matched", "miss", "ambiguous", "unsupported"}:
            raise ValueError("memory_resolution_invalid:" + result["reason"])
        if request.get('selection_intent') is not None:
            from .selection_satisfaction import validate_selection_intent
            validate_selection_intent(action, recipe['strategies'])
            if result['status'] != 'matched' or memory_bindings is None:
                raise ValueError('selection_unique_bound_row_required')
            row = result['evidence']['row']
            controls = observations['uia']['snapshot']['controls']
            actual = next(item for item in controls if item['control_id'] == row['row_control_id'])
            container = next(item for item in controls if item['control_id'] == row['container_control_id'])
            row['runtime_id'] = deepcopy(actual.get('runtime_id'))
            row['container_runtime_id'] = deepcopy(container.get('runtime_id'))
            if not row['runtime_id'] or not row['container_runtime_id']:
                raise ValueError('selection_runtime_identity_required')
            from app.agent.windows_row_selection_reader import read_row_selection
            result['row_selection'] = read_row_selection(coordinator, {'handle': handle, 'process_id': pid},
                actual['name'], expected_runtime_id=row['runtime_id'])
            from .selection_satisfaction import validate_selection_state
            validate_selection_state(result)
        result["grounding_goal"] = grounding_goal
        return result

    resolution = read_current()
    target = (MemoryGroundingTarget(reference, resolution, read_current=read_current,
              **({'selection_request': request, 'selection_bindings': {**memory_bindings,
                  'session_directory': str(Path(coordinator._runtime_output_root).resolve().parent)}}
                 if request.get('selection_intent') is not None else {}))
              if resolution["status"] == "matched" else None)
    return target, resolution
