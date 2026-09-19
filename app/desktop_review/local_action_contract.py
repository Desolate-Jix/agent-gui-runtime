from copy import deepcopy


class LocalActionFieldsError(ValueError):
    def __init__(self, unknown_fields, allowed_fields):
        self.unknown_fields = sorted(unknown_fields)
        self.allowed_fields = sorted(allowed_fields)
        super().__init__(f"Unknown local action fields: {', '.join(self.unknown_fields)}; "
                         f"allowed fields: {', '.join(self.allowed_fields)}")


def _validated_request(operation, request):
    from app.api.models.request import ExecuteRecognitionPlanRequest, ScrollRequest, TypeTextRequest, ROIModel
    from .local_keyboard_action import LocalKeyRequest
    models = {"execute_recognition_plan": ExecuteRecognitionPlanRequest, "type_text": TypeTextRequest,
              "scroll": ScrollRequest, "press_key": LocalKeyRequest}
    if operation not in models or type(request) is not dict:
        raise ValueError("unsupported local non-learning action")
    model = models[operation]
    extra_fields = {"capture_roi"} if operation == "type_text" else set()
    allowed_fields = set(model.model_fields) | extra_fields
    if set(request) - allowed_fields:
        raise LocalActionFieldsError(set(request) - allowed_fields, allowed_fields)
    value = deepcopy(request)
    if operation == "execute_recognition_plan":
        if any(value.get(key) is not None for key in (
                "approved_plan_id", "learned_instruction_id", "interface_memory_id", "interface_memory_action_id",
                "learning_mode", "observe_trace_path", "image_path")):
            raise ValueError("local non-learning actions cannot load learning or saved action sources")
        value.update(agent_mode="execute", learning_mode=None, capture_live=True,
                     auto_observe_learning_artifacts=False, allow_saved_image_execution=False,
                     write_policy={"path_graph": False, "element_memory": False, "trace": True},
                     max_execution_attempts=1)
    elif operation == "type_text":
        if value.get("submit", False) is not False:
            error = ValueError("local text entry requires submit=false; "
                               "use a separate press_key Enter action to submit search")
            error.invalid_fields = ["submit"]
            error.allowed_fields = sorted(allowed_fields)
            raise error
        # 显式 false 沿用当前焦点与选区；坐标仍用于核对当前窗口，不隐式再次点击。
        if type(value.get("click_before_typing")) is not bool or value.get("x") is None or value.get("y") is None:
            raise ValueError("local text entry requires explicit click_before_typing and a current field point")
    metadata = value.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("local action metadata must be an object")
    if "auto_observe_learning_artifacts" in metadata or "learning_artifacts" in metadata:
        raise ValueError("local non-learning actions cannot request learning artifacts")
    if metadata.get("path_graph_action_context") is not None:
        raise ValueError("local non-learning actions cannot update a path graph")
    validated = model.model_validate(value).model_dump()
    if operation == "type_text" and value.get("capture_roi") is not None:
        validated["capture_roi"] = ROIModel.model_validate(value["capture_roi"]).model_dump()
    return validated
