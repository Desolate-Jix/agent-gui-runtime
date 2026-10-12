def _receipt_action(receipt, operation):
    from .local_step_no_dispatch import pre_capture_failure_verified
    if pre_capture_failure_verified(receipt, operation):
        return False
    data = (receipt.get("response") or {}).get("data") or {}
    data = data.get("result", data)
    value = (data.get("pressed") if operation == "press_key" else
        (data.get("execution_path") or {}).get("action_executed", data.get("action_executed")))
    return value if type(value) is bool else None
