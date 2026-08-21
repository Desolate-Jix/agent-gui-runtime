from __future__ import annotations

from pathlib import Path


SKILL_PATH = Path(__file__).parents[1] / "SKILL.md"
SCENARIOS_PATH = Path(__file__).with_name("SCENARIOS.md")


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_frontmatter_description_only_declares_trigger_conditions() -> None:
    text = _skill_text()
    description = next(
        line.removeprefix("description: ")
        for line in text.splitlines()
        if line.startswith("description: ")
    )

    assert description.startswith("Use when ")
    assert "automatic per-slice commits" in description
    assert "rollback checkpoints" in description
    assert "keeping push" not in description


def test_checkpoint_flow_forbids_destructive_git_even_when_separately_requested() -> None:
    text = _skill_text()

    assert "在本 Skill 的自动 checkpoint 流程中绝不执行" in text
    assert "停止 checkpoint 流程并将其作为独立任务处理" in text
    assert "未经用户针对该操作明确授权，不得使用" not in text
    for command in (
        "git reset --hard",
        "git clean",
        "git push --force",
        "git push --force-with-lease",
    ):
        assert command in text


def test_skill_preserves_atomic_validation_and_push_boundaries() -> None:
    text = _skill_text()

    for required in (
        "git add -- <explicit paths>",
        "git diff --cached --check",
        "测试失败不得创建声称完成的 commit",
        "自动 commit 不等于自动 push",
        "git revert <commit>",
        "Final report ledger",
    ):
        assert required in text


def test_reusable_pressure_scenarios_cover_checkpoint_failure_modes() -> None:
    text = SCENARIOS_PATH.read_text(encoding="utf-8")

    for required in (
        "Inherited dirty sentinel",
        "Focused test failure",
        "Mixed ownership in one hunk",
        "Shortcut pressure",
        "zero completion commit",
        "no push",
    ):
        assert required in text
