"""显式合成的路径图契约样例，不是恢复的历史记录或操作授权。"""
def _graph(name, app_id, states, actions, transitions):
    return {
        "contract_version": "runtime_path_graph_v1",
        "graph_id": "synthetic_test_" + name,
        "app_id": app_id,
        "fixture_provenance": "synthetic_unit_test_only",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "coordinate_policy": {"coordinate_space": "window_screenshot"},
        "states": [{"state_id": state} for state in states],
        "action_templates": actions,
        "transitions": [
            {"from_state_id": before, "to_state_id": after, "action_template_id": action}
            for before, after, action in transitions
        ],
    }


def _read(action_id, container, skill):
    return {"action_template_id": action_id, "action_type": "read", "learned_skill_ref": skill,
            "scroll_target": {"target_container_id": container, "target_pane": "page"}}


def _click(action_id, skill, **extra):
    return {"action_template_id": action_id, "action_type": "click", "learned_skill_ref": skill, **extra}


def _seed(candidate_id, role, bbox, point):
    return {"contract_version": "seeded_candidate_v1", "candidate_id": candidate_id,
            "role": role, "bbox": bbox, "click_point": point,
            "fixture_provenance": "synthetic_unit_test_only", "artifact_is_authorization": False}


def runtime_graph_fixture(name):
    if name == "github_issues":
        return _graph(name, "github", ["github_issue_detail"], [
            _read("read_issue_detail", "github:page", "skill.read_detail_page_until_bounded")
        ], [("github_issue_detail", "github_issue_detail", "read_issue_detail")])
    if name == "python_docs_search":
        return _graph(name, "python_docs", ["docs:search_page", "docs:search_results", "docs:article_page"], [
            {"action_template_id": "type_public_search_query", "action_type": "input",
             "learned_skill_ref": "skill.input_text_into_field",
             "input_target": {"role": "searchbox", "click_point": {"x": 404, "y": 283}},
             "input_policy": {"requires_agent_text": True, "clear_existing": True,
                              "submit_allowed": True, "input_category": "public_search_query"}},
            _click("trigger_search", "skill.trigger_search", seeded_candidate=_seed(
                "docs_search_button_seed", "button", {"x": 497, "y": 272, "w": 57, "h": 22}, {"x": 525, "y": 283})),
            _click("open_search_result", "skill.open_result_from_search_list", seeded_candidate=_seed(
                "docs_first_search_result_seed", "link", {"x": 356, "y": 602, "w": 78, "h": 24}, {"x": 392, "y": 614})),
            _read("read_article", "docs:page", "skill.read_detail_page_until_bounded"),
        ], [("docs:search_page", "docs:search_page", "type_public_search_query"),
            ("docs:search_page", "docs:search_results", "trigger_search"),
            ("docs:search_results", "docs:article_page", "open_search_result"),
            ("docs:article_page", "docs:article_page", "read_article")])
    if name == "table_directory":
        return _graph(name, "table_directory", ["table:list_page", "table:list_filtered", "table:record_detail"], [
            _click("switch_filter_tab", "skill:switch_filter_tab"),
            _click("open_record_from_table", "skill:open_record_from_table"),
            _click("sort_records", "skill:sort_records"),
            _click("blocked_write_action", "skill:write_record", availability_policy={"default_available": False}),
            {"action_template_id": "load_more_records", "action_type": "scroll",
             "scroll_target": {"target_container_id": "table:records_list", "target_pane": "records_list"}},
            _read("read_record_detail", "table:page", "skill:read_record_detail"),
        ], [("table:list_page", "table:list_filtered", "switch_filter_tab"),
            ("table:list_page", "table:record_detail", "open_record_from_table"),
            ("table:list_page", "table:list_page", "load_more_records"),
            ("table:list_page", "table:list_page", "blocked_write_action"),
            ("table:list_filtered", "table:list_filtered", "sort_records"),
            ("table:record_detail", "table:record_detail", "read_record_detail")])
    raise ValueError("Unknown synthetic runtime graph fixture: " + name)
