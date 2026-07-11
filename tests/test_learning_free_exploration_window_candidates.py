from scripts.report_learning_free_exploration_window_candidates import (
    build_window_candidate_gate,
    classify_window_candidate,
)


def test_window_candidate_classification_blocks_panel_chatgpt_and_protected_windows() -> None:
    protected = classify_window_candidate({"title": "Welcome to Python.org - Microsoft Edge", "process_name": "msedge.exe"})
    panel = classify_window_candidate({"title": "127.0.0.1:8000/panel?stage=learn_replay", "process_name": "msedge.exe"})
    control = classify_window_candidate({"title": "ChatGPT", "process_name": "msedge.exe"})
    overlay = classify_window_candidate({"title": "NVIDIA GeForce Overlay", "process_name": "NVIDIA Overlay.exe"})
    candidate = classify_window_candidate({"title": "Untitled - Notepad", "process_name": "notepad.exe"})

    assert protected["candidate_for_free_exploration_capture"] is False
    assert protected["classification"] == "protected_baseline_window"
    assert panel["candidate_for_free_exploration_capture"] is False
    assert panel["classification"] == "panel_self_observation_window"
    assert control["candidate_for_free_exploration_capture"] is False
    assert control["classification"] == "control_or_review_window"
    assert overlay["candidate_for_free_exploration_capture"] is False
    assert overlay["classification"] == "system_or_overlay_window"
    assert candidate["candidate_for_free_exploration_capture"] is True
    assert candidate["classification"] == "usable_non_protected_window"


def test_window_candidate_gate_blocks_when_only_forbidden_windows_exist() -> None:
    items = [
        classify_window_candidate({"title": "ChatGPT", "process_name": "msedge.exe"}),
        classify_window_candidate({"title": "Apple Music", "process_name": "AppleMusic.exe"}),
    ]

    gate = build_window_candidate_gate(items)

    assert gate["allowed"] is False
    assert gate["status"] == "blocked_until_target_window_available"
    assert gate["candidate_count"] == 0
    assert "no_usable_non_protected_visible_window" in gate["blockers"]


def test_window_candidate_gate_allows_real_non_protected_window() -> None:
    items = [
        classify_window_candidate({"title": "ChatGPT", "process_name": "msedge.exe"}),
        classify_window_candidate({"title": "Calculator", "process_name": "CalculatorApp.exe"}),
    ]

    gate = build_window_candidate_gate(items)

    assert gate["allowed"] is True
    assert gate["status"] == "ready_for_safe_bind_capture_observe"
    assert gate["candidate_count"] == 1
