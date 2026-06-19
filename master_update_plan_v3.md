# Quant Trade System Master Update Plan V3

> 模型规范优先级：V3 定义系统架构和产品主线；
> `multi_horizon_model_upgrade_plan.md` 定义当前神经模型的详细目标、
> 标签、验证门槛和 checkpoint 晋升规则。模型专项文档更新时，V3
> 必须同步记录不可违反的产品与治理约束。

## 0. 文档定位

### Previous System Version
* V1 解决的是系统从零到可用。
* V2 解决的是系统从“能分析”到“能复盘、能解释、能沉淀样本”。

### The Goal of This Version of the System
V3 的目标是把系统推进成一个更接近专业量化辅助决策工作台的个人系统：

`市场终端 + 量化计划器 + 风控纪律层 + 研究治理系统`

这份文档不是要把系统改成机构级自动交易平台，也不是要追求更复杂的模型。V3 的核心问题是：

- 信息能不能更快被看见
- 建议能不能更可靠地执行
- 信号能不能快速和提前被捕捉，从而促进交易盈利
- 信号能不能被持续验证
- 研究结果能不能反哺下一次决策
- 系统能不能在单人使用场景下保持简单、稳定、可维护

V3 的产品判断是：

`盈利能力来自更早发现高质量机会信号、更早发现市场风险信号、更少执行低质量动作、更严格复盘真实结果，而不是堆更多模型或制造更多提醒。`

### 0.1 审阅结论

本轮修订的方向是正确的，尤其是：

- 把“快速捕捉可交易信号和市场风险信号”明确提升为收益相关目标
- 把系统定位从单页分析工具升级为个人量化决策工作台
- 把前后端分离作为 V3 的核心工程目标
- 把交易时段、夜间、周末任务拆成不同节奏，避免前端等待重计算，从而使前端数据可用性更高
- 把图表、模型接口和后台调度都约束为“服务交易决策”，而不是服务展示复杂度

V3 后续所有改造都应遵守五条约束：

- 前端只展示当前快照，不承载重计算
- 后台任务按明确节奏产出结果，不靠页面点击触发系统主流程；前端可以通过 Settings 修改任务节奏配置
- 每个交易建议都要能被真实执行结果、计划质量和后续收益验证
- 真实成交记录以 Robinhood CSV 导入为 source of truth，不再依赖手动补录成交明细
- 远程 LLM 和研报分析只能作为解释、摘要和辅助证据来源，不能直接生成交易动作

---

## 1. 外部系统给我们的启发

### 1.1 参考系统

V3 参考的系统分三类。

第一类是量化执行与回测框架：

- QuantConnect / LEAN
- Freqtrade / FreqAI

这类系统最值得借鉴的是模块边界：

- universe selection
- alpha / signal
- portfolio construction
- risk management
- execution / review

对本系统的启发：

- 把“信号生成”和“仓位建议”继续分开
- 把“风险阻断”和“解释展示”继续分开
- 所有信号都必须能追溯到对应模块，而不是混在页面逻辑里

第二类是量化研究平台：

- Microsoft Qlib
- FinRL

这类系统最值得借鉴的是研究治理：

- 数据处理
- 特征与模型训练
- 回测验证
- 实验记录
- 模型 / 策略晋升

对本系统的启发：

- 周末研究不应该只是报告，而应该进入策略治理
- 每个模型都要有统一接口、版本、验证状态和晋升状态
- 研究输出必须能变成 snapshot / journal，而不是只存在 markdown 里

第三类是投资决策终端：

- TradingView
- Koyfin
- TrendSpider
- Composer

这类系统最值得借鉴的是产品体验：

- watchlist 一眼看出变化
- alerts 是多条件、分优先级的
- dashboard 先给结论，再给细节
- 图表、新闻、基本面和组合信息不割裂

对本系统的启发：

- 前端应该像工作台，而不是报告浏览器
- 图表应该服务于行动判断，而不是展示技术指标全集
- 告警应该按优先级进入 Slack / Email / UI，而不是平铺所有变化

### 1.2 我们不该照搬的地方

不建议照搬：

- 全自动实盘交易
- 复杂多用户权限系统
- 大规模低延迟日内交易架构
- 让 LLM 直接决定交易动作
- 过早扩展到几千只股票全市场扫描
- 为了“研究感”保留大量低价值指标和页面

我们的系统核心仍然是个人交易辅助，而不是券商、基金公司或高频交易平台。

### 1.3 V3 借鉴原则

V3 借鉴外部系统时遵守三条原则：

- 借鉴模块边界，不照搬复杂机构基础设施
- 借鉴研究治理，不把模型复杂度当成目标
- 借鉴终端体验，不把页面做成信息堆叠

最终系统应该更像：

`个人投资决策终端 + 后台量化研究流水线`

而不是：

`自动交易机器人 + 大而全研究平台`

---

## 2. 当前系统定位

当前系统已经形成了几个很有价值的主线：

- 核心 ETF 引擎
- 卫星仓雷达
- 纪律与风险层
- 夜间计划
- 盘中监控
- 收盘复盘
- Robinhood CSV 回流
- Slack / Email / WebUI 通知
- 本地 SLM 转述 + 远程 LLM 深解释
- 周末研究
- 策略验证与实验日志
- nightly decision journal

这套系统已经不再是一个简单策略面板，而是一个围绕个人真实交易节奏设计的决策系统。

### 2.1 真实交易循环

`夜间回测和计划 -> 盘前查看 -> 手动执行 -> 盘中监控 -> Robinhood CSV 回流 -> 收盘复盘 -> 周末研究`

