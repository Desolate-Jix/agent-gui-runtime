from __future__ import annotations

from app.seek.extraction import extract_seek_job_cards, extract_seek_job_detail, infer_results_list_bbox_from_inventory


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


def test_extract_seek_job_cards_returns_visual_top_to_bottom_order() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {"id": "action_bottom", "label": "Backend Developer", "bbox": {"x": 20, "y": 700, "w": 420, "h": 180}, "click_point": {"x": 230, "y": 790}},
            {"id": "action_top", "label": "Application Support Engineer", "bbox": {"x": 20, "y": 400, "w": 420, "h": 180}, "click_point": {"x": 230, "y": 490}},
        ],
        "page_elements": [
            {"id": "bottom_company", "text": "Bottom Co", "bbox": {"x": 32, "y": 748, "w": 130, "h": 22}},
            {"id": "bottom_location", "text": "Wellington, NZ", "bbox": {"x": 32, "y": 780, "w": 160, "h": 22}},
            {"id": "top_company", "text": "Westpac New Zealand Limited", "bbox": {"x": 32, "y": 448, "w": 220, "h": 22}},
            {"id": "top_location", "text": "Auckland CBD, Auckland (Hybrid)", "bbox": {"x": 32, "y": 480, "w": 260, "h": 22}},
        ],
        "cards": [
            {
                "id": "card_bottom",
                "label": "Backend Developer",
                "bbox": {"x": 20, "y": 700, "w": 420, "h": 180},
                "primary_action_id": "action_bottom",
                "child_action_ids": ["action_bottom"],
                "child_page_element_ids": ["bottom_company", "bottom_location"],
            },
            {
                "id": "card_top",
                "label": "Application Support Engineer",
                "bbox": {"x": 20, "y": 400, "w": 420, "h": 180},
                "primary_action_id": "action_top",
                "child_action_ids": ["action_top"],
                "child_page_element_ids": ["top_company", "top_location"],
            },
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert [job["title"] for job in result["jobs"]] == ["Application Support Engineer", "Backend Developer"]


def test_extract_seek_job_cards_infers_centered_results_list_from_live_cards() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "action_job_1",
                "label": "Software Engineer",
                "bbox": {"x": 620, "y": 420, "w": 420, "h": 180},
                "click_point": {"x": 800, "y": 500},
            }
        ],
        "page_elements": [
            {"id": "company", "text": "Example Tech", "bbox": {"x": 650, "y": 470, "w": 160, "h": 24}},
            {"id": "location", "text": "Auckland", "bbox": {"x": 650, "y": 510, "w": 120, "h": 24}},
        ],
        "cards": [
            {
                "id": "card_job_1",
                "label": "Software Engineer",
                "bbox": {"x": 600, "y": 390, "w": 470, "h": 250},
                "primary_action_id": "action_job_1",
                "child_action_ids": ["action_job_1"],
                "child_page_element_ids": ["company", "location"],
            }
        ],
    }

    inferred = infer_results_list_bbox_from_inventory(inventory, window_size={"width": 2560, "height": 1400})
    result = extract_seek_job_cards({"image_size": {"width": 2560, "height": 1400}, "screen_inventory": inventory})

    assert inferred is not None
    assert inferred["x"] >= 580
    assert result["summary"]["jobs_seen"] == 1
    assert result["results_list_container"]["sources"] == ["screen_inventory_job_card_bbox"]
    assert result["results_list_container"]["bbox"]["x"] >= 580
    assert result["jobs"][0]["click_point"] == {"x": 800, "y": 500}


