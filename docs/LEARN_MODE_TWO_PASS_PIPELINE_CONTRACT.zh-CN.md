# 学习模式两轮分栏识别流程合同

更新日期：2026-07-07

本文是学习模式前半段识别链路的硬合同。后续实现、调试、评测和面板展示必须按这个流程审查，不能用单张截图的局部 heuristic 替代主流程。

代码产物应使用或兼容以下合同 ID：

- `learn_mode_two_pass_pipeline_contract_v1`
- `learn_two_pass_flow_compliance_v1`
- `direct_numbering_within_precise_region`
- `subdivide_then_number`
- `center_subdivide_then_number`

## 0. 总原则

学习模式只读图，不操作窗口。

- 不点击
- 不输入
- 不上传文件
- 不提交
- 不登录
- 不授权 Execute
- 不提升 Runtime PathGraph

学习模式输出的是学习草稿、界面详情、编号图、trace 和只读 PathGraph 预览。所有产物必须保持：

- `display_only=true`
- `execute_binding_enabled=false`
- `artifact_is_authorization=false`
- `draft_only=true` 或等价字段

## 0.1 防跑偏执行清单

以后每次修改、运行或汇报学习模式识别，都必须先按这张清单检查。没有通过清单时，不能说“流程已经跑通”，也不能继续往 PathGraph 或学习草稿可执行方向包装。

执行顺序必须是：

```text
绑定窗口 / 截完整图
-> 第一次模型调用：只做整屏结构分栏
-> 第一轮栏级精准定位：校准上下左右栏、中间栏、弹窗/浮层的完整 bbox
-> 第二次模型调用：只在已经校准的栏内识别内容
   -> 顶栏 / 侧栏 / 底栏：直接编号定位
   -> 中间主栏：先再次分区，再对每个子区编号定位
-> OCR / 视觉结构 / 4B 或 VISTA 定位 / rerank / gate dry-run 融合
-> 输出融合截图、界面详情、学习草稿和只读 PathGraph 预览
-> 人工审查 / 修改
```

必须同时满足：

- 第一次模型调用不能直接编号按钮、卡片或文字。
- 第一轮精准定位必须定位整条栏，不是定位栏里的按钮集合。
- 第二次模型调用必须以第一轮校准后的栏 bbox 为输入。
- 顶栏、侧栏、底栏不再二次分栏，直接做栏内编号。
- 中间主栏必须先二次分区，再编号。
- 中间主栏二次分区时，同类、大小接近、语义接近的卡片可以成组；不同大小或不同语义的卡片不能强行放进同一组。
- 顶栏 / header 在直接编号控件之外，还应保留 display-only 父组表达控制带；后续可在证据充分时继续拆成 player、search、window controls 等子父组。
- 顶栏 / header 的直接编号控件不能停留在极小 glyph / OCR fragment bbox；必须扩成只读 hit-area 证据框，并保留上游 visual / model 证据链。
- OCR 和 4B/VISTA 定位是校准证据，不是替代第一轮分栏流程的捷径。
- Gate 在学习模式只做 dry-run 审查，不授权点击。
- 最终截图必须自动更新到融合后的框图，不能要求用户点下面的条目才看到框。

禁止的跑偏方式：

- 看到某一张图偏了，就只针对这张图写局部 heuristic。
- 用按钮间距反推栏宽，导致侧栏或顶栏只框住图标。
- 把 QQ、Apple Music 或某个网站的特殊布局写成通用策略。
- 用已经失效的旧草稿、旧路径图、旧界面详情填充新识别结果。
- 把 observe-only / fallback-only 结果显示成已经完成精准定位。
- 把不可操作的 review-only 区域漏掉融合框；不可操作也要能在截图上显示审查框。
- 在没有实际编号图、定位证据、融合结果时，让进度条继续显示完成。
- 把学习草稿当成 Runtime PathGraph 或 Execute 授权。

消息流界面的额外约束：

- `message_item` 不能跨多个时间戳 / 发送者锚点吞掉多条消息。
- 如果前一条 `message_card` 的 bbox 过高并覆盖到后续时间戳、发送者或气泡，后续锚点必须切出新的消息父框。
- 时间戳、发送者、头像、等级等上下文片段必须优先归属到其后方最近的消息核心，而不是被前一个过大的 bbox 抢走。
- `message_card`、`image_message`、`message_bubble` 的 bbox 可以根据后续消息起始锚点做 display-only 裁剪，但裁剪结果仍需标记 review-only，不得提升为 Execute 候选。
- 如果 `message_bubble` 子框已经扩成 review 背景，而 timestamp / sender context 与气泡核心之间有明显空白，`message_item` 的显示 bbox 应收敛到消息核心；上下文关系通过 `member_item_ids`、`semantic_parent_group_id` 和 context overlay 保留，不再用父框吞掉空白区域。
- `message_item` 显示 bbox 不能被解释为包含所有上下文子项的完整几何框；完整父子关系以 JSON 证据为准。
- OCR 只看到一行文字时，可以为 `message_bubble` 扩成保守 review 背景，但扩展必须贴近文本气泡核心；不能用固定大 padding 把大量空白也包进气泡。
- 这种保守气泡框仍必须标记 `needs_review` / `display_only`，不能提升为可点击或可执行候选。

每次真实界面复跑都必须记录：

- 使用的截图和 trace。
- 第一次分栏输出。
- 栏级精准定位结果。
- 第二次栏内识别结果。
- 融合框 overlay。
- Codex 自己目检结论。
- 是否保护了上一版已经识别正确的区域。
- 如果退化，必须先回滚或修复通用 invariant，再继续。

GPT 图审发送规则：