这条循环仍然是系统主线：

- 夜间生成可执行计划
- 盘前查看计划和作废条件
- Robinhood 手动下单
- 交易时段由系统做风险和机会监控
- 收盘后通过 Robinhood CSV 回流真实交易
- 夜间复盘计划质量和执行质量
- 周末做更长时间研究与策略治理，包括历史数据挖掘、长窗口回测、核心 ETF / 卫星仓候选更新、结构性风险扫描
- 远程 LLM API 可用于研报、新闻和事件材料的摘要、对比和解释，但其输出必须进入结构化证据层，不能直接变成买卖建议

### 2.2 三个时间尺度

V3 必须明确区分三个时间尺度：

- `交易时段轻量循环`
- `夜间计划与复盘`
- `周末长周期研究`

交易时段轻量循环：

- 默认每 30 分钟运行一次
- 可配置为 15 / 30 / 60 分钟
- 只做市场风险、盘中战术信号、计划内触发和数据健康检查
- 不做重型回测、不训练模型、不生成长报告

夜间计划与复盘：

- 导入或等待 Robinhood CSV
- 更新行情、事件、风险状态
- 评估计划执行与价位失效
- 生成次日计划
- 更新 nightly journal

周末长周期研究：

- 做更长窗口的数据挖掘
- 下载或读取已配置来源中的研报、市场新闻和事件材料，并对其进行摘要、归因和风险提示
- 做策略验证和候选策略晋升/降级建议
- 复盘核心 ETF 与卫星仓的周度表现
- 反哺下周计划权重和候选优先级

周末研究必须遵守：

- 数据来源、生成时间和 freshness 必须可见
- LLM 输出必须标记为辅助解释，不得覆盖量化信号和风控规则
- 研究结果必须写入 snapshot / journal，方便下周计划引用和后续复盘

### 2.3 V3 的架构定位

V3 后系统应该从：

`Streamlit 前端直接组织计算`

升级为：

`后台任务生成快照 + FastAPI 提供稳定 DTO + React 前端快速展示`

V3 的任务是让这个循环更快、更清晰、更可信，同时去掉 Streamlit rerun 对用户体验的影响。

---

## 3. V3 总目标

### 3.1 产品目标

V3 完成后，用户每天打开系统时，应该能在 30 秒内回答：

- 当前有没有必须关注的风险
- 明天有没有可执行动作
- 核心 ETF 是否需要调整
- Top 3 卫星仓是否有变化
- 哪些计划昨日触达但没有执行
- 哪些建议失效或不可执行
- 当前系统信号是否仍然值得信
- 当前市场是否出现盘中战术机会
- 当前数据是否新鲜、可靠、可用于决策

交易时段内，系统默认每 30 分钟运行一次轻量市场检查；紧急风险可以通过规则立即升级为 Slack / Email 提醒。

### 3.2 工程目标

V3 完成后，系统应具备：

- 更清晰的市场终端层
- 更直观的图表式显示来辅助决策
- 更严格的计划可执行性追踪
- 更完整的实验和研究治理
- 更简洁的模型接口，从而可以容易替换模型、策略和解释器
- 更稳定的数据源与 freshness 管理
- 更克制的盘中战术信号
- 更集中、更低噪声的 UI 与 Slack 交互
- 更清晰的前后端分离，让前端只读当前结果，不承担重计算
- 更明确的后台任务调度节奏，让交易时段、夜间、周末各做各的事
- 更统一的 Settings 配置入口，让任务频率、LLM / SLM、Slack / Email、数据源和运行开关都集中管理
- 更可靠的 Robinhood CSV 导入链路，把真实成交记录作为复盘和账户同步的唯一事实来源

### 3.3 非目标

V3 不做：

- Robinhood 实盘自动下单
- 高频交易
- 毫秒级行情
- 让 LLM 直接生成买卖决策
- 复杂团队协作权限
- 为了技术炫耀引入过重基础设施
- 把 React 前端做成复杂金融终端复刻版
- 在 HTTP 请求里同步执行长时间量化任务

说明：

前后端分离是 V3 的核心架构目标。V3 不再把 Streamlit 作为长期主界面，而是要把当前 Streamlit 的“点击就重跑脚本”模式，替换成：

`后台任务按计划生成快照（交易时段轻量监控，夜间计划复盘，周末长时间研究） -> 后端 API 读取快照 -> 前端快速展示当前结果`

Streamlit 可以在迁移期短暂保留，但 V3 的最终目标是移除 Streamlit 主界面。

---

## 4. V3 核心方向

### 4.1 市场终端层升级

#### 4.1.1 目标

把系统从“展示很多分析结果”进一步改成“像一个日常可用的市场决策终端”。

当前 Dashboard 已经能用，但下一步应进一步强化：

- 变化优先
- 风险优先
- 可执行动作优先
- 原始数据后置

#### 4.1.2 新增 Market Monitor Snapshot

新增统一快照：

`storage/state/market_monitor_snapshot.json`

建议包含：

- major_index_status
- core_etf_status
- tactical_tool_status
- volatility_status
- market_breadth_proxy
- news_event_pressure
- intraday_tactical_state
- top_dashboard_changes

第一版不追求复杂行情终端，只先整合已有数据：

- SPY / QQQ / VOO / SCHD
- SQQQ / PSQ / SH
- VIX proxy 或现有 risk gate
- 新闻事件压力
- 盘中战术状态

交易时段更新节奏：

- 默认每 30 分钟生成一次 market monitor snapshot
- 可配置为 15 / 30 / 60 分钟
- 当 risk gate / tactical state 进入 `ACTIONABLE` 或 `URGENT` 时允许即时更新
- 每次更新只做轻量计算，不触发全量回测或模型训练