def test_extract_seek_job_cards_rejects_homepage_recommendation_sidebar_cards() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [
            {
                "id": "saved_action",
                "label": "Saved searches section",
                "bbox": {"x": 1140, "y": 600, "w": 356, "h": 200},
                "click_point": {"x": 1318, "y": 700},
            },
            {
                "id": "compensation_action",
                "label": "Compensation range selector",
                "bbox": {"x": 1140, "y": 1000, "w": 356, "h": 200},
                "click_point": {"x": 1318, "y": 1100},
            },
            {
                "id": "next_action",
                "label": "Next button",
                "bbox": {"x": 1140, "y": 1200, "w": 356, "h": 100},
                "click_point": {"x": 1318, "y": 1250},
            },
            {
                "id": "dev_action",
                "label": "Intermediate Developer",
                "bbox": {"x": 632, "y": 457, "w": 769, "h": 236},
                "click_point": {"x": 1016, "y": 575},
            },
            {
                "id": "support_action",
                "label": "Application Support Engineer",
                "bbox": {"x": 632, "y": 704, "w": 769, "h": 259},
                "click_point": {"x": 1016, "y": 833},
            },
            {
                "id": "page_shell_action",
                "label": "Jobs on SEEK - New Zealand's no. 1 Employment, Career and Recruitment site",
                "bbox": {"x": 12, "y": 80, "w": 2536, "h": 1308},
                "click_point": {"x": 1280, "y": 734},
            },
        ],
        "page_elements": [
            {"id": "saved_text", "text": "Saved searches", "bbox": {"x": 1140, "y": 560, "w": 180, "h": 24}},
            {"id": "saved_noise", "text": "Use the Save search button below the search results", "bbox": {"x": 1168, "y": 640, "w": 300, "h": 24}},
            {"id": "compensation_text", "text": "What compensation range are you targeting?", "bbox": {"x": 1168, "y": 1012, "w": 300, "h": 24}},
            {"id": "next_text", "text": "Next", "bbox": {"x": 1320, "y": 1240, "w": 64, "h": 24}},
            {"id": "dev_title", "text": "Intermediate Developer", "bbox": {"x": 653, "y": 470, "w": 260, "h": 24}},
            {"id": "dev_company", "text": "Enlighten Designs Ltd", "bbox": {"x": 653, "y": 505, "w": 220, "h": 24}},
            {"id": "dev_type", "text": "Full time", "bbox": {"x": 653, "y": 535, "w": 100, "h": 24}},
            {"id": "dev_location", "text": "Hamilton Central, Waikato (Hybrid)", "bbox": {"x": 653, "y": 565, "w": 310, "h": 24}},
            {"id": "support_title", "text": "Application Support Engineer", "bbox": {"x": 653, "y": 725, "w": 310, "h": 24}},
            {"id": "support_company", "text": "Westpac New Zealand Limited", "bbox": {"x": 653, "y": 760, "w": 260, "h": 24}},
            {"id": "support_type", "text": "Full time", "bbox": {"x": 653, "y": 790, "w": 100, "h": 24}},
            {"id": "support_location", "text": "Auckland CBD, Auckland (Hybrid)", "bbox": {"x": 653, "y": 820, "w": 300, "h": 24}},
        ],
        "cards": [
            {
                "id": "saved_card",
                "label": "Saved searches section",
                "bbox": {"x": 1140, "y": 600, "w": 356, "h": 200},
                "primary_action_id": "saved_action",
                "child_action_ids": ["saved_action"],
                "child_page_element_ids": ["saved_text", "saved_noise"],
            },
            {
                "id": "compensation_card",
                "label": "Compensation range selector",
                "bbox": {"x": 1140, "y": 1000, "w": 356, "h": 200},
                "primary_action_id": "compensation_action",
                "child_action_ids": ["compensation_action"],
                "child_page_element_ids": ["compensation_text"],
            },
            {
                "id": "next_card",
                "label": "Next button",
                "bbox": {"x": 1140, "y": 1200, "w": 356, "h": 100},
                "primary_action_id": "next_action",
                "child_action_ids": ["next_action"],
                "child_page_element_ids": ["next_text"],
            },
            {
                "id": "dev_card",
                "label": "Intermediate Developer",
                "bbox": {"x": 632, "y": 457, "w": 769, "h": 236},
                "primary_action_id": "dev_action",
                "child_action_ids": ["dev_action"],
                "child_page_element_ids": ["dev_title", "dev_company", "dev_type", "dev_location"],
            },
            {
                "id": "support_card",
                "label": "Application Support Engineer",
                "bbox": {"x": 632, "y": 704, "w": 769, "h": 259},
                "primary_action_id": "support_action",
                "child_action_ids": ["page_shell_action", "support_action"],
                "child_page_element_ids": ["support_title", "support_company", "support_type", "support_location"],
            },
        ],
    }

    result = extract_seek_job_cards({"image_size": {"width": 2560, "height": 1400}, "screen_inventory": inventory})

    assert [job["title"] for job in result["jobs"]] == ["Intermediate Developer", "Application Support Engineer"]
    assert result["results_list_container"]["bbox"]["x"] >= 600
    assert result["results_list_container"]["bbox"]["w"] < 900


