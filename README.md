# agent-gui-runtime

[涓枃](README.md) | [English](README.en.md)

Windows 鏈湴 GUI 鑷姩鍖栬繍琛屾椂銆傚畠涓嶆槸瀹屾暣 Agent锛岃€屾槸缁欎笂灞?Agent 鎻愪緵绋冲畾鐨勬湰鍦?HTTP API锛岀敤鏉ュ彂鐜板簲鐢ㄣ€佺粦瀹氱獥鍙ｃ€佹埅鍥俱€丱CR/瑙嗚璇嗗埆銆佺敓鎴愮偣鍑昏鍒掋€佹墽琛屽彈鎺х偣鍑诲拰楠岃瘉缁撴灉銆?
鏍稿績閾捐矾锛?
```text
Agent -> local HTTP API -> GUI runtime -> bound Windows window
```

## 閮ㄧ讲鍜屽惎鍔?
### 1. 鐜瑕佹眰

- Windows 10 / Windows 11
- Python 3.11
- `uv`
- 鏈湴瑙嗚妯″瀷鍙€夛紱娌℃湁妯″瀷鏃朵粛鍙墦寮€娴嬭瘯闈㈡澘鍜屾祴璇曞熀纭€ API

### 2. 瀹夎渚濊禆

```powershell
uv sync
```

`FastAPI` 鍜?`uvicorn[standard]` 宸插啓鍦?`pyproject.toml` 鐨勪緷璧栧垪琛ㄩ噷锛屾墽琛?`uv sync` 浼氳嚜鍔ㄥ畨瑁咃紝涓嶉渶瑕佸崟鐙?`pip install fastapi`銆?
鍙€夐獙璇侊細

```powershell
uv run python -c "import fastapi, uvicorn; print('FastAPI runtime deps ok')"
```

### 3. 涓€閿惎鍔ㄦ祴璇曢潰鏉?
鍙屽嚮鏍圭洰褰曪細

```text
start_test_panel.bat
```

褰撳墠榛樿鎵撳紑娴忚鍣ㄦ祴璇曢潰鏉匡細

```text
http://127.0.0.1:8000/panel
```

`start_test_panel.bat` 鏄函 `.bat` 鍚姩鍣紝涓嶄緷璧?`.ps1`銆傚畠浼氾細

- 妫€鏌?`http://127.0.0.1:8000/health`
- 濡傛灉 runtime 涓嶅彲鐢紝鍦ㄦ渶灏忓寲 `cmd` 绐楀彛涓惎鍔?FastAPI runtime
- 绛夊緟 runtime 灏辩华
- 鎵撳紑娴忚鍣ㄦ祴璇曢潰鏉?- 灏?runtime 鏃ュ織鍐欏叆 `logs/test-panel-runtime.log`

```text
```

涔熷彲浠ユ墜鍔ㄦ墦寮€鏃ф闈㈤潰鏉匡細

```powershell
```

### 4. 鎵嬪姩鍚姩 runtime

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

鎺ュ彛鏂囨。锛?
```text
http://127.0.0.1:8000/docs
```

娴忚鍣ㄦ祴璇曢潰鏉匡細

```text
http://127.0.0.1:8000/panel
```

### 5. 鍚姩鏈湴瑙嗚妯″瀷

鎺ㄨ崘閫氳繃娴嬭瘯闈㈡澘鎴?runtime API 绠＄悊妯″瀷鐘舵€併€?
妯″瀷 profile 缁熶竴鏀惧湪锛?
```text
configs/model_profiles/
```

鍚姩/鍋滄鑴氭湰缁熶竴鏀惧湪锛?
```text
scripts/model_servers/
```

褰撳墠宸叉湁 profile锛?
- `configs/model_profiles/qwen3_6_iq4_xs.json`
- `configs/model_profiles/qwen3_vl_8b_q4_k_m.json`

鎵嬪姩鍚姩 llama.cpp 瑙嗚妯″瀷锛?
```powershell
.\scripts\model_servers\start_llama_vision_server.ps1
```