#### 4.1.3 Dashboard 改造方向

Dashboard 第一屏固定为 4 个区域：

- 今日结论
- 风险与纪律
- 市场状态
- 今日变化

每个区域只展示 3-5 个重点字段。

建议图表：

- intraday index pressure sparkline
- core ETF target vs current weight bar
- Top 3 satellite score trend
- plan quality rolling rate

图表只显示决策需要的信息，不展示完整研究指标。

详细表格继续后置到：

- Core ETFs
- Satellite Radar
- Risk & Discipline
- Operations

#### 4.1.4 Watchlist / Candidate UX

候选池不应该再像普通表格。

建议显示为：

- Top 3：重点列表
- Top 10：紧凑比较表
- Newly promoted：新进入
- Downgraded：降级
- Removed：移除

重点不是更多字段，而是更快看出：

`谁变了，为什么变了，要不要行动。`

---

### 4.2 建议可执行性追踪

#### 4.2.1 目标

很多系统只问“信号是否正确”，但真实交易里更重要的问题是：

- 建议有没有执行机会
- 买入区间是否触达
- 是否跳空失效
- 用户是否按计划执行
- 未执行是因为错过、主动放弃，还是系统区间不合理

V2 已经加入：

- reachable
- missed_reachable
- price_failure
- invalidated

V3 要把这些指标正式变成系统核心质量指标。

执行质量比信号方向更贴近真实收益。

如果一个信号方向正确，但计划区间长期不可触达，系统也应该降低它的可信度。

#### 4.2.2 新增 Plan Quality Snapshot

新增：

`storage/state/plan_quality_snapshot.json`

按滚动窗口统计：

- plan_count
- action_count
- reachable_rate
- missed_reachable_rate
- invalidation_rate
- price_failure_rate
- executed_rate
- follow_rate
- average_entry_slippage
- post_entry_next_close_return
- post_entry_5d_return

统计维度：

- core_etf
- satellite
- tactical
- by_symbol
- by_action
- by_regime

#### 4.2.3 UI 显示

Dashboard 只显示：

- 计划可执行率
- 触达未执行数
- 价位失效率
- 最近 5 次计划质量

Operations 或 Risk 页提供详细明细。

#### 4.2.4 Slack 命令

新增命令：

- `计划质量`
- `最近计划`

输出：

- 最近计划数
- 可执行率
- 触达未执行
- 价位失效
- 最常失效的标的

---

### 4.3 研究治理与策略晋升

#### 4.3.1 目标

V2 已经有 strategy validation 和 experiment journal。

V3 要把它升级成“策略治理”：

- 不是只知道策略最近表现如何
- 而是知道策略是否应该继续作为默认
- 候选策略何时可以晋升
- 旧策略何时需要降级

#### 4.3.2 策略状态机

每个策略增加状态：

- RESEARCH
- CANDIDATE
- SHADOW
- DEFAULT
- DEGRADED
- RETIRED

解释：

- RESEARCH：只做研究，不进入正式建议
- CANDIDATE：可进入周末研究
- SHADOW：跟随生产信号并记录表现，但不影响交易建议
- DEFAULT：当前正式策略
- DEGRADED：仍保留，但不应主导建议
- RETIRED：不再跑，除非手动恢复

#### 4.3.3 新增 Strategy Registry State

新增：

`storage/state/strategy_registry_state.json`

包含：

- strategy_id
- status
- promoted_at
- downgraded_at
- default_since
- validation_window
- last_validation_status
- reason

#### 4.3.4 晋升规则

策略不能因为一次回测好就晋升。

建议第一版规则：

- 连续 N 次 weekend validation 优于默认策略
- 覆盖样本数达到最低阈值
- max drawdown 不显著更差
- plan quality 不更差
- 至少通过一个不同市场 regime 的验证

#### 4.3.5 降级规则

默认策略进入 DEGRADED 的条件：

- 连续多次 REVIEW
- 核心 ETF 上默认策略排名落后
- 计划价位失效率显著升高
- Follow 交易收益明显不如 Ignore

第一版只给降级建议，不自动切换默认策略。

#### 4.3.6 统一模型接口

V3 要让模型可替换，而不是让每个模型都把自己的输入、输出和解释方式写进业务代码。

建议新增：

- `quant_core/models/interfaces.py`
- `quant_core/models/registry.py`
- `storage/config/model_registry.json`

统一接口：

- `fit(context) -> model_artifact`
- `predict(context) -> prediction`
- `explain(context, prediction) -> structured_reason`
- `validate(context) -> validation_result`

模型类型：

- rule_based
- finance_multi_asset_transformer
- llm_remote_explainer
- slm_local_narrator
- future_candidate_model

所有模型输出必须至少包含：

- model_id
- model_version
- generated_at
- input_window
- confidence
- signal
- reason_codes
- warnings

新模型必须先接入统一接口，再进入策略验证或周末研究。

#### 4.3.7 神经量化模型目标与治理约束

当前默认神经模型采用 `target schema v2`。模型的训练逻辑必须明确为：

```text
历史某个观察时点之前的行情与可用特征
  -> 对应历史中后来真实发生的 63/126/252 日结果
  -> 训练多周期概率预测模型
  -> 输入当前最新历史窗口
  -> 预测尚未发生的未来收益概率与区间
```

主训练目标：

- 未来 `63/126/252` 日绝对收益分布
- 未来收益大于零的概率
- 未来跑赢短期美债总回报的概率与超额收益
- P10 / P50 / P90 绝对收益区间
- 由当前价格换算出的 P10 / P50 / P90 未来价格区间
- 最大有利波动和最大不利波动

