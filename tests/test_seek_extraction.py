from __future__ import annotations

from app.seek.extraction import extract_seek_job_cards, extract_seek_job_detail


def test_extract_seek_job_cards_from_screen_inventory() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "action_job_1",
                "label": "Software Engineer (Test Systems)",
                "bbox": {"x": 20, "y": 400, "w": 420, "h": 220},
                "click_point": {"x": 230, "y": 510},
                "metadata": {"source": "vision"},
            },
            {
                "id": "action_save_1",
                "label": "Save",
                "bbox": {"x": 390, "y": 590, "w": 34, "h": 30},
                "click_point": {"x": 407, "y": 605},
                "metadata": {"source": "uia"},
            },
        ],
        "page_elements": [
            {"id": "text_company_1", "text": "Quantifi Photonics", "bbox": {"x": 32, "y": 455, "w": 180, "h": 22}},
            {"id": "text_location_1", "text": "Rosedale, Auckland", "bbox": {"x": 32, "y": 490, "w": 190, "h": 22}},
            {"id": "text_work_type_1", "text": "Full time", "bbox": {"x": 32, "y": 525, "w": 120, "h": 22}},
            {
                "id": "text_url_1",
                "text": "https://jobs.teradyne.com/job-invite/11792/",
                "bbox": {"x": 32, "y": 560, "w": 330, "h": 22},
            },
        ],
        "cards": [
            {
                "id": "card_job_1",
                "label": "Software Engineer (Test Systems)",
                "bbox": {"x": 20, "y": 400, "w": 420, "h": 220},
                "primary_action_id": "action_job_1",
                "child_action_ids": ["action_job_1", "action_save_1"],
                "child_page_element_ids": [
                    "text_company_1",
                    "text_location_1",
                    "text_work_type_1",
                    "text_url_1",
                ],
            },
            {
                "id": "card_filter_pay",
                "label": "Pay",
                "bbox": {"x": 20, "y": 120, "w": 90, "h": 44},
                "primary_action_id": "filter_pay",
                "child_action_ids": [],
                "child_page_element_ids": [],
            },
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["contract_version"] == "seek_job_cards_v1"
    assert result["summary"]["jobs_seen"] == 1
    job = result["jobs"][0]
    assert job["contract_version"] == "seek_job_card_v1"
    assert job["title"] == "Software Engineer (Test Systems)"
    assert job["company"] == "Quantifi Photonics"
    assert job["location"] == "Rosedale, Auckland"
    assert job["work_type"] == "Full time"
    assert job["source_url"] == "https://jobs.teradyne.com/job-invite/11792/"
    assert job["card_bbox"] == {"x": 20, "y": 400, "w": 420, "h": 220}
    assert job["click_point"] == {"x": 230, "y": 510}


def test_extract_seek_job_card_uses_child_title_when_card_label_is_generic() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "action_job_1",
                "label": "Job listing",
                "bbox": {"x": 20, "y": 400, "w": 420, "h": 220},
                "click_point": {"x": 230, "y": 510},
            }
        ],
        "page_elements": [
            {"id": "title", "text": "Applications Software Engineer", "bbox": {"x": 32, "y": 430, "w": 240, "h": 22}},
            {"id": "company", "text": "Temperzone", "bbox": {"x": 32, "y": 460, "w": 140, "h": 22}},
            {"id": "location", "text": "Manukau, Auckland", "bbox": {"x": 32, "y": 490, "w": 180, "h": 22}},
        ],
        "cards": [
            {
                "id": "card_browser_window",
                "label": "Software Engineer Jobs in All Auckland - Microsoft Edge",
                "bbox": {"x": 0, "y": 0, "w": 1200, "h": 1000},
                "primary_action_id": "browser_title",
                "child_action_ids": [],
                "child_page_element_ids": ["title", "company", "location"],
            },
            {
                "id": "card_filter_spanning_results",
                "label": "software engineer Applications Software Engineer",
                "bbox": {"x": 58, "y": 196, "w": 260, "h": 300},
                "primary_action_id": "bad_filter_card",
                "child_action_ids": [],
                "child_page_element_ids": ["title", "company", "location"],
            },
            {
                "id": "card_job_1",
                "label": "Job listing",
                "bbox": {"x": 20, "y": 400, "w": 420, "h": 220},
                "primary_action_id": "action_job_1",
                "child_action_ids": [],
                "child_page_element_ids": ["title", "company", "location"],
            },
            {
                "id": "card_job_1_link",
                "label": "hyperlink",
                "bbox": {"x": 20, "y": 400, "w": 420, "h": 220},
                "primary_action_id": "action_job_1",
                "child_action_ids": [],
                "child_page_element_ids": ["title", "company", "location"],
            }
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 1
    job = result["jobs"][0]
    assert job["title"] == "Applications Software Engineer"
    assert job["company"] == "Temperzone"
    assert job["location"] == "Manukau, Auckland"


def test_extract_seek_job_card_uses_child_title_when_label_is_job_title() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "action_job_1",
                "label": "Job title link",
                "bbox": {"x": 37, "y": 388, "w": 341, "h": 182},
                "click_point": {"x": 208, "y": 479},
            }
        ],
        "page_elements": [
            {"id": "logo_noise", "text": "obe p8", "bbox": {"x": 58, "y": 410, "w": 80, "h": 20}},
            {"id": "title", "text": "Staff Software Engineer", "bbox": {"x": 58, "y": 440, "w": 240, "h": 24}},
            {"id": "company", "text": "Kami Holdings Limited", "bbox": {"x": 58, "y": 470, "w": 190, "h": 24}},
            {"id": "location", "text": "Parnell, Auckland", "bbox": {"x": 58, "y": 500, "w": 190, "h": 24}},
        ],
        "cards": [
            {
                "id": "card_job_title",
                "label": "Job title link",
                "bbox": {"x": 37, "y": 388, "w": 341, "h": 182},
                "primary_action_id": "action_job_1",
                "child_action_ids": [],
                "child_page_element_ids": ["logo_noise", "title", "company", "location"],
            }
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 1
    job = result["jobs"][0]
    assert job["title"] == "Staff Software Engineer"
    assert job["company"] == "Kami Holdings Limited"
    assert job["location"] == "Parnell, Auckland"


def test_extract_seek_job_cards_skips_numbered_generic_listing_without_child_title() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "action_job_1",
                "label": "Job listing 1",
                "bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
                "click_point": {"x": 220, "y": 510},
            }
        ],
        "page_elements": [
            {"id": "company", "text": "Temperzone", "bbox": {"x": 40, "y": 454, "w": 180, "h": 22}},
            {"id": "location", "text": "Manukau, Auckland", "bbox": {"x": 40, "y": 488, "w": 180, "h": 22}},
            {
                "id": "summary",
                "text": "systems, streamline processes, and power business",
                "bbox": {"x": 40, "y": 522, "w": 320, "h": 22},
            },
        ],
        "cards": [
            {
                "id": "card_job_1",
                "label": "Job listing 1",
                "bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
                "primary_action_id": "action_job_1",
                "child_action_ids": [],
                "child_page_element_ids": ["company", "location", "summary"],
            }
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 0


def test_extract_seek_job_cards_prefers_complete_uia_card_for_overlapping_same_job() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "action_screen_mixed",
                "label": "Software Applications Software Engineer",
                "bbox": {"x": 56, "y": 571, "w": 262, "h": 255},
                "click_point": {"x": 187, "y": 698},
            },
            {
                "id": "action_uia_complete",
                "label": "Engineering Manager - Software",
                "bbox": {"x": 36, "y": 529, "w": 426, "h": 243},
                "click_point": {"x": 249, "y": 650},
            },
            {
                "id": "action_uia_incomplete",
                "label": "hyperlink",
                "bbox": {"x": 36, "y": 529, "w": 426, "h": 243},
                "click_point": {"x": 249, "y": 650},
            },
        ],
        "page_elements": [
            {"id": "title_a", "text": "Engineering Manager -", "bbox": {"x": 58, "y": 560, "w": 220, "h": 24}},
            {"id": "title_b", "text": "Software", "bbox": {"x": 58, "y": 590, "w": 100, "h": 24}},
            {"id": "company", "text": "Halter", "bbox": {"x": 58, "y": 622, "w": 90, "h": 24}},
            {"id": "location", "text": "Auckland CBD, Auckland", "bbox": {"x": 58, "y": 654, "w": 230, "h": 24}},
            {
                "id": "summary",
                "text": "We're looking for a Software Engineering Manager to lead a team",
                "bbox": {"x": 58, "y": 686, "w": 330, "h": 42},
            },
            {"id": "stale_title", "text": "Applications Software Engineer", "bbox": {"x": 58, "y": 732, "w": 280, "h": 24}},
        ],
        "cards": [
            {
                "id": "card_screen_mixed",
                "label": "Software Applications Software Engineer",
                "bbox": {"x": 56, "y": 571, "w": 262, "h": 255},
                "primary_action_id": "action_screen_mixed",
                "child_action_ids": ["action_screen_mixed"],
                "child_page_element_ids": ["title_b", "company", "location", "summary", "stale_title"],
            },
            {
                "id": "card_uia_complete",
                "label": "Engineering Manager - Software",
                "bbox": {"x": 36, "y": 529, "w": 426, "h": 243},
                "primary_action_id": "action_uia_complete",
                "child_action_ids": ["action_uia_complete"],
                "child_page_element_ids": ["title_a", "title_b", "company", "location", "summary"],
            },
            {
                "id": "card_uia_incomplete",
                "label": "hyperlink",
                "bbox": {"x": 36, "y": 529, "w": 426, "h": 243},
                "primary_action_id": "action_uia_incomplete",
                "child_action_ids": ["action_uia_incomplete"],
                "child_page_element_ids": ["title_a", "title_b", "company", "location", "summary"],
            },
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 1
    job = result["jobs"][0]
    assert job["title"] == "Engineering Manager - Software"
    assert job["source_card_id"] == "card_uia_complete"
    assert job["primary_action_id"] == "action_uia_complete"


def test_extract_seek_job_detail_from_right_pane_inventory() -> None:
    detail_bbox = {"x": 490, "y": 210, "w": 650, "h": 900}
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "detail_apply",
                "label": "Apply",
                "bbox": {"x": 520, "y": 820, "w": 110, "h": 48},
                "click_point": {"x": 575, "y": 844},
            },
            {
                "id": "detail_save",
                "label": "Save",
                "bbox": {"x": 650, "y": 820, "w": 88, "h": 48},
                "click_point": {"x": 694, "y": 844},
            },
        ],
        "page_elements": [
            {"id": "detail_title", "text": "Software Engineer (Test Systems)", "bbox": {"x": 520, "y": 580, "w": 360, "h": 34}},
            {"id": "detail_company", "text": "Quantifi Photonics", "bbox": {"x": 520, "y": 630, "w": 220, "h": 24}},
            {"id": "detail_location", "text": "Rosedale, Auckland", "bbox": {"x": 520, "y": 680, "w": 220, "h": 24}},
            {"id": "detail_work", "text": "Full time", "bbox": {"x": 520, "y": 720, "w": 140, "h": 24}},
            {
                "id": "detail_requirements",
                "text": "Requirements: C# programming experience and test automation skills.",
                "bbox": {"x": 520, "y": 930, "w": 560, "h": 40},
            },
            {
                "id": "detail_responsibilities",
                "text": "You will build and support test systems for photonics products.",
                "bbox": {"x": 520, "y": 980, "w": 560, "h": 40},
            },
            {
                "id": "detail_benefits",
                "text": "Benefits include flexible work and health insurance.",
                "bbox": {"x": 520, "y": 1030, "w": 560, "h": 40},
            },
        ],
    }
    scroll_containers = {
        "contract_version": "scroll_containers_v1",
        "containers": [
            {
                "container_id": "seek:job_detail",
                "label": "job detail",
                "bbox": detail_bbox,
                "safe_points": [{"x": 815, "y": 600}],
            }
        ],
    }

    detail = extract_seek_job_detail(inventory, scroll_containers=scroll_containers)

    assert detail["contract_version"] == "seek_job_detail_v1"
    assert detail["title"] == "Software Engineer (Test Systems)"
    assert detail["company"] == "Quantifi Photonics"
    assert detail["location"] == "Rosedale, Auckland"
    assert detail["work_type"] == "Full time"
    assert detail["apply_button_state"]["visible"] is True
    assert detail["apply_button_state"]["click_point"] == {"x": 575, "y": 844}
    assert detail["save_button_state"]["visible"] is True
    assert detail["detail_container"]["container_id"] == "seek:job_detail"
    assert detail["requirements"] == ["Requirements: C# programming experience and test automation skills."]
    assert detail["responsibilities"] == ["You will build and support test systems for photonics products."]
    assert detail["benefits"] == ["Benefits include flexible work and health insurance."]


