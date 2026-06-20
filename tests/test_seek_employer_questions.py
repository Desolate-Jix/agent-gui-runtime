from __future__ import annotations

from app.seek.employer_questions import (
    build_employer_question_answer_preview,
    build_employer_question_answer_plan,
    build_employer_question_inventory,
    select_employer_question_option,
)


def _item(item_id: str, text: str, role: str, x: int, y: int, w: int = 120, h: int = 24) -> dict:
    return {"collection": "test", "id": item_id, "text": text, "role": role, "bbox": {"x": x, "y": y, "w": w, "h": h}}


def test_employer_question_inventory_groups_duplicate_yes_no_by_question_bbox() -> None:
    state = {
        "contract_version": "seek_application_flow_state_v1",
        "current_step": "answer_employer_questions",
        "application_form_inventory": {
            "contract_version": "application_form_inventory_v1",
            "fields": [
                _item("q1", "Do you have at least 1-2 years of experience in web application development?", "text", 800, 560, 620, 28),
                _item("q1_yes", "Yes", "radio", 800, 600, 60, 40),
                _item("q1_no", "No", "radio", 900, 600, 60, 40),
                _item("q2", "Are you comfortable reading, altering and designing solutions with Java, AngularJS, React, Vue, MySQL?", "text", 800, 700, 760, 28),
                _item("q2_yes", "Yes", "radio", 800, 740, 60, 40),
                _item("q2_no", "No", "radio", 900, 740, 60, 40),
            ],
            "actions": [],
        },
    }

    inventory = build_employer_question_inventory(state)

    assert inventory["contract_version"] == "employer_question_inventory_v1"
    assert inventory["question_count"] == 2
    assert inventory["questions"][0]["question_id"] == "q1"
    assert inventory["questions"][0]["answer_type"] == "radio_yes_no"
    assert [item["id"] for item in inventory["questions"][0]["control_candidates"]] == ["q1_yes", "q1_no"]
    assert [item["id"] for item in inventory["questions"][1]["control_candidates"]] == ["q2_yes", "q2_no"]


def test_duplicate_yes_no_ranking_selects_local_question_option() -> None:
    state = {
        "application_form_inventory": {
            "fields": [
                _item("q1", "Do you have at least 1-2 years of experience in web application development?", "text", 800, 560, 620, 28),
                _item("q1_yes", "Yes", "radio", 800, 600, 60, 40),
                _item("q1_no", "No", "radio", 900, 600, 60, 40),
                _item("q2", "Are you comfortable reading, altering and designing solutions with Java, AngularJS, React, Vue, MySQL?", "text", 800, 700, 760, 28),
                _item("q2_yes", "Yes", "radio", 800, 740, 60, 40),
                _item("q2_no", "No", "radio", 900, 740, 60, 40),
            ]
        }
    }
    question = build_employer_question_inventory(state)["questions"][1]

    selection = select_employer_question_option(question, planned_answer="Yes")

    assert selection["runner_decision"] == "allow"
    assert selection["selected_candidate"]["id"] == "q2_yes"
    assert selection["duplicate_option_guard"]["global_expected_label_count"] == 2
    assert selection["duplicate_option_guard"]["local_expected_label_count"] == 1
    assert selection["duplicate_option_guard"]["ambiguous"] is False


def test_duplicate_yes_no_ranking_rejects_cross_group_candidate() -> None:
    state = {
        "application_form_inventory": {
            "fields": [
                _item("q1", "Do you have at least 1-2 years of experience in web application development?", "text", 800, 560, 620, 28),
                _item("q1_yes", "Yes", "radio", 800, 600, 60, 40),
                _item("q2", "Are you comfortable reading, altering and designing solutions with Java, AngularJS, React, Vue, MySQL?", "text", 800, 700, 760, 28),
            ]
        }
    }
    question = build_employer_question_inventory(state)["questions"][0]
    question["control_candidates"].append(
        {"id": "q2_yes_leaked", "label": "Yes", "role": "radio", "bbox": {"x": 800, "y": 740, "w": 60, "h": 40}}
    )

    selection = select_employer_question_option(question, planned_answer="Yes")

    assert selection["runner_decision"] == "allow"
    assert selection["selected_candidate"]["id"] == "q1_yes"
    assert any(item["candidate"]["id"] == "q2_yes_leaked" for item in selection["rejected_candidates"])
    assert {item["reject_reason"] for item in selection["rejected_candidates"]} == {"candidate_outside_question_group_bbox"}


