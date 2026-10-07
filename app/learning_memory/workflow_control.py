"""工作流定义和试运行的只读/记账入口，不派发桌面输入。"""


FIELDS = {
    "takeover_preview": ({"admission_request_id", "source_run_id"}, {"resolution"}),
    "takeover_commit": ({"preview_request_id", "preview_sha256", "mode"}, {"vision_capabilities"}),
    "record_model_call": ({"scope", "model_call"}, set()),
    "synthesis_prepare": ({"learning_session_id"}, set()),
    "synthesis_status": ({"synthesis_id"}, set()),
    "synthesis_resume": ({"synthesis_id", "source_sha256", "after_reply_request_id", "user_instruction"}, set()),
    "synthesis_complete": ({"synthesis_id", "source_sha256", "parameter_bindings", "annotations"}, {"resume_request_id"}),
    "compile": ({"learning_session_id"}, {"parameter_bindings", "annotations"}),
    "read": ({"workflow_id"}, {"program_id"}),
    "save": ({"workflow_id", "expected_sha256", "definition"}, {"target_recipes"}),
    "start": ({"workflow_id", "program_id", "start_step_id", "inputs"}, {"execution_strategy"}),
    "prepare": ({"run_id"}, {"observations", "vision_capabilities"}),
    "review": ({"run_id", "execution_request_id", "verdict", "observations", "outputs"}, set()),
    "verify": ({"run_id", "execution_request_id"}, set()),
    "run": ({"run_id", "mode"}, {"vision_capabilities"}),
    "continue": ({"run_id", "wait_id"}, set()),
    "status": ({"run_id"}, set()),
    "cancel": ({"run_id"}, set()),
}


def validate_request(request):
    if not isinstance(request, dict) or request.get("action") not in FIELDS:
        raise ValueError("learning_workflow requires a supported action")
    required, optional = FIELDS[request["action"]]
    if not required <= set(request) or set(request) - required - optional - {"action"}:
        raise ValueError("learning_workflow fields do not match action")
    for key in required - {"definition", "inputs", "observations", "outputs", "parameter_bindings", "annotations", "scope", "model_call"}:
        if not isinstance(request[key], str) or not request[key].strip():
            raise ValueError(key + " must be non-empty text")
    for key in {"definition", "inputs", "observations", "outputs", "vision_capabilities",
                "parameter_bindings", "annotations", "scope", "model_call"} & set(request):
        if not isinstance(request[key], dict):
            raise ValueError(key + " must be an object")
    if "vision_capabilities" in request:
        from app.vision.recognition_source import ClientVisionCapabilities
        ClientVisionCapabilities.model_validate(request["vision_capabilities"])
    if "resolution" in request:
        from .workflow_recovery_resolution import validate_resolution
        validate_resolution(request["resolution"])
    if "execution_strategy" in request:
        from .workflow_execution_strategy import validate_execution_strategy
        validate_execution_strategy(request["execution_strategy"])
    if "resume_request_id" in request and (not isinstance(request["resume_request_id"], str)
            or not request["resume_request_id"].strip()):
        raise ValueError("resume_request_id must be non-empty text")
    if "user_instruction" in request and len(request["user_instruction"]) > 4000:
        raise ValueError("user_instruction must contain at most 4000 characters")
    if "target_recipes" in request and (not isinstance(request["target_recipes"], list)
            or len(request["target_recipes"]) > 256 or any(not isinstance(item, dict) for item in request["target_recipes"])):
        raise ValueError("target_recipes must contain at most 256 recipe objects")
    if request["action"] in {"run", "takeover_commit"} and request["mode"] not in {"single", "until_wait"}:
        raise ValueError("workflow_runner_mode_invalid")
    return request


def workflow_control(library, session_dir, request, request_id):
    from .workflow_program import WorkflowProgramService
    from .workflow_trial import TrialService
    value = validate_request(request)
    action = value["action"]
    if action == "record_model_call":
        from .caller_model_calls import record_model_call
        return record_model_call(library, session_dir, scope=value["scope"], model_call=value["model_call"])
    if action.startswith("synthesis_"):
        from .learning_synthesis import LearningSynthesisService
        synthesis = LearningSynthesisService(library, session_dir)
        if action == "synthesis_prepare":
            return synthesis.prepare(value["learning_session_id"])
        if action == "synthesis_status":
            return synthesis.status(value["synthesis_id"])
        if action == "synthesis_resume":
            return synthesis.resume(value["synthesis_id"], value["source_sha256"],
                value["after_reply_request_id"], value["user_instruction"], request_id)
        return synthesis.complete(value["synthesis_id"], value["source_sha256"],
                                  value["parameter_bindings"], value["annotations"], request_id,
                                  resume_request_id=value.get("resume_request_id"))
    if action == "verify":
        raise ValueError("workflow_verification_requires_live_host")
    if action in {"run", "continue", "takeover_preview", "takeover_commit"}:
        raise ValueError("workflow_execution_requires_live_host")
    if action == "read":
        return WorkflowProgramService(library).load(value["workflow_id"], value.get("program_id"))
    if action == "compile":
        from .workflow_compiler import compile_workflow_draft
        return compile_workflow_draft(library, learning_session_id=value["learning_session_id"],
                                      parameter_bindings=value.get("parameter_bindings", {}),
                                      annotations=value.get("annotations", {}))
    if action == "save":
        return WorkflowProgramService(library).save(value["workflow_id"], value["expected_sha256"],
                                                   value["definition"], request_id,
                                                   target_recipes=value.get("target_recipes"))
    service = TrialService(library, session_dir)
    if action == "start":
        return service.start(value["workflow_id"], value["program_id"], value["start_step_id"], value["inputs"], request_id,
                             execution_strategy=value.get("execution_strategy", "learned"))
    if action == "prepare":
        return service.prepare(value["run_id"], request_id, value.get("observations"),
                               vision_capabilities=value.get("vision_capabilities"))
    if action == "review":
        return service.review(value["run_id"], request_id, value["execution_request_id"],
                              value["verdict"], value["observations"], value["outputs"])
    if action == "cancel":
        return service.cancel(value["run_id"], request_id)
    return service.status(value["run_id"])