def test_extract_seek_job_detail_uses_apply_text_when_action_bbox_is_outside_detail() -> None:
    detail_bbox = {"x": 513, "y": 346, "w": 709, "h": 832}
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "misaligned_apply_action",
                "label": "Apply button",
                "bbox": {"x": 420, "y": 815, "w": 130, "h": 35},
                "click_point": {"x": 485, "y": 832},
            }
        ],
        "page_elements": [
            {"id": "title", "text": "Applications Software Engineer", "bbox": {"x": 560, "y": 520, "w": 360, "h": 34}},
            {"id": "company", "text": "Temperzone View all jobs", "bbox": {"x": 560, "y": 570, "w": 240, "h": 24}},
            {"id": "location", "text": "Manukau, Auckland", "bbox": {"x": 560, "y": 615, "w": 220, "h": 24}},
            {"id": "apply_text", "text": "Apply C", "bbox": {"x": 559, "y": 815, "w": 84, "h": 32}},
        ],
    }
    scroll_containers = {
        "contract_version": "scroll_containers_v1",
        "containers": [{"container_id": "seek:job_detail", "bbox": detail_bbox}],
    }

    detail = extract_seek_job_detail(inventory, scroll_containers=scroll_containers)

    assert detail["apply_button_state"]["visible"] is True
    assert detail["apply_button_state"]["label"] == "Apply C"
    assert detail["apply_button_state"]["click_point"] == {"x": 601, "y": 831}