def test_duplicate_yes_no_ranking_rejects_ambiguous_local_options() -> None:
    question = {
        "question_id": "q1",
        "question_text": "Do you have at least 1-2 years of experience in web application development?",
        "question_bbox": {"x": 800, "y": 560, "w": 620, "h": 28},
        "question_group_bbox": {"x": 800, "y": 560, "w": 300, "h": 120},
        "next_question_boundary_y": 680,
        "global_option_counts": {"yes": 2},
        "control_candidates": [
            {"id": "yes_a", "label": "Yes", "role": "radio", "bbox": {"x": 800, "y": 600, "w": 60, "h": 40}},
            {"id": "yes_b", "label": "Yes", "role": "radio", "bbox": {"x": 880, "y": 600, "w": 60, "h": 40}},
        ],
    }

    selection = select_employer_question_option(question, planned_answer="Yes")

    assert selection["runner_decision"] == "reject"
    assert selection["reject_reason"] == "ambiguous_duplicate_option"
    assert selection["selected_candidate"] is None
    assert selection["duplicate_option_guard"]["ambiguous"] is True


def test_inventory_can_use_screen_reading_uia_controls() -> None:
    state = {
        "contract_version": "seek_application_flow_state_v1",
        "current_step": "answer_employer_questions",
        "application_form_inventory": {
            "contract_version": "application_form_inventory_v1",
            "fields": [
                _item(
                    "ocr_partial_q1",
                    "Do you have at least 1-2 years of experience in web application development?",
                    "text",
                    802,
                    570,
                    626,
                    22,
                )
            ],
        },
    }
    screen_reading = {
        "contract_version": "screen_reading_v1",
        "source_layers": {
            "windows_uia": {
                "controls": [
                    {
                        "control_id": "uia_q1_yes",
                        "name": "Yes",
                        "control_type": "RadioButton",
                        "automation_id": ":r1q:",
                        "bbox": {"x": 792, "y": 594, "w": 45, "h": 45},
                    },
                    {
                        "control_id": "uia_q1_no",
                        "name": "No",
                        "control_type": "RadioButton",
                        "automation_id": ":r1r:",
                        "bbox": {"x": 792, "y": 646, "w": 45, "h": 45},
                    },
                    {
                        "control_id": "uia_q2",
                        "name": "Are you comfortable reading, altering and designing solutions with Java, AngularJS, React, Vue, MySQL?",
                        "control_type": "Text",
                        "bbox": {"x": 802, "y": 724, "w": 730, "h": 42},
                    },
                ]
            }
        },
    }

    inventory = build_employer_question_inventory(state, screen_reading=screen_reading)
    selection = select_employer_question_option(inventory["questions"][0], planned_answer="Yes")

    assert inventory["source_contracts"]["screen_reading"] == "screen_reading_v1"
    assert inventory["questions"][0]["answer_type"] == "radio_yes_no"
    assert [item["id"] for item in inventory["questions"][0]["control_candidates"]] == ["uia_q1_yes", "uia_q1_no"]
    assert selection["runner_decision"] == "allow"
    assert selection["selected_candidate"]["id"] == "uia_q1_yes"