鍋滄鏈湴瑙嗚妯″瀷锛?
```powershell
.\scripts\model_servers\stop_local_vision_server.ps1
```

## 娴嬭瘯闈㈡澘

娴忚鍣ㄦ祴璇曢潰鏉挎槸褰撳墠鎺ㄨ崘璋冭瘯鍏ュ彛銆傚畠鐢?FastAPI runtime 鐩存帴鎻愪緵锛屼娇鐢ㄧ幇鏈夋湰鍦?API锛屼笉闇€瑕侀澶栧墠绔瀯寤烘楠ゃ€?
涓昏鑳藉姏锛?
- `GET /health` runtime 鍋ュ悍妫€鏌?- `GET /runtime/models` 妯″瀷鐘舵€佹鏌?- `POST /runtime/prepare` runtime 鍑嗗
- `POST /runtime/models/start` / `POST /runtime/models/stop` 妯″瀷鍚姩鍜屽仠姝?- 涓嫳鏂囩晫闈㈠垏鎹?- observe / locate 鐙珛妯″瀷 profile 涓嬫媺閫夋嫨
- 妯″瀷鍚姩/鍋滄鑴氭湰灞曠ず
- 妯″瀷鏈嶅姟 `/v1/models` 鐘舵€佹祴璇?- `GET /apps` 搴旂敤鍙戠幇
- `POST /apps/open` 鎵撳紑搴旂敤
- `GET /session/windows` 鍒楀嚭鍙绐楀彛
- `POST /session/bind_window` 缁戝畾绐楀彛
- 鎵撳紑鐨勮蒋浠?绐楀彛涓嬫媺閫夋嫨锛屽苟鍙嶅～杩涚▼鍚嶅拰鏍囬缁戝畾鏉′欢
- `POST /state/capture_window` 鎴浘骞堕瑙?- 鎷栨斁/閫夋嫨鏈湴鍥剧墖涓婁紶涓烘祴璇曟埅鍥?- `POST /vision/observe_screen` 鏁村睆鐞嗚В
- `POST /vision/locate_target` 绮惧噯瀹氫綅
- 鑷姩鎶婂畾浣嶅€欓€夊～鍏ヤ汉宸ュ鏍?bbox / point
- `POST /action/execute_recognition_plan` dry-run 鎴?gated execution
- `POST /action/execute_confirmed_point` 浜哄伐澶嶆牳鍧愭爣 dry-run / 鐪熷疄鐐瑰嚮
- `POST /action/type_text` 鍙楁帶鏂囧瓧杈撳叆
- `POST /vision/render_recognition_plan_overlay` 娓叉煋璇嗗埆 overlay
- observe / locate 闄勫姞 prompt rules
- 鎴浘銆佷笂浼犲浘銆乷verlay 鍥鹃瑙堝拰鍊欓€夋 overlay
- 鏌ョ湅姣忎釜闃舵鐨勫師濮?JSON 杩斿洖
- 浣跨敤纭畾鎬?SVG Action Path Graph 灞曠ず goal銆佹埅鍥俱€丱CR/UIA/瑙嗚璇佹嵁銆佸€欓€夋帓搴忋€乸re-click gate銆佺湡瀹炵偣鍑汇€侀獙璇併€乼imings 鍜?trace artifact

闀胯€楁椂鏈湴妯″瀷璇锋眰浣跨敤 `configs/vision.json` 涓殑 `timeout_seconds` / 闈㈡澘 `Timeout seconds`锛岄粯璁?`600` 绉掞紝閬垮厤澶фā鍨嬪畾浣嶈秴杩囨棫鐨?`300` 绉掑鎴风闄愬埗銆?
## Agent 宸ヤ綔娴?
涓婂眰 Agent 搴旀寜 API-first 娴佺▼鎿嶄綔锛屼笉鐩存帴浣跨敤妯″瀷杩斿洖鐨勫師濮嬪潗鏍囩偣鍑汇€?
鎺ㄨ崘椤哄簭锛?
```text
GET  /apps
POST /runtime/prepare
POST /apps/open                 鍙€?GET  /session/windows
POST /session/bind_window
POST /state/capture_window      鍙€夛紝鎺ュ彛鍐呴儴涔熷彲 live capture
POST /vision/observe_screen
POST /vision/locate_target
POST /action/execute_recognition_plan  dry_run=true
POST /action/execute_recognition_plan  dry_run=false锛屾惡甯?approved_plan_id
```