def test_extract_seek_job_cards_ignores_full_window_cards_when_inferring_container() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "action_window",
                "label": "Software Engineer Jobs in All Auckland - Microsoft Edge",
                "bbox": {"x": 0, "y": 0, "w": 2560, "h": 1400},
                "click_point": {"x": 1280, "y": 700},
                "role": "window",
            },
            {
                "id": "action_toggle",
                "label": "Strong applicant jobs toggle",
                "bbox": {"x": 490, "y": 620, "w": 370, "h": 80},
                "click_point": {"x": 675, "y": 660},
                "role": "toggle",
            },
            {
                "id": "action_job_1",
                "label": "Technical Application Support Specialist",
                "bbox": {"x": 653, "y": 573, "w": 88, "h": 25},
                "click_point": {"x": 697, "y": 586},
            },
        ],
        "page_elements": [
            {"id": "title", "text": "Technical Application Support Specialist", "bbox": {"x": 653, "y": 573, "w": 280, "h": 25}},
            {"id": "company", "text": "Autoplay Automotive Ltd", "bbox": {"x": 653, "y": 635, "w": 240, "h": 25}},
            {"id": "location", "text": "Freemans Bay, Auckland", "bbox": {"x": 653, "y": 682, "w": 230, "h": 25}},
        ],
        "cards": [
            {
                "id": "card_window",
                "label": "Software Engineer Jobs in All Auckland, Job Vacancies - Jun 2026 | SEEK - Microsoft Edge",
                "bbox": {"x": 0, "y": 0, "w": 2560, "h": 1400},
                "role": "window",
                "primary_action_id": "action_window",
                "child_action_ids": ["action_window"],
                "child_page_element_ids": ["title", "company", "location"],
            },
            {
                "id": "card_search_results",
                "label": "Search Results",
                "bbox": {"x": 12, "y": 312, "w": 2521, "h": 12662},
                "role": "group",
                "primary_action_id": None,
                "child_action_ids": [],
                "child_page_element_ids": ["title", "company", "location"],
            },
            {
                "id": "card_toggle",
                "label": "Strong applicant jobs toggle",
                "bbox": {"x": 490, "y": 620, "w": 370, "h": 80},
                "role": "toggle",
                "primary_action_id": "action_toggle",
                "child_action_ids": ["action_toggle"],
                "child_page_element_ids": [],
            },
            {
                "id": "card_job",
                "label": "Technical Application Support Specialist",
                "bbox": {"x": 632, "y": 529, "w": 475, "h": 409},
                "primary_action_id": "action_job_1",
                "child_action_ids": ["action_job_1"],
                "child_page_element_ids": ["title", "company", "location"],
            },
        ],
    }

    result = extract_seek_job_cards({"image_size": {"width": 2560, "height": 1400}, "screen_inventory": inventory})

    assert result["summary"]["jobs_seen"] == 1
    assert result["jobs"][0]["title"] == "Technical Application Support Specialist"
    assert result["results_list_container"]["bbox"]["x"] >= 600
    assert result["results_list_container"]["bbox"]["w"] < 600


