"""真实 Agent 文本旅程编排；复用现有面板和运行时，不含输入执行器。"""
import json

from tests.native_fixture_review_support import FixtureTextScope
from app.agent.text_parameters import ReviewedTextParameters, ReviewedTextSource


def run_text_journey(*, call_agent, human_step, result, identity, handle, target_pid, shared, task):
    preparations = []
    segment_id = None
    previous_batch = None
    previous_version = None
    for kind, value in zip(("literal", "variable"), FixtureTextScope.VALUES):
        prefix = "text-" + kind
        introduction = (f"先agent_link_status核对task_id={task}，start_learning_segment，"
            "idempotency_key=text-start-once,title=原生文本填写实机验收。" if segment_id is None else
            f"继续task_id={task},segment_id={segment_id}。读取get_fresh_learning_runtime的preparation_id={preparations[0]}，"
            "必须看到实际事后回执/截图及字段verified，不能把派发当成功。"
            f"get_interface_memory读取先前保存的interface_id={previous_batch},version_id={previous_version}，"
            "总结已保存的搜索词字段含义，不用旧历史资产；接下来仍从全新截图重新定位。")
        parameters = ReviewedTextParameters("fixture.searchQuery",
            ReviewedTextSource(kind, value if kind == "literal" else "search_term"), True, False).to_payload()
        before = "" if kind == "literal" else FixtureTextScope.VALUES[0]
        text_values = "" if kind == "literal" else f",text_values={json.dumps({'search_term': value}, ensure_ascii=False)}"
        prompt = (
            introduction + "只使用Agent Review MCP。不得审批或执行输入，不调用shell/web。"
            f"observe_learning_screen绑定application_identity={json.dumps(identity)},target_window_handle={handle},target_process_id={target_pid},"
            f"idempotency_key={prefix}-observe,title=本轮原生文本界面,meaning=搜索词字段的非提交填写,goal=null。"
            "阅读工具返回的原图，确认只有一个搜索词文本框和当前内容显示，没有提交按钮。"
            f"字段当前应为{json.dumps(before, ensure_ascii=False)}，若不符或识别不确定停止，不换目标。"
            "自主根据图片submit_observed_interface_learning保存界面及可见区域，不强制创建流程图。"
            "使用observe的同一batch_id和interface_memory确切expected_revision/expected_sha256；"
            "regions每项为bbox[x,y,w,h],name,kind,meaning,recognition_text，不虚构坐标或region_id。"
            f"idempotency_key={prefix}-learn。get_interface_memory核对保存的控件和含义。"
            f"prepare_fresh_learning_runtime使用同一segment_id,batch_id,idempotency_key={prefix}-prepare。"
            "只在observed之后request_fresh_learning_action："
            f"intent_id={prefix}-intent,action_id={prefix}-action,semantic_action=fill_field,goal=搜索词,"
            f"text_parameters={json.dumps(parameters, ensure_ascii=False)}{text_values}。"
            "这里fixture.searchQuery是本次字段逻辑身份，实际字段仍由截图、UIA与Gate核验。"
            "get_fresh_learning_runtime确认pending_review后结束本轮回应；测试操作员会核对完整新图和文本并独立确认。"
            "保持segment active，任何工具错误立即停止，绝不伪称执行成功。")
        calls = call_agent(prefix + "-preview", prompt, shared)
        if segment_id is None:
            starts = [c for c in calls if c["tool"] == "start_learning_segment"]
            assert len(starts) == 1
            segment_id = starts[0]["result"]["structured_content"]["segment_id"]
            result["segment_id"] = segment_id
        learned = [c for c in calls if c["tool"] == "submit_observed_interface_learning"]
        assert len(learned) == 1
        memory = learned[0]["result"]["structured_content"]
        previous_batch, previous_version = memory["interface_id"], memory["version_id"]
        prepared = [c for c in calls if c["tool"] == "prepare_fresh_learning_runtime"]
        assert len(prepared) == 1
        preparation = prepared[0]["result"]["structured_content"]
        assert preparation["phase"] == "observed"
        preparations.append(preparation["preparation_id"])
        human_step(prefix, {"state": "text", "value": value}, preparations[-1])
    call_agent("final-read", f"只读核对task={task},segment_id={segment_id}的两次真实填写回执preparation_id={json.dumps(preparations)}。"
        "检查固定/变量填写的字段verification和剪贴板恢复证据，不把缺失证据称为成功。"
        "get_learning_segment读取图同步情况，仅在子动作已清理时用最新revision finish_learning_segment。不要执行新动作。", shared)
    result["native_literal_variable_text_verified"] = True
    result["saved_reopened_project_replay_verified"] = False