- Browser bridge 只允许用于读取 ChatGPT 页面状态、获取 composer / send button 坐标、检查附件数量和读取回复。
- 真正点击 GPT 输入框、移除附件、点击发送按钮时，必须使用 framework 的真实鼠标点击能力，例如 `InputController.click_point()`。
- 图片必须通过 framework 的图片剪贴板粘贴能力送入 GPT，例如 `InputController.paste_image(..., focus_bound_window=False)`；不要用 Browser bridge 的虚拟 clipboard 当作图片粘贴证据。
- 文字必须走固定点流程：先用 framework 点击 GPT composer，再用 `InputController.type_text(..., click_before_typing=true)` 通过剪贴板粘贴；不要用 Browser bridge 写入正文，避免焦点漂移到 Codex 输入框。
- 每张图片粘贴前必须再次用 framework 点击 GPT composer，然后再执行图片剪贴板粘贴。
- 发送前必须确认 GPT composer 中的图片数量等于本轮要审核的 overlay 数量。
- 发送后必须确认最后一条 GPT user message 的图片数量仍然正确。
- 如果图片上传/粘贴失败，不能说 GPT 已审核图片，只能说 ChatGPT 图审链路阻塞。

## 1. 绑定与截图

先绑定目标窗口，截取完整界面图。

这一阶段只生成证据，不做理解决策。

输出必须包含：

- full screenshot
- window metadata
- screenshot checksum
- trace id
- viewport / window size

## 2. 第一次模型调用：整屏分栏

第一次模型调用只负责页面结构分栏，不识别按钮细节，不编号卡片，不生成动作。

必须识别的结构栏包括：

- `top_bar` / `header`
- `left_sidebar`
- `right_sidebar`
- `bottom_bar`
- `center` / `main_content`
- `modal` / `popup` / `floating_panel`

分栏原则：

- 栏之间可以紧贴，甚至几乎没有间隔。
- 没有明显 gutter 不能作为漏掉栏位的理由。
- 栏 bbox 要覆盖完整视觉结构区域，而不是只覆盖内部按钮或文字。
- 左右栏应覆盖完整可见高度。
- 顶底栏应覆盖完整可见宽度。
- 如果已经识别出左右侧栏，顶栏/底栏的“完整可见宽度”指非侧栏通道宽度：它们可以与侧栏贴边，但不能横穿或压住侧栏。
- 中间栏应覆盖主要内容区域。
- 没有左侧栏证据时，居中的网页内容列不能把 `primary_area` 横向收窄；主栏应覆盖从视口左边到右边的完整视觉主区域。
- 浏览器 chrome 左上角按钮不能作为应用/网页左侧栏证据；计算主栏左边界时必须忽略 top/browser chrome 区域内的图标。
- 粗 bbox 只是参考，后续精准定位可以完全替换。

分栏依据：

- 屏幕边缘
- 背景色或明暗变化
- 分隔线
- 滚动条
- 内容密度变化
- OCR 文本分布
- 控件分布
- 主内容起始位置
- 弹窗遮挡关系

输出字段：

- `region_id`
- `region_type`
- `rough_bbox`
- `semantic_summary`
- `boundary_evidence`
- `uncertainty`

第一轮模型输出只能作为结构假设。它可以偏，可以粗，但必须包含足够语义解释，方便后续栏级精准定位：

- 这是哪种栏：顶栏、侧栏、主栏、底栏、弹窗、浮层。
- 为什么认为这里是一个栏：边缘、分隔线、背景、滚动条、控件密度、标题或内容起点。
- 这个栏可能包含什么内容。
- 哪些边界不确定。
- 哪些区域可能互相遮挡或包含。

第一轮之后必须马上进入栏级精准定位，不能跳到内部编号。

## 3. 栏精准定位

对第一次模型输出的每个栏做精准定位。这里仍然不做内部编号。

目标：

- 修正每个栏的完整 bbox。
- 确认栏之间的相邻、包含、遮挡关系。
- 为后续界面详情的位置排布准备稳定结构。

定位原则：

- 栏 bbox 宁愿完整覆盖一点，也不能因为内部按钮稀疏而框窄。
- 按钮间距不能用来缩小栏 bbox。
- 栏之间允许紧贴。
- 栏内部允许存在大块空白。
- modal / popup 的遮挡关系优先级高于底层栏。
- 如果栏边界不确定，标记 `needs_review`，不要自动缩小到按钮集合。

输出字段：

- `precise_bbox`
- `relation_to_other_regions`
- `boundary_evidence`
- `confidence`
- `needs_review`

栏级精准定位的通用策略：

