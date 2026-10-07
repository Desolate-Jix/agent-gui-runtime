"""恢复核验须保留原审阅提交，不能从分支后的输出反推。"""
from hashlib import sha256

import pytest

from app.desktop_review.external_mapping import canonical_json_bytes
from tests.test_workflow_trial import services, response, WORKFLOW


@pytest.mark.parametrize("observed", [False, None, True])
def test_review_preserves_actual_submitted_outputs_before_condition_changes_verdict(services, observed):
    _, trials, program, session = services
    run = trials.start(WORKFLOW, program["program_id"], "search", {"query": "A"}, "start")
    ticket = trials.prepare(run["run_id"], "prepare")
    response(session, ticket)
    observations = {} if observed is None else {"results_visible": observed}
    submitted = {"result_title": "\u5b66\u4e60\u539f\u63d0\u4ea4"}
    state = trials.review(run["run_id"], "review-original", ticket["execution_request_id"],
                          "success", observations, submitted)
    entry = state["history"][0]
    assert entry["review_request"] == {"request_id": "review-original", "submitted_outputs": submitted}
    assert entry["outputs"] == (submitted if observed is True else {})
    assert state["requests"]["review-original"] == sha256(canonical_json_bytes(
        [ticket["execution_request_id"], "success", observations, submitted])).hexdigest()
    assert trials.review(run["run_id"], "review-original", ticket["execution_request_id"],
                         "success", observations, submitted) == state