def test_extract_seek_job_cards_synthesizes_from_results_list_texts_when_cards_missing() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [],
        "page_elements": [
            {"id": "title1", "text": "Applications Software Engineer", "bbox": {"x": 58, "y": 470, "w": 260, "h": 24}},
            {"id": "company1", "text": "Temperzone", "bbox": {"x": 58, "y": 500, "w": 120, "h": 24}},
            {"id": "location1", "text": "Manukau, Auckland", "bbox": {"x": 58, "y": 532, "w": 190, "h": 24}},
            {"id": "summary1", "text": "Build and support modern applications.", "bbox": {"x": 58, "y": 570, "w": 320, "h": 24}},
            {"id": "title2", "text": "Software Engineers (All levels!)", "bbox": {"x": 58, "y": 824, "w": 260, "h": 24}},
            {"id": "company2", "text": "Halter", "bbox": {"x": 58, "y": 852, "w": 90, "h": 24}},
            {"id": "location2", "text": "Auckland CBD, Auckland", "bbox": {"x": 58, "y": 884, "w": 230, "h": 24}},
        ],
        "cards": [],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 2
    assert [(job["title"], job["company"], job["location"]) for job in result["jobs"]] == [
        ("Applications Software Engineer", "Temperzone", "Manukau, Auckland"),
        ("Software Engineers (All levels!)", "Halter", "Auckland CBD, Auckland"),
    ]
    assert result["jobs"][0]["evidence"]["synthetic_from"] == "results_list_page_elements"