- 栏之间的间隔可以为 0，不能因为没有空隙就漏掉栏。
- 顶栏和底栏以整条横向视觉区域为目标，通常应覆盖完整可见宽度。
- 左右侧栏以整条纵向视觉区域为目标，通常应覆盖完整可见高度。
- 中间主栏以剩余主要内容区域为目标，不能只框住第一张卡片或一个标题。
- 如果图标列、文字列和空白都属于同一侧栏，必须一起包含。
- 如果顶栏按钮很稀疏，顶栏 bbox 仍然覆盖整条顶栏，而不是多个按钮的小 union。
- 结构栏可以相邻或轻微接触；这种接触不是错误。
- 没有包含关系的两个区域不应大面积重叠。
- 同级顶栏、底栏、左栏、右栏和主栏必须形成可复盘的 sibling partition：可贴边、可共享边界，但不能互相覆盖来解释不确定区域。
- Stage1 gate 必须检查这个 sibling partition；如果顶栏从 `x=0` 横穿已识别左栏，或主栏继续压到右栏下面，必须先修栏定位，不能继续 Stage2 编号。
- 有父子包含关系时可以重叠，例如卡片包含图片、标题和按钮。
- 发现同类结构区一个大框包含一个明显过小的重复小框时，应保留大框，把小框标为 duplicate / suppressed，而不是让它进入后续编号。
- 如果右侧候选形成窄的、靠右的、纵向连续信息带，并且不像横向卡片网格，应从主内容中拆成 `right_sidebar`。
- 右侧信息栏拆出后，同级 `main_content` / `primary_area` 不能继续压到右栏下面，必须裁到右栏左边界。
- 不能仅凭“元素在右侧”就拆右栏；横向卡片网格里的最右卡片仍属于主内容。
- 浏览器网页 surface 需要额外区分 `browser_chrome`、`webpage_header/site_nav`、`primary_area` 和右边缘 `floating_controls/scroll review`。顶部网页 header/search/nav 控件不能作为 primary 内容起点，否则会把 header 和 primary 混在一起。
- 如果浏览器网页没有明确 `right_sidebar`，但右边缘存在浮动控件、翻译/工具按钮或滚动条证据，应拆出 `floating_controls`；如果证据缺失但 browser chrome 已确认，允许生成 display-only 的右边缘 review strip，提醒人工审查 floating/scroll 归属。该 strip 不授权执行。
- `floating_controls` 是 overlay/review 区，不应被包装成普通右侧信息栏；它可以和 `primary_area` 共享视觉范围，但必须保持 `display_only=true`、`execute_binding_enabled=false`、`artifact_is_authorization=false`。
- `bottom_bar` 必须像真实底栏：通常接近整屏宽、贴近屏幕底部，并且不是主内容内部的一个章节。
- 如果一个 bottom-like 候选又窄又不贴左，并且和 `primary_area` / `main_content` 水平重叠、垂直连续或实际落在主内容内部，应并回主内容，而不是让 Stage1 gate 因假底栏阻断。
- 这种归并必须写入 `stage1_structure.zone_corrections[*].correction=bottom_bar_content_merged_into_primary_region`，方便审查它是通用栏策略，而不是针对单个网页的硬编码。

## 3.1 栏与内部内容的父子边界关系

Stage1/栏级定位输出的是父区域，Stage2/栏内编号输出的是子内容。父子关系必须是硬约束：

- 每个编号 item 必须归属到一个父栏或父分区。
- 每个 `subregion_group` / 卡片组 / 文本组也必须归属到一个父栏或父分区。
- 内部内容的 bbox 不能超出父栏 bbox。
- 如果模型、OCR 或视觉候选给出的内部 bbox 越过父栏边界，Stage2 必须把它裁回父栏内，并记录 `region_content_boundary` / `bbox_boundary_clip` 证据。
- 如果裁剪后几何过小或语义不可信，应降级为 review-only 或 suppressed，不能继续包装成可执行候选。
- 没有父子包含关系的同级栏不能用重叠来解释；它们应相邻、相切或被 Stage1 gate 阻断。
- 只有真实父子关系可以重叠，例如卡片父框包含图片、标题、标签和按钮。
- 融合截图必须显示裁剪后的框，不能只在用户点选下方详情时才显示修正结果。

当前正式字段：

- `region_content_boundary.policy=numbered_items_and_subregion_groups_must_not_extend_outside_parent_region`
- `region_content_boundary.parent_child_relation_policy=every_stage2_child_must_name_its_parent_region_before_promotion`
- `region_content_boundary.parent_region_id`
- `region_content_boundary.parent_region_bbox`
- `region_content_boundary.clipped_numbered_item_count`
- `region_content_boundary.clipped_subregion_group_count`
- `region_content_boundary.rejected_numbered_item_count`
- `region_content_boundary.rejected_subregion_group_count`
- `region_content_boundary.child_scope_policy`
- `region_content_boundary.annotated_numbered_item_count`
- `region_content_boundary.annotated_subregion_group_count`
- `numbered_items[*].parent_region_id`
- `numbered_items[*].parent_region_bbox`
- `numbered_items[*].parent_boundary_relation`
- `numbered_items[*].parent_boundary_relation.child_scope`
- `numbered_items[*].parent_boundary_relation.inside_parent_after_enforcement`
- `numbered_items[*].bbox_boundary_clip`
- `numbered_items[*].bbox_boundary_reject`
- `subregion_groups[*].parent_region_id`
- `subregion_groups[*].parent_region_bbox`
- `subregion_groups[*].parent_boundary_relation`
- `subregion_groups[*].bbox_boundary_clip`
- `subregion_groups[*].bbox_boundary_reject`
- `fusion.region_content_boundary_summary.policy=fused_child_boxes_must_name_parent_region_and_stay_inside_parent_region`
- `fusion.region_content_boundary_summary.missing_parent_child_count`
- `fusion.region_content_boundary_summary.clipped_fused_child_count`
- `fusion.region_content_boundary_summary.outside_parent_after_clip_count`
- `fusion.region_content_boundary_summary.boundary_contract_status`
- `fusion.region_content_boundary_summary.pathgraph_promotion_allowed`
- `fusion.region_content_boundary_summary.promotion_blockers`
- `fusion.region_content_boundary_summary.visual_overlay_status`
- `fusion.region_content_boundary_summary.learning_artifact_status`
- `fused_review_boxes[*].parent_region_id`
- `fused_review_boxes[*].parent_region_bbox`
- `fused_review_boxes[*].fusion_boundary_clip`
- `fused_review_boxes[*].fusion_boundary_review`

判定规则：

