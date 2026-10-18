def _receipt_action(receipt, operation):
    data = (receipt.get("response") or {}).get("data") or {}
    data = data.get("result", data)
    value = (data.get("pressed") if operation == "press_key" else
        (data.get("execution_path") or {}).get("action_executed", data.get("action_executed")))
    return value if type(value) is bool else None
