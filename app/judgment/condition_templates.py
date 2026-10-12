"""记录号条件的版本化纯合同；不读取画面、连接服务或授予动作权限。"""
from collections.abc import Mapping
from hashlib import sha256
import json
import re


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PLACEHOLDER = "{record_id}"
_TEMPLATE_FIELDS = {
    "schema", "kind", "condition_template_id", "revision", "template_sha256",
    "text_template", "parameters", "allowed_states", "review_policy",
}
_BINDING_FIELDS = {"schema", "template", "typed_parameters"}
_SNAPSHOT_FIELDS = {
    "schema", "condition_template_id", "revision", "template_sha256", "binding",
    "typed_parameters", "condition", "allowed_states", "review_policy",
    "binding_sha256", "source_sha256", "snapshot_sha256",
}


def _fields(value, expected, label):
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"condition_{label}_fields_invalid")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value):
    return sha256(_canonical(value)).hexdigest()


def _copy(value, label):
    encoded = _canonical(value)
    if len(encoded) > 64 * 1024:
        raise ValueError(f"condition_{label}_too_large")
    return json.loads(encoded)


def validate_condition_template(snapshot):
    """验证完整语义摘要并返回独立 JSON 快照，不判断模板是否获准采用。"""
    _fields(snapshot, _TEMPLATE_FIELDS, "template")
    if (snapshot["schema"] != "condition_template.v1"
            or snapshot["kind"] != "record_id_equals_input"):
        raise ValueError("condition_template_schema_invalid")
    template_id, revision = snapshot["condition_template_id"], snapshot["revision"]
    if (type(template_id) is not str or not _ID.fullmatch(template_id)
            or type(revision) is not int or revision < 1):
        raise ValueError("condition_template_identity_invalid")
    text = snapshot["text_template"]
    if (type(text) is not str or not 1 <= len(text) <= 4000
            or text.count(_PLACEHOLDER) != 1
            or any(character in text.replace(_PLACEHOLDER, "") for character in "{}")):
        raise ValueError("condition_template_text_invalid")
    parameters = snapshot["parameters"]
    _fields(parameters, {"record_id"}, "template_parameters")
    parameter = parameters["record_id"]
    _fields(parameter, {"type", "min_length", "max_length"}, "template_parameter")
    minimum, maximum = parameter["min_length"], parameter["max_length"]
    if (parameter["type"] != "string" or type(minimum) is not int or type(maximum) is not int
            or not 1 <= minimum <= maximum <= 4000):
        raise ValueError("condition_template_parameter_invalid")
    states = snapshot["allowed_states"]
    if (type(states) is not list or len(states) > 32
            or any(type(state) is not str or not state.strip() or len(state) > 1000 for state in states)
            or len(set(states)) != len(states)):
        raise ValueError("condition_template_states_invalid")
    if snapshot["review_policy"] not in ("adaptive", "always_main"):
        raise ValueError("condition_template_policy_invalid")
    digest = snapshot["template_sha256"]
    if (type(digest) is not str or not _SHA256.fullmatch(digest)
            or digest != _digest({key: value for key, value in snapshot.items() if key != "template_sha256"})):
        raise ValueError("condition_template_digest_invalid")
    return _copy(snapshot, "template")


def _parameter_value(value, template):
    parameter = template["parameters"]["record_id"]
    if (type(value) is not str
            or not parameter["min_length"] <= len(value) <= parameter["max_length"]):
        raise ValueError("condition_parameter_value_invalid")
    return value


def validate_condition_binding(binding, *, input_types=None):
    """保留输入引用；声明类型为 string/number/boolean，记录号只接受 string。"""
    _fields(binding, _BINDING_FIELDS, "binding")
    if binding["schema"] != "condition_binding.v1":
        raise ValueError("condition_binding_schema_invalid")
    template = validate_condition_template(binding["template"])
    parameters = binding["typed_parameters"]
    _fields(parameters, {"record_id"}, "binding_parameters")
    reference = parameters["record_id"]
    if type(reference) is not dict:
        raise ValueError("condition_binding_reference_invalid")
    declarations = {} if input_types is None else input_types
    if not isinstance(declarations, Mapping):
        raise ValueError("condition_binding_input_types_invalid")
    source = reference.get("source")
    if source == "literal":
        _fields(reference, {"source", "value"}, "binding_reference")
        _parameter_value(reference["value"], template)
    elif source == "input":
        _fields(reference, {"source", "name"}, "binding_reference")
        name = reference["name"]
        if type(name) is not str or not _ID.fullmatch(name):
            raise ValueError("condition_binding_input_name_invalid")
        if name not in declarations:
            raise ValueError("condition_binding_input_unknown")
        if declarations[name] != "string":
            raise ValueError("condition_binding_input_type_invalid")
    else:
        raise ValueError("condition_binding_source_invalid")
    return _copy({"schema": binding["schema"], "template": template,
                  "typed_parameters": parameters}, "binding")


