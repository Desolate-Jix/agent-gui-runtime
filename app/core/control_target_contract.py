"""纯数据的原生目标合同；不引入定位、截图或输入能力。"""
from copy import deepcopy


CONTROL_TYPES = frozenset({"Button", "Hyperlink", "Edit", "ComboBox", "MenuItem", "TabItem"})
CONTAINER_TYPES = frozenset({"Window", "Pane", "Group", "Custom", "ToolBar", "Menu", "Tab"})


def validate_task_plan_control_target(value, *, for_input=False):
    if (not isinstance(value, dict) or not {"name", "control_type"} <= set(value)
            or set(value) - {"name", "control_type", "container"}):
        raise ValueError("task_plan_target_fields_invalid")
    def semantic(item, types):
        if (not isinstance(item, dict) or set(item) != {"name", "control_type"}
                or not isinstance(item["name"], str) or not item["name"].strip()
                or len(item["name"]) > 512 or not isinstance(item["control_type"], str)
                or item["control_type"] not in types):
            raise ValueError("task_plan_target_semantics_invalid")
    semantic({key: value[key] for key in ("name", "control_type")},
             {"Edit", "ComboBox"} if for_input else CONTROL_TYPES)
    if "container" in value:
        semantic(value["container"], CONTAINER_TYPES)
    return deepcopy(value)
