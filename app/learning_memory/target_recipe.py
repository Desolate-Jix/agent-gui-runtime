"""不可变目标规则及其宿主拥有的引用。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.workspace import _write_immutable


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RECIPE = re.compile(r"target-recipe-[0-9a-f]{64}\Z")
_TEMPLATE = re.compile(r"template-[0-9a-f]{64}\Z")
_INTERFACE = re.compile(r"interface-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_VERSION = re.compile(r"interface-version-[0-9a-f]{64}\Z")
_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")


def _matches(value, pattern):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def validate_target_reference(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"recipe_id", "interface_key", "state_key"}
            or not _matches(value["recipe_id"], _RECIPE)
            or not _matches(value["interface_key"], _KEY)
            or not _matches(value["state_key"], _KEY)):
        raise ValueError("target_memory_reference_invalid")
    return deepcopy(value)


def _uia(value):
    if (not isinstance(value, dict) or set(value) not in (
            {"kind", "name", "control_type"}, {"kind", "name", "control_type", "automation_id"})
            or value.get("kind") != "uia" or not isinstance(value.get("name"), str)
            or not value["name"].strip() or len(value["name"]) > 2000
            or not isinstance(value.get("control_type"), str) or not value["control_type"].strip()
            or len(value["control_type"]) > 120
            or ("automation_id" in value and (not isinstance(value["automation_id"], str)
                or not value["automation_id"].strip() or len(value["automation_id"]) > 2000))):
        raise ValueError("target_recipe_uia_invalid")


def _locator(value):
    if not isinstance(value, dict):
        raise ValueError("target_recipe_strategy_invalid")
    if value.get("kind") == "template" and set(value) == {"kind", "template_id"} and _matches(value["template_id"], _TEMPLATE):
        return
    if value.get("kind") == "uia":
        _uia(value)
        return
    raise ValueError("target_recipe_strategy_invalid")


def _strategy(value):
    if isinstance(value, dict) and value.get("kind") == "visible_row":
        from .uia_rows import validate_visible_row_strategy
        validate_visible_row_strategy(value)
        return
    _locator(value)


def _scope(value):
    required = {"task_id", "interface_key", "state_key"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"application", "anchors"}:
        raise ValueError("target_recipe_scope_invalid")
    for key in required:
        if not _matches(value[key], _KEY):
            raise ValueError("target_recipe_scope_invalid")
    if "application" in value:
        app = value["application"]
        if (not isinstance(app, dict) or set(app) not in ({"executable_name"}, {"executable_name", "window_class"})
                or not isinstance(app.get("executable_name"), str) or not app["executable_name"].strip()
                or len(app["executable_name"]) > 260
                or "/" in app["executable_name"] or "\\" in app["executable_name"]
                or ("window_class" in app and (not isinstance(app["window_class"], str)
                    or not app["window_class"].strip() or len(app["window_class"]) > 260))):
            raise ValueError("target_recipe_application_invalid")
    if "anchors" in value:
        anchors = value["anchors"]
        if not isinstance(anchors, list) or not 1 <= len(anchors) <= 16:
            raise ValueError("target_recipe_anchors_invalid")
        for anchor in anchors:
            _locator(anchor)


def action_semantics_sha256(action: dict, *, scope: dict, strategies: list) -> str:
    from .selection_satisfaction import validate_selection_intent
    _scope(scope)
    if not isinstance(strategies, list) or not 1 <= len(strategies) <= 8:
        raise ValueError("target_recipe_strategies_invalid")
    for strategy in strategies:
        _strategy(strategy)
    if not isinstance(action, dict):
        raise ValueError("target_recipe_action_invalid")
    validate_selection_intent(action, strategies)
    kind = action.get("kind")
    if kind == "click":
        intent = action.get("goal")
        click_kind = action.get("click_kind", "single")
        if click_kind not in {"single", "double", "right"}:
            raise ValueError("target_recipe_action_invalid")
        semantic = {"kind": kind, "target_intent": intent, "click_kind": click_kind,
                    "scope": scope, "strategies": strategies}
    elif kind == "input_sequence":
        intent = action.get("field_goal")
        if type(action.get("submit_search")) is not bool:
            raise ValueError("target_recipe_action_invalid")
        semantic = {"kind": kind, "target_intent": intent, "submit_search": action["submit_search"],
                    "scope": scope, "strategies": strategies}
    else:
        raise ValueError("target_recipe_action_invalid")
    if not isinstance(intent, str) or not intent.strip() or len(intent) > 2000:
        raise ValueError("target_recipe_action_invalid")
    if action.get('selection_intent') is not None:
        semantic['selection_intent'] = action['selection_intent']
    return hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()


def validate_editorial_action(recipe, action):
    from .selection_satisfaction import validate_selection_intent
    if not isinstance(recipe, dict):
        raise ValueError('target_recipe_invalid')
    validate_selection_intent(action, recipe.get('strategies', []))
    if recipe.get("contract_version") != "target_recipe.v3":
        return
    from .target_recipe_proposal import _TARGET_TYPES
    kind = action.get("kind") if isinstance(action, dict) else None
    if kind not in _TARGET_TYPES:
        raise ValueError("target_edit_action_control_type_mismatch")
    allowed = _TARGET_TYPES[kind] | ({"ListItem", "DataItem"} if kind == "click" else set())
    strategies = recipe.get("strategies")
    if not isinstance(strategies, list):
        raise ValueError("target_recipe_strategies_invalid")
    if not 1 <= len(strategies) <= 8 or any(row["kind"] not in {"uia", "visible_row"} for row in strategies):
        raise ValueError("target_edit_single_strategy_required")
    for strategy in strategies:
        target = strategy["action"] if strategy["kind"] == "visible_row" else strategy
        row_name = strategy["kind"] == "visible_row" and target.get("source") == "row_name"
        if row_name and kind != "click":
            raise ValueError("target_edit_action_control_type_mismatch")
        if target["control_type"] not in (allowed | {"Edit"} if row_name else allowed):
            raise ValueError("target_edit_action_control_type_mismatch")


def _validate_recipe(recipe):
    fields = {"contract_version", "recipe_id", "interface_id", "interface_version_id",
              "action_semantics_sha256", "scope", "strategies", "evidence_refs"}
    version = recipe.get("contract_version") if isinstance(recipe, dict) else None
    if (not isinstance(recipe, dict) or set(recipe) != (fields | {"editorial"} if version == "target_recipe.v3" else fields)
            or version not in {"target_recipe.v1", "target_recipe.v2", "target_recipe.v3"}
            or not _matches(recipe.get("recipe_id"), _RECIPE)
            or not _matches(recipe.get("interface_id"), _INTERFACE)
            or not _matches(recipe.get("interface_version_id"), _VERSION)
            or not _matches(recipe.get("action_semantics_sha256"), _SHA)):
        raise ValueError("target_recipe_invalid")
    _scope(recipe["scope"])
    strategies = recipe["strategies"]
    if not isinstance(strategies, list) or not 1 <= len(strategies) <= 8:
        raise ValueError("target_recipe_strategies_invalid")
    for strategy in strategies:
        _strategy(strategy)
    evidence = recipe["evidence_refs"]
    count = 2 if version in {"target_recipe.v2", "target_recipe.v3"} else 1
    if (not isinstance(evidence, list) or len(evidence) != count or not isinstance(evidence[0], dict)
            or set(evidence[0]) != {"kind", "content_sha256", "source_image_sha256"}
            or evidence[0]["kind"] != "interface_content"
            or not _matches(evidence[0]["content_sha256"], _SHA)
            or not _matches(evidence[0]["source_image_sha256"], _SHA)):
        raise ValueError("target_recipe_evidence_invalid")
    if count == 2:
        from .action_evidence import validate_action_evidence_reference
        validate_action_evidence_reference(evidence[1])
    if version == "target_recipe.v3":
        editorial = recipe["editorial"]
        if (not isinstance(editorial, dict) or set(editorial) != {"kind", "validation", "context_recipe"}
                or editorial["kind"] != "human_edit" or editorial["validation"] != "unverified"
                or not isinstance(editorial["context_recipe"], dict)
                or editorial["context_recipe"].get("contract_version") != "target_recipe.v2"):
            raise ValueError("target_recipe_editorial_invalid")
        original = _validate_recipe(editorial["context_recipe"])
        if any(recipe[key] != original[key] for key in
               ("interface_id", "interface_version_id", "evidence_refs", "scope")):
            raise ValueError("target_recipe_editorial_context_changed")
    expected = "target-recipe-" + hashlib.sha256(canonical_json_bytes({k: v for k, v in recipe.items() if k != "recipe_id"})).hexdigest()
    if recipe["recipe_id"] != expected:
        raise ValueError("target_recipe_digest_mismatch")
    return deepcopy(recipe)


def _root(library):
    return library._artifact_root / "desktop-review" / "target-recipes"


def _check_evidence(library, recipe):
    content = library.load_interface_content(recipe["interface_id"], recipe["interface_version_id"])
    scope = recipe["scope"]
    source = content["source"]
    if (content["content_sha256"] != recipe["evidence_refs"][0]["content_sha256"]
            or source.get("kind") != "execution_memory_v1"
            or any(source.get(key) != scope[key] for key in ("task_id", "interface_key", "state_key"))):
        raise ValueError("target_recipe_interface_evidence_mismatch")
    evidence = library.load_interface_content_evidence(recipe["interface_id"], recipe["interface_version_id"])
    raw = library._artifact_file(evidence["image_path"], "目标原图").read_bytes()
    digest = recipe["evidence_refs"][0]["source_image_sha256"]
    if evidence.get("sha256") != digest or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("target_recipe_image_evidence_mismatch")
    if recipe["contract_version"] in {"target_recipe.v2", "target_recipe.v3"}:
        from .action_evidence import load_action_evidence, validate_captured_rule
        action_source = load_action_evidence(library, recipe["evidence_refs"][1])
        expected_pin = {"interface_id": recipe["interface_id"], "version_id": recipe["interface_version_id"],
                        "content_sha256": content["content_sha256"]}
        before = action_source["review"]["before"]
        if (action_source["pin"] != expected_pin
                or any(before.get(key) != scope[key] for key in ("interface_key", "state_key"))
                or action_source["observation"]["frame"]["application"] != scope.get("application")):
            raise ValueError("target_recipe_action_interface_mismatch")
        if recipe["contract_version"] == "target_recipe.v3":
            original = recipe["editorial"]["context_recipe"]
            _check_evidence(library, original)
            from .workflow_target_editor_service import validate_editorial_target
            validate_editorial_target(recipe, action_source["observation"])
        else:
            validate_captured_rule(recipe, action_source)
    from .templates import template_evidence
    for locator in [*recipe["strategies"], *scope.get("anchors", [])]:
        if locator["kind"] == "template":
            template = template_evidence(library, locator["template_id"])
            if (template["interface_id"] != recipe["interface_id"]
                    or template["version_id"] != recipe["interface_version_id"]):
                raise ValueError("target_recipe_template_evidence_mismatch")


def save_target_recipe(library, recipe: dict) -> dict:
    value = _validate_recipe(recipe)
    _check_evidence(library, value)
    _write_immutable(_root(library) / (value["recipe_id"] + ".json"), canonical_json_bytes(value) + b"\n")
    return deepcopy(value)


def load_target_recipe(library, reference: dict) -> dict:
    ref = validate_target_reference(reference)
    try:
        value = json.loads((_root(library) / (ref["recipe_id"] + ".json")).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError("target_recipe_file_invalid") from error
    recipe = _validate_recipe(value)
    if (recipe["scope"]["interface_key"], recipe["scope"]["state_key"]) != (ref["interface_key"], ref["state_key"]):
        raise ValueError("target_recipe_reference_mismatch")
    _check_evidence(library, recipe)
    return recipe


def recipe_from_template(library, template_reference: dict, action: dict) -> dict:
    from .live_template import validate_template_reference
    from .templates import template_evidence
    ref = validate_template_reference(template_reference)
    template = template_evidence(library, ref["template_id"])
    content = library.load_interface_content(template["interface_id"], template["version_id"])
    source = content["source"]
    scope = {key: source[key] for key in ("task_id", "interface_key", "state_key")}
    strategies = [{"kind": "template", "template_id": ref["template_id"]}]
    evidence = [{"kind": "interface_content", "content_sha256": content["content_sha256"],
                 "source_image_sha256": template["source_image_sha256"]}]
    body = {"contract_version": "target_recipe.v1", "interface_id": template["interface_id"],
            "interface_version_id": template["version_id"], "scope": scope,
            "strategies": strategies, "evidence_refs": evidence,
            "action_semantics_sha256": action_semantics_sha256(action, scope=scope, strategies=strategies)}
    recipe = {**body, "recipe_id": "target-recipe-" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()}
    saved = save_target_recipe(library, recipe)
    return {"recipe_id": saved["recipe_id"], "interface_key": scope["interface_key"], "state_key": scope["state_key"]}


__all__ = ["validate_target_reference", "save_target_recipe", "load_target_recipe",
           "action_semantics_sha256", "recipe_from_template"]