def _input_reference(binding):
    if type(binding) is not dict or type(binding.get("typed_parameters")) is not dict:
        return None
    reference = binding["typed_parameters"].get("record_id")
    if (type(reference) is dict and reference.get("source") == "input"
            and type(reference.get("name")) is str):
        return reference["name"]
    return None


def resolve_condition_binding(binding, inputs):
    """只解析本次实际引用的输入，返回带完整重建材料的具体内容快照。"""
    if not isinstance(inputs, Mapping):
        raise ValueError("condition_binding_inputs_invalid")
    name = _input_reference(binding)
    declarations = {name: "string"} if name is not None and name in inputs else {}
    checked = validate_condition_binding(binding, input_types=declarations)
    template = checked["template"]
    reference = checked["typed_parameters"]["record_id"]
    value = reference["value"] if reference["source"] == "literal" else inputs[reference["name"]]
    value = _parameter_value(value, template)
    # 参数只作为 JSON 字符串数据插入，绝不解析参数内的占位符或表达式。
    condition = template["text_template"].replace(_PLACEHOLDER, json.dumps(value, ensure_ascii=False))
    if len(condition) > 4000:
        raise ValueError("condition_snapshot_text_invalid")
    source = {"schema": "condition_parameter_source.v1",
              "typed_parameters": {"record_id": {**reference, "value": value}}}
    snapshot = {
        "schema": "condition_snapshot.v1",
        **{key: template[key] for key in ("condition_template_id", "revision", "template_sha256")},
        "binding": checked,
        "typed_parameters": {"record_id": value},
        "condition": condition,
        "allowed_states": template["allowed_states"],
        "review_policy": template["review_policy"],
        "binding_sha256": _digest(checked),
        "source_sha256": _digest(source),
    }
    snapshot["snapshot_sha256"] = _digest(snapshot)
    return _copy(snapshot, "snapshot")


def validate_condition_snapshot(snapshot):
    """重建全部字段；可信 run 输入和 profile 批准仍须由采用端另行核对。"""
    _fields(snapshot, _SNAPSHOT_FIELDS, "snapshot")
    if snapshot["schema"] != "condition_snapshot.v1":
        raise ValueError("condition_snapshot_schema_invalid")
    parameters = snapshot["typed_parameters"]
    _fields(parameters, {"record_id"}, "snapshot_parameters")
    if type(parameters["record_id"]) is not str:
        raise ValueError("condition_snapshot_parameters_invalid")
    name = _input_reference(snapshot["binding"])
    inputs = {name: parameters["record_id"]} if name is not None else {}
    try:
        expected = resolve_condition_binding(snapshot["binding"], inputs)
        if _canonical(snapshot) != _canonical(expected):
            raise ValueError("condition_snapshot_reconstruction_invalid")
    except (ValueError, TypeError):
        raise ValueError("condition_snapshot_reconstruction_invalid") from None
    return expected


def make_record_id_template(*, condition_template_id="detail_record_id_equals_input", revision=1,
                            text_template="The detail page record ID equals {record_id}.",
                            min_length=1, max_length=160, allowed_states=(), review_policy="adaptive"):
    """构造唯一支持的记录号模板；返回值本身不代表 profile 已批准。"""
    if type(allowed_states) not in (list, tuple):
        raise ValueError("condition_template_states_invalid")
    snapshot = {
        "schema": "condition_template.v1", "kind": "record_id_equals_input",
        "condition_template_id": condition_template_id, "revision": revision,
        "text_template": text_template,
        "parameters": {"record_id": {"type": "string", "min_length": min_length, "max_length": max_length}},
        "allowed_states": list(allowed_states), "review_policy": review_policy,
    }
    snapshot["template_sha256"] = _digest(snapshot)
    return validate_condition_template(snapshot)


__all__ = ["make_record_id_template", "validate_condition_template", "validate_condition_binding",
           "resolve_condition_binding", "validate_condition_snapshot"]