def test_inventory_dedupes_partial_question_text_and_filters_navigation_buttons() -> None:
    state = {
        "application_form_inventory": {
            "fields": [
                _item("ocr_partial", "Which of the following statements best describes yourright to work in New", "text", 800, 422, 614, 25),
            ]
        }
    }
    screen_reading = {
        "contract_version": "screen_reading_v1",
        "source_layers": {
            "windows_uia": {
                "controls": [
                    {
                        "control_id": "uia_full_q",
                        "name": "Which of the following statements best describes your right to work in New Zealand?",
                        "control_type": "Text",
                        "bbox": {"x": 802, "y": 421, "w": 609, "h": 47},
                    },
                    {
                        "control_id": "uia_combo",
                        "name": "Which of the following statements best describes your right to work in New Zealand?",
                        "control_type": "ComboBox",
                        "automation_id": "question-NZ_Q_358_V_10",
                        "bbox": {"x": 802, "y": 479, "w": 661, "h": 49},
                    },
                    {
                        "control_id": "uia_next_q",
                        "name": "Do you have at least 1-2 years of experience in web application development?",
                        "control_type": "Text",
                        "bbox": {"x": 802, "y": 570, "w": 626, "h": 22},
                    },
                    {
                        "control_id": "uia_continue",
                        "name": "Continue",
                        "control_type": "Button",
                        "bbox": {"x": 1372, "y": 1080, "w": 120, "h": 50},
                    },
                    {
                        "control_id": "uia_back",
                        "name": "Back",
                        "control_type": "Button",
                        "bbox": {"x": 786, "y": 1080, "w": 90, "h": 50},
                    },
                ]
            }
        },
    }

    inventory = build_employer_question_inventory(state, screen_reading=screen_reading)

    assert inventory["question_count"] == 2
    assert inventory["questions"][0]["question_text"] == "Which of the following statements best describes your right to work in New Zealand?"
    assert inventory["questions"][0]["answer_type"] == "select_choice"
    assert [item["id"] for item in inventory["questions"][0]["control_candidates"]] == ["uia_combo"]
    assert all("continue" not in item["label"].casefold() for item in inventory["questions"][1]["control_candidates"])


def test_inventory_captures_select_choice_selected_value_text() -> None:
    state = {
        "application_form_inventory": {
            "fields": [
                _item("q1", "Which of the following statements best describes your right to work in New Zealand?", "text", 800, 420, 610, 28),
                _item("q1_combo", "Which of the following statements best describes your right to work in New Zealand?", "combobox", 800, 480, 660, 48),
                _item("q1_value", "I have a graduate temporary work visa (e.g. post study work visa - open)", "text", 820, 492, 560, 24),
                _item("q2", "Do you have at least 1-2 years of experience in web application development?", "text", 800, 570, 626, 22),
            ]
        }
    }

    inventory = build_employer_question_inventory(state)

    q1 = inventory["questions"][0]
    assert q1["answer_type"] == "select_choice"
    assert [item["id"] for item in q1["control_candidates"]] == ["q1_combo"]
    assert [item["id"] for item in q1["selected_value_candidates"]] == ["q1_value"]
    assert q1["selected_value_candidates"][0]["label"] == "I have a graduate temporary work visa (e.g. post study work visa - open)"


def test_inventory_infers_selected_work_rights_select_without_control_bbox() -> None:
    state = {
        "application_form_inventory": {
            "fields": [
                _item("q1", "Which of the following statements best describes your right to work in New Zealand?", "text", 800, 420, 610, 28),
                _item("q1_value", "I have a graduate temporary work visa (e.g. post study work visa - open)", "text", 820, 492, 560, 24),
            ]
        }
    }

    inventory = build_employer_question_inventory(state)

    assert inventory["question_count"] == 1
    assert inventory["questions"][0]["answer_type"] == "select_choice"
    assert inventory["questions"][0]["control_candidates"] == []
    assert inventory["questions"][0]["selected_value_candidates"][0]["id"] == "q1_value"


def test_inventory_does_not_treat_url_query_as_question() -> None:
    state = {
        "application_form_inventory": {
            "fields": [
                _item("url", "https://nz.seek.com/job/92822270/apply?sol=abc", "text", 90, 48, 601, 24),
                _item("label", "Cover letter", "text", 482, 1017, 149, 30),
            ]
        }
    }

    inventory = build_employer_question_inventory(state)

    assert inventory["question_count"] == 0