- 如果一个内部 item / group 没有 `parent_region_id`，只能进入审查队列，不能进入 PathGraph candidate。
- 如果内部 bbox 被裁剪，Stage2、融合结果、面板和 overlay 都必须使用裁剪后的 bbox，同时在详情里保留 `previous_bbox`。
- 如果内部 bbox 与父栏完全无交集，不能伪造 1px 裁剪框；必须记录为 `outside_parent_rejected`，不在融合截图上渲染，也不能进入 PathGraph candidate。
- `child_scope=inside_parent` 表示子内容完整位于父栏内；`child_scope=clipped_to_parent` 表示只保留父栏内部分并要求人工审查；`child_scope=outside_parent_rejected` 表示该候选不属于该栏。
- 融合层必须重复执行父栏边界检查，防止 stale child bbox、旧学习草稿或中间合成结果绕过 Stage2 裁剪后继续显示。
- 裁剪成功不能解释成识别成功；`clipped_fused_child_count>0` 时该 child 必须是 `review_required=true`，`pathgraph_promotion_allowed=false`。
- `missing_parent_child_count>0`、`clipped_fused_child_count>0` 或 `outside_parent_after_clip_count>0` 任一成立时，只能进入人工审查，不能进入 Runtime PathGraph promotion。
- 如果 Stage1 gate 阻断导致 Stage2 未执行，`boundary_contract_status` 必须是 `not_evaluated_stage2_skipped`，不能因为没有 child 而显示为通过。
- 如果两个同级栏或同级 group 大面积重叠，但没有父子关系字段，必须归类为 `non_parent_overlap` / `boundary_review_region`。
- 如果存在父子关系，子框可以在父框内部重叠，例如卡片包含图片、标题、文字、按钮；这种重叠必须能从 `parent_boundary_relation` 或语义父组字段复盘。

这个约束是 display/review-only 的结构一致性约束，不授权 Execute，不证明识别准确率，也不提升 Runtime PathGraph。

## 3.2 Overlay 标签可读性约束

融合截图里的 label 只是审查辅助，不是识别结果本身。label 不能破坏截图可读性：

- label 必须尽量限制在对应 bbox 宽度和画布边界内。
- label 也是 overlay 识别内容的一部分，默认必须画在自己的 bbox 内部；不能因为 bbox 合法但 label 浮到父区外而制造“内容超出栏”的视觉假象。
- 长 role 名必须压缩成可读短名，不能横向覆盖兄弟框或主内容。
- 消息上下文关系可以显示为短标签，但不能用大标签盖住消息气泡。
- 顶栏 / 侧栏控件密集时，宁愿缩短 label，也不能让 label 互相堆叠到不可审查。
- label 缩短不能改变原始 trace / report 中的真实 role 和 bbox；完整信息必须保留在 JSON 证据里。
- label containment 只改善 review overlay，不代表识别准确率提升，也不授权 Execute。

## 4. 第二次模型调用：按栏识别内容

第二次模型调用才开始识别栏内部元素。不同栏必须走不同策略。

### 4.1 顶栏、侧栏、底栏

`top_bar`、`left_sidebar`、`right_sidebar`、`bottom_bar` 直接进入栏内编号定位模式。

需要识别：

- button
- icon button
- tab
- menu item
- search input
- toggle
- avatar / profile
- status indicator
- navigation item

栏内编号原则：

- 控件可以按轨道、行、列分组。
- 按钮间距只用于控件分组，不用于缩小栏 bbox。
- 间距断裂说明不同控件组，不说明它们不属于同一栏。
- 小图标必须保留，不能因为缺文字被丢弃。
- 文本和图标接近时，可以合成一个 nav item。
- 多个孤立按钮允许存在。
- 侧栏按钮通常位于一个或多个纵向轨道，但轨道规则只用于分组按钮，不能重新决定侧栏 bbox。
- 顶栏按钮通常位于一个或多个横向轨道，但轨道规则只用于分组按钮，不能重新决定顶栏 bbox。
- 如果按钮间距断裂，可以拆成多个 control group；这些 group 仍然属于同一栏。
- 顶栏的控件搜索可以限制在顶栏内部的顶部控制带，但不能因此缩小顶栏 region bbox。

输出字段：

- `numbered_items`
- `item_type`
- `bbox`
- `text`
- `icon_description`
- `group_id`
- `possible_action`
- `review_only`
- `actionable_candidate`

### 4.2 中间主内容栏

`center` / `main_content` 不能直接全量编号。必须先二次分区，再对子区编号。

主内容二次分区包括：

- page title
- filter / search area
- card row
- list region
- detail region
- form region
- recommendation section
- media grid
- table
- empty state
- footer inside main content

主内容分区原则：

