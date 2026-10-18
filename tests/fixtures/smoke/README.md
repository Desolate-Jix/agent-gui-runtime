# Execute smoke fixtures / 执行冒烟测试素材

`seek_resume_fixture.html` is a synthetic, self-contained browser test page, not the legacy review UI or live recruitment data. It was moved byte-for-byte from `app/web_panel/seek_resume_fixture.html` during source consolidation. The archived original is available in commit `8609c8c1995e966382f2c2c91f390d5ae82d6f12`; layout and scripted behavior were not changed by the move.

这是独立的合成浏览器测试页面，不是旧审核界面，也不是真实招聘数据。整理时从旧网页目录按原字节迁入；归档提交保留原件，迁移没有修改布局或页面动作。

The existing smoke case is `tests/smoke/execute_cases/seek_resume_screening_flow.json`. Its file URL targets the configured `D:/agent-gui-runtime` workspace, retaining the existing fixed-workspace assumption. Import/ownership tests do not open a browser. Running a real smoke case is a separate gated action, not authorized by this fixture or a passing unit test.

既有 smoke 配置仍使用当前 `D:/agent-gui-runtime` 工作目录的文件 URL，未在此次迁移中增加路径可移植能力。归属与导入测试不打开浏览器。真实运行仍是另行审核的门控动作，不能把素材或单元测试通过当作操作授权。