def test_inventory_merges_wrapped_questions_and_infers_empty_textarea() -> None:
    state = {
        "application_form_inventory": {
            "fields": [
                _item("q1a", "Which of the following statements best describes your right to work in New", "text", 480, 421, 612, 24),
                _item("q1b", "Zealand?", "text", 481, 447, 77, 21),
                _item("q1_value", "garbled selected work visa value", "text", 497, 491, 574, 26),
                _item("q2a", "Are you comfortable reading, altering and designing solutions with some of the", "text", 482, 712, 639, 23),
                _item("q2b", "following: Java, AngularJS, React, Vue, MySQL?", "text", 481, 737, 386, 22),
                _item("q2_yes", "Yes", "text", 519, 772, 30, 20),
                _item("q2_no", "No", "text", 517, 811, 29, 20),
                _item("q3", "Can you start immediately or within 1-2 weeks?", "text", 483, 877, 381, 22),
            ]
        }
    }

    inventory = build_employer_question_inventory(state)

    assert inventory["question_count"] == 3
    assert inventory["questions"][0]["question_text"].endswith("New Zealand?")
    assert inventory["questions"][0]["answer_type"] == "select_choice"
    assert inventory["questions"][1]["question_text"].endswith("Vue, MySQL?")
    assert inventory["questions"][1]["answer_type"] == "radio_yes_no"
    assert inventory["questions"][2]["answer_type"] == "text_input"
    textbox = inventory["questions"][2]["control_candidates"][0]
    assert textbox["source"] == "synthetic_empty_textbox_region"
    assert textbox["inference_reason"] == "empty_textarea_visible_below_text_question"
    plan = build_employer_question_answer_plan(
        inventory,
        profile={
            "contract_version": "candidate_profile_v1",
            "work_rights_summary": "Post-study Open Work Visa valid 2026-04-25 to 2029-04-25.",
            "skills": ["React", "SQL", "Frontend"],
            "experience_summary": "Built web applications and REST APIs.",
        },
    )
    preview = build_employer_question_answer_preview(plan)
    assert preview["status"] == "ready"
    assert preview["ready_count"] == 3
    assert preview["previews"][0]["target"]["action_type"] == "already_selected"
    assert preview["previews"][0]["target"]["selected_value_evidence"]["match_type"] == "visible_dropdown_value_ocr_unreliable_work_rights"


def test_inventory_handles_missing_work_rights_value_and_glued_question_text() -> None:
    state = {
        "application_form_inventory": {
            "fields": [
                _item("q1a", "Which of the following statements best describes your right to work in New", "text", 600, 527, 767, 30),
                _item("q1b", "Zealand?", "text", 602, 559, 96, 26),
                _item("q2", "Do you have at least 1-2 years of experience in web application development?", "text", 601, 711, 788, 33),
                _item("q2_yes", "Yes", "text", 641, 757, 46, 28),
                _item("q2_no", "No", "text", 647, 808, 34, 25),
                _item("q3a", "Areyou comfortablereading,altering and designing solutionswith some of the", "text", 604, 891, 798, 27),
                _item("q3b", "following: Java,AngularJS,React,Vue,MySQL?", "text", 602, 921, 482, 28),
                _item("q3_yes", "Yes", "text", 647, 965, 40, 26),
                _item("q3_no", "No", "text", 647, 1015, 34, 24),
                _item("q4", "Can you start immediately or within 1-2 weeks?", "text", 604, 1097, 475, 28),
            ]
        }
    }

    inventory = build_employer_question_inventory(state)

    assert inventory["question_count"] == 4
    assert inventory["questions"][0]["answer_type"] == "select_choice"
    assert inventory["questions"][0]["selected_value_candidates"][0]["source"] == "synthetic_work_rights_dropdown_value_region"
    assert inventory["questions"][2]["question_text"].startswith("Areyou")
    assert inventory["questions"][2]["question_text"].endswith("Vue,MySQL?")
    assert inventory["questions"][2]["answer_type"] == "radio_yes_no"
    plan = build_employer_question_answer_plan(
        inventory,
        profile={
            "contract_version": "candidate_profile_v1",
            "work_rights_summary": "Post-study Open Work Visa valid 2026-04-25 to 2029-04-25.",
            "skills": ["React", "SQL", "Frontend"],
            "experience_summary": "Built web applications and REST APIs.",
        },
    )
    preview = build_employer_question_answer_preview(plan)
    assert preview["status"] == "ready"
    assert preview["previews"][0]["target"]["selected_value_evidence"]["match_type"] == "structural_work_rights_dropdown_value_ocr_missing"