def test_extract_seek_job_cards_rejects_strong_applicant_filter_card() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "filter_toggle",
                "label": "Filter: Strong applicant jobs",
                "bbox": {"x": 480, "y": 620, "w": 400, "h": 80},
                "click_point": {"x": 680, "y": 660},
                "role": "toggle",
            }
        ],
        "page_elements": [
            {"id": "salary_noise", "text": "$60,000 - $70,000 annual subj to Exp and", "bbox": {"x": 652, "y": 700, "w": 260, "h": 24}},
            {"id": "location_noise", "text": "Freemans Bay, Auckland", "bbox": {"x": 652, "y": 730, "w": 230, "h": 24}},
        ],
        "cards": [
            {
                "id": "card_filter",
                "label": "Filter: Strong applicant jobs",
                "bbox": {"x": 480, "y": 620, "w": 400, "h": 80},
                "role": "toggle",
                "primary_action_id": "filter_toggle",
                "child_action_ids": ["filter_toggle"],
                "child_page_element_ids": ["salary_noise", "location_noise"],
            }
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 0


def test_extract_seek_job_card_gets_company_when_uia_title_appears_after_ocr_texts() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [
            {
                "id": "action_uia_job",
                "label": "Technical Application Support Specialist",
                "bbox": {"x": 653, "y": 573, "w": 88, "h": 25},
                "click_point": {"x": 697, "y": 586},
            }
        ],
        "page_elements": [
            {"id": "title_a", "text": "Technical ApplicationSupport", "bbox": {"x": 653, "y": 529, "w": 250, "h": 25}},
            {"id": "title_b", "text": "Specialist", "bbox": {"x": 653, "y": 573, "w": 88, "h": 25}},
            {"id": "logo", "text": "CUtOPLAY", "bbox": {"x": 877, "y": 600, "w": 90, "h": 25}},
            {"id": "company", "text": "Autoplay Automotive Ltd", "bbox": {"x": 653, "y": 635, "w": 240, "h": 25}},
            {"id": "location", "text": "Freemans Bay, Auckland", "bbox": {"x": 653, "y": 682, "w": 230, "h": 25}},
        ],
        "cards": [
            {
                "id": "card_job",
                "label": "hyperlink",
                "bbox": {"x": 632, "y": 529, "w": 475, "h": 409},
                "primary_action_id": "action_uia_job",
                "child_action_ids": ["action_uia_job"],
                "child_page_element_ids": ["title_a", "title_b", "logo", "company", "location"],
            }
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 1
    job = result["jobs"][0]
    assert job["title"] == "Technical Application Support Specialist"
    assert job["company"] == "Autoplay Automotive Ltd"
    assert job["location"] == "Freemans Bay, Auckland"


def test_extract_seek_job_card_does_not_treat_company_with_new_zealand_as_location() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [],
        "page_elements": [
            {"id": "title", "text": "Senior Android Developer", "bbox": {"x": 652, "y": 966, "w": 231, "h": 24}},
            {"id": "company", "text": "Fiserv New Zealand Limited", "bbox": {"x": 652, "y": 998, "w": 231, "h": 24}},
        ],
        "cards": [],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 0


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


def test_extract_seek_job_detail_infers_right_drawer_and_excludes_homepage_sidebar() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [
            {"id": "apply", "label": "Apply for Intermediate Developer at Enlighten Designs Ltd", "bbox": {"x": 1680, "y": 852, "w": 146, "h": 49}},
            {"id": "save", "label": "Save Intermediate Developer at Enlighten Designs Ltd", "bbox": {"x": 1841, "y": 852, "w": 87, "h": 49}},
            {"id": "match", "label": "How you match", "bbox": {"x": 1712, "y": 975, "w": 127, "h": 22}},
        ],
        "page_elements": [
            {"id": "saved", "text": "Saved searches", "bbox": {"x": 1445, "y": 414, "w": 164, "h": 33}},
            {"id": "compensation", "text": "What compensation range are you targeting?", "bbox": {"x": 1467, "y": 767, "w": 250, "h": 31}},
            {"id": "title", "text": "Intermediate Developer", "bbox": {"x": 1680, "y": 609, "w": 288, "h": 33}},
            {"id": "company", "text": "Enlighten Designs Ltd View all jobs", "bbox": {"x": 1680, "y": 652, "w": 260, "h": 20}},
            {"id": "location", "text": "Hamilton Central, Waikato (Hybrid)", "bbox": {"x": 1712, "y": 691, "w": 247, "h": 20}},
            {
                "id": "classification",
                "text": "Developers/Programmers (Information & Communication Technology)",
                "bbox": {"x": 1712, "y": 726, "w": 491, "h": 20},
            },
            {"id": "work_type", "text": "Full time", "bbox": {"x": 1712, "y": 761, "w": 61, "h": 20}},
            {"id": "posted", "text": "Posted 1d ago · Medium application volume", "bbox": {"x": 1680, "y": 804, "w": 315, "h": 20}},
            {"id": "apply_text", "text": "Quick apply", "bbox": {"x": 1701, "y": 862, "w": 104, "h": 31}},
            {"id": "match_text", "text": "4 skills and credentials match your profile", "bbox": {"x": 1707, "y": 1002, "w": 297, "h": 26}},
            {"id": "body_heading", "text": "The step up that actually matters", "bbox": {"x": 1677, "y": 1211, "w": 274, "h": 26}},
            {"id": "body", "text": "There's a moment in every developer's career where the job changes.", "bbox": {"x": 1680, "y": 1251, "w": 744, "h": 71}},
            {"id": "questions", "text": "Employer questions", "bbox": {"x": 1680, "y": 1328, "w": 240, "h": 31}},
            {
                "id": "work_rights_question",
                "text": "Do you have a legal right to work in New Zealand?",
                "bbox": {"x": 1680, "y": 1364, "w": 520, "h": 20},
            },
            {"id": "featured_heading", "text": "Featured jobs", "bbox": {"x": 1680, "y": 1420, "w": 180, "h": 31}},
            {"id": "featured_job", "text": "Intermediate PHP Developer", "bbox": {"x": 1680, "y": 1465, "w": 250, "h": 20}},
        ],
    }

    detail = extract_seek_job_detail({"image_size": {"width": 2560, "height": 1400}, "screen_inventory": inventory})

    assert detail["detail_container"]["sources"] == ["seek_detail_drawer_anchor_bbox"]
    assert detail["detail_container"]["bbox"]["x"] >= 1600
    safe_point = detail["detail_container"]["safe_points"][0]
    bbox = detail["detail_container"]["bbox"]
    assert bbox["x"] <= safe_point["x"] <= bbox["x"] + bbox["w"]
    assert bbox["y"] <= safe_point["y"] <= bbox["y"] + bbox["h"]
    assert detail["title"] == "Intermediate Developer"
    assert detail["company"] == "Enlighten Designs Ltd"
    assert detail["apply_button_state"]["visible"] is True
    assert "Saved searches" not in detail["evidence"]["texts"]
    assert "What compensation range are you targeting?" not in detail["evidence"]["texts"]
    assert "Employer questions" in detail["evidence"]["texts"]
    assert "Do you have a legal right to work in New Zealand?" in detail["evidence"]["texts"]
    assert "Featured jobs" not in detail["evidence"]["texts"]
    assert "Intermediate PHP Developer" not in detail["evidence"]["texts"]


def test_extract_seek_job_detail_clamps_wide_drawer_left_edge() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [
            {
                "id": "apply",
                "label": "Apply for Application Support Engineer at Westpac New Zealand Limited",
                "bbox": {"x": 1680, "y": 890, "w": 146, "h": 49},
            },
        ],
        "page_elements": [
            {"id": "saved_jobs", "text": "later. You can then access them on all your devices.", "bbox": {"x": 1460, "y": 620, "w": 330, "h": 48}},
            {"id": "title", "text": "Application Support Engineer", "bbox": {"x": 1680, "y": 615, "w": 330, "h": 33}},
            {"id": "company", "text": "Westpac New Zealand Limited View all jobs", "bbox": {"x": 1680, "y": 658, "w": 350, "h": 20}},
            {"id": "location", "text": "Auckland CBD, Auckland (Hybrid)", "bbox": {"x": 1712, "y": 702, "w": 247, "h": 20}},
            {"id": "match", "text": "3 skills and credentials match your profile", "bbox": {"x": 1540, "y": 1010, "w": 360, "h": 26}},
            {"id": "body", "text": "As an Application Support Engineer, you will support the team.", "bbox": {"x": 1680, "y": 1210, "w": 740, "h": 44}},
        ],
    }

    detail = extract_seek_job_detail({"image_size": {"width": 2560, "height": 1400}, "screen_inventory": inventory})

    assert detail["detail_container"]["bbox"]["x"] >= int(2560 * 0.62)
    assert detail["company"] == "Westpac New Zealand Limited"
    assert "later. You can then access them on all your devices." not in detail["evidence"]["texts"]


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


