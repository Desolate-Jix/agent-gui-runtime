# 工作台译文维护 / Workbench translation maintenance

工作台使用 Qt `QTranslator` 和 `Workbench` context；中文是源文案，`en-US.ts` 提供英文，`zh-CN.ts` 保留中文。三个 Qt context 中的标准按钮词条由项目人工维护。资源不包含用户标题、备注、识别文字、截图文字或原始日志的翻译。

The workbench uses Qt `QTranslator` with the `Workbench` context. Chinese is the source language; `en-US.ts` supplies English and `zh-CN.ts` retains Chinese. Standard button messages in three Qt contexts are maintained by this project. User titles, notes, recognized text, screenshots, and raw logs are not translated.

新增显示文字使用 `tr('固定文案')`；动态值使用 `tr('说明：{value}', value=user_value)`。用 `ui(widget.setText, template)` 或 `bind_text(widget, 'setText', template)` 显式绑定。不要对用户值调用 `tr(user_value)`，不要遍历控件树翻译可编辑内容。装入用户内容并替换旧显示绑定时使用 `user_text(widget.setText, value)`。多项拼接使用 `join_text` 保留各项模板。

Wrap fixed UI messages with `tr('source')`, and place dynamic values in named placeholders. Bind display setters explicitly with `ui` or `bind_text`. Never translate a user value or traverse editable widget content. Use `user_text` when replacing an existing display binding with user content, and `join_text` for lists of templates.

在工作树根目录执行以下命令。`check_catalog.py` 只扫描和报告，不自动翻译、写入 `.ts` 或调用外部服务。新增词条必须人工填写两份 `.ts` 后编译；不需要安装依赖。

Run these commands from the worktree root. The checker only inventories literal sources and validates format placeholders. It does not translate, modify `.ts`, or contact external services. Add messages to both catalogs manually, then compile using the existing Qt tool; no new dependency is required.

```powershell
& '<PYTHON_EXE>' -I -B -X utf8 app/learning_memory/translations/check_catalog.py --output .superpowers/sdd/2026-10-05-learning-optional-install-and-language/L-source-inventory.json
& '<PYSIDE6_LRELEASE_EXE>' app/learning_memory/translations/en-US.ts -qm app/learning_memory/translations/en-US.qm
& '<PYSIDE6_LRELEASE_EXE>' app/learning_memory/translations/zh-CN.ts -qm app/learning_memory/translations/zh-CN.qm
```

`raw_literals_for_manual_review` 包含合法的字典查表词条、由 helper 绑定的表单标题、协议值、自动新建的用户标题和后端诊断；不能把计数当成“未翻译 UI”的数量。扫描也不能证明动态回调或视觉布局已验收，需要相应离屏行为回归。

`raw_literals_for_manual_review` includes valid dictionary lookups, helper-bound form labels, protocol values, generated user titles, and backend diagnostics. Its count is not the number of untranslated UI messages. Static scanning does not prove dynamic callbacks or visual layout; those need relevant behavioral checks.