鍏抽敭鍘熷垯锛?
- 鍏堢敤鏁村睆鐞嗚В寰楀埌绠€鐭€欓€夊垪琛紝鍐嶅閫変腑鐨勭洰鏍囩簿鍑嗗畾浣?- `observe_screen.suggested_state_hint` 鏄笅涓€娆?`locate_target.state_hint` 鐨勯粯璁ゅ缓璁紱Agent 浠嶅彲鎸夌洰鏍囪鐩?- 涓婂眰 Agent 搴斾繚鐣欑敤鎴峰師鏂囩敤浜?trace锛屼絾鍙戠粰瑙嗚妯″瀷鐨?`goal` / `state_hint` / 鎺掗櫎绾︽潫寤鸿瑙勮寖鍖栦负鑻辨枃
- OCR anchors 榛樿鍙備笌瑙嗚瀹氫綅锛涚簿鍑嗗畾浣嶄繚鐣欏畬鏁?OCR 缁撴灉鐢ㄤ簬鏍￠獙锛屼絾鍚戞ā鍨嬪彂閫佸彈棰勭畻鎺у埗鐨勫嚑浣曟姇褰?- `observe_screen` 鍙敤浜庣晫闈㈡憳瑕佸拰鍊欓€夊彂鐜帮紝涓嶇敤浜庣偣鍑绘垨鏈€缁堝潗鏍囪瘉鏄?- `locate_target` 鍙繑鍥?no-click 瀹氫綅缁撴灉
- `located_bbox` / `located_point` 鏄簿鍑嗚瑙夋ā鍨嬪缓璁綅缃紱鍙湁 `selected_click_point` 琛ㄧず宸查€氳繃鐐瑰嚮鍓嶉椄闂ㄧ殑鍙墽琛屽潗鏍?- 鑷富 Agent 鐨勭湡瀹炵偣鍑诲彧鑳借蛋 `execute_recognition_plan`
- `execute_confirmed_point` 浠呯敤浜庝汉宸ュ鏍稿悗鐨勬樉寮忓潗鏍囩偣鍑伙紝涓嶆槸鑷姩鎵ц鏃佽矾
- 鎵ц鍓嶅繀椤婚€氳繃 `pre_click_decision_v1`
- 鎴愬姛 dry-run 浼氳繑鍥?`approved_plan_id`锛涚湡瀹炵偣鍑诲簲澶嶇敤杩欎釜 ID锛宺untime 鏍￠獙鍚屼竴绐楀彛鍜屽凡鎵瑰噯鐐逛綅鍚庣洿鎺ョ偣鍑伙紝涓嶅啀绗簩娆¤繍琛屽ぇ瑙嗚妯″瀷

瀹屾暣 Agent API 璋冪敤瑙勮寖瑙侊細

```text
AGENT_API_WORKFLOW.md
```

姣忎釜 API 鐨勫瓧娈靛惈涔夈€佽璁＄洰鐨勩€佽繑鍥炵粨鏋勮锛?
```text
API_FIELD_REFERENCE.zh-CN.md
```

## 瀛︿範妯″紡

褰撳墠瀛︿範妯″紡鍏堝仛鏈€灏忕殑 `instruction_learning` 鍒囩墖锛屼笉鍋氭湭鐭ラ〉闈㈣嚜涓绘帰绱€?
`learning_mode="instruction"` 鐨勮鍒欙細