- 子区之间可以紧贴。
- 子区 bbox 要覆盖完整视觉区域。
- section title 不能被上一张卡片吞掉。
- section title 位于 card/list group 上方且空间关系合理时，必须生成 `section_parent`，记录标题和子 group 的父子关系；标题不能长期作为孤立 text。
- `section_parent` 只表示学习草稿/界面详情层级，不授权执行。它的 overlay 样式应区别于 Stage1 结构栏和 card group，避免视觉层级混淆。
- 卡片父框必须包含自己的图像、标题、描述、附属按钮。
- 如果当前证据只能覆盖局部 artwork、标题碎片或不完整卡片槽位，不能标为合格 `media_card`，必须降级为 `card_parent_incomplete` / `needs_review`。
- `card_parent_incomplete` 必须明确 `action_candidate=false`、`review_required=true`、`incomplete_reason`，并使用区别于普通 orange media card 的弱化/警告展示样式；它只用于人工审查，不授权点击或 PathGraph action。
- v87 后，密集媒体卡片行允许有限的占位卡片槽推断：如果同一行至少有 4 个 peer cards、当前候选只有小图标/placeholder visual、并且存在标题/文字 child 作为语义锚点，可以用 peer row 的 slot 几何推断完整卡片父框。必须记录 `original_visual_bbox`、`inferred_slot_bbox`、`child_anchor_bbox` 和 `slot_inference.reason=dense_row_placeholder_visual_slot_inferred`。没有文字锚点、非密集行、被 parent 裁剪过小或会跨 sibling 的候选，仍必须保持 `card_parent_incomplete` / `needs_review`。
- 没有父子关系的元素不能重叠合并。
- 同一行相似卡片可以组成 card group。
- 不同大小、不同语义的卡片不能强行放进同一组。
- 卡片父框不能跨入下一分区标题。
- 卡片中的图片、标题、描述和小按钮如果具有视觉包含或语义归属关系，应作为同一父卡片的子元素。
- 不完整露出的卡片只能标为 visible-part / review-only，不能强行补全成完整卡片。
- 底部视口边缘只有标题/文字碎片露出时，如果存在可信 section title，可聚合为 `partial_visible_card`；section title 自身必须保留为 title/text。
- `partial_visible_card` 的视觉扫描不能只受 OCR/text union 的窄主栏 bbox 限制；在可信 section title 锚定下，可以沿同一主内容行向截图右侧扩展扫描，以补全没有 OCR 文本但仍可见的同排 partial card。
- 没有 section title 证据的聊天输入栏、发送按钮、工具栏图标或普通消息文本，不能触发 `partial_visible_card`。
- `partial_visible_card` 只表示当前视口可见部分，不是完整卡片，也不授权点击。
- 中间主栏的二次分区应优先保证页面详情可读，而不是追求一次性把所有小元素都编号完。

对子区编号时识别：

- card
- list item
- field
- button
- text block
- image / media
- table row
- detail panel
- form section

输出字段：

- `subregions`
- `numbered_items`
- `parent_child_relationships`
- `card_groups`
- `possible_actions`
- `read_only_regions`

## 5. OCR / 视觉 / 执行定位融合

融合顺序必须稳定：

1. 模型语义理解
2. OCR 文本锚点
3. 图像结构、contour、颜色、separator
4. 4B / VISTA 精准定位
5. rerank
6. gate dry-run

融合规则：

- 模型 bbox 是候选，不是最终真相。
- OCR 可以校准文字位置。
- 视觉结构可以校准大区域边界。
- 执行定位链只做 dry-run，不点击。
- Gate 只判断候选是否可继续审查，不授权执行。

输出字段：

- `fused_bbox`
- `evidence_sources`
- `conflict_reason`
- `final_display_bbox`
- `grounding_status`
- `gate_status`

## 5.1 Stage2 编号过滤规则

Stage2 编号必须以已经校准的栏 bbox 为边界，不能继续把别的栏里的 OCR 文本或候选混进来。

规则：

