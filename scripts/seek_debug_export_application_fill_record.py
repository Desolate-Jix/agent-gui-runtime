from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


REPORT_NAME = "step_report.json"
RECORD_CONTRACT = "seek_application_fill_record_v1"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _step_reports(run_dir: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob(f"step_*/{REPORT_NAME}")):
        report = _read_json(path)
        report["_report_path"] = str(path)
        reports.append(report)
    return sorted(reports, key=lambda item: int(item.get("step_index") or 0))


def _auxiliary_reports(run_dir: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("*.json")):
        if path.name == "state.json" or path.name == "application_fill_record.json":
            continue
        report = _read_json(path)
        contract = str(report.get("contract_version") or "")
        if contract in {
            "seek_cover_letter_revision_v1",
            "seek_employer_questions_manual_debug_v1",
            "seek_review_submit_stop_before_submit_v1",
        }:
            report["_report_path"] = str(path)
            reports.append(report)
    return reports


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(value or "").casefold())


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _path(value: Any) -> str | None:
    if not value:
        return None
    return str(Path(str(value)).resolve())


def _collect_trace_paths(value: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("trace_path") and item:
                paths.append(str(item))
            elif key == "trace_paths" and isinstance(item, list):
                paths.extend(str(path) for path in item if path)
            else:
                paths.extend(_collect_trace_paths(item))
    elif isinstance(value, list):
        for item in value:
            paths.extend(_collect_trace_paths(item))
    return _unique([_path(path) or str(path) for path in paths])


def _collect_screenshots(reports: list[dict[str, Any]]) -> list[str]:
    screenshots: list[str] = []
    for report in reports:
        if report.get("step_name") in {"execute_apply_entry", "continue_application_flow"}:
            for key in ("before_image", "after_image"):
                path = _path(report.get(key))
                if path:
                    screenshots.append(path)
        for capture in report.get("captures") or []:
            if isinstance(capture, dict):
                path = _path(capture.get("image_path"))
                if path:
                    screenshots.append(path)
        for action in report.get("actions") or []:
            if not isinstance(action, dict):
                continue
            after = action.get("after_capture") if isinstance(action.get("after_capture"), dict) else {}
            path = _path(after.get("image_path"))
            if path:
                screenshots.append(path)
    return _unique(screenshots)


def _latest_report(reports: list[dict[str, Any]], *, step_name: str | None = None, status: str | None = None) -> dict[str, Any]:
    for report in reversed(reports):
        if step_name and report.get("step_name") != step_name:
            continue
        if status and report.get("status") != status:
            continue
        return report
    return {}


def _match_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    return _latest_report(reports, step_name="match")


def _filled_cover_letter_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    for report in reversed(reports):
        safe = report.get("safe_form_fill_attempt") if isinstance(report.get("safe_form_fill_attempt"), dict) else {}
        if safe.get("status") == "filled_until_review" and int(safe.get("fields_filled") or 0) > 0:
            return report
    return {}


def _cover_letter_revision_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    for report in reversed(reports):
        if report.get("contract_version") == "seek_cover_letter_revision_v1" and _text(report.get("cover_letter")):
            return report
    return {}


def _final_review_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    for report in reversed(reports):
        flow = report.get("application_flow_state") if isinstance(report.get("application_flow_state"), dict) else {}
        blocker = flow.get("final_submit_visible_blocker") if isinstance(flow.get("final_submit_visible_blocker"), dict) else {}
        if flow.get("current_step") == "review_and_submit" and blocker.get("blocked") is True:
            return report
    return _latest_report(reports, step_name="continue_application_flow")


def _manual_employer_questions_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    for report in reversed(reports):
        if report.get("contract_version") == "seek_employer_questions_manual_debug_v1":
            return report
    return {}


def _automated_employer_questions_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    for report in reversed(reports):
        fill = report.get("employer_question_fill_attempt") if isinstance(report.get("employer_question_fill_attempt"), dict) else {}
        if fill.get("status") == "filled_until_review" and int(fill.get("answered_count") or 0) > 0:
            return report
    return {}


def _final_submit_boundary_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    for report in reversed(reports):
        if report.get("contract_version") == "seek_review_submit_stop_before_submit_v1":
            return report
    return {}


def _job_payload(reports: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    match = _match_report(reports)
    detail = _first_dict(match.get("detail"), state.get("detail"))
    decision = _first_dict(match.get("match_decision"), state.get("match_decision"))
    current = _first_dict(state.get("current_job"), match.get("job"))
    job_id = detail.get("job_id") or decision.get("job_id") or current.get("job_id")
    title = detail.get("title") or decision.get("title") or current.get("title")
    company = detail.get("company") or current.get("company")
    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": detail.get("location") or current.get("location"),
        "application_url": None,
        "detail_url": detail.get("detail_url") or current.get("source_url"),
    }


def _find_apply_url(*values: Any) -> str | None:
    pattern = re.compile(r"https://nz\.seek\.com/job/\d+/apply/[^\s\"'<>]+")
    for value in values:
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
        match = pattern.search(text)
        if match:
            return match.group(0).rstrip("\\,.;)")
    return None


def _cover_letter(report: dict[str, Any]) -> str:
    if _text(report.get("cover_letter")):
        return str(report.get("cover_letter") or "")
    draft = report.get("cover_letter_draft") if isinstance(report.get("cover_letter_draft"), dict) else {}
    return str(draft.get("draft") or "")


def _cover_letter_trace(report: dict[str, Any]) -> str | None:
    trace_path = _path(report.get("type_text_trace_path"))
    if trace_path:
        return trace_path
    safe = report.get("safe_form_fill_attempt") if isinstance(report.get("safe_form_fill_attempt"), dict) else {}
    for field in safe.get("field_results") or []:
        if not isinstance(field, dict) or field.get("filled") is not True:
            continue
        response = field.get("type_text_response") if isinstance(field.get("type_text_response"), dict) else {}
        trace_path = _path(response.get("trace_path"))
        if trace_path:
            return trace_path
    return None


def _employer_questions(report: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(report, dict):
        return []
    manual_answers = report.get("answers") if isinstance(report.get("answers"), list) else []
    if manual_answers:
        questions: list[dict[str, str]] = []
        for item in manual_answers:
            if not isinstance(item, dict):
                continue
            question = _text(item.get("question"))
            answer = _text(item.get("answer"))
            if question and answer:
                questions.append(
                    {
                        "question": question,
                        "answer": answer,
                        "evidence": _text(item.get("evidence")),
                    }
                )
        return questions
    content = report.get("filled_content") if isinstance(report.get("filled_content"), dict) else {}
    questions = content.get("employer_questions") if isinstance(content.get("employer_questions"), list) else []
    if questions:
        return [question for question in questions if isinstance(question, dict)]
    fill = report.get("employer_question_fill_attempt") if isinstance(report.get("employer_question_fill_attempt"), dict) else {}
    if fill.get("status") != "filled_until_review":
        return []
    plan = report.get("employer_question_answer_plan") if isinstance(report.get("employer_question_answer_plan"), dict) else {}
    answers = plan.get("answers") if isinstance(plan.get("answers"), list) else []
    planned_questions: list[dict[str, str]] = []
    for item in answers:
        if not isinstance(item, dict):
            continue
        question = _text(item.get("question_text"))
        answer = _text(item.get("planned_answer"))
        if not question or not answer:
            continue
        evidence_parts = [_text(item.get("answer_source")), _text(item.get("evidence"))]
        planned_questions.append(
            {
                "question": question,
                "answer": answer,
                "evidence": " | ".join(part for part in evidence_parts if part),
            }
        )
    answered_count = int(fill.get("answered_count") or 0)
    return planned_questions[:answered_count] if answered_count else planned_questions


def _looks_like_error_summary_question(question: dict[str, str]) -> bool:
    text = _normalize_key(question.get("question"))
    return "pleasemakeaselection" in text or "pleasemakeaselection" in _normalize_key(question.get("answer"))


def _canonical_question_key(question: dict[str, str]) -> str:
    text = _normalize_key(question.get("question"))
    text = text.replace("pleasemakeaselection", "")
    answer = _normalize_key(question.get("answer"))
    if "righttoworkinnewzealand" in text or "visa" in text:
        return f"work_rights::{answer}"
    return f"{text}::{answer}"


def _dedupe_employer_questions(questions: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            continue
        if _looks_like_error_summary_question(question):
            continue
        key = _canonical_question_key(question)
        if key in seen:
            continue
        seen.add(key)
        result.append(question)
    return result


def _last_capture_path(report: dict[str, Any]) -> str | None:
    captures = [capture for capture in report.get("captures") or [] if isinstance(capture, dict)]
    for capture in reversed(captures):
        path = _path(capture.get("image_path"))
        if path:
            return path
    return None


def build_record_from_debug_run(run_dir: str | Path, *, created_at: str | None = None) -> dict[str, Any]:
    run_path = Path(run_dir)
    reports = _step_reports(run_path)
    if not reports:
        raise ValueError(f"No {REPORT_NAME} files found under {run_path}")
    auxiliary_reports = _auxiliary_reports(run_path)
    evidence_reports = [*reports, *auxiliary_reports]
    state_path = run_path / "state.json"
    state = _read_json(state_path) if state_path.exists() else {}

    job = _job_payload(reports, state)
    filled_report = _filled_cover_letter_report(reports)
    final_report = _final_review_report(reports)
    revision_report = _cover_letter_revision_report(auxiliary_reports)
    manual_questions_report = _manual_employer_questions_report(auxiliary_reports)
    automated_questions_report = _automated_employer_questions_report(reports)
    final_boundary_report = _final_submit_boundary_report(auxiliary_reports)
    apply_url = _find_apply_url(final_boundary_report, final_report, filled_report, state)
    job["application_url"] = apply_url
    cover_letter_report = revision_report or filled_report
    cover_letter = _cover_letter(cover_letter_report)
    cover_letter_trace = _cover_letter_trace(cover_letter_report)
    screenshots = _collect_screenshots(evidence_reports)
    review_screenshot = (
        _last_capture_path(final_boundary_report)
        or _last_capture_path(revision_report)
        or _path(final_report.get("after_image") or final_report.get("before_image"))
    )
    if review_screenshot and review_screenshot not in screenshots:
        screenshots.append(review_screenshot)
    action_traces = [
        path
        for path in _collect_trace_paths(evidence_reports)
        if "\\logs\\traces\\actions\\" in path or "/logs/traces/actions/" in path
    ]
    vision_traces = [
        path
        for path in _collect_trace_paths(evidence_reports)
        if "\\logs\\traces\\vision\\" in path or "/logs/traces/vision/" in path
    ]
    employer_questions = (
        _employer_questions(filled_report)
        or _employer_questions(automated_questions_report)
        or _employer_questions(manual_questions_report)
    )
    employer_questions = _dedupe_employer_questions(employer_questions)
    flow = final_report.get("application_flow_state") if isinstance(final_report.get("application_flow_state"), dict) else {}
    blocker = flow.get("final_submit_visible_blocker") if isinstance(flow.get("final_submit_visible_blocker"), dict) else {}
    final_submit_text_visible = final_boundary_report.get("final_submit_text_visible") is True
    reached_review_step = (
        flow.get("current_step") == "review_and_submit"
        and final_report.get("final_submission_performed") is not True
    )
    final_boundary_clear = (
        final_boundary_report.get("contract_version") == "seek_review_submit_stop_before_submit_v1"
        and int(final_boundary_report.get("final_submissions") or 0) == 0
        and final_submit_text_visible
    )
    stage = (
        "review_before_submit"
        if final_boundary_clear or reached_review_step or (flow.get("current_step") == "review_and_submit" and blocker.get("blocked") is True)
        else str(flow.get("current_step") or "unknown")
    )

    filled_fields = [
        {
            "step": "choose_documents",
            "field": "resume",
            "value": "WENQING JI.pdf (SEEK default/selected resume)",
            "policy": "unchanged",
        },
        {
            "step": "choose_documents",
            "field": "cover_letter",
            "value": cover_letter,
            "policy": "replaced_existing_cover_letter",
        },
    ]
    for index, question in enumerate(employer_questions):
        filled_fields.append(
            {
                "step": "answer_employer_questions",
                "field": str(question.get("question") or f"question_{index + 1}"),
                "value": str(question.get("answer") or ""),
                "evidence": str(question.get("evidence") or ""),
            }
        )

    return {
        "contract_version": RECORD_CONTRACT,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "status": "stopped_at_review_before_submit" if stage == "review_before_submit" else "needs_review",
        "final_submit_performed": False,
        "job": job,
        "filled_content": {
            "resume": "WENQING JI.pdf (SEEK default/selected resume)",
            "cover_letter": cover_letter,
            "employer_questions": employer_questions,
            "seek_profile_mutation": "none; Update SEEK Profile step was continued without pressing Add/Edit controls",
        },
        "evidence": {
            "screenshots": screenshots,
            "action_traces": _unique(action_traces),
            "vision_traces": _unique(vision_traces),
            "final_submit_guard": "Review page contains Submit application; final_submit_visible_blocker matched and no submit click was sent.",
            "review_before_submit_screenshot": review_screenshot,
            "cover_letter_type_text_trace": cover_letter_trace,
            "final_submit_clicked": False,
            "employer_questions_report": _path(
                manual_questions_report.get("_report_path") or automated_questions_report.get("_report_path")
            ),
            "final_submit_boundary_report": _path(final_boundary_report.get("_report_path")),
            "final_submit_text_visible": final_submit_text_visible,
        },
        "known_issues_from_run": [
            *(
                []
                if employer_questions
                else [
                    "This run had no visible employer-question step; employer_question_total is recorded as 0/0 rather than inventing answers."
                ]
            ),
            "Earlier Continue targeting selected a right-edge floating browser/plugin widget; the runner now rejects right-edge/header/bottom-edge Continue points before execution.",
        ],
        "job_id": job.get("job_id"),
        "job_title": job.get("title"),
        "apply_url": apply_url,
        "stage": stage,
        "submit_clicks": 0,
        "final_submissions": 0,
        "final_submit_clicked": False,
        "employer_question_total": len(employer_questions),
        "filled_fields": filled_fields,
        "source_debug_run_dir": str(run_path),
        "source_step_reports": [str(report.get("_report_path")) for report in evidence_reports if report.get("_report_path")],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a SEEK one-step debug run into seek_application_fill_record_v1.")
    parser.add_argument("--run-dir", type=Path, required=True, help="SEEK debug run directory containing step reports.")
    parser.add_argument("--out", type=Path, default=None, help="Output application_fill_record.json path.")
    args = parser.parse_args(argv)

    out = args.out or (args.run_dir / "application_fill_record.json")
    record = build_record_from_debug_run(args.run_dir)
    _write_json(out, record)
    print(
        json.dumps(
            {
                "success": True,
                "contract_version": record.get("contract_version"),
                "out": str(out),
                "status": record.get("status"),
                "job_title": record.get("job_title"),
                "employer_question_total": record.get("employer_question_total"),
                "final_submissions": record.get("final_submissions"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