- 鍙褰曟垚鍔熺湡瀹炵偣鍑诲苟閫氳繃楠岃瘉鐨勬寚浠よ矾寰?- 鍐欏叆 `learned_instruction_v1`
- 姘镐箙璧勪骇鐩綍涓?`artifacts/local-learning/instructions/{id}/`
- 璧勪骇鍖呭惈 `learned_instruction.json`銆佹簮绐楀彛鎴浘銆佺偣鍑诲墠鎴浘銆佺偣鍑诲悗鎴浘銆乨iff 鍥惧拰鐩爣 crop
- 鍚庣画鎼哄甫 `learned_instruction_id` 鏃讹紝鍙互鍦ㄦ牎楠屽悓 goal銆乤pp銆亀indow handle銆亀indow size 鍜?point bounds 鍚庡鐢ㄧ偣鍑荤偣
- 澶嶇敤鍙互璺宠繃瑙嗚妯″瀷瀹氫綅锛屼絾浠嶅繀椤绘墽琛岀湡瀹炵偣鍑诲拰鐐瑰嚮鍚庨獙璇?- 澶嶇敤澶辫触鏃跺簲鍥炲埌姝ｅ父 recognition path锛屼笉鍏佽闈欓粯鐐瑰嚮鍏朵粬浣嶇疆

## 璇嗗埆绠＄嚎

褰撳墠涓昏矾寰勶細

```text
screenshot
-> vision_regions_v1 + OCR anchors
-> page_structure_v1
-> screen_reading_v1
-> candidate_rank_v1
-> narrow_search_v1
-> pre_click_decision_v1
-> gated action
-> post-click verification
```