- `screen_map.sections` 这类结构区 hint 只用于 Stage1 分栏和栏级定位，不进入 Stage2 编号。
- 当同次识别因初始 inventory 覆盖不足触发 OCR content recovery 时，去重后的 recovered OCR 候选必须先进入 Stage1 deterministic root partition，再进入后续 Stage2 supplemental numbering。Stage1 和 Stage2 不得分别读取恢复前、恢复后的两套候选集。
- 当一个宽、高均占主要窗口面积的 `DataGrid` / table 容器存在时，容器内部的高支持列边界只能作为表格内部结构，不能直接升级为根级侧栏切线。只有与该容器真实左边界对齐的切线才可继续参与侧栏判断。顶部栏恢复必须同时具备宽顶部语义区域和同图水平分隔线证据，不能使用表格前几行推导出的 `top_end` 吞并主内容。
- 每个 item 必须中心点落在当前栏 bbox 内，或与当前栏有足够交叠，才允许成为该栏的编号项。
- 当 `right_sidebar` 从主内容中拆出时，右栏内部的 OCR/text 子项也必须随右栏一起归属，不能留在 `primary_area`。
- 同级栏位之间没有父子关系时，编号结果不能跨栏重复展示同一个内容。
- 顶栏、侧栏、底栏的 direct numbering 可以使用视觉小控件检测，但检测 crop 只能是该栏内部的控制带，不得扫描到主内容。
- 顶栏 / header 的横向小控件不能长期保留为 glyph-only 框。视觉候选必须先按最小 hit-area 扩展，再可用相邻控件中心距推断横向 slot 宽度，最后裁回父栏 bbox；该扩展只改变 review/display 框，不代表点击授权。
- 顶栏 / header 中横向控件数量足够时，应在整条 `topbar_control_strip` 下按相邻中心距生成 display-only `topbar_control_cluster`。cluster 只用于表达播放控制、搜索/状态、右侧工具、窗口控制等“相邻控件组”的证据；不能替代栏 bbox，不能改变子按钮授权，不能作为可执行 PathGraph 节点。
- 顶栏里没有明确单独动作语义的长条区域，例如播放器条、状态条、搜索容器或 now-playing 区，应该生成非动作 `review_parent` / container，而不是只留下多个孤立 icon 子框。
- 侧栏 direct numbering 不能把 icon/OCR 的窄碎片直接当作最终按钮框。具有视觉或语义证据的侧栏项必须扩展为完整 `nav_item` / row hit-area；没有证据的碎片只能保留为 `sidebar_review_region`，不能作为动作候选。
- `nav_item` 必须至少有一种证据：局部图标/文字像素、OCR/text/member/card/notice 等语义证据、UIA/control 证据，或稳定 row 背景证据。无证据的边线、空白、stage 边界不能升级为 `nav_item`。
- `notice_region` 内的公告正文、说明文本或 notice child 不能继续保持 `nav_item`。除非有明确点击证据，否则必须降级为 `notice_item` / text child，并保留 `original_role` 用于审计。
- 当一个 `nav_item` 同时跨越公告、成员列表、header、消息区或其它父区域边界时，它不是合格动作候选。系统必须尝试拆分；拆分证据不足时降级为 `boundary_review_region` / `needs_review`，记录 `boundary_violation`、`original_role` 和 `bbox_policy`，不能保留为可执行-looking row。
- 聊天/会话类主内容必须逐步形成语义父框：文本气泡是 `message_bubble`，图片/表情是 `image_message`，卡片消息是 `message_card`，它们再归入 display-only `message_item`。时间戳和发送者只能作为 child evidence，不能单独 promotion 为 action。
- text-only `message_bubble` 缺少可见气泡背景候选时，`message_item` 可以保守扩展 display bbox 并记录原始 bbox；该策略只用于审查图显示，不改变 child item，也不授权点击。
- `image_message` 只有核心图片/表情 bbox 而缺少完整外层消息槽证据时，`message_item` 可以保守扩展为 `message_item_image_background_expanded_needs_review`，并应给左侧预留头像/间隔槽位，避免父框只贴住图片核心。必须记录 `raw_bbox_before_policy`，并保持 `review_required=true`、`action_candidate=false`、`execute_binding_enabled=false`。该扩展只能作为人工审查槽位，不能包装成可执行消息节点。
- `message_card` 内部的标题、转发摘要、图片说明、链接摘要等连续内容行必须标为 `message_card_content` / review-only，不能被扩成普通 `message_bubble`。如果父 `message_card` bbox 过高，只有顶部连续内容簇可以继承 card content 关系；遇到明显垂直断裂后的后续文本、时间戳、发送者或气泡必须重新作为普通消息候选处理。
- 普通主内容卡片行分组器只能处理非聊天媒体卡片。`message_card`、`message_card_content`、`message_bubble`、`image_message` 不能进入 `media_card_group`，否则会把聊天卡片内部内容重复包装成普通媒体卡片行。
- 一个 `message_item` 不能跨多个 timestamp start anchor。吸收后如果同一候选父框含多个 timestamp，应以最后一个 timestamp 到当前 message core 为准，前面的 timestamp / sender 不能被硬合并进后续消息。
- `message_item` 的每个成员必须反写 `semantic_parent_group_id`，让机器可读结构能复盘 child 属于哪条消息。时间戳、发送者、头像、等级等上下文 child 必须写入 `message_context_role`，例如 `timestamp`、`sender`、`avatar`、`sender_or_level`。这些字段只是证据层，不改变 overlay bbox，也不授权 Execute。
- overlay 必须把 `message_context_role` 以区别于普通 text 的高对比样式显示出来，并能看出它指向哪个父 `message_item`。如果全图标签太密导致看不清，应生成局部放大审查图或 context-only review 图，而不是把 JSON 证据当成可视化通过。
- 右侧成员列表这类连续成员行应生成 `member_list_region` 父框；`notice_region` 和 `member_list_region` 是兄弟区域，不能被单个 `nav_item` 跨越。
- 如果成员行已经被侧栏 evidence filter 合并成 review container，父框合成必须读取 children 中的原始成员语义；合并容器只能作为 bbox evidence，不能污染 `member_item_ids`。
- 如果过大的 `boundary_review_region` / `sidebar_review_region` 容器里包含成员列表标题 child，例如 `members` / `群聊成员`，成员列表父框必须使用该 child 的小 bbox 作为 `member_list_header` 证据，而不是把外层跨区大 bbox 当成 header。
- 合并连续 `sidebar_review_region` 时必须保留原 item 的嵌套 children；后续 member/list/header 重建可以从 children 恢复语义层级。
- `member_list_region` 可以包含从 oversized review container 抽取出的 header/row proxy，但这些 proxy 仍是 display-only 证据，不授权点击，也不表示外层 review container 可执行。
- 会话列表这类左列/列表列碎片应生成 display-only `conversation_row` 父框；它只用于学习草稿展示和界面详情，不授权打开会话。
- 当前 v14 只证明这些父框可在固定 trace 上出现，不证明聊天界面识别可靠。大图/表情消息仍需要同截图视觉候选恢复，text-only 发送按钮仍需要完整 hit-area 归一化。
- 有明确聊天上下文时，同截图视觉候选中的大块图片/表情可以合成为 display-only `image_message`；layout/content/review 背景框不能阻止这种恢复，但真实已编号图片/卡片不能被重复合成。
- `Send` / `发送` / `Submit` / `Confirm` 等 text-only 按钮标签必须扩展成完整按钮 hit-area；靠近父栏边界时应优先平移框保持宽高，而不是直接裁掉按钮宽度。
- text-only button hit-area 只是审查和安全识别证据，不代表该按钮允许点击；最终 submit/send/confirm 仍必须被 Gate 单独阻断。
- 当前 v15 证明 `image_message` 和 `text_button` 可以在固定 trace 上出现，但外层 `message_item` 完整性仍未通过，不能作为 demo 完成或识别可靠性结论。
- 聊天、评论、客服和协作工具这类底部输入区，应把底部工具图标行、composer 空白输入区域和 `Send` / `发送` 按钮合成为 display-only `input_toolbar_region` 父框。
- `input_toolbar_region` 只能由同一底部 composer stack 内的工具/输入/发送类候选合成；不能吞掉上一条消息、时间戳、发送者、聊天滚动内容或右侧栏。
- `input_toolbar_region` 仍必须保持 `review_required=true`、`action_candidate=false`、`execute_binding_enabled=false`、`artifact_is_authorization=false`。其中的 Send/发送按钮不能因为父框合成而获得点击授权。
- 如果 `input_toolbar_region` 高度较大，只能作为 conditional review evidence；必须人工目检确认没有吞掉上一条消息核心，不能凭 `outside_parent_bbox=0` 宣传视觉通过。
- 连续无证据的 `sidebar_review_region` 必须合并，并在 overlay 展示层用弱化背景样式显示，避免看起来像 `nav_item` / `control`。推荐使用灰蓝虚线框、`review-only` 小标签、`display_layer=review_background`、`number_policy=hide_stage_number` 和低视觉权重；不能使用主编号橙色控件样式。它们只用于人工审查，不参与 PathGraph action candidate，也不授权点击。
- 主内容的结构大框、页面 section hint、整页 primary area hint 不能作为 `media_card` 或 `media_card_group` 编号项。