机会成本基准：

- 默认使用 `BIL` 作为短期美国国债总回报代理
- 该标的必须可以在模型配置中替换，例如改为 `SGOV`
- 短债基准用于判断承担股票风险是否值得，不是把长期国债 ETF
  当作无风险资产

辅助目标：

- 跑赢 `SPY` 的概率
- 相对 `SPY` 的超额收益
- 同一观察日期下的横截面排序和 Top 3 选择

辅助目标不能反过来替代绝对收益和短债机会成本预测。系统不允许仅凭
横截面排名将模型描述为“预测未来上涨”。

样本外验证至少包含：

- purged chronological walk-forward，禁止随机打乱时间序列
- 至少三个有效 folds
- 绝对收益 P50 的 MAE
- 上涨方向准确率和 Brier score
- 跑赢短债方向准确率和 Brier score
- Top 3 相对短债的实际超额收益
- P10 / P50 / P90 empirical coverage
- 辅助 Rank IC 和 Top 3 相对 SPY 超额收益
- 预训练模型与同架构从零训练的 ablation
- MoE expert collapse 检查

模型治理：

- 训练完成不等于投入生产
- validation 未通过时，模型只能输出 `SHADOW` 预测
- shadow 预测可以展示，但必须被生产闸门降级为 `HOLD/WATCH`
- validation 通过后只进入 `ELIGIBLE_FOR_MANUAL_PROMOTION`
- 用户必须在 `Research & Models` 手动晋升
- 晋升与 checkpoint version 严格绑定
- 每次重新训练产生新 version，并自动回到 `SHADOW`
- 旧 target schema checkpoint 必须拒绝加载，不能兼容性沿用

当前实施状态：

- target schema v2、双基准训练头、价格区间和验证指标已完成
- 旧相对排名 checkpoint 已失效
- 下一次操作必须是重新训练并查看 walk-forward 结果
- 只有验证通过并手动晋升后，夜间计划才能使用该版本的正式动作

---

### 4.4 数据可靠性与数据源治理

#### 4.4.1 目标

最近出现过价格拿不到或 `NaN` 污染的问题。V3 必须把数据可靠性提升为正式能力。

系统要明确区分：

- 数据源失败
- 数据源返回脏值
- 缓存过期
- 快照过期
- 当前值缺失
- 当前值来自 fallback

#### 4.4.2 新增 Data Health Snapshot

新增：

`storage/state/data_health_snapshot.json`

包含：

- quote_success_rate
- quote_nan_rejected_count
- quote_missing_symbols
- primary_source_success_rate
- fallback_source_count
- stale_price_count
- stale_snapshot_count
- last_successful_refresh_at
- last_failed_refresh_at
- provider_error_summary

#### 4.4.3 UI 显示

Dashboard 只显示简洁状态：

- Data: OK / DEGRADED / STALE / BROKEN
- 缺失价格数
- fallback 次数

Settings / Operations 显示详细来源和错误。

#### 4.4.4 Slack 命令

新增：

- `数据状态`

输出：

- 上次刷新时间
- 主源 / fallback 情况
- 缺失价格标的
- 是否有 NaN / invalid price 被拒绝

---

### 4.5 盘中战术层增强

#### 4.5.1 目标

盘中战术层不是要把系统变成日内交易系统，而是要更早捕捉：

- 大盘急跌
- 风险升级
- SQQQ / PSQ / SH 等防守工具机会
- 夜间计划内买点触发

#### 4.5.2 高频轻量采样

新增独立轻量采样对象：

- SPY
- QQQ
- VOO
- SCHD
- SQQQ
- PSQ
- SH

采样频率：

- market monitor: 默认 30 分钟
- tactical watchlist: 5-15 分钟
- non-market hours: 不采样或低频

解释：

- market monitor 用于整体风险和驾驶舱状态
- tactical watchlist 用于 SPY / QQQ / SQQQ / PSQ / SH 等少数战术工具
- 两者都不能触发重型回测或训练

记录：

- current_price
- pct_from_open
- pct_from_previous_close
- intraday_high
- intraday_low
- vwap proxy
- tactical_state
- alert_triggered

#### 4.5.3 战术信号分级

输出不要只有 buy / sell。

使用：

- INFO
- WATCH
- ACTIONABLE
- URGENT

动作类型：

- REDUCE_RISK
- TACTICAL_HEDGE
- PLAN_ENTRY_TRIGGERED
- DO_NOT_CHASE
- RISK_EXIT

#### 4.5.4 样本沉淀

盘中事件日志继续扩展：

- trigger_price
- 15m_return
- 30m_return
- close_return
- next_open_return
- was_alert_sent
- did_user_trade
- action_taken
- outcome_label

这不是立刻训练模型，而是为未来判断“哪些盘中提醒有价值”准备数据。

---

### 4.6 解释层升级

#### 4.6.1 原则

继续保持分工：

- 结构化原因引擎负责事实与因果来源
- 本地 SLM 负责转述
- 远程 LLM 负责复杂解释、调研和多信息综合

本地 SLM 不做交易推理，不替代结构化原因引擎。

#### 4.6.2 解释缓存治理

新增 explain cache health：

- cache_size
- hit_rate
- stale_count
- largest_kind
- last_cleanup_at

缓存按类型区分：

- core_etf_explanation
- satellite_candidate_explanation
- change_feed_narration
- discipline_narration
- news_summary_narration

#### 4.6.3 UI 交互

每个解释按钮都要显示：

