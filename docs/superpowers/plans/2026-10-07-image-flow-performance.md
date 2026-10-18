# 图像核验流程和性能测试 / Image-check flow and performance

范围：当前维护源码，全新自有低风险窗口及数据根；不发布、打包或更改版本。真实输入只走项目门控接口。 / Source only, fresh owned window/data, maintained gated input only; no release changes.

- [x] 本轮真实教学生成学习段，Main 查看原图并做非人工 QA，生成局部规则、保存确切版本，库关闭重开两次确认 pin。 / Fresh teaching, nonhuman QA and exact library pins after two reopenings.
- [x] 图像开启和关闭定义仅 `image_check` 不同；相同定位/动作/结果条件，交替完成 c03 三对两步流程，新数据每对更换。 / Three alternating paired flows; only image-check configuration differs.
- [x] 同一窗口/连接连续使用；未跳转负例保留原请求后 Agent 判失败，无重复点击；死宿主恢复未测。 / Continuous same-session flow and failed-transition review passed; dead-host recovery untested.
- [x] 六个实际成功 proof 复算、两个反向状态原图拒绝、两个派生双副本离线歧义拒绝；首次失败保留，正常收尾核对。 / Six proof replays, two actual opposite-state negatives and two derived ambiguity checks; cleanup and first failures retained.
- [x] 端到端与已分类核验/可观察 Agent 等待分开；其他动作/截图/调用方阶段未完全分类，total calls/token/pure inference 仍未知。 / Full-flow timing separated from partial verification/review timing; incomplete phase coverage remains explicit.
- [x] Main 完成主链后 Sol 独立只读审核证据与冻结；collector 后续冻结依赖元数据变化单独说明，未冒充独立桌面复跑。 / Independent evidence audit follows Main; collector metadata change and lack of a second live run are explicit.

单一合成应用的有限试验不能证明所有外部软件的稳定率；结果相似度不是准确率，旧 benchmark 不充当本轮数据。 / A bounded synthetic-app experiment is not general accuracy/stability proof; prior cohorts are not reused.