## 6. 学习草稿生成

学习草稿必须接近模板的结构，但不能直接执行。

草稿包含：

- 页面摘要
- state guess
- screen inventory
- 界面详情
- 区域层级
- 编号元素
- 可能动作
- read-only 区域
- needs-review 区域
- unsafe / blocked 区域

草稿必须明确：

- 这是候选草稿，不是 Runtime PathGraph。
- 需要人工审查后才能进入模板或 PathGraph candidate。
- 不授权点击、输入、提交或 Execute 绑定。

## 7. PathGraph 草稿预览

根据学习草稿生成只读 PathGraph 预览。

允许生成：

- state node
- region node
- candidate action node
- read relation
- possible transition
- blocker

禁止生成：

- Runtime PathGraph promotion
- Execute 绑定
- live click
- live fill
- submit / send / confirm

## 8. 人工审查与修改

面板必须提供简单编辑能力，不要求用户手改 Markdown 或 JSON。

可修改：

- 区域名称
- 区域类型
- bbox
- parent-child 关系
- action 类型
- 是否 review-only
- 是否可进入 PathGraph candidate
- blocker 理由

推荐交互：

- 原图弹窗
- 大图框选
- 表单式修改
- 下拉选择类型
- 保存为 reviewed draft

## 9. 失败分类

每次真实界面测试后，不能直接修单图。必须先把失败归类到可复用层。

失败分类：

- `stage1_region_split_failed`
- `region_bbox_too_narrow`
- `region_bbox_too_large`
- `region_boundary_confused`
- `sidebar_items_missing`
- `topbar_items_missing`
- `main_subregion_split_failed`
- `card_parent_child_failed`
- `section_heading_swallowed`
- `ocr_anchor_missing`
- `coordinate_transform_error`
- `grounding_miss`
- `gate_wrong_reject`
- `gate_wrong_accept`
- `stale_trace_or_overlay`
- `stage_order_violation`
- `old_result_residue`
- `overlay_not_refreshed`
- `progress_without_evidence`
- `duplicate_structure_region`
- `non_parent_overlap`
- `model_prompt_too_coarse`

修复规则：

- 先修通用流程或合同。
- 再修对应 parser / model prompt / locator / fusion 层。
- 不允许把单张截图的局部补丁包装成学习模式主策略。

每个失败修复都必须回答：

1. 可见失败是什么？
2. 违反了哪个通用 invariant？
3. 修复位置是模型 prompt、parser、栏定位、编号定位、融合、面板展示，还是测试？
4. 为什么不是只修这个 app？
5. 用哪张旧图保护已有正确结果？
6. 用哪张新图验证通用性？
7. 这次修复有没有放松安全边界？

## 10. 面板展示

学习产物回放只需要清晰展示三块：

- 截图 / 编号图
- 界面详情
- PathGraph 草稿

附加信息：

- trace
- evidence
- needs-review list
- 人工修改入口

模板和学习草稿必须分开显示，不能混在同一个视图里。

面板刷新规则：

- 每次开始新识别，必须清空旧学习草稿、旧路径图、旧界面详情和旧融合框。
- 新识别未完成前，历史结果只能出现在“历史学习草稿”，不能混入当前结果。
- 整屏理解、编号选择、精准定位、融合结果各阶段必须显示真实证据状态。
- 如果某阶段没有证据，显示 `not run` / `not covered` / `observe-only`，不能显示完成。
- 最终截图区域必须展示当前最新 overlay。
- 用户不需要点击下方候选条目才看到框。

## 11. 当前实现约束

当前 `app.learn.recognition.two_stage` 仍有 parser / heuristic 驱动的 scaffold。它可以作为临时显示和回归工具，但不能代表最终学习模式主流程。

后续实现必须以本文合同为准，把主链路调整为：

```text
绑定 / 截图
-> 第一次模型调用：整屏分栏
-> 栏精准定位
-> 第二次模型调用：按栏识别内容
   -> 顶栏 / 侧栏 / 底栏：直接编号定位
   -> 中间栏：二次分区后编号定位
-> OCR / 视觉 / 执行定位融合
-> 学习草稿
-> 只读 PathGraph 预览
-> 人工审查 / 修改
```

一句话总结：

先整屏分栏，栏必须完整；再栏内编号，控件间距只用于分组；中间栏先二次分区再编号；最后融合成只读学习草稿和路径图预览。

## 12. 回归保护要求

任何学习模式识别策略改动都必须保护已有相对较好的结果。这里的保护对象不是单独的 Apple Music，而是“保护集”里的每一个界面。