def test_extract_seek_job_cards_prefers_precise_synthetic_candidate_over_generic_spanning_card() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "available_actions": [
            {
                "id": "generic_job_listing",
                "label": "Job listing",
                "bbox": {"x": 480, "y": 760, "w": 400, "h": 480},
                "click_point": {"x": 680, "y": 1000},
            }
        ],
        "page_elements": [
            {"id": "other_title", "text": "SeniorAndroid Developer", "bbox": {"x": 652, "y": 925, "w": 231, "h": 24}},
            {"id": "other_company", "text": "Fiserv New Zealand Limited", "bbox": {"x": 652, "y": 960, "w": 240, "h": 24}},
            {"id": "other_location", "text": "Auckland CBD, Auckland", "bbox": {"x": 652, "y": 995, "w": 240, "h": 24}},
            {"id": "title", "text": "Software Engineer", "bbox": {"x": 649, "y": 1030, "w": 180, "h": 24}},
            {"id": "company", "text": "ANZ Bank New Zealand Limited", "bbox": {"x": 649, "y": 1065, "w": 260, "h": 24}},
            {"id": "location", "text": "Auckland CBD, Auckland", "bbox": {"x": 649, "y": 1100, "w": 240, "h": 24}},
        ],
        "cards": [
            {
                "id": "generic_spanning_card",
                "label": "Job listing",
                "bbox": {"x": 480, "y": 760, "w": 400, "h": 480},
                "primary_action_id": "generic_job_listing",
                "child_action_ids": ["generic_job_listing"],
                "child_page_element_ids": ["other_title", "other_company", "other_location", "title", "company", "location"],
            }
        ],
    }

    result = extract_seek_job_cards(inventory)

    jobs = result["jobs"]
    software = next(job for job in jobs if job["title"] == "Software Engineer")
    assert software["company"] == "ANZ Bank New Zealand Limited"
    assert software["source_card_id"].startswith("synthetic_results_text")
    assert software["click_point"]["y"] < 1060