- using local_slm / remote_llm
- model name
- generated_at
- cache_hit / fresh

解释不应该自动在首页触发。

---

### 4.7 UI 与交互效率

#### 4.7.1 总原则

V3 UI 的目标不是更漂亮，而是更快决策。

优先级：

1. 今日是否行动
2. 风险是否阻断
3. 哪些标的变化最大
4. 哪些建议可执行
5. 为什么
6. 原始明细

#### 4.7.2 减少宽表

当前已经开始压缩宽表。V3 继续要求：

- 默认表格不横向滚动
- 只展示决策字段
- 原始字段放折叠明细
- 重要变化优先列表化

#### 4.7.3 页面重新分工

建议最终页面：

- Dashboard：当天结论
- Core ETFs：核心仓计划与质量
- Satellite Radar：Top3 与候选池变化
- Risk & Discipline：阻断条件和纪律复盘
- Market Monitor：市场状态与盘中战术
- Operations：同步、报告、诊断
- Settings：所有配置

Market Monitor 可以先作为 Dashboard / Risk 的子区，成熟后再独立页面。

#### 4.7.4 图表式决策组件

V3 前端应该增加图表，但图表必须服务于交易判断。

推荐图表组件：

- `Risk Timeline`: 最近 1-5 天风险状态变化
- `Plan Quality Trend`: 最近 N 次计划可执行率
- `Core Weight Delta`: 当前权重 vs 目标权重
- `Top3 Rank Trend`: 卫星仓 Top 3 排名变化
- `Intraday Tactical Strip`: 盘中压力状态时间线
- `Data Freshness Strip`: 行情、事件、快照新鲜度

不建议第一版做：

- 大而全技术指标图
- 复杂 K 线画图系统
- 多窗口专业交易终端
- 需要大量前端状态管理的图表交互

先做“决策型小图”，再考虑完整图表。

---

### 4.8 前后端分离

#### 4.8.1 为什么需要前后端分离

当前系统已经明显不是一个简单 Streamlit demo。

现在前端需要展示：

- Dashboard
- Core ETFs
- Satellite Radar
- Risk & Discipline
- Market Monitor
- Operations
- Settings

后台又需要持续运行：

- market refresh
- nightly scheduler
- weekend research
- intraday tactical sampling
- Slack bot
- report generation
- Robinhood CSV import / reconcile

在 Streamlit 当前模式下，前端点击页面、切换标签、更新控件时，容易触发脚本 rerun。即使已经做了缓存和延迟加载，系统仍然天然存在一个问题：

`前端展示逻辑和后端计算逻辑绑得太紧。`

V3 应该把它拆开。

#### 4.8.2 目标架构

目标不是重写所有量化逻辑，而是保留 Python quant core，并用完整的 API + 独立前端替代 Streamlit UI。

建议架构：

```text
jobs.run_all
  -> market refresh worker
  -> nightly worker
  -> weekend research worker
  -> intraday monitor worker
  -> slack bot
  -> api server

api server
  -> reads storage/state/*.json
  -> exposes read-only dashboard endpoints
  -> accepts limited operations commands

frontend app
  -> reads api server
  -> renders instantly from snapshots
  -> never runs heavy quant computation
```

核心原则：

- 量化计算继续留在 Python 后端
- 前端只读取快照和发起明确操作
- 页面切换不能触发重分析
- 缺数据时显示 stale / missing，而不是现场同步重算
- Streamlit 不再作为目标 UI
- 迁移完成后删除 Streamlit 页面与依赖

#### 4.8.3 后端 API 范围

第一版 API 建议只做本地单用户。

技术选择：

- `FastAPI`
- 只监听 `127.0.0.1`
- 不引入数据库
- 继续读取 JSON / JSONL / Parquet 快照

