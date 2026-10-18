"""原生拥有者收集并冻结本次值；Runtime/窗口是明确的内存边界。"""
from types import SimpleNamespace
from threading import get_ident

import pytest

from app.agent.text_parameters import text_parameter_reference
from app.agent.text_execution import text_execution_reference
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError
from test_native_text_input_dialog import parameters
from test_native_single_step_coordinator import _Runtime, _Windows, _Host, _coordinator, _Preview


class TextRuntime(_Runtime):
    def __init__(self, reviewed):
        super().__init__()
        self.reviewed = reviewed
        self.text_input = None
        self.observation.available_actions = (SimpleNamespace(
            action_id="action-1", semantic_action="fill_field", target_state_id="state-2",
            text_parameters_ref=text_parameter_reference(reviewed),
        ),)

    def get_local_reviewed_text_parameters(self, *, action_id):
        assert action_id == "action-1"
        self.calls.append(("text-parameters", get_ident()))
        return self.reviewed

    def request_grounded_confirmation(self, request, *, text_input):
        self.text_input = text_input
        return super().request_grounded_confirmation(request)

    def get_local_grounded_text_input(self, *, confirmation_id):
        self.calls.append(("text-preview", get_ident()))
        return self.text_input

    def _claim(self):
        claim = super()._claim()
        data = _Preview(self).to_dict()
        data["review_selection"].update(text_parameters_ref=text_parameter_reference(self.reviewed))
        data["grounding_preview"] = {"semantic_action": "fill_field"}
        data["text_execution_ref"] = text_execution_reference(self.text_input)
        claim.grounded_confirmation.preview = SimpleNamespace(to_dict=lambda: data)
        return claim


def prepared(reviewed):
    runtime, windows, host = TextRuntime(reviewed), _Windows(), _Host()
    coordinator = _coordinator(runtime, windows, host, lambda: None, lambda: None)
    observed = coordinator.prepare(asset_id="asset-1", asset_content_sha256="c" * 64,
                                   target_window_handle=41, target_process_id=7)
    return coordinator, runtime, observed


@pytest.mark.parametrize("kind,value,variables,want", [
    ("literal", "固定\r\n文本", {}, "固定\r\n文本"),
    ("variable", "query", {"query": "本次变量"}, "本次变量"),
])
def test_coordinator_resolves_before_publication_on_owner_and_keeps_intent_identity_only(kind, value, variables, want):
    coordinator, runtime, observed = prepared(parameters(kind, value))
    try:
        assert observed["actions"][0]["semantic_action"] == "fill_field"
        reviewed = coordinator.text_input_requirements(action_id="action-1")
        assert reviewed == runtime.reviewed
        assert runtime.text_input is None
        view = coordinator.request_review(action_id="action-1", text_values=variables)
        variables["query"] = "later mutation"
        assert runtime.text_input.text == want
        assert view["text_input_local"].text == want
        assert set(runtime.request.model_dump()) == {"intent_id", "session_id", "observation_id", "action_id"}
        assert len({thread for _, thread in runtime.calls}) == 1
        coordinator.approve(confirmation_id=view["confirmation_id"],
                            preview_content_sha256=view["preview"]["content_sha256"])
        with pytest.raises(NativeSingleStepCoordinatorError) as blocked:
            coordinator.execute(confirmation_id=view["confirmation_id"])
        assert blocked.value.code == "text_execution_not_ready"
    finally:
        coordinator.cancel()
        coordinator.shutdown()


def test_missing_variable_or_fixed_override_stops_before_runtime_publication():
    for reviewed, variables in ((parameters(), {}), (parameters("literal", "fixed"), {"query": "override"})):
        coordinator, runtime, _ = prepared(reviewed)
        try:
            with pytest.raises(NativeSingleStepCoordinatorError) as failure:
                coordinator.request_review(action_id="action-1", text_values=variables)
            assert failure.value.code == "text_input_invalid"
            assert runtime.text_input is None
            assert not any(name == "request" for name, _ in runtime.calls)
        finally:
            coordinator.cancel()
            coordinator.shutdown()
