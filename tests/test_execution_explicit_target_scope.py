"""明确目标标签不能被动作描述或页面上下文中的同词控件替代。"""

import pytest

from app.operation.recognition.text_match import explicit_target_label
from app.operation.recognition.candidate_ranker import _goal_label_match, _explicit_goal_action_terms
from app.operation.recognition.control_target import uia_action_identity_matches
from tests.test_native_vista_candidate_contract import _recognize


GOAL = "Click the search result link titled Amazon Web Services (AWS) whose site is aws.amazon.com"


@pytest.mark.parametrize("goal,label", [
    (GOAL, "Amazon Web Services (AWS)"),
    ('Click the search result link titled "Atlas Search (Docs)" on the results page', "Atlas Search (Docs)"),
    ("Click the result titled Travel Guide (2026) whose site is example.test", "Travel Guide (2026)"),
    ("Click the tab labelled 游戏 (Games tab) in the app's left tab bar", "游戏"),
    ('Click the button named "Search in files" on the toolbar', "Search in files"),
    ("Click the button labeled Apply or Open", None),
    ('Click the link titled "War or Peace"', "War or Peace"),
])
def test_extracts_explicit_identity_without_losing_title_parentheses(goal, label):
    assert explicit_target_label(goal) == label


@pytest.mark.parametrize("label,expected", [("Search", False), ("Amazon", False),
    ("aws.amazon.com", False), ("Amazon Web Services (AWS)", True),
    ("Cloud Computing Services - Amazon Web Services (AWS) https://aws.amazon.com", True)])
def test_shared_label_match_does_not_promote_context_words(label, expected):
    assert _goal_label_match(GOAL, [label], negated=False) is expected
    assert uia_action_identity_matches({"control_type": "Hyperlink", "name": label,
        "patterns": ["Invoke"]}, goal=GOAL) is expected


def test_search_context_is_not_search_action():
    assert _explicit_goal_action_terms(GOAL) == set()
    assert _explicit_goal_action_terms('Click the button labelled "Search"') == {"search"}


def test_negated_target_does_not_become_positive_identity():
    goal = 'Do not click the button labelled "Search"'
    assert not _goal_label_match(goal, ["Search"], negated=False)
    assert _goal_label_match(goal, ["Search"], negated=True)


def test_recognition_pipeline_does_not_invent_toolbar_identity_conflict(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, point={"x": 100, "y": 40},
                        label="Search", goal=GOAL)
    assert result["candidate_result"]["summary"]["vista_direct_uia_conflict_candidate_ids"] == []
    direct = next(c for c in result["candidate_result"]["candidates"]
                  if c["candidate_id"].startswith("vista_direct_"))
    assert direct["label"] == "Amazon Web Services (AWS)"
    assert "vista_direct_current_uia_identity_ambiguous" not in direct["reasons"]
    # 修正匹配不代表模型点已获独立验证；无 OCR 佐证仍不能执行。
    assert result["pre_click_decision"]["allowed"] is False


def test_real_explicit_target_geometry_conflict_is_still_rejected(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, point={"x": 100, "y": 40},
                        label="Travel Guide (2026)",
                        goal="Click the search result titled Travel Guide (2026) whose site is example.test")
    assert result["candidate_result"]["candidates"] == []
    assert result["pre_click_decision"]["allowed"] is False


def test_two_real_overlapping_title_targets_remain_ambiguous(tmp_path):
    from app.api import vision
    from tests.test_uia_action_identity_context import _rig

    fast, arguments = _rig(tmp_path, label="Travel Guide (2026)", overlapping=True)
    arguments["goal"] = "Click the search result titled Travel Guide (2026) whose site is example.test"
    candidate, reason = vision._vista_direct_current_uia_identity(fast_inventory=fast, **arguments)
    assert candidate is None
    assert reason == "vista_direct_current_uia_identity_ambiguous"


def test_compound_accessible_names_require_unique_current_point(tmp_path):
    from app.api import vision
    from tests.test_uia_action_identity_context import _rig

    fast, arguments = _rig(tmp_path, label="Travel Guide (2026) https://example.test", kind="Hyperlink")
    arguments["goal"] = "Click the search result titled Travel Guide (2026) whose site is example.test"
    candidate, reason = vision._vista_direct_current_uia_identity(fast_inventory=fast, **arguments)
    assert reason is None
    identity = candidate.element.evidence["current_uia_point_disambiguation"]
    assert identity["selected_control_id"] == "selected"
    assert identity["matching_control_count"] == 2
    assert identity["excluded_control_ids"] == ["distant-namesake"]