涓昏 Agent 璺緞浼氳繑鍥?`timings`銆傚叾涓?`total_ms` 鏄暣娆¤皟鐢ㄨ€楁椂锛宍steps[]` 浼氭媶鍑烘ā鍨嬪惎鍔ㄣ€佹埅鍥俱€丱CR anchor 鍑嗗銆佽瑙夋帹鐞嗐€佸€欓€夋帓搴忋€佺偣鍑诲墠闂搁棬銆佺湡瀹炵偣鍑诲拰鐐瑰嚮鍚庨獙璇佺瓑闃舵銆傚畠鍙敤浜庢€ц兘璇婃柇鍜?trace 澶嶇洏锛涙槸鍚﹀厑璁哥偣鍑讳粛浠?`pre_click_decision_v1` 涓哄噯銆?
閲嶇偣锛?
- OCR 鏂囧瓧妗嗕細浣滀负绌洪棿閿氱偣浼犵粰瑙嗚妯″瀷
- `click_target` 榛樿鍙戦€?`relation_matrix_compact` 鏂囧瓧鍧愭爣涓庡寘鍚?鎺掗櫎绛栫暐鐭╅樀
- 鍥炬爣鍜屾枃瀛楃殑鍏崇郴浼氳繘鍏?grounding 璇佹嵁
- 灏忓浘鏍囧畾浣嶄紭鍏堝弬鑰?OCR anchors
- 鍊欓€夌偣鍑荤偣蹇呴』缁忚繃鏈湴 ranking銆乶arrow search 鍜?pre-click gate
- overlay 鐢ㄤ簬浜哄伐澶嶆牳

## 涓昏鎺ュ彛

搴旂敤鍜岀獥鍙ｏ細

- `GET /apps`
- `POST /runtime/prepare`
- `GET /runtime/models`
- `POST /runtime/models/start`
- `POST /runtime/models/stop`
- `POST /apps/open`
- `GET /session/windows`
- `POST /session/bind_window`
- `POST /state/capture_window`

瑙嗚锛?
- `POST /vision/analyze`
- `POST /vision/page_structure`
- `POST /vision/screen_reading`
- `POST /vision/observe_screen`
- `POST /vision/locate_target`
- `POST /vision/recognition_plan`
- `POST /vision/render_recognition_plan_overlay`

鍔ㄤ綔锛?
- `POST /action/execute_recognition_plan`
- `POST /action/execute_confirmed_point`
- `POST /action/type_text`
- `POST /action/click_text`
- `POST /action/click_mouse_tester_left_region`

闈㈡澘锛?
- `GET /panel`
- `/panel/assets/*`

## 椤圭洰缁撴瀯

```text
app/
  api/                FastAPI routes
  core/               window/input/screenshot/OCR/runtime artifacts
  vision/             vision providers, OCR anchors, normalization
  page_structure/     page_structure_v1 fusion
  screen_reading/     screen_reading_v1 READ layer
  recognition/        candidate rank, local grounding, pre-click decision
configs/
  vision.json
  settings_panel.json
  model_profiles/     model registry
scripts/
  model_servers/      model server start/stop scripts
tests/
artifacts/
logs/
```

璇︾粏鐩綍璇存槑瑙侊細

```text
PROJECT_STRUCTURE.md
```

## 褰撳墠鐘舵€?
宸插叿澶囷細

- 鏈湴 FastAPI runtime
- Windows 绐楀彛鍙戠幇鍜岀粦瀹?- 鎴浘鍜?ROI 鎴浘
- OCR anchors
- local/API 瑙嗚 provider 鎶借薄
- `observe_screen` 鏁村睆鐞嗚В鎺ュ彛
- `locate_target` 绮惧噯瀹氫綅鎺ュ彛
- no-click recognition plan
- pre-click decision gate
- gated click execution
- recognition overlay
- MouseTester 鐪熷疄鐐瑰嚮鍩虹嚎
- 妯″瀷 registry 鍜岀粺涓€妯″瀷鍚姩鑴氭湰鐩綍
- 鏈€灏?`instruction_learning` 璁板綍鍜屽鐢ㄨ矾寰?
褰撳墠杈圭晫锛?
- 杩樹笉鏄敓浜х骇閫氱敤妗岄潰 Agent
- 杩橀渶瑕佹洿澶氶〉闈€佹洿澶氳礋渚嬨€佹洿澶氱獥鍙ｅ昂瀵?DPI/缂╂斁鍙樺寲娴嬭瘯
- 瀛︿範妯″紡鍏堥檺鍒跺湪鍥哄畾鎸囦护鍜屾垚鍔熼獙璇佽褰曪紝涓嶅仛鏈煡椤甸潰鑷富鎺㈢储

## 楠岃瘉

娴忚鍣ㄩ潰鏉胯縼绉荤殑鏈€鏂伴獙璇侊細

```powershell
uv run pytest tests\test_web_panel_route.py tests\test_runtime_route.py -q
uv run pytest -q
```

褰撳墠缁撴灉锛?
```text
tests/test_web_panel_route.py + tests/test_runtime_route.py: 10 passed
full suite: 141 passed
```

骞跺凡鐢ㄤ复鏃?uvicorn 瀹為檯璇锋眰楠岃瘉锛?
```text
GET /panel -> 200
GET /panel/assets/panel.css -> 200
GET /panel/assets/panel.js -> 200
```

## 閲嶈鏂囨。

- `README.en.md`锛氳嫳鏂囩増 README
- `AGENT_API_WORKFLOW.md`锛欰gent 璋冪敤 API 鐨勬爣鍑嗘祦绋?- `API_FIELD_REFERENCE.zh-CN.md`锛氭瘡涓?API 鐨勫瓧娈电骇涓枃璁捐鍙傝€?- `ACTION_PATH_GRAPH_SPEC.zh-CN.md`锛氭搷浣滆矾寰勫浘 `runtime_path_graph_v1` 鏍煎紡瑙勮寖
- `LEARNING_MODE_PLAN.zh-CN.md`锛氬涔犳ā寮忚鍒?- `PROJECT_STRUCTURE.md`锛氭枃浠剁粨鏋勩€侀厤缃€佷骇鐗╀綅缃?- `PROJECT_SUMMARY.md`锛氶」鐩憳瑕?- `CURRENT_STATE.md`锛氬綋鍓嶇姸鎬?- `NEXT_STEPS.md`锛氫笅涓€姝ヨ鍒?- `ACCURACY_EVALUATION_STANDARD.md`锛氬噯纭巼璇勪及鏍囧噯
- `RUNTIME_STATE_GRAPH.md` / `RUNTIME_STATE_GRAPH.zh-CN.md`锛氱姸鎬佸浘璁捐

## 寮€鍙戣鍒?
鏈粨搴撹姹備唬鐮佸拰鏂囨。鍚屾銆傝涓恒€丄PI銆佹灦鏋勩€侀厤缃€佽繘搴︽垨闄愬埗鍙戠敓鍙樺寲鏃讹紝闇€瑕佸悓姝ユ洿鏂扮浉鍏虫枃妗ｃ€?
瀹炵幇浠ｇ爜鏃堕伒寰細

```text
skills/code-implementation-loop/SKILL.md
```

鏈€灏忛棴鐜細

1. 鍋氭渶灏忔湁鎰忎箟鏀瑰姩
2. 璺戞渶绐勯獙璇?3. 鐪嬬粨鏋?4. 淇け璐?5. 閲嶈窇鐩村埌閫氳繃鎴栬褰曠湡瀹?blocker

## 缁存姢澶囨敞

- Windows only
- local-only HTTP API
- 鍗?session / 鍗曠粦瀹氱獥鍙ｄ紭鍏?- 涓嶅厑璁哥洿鎺ヤ粠妯″瀷鍘熷 bbox 鐐瑰嚮
- 鎵€鏈夌湡瀹炵偣鍑婚兘搴旇蛋 gated action API
- 鍘嗗彶缁嗚妭涓嶈缁х画濉炶繘 README锛屾斁鍒颁笓闂ㄦ枃妗ｉ噷

## 2026-06-02 浏览器测试面板状态

`/panel` 是唯一保留的本地测试面板入口；旧 Tkinter 桌面面板代码、启动脚本、测试和 `tkinterdnd2` 依赖已移除。`start_test_panel.bat` 会启动 FastAPI runtime 并打开 `http://127.0.0.1:8000/panel`。

当前面板结构：左侧阶段导航使用按钮式中英文切换；顶部流程图按 trace 分组阶段显示 Request、Capture、OCR、Vision、Candidates、Gate、Action、Verify；Trace 页面隐藏普通流程图、导航路径图、截图预览、页面详情和 API 响应，只显示 trace 文件卡片与 Trace Flow。Trace Flow 从 `/panel/inspect_trace` 返回的 `flow_stages` 渲染，点击阶段可查看该阶段 summary 和原始 JSON。

模型测试页位于健康检查下面的 Models 入口，只显示模型测试控件和模型返回结果。它通过 `POST /panel/model_test` 将 prompt 和可选图片路径转发给已配置的 OpenAI-compatible 视觉模型，不显示导航路径图或 API 响应卡片。

最新验证：`node --check app\web_panel\panel.js`；`python -m py_compile app\main.py app\api\panel.py`；`uv run pytest tests\test_web_panel_route.py tests\test_runtime_route.py -q` -> `11 passed`；`uv run pytest -q` -> `136 passed`；临时 uvicorn smoke 确认 `/panel` 与 `/panel/assets/panel.js` 均返回 200。

### 2026-06-02 Trace UTF-8 兼容更新

浏览器面板现在将 `/panel` 明确返回为 `text/html; charset=utf-8`；trace JSON 读取使用 `utf-8-sig`，兼容带 BOM 的 UTF-8 文件。`/panel/inspect_trace` 除当前 recognition/screen-reading trace 外，也支持旧 overlay trace 和 `vision_layer_trace_v1` layer trace，统一输出带原始阶段 JSON 的 `flow_stages` 给 Trace Flow 使用。

本次更新后的验证：`node --check app\web_panel\panel.js`；`python -m py_compile app\api\panel.py`；`uv run pytest tests\test_web_panel_route.py -q` -> `9 passed`；`uv run pytest -q` -> `138 passed`；uvicorn smoke 确认 `/panel` 返回 200、Content-Type 为 `text/html; charset=utf-8`，Trace 控件没有剩余可见乱码。
