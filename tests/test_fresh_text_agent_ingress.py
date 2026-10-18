"""首次填写入口的参数冻结与透传回归；不代表真实 MCP 或系统输入验收。"""

import json
from threading import RLock
from types import SimpleNamespace

import pytest

from app.agent.text_execution import text_execution_reference
from app.agent.text_parameters import ResolvedTextParameters, text_parameter_reference
from app.agent_link.contracts import AgentLinkError
from app.desktop_review.fresh_learning_runtime import FreshLearningRuntimeMixin, _resolve_fresh_text_input
from app.desktop_review.fresh_runtime_callsite import FreshLearningRuntimeCallsite
from tests.test_fresh_text_preview import _parameters


@pytest.mark.parametrize("kind", ["literal", "variable"])
def test_fresh_ingress_resolves_exact_source(kind):
    parameters = _parameters(kind)
    values = {parameters.reviewed.content.value: parameters.text} if kind == "variable" else None
    resolved = _resolve_fresh_text_input("fill_field", parameters.reviewed.to_payload(), values)
    assert resolved == parameters
    assert type(resolved) is ResolvedTextParameters


@pytest.mark.parametrize("case", ["missing", "variable_missing", "extra", "wrong_type", "literal_values", "submit", "geometry"])
def test_fresh_ingress_rejects_invalid_text_before_preparation(case):
    parameters = _parameters("variable" if case in {"variable_missing", "extra", "wrong_type"} else "literal")
    declaration = parameters.reviewed.to_payload()
    values = None
    if case == "missing":
        declaration = None
    elif case == "extra":
        values = {parameters.reviewed.content.value: parameters.text, "unexpected": "private-value"}
    elif case == "wrong_type":
        values = {parameters.reviewed.content.value: 123}
    elif case == "literal_values":
        values = {"unexpected": "private-value"}
    elif case == "submit":
        declaration["submit"] = True
    elif case == "geometry":
        declaration["bbox"] = [0, 0, 10, 10]
    with pytest.raises(AgentLinkError) as caught:
        _resolve_fresh_text_input("fill_field", declaration, values)
    assert caught.value.code == "invalid_arguments"
    assert "private-value" not in str(caught.value)


def test_navigation_keeps_its_original_contract():
    assert _resolve_fresh_text_input("open_detail", None, None) is None
    for declaration, values in [(None, {}), (_parameters().reviewed.to_payload(), None)]:
        with pytest.raises(AgentLinkError):
            _resolve_fresh_text_input("open_detail", declaration, values)


class _Ingress(FreshLearningRuntimeMixin):
    def __init__(self):
        self._guard = RLock()
        self.owner = SimpleNamespace(get=lambda **_: {"status": "active"})
        self.calls = []
        self._coordinator = SimpleNamespace(request_fresh_review=self._review)
        self.record = {
            "preparation_id": "preparation.text", "session_id": "session.text",
            "phase": "observed", "cleanup_verified": False, "cancel_requested": False,
            "binding": SimpleNamespace(segment_id="segment.text"),
            "observation": {"observation_id": "observation.text"},
            "selection": SimpleNamespace(source=SimpleNamespace(reference=lambda: {"source_sha256": "a" * 64})),
        }

    def _review(self, **arguments):
        self.calls.append(arguments)
        return {"confirmation_id": "confirmation.text"}

    def _fresh_owned(self, *args):
        return self.record

    def _refresh(self, record):
        pass

    def _view(self, record):
        return self._fresh_view(record)

    def get_fresh(self, **scope):
        return self._view(self.record)


def test_variable_retry_binds_resolved_value_without_storing_raw_text():
    ingress = _Ingress()
    parameters = _parameters("variable")
    arguments = dict(connection_id="connection.text", task_id="task.text", segment_id="segment.text",
        preparation_id="preparation.text", intent_id="intent.text", action_id="action.fill",
        semantic_action="fill_field", goal="Fill the current note",
        text_parameters=parameters.reviewed.to_payload(),
        text_values={parameters.reviewed.content.value: parameters.text})
    view = ingress.request_fresh(**arguments)
    assert view["phase"] == "pending_review"
    assert ingress.calls[0]["text_input"] == parameters
    assert ingress.record["intent"]["text_parameters_ref"] == text_parameter_reference(parameters.reviewed)
    assert ingress.record["text_execution_ref"] == text_execution_reference(parameters)
    assert "text_parameters" not in ingress.record and "text_values" not in ingress.record
    assert parameters.text not in json.dumps(view, ensure_ascii=False)
    assert parameters.text not in repr(ingress.record)
    assert ingress.request_fresh(**arguments) == view
    assert len(ingress.calls) == 1
    arguments["text_values"] = {parameters.reviewed.content.value: "different resolved value"}
    with pytest.raises(AgentLinkError) as conflict:
        ingress.request_fresh(**arguments)
    assert conflict.value.code == "idempotency_conflict"
    assert len(ingress.calls) == 1


def test_callsite_forwards_private_text_and_local_field_getters():
    calls = []
    parameters = _parameters()
    expectation = object()
    callsite = object.__new__(FreshLearningRuntimeCallsite)
    callsite._validate = lambda: None
    callsite._selection = SimpleNamespace(target_process_id=9001)
    callsite._controller = SimpleNamespace(
        request_grounded_confirmation=lambda request, **kwargs: calls.append((request, kwargs)),
        get_local_grounded_text_input=lambda **_: parameters,
        get_local_grounded_text_field_expectation=lambda **_: expectation,
    )
    request = {"intent_id": "intent.text"}
    callsite.request_grounded_confirmation(request, text_input=parameters)
    assert calls == [(request, {"target_process_id": 9001, "text_input": parameters})]
    assert callsite.get_local_grounded_text_input(confirmation_id="confirmation.text") is parameters
    assert callsite.get_local_grounded_text_field_expectation(confirmation_id="confirmation.text") is expectation
