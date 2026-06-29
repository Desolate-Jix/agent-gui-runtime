from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.prompts import (
    PromptRollbackRequest,
    PromptVersionSave,
    diff_agent_prompt_versions,
    get_agent_prompt,
    get_agent_prompt_version,
    list_agent_prompt_versions,
    list_agent_prompts,
    rollback_agent_prompt_version,
    save_agent_prompt_version,
)


def test_list_agent_prompts_includes_full_jd_review() -> None:
    prompts = list_agent_prompts()

    full_jd = next(item for item in prompts if item.get("prompt_id") == "job_suitability_full_jd_v1")
    assert full_jd["contract_version"] == "agent_prompt_template_v1"
    assert full_jd["output_contract"] == "job_suitability_decision_v1"
    assert full_jd["variable_count"] >= 3


def test_get_agent_prompt_loads_latest_template() -> None:
    prompt, path = get_agent_prompt("agent_next_action_agentic_loop_v1")

    assert path.name == "agent_next_action_agentic_loop_v1.json"
    assert prompt.output_contract == "agent_next_action_decision_v1"
    assert "screen_observation" in prompt.variables
    assert "PathGraph" in prompt.template


def test_save_agent_prompt_version_writes_new_version(tmp_path: Path) -> None:
    source = Path("artifacts/agent_prompts/job_suitability_full_jd_v1.json")
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    saved, path, trace_path = save_agent_prompt_version(
        "job_suitability_full_jd_v1",
        PromptVersionSave(
            template="新版 prompt {{full_job_detail_text}}",
            version="test_version",
            change_note="unit test",
        ),
        prompt_dir=prompt_dir,
    )

    assert path.name == "job_suitability_full_jd_v1__test_version.json"
    assert saved.version == "test_version"
    assert saved.template == "新版 prompt {{full_job_detail_text}}"
    assert Path(trace_path).exists()


def test_prompt_versions_and_diff_use_saved_versions(tmp_path: Path) -> None:
    source = Path("artifacts/agent_prompts/job_suitability_full_jd_v1.json")
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    save_agent_prompt_version(
        "job_suitability_full_jd_v1",
        PromptVersionSave(template="新版 prompt {{full_job_detail_text}}", version="candidate"),
        prompt_dir=prompt_dir,
    )

    versions = list_agent_prompt_versions("job_suitability_full_jd_v1", prompt_dir=prompt_dir)
    assert [item["version"] for item in versions] == ["2026-06-29.base", "candidate"]

    candidate, _path = get_agent_prompt_version("job_suitability_full_jd_v1", "candidate", prompt_dir=prompt_dir)
    assert candidate.template == "新版 prompt {{full_job_detail_text}}"

    diff = diff_agent_prompt_versions(
        "job_suitability_full_jd_v1",
        "2026-06-29.base",
        "candidate",
        prompt_dir=prompt_dir,
    )
    assert diff["contract_version"] == "agent_prompt_diff_v1"
    assert diff["changed"] is True
    assert "+新版 prompt {{full_job_detail_text}}" in diff["diff"]


def test_prompt_rollback_saves_target_template_as_new_version(tmp_path: Path) -> None:
    source = Path("artifacts/agent_prompts/job_suitability_full_jd_v1.json")
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    base, _base_path = get_agent_prompt_version("job_suitability_full_jd_v1", "2026-06-29.base", prompt_dir=prompt_dir)
    save_agent_prompt_version(
        "job_suitability_full_jd_v1",
        PromptVersionSave(template="broken prompt", version="broken"),
        prompt_dir=prompt_dir,
    )

    rolled_back, path, trace_path = rollback_agent_prompt_version(
        "job_suitability_full_jd_v1",
        PromptRollbackRequest(target_version="2026-06-29.base", new_version="rollback_base"),
        prompt_dir=prompt_dir,
    )

    assert path.name == "job_suitability_full_jd_v1__rollback_base.json"
    assert rolled_back.template == base.template
    assert Path(trace_path).exists()


def test_save_agent_prompt_version_rejects_duplicate(tmp_path: Path) -> None:
    source = Path("artifacts/agent_prompts/job_suitability_full_jd_v1.json")
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    request = PromptVersionSave(template="first", version="dup")
    save_agent_prompt_version("job_suitability_full_jd_v1", request, prompt_dir=prompt_dir)

    with pytest.raises(FileExistsError):
        save_agent_prompt_version("job_suitability_full_jd_v1", request, prompt_dir=prompt_dir)