第一批只读接口：

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/core-etfs`
- `GET /api/satellite-radar`
- `GET /api/risk`
- `GET /api/market-monitor`
- `GET /api/plan-quality`
- `GET /api/data-health`
- `GET /api/change-feed`
- `GET /api/news-summary`
- `GET /api/reports/latest`
- `GET /api/model-registry`
- `GET /api/job-status`
- `GET /api/settings`

第一批操作接口：

- `POST /api/actions/refresh-market`
- `POST /api/actions/run-nightly-once`
- `POST /api/actions/run-weekend-research-once`
- `POST /api/actions/import-robinhood-csv`
- `POST /api/actions/save-settings`
- `POST /api/actions/update-schedule`
- `POST /api/actions/start-job`
- `POST /api/actions/cancel-job`

操作接口必须满足：

- 明确返回 job status
- 不在 HTTP 请求里长时间同步跑重任务
- 需要时写入 command / job journal
- 前端轮询 job 状态

#### 4.8.4 前端路线

V3 前端目标是独立 Web App。

技术建议：

- `Vite + React + TypeScript`
- 本地单用户部署
- 通过 FastAPI 读取后端快照
- 通过 operation endpoints 触发明确任务
- 不引入复杂权限、团队协作或云部署

前端原则：

- 只做本地 dashboard
- 不做营销页面
- 不做复杂用户系统
- 重点是速度、布局和交互
- 任何页面切换都不能触发后端重计算
- 所有数据读取都必须显示 freshness / stale 状态

前端页面对应：

- Dashboard
- Core ETFs
- Satellite Radar
- Risk & Discipline
- Market Monitor
- Operations
- Settings

迁移路线：

1. 先把 FastAPI snapshot API、React 前端骨架和 `jobs.run_all` 新编排跑起来
2. 一次性迁移 Dashboard、Core ETFs、Satellite Radar、Risk、Market Monitor、Operations、Settings，并删除 Streamlit 主界面
3. 在新架构稳定后，再接入 Data Health、Plan Quality、Strategy Governance 和高级 Slack / Email 摘要

#### 4.8.5 快照契约

前后端分离的关键不是框架，而是稳定数据契约。

每个快照必须包含：

- `generated_at`
- `source`
- `freshness_status`
- `is_stale`
- `summary`
- `items`
- `errors`
- `warnings`
- `data_quality`
- `next_update_hint`

API 不应该把内部各种文件原样吐给前端，而要返回稳定 DTO。

建议新增：

- `quant_core/api/schemas.py`
- `quant_core/api/snapshot_loader.py`
- `jobs/api_server.py`
- `quant_core/jobs/job_registry.py`
- `storage/state/job_status.json`
- `storage/config/runtime_schedule.json`

#### 4.8.6 性能目标

前后端分离后的目标：

- Dashboard 首屏 < 1 秒读取本地 API
- 页面切换 < 300ms 到可见内容
- 后台重任务不阻塞前端
- API 返回 stale 状态，而不是卡住等待重算
- Jetson Orin Nano 上也能完整渲染首页

#### 4.8.7 Streamlit 的最终角色

Streamlit 是迁移期工具，不是最终架构。

建议演进：

- Step 1：先把新架构跑起来，新增 FastAPI snapshot API + React frontend + `jobs.run_all` 编排
- Step 2：一次性迁移日常页面和操作入口，并删除 Streamlit 主界面、旧页面和旧依赖
- Step 3：在新架构稳定后，再接入更高级的数据健康、计划质量、策略治理和模型接口

Streamlit 删除条件：

- React dashboard 能覆盖所有日常页面
- FastAPI 能提供所有页面所需 DTO
- Operations 能完成 Robinhood CSV、强制刷新、报告生成、设置保存
- Slack / Email / nightly / weekend research 不依赖 Streamlit
- 测试覆盖 API 和前端关键数据契约

---

### 4.9 后台任务调度

#### 4.9.1 目标

V3 后台任务必须有清晰节奏，而不是靠前端页面触发。

任务分三类：

- 交易时段轻量任务
- 夜间计划复盘任务
- 周末长时间研究任务

任务节奏由配置文件控制，并通过 Settings 页面修改：

- `storage/config/runtime_schedule.json`
- trading hours monitor interval
- tactical watchlist interval
- nightly run window
- weekend research window
- Slack / Email digest switches

前端只能修改配置或发起明确任务请求，不能在页面渲染过程中直接执行长任务。

#### 4.9.2 交易时段轻量任务

默认节奏：

- market monitor: 每 30 分钟
- tactical watchlist: 5-15 分钟
- data health: 每 30 分钟
- Slack / Email: 只推高优先级变化

允许配置：

- 15 分钟
- 30 分钟
- 60 分钟

交易时段任务只允许：

- 刷新小股票池行情
- 更新 market monitor snapshot
- 更新 intraday tactical snapshot
- 记录 intraday event journal
- 发送高优先级提醒

禁止：

- 全量回测
- 模型训练
- 周末研究
- 生成大型 PDF
- 阻塞 API 请求

#### 4.9.3 夜间任务

夜间任务负责：

- Robinhood CSV 回流后的复盘
- 全量行情和事件更新
- 核心 ETF / 卫星仓分析
- 次日计划
- plan quality 更新
- nightly decision journal
- Slack / Email 夜报

#### 4.9.4 周末任务

周末任务负责：

- 长窗口回测
- 策略验证
- 候选策略晋升 / 降级建议
- 下周行情偏向研究
- 模型候选比较

周末任务可以耗时较长，但必须：

- 写 job status
- 写 manifest
- 允许失败后恢复
- 不影响前端读取当前快照

---

## 5. V3 实施路线

V3 不采用过细的企业级迁移节奏。

这是个人使用系统，允许短暂停机、允许一次性替换旧界面，也不需要为了持续在线而拆成很多小阶段。

因此实施路线压缩为三步：

1. 先把新架构跑起来
2. 一次性完成页面迁移和 Streamlit 删除
3. 再补高级数据健康、计划质量和策略治理

### Step 1: 跑通前后端分离新架构

目标：

先证明新架构可用，让前端能脱离 Streamlit，从后端快照 API 读取当前系统状态。

新增：

- `quant_core/api/schemas.py`
- `quant_core/api/snapshot_loader.py`
- `jobs/api_server.py`
- `quant_core/jobs/job_registry.py`
- `storage/state/job_status.json`
- `storage/config/runtime_schedule.json`
- `frontend/`
- Vite + React + TypeScript
- API client
- shared layout
- basic routing
- Dashboard first screen

第一批 API：

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/core-etfs`
- `GET /api/satellite-radar`
- `GET /api/risk`
- `GET /api/change-feed`
- `GET /api/job-status`
- `GET /api/settings`

验收：

- API 不触发重计算
- 缺失快照返回 stale / missing 状态
- React Dashboard 读取 `/api/dashboard`
- 页面切换不触发后端计算
- Jetson 上能完整渲染首页
- `~/venv/bin/python -m jobs.run_all` 可以启动 API、前端和后台基础任务
- Settings 可以读取任务节奏配置，但第一步不要求完成所有配置编辑能力
- 现有 Streamlit 可以临时保留为 fallback，但不再继续新增功能

---

### Step 2: 一次性迁移页面并删除 Streamlit

