"""本次冻结原文的无原文引用；只作预览绑定，不赋予执行权限。"""
from collections.abc import Mapping
from hashlib import sha256
import re

from .text_parameters import ResolvedTextParameters, text_parameter_reference, validate_text_parameter_reference
from .automatic_safety_policy import FRESH_PREVIEW_VERSIONS


def text_execution_reference(parameters: ResolvedTextParameters) -> dict:
    if type(parameters) is not ResolvedTextParameters:
        raise ValueError("text execution requires immutable resolved parameters")
    return {
        "contract_version": "text_execution_reference_v1",
        "parameters_sha256": text_parameter_reference(parameters.reviewed)["parameters_sha256"],
        "text_sha256": sha256(parameters.text.encode("utf-8")).hexdigest(),
        "text_length": len(parameters.text),
    }


def validate_text_execution_reference(value: object, declaration_reference: object) -> dict:
    declaration = validate_text_parameter_reference(declaration_reference)
    if (not isinstance(value, Mapping)
            or set(value) != {"contract_version", "parameters_sha256", "text_sha256", "text_length"}
            or value.get("contract_version") != "text_execution_reference_v1"
            or value.get("parameters_sha256") != declaration["parameters_sha256"]
            or not isinstance(value.get("text_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["text_sha256"]) is None
            or type(value.get("text_length")) is not int or not 0 <= value["text_length"] <= 32768):
        raise ValueError("text execution reference does not match the reviewed declaration")
    return dict(value)


def validate_local_text_preview(preview: Mapping, parameters: ResolvedTextParameters) -> None:
    if preview.get("contract_version") in FRESH_PREVIEW_VERSIONS:
        from .fresh_learning_action_preview import FreshLearningActionPreview

        current = FreshLearningActionPreview.from_dict(preview).to_dict()
        if (type(parameters) is not ResolvedTextParameters
                or current["intent"]["semantic_action"] != "fill_field"
                or current["intent"].get("text_parameters_ref") != text_parameter_reference(parameters.reviewed)
                or current.get("text_execution_ref") != text_execution_reference(parameters)):
            raise ValueError("local text does not match the frozen fresh preview")
        return
    if (type(parameters) is not ResolvedTextParameters
            or preview.get("grounding_preview", {}).get("semantic_action") != "fill_field"
            or preview.get("review_selection", {}).get("text_parameters_ref") != text_parameter_reference(parameters.reviewed)
            or preview.get("text_execution_ref") != text_execution_reference(parameters)):
        raise ValueError("local text does not match the frozen preview")