def test_extract_seek_job_cards_extends_results_bbox_from_visible_column_text_when_model_cards_are_missing() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [
            {
                "id": "action_android",
                "label": "Senior Android Developer",
                "bbox": {"x": 632, "y": 529, "w": 475, "h": 206},
                "click_point": {"x": 869, "y": 632},
            }
        ],
        "page_elements": [
            {"id": "android_title", "text": "Senior Android Developer", "bbox": {"x": 653, "y": 547, "w": 217, "h": 27}},
            {"id": "android_company", "text": "Fiserv New Zealand Limited", "bbox": {"x": 653, "y": 576, "w": 250, "h": 24}},
            {"id": "android_location", "text": "Auckland CBD, Auckland", "bbox": {"x": 653, "y": 611, "w": 220, "h": 24}},
            {"id": "cloud_title", "text": "Cloud Engineer", "bbox": {"x": 653, "y": 762, "w": 135, "h": 31}},
            {"id": "cloud_company", "text": "Datacom", "bbox": {"x": 653, "y": 790, "w": 81, "h": 26}},
            {"id": "cloud_location", "text": "Auckland CBD, Auckland (Hybrid)", "bbox": {"x": 653, "y": 822, "w": 280, "h": 24}},
            {"id": "software_title", "text": "Software Engineer", "bbox": {"x": 653, "y": 1094, "w": 159, "h": 28}},
            {"id": "software_company", "text": "ANZ Bank New Zealand Limited", "bbox": {"x": 654, "y": 1122, "w": 261, "h": 22}},
            {"id": "software_location", "text": "Auckland CBD, Auckland", "bbox": {"x": 654, "y": 1154, "w": 220, "h": 22}},
        ],
        "cards": [
            {
                "id": "android_card",
                "label": "Senior Android Developer",
                "bbox": {"x": 632, "y": 529, "w": 475, "h": 206},
                "primary_action_id": "action_android",
                "child_action_ids": ["action_android"],
                "child_page_element_ids": ["android_title", "android_company", "android_location"],
            }
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 3
    assert [job["title"] for job in result["jobs"]] == [
        "Senior Android Developer",
        "Cloud Engineer",
        "Software Engineer",
    ]
    assert result["results_list_container"]["bbox"]["h"] > 600


def test_extract_seek_job_cards_rejects_model_card_when_label_conflicts_with_child_title() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [
            {
                "id": "action_screen_9_senior-android-developer-job-card",
                "label": "Senior Android Developer job card",
                "bbox": {"x": 498, "y": 760, "w": 362, "h": 320},
                "click_point": {"x": 679, "y": 920},
            },
            {
                "id": "action_uia_145_senior-android-developer",
                "label": "Senior Android Developer",
                "bbox": {"x": 632, "y": 529, "w": 475, "h": 239},
                "click_point": {"x": 869, "y": 648},
            },
        ],
        "page_elements": [
            {"id": "cloud_title", "text": "Cloud Engineer", "bbox": {"x": 652, "y": 795, "w": 180, "h": 24}},
            {"id": "cloud_company", "text": "Datacom", "bbox": {"x": 652, "y": 830, "w": 120, "h": 24}},
            {"id": "cloud_location", "text": "Auckland CBD, Auckland (Hybrid)", "bbox": {"x": 652, "y": 865, "w": 260, "h": 24}},
            {"id": "android_title", "text": "SeniorAndroid Developer", "bbox": {"x": 652, "y": 555, "w": 231, "h": 24}},
            {"id": "android_company", "text": "Fiserv New Zealand Limited", "bbox": {"x": 652, "y": 590, "w": 240, "h": 24}},
            {"id": "android_location", "text": "Auckland CBD, Auckland", "bbox": {"x": 652, "y": 625, "w": 240, "h": 24}},
        ],
        "cards": [
            {
                "id": "card_2_senior-android-developer-job-card",
                "label": "Senior Android Developer job card",
                "bbox": {"x": 498, "y": 760, "w": 362, "h": 320},
                "primary_action_id": "action_screen_9_senior-android-developer-job-card",
                "child_action_ids": ["action_screen_9_senior-android-developer-job-card"],
                "child_page_element_ids": ["cloud_title", "cloud_company", "cloud_location"],
            },
            {
                "id": "card_14_hyperlink",
                "label": "Hyperlink",
                "bbox": {"x": 632, "y": 529, "w": 475, "h": 239},
                "primary_action_id": "action_uia_145_senior-android-developer",
                "child_action_ids": ["action_uia_145_senior-android-developer"],
                "child_page_element_ids": ["android_title", "android_company", "android_location"],
            },
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert all(job["source_card_id"] != "card_2_senior-android-developer-job-card" for job in result["jobs"])
    assert any(job["title"] == "Senior Android Developer" for job in result["jobs"])


def test_extract_seek_job_cards_keeps_plain_title_card_with_cross_pane_child_noise() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 1200, "height": 1000},
        "available_actions": [],
        "page_elements": [
            {"id": "detail_title", "text": "Senior Backend Developer", "bbox": {"x": 520, "y": 440, "w": 300, "h": 28}},
            {"id": "detail_company", "text": "Example Systems", "bbox": {"x": 520, "y": 490, "w": 220, "h": 24}},
            {"id": "detail_location", "text": "Auckland CBD, Auckland", "bbox": {"x": 520, "y": 535, "w": 220, "h": 24}},
        ],
        "cards": [
            {
                "id": "left_card_job_1",
                "label": "Software Engineer (Test Systems)",
                "bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
                "primary_action_id": None,
                "child_action_ids": [],
                "child_page_element_ids": ["detail_title", "detail_company", "detail_location"],
            }
        ],
    }

    result = extract_seek_job_cards(inventory)

    assert result["summary"]["jobs_seen"] == 1
    assert result["jobs"][0]["title"] == "Software Engineer (Test Systems)"


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


