# 已学习控件快速重定位实验计划

1. 在 `tests/test_vision_route.py` 增加唯一当前 UIA 命中和歧义回退测试，先确认测试失败。
2. 在 `app/api/vision.py` 增加显式实验开关与最小快速定位判断；输出独立 trace 字段。
3. 运行目标测试、相关 vision/action 测试和语法检查。
4. 检查 GPU 占用；以真实窗口重新截图运行 Notepad 和外部浏览器 A/B dry-run。
5. 只在低风险且 Gate 放行时执行一次真实动作，保留动作前后截图和 Trace。
6. 更新 `README.md`、`CURRENT_STATE.md` 和 `NEXT_STEPS.md` 的实验状态与限制。
