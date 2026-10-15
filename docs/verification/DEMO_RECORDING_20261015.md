# 0.1.4 demo correction and browser recording / 0.1.4 演示修正与浏览器录制

## English

The original Notepad release video captured only the editing client area. It showed text changes but omitted the File menu and its popup, so it was incomplete as a demonstration of the task. The original raw recording already had the omission; trimming did not cause it. The old video remains for history and is superseded by the full-window recording below. The existing 7-Zip video is unchanged.

The external recorder now records the visible screen rectangle of the newly owned window, including its title and menus. It checks the original process identity, foreground ownership and fixed rectangle, stopping on a mismatch. Recording is separate from runtime screenshots, targeting and action authorization. **No Runtime behavior, model prompt, threshold, installer or version was changed.** Both tasks used the production bytes from the 0.1.4 release payload with an existing Python environment.

| New recording | Actual result | Complete plan time | Video duration |
| --- | --- | ---: | ---: |
| [Notepad, full window](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Notepad-FullWindow.mp4) | First-attempt automatic 3/3: replace note → File menu → Save; exact UTF-8 disk oracle passed | 27.9876454 s | 19.800 s |
| [Browser](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Browser.mp4) | First-attempt automatic 3/3: type Google URL → search `java` → open the first ordinary result; the destination was Java/Oracle | 31.3581529 s | 27.200 s |

The six steps completed without Main review; one ordinary Luna review resolved automatically. The complete deduplicated API ledger contains **17 primary Decision + 6 grounding + 1 ordinary-review requests = 24 HTTP requests**, **37,367 input + 1,999 output = 39,366 tokens**. This is the combined recording batch, excluding Main/worker subscription usage; it is not a controlled speed comparison.

At the user's request, **10.788956 s / 6.5749 s of initial pre-action waiting were removed**, retaining about 1 second before the first visible input. Subsequent actions and waits remain at **1× speed, 15 fps CFR**, with no narration or audio. Trailing operator idle and invisible frame margins were also removed. The initial Bing account header and autocomplete history rows are covered during the first navigation stage; the intended URL and click target remain visible. Menu-open, text-entry, save, the edited openers and all three browser outcome frames were inspected; full decode and H.264 level 3.2 checks passed. Raw recordings and the versions retaining initial waiting (**30.600 s / 33.733 s**) remain locally. Edited clip duration is not full-plan latency.

Only this run's owned windows were closed. Host cleanup passed. The existing named Edge test profile was retained; caches, cookies, sign-in state and original browser windows were not cleared or reset.

Saved note: `Agent Review Instant 0.1.4 - typed and saved automatically.` Its file SHA256 is `acac203405ce137a0067f235f71ba519025aded31876b8ff1425f006aa0046ae`.

| New asset | SHA256 |
| --- | --- |
| `AgentGUIRuntime-0.1.4-Notepad-FullWindow.mp4` | `057423d176f2b218e82faf0c0e76ad0099e99fb9f8c7f7cb2030b3e7d2ee4b9f` |
| `AgentGUIRuntime-0.1.4-Browser.mp4` | `8e2134cbab9d566e7795d1c27d35aa979e151d9ebc0c0c824725cabccc3b28b3` |

Local original evidence: `D:/AgentGUI-Projects/evidence/demo-rerecord-20261015-01/`, including `diagnosis/DIAGNOSIS.md`, original recordings, plan receipts, `run/api-accounting.json` and `demo-acceptance.json`. These recording results supplement the [release acceptance](MULTI_APP_EXECUTION_20261015.md); they do not replace its original timings or first failures. The Amadeus/Pi integration is a separate investigation and was not used to run these demos.

## 简体中文

原发布页的记事本录像只捕获编辑客户区，虽然能看见文字变化，却漏掉 File 菜单与下拉菜单，不能完整展示该任务。缺失在原始录像中就已存在，不是剪辑造成。旧片作为历史保留，由下方完整窗口版替代；原有 7-Zip 视频保持不变。

外部录像器现录制本轮新窗口的可见屏幕矩形，包含标题与菜单，核对原进程身份、前台归属和固定矩形，失配即停止。录屏独立于 Runtime 截图、定位和动作授权。**没有修改 Runtime 行为、模型提示词、阈值、安装器或版本号。** 两项任务均使用 0.1.4 发布载荷的生产代码，沿用已有 Python 环境。

| 新录像 | 实际结果 | 完整计划耗时 | 成片时长 |
| --- | --- | ---: | ---: |
| [记事本完整窗口版](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Notepad-FullWindow.mp4) | 首次自动完成 3/3：替换便笺 → File 菜单 → Save；UTF-8 磁盘内容精确核对通过 | 27.9876454 秒 | 19.800 秒 |
| [浏览器](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Browser.mp4) | 首次自动完成 3/3：输入 Google 网址 → 搜索 `java` → 打开首个普通结果；目的页为 Java／Oracle | 31.3581529 秒 | 27.200 秒 |

六步均无需 Main 审核完成，有一次普通 Luna 复核自动解决。完整去重 API 账本为 **17 次主 Decision + 6 次定位 + 1 次普通复核 = 24 次 HTTP 请求**，**37,367 input + 1,999 output = 39,366 tokens**。这是整批录制合计，不含 Main／worker 套餐用量，也不是受控提速对比。

按用户要求，**剪去首次操作前的 10.788956 秒／6.5749 秒等待**，保留首次可见输入前约 1 秒；后续动作与等待以 **1× 原速、15 fps CFR** 播放，无旁白或音轨。另去除结尾人工空等及不可见边框。浏览器首次导航阶段遮盖初始 Bing 账户栏和自动补全历史行，期望网址与点击目标仍可见。已核对菜单展开、文字输入、保存、剪后开头以及三个浏览器结果画面，完整解码与 H.264 level 3.2 检查通过。原始录像及保留首次等待的版本（**30.600 秒／33.733 秒**）均在本地保留；剪后时长不代表完整流程延迟。

只关闭本轮窗口，宿主收尾通过。继续保留原具名 Edge 测试资料目录，没有清理或重置缓存、Cookie、登录状态及原浏览器窗口。

保存便笺为 `Agent Review Instant 0.1.4 - typed and saved automatically.`，文件 SHA256 为 `acac203405ce137a0067f235f71ba519025aded31876b8ff1425f006aa0046ae`。

| 新资产 | SHA256 |
| --- | --- |
| `AgentGUIRuntime-0.1.4-Notepad-FullWindow.mp4` | `057423d176f2b218e82faf0c0e76ad0099e99fb9f8c7f7cb2030b3e7d2ee4b9f` |
| `AgentGUIRuntime-0.1.4-Browser.mp4` | `8e2134cbab9d566e7795d1c27d35aa979e151d9ebc0c0c824725cabccc3b28b3` |

本地原始证据位于 `D:/AgentGUI-Projects/evidence/demo-rerecord-20261015-01/`，包括 `diagnosis/DIAGNOSIS.md`、原始录像、计划回执、`run/api-accounting.json` 和 `demo-acceptance.json`。本轮结果补充[发布验收](MULTI_APP_EXECUTION_20261015.md)，不替换其原始耗时或首次失败。Amadeus／Pi 接入属于另一项核查，这两段 Demo 没有通过 Amadeus 运行。