def test_extract_seek_job_cards_replaces_incomplete_card_duplicate_with_synthetic_card() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "action_job_1",
                "label": "Software Engineers (All levels!)",
                "bbox": {"x": 47, "y": 675, "w": 326, "h": 195},
                "click_point": {"x": 210, "y": 772},
            }
        ],
        "page_elements": [
            {
                "id": "summary_a",
                "text": "Build and support modern applications that connect",
                "bbox": {"x": 58, "y": 710, "w": 320, "h": 24},
            },
            {"id": "title", "text": "Software Engineers (All levels!)", "bbox": {"x": 58, "y": 824, "w": 260, "h": 24}},
            {"id": "company", "text": "Halter", "bbox": {"x": 58, "y": 852, "w": 90, "h": 24}},
            {"id": "location", "text": "Auckland CBD, Auckland", "bbox": {"x": 58, "y": 884, "w": 230, "h": 24}},
        ],
        "cards": [
            {
                "id": "card_job_incomplete",
                "label": "Software Engineers (All levels!)",
                "bbox": {"x": 47, "y": 675, "w": 326, "h": 195},
                "primary_action_id": "action_job_1",
                "child_action_ids": ["action_job_1"],
                "child_page_element_ids": ["summary_a", "title", "company"],
            }
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 1
    job = result["jobs"][0]
    assert job["title"] == "Software Engineers (All levels!)"
    assert job["company"] == "Halter"
    assert job["location"] == "Auckland CBD, Auckland"
    assert job["evidence"]["synthetic_from"] == "results_list_page_elements"


def test_extract_seek_job_cards_rejects_card_label_with_incomplete_title_suffix() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "action_job_1",
                "label": "Engineering Manager -",
                "bbox": {"x": 47, "y": 430, "w": 326, "h": 195},
                "click_point": {"x": 210, "y": 520},
            }
        ],
        "page_elements": [
            {"id": "title", "text": "Engineering Manager -", "bbox": {"x": 58, "y": 460, "w": 220, "h": 24}},
            {
                "id": "summary",
                "text": "We're looking for a Software Engineering Manager who builds and elevates their team",
                "bbox": {"x": 58, "y": 492, "w": 360, "h": 48},
            },
        ],
        "cards": [
            {
                "id": "card_job_incomplete_title",
                "label": "Engineering Manager -",
                "bbox": {"x": 47, "y": 430, "w": 326, "h": 195},
                "primary_action_id": "action_job_1",
                "child_action_ids": ["action_job_1"],
                "child_page_element_ids": ["title", "summary"],
            }
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 0


def test_extract_seek_job_cards_keeps_synthetic_card_boundaries_and_ignores_descriptions() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [],
        "page_elements": [
            {"id": "title1", "text": "Software Engineer", "bbox": {"x": 58, "y": 420, "w": 220, "h": 24}},
            {"id": "company1", "text": "Potentia", "bbox": {"x": 58, "y": 452, "w": 110, "h": 24}},
            {"id": "location1", "text": "Auckland CBD, Auckland", "bbox": {"x": 58, "y": 484, "w": 220, "h": 24}},
            {
                "id": "summary1",
                "text": "Build scalable software using Python & C# in a cloud environment",
                "bbox": {"x": 58, "y": 520, "w": 330, "h": 42},
            },
            {
                "id": "url1",
                "text": "https://www.seek.co.nz/job/123456",
                "bbox": {"x": 58, "y": 566, "w": 300, "h": 24},
            },
            {
                "id": "title2",
                "text": "Staff Software Engineer",
                "bbox": {"x": 58, "y": 612, "w": 260, "h": 24},
            },
            {"id": "company2", "text": "GreenTech", "bbox": {"x": 58, "y": 644, "w": 130, "h": 24}},
            {"id": "location2", "text": "Parnell, Auckland", "bbox": {"x": 58, "y": 676, "w": 190, "h": 24}},
            {
                "id": "summary2",
                "text": "Global decarbonisation through scalable, purpose-led technology",
                "bbox": {"x": 58, "y": 708, "w": 330, "h": 42},
            },
        ],
        "cards": [],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 2
    assert [(job["title"], job["company"], job["location"]) for job in result["jobs"]] == [
        ("Software Engineer", "Potentia", "Auckland CBD, Auckland"),
        ("Staff Software Engineer", "GreenTech", "Parnell, Auckland"),
    ]
    assert all("Build scalable" not in job["title"] for job in result["jobs"])
    assert all(not str(job["location"]).startswith("https://") for job in result["jobs"])


def test_extract_seek_job_cards_does_not_treat_ownership_summary_as_title() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [],
        "page_elements": [
            {
                "id": "summary",
                "text": "global casino platforms with strong ownership and",
                "bbox": {"x": 58, "y": 420, "w": 330, "h": 24},
            },
            {
                "id": "company",
                "text": "DataScientist-Video Analytics",
                "bbox": {"x": 58, "y": 452, "w": 260, "h": 24},
            },
            {"id": "location", "text": "Auckland (Hybrid)", "bbox": {"x": 58, "y": 484, "w": 180, "h": 24}},
        ],
        "cards": [],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 1
    assert result["jobs"][0]["title"] == "DataScientist-Video Analytics"


def test_extract_seek_job_cards_rejects_synthetic_body_text_without_card_anchor() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [],
        "page_elements": [
            {
                "id": "detail_like_title",
                "text": "Fullstack Engineering, AI, RAG, Tooling",
                "bbox": {"x": 58, "y": 420, "w": 320, "h": 24},
            },
            {
                "id": "detail_like_summary",
                "text": "Work on frontend experiences to robust backend",
                "bbox": {"x": 58, "y": 452, "w": 330, "h": 24},
            },
        ],
        "cards": [],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 0


def test_extract_seek_job_cards_rejects_synthetic_detail_classification_and_background_section() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [],
        "page_elements": [
            {
                "id": "classification",
                "text": "Engineering-Software (Information & Communication Technology)",
                "bbox": {"x": 58, "y": 420, "w": 360, "h": 24},
            },
            {
                "id": "background",
                "text": "Background",
                "bbox": {"x": 58, "y": 452, "w": 120, "h": 24},
            },
            {
                "id": "description",
                "text": "You will work with product teams on delivery",
                "bbox": {"x": 58, "y": 484, "w": 330, "h": 24},
            },
        ],
        "cards": [],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 0


def test_extract_seek_job_cards_merges_split_synthetic_title_before_company() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [],
        "page_elements": [
            {
                "id": "title_a",
                "text": "Lead Software Engineer - AI &",
                "bbox": {"x": 58, "y": 420, "w": 280, "h": 24},
            },
            {"id": "title_b", "text": "Automation", "bbox": {"x": 58, "y": 452, "w": 130, "h": 24}},
            {"id": "company", "text": "First Focus IT P/L", "bbox": {"x": 58, "y": 484, "w": 180, "h": 24}},
            {"id": "location", "text": "Auckland CBD, Auckland (Hybrid)", "bbox": {"x": 58, "y": 516, "w": 260, "h": 24}},
            {"id": "salary", "text": "Up to $170k + Kiwisaver", "bbox": {"x": 58, "y": 548, "w": 230, "h": 24}},
        ],
        "cards": [],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 1
    job = result["jobs"][0]
    assert job["title"] == "Lead Software Engineer - AI & Automation"
    assert job["company"] == "First Focus IT P/L"
    assert job["location"] == "Auckland CBD, Auckland (Hybrid)"


def test_extract_seek_job_cards_rejects_synthetic_card_that_spans_detail_pane() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [],
        "page_elements": [
            {"id": "title", "text": "Senior Software Engineer", "bbox": {"x": 58, "y": 960, "w": 240, "h": 24}},
            {"id": "company", "text": "Absolute IT Limited", "bbox": {"x": 58, "y": 992, "w": 180, "h": 24}},
            {"id": "location", "text": "Auckland CBD, Auckland", "bbox": {"x": 58, "y": 1024, "w": 220, "h": 24}},
            {"id": "save_search", "text": "Save this search", "bbox": {"x": 680, "y": 1050, "w": 180, "h": 24}},
            {
                "id": "url",
                "text": "https://nz.seek.com/job/92763500?type=standard&ref=search-standalone&origin=jobCard",
                "bbox": {"x": 58, "y": 1082, "w": 850, "h": 24},
            },
        ],
        "cards": [],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 0


def test_extract_seek_job_cards_rejects_viewed_status_as_synthetic_company() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [],
        "page_elements": [
            {
                "id": "summary_title",
                "text": "Lead a talented engineering team delivering a major",
                "bbox": {"x": 58, "y": 748, "w": 368, "h": 24},
            },
            {
                "id": "summary",
                "text": "digital transformation in Auckland. Strategic role",
                "bbox": {"x": 58, "y": 780, "w": 360, "h": 24},
            },
            {"id": "viewed", "text": "23h ago ·Viewed", "bbox": {"x": 58, "y": 812, "w": 130, "h": 24}},
        ],
        "cards": [],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 0


def test_extract_seek_job_detail_prefers_job_title_over_brand_logo() -> None:
    detail_bbox = {"x": 490, "y": 210, "w": 650, "h": 900}
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "detail_apply",
                "label": "Apply",
                "bbox": {"x": 520, "y": 820, "w": 110, "h": 48},
                "click_point": {"x": 575, "y": 844},
            }
        ],
        "page_elements": [
            {"id": "logo", "text": "temperzone", "bbox": {"x": 520, "y": 360, "w": 180, "h": 24}},
            {"id": "tagline", "text": "climate innovations", "bbox": {"x": 520, "y": 390, "w": 180, "h": 24}},
            {"id": "title", "text": "Applications Software Engineer", "bbox": {"x": 520, "y": 450, "w": 360, "h": 34}},
            {"id": "company", "text": "Temperzone View all jobs", "bbox": {"x": 520, "y": 500, "w": 240, "h": 24}},
            {"id": "location", "text": "Manukau, Auckland", "bbox": {"x": 520, "y": 545, "w": 220, "h": 24}},
            {"id": "responsibility", "text": "Key Responsibilities:", "bbox": {"x": 520, "y": 700, "w": 240, "h": 24}},
        ],
    }
    scroll_containers = {
        "contract_version": "scroll_containers_v1",
        "containers": [{"container_id": "seek:job_detail", "bbox": detail_bbox}],
    }

    detail = extract_seek_job_detail(inventory, scroll_containers=scroll_containers)

    assert detail["title"] == "Applications Software Engineer"
    assert detail["company"] == "Temperzone"
    assert detail["location"] == "Manukau, Auckland"