def test_employer_question_answer_plan_maps_profile_evidence_to_ready_answers() -> None:
    state = {
        "application_form_inventory": {
            "fields": [
                _item("q1", "Which of the following statements best describes your right to work in New Zealand?", "text", 800, 420, 610, 28),
                _item("q1_combo", "Which of the following statements best describes your right to work in New Zealand?", "combobox", 800, 480, 660, 48),
                _item("q2", "Do you have at least 1-2 years of experience in web application development?", "text", 800, 570, 626, 22),
                _item("q2_yes", "Yes", "radio", 792, 594, 45, 45),
                _item("q2_no", "No", "radio", 792, 646, 45, 45),
                _item("q3", "Are you comfortable reading, altering and designing solutions with Java, AngularJS, React, Vue, MySQL?", "text", 800, 724, 760, 42),
                _item("q3_yes", "Yes", "radio", 792, 780, 45, 45),
                _item("q3_no", "No", "radio", 792, 832, 45, 45),
                _item("q4", "Can you start immediately or within 1-2 weeks?", "text", 800, 910, 600, 28),
                _item("q4_text", "", "textbox", 800, 950, 650, 100),
            ]
        }
    }
    inventory = build_employer_question_inventory(state)
    profile = {
        "contract_version": "candidate_profile_v1",
        "work_rights_summary": "Post-study Open Work Visa valid 2026-04-25 to 2029-04-25; may undertake any work anywhere in New Zealand.",
        "experience_summary": "Built scalable frontend applications, REST APIs, test automation, and web implementation projects.",
        "skills": ["React", "SQL", "Frontend", "Software Engineering"],
    }

    plan = build_employer_question_answer_plan(inventory, profile=profile)

    assert plan["contract_version"] == "employer_question_answer_plan_v1"
    assert plan["status"] == "ready"
    assert plan["question_count"] == 4
    assert plan["ready_count"] == 4
    answers = plan["answers"]
    assert answers[0]["answer_category"] == "work_rights"
    assert answers[0]["planned_answer"] == "I have a graduate temporary work visa (e.g. post study work visa - open)"
    assert answers[1]["planned_answer"] == "Yes"
    assert answers[1]["selection"]["runner_decision"] == "allow"
    assert answers[2]["planned_answer"] == "Yes"
    assert answers[2]["selection"]["selected_candidate"]["id"] == "q3_yes"
    assert answers[3]["answer_category"] == "availability"
    assert "1-2 weeks" in answers[3]["planned_answer"]


def test_employer_question_answer_plan_blocks_sensitive_question() -> None:
    inventory = {
        "contract_version": "employer_question_inventory_v1",
        "questions": [
            {
                "question_id": "q1",
                "question_text": "Do you have any criminal convictions or health conditions we should know about?",
                "question_text_hash": "hash",
                "answer_type": "text_input",
                "control_candidates": [],
            }
        ],
    }

    plan = build_employer_question_answer_plan(inventory, profile={"contract_version": "candidate_profile_v1"})

    assert plan["status"] == "needs_user_review"
    assert plan["counts"]["blocked_sensitive"] == 1
    assert plan["answers"][0]["status"] == "blocked_sensitive"
    assert plan["answers"][0]["requires_user_review"] is True