def test_extract_seek_job_detail_does_not_use_match_skill_as_company() -> None:
    detail_bbox = {"x": 1134, "y": 280, "w": 896, "h": 1104}
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [
            {
                "id": "quick_apply",
                "label": "Quick apply",
                "bbox": {"x": 1191, "y": 1005, "w": 104, "h": 31},
                "click_point": {"x": 1243, "y": 1020},
            }
        ],
        "page_elements": [
            {"id": "brand_logo", "text": "DATACOM", "bbox": {"x": 1168, "y": 650, "w": 180, "h": 40}},
            {"id": "title", "text": "Cloud Engineer", "bbox": {"x": 1168, "y": 760, "w": 220, "h": 34}},
            {"id": "company", "text": "Datacom View all jobs", "bbox": {"x": 1168, "y": 807, "w": 260, "h": 24}},
            {"id": "location", "text": "Auckland CBD, Auckland (Hybrid)", "bbox": {"x": 1168, "y": 850, "w": 320, "h": 24}},
            {
                "id": "classification",
                "text": "Engineering - Software (Information & Communication Technology)",
                "bbox": {"x": 1168, "y": 890, "w": 620, "h": 24},
            },
            {"id": "work_type", "text": "Fulltime", "bbox": {"x": 1168, "y": 930, "w": 130, "h": 24}},
            {"id": "posted", "text": "Posted 2d ago · Medium application volume", "bbox": {"x": 1168, "y": 965, "w": 380, "h": 24}},
            {"id": "apply_text", "text": "Quick apply", "bbox": {"x": 1191, "y": 1005, "w": 104, "h": 31}},
            {"id": "match_title", "text": "How you match", "bbox": {"x": 1168, "y": 1126, "w": 180, "h": 24}},
            {
                "id": "match_text",
                "text": "1 skill or credential matches your profile",
                "bbox": {"x": 1168, "y": 1160, "w": 360, "h": 24},
            },
            {"id": "skill", "text": "Amazon Web Services", "bbox": {"x": 1190, "y": 1200, "w": 240, "h": 24}},
        ],
    }
    scroll_containers = {
        "contract_version": "scroll_containers_v1",
        "containers": [{"container_id": "seek:job_detail", "bbox": detail_bbox}],
    }

    detail = extract_seek_job_detail(inventory, scroll_containers=scroll_containers)

    assert detail["title"] == "Cloud Engineer"
    assert detail["company"] == "Datacom"
    assert detail["location"] == "Auckland CBD, Auckland (Hybrid)"