def test_extract_seek_job_detail_includes_header_above_scroll_body() -> None:
    detail_bbox = {"x": 490, "y": 346, "w": 650, "h": 820}
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "quick_apply",
                "label": "Quick apply",
                "bbox": {"x": 520, "y": 473, "w": 130, "h": 48},
                "click_point": {"x": 585, "y": 497},
            }
        ],
        "page_elements": [
            {"id": "title", "text": "Full-StackDevelopers", "bbox": {"x": 520, "y": 188, "w": 320, "h": 34}},
            {"id": "company", "text": "BrightSpark Recruitment View all jobs", "bbox": {"x": 520, "y": 223, "w": 320, "h": 24}},
            {"id": "location", "text": "Auckland CBD, Auckland (Hybrid)", "bbox": {"x": 520, "y": 266, "w": 260, "h": 24}},
            {
                "id": "body",
                "text": "The agency is made up of a highly skilled team of designers, developers, and project managers.",
                "bbox": {"x": 520, "y": 730, "w": 560, "h": 48},
            },
        ],
    }
    scroll_containers = {
        "contract_version": "scroll_containers_v1",
        "containers": [{"container_id": "seek:job_detail", "bbox": detail_bbox}],
    }

    detail = extract_seek_job_detail(inventory, scroll_containers=scroll_containers)

    assert detail["title"] == "Full-StackDevelopers"
    assert detail["company"] == "BrightSpark Recruitment"
    assert detail["location"] == "Auckland CBD, Auckland (Hybrid)"
    assert detail["apply_button_state"]["visible"] is True
    assert detail["detail_read_bbox"]["y"] < detail_bbox["y"]