当前必须保护的回归样本：

- Apple Music：用于保护顶栏、左侧栏、主内容连续区域、媒体卡片父子关系和融合 overlay；它是当前最强 Stage1 基线之一，但不是唯一回归对象。
- Python.org：用于保护浏览器 chrome、网页 header、primary area、右侧 floating/scroll review 归属，防止网页 surface 被 Apple Music 特化污染。
- QQ：用于保护聊天/协作软件的大栏结构，尤其是会话列表、聊天线程、右侧栏和底部输入区的 Stage1.5 需求。

保护集扩展规则：

- 新界面一旦被标记为 accepted、conditional pass、stage1_geometry_ready 或有明确可复用价值，就进入保护集。
- 进入保护集后，每次策略变更都必须一起复跑；不能只回归 Apple Music。
- 如果某个保护样本退化，必须先修复通用 invariant 或回滚该策略，再继续新增界面或推进 Stage2。

执行要求：

- 改策略后必须复跑当前保护集的全部界面，确认已经识别完整或已知 conditional 的区域没有被破坏。
- 如果新界面暴露问题，只能把问题归类成通用 invariant，再调整流程。
- 调整后必须重新复跑完整保护集，确认没有把旧界面搞坏。
- Codex 必须查看每张生成的 overlay 图，再向用户汇报。
- 没有目检截图时，只能说“脚本生成了结果”，不能说“识别效果变好”。

## 13. Stage1 几何通过不等于粒度通过

Stage1 report 必须同时区分两层结论：

- `region_selection_audit`：只检查大栏几何是否合法、是否明显越界/重叠/过窄。
- `stage1_granularity_review`：检查大栏是否还需要 Stage1.5 子栏拆分。

规则：

- `region_selection_audit=passed` 不能被解释成 reviewer full pass。
- 如果 `stage1_granularity_review.status=stage1_geometry_passed_needs_granularity_review`，只能说明 Stage1 大栏几何可以继续审查，但还不能直接进入最终内部编号结论。
- 浏览器网页里，`primary_area` 可以先表示完整页面主体；如果需要中间内容列、右侧浮动/滚动区或网页 section，必须在 Stage1.5 中拆，不要在 Stage1 写死具体网站宽度。
- 聊天/协作软件里，如果 primary 内同时包含会话列表、聊天线程、底部输入区，应标记 `primary_contains_multiple_work_panes` 并进入 Stage1.5。
- Stage1.5 仍是 display-only / review-only，不授权 Execute，不生成 Runtime PathGraph。

Stage1.5 report 输出要求：

- `stage1_5_partition`：记录 Stage1.5 子区建议、状态、证据和安全边界。
- `stage1_5_overlay_path`：当存在 Stage1.5 子区时，必须生成 Stage1 蓝框 + Stage1.5 橙框的同图 overlay；不要求用户点击候选后才看到框。
- runner JSON summary 必须输出 `stage1_5_overlay_path`、`stage1_5_status`、`stage1_5_subregion_count`，方便复跑审查。
- Stage1.5 子区必须裁剪在父栏内；可以用高重叠证据识别轻微越界的候选，但最终显示 bbox 不能超出父栏。

当前 v79 保护样本：

- Python.org：`browser_primary_scope_ambiguous_full_page_vs_content_column`。
- AppleMusic：`stage1_geometry_ready`。
- QQ：`primary_contains_multiple_work_panes`。

当前 v79 状态：

- Python.org：Stage1 保持完整页面主体，Stage1.5 生成 `content_column`；后续编号必须优先使用该内容列或明确子区。
- AppleMusic：保持 `not_needed_stage1_geometry_ready`，不生成 Stage1.5，作为保护集基线之一。
- QQ：Stage1.5 生成 `conversation_list`、`message_thread`、`bottom_composer`；`conversation_list` 必须覆盖父栏左边界到 `message_thread` 左边界，`message_thread` 和 `conversation_list` 都必须在 `bottom_composer` 上边界结束。v79 中，如果 raw `bottom_composer` 横向吞入 sibling pane，必须按 active `message_thread` channel 收敛，并在 `stage1_5_boundary_review` 里保留原始 bbox 和约束原因。
- GPT v79 已完成三图视觉审核并保存到 `artifacts\chatgpt_reports\stage1_5_v79_gpt_audit_result_external_edge.json`：Python.org `CONDITIONAL PASS`，AppleMusic `PASS`，QQ `CONDITIONAL PASS`。后续编号只能基于 Python.org 的 `content_column` / header 子区和 QQ 的 conversation/message/composer 核心子区继续；QQ `bottom_composer` 横向越界已收敛，但纵向/空白 overreach 必须保留 review 标记，不能当作精确输入区。任何后续策略变更都不能只回归 AppleMusic。
- v85 后，full two-stage pipeline 必须把 Stage1.5 子区作为 Stage2 编号输入：如果 Stage1.5 对某个 broad parent 生成了 `content_column`、`conversation_list`、`message_thread`、`bottom_composer` 等子区，Stage2 必须编号这些子区，不能再直接编号 broad parent。Stage1 broad parent 仍保留为结构显示框，不收缩、不授权执行。
- Stage1.5 子区进入 Stage2 时，必须携带落在该子区内的 parent item ids；不能只传子区壳本身，否则页面详情和 PathGraph 草稿会丢掉内部 card/text。GPT v85 图审保存在 `artifacts\chatgpt_reports\stage2_v85_stage1_5_input_policy_gpt_audit_result.json`，三界面均为 `CONDITIONAL PASS`，只能证明该数据流没有明显 protected-set regression，不能宣传 full pass 或识别准确率。
