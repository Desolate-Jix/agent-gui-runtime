"""VISTA 服务的精简指令不能丢掉调用方明确的字段/标签区分。"""
from app.vision.model_workers.vista_openai_server import _vista_prompt


def test_compact_prompt_preserves_named_target_constraints():
    goal = "搜索词"
    constraints = "Locate the editable input area, not its printed label."
    source = f"Locate target\nGoal: {goal}\nTarget constraints: {constraints}\nCandidates:\n- bbox=[1,2,3,4]"
    prompt = _vista_prompt(source)
    assert goal in prompt and constraints in prompt
    assert "bbox" not in prompt


def test_existing_single_goal_and_official_prefix_keep_behavior():
    plain = _vista_prompt("Goal: 查看示例详情")
    assert "查看示例详情" in plain
    assert _vista_prompt(plain) == plain
