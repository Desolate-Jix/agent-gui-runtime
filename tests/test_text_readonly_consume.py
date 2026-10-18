"""缺少本地字段期望的旧只读预览不得进入消费或输入。"""
from dataclasses import replace
from app.agent.text_parameters import resolve_text_parameters
from test_text_local_publication import local


def test_approved_text_preview_without_local_field_expectation_cannot_consume(local, monkeypatch):
    reviewed = local.service.get_local_reviewed_text_parameters(action_id=local.request.action_id)
    resolved = resolve_text_parameters(reviewed, {"query": "本次审核值"})
    claim = local.service.request_grounded_confirmation(local.request, text_input=resolved)
    cid = claim.grounded_confirmation.confirmation_id
    approved = local.service.decide_grounded_confirmation(confirmation_id=cid, decision="approved")
    assert approved.phase == "grounded_confirmation_approved"
    controller = local.controllers[-1]
    context = controller._grounded_publications[local.request.session_id]
    controller._grounded_publications[local.request.session_id] = replace(context, text_field_expectation=None)
    captures = []
    original = controller._capture_current_resolution

    def capture(**kwargs):
        captures.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(controller, "_capture_current_resolution", capture)
    result = local.service.consume_grounded_confirmation(confirmation_id=cid)
    assert result.status == "REJECTED"
    assert result.reason_code == "text_execution_not_ready"
    assert captures == []
    assert local.backend.attempt_count == 0
    stored = local.claims.get_for_grounded_confirmation(confirmation_id=cid)
    assert stored.phase == "grounded_confirmation_approved"
    assert stored.grounded_consume is None
    assert local.service.get_local_grounded_text_input(confirmation_id=cid) == resolved
