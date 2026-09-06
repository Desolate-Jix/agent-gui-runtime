from app.api import panel


def test_selection_replay_mode_cannot_start_a_production_stage(monkeypatch):
    def unexpected_start(**kwargs):
        raise AssertionError("replay-only mode must not create a production stage lease")

    monkeypatch.setattr(panel, "start_learning_workflow_stage_operation", unexpected_start)
    request = panel.PanelStartLearningWorkflowStageOperationRequest(
        run_id="run/selection-boundary",
        expected_revision=0,
        stage="screen_understanding",
        learning_pipeline_mode="hybrid_v1_2",
    )
    result = panel.start_learning_workflow_stage_operation_endpoint(request)
    assert result.success is False
    assert result.error.code == "hybrid_selection_replay_only"
    assert result.data is None