当前状态：已完成迁移收口。React 前端已覆盖 Dashboard、Core ETFs、Satellite Radar、Risk & Discipline、Market Monitor、Operations、Settings；FastAPI 已提供对应快照 API 和手动操作 API；旧 `main.py`、`app/ui/*`、Streamlit-only helper、Streamlit 依赖和旧 UI 测试已移除。`jobs.run_all` 现在读取 `storage/config/runtime_schedule.json` 中的任务节奏配置，前端 Settings 保存后会进入后台下一轮执行。

目标：

把所有日常使用入口迁移到 React，并在功能覆盖后删除 Streamlit 主界面和旧 UI 文件。

迁移：

- Dashboard
- Core ETFs
- Satellite Radar
- Risk & Discipline
- Market Monitor
- Operations
- Settings
- Robinhood CSV 上传
- 强制刷新行情
- 手动运行 nightly
- 手动运行 weekend research
- 保存 Settings
- 修改交易时段监控、夜间任务和周末研究的运行节奏
- 查看 reports / job status

同步清理：

- 移除 Streamlit 主入口
- 删除不再使用的 `app/ui/*` Streamlit 页面组件
- 删除旧 Streamlit-only helper
- requirements 移除不再需要的 Streamlit 运行依赖
- README 更新启动方式
- 清理不再使用的配置、示例文件和临时数据

验收：

- 所有日常页面都从 API DTO 读取数据
- 页面切换不触发后端重计算
- 表格不强制横向滚动，主视图只显示决策字段
- 操作接口返回 job status
- 前端轮询 job status
- 上传 CSV 不阻塞页面
- Settings 保存有 schema 校验，并会规范化无效 interval / poll 参数
- 任务节奏修改后写入 `storage/config/runtime_schedule.json`，由后台 worker 在下一轮读取
- `~/venv/bin/python -m jobs.run_all` 一次启动完整系统
- 不再需要打开 Streamlit
- Slack / Email / nightly / weekend research 正常
- 全量测试通过

---

### Step 3: 接入高级可靠性和决策质量模块

当前状态：已完成最小闭环接入。新增 Data Health、Plan Quality、Market Monitor、Strategy Governance、Model Registry、Weekend Evidence Layer 的最小可用模块；对应快照已接入 API、Dashboard、Operations 诊断、Slack 查询、nightly report、Change Feed 和 weekend research。后续重点不是继续扩大页面，而是积累更多真实复盘样本、优化告警阈值、校准计划质量评分，并把 evidence layer 接入更丰富的数据源。

目标：

在新架构稳定后，再把更高级的收益相关能力接入系统主循环。

这些能力不阻塞 Step 1 和 Step 2，因为它们属于“让系统更聪明、更可信”，不是“让系统跑起来”的前置条件。

#### 3.1 Data Health Foundation

目标：

把数据可靠性做成可观测对象，避免 `NaN`、过期缓存和 fallback 状态污染交易判断。

新增：

- `quant_core/data/data_health.py`
- `storage/state/data_health_snapshot.json`
- API endpoint `GET /api/data-health`
- Slack 命令 `数据状态`
- Dashboard 数据健康摘要

验收：

- 外部源失败时 UI 和 Slack 能明确显示 DEGRADED
- NaN / inf 会被拒绝并计数
- 缺失价格标的能被列出来
- 前端能显示 freshness / stale

#### 3.2 Plan Quality Foundation

目标：

把“计划是否真的可执行”升级为正式指标。

新增：

- `quant_core/execution/plan_quality.py`
- `storage/state/plan_quality_snapshot.json`
- API endpoint `GET /api/plan-quality`
- Slack 命令 `计划质量`
- Dashboard 计划质量摘要

验收：

- 能看到最近 N 天计划可执行率
- 能区分触达未执行、区间未到、跳空失效
- 能按 core / satellite / tactical 分组
- 能反哺策略验证和核心 ETF 建议质量

#### 3.3 Market Monitor + Intraday Tactical Sampling

目标：

把交易时段轻量监控正式补强。

新增：

- `quant_core/monitoring/market_monitor.py`
- `storage/state/market_monitor_snapshot.json`
- API endpoint `GET /api/market-monitor`
- `jobs.run_all` 增加可配置 market-hours sampler
- `intraday_event_journal` 增加 outcome 字段
- Slack 只推 ACTIONABLE / URGENT

验收：

- 能看到 SPY / QQQ / VOO / SCHD 状态
- 能看到 SQQQ / PSQ / SH 战术工具状态
- 能看到市场压力是否升温
- 大盘急跌时能生成风险升级记录
- `DO_NOT_CHASE` 能阻止追高反向 ETF
- 不阻塞前端渲染

#### 3.4 Strategy Governance + Model Interface

目标：

把策略验证升级成策略生命周期管理，并统一模型接口。

新增：

- `quant_core/research/strategy_governance.py`
- `storage/state/strategy_registry_state.json`
- `quant_core/models/interfaces.py`
- `quant_core/models/registry.py`
- `storage/config/model_registry.json`
- Weekend Research 中加入策略晋升 / 降级建议

验收：

- 每个策略有状态
- 默认策略 REVIEW 时能给降级建议
- 候选策略满足条件时能给晋升建议
- 新模型通过统一接口进入系统
- 不自动切换默认策略

#### 3.5 Advanced UI / Slack Integration

目标：

把高级模块的结果接入日常工作流，而不是让它们停留在后台文件里。

接入：

- Dashboard 数据健康摘要
- Dashboard 计划质量摘要
- Market Monitor 战术状态条
- Strategy Governance 状态摘要
- Slack 命令 `数据状态`
- Slack 命令 `计划质量`
- Slack / Email 高优先级提醒

验收：