def test_extract_seek_job_detail_reads_company_after_sticky_header_buttons() -> None:
    detail_bbox = {"x": 1134, "y": 280, "w": 896, "h": 1104}
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [
            {"id": "quick_apply", "label": "Quick apply button", "bbox": {"x": 1308, "y": 530, "w": 104, "h": 40}},
            {"id": "save", "label": "Save button", "bbox": {"x": 1436, "y": 530, "w": 34, "h": 40}},
        ],
        "page_elements": [
            {"id": "title", "text": "Cloud Engineer", "bbox": {"x": 1168, "y": 364, "w": 180, "h": 28}},
            {"id": "quick_apply_text", "text": "Quick apply", "bbox": {"x": 1308, "y": 530, "w": 104, "h": 40}},
            {"id": "save_text", "text": "Save", "bbox": {"x": 1436, "y": 530, "w": 34, "h": 40}},
            {"id": "company", "text": "Datacom", "bbox": {"x": 1168, "y": 394, "w": 90, "h": 20}},
            {
                "id": "responsibility",
                "text": "·Providing technical support remotely via phone, email, or online systems to meet service response times",
                "bbox": {"x": 1168, "y": 760, "w": 720, "h": 40},
            },
            {"id": "section", "text": "Our Why", "bbox": {"x": 1168, "y": 640, "w": 130, "h": 24}},
            {
                "id": "body",
                "text": "Datacom works with organisations and communities across Australia and New Zealand.",
                "bbox": {"x": 1168, "y": 684, "w": 720, "h": 40},
            },
        ],
    }
    scroll_containers = {
        "contract_version": "scroll_containers_v1",
        "containers": [{"container_id": "seek:job_detail", "bbox": detail_bbox}],
    }

    detail = extract_seek_job_detail(inventory, scroll_containers=scroll_containers)

    assert detail["title"] == "Cloud Engineer"
    assert detail["company"] == "Datacom"
    assert detail["location"] is None
    assert detail["work_type"] is None


def test_extract_seek_job_detail_ignores_close_icon_as_company() -> None:
    detail_bbox = {"x": 1134, "y": 280, "w": 896, "h": 1104}
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [
            {"id": "quick_apply", "label": "Quick apply button", "bbox": {"x": 1308, "y": 530, "w": 180, "h": 48}},
        ],
        "page_elements": [
            {
                "id": "title",
                "text": "Intermediate Engineer - AI Automation & Integration",
                "bbox": {"x": 1168, "y": 364, "w": 640, "h": 32},
            },
            {"id": "close", "text": "X", "bbox": {"x": 2240, "y": 318, "w": 24, "h": 24}},
            {"id": "company", "text": "Inde Technology", "bbox": {"x": 1168, "y": 410, "w": 190, "h": 24}},
            {"id": "location", "text": "Auckland CBD, Auckland (Hybrid)", "bbox": {"x": 1168, "y": 454, "w": 320, "h": 24}},
        ],
    }
    scroll_containers = {
        "contract_version": "scroll_containers_v1",
        "containers": [{"container_id": "seek:job_detail", "bbox": detail_bbox}],
    }

    detail = extract_seek_job_detail(inventory, scroll_containers=scroll_containers)

    assert detail["title"] == "Intermediate Engineer - AI Automation & Integration"
    assert detail["company"] == "Inde Technology"
    assert detail["company"] != "X"


def test_extract_seek_job_detail_prefers_location_after_title_over_search_filter() -> None:
    inventory = {
        "contract_version": "screen_inventory_v1",
        "image_size": {"width": 2560, "height": 1400},
        "available_actions": [],
        "page_elements": [
            {"id": "filter_location", "text": "All Auckland", "bbox": {"x": 1500, "y": 180, "w": 160, "h": 24}},
            {"id": "title", "text": "Senior Android Developer", "bbox": {"x": 1160, "y": 760, "w": 300, "h": 32}},
            {"id": "company", "text": "Fiserv New Zealand Limited View all jobs", "bbox": {"x": 1160, "y": 805, "w": 330, "h": 24}},
            {"id": "location", "text": "Auckland CBD, Auckland", "bbox": {"x": 1160, "y": 850, "w": 260, "h": 24}},
            {
                "id": "classification",
                "text": "Developers/Programmers (Information & Communication Technology)",
                "bbox": {"x": 1160, "y": 900, "w": 540, "h": 24},
            },
            {"id": "work_type", "text": "Full time", "bbox": {"x": 1160, "y": 945, "w": 120, "h": 24}},
        ],
    }

    detail = extract_seek_job_detail(inventory)

    assert detail["title"] == "Senior Android Developer"
    assert detail["company"] == "Fiserv New Zealand Limited"
    assert detail["location"] == "Auckland CBD, Auckland"