def test_employer_question_answer_preview_builds_click_and_type_targets() -> None:
    state = {
        "application_form_inventory": {
            "fields": [
                _item("q1", "Do you have at least 1-2 years of experience in web application development?", "text", 800, 570, 626, 22),
                _item("q1_yes", "Yes", "radio", 792, 594, 45, 45),
                _item("q1_no", "No", "radio", 792, 646, 45, 45),
                _item("q2", "Can you start immediately or within 1-2 weeks?", "text", 800, 724, 626, 22),
                _item("q2_text", "", "textbox", 802, 760, 650, 110),
            ]
        }
    }
    inventory = build_employer_question_inventory(state)
    plan = build_employer_question_answer_plan(
        inventory,
        profile={
            "contract_version": "candidate_profile_v1",
            "experience_summary": "Built web applications and REST APIs.",
            "skills": ["React", "SQL"],
            "work_rights_summary": "Post-study Open Work Visa valid 2026-04-25 to 2029-04-25.",
        },
    )

    preview = build_employer_question_answer_preview(plan)

    assert preview["contract_version"] == "employer_question_answer_preview_v1"
    assert preview["status"] == "ready"
    assert preview["ready_count"] == 2
    click_preview = preview["previews"][0]
    assert click_preview["runner_decision"] == "allow"
    assert click_preview["target"]["action_type"] == "click"
    assert click_preview["target"]["candidate"]["id"] == "q1_yes"
    type_preview = preview["previews"][1]
    assert type_preview["runner_decision"] == "allow"
    assert type_preview["target"]["action_type"] == "type_text"
    assert type_preview["target"]["candidate"]["id"] == "q2_text"
    assert type_preview["target"]["bbox"] == {"x": 802, "y": 760, "w": 650, "h": 110}
    assert type_preview["target"]["submit"] is False


def test_employer_question_answer_preview_requires_review_for_unmapped_select_choice() -> None:
    answer_plan = {
        "contract_version": "employer_question_answer_plan_v1",
        "answers": [
            {
                "question_id": "q1",
                "question_text": "Which of the following statements best describes your right to work in New Zealand?",
                "question_text_hash": "hash",
                "answer_type": "select_choice",
                "status": "ready",
                "answer_category": "work_rights",
                "planned_answer": "I have a graduate temporary work visa (e.g. post study work visa - open)",
                "answer_source": "candidate_profile_v1.work_rights_summary",
                "requires_user_review": False,
                "selection": None,
            }
        ],
    }

    preview = build_employer_question_answer_preview(answer_plan)

    assert preview["status"] == "needs_user_review"
    assert preview["previews"][0]["runner_decision"] == "needs_user_review"
    assert preview["previews"][0]["reject_reason"] == "select_choice_requires_dropdown_option_mapping"


def test_employer_question_answer_preview_marks_selected_select_choice_done() -> None:
    answer_plan = {
        "contract_version": "employer_question_answer_plan_v1",
        "answers": [
            {
                "question_id": "q1",
                "question_text": "Which of the following statements best describes your right to work in New Zealand?",
                "question_text_hash": "hash",
                "answer_type": "select_choice",
                "status": "ready",
                "answer_category": "work_rights",
                "planned_answer": "I have a graduate temporary work visa (e.g. post study work visa - open)",
                "answer_source": "candidate_profile_v1.work_rights_summary",
                "requires_user_review": False,
                "selection": None,
                "selected_value_candidates": [
                    {
                        "id": "q1_value",
                        "label": "I have a graduate temporary work visa (e.g. post study work visa - open)",
                        "role": "text",
                        "bbox": {"x": 820, "y": 492, "w": 560, "h": 24},
                        "source": "test",
                    }
                ],
            }
        ],
    }

    preview = build_employer_question_answer_preview(answer_plan)

    assert preview["status"] == "ready"
    assert preview["ready_count"] == 1
    assert preview["previews"][0]["runner_decision"] == "allow"
    assert preview["previews"][0]["requires_post_fill_verification"] is False
    assert preview["previews"][0]["target"]["action_type"] == "already_selected"
    assert preview["previews"][0]["target"]["selected_value_evidence"]["candidate"]["id"] == "q1_value"
