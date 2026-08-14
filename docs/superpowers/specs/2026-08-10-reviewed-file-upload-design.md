# Reviewed File Upload Design

## 目标

在不放宽 final-submit Gate 的前提下，为通用表单流程增加一次受控文件上传能力。该能力服务于学习资产驱动的 Agent 流程，不绑定 SEEK：学习资产只描述“这里是文件上传控件及其用途”，真实文件必须来自当前经审核的文件证据，并在当前截图上重新定位。

## 安全边界

- 每次只允许一个文件、一个当前控件、一次文件选择。
- 文件证据必须包含绝对路径、当前 SHA-256、大小、扩展名和显式 `human_approved=true`。
- 默认只允许简历常用格式：`.pdf`、`.doc`、`.docx`、`.rtf`。
- 文件不存在、哈希变化、大小变化、扩展名不允许、控件截图过期、点位越界或 Action Gate 未通过时全部 fail closed。
- Trace 和报告不保存绝对路径或文件正文，只保存文件名哈希、内容哈希、大小和扩展名。
- 上传成功必须通过重新 observe 后的文件名哈希和大小验证；打开文件选择器不等于上传成功。
- 上传动作不能携带 submit/continue/final-submit 语义，最终提交仍硬阻断。

## 数据流

1. Agent 从当前审核界面资产读取 `file_upload` 控件及用途。
2. 当前表单 inventory 重新确认该控件仍存在。
3. 人工审核文件证据绑定文件路径与哈希。
4. Operation 在当前截图中定位控件，Gate 审核一次点击。
5. Operation 点击控件，绑定原生文件选择器，输入经审核路径并确认选择。
6. 重新绑定原表单并 observe。
7. 通过文件名哈希与大小验证上传效果，Trace 记录脱敏证据。

## 组件

- `app/operation/form_file_upload_executor.py`：纯契约校验、一次 dispatch 和效果验证。
- `scripts/run_general_form_fixture_smoke.py`：本地 Windows GUI fixture 适配器，负责真实文件选择器交互。
- `tests/fixtures/general_form_file_upload_site/`：独立本地文件上传页面和合成 PDF。
- 单元测试与 fixture smoke：覆盖允许、过期截图、错误哈希、未审核文件、错误 Gate、效果未发生和 final-submit 计数。

## 验收

- 本地真实 GUI fixture 中 `upload_attempted=1`、`upload_effect_success=true`。
- `submit_clicks=0`、`final_submissions=0`。
- 报告和 Trace 不包含绝对文件路径或文件正文。
- 上传完成后流程停留在表单/审核界面，不触发 Continue 或最终提交。

\n