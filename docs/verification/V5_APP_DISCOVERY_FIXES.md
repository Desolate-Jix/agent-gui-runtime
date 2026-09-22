# v5 source fixes / v5 源码修复 — 2026-09-22

Status: **source verified, not packaged or published**. Existing test.5 ZIP is unchanged. / 状态：源码已验证，未打包、未发布；原 test.5 ZIP 未变。

## Scope / 范围

- Installed desktop apps: bounded user/common Desktop and Start Menu shortcuts, HKCU/HKLM App Paths (32/64-bit views); stable IDs, aliases, command+cwd deduplication. / 安装应用有界发现、稳定 ID、别名和命令＋工作目录去重。
- Launch by one of app_id/name/absolute .exe or .lnk path; preserve shortcut arguments and cwd, no shell evaluation. Ambiguity returns candidates. / 支持名称、ID、路径启动，保留参数与工作目录，同名消歧。
- Instant launch defaults to reuse a uniquely identified existing argument-free app; URL/argument launches preserve intended dispatch. Existing user windows are not adopted for cleanup. / 默认复用唯一现有窗口，不吞 URL/参数，不接管用户原窗口清理权。
- Desktop capture/click auto-resolves the current shell; fresh recognition uses the existing input route. / 桌面操作无需调用方预先绑定，内部仍核对桌面身份与新截图。
- Model startup diagnostics include phase/code/type and available log/exit/OS details. Friend's connection-refused root cause is **not established**. / 新增模型失败诊断，不冒称朋友电脑的问题已修复。

## Checks / 检查

Interpreter: `D:\agent-gui-runtime\.superpowers\sdd\2026-09-13-formal-release\.venv-clean-desktop\Scripts\python.exe`.

- `python -m pytest tests -q --disable-warnings`: **908 passed**, 27.75 s.
- Targeted regression was red before fixing missing per-HWND binding, different-cwd merging, and unrelated unbindable windows; all passed afterwards. / 对应回归先失败再修复通过。
- Real temporary shortcut read twelve times: correct argv/cwd, unchanged bytes, no COM teardown stderr. Real read-only installed scan: 202 unique discovered entries, stable across two scans. / 真实快捷方式解析与整机只读发现通过；数量仅是本机观察，不是跨机器覆盖率。
- `git -c core.whitespace=cr-at-eol diff --check`: clean.

## Real single-operation and continuous testing / 实机单项与连续使用

Evidence roots / 原始证据：

- `20260922-instant-v5-desktop-01`
- `20260922-instant-v5-app-discovery-01`
- `20260922-instant-v5-app-discovery-02`

All input/window actions used the source MCP runtime, not a replacement automation driver. No learning assets/models were copied. / 全部动作经源码 MCP，驱动只转发请求；没有复制学习资产或模型。

Desktop: two fresh-recognition double-click launches of an owned Calculator test shortcut, independently observed new windows, then recognition-based close. Cold/warm desktop-click receipts: 23.06 s / 9.84 s. First two desktop capture attempts failed with `capture_visibility_changed`; retained, **not reclassified as first-pass success**. Test shortcut removed after verifying its exact hash. / 桌面两轮成功，但保留最初遮挡变化失败，不宣称该竞态已根治。

App-discovery round 01: same session, name → Notepad, reuse same HWND/PID, close; absolute executable path → new Notepad, reuse, close; installed `Character Map` → actual character-map UI, discovered-ID reuse, close; explicit test .lnk → Notepad, close. Original screenshots inspected. Name launch 1.78 s; explicit path 0.239 s; shortcut 0.211 s; discovered Character Map 1.76 s. / 本机实测耗时，不是普适性能承诺。

Independent code review found that identity reads require per-HWND binding, and cwd must participate in deduplication and visible previews. Fixed with regression tests. Round 02 initially then exposed unrelated windows whose client area is unavailable aborting reuse inventory: three failed receipts are retained; no app launch was dispatched by those failures. The common inventory loop now ignores only uninspectable windows rather than misreading a stale binding. / 保留审查与首轮失败记录；修改通用窗口查找，不是针对某个软件打补丁。

Final round 02 session `session-e3203794ebb7480baace7299be603961`:

1. Launch Character Map by name (3.04 s).
2. Launch blank Notepad by full path (0.283 s), changing the bound target.
3. Launch Character Map again: same original HWND/PID, `reused_existing_window=true`, `launch_dispatched=false` (2.64 s).
4. Explicit `prefer_existing=false` opens a second owned blank Notepad (0.240 s).
5. Normal Notepad path launch returns **two current HWND/PID candidates**, `application_window_ambiguous`, no third launch (0.082 s).
6. Explicit select recovers from ambiguity; original Character Map screenshot inspected.
7. Gracefully close the two owned blank Notepads and Character Map (each ~0.06 s); final inventory contains no test Notepad/Character Map windows.
8. Host stopped, `cleanup_verified=true`, `host_alive=false`, `pending_ids=[]`, `cleanup_errors=[]`.

Client-side mistakes remain recorded separately: extra `command.title` rejected before admission; one helper reused its previous evidence-directory closure and timed out without reaching the new driver; one launch sent while host was starting returned `accepted=false/host_not_ready`, then explicitly resubmitted after ready. None is counted as a runtime input success. / 驱动错误和未就绪拒绝单独记录，不隐去失败，不冒充成功。

## Reusable failure contracts / 通用故障闭环

| Failure / 故障 | Invariant and fix / 不变量与修复 | Regression / 防回归 |
| --- | --- | --- |
| Unlisted apps looked like MCP registration failure / 非内置软件打不开 | Discovery is machine-local, not limited to four static entries; typed selector errors and candidates / 通用发现与结构化错误 | Installed app parsing and selector tests; real Character Map |
| Reuse missed windows after switching targets / 切换后漏认旧窗口 | Bind each observed HWND before reading its identity / 身份读取必须对应当前 HWND | Fresh/unrelated binding and multiple-window tests; real cross-app reuse |
| Different cwd merged / 不同工作目录被合并 | Command **and** cwd identify a launch configuration; show cwd in preview / 参数和工作目录不能丢失 | Distinct-cwd and preview tests |
| Unrelated invalid window aborted launch / 无效旁窗阻断 | One uninspectable unrelated window does not abort inventory / 无效旁窗不应中断整个枚举 | ValueError regression + final real session |

These changes are common application/runtime behavior, not Notepad/Character-Map profiles. They do not add an automatic click bypass; desktop clicks retain the existing recognition path. / 均为公共层修复，不新增针对测试软件的规则或裸点击后门。

## Limits / 限制

- UWP-only shortcuts, network paths, scripts and launchers handing off to a different executable are not guaranteed. A dispatched process is not proof of a ready application. / 不承诺“所有软件”。
- Only observable identity-matched windows can be reused; inaccessible/minimized special windows and permissions may still require explicit selection/preparation. / 复用仅针对可观察且身份匹配窗口。
- Friend model failure needs the original redacted error/log and hardware details; seven diagnostic tests do not prove that machine repaired. / 朋友模型问题仍需原日志。
- This slice does not certify long-term reliability, independent AionUi acceptance or delivery dependency closure. No new ZIP, release, commit or push was made. / 未冒充外部验收或发布完成。