- 打开 Dashboard 30 秒内知道今天是否应该行动
- Slack 查询能回答日常关键问题
- 高级模块的结果能进入 nightly report
- 低优先级变化不会打扰用户

#### 3.6 Weekend Research Evidence Layer

目标：

把周末长周期研究从“生成一份报告”升级为“生成可复盘、可引用、可降噪的证据层”。

新增：

- `quant_core/research/evidence_collector.py`
- `quant_core/research/weekend_research.py`
- `storage/state/weekend_research_snapshot.json`
- `storage/journals/weekend_research_journal.jsonl`

输入：

- 长窗口价格和成交量数据
- 核心 ETF 与卫星仓候选池历史表现
- 已配置来源中的研报、新闻、事件材料
- 远程 LLM 对长文本材料的摘要和对比

输出：

- 下周值得关注的核心 ETF / 卫星仓主题
- 结构性风险提示
- 候选池新增 / 降级理由
- 策略验证摘要
- 引用来源、生成时间、freshness 和置信度

约束：

- LLM 输出必须进入 evidence，不直接进入 action
- 没有可验证来源的结论必须标记为 low confidence
- 周末研究可以影响下周候选优先级，但不能绕过 risk gate 和 plan quality

---

## 6. 测试策略

V3 测试按能力分类，而不是按过细迁移阶段分类。三步推进中，每一步只需要覆盖其对应的主风险。

### 6.1 API / Frontend Contract

覆盖：

- API health endpoint
- dashboard endpoint with complete snapshots
- dashboard endpoint with missing snapshots
- stale status propagation
- operation endpoint returns job status
- React pages render from API fixtures
- Settings save validates payloads
- schedule update writes valid `runtime_schedule.json`
- Operations upload/import flows return job status
- Robinhood CSV import deduplicates repeated records
- no Streamlit dependency in main runtime after migration

### 6.2 Data Health

覆盖：

- provider success
- provider failure
- fallback success
- NaN rejected
- stale cache
- missing symbol
- degraded / broken status enters high-priority Change Feed

### 6.3 Plan Quality

覆盖：

- executed plan
- reachable but missed
- invalidated
- unreachable
- grouped summary
- plan deviation enters Change Feed and nightly summary

### 6.4 Strategy Governance / Model Interface

覆盖：

- default stays DEFAULT
- default becomes DEGRADED candidate
- candidate becomes SHADOW candidate
- retired strategies are excluded
- model registry loads active models
- model prediction output follows interface schema
- model validation output follows interface schema
- historical labels include absolute, short-Treasury-relative, and
  SPY-relative outcomes without leakage
- old target-schema checkpoints are rejected
- unpromoted model actions are gated to HOLD / WATCH
- promotion is bound to the exact checkpoint version
- retraining returns the model to SHADOW
- strategy review state enters Change Feed without automatic promotion

### 6.5 Market Monitor / Intraday Tactical

覆盖：

- normal market
- stress building
- panic
- defensive ETF overextended
- tactical sampler cadence
- ACTIONABLE / URGENT alert filtering

### 6.6 Slack / UI

覆盖：

- `数据状态`
- `计划质量`
- market monitor rendering
- no `nan` in user-facing text
- no wide mandatory table in main views
- chart components render from compact DTOs

### 6.7 Weekend Research Evidence

覆盖：

- evidence items include source and generated_at
- stale research source is marked stale
- LLM summary is stored as evidence, not action
- low-confidence unsupported conclusion is marked low confidence
- weekend research snapshot can feed next-week candidate priority without bypassing risk gate

---

## 7. 当前不做的事项

V3 仍然不建议做：

- 高质量分析师预期全自动覆盖
- 复杂 fundamental data vendor 集成
- 自动实盘下单
- 高频行情基础设施
- 复杂云部署和公网 API
- 用本地 SLM 替代结构化原因引擎
- 让远程 LLM 直接产出交易动作
- 大规模股票池扩展到几千只

这些以后可以讨论，但不是当前系统最影响收益和稳定性的地方。

---

## 8. V3 成功标准

V3 成功后，系统应该满足：

- React Dashboard 首屏读取本地 API 后快速显示，不依赖 Streamlit rerun
- 用户 30 秒内知道今天是否应该行动
- 所有价格缺失和数据源失败都可见
- 夜间计划能持续评估可执行性
- Robinhood CSV 成为真实成交记录的可靠回流入口，并能去重导入
- 盘中战术信号更及时，但不会频繁骚扰
- 默认策略是否可信有明确治理流程
- Settings 能集中管理任务节奏、通知、数据源和 LLM / SLM 配置
- 周末研究能产出可引用 evidence，而不是只生成不可复盘的文字报告
- 模型接口足够清晰，后续模型能被替换而不改业务主链路
- UI 更像市场决策终端，而不是报告集合
- Slack 查询能覆盖日常关键问题
- Streamlit 主界面被移除，完整系统由 `jobs.run_all` 启动 API、前端和后台任务

一句话总结：

`V3 的重点不是让系统更大，而是让它更像一个可信、克制、能持续进化的个人量化决策工作台。`

---

## 9. 参考资料

- QuantConnect LEAN documentation: https://www.quantconnect.com/docs/
- Qlib documentation / repository: https://github.com/microsoft/qlib
- Freqtrade documentation: https://docs.freqtrade.io/en/stable/
- FinRL documentation / repository: https://github.com/AI4Finance-Foundation/FinRL
- TradingView features: https://www.tradingview.com/features/
- Koyfin features: https://www.koyfin.com/features/
- TrendSpider: https://trendspider.com/
- Composer: https://www.composer.trade/
