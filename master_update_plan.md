# Quant Trade System Master Update Plan

## 0. 文档目标

这份文档用于指导系统下一阶段的主线升级。新版本系统不再以“单只股票信号展示器”为中心，而是重构为：

1. `核心 ETF 引擎`
2. `卫星仓雷达`
3. `仓位纪律层`

系统的首要目标保持不变：

- 辅助真实股票/ETF交易
- 提高长期盈利概率
- 降低错误重仓、错误分散、错误追高、错误死扛的风险

本计划默认以下约束继续成立：

- 单用户、本地优先、文件持久化
- 保持 `jobs/run_all.py` 为统一运行入口
- 继续采用 TDD 方式逐步升级
- 不把 LLM 作为交易主决策器，只把它用作解释、摘要、研究辅助

---

## 1. 新系统定位

### 1.1 核心定位

系统要回答的，不再只是“某只股票现在买还是卖”，而是以下三个层级的问题：

1. `核心资金应该配置到哪些 ETF，是否该买/卖/减/停，价位区间如何`
2. `当前最值得建立或继续持有的卫星仓股票是谁，最多 3 只`
3. `当前整体是否适合重仓、轻仓、还是停手`

### 1.2 新工作流

用户的真实决策流程应该被系统重构成：

1. 先看 `仓位纪律层`
2. 再看 `核心 ETF 引擎`
3. 最后看 `卫星仓雷达`

顺序不能反过来。先决定风险状态，再决定买什么，而不是先看到信号再硬找理由上仓位。

### 1.3 系统最终输出

系统以后每天真正应该输出的，是三份主结论：

1. `核心仓建议`
2. `卫星仓建议`
3. `纪律状态`

### 1.4 运行模式总纲

系统的默认运行模式应明确收敛为：

1. `夜间计划`
2. `盘前查看`
3. `盘中监控`
4. `收盘后回流与复盘`

对应节奏如下：

- 夜间：生成`次日交易计划`
- 盘前：用户主动查看是否有动作、具体建议区间与失效条件
- 盘中：系统默认静默，只在`紧急风险`或`计划内触发条件命中`时提醒
- 收盘后：导入 Robinhood CSV，做真实执行回流与复盘，再进入下一轮夜间运行

这是一条正式设计要求：

`系统默认不以盘中频繁找新机会为目标，而以“夜间计划 + 盘中监控 + 收盘复盘”的周期闭环为主。`

---

## 2. 核心原则

### 2.1 不允许写死核心 ETF

核心 ETF 池必须可配置、可扩展、可替换，不能在代码里固定写死为 `VOO/QQQ/SCHD`。

默认候选池可以是：

- `VOO`
- `VTI`
- `SPY`
- `QQQ`
- `SCHD`
- `DGRO`
- `VUG`
- `QUAL`
- `SPLG`

但真正启用哪些 ETF，应由配置文件和 UI 决定，而不是代码写死。

### 2.2 核心 ETF 与卫星仓分工不同

- `核心 ETF`：长期底仓、风格配置、节奏调仓
- `卫星仓`：寻找中长期趋势确认的高弹性个股

不能用卫星仓替代核心仓，也不能让核心仓逻辑和个股逻辑混在一起。

### 2.3 候选池必须有限

候选池上限建议固定为 `<=100`。

理由：

- 100 对单用户系统足够大
- 100 以内便于夜间批量分析、排序、回测、解释
- 超过 100 会明显增加计算噪音与使用负担

### 2.4 LLM 只做解释层

LLM 可以参与：

- 新闻/事件摘要
- 候选股原因解释
- 夜间报告摘要
- Slack 解释

LLM 不应直接参与：

- 最终买卖判定
- 高频页面逐行实时决策
- 仓位大小的最后裁决

### 2.5 回测是验证器，不是主筛选器

候选池不能由“回测谁最好谁进池”直接决定。

正确顺序应为：

1. 先筛选
2. 再打分
3. 再做回测验证
4. 最后更新候选池

### 2.6 没有强信号就不交易

这是一条正式设计要求：

`系统必须显式支持“明日无交易动作”。`

也就是说，夜间主输出不应默认强行给出交易建议，而应先判断：

- `明日建议：有动作`
- `明日建议：无动作`

当结论为 `无动作` 时，也要给出明确理由，例如：

- 核心 ETF 全部处于 `HOLD / PAUSE_BUY`
- 纪律层当前为 `LIGHT / STOP`
- 卫星仓没有达到 `PROBE / CONFIRMED` 门槛

“不动”应被视为一个完整结论，而不是空输出。

---

## 3. 目标系统结构

## 3.1 三大引擎

### A. 核心 ETF 引擎

回答：

- 当前该关注哪些核心 ETF
- 当前该买/卖/减/停什么 ETF
- 当前的目标权重区间
- 合理买入区间、追价上限、减仓区间

### B. 卫星仓雷达

回答：

- 当前候选池 `<=100` 有哪些票
- 其中 Top 10-20 哪些值得深挖
- 当前最值得建立/继续持有的 `Top 3` 是谁

### C. 仓位纪律层

回答：

- 现在适不适合重仓
- 能不能开新仓
- 单仓和总仓位上限是多少
- 是否该暂停追高

---

## 4. 数据与配置设计

## 4.1 新增配置文件

建议新增以下配置文件：

### `storage/config/core_etf_universe.json`

用途：

- 管理核心 ETF 候选池
- 设置 ETF 的角色、启用状态、优先级、是否长期允许持有

建议结构：

```json
{
  "etfs": [
    {
      "symbol": "VOO",
      "enabled": true,
      "role": "broad_market",
      "priority": 1,
      "long_term_core": true
    },
    {
      "symbol": "QQQ",
      "enabled": true,
      "role": "growth",
      "priority": 2,
      "long_term_core": true
    },
    {
      "symbol": "SCHD",
      "enabled": true,
      "role": "dividend_quality",
      "priority": 3,
      "long_term_core": true
    }
  ]
}
```

### `storage/config/satellite_universe.json`

用途：

- 管理卫星仓扫描池来源
- 限制夜间扫描宇宙，不无限扩大

建议字段：

- `source_indexes`
- `manual_include`
- `manual_exclude`
- `max_candidate_pool_size`
- `max_deep_analysis_size`
- `max_recommendations`

建议默认：

- `max_candidate_pool_size = 100`
- `max_deep_analysis_size = 20`
- `max_recommendations = 3`

### `storage/config/engine_policy.json`

用途：

- 管理评分权重、纪律阈值、换池规则、持仓上限

建议字段：

- `core_etf_weight_ranges`
- `satellite_max_total_weight_pct`
- `satellite_max_single_weight_pct`
- `candidate_entry_threshold`
- `candidate_exit_threshold`
- `candidate_persistence_days`
- `discipline_regime_thresholds`

## 4.2 新增状态文件

### `storage/state/core_etf_snapshot.json`

记录核心 ETF 引擎输出。

### `storage/state/satellite_candidate_pool.json`

记录候选池快照与历史变化。

### `storage/state/discipline_snapshot.json`

记录仓位纪律层输出。

### `storage/state/llm_summary_cache.json`

记录夜间生成的 LLM 摘要缓存，避免白天重复调用。

### `storage/state/nightly_run_manifest.json`

记录夜间任务运行清单与各阶段状态，作为幂等恢复、freshness 校验与断点续跑的基础。

建议字段：

- `run_id`
- `started_at`
- `finished_at`
- `status`
- `steps`

其中 `steps` 中每一项建议至少包含：

- `step_name`
- `status`
- `started_at`
- `finished_at`
- `input_version`
- `output_file`
- `is_fresh`
- `error_message`

---

## 5. 核心 ETF 引擎设计

## 5.1 ETF 输入范围

输入来自 `core_etf_universe.json` 中已启用的 ETF，而不是写死代码常量。

系统必须支持：

- 替换 `VOO -> VTI`
- 禁用 `SPY`
- 加入 `QUAL`
- 暂时只用 `VOO + QQQ`

## 5.1.1 核心 ETF 候选池是正式设计要求

核心 ETF 不应被视为静态长期持有清单，而应被视为一个`低频轮动候选池`。

这意味着：

- 系统要先维护一组`核心 ETF 候选池`
- 再从候选池中决定当前重点配置哪些 ETF
- 再通过纪律层决定是否允许增减仓

核心 ETF 候选池与卫星仓候选池的区别是：

- 核心 ETF 候选池用于`风格配置与权重微调`
- 卫星仓候选池用于`寻找高弹性中长期趋势个股`

核心 ETF 候选池不追求高频切换，而追求：

- 风格识别
- 配置节奏
- 风险缓冲
- 低频优化

## 5.1.2 核心 ETF 候选池规模

建议规模：

- `5-12` 只为宜

原因：

- 足够覆盖 broad market / growth / dividend / quality / cash substitute 等角色
- 不至于把核心仓变成“ETF 选股游戏”
- 便于夜间低频回测和比较

默认建议候选：

- `VOO`
- `VTI`
- `SPY`
- `QQQ`
- `SCHD`
- `DGRO`
- `QUAL`
- `VUG`
- `SPLG`

可选扩展：

- `SGOV`
- `BIL`

## 5.1.3 核心 ETF 角色标签

每个核心 ETF 应有角色标签，供 UI、评分和解释层使用。

建议角色：

- `broad_market`
- `growth`
- `dividend_quality`
- `quality`
- `cash_substitute`
- `other`

角色的意义不是固定决定买卖，而是帮助系统回答：

- 当前应偏 broad market 还是 growth
- 当前是否需要 dividend/quality 做缓冲
- 当前是否应提高现金替代比例

## 5.2 ETF 引擎输出字段

每个 ETF 至少输出以下字段：

- `symbol`
- `enabled`
- `role`
- `current_price`
- `signal`
- `signal_reason`
- `current_weight_pct`
- `target_weight_pct`
- `target_weight_range_low_pct`
- `target_weight_range_high_pct`
- `action`
- `recommended_buy_zone_low`
- `recommended_buy_zone_high`
- `max_chase_price`
- `trim_zone_low`
- `trim_zone_high`
- `risk_break_level`
- `expected_return_3m`
- `expected_return_12m`
- `confidence`
- `regime_alignment`
- `analysis_freshness`

## 5.2.1 次日可执行计划字段

ETF 与卫星仓建议在夜间输出时，不应只停留在状态标签，而应升级为`次日可执行计划单`。

每条建议建议额外输出：

- `plan_action`
- `plan_weight_delta_pct`
- `entry_condition`
- `invalid_condition`
- `plan_valid_until`
- `risk_break_level`
- `execution_priority`

说明：

- `entry_condition`：什么情况下第二天可以执行，例如“开盘后价格进入买入区间可分批建仓”
- `invalid_condition`：什么情况下建议失效，例如“跳空高开超过追价上限则本次建议作废”
- `plan_valid_until`：建议有效期，默认不应无限期延续
- `execution_priority`：用于排序真正应该优先处理的计划

这是一条正式设计要求：

`夜间输出必须从“研究结论”升级为“第二天可执行的计划单”。`

## 5.3 ETF 动作枚举

建议动作固定为：

- `ACCUMULATE`
- `HOLD`
- `TRIM`
- `PAUSE_BUY`
- `RISK_EXIT`

这些动作比简单 `BUY/SELL` 更适合长期 ETF。

## 5.3.1 ETF 动作防抖与最小调整阈值

这是一条正式设计要求：

`核心 ETF 引擎必须内置 hysteresis（防抖/滞后）机制，防止系统因为微小评分变化而频繁改变建议。`

建议硬规则：

- `target_weight_pct` 与当前目标权重差异 `< 3%` 时，不产生新动作建议
- `HOLD -> ACCUMULATE` / `HOLD -> PAUSE_BUY` / `HOLD -> TRIM` 之类的动作切换，需要连续 `2` 个夜间周期支持
- 即使权重变化超过阈值，如果折算后的建议交易金额过小，也不应提示执行

设计目标：

- 避免系统天天给出 `55% -> 56%` 这种无意义微调
- 降低用户对核心 ETF 引擎的疲劳感与不信任
- 让核心 ETF 层保持低频、稳定、可执行

## 5.4 ETF 买卖价输出原则

ETF 不应输出单一点价，而应输出价位区间：

- `买入区间`
- `追价上限`
- `减仓区间`
- `风险破坏位`

原因：

- 长期 ETF 更适合分批买入
- 精确点价对长期账户帮助有限
- 区间更适合纪律化执行

## 5.5 ETF 引擎信号来源

ETF 引擎建议基于以下信号组合：

### 趋势信号

- 3M/6M/12M 回报
- 相对强弱：ETF vs `VOO/VTI/SPY`
- 均线结构
- 回撤深度
- 波动率

### 风格轮动信号

- `QQQ vs broad_market`
- `SCHD vs broad_market`
- `growth vs dividend_quality`
- `broad_market vs cash`

### 风险信号

- VIX
- benchmark drawdown
- benchmark volatility
- 事件风控结果
- analysis freshness

### 纪律层信号

- scoreboard 最近有效性
- 当前总敞口
- 资金缓冲

## 5.5.1 核心 ETF 轮动评分

核心 ETF 不应只看单 ETF 的绝对趋势，还要看不同 ETF 之间的`相对配置价值`。

建议加入轮动评分：

### 趋势相对强弱

- `QQQ vs VOO/VTI`
- `SCHD vs VOO/VTI`
- `QUAL vs VOO/VTI`
- `cash_substitute vs broad_market`

### 风格适配

- 当前市场是否奖励成长风格
- 当前市场是否奖励分红/质量风格
- 当前是否更适合宽基底仓

### 风险适配

- 高波动时是否应降低成长ETF比重
- 回撤加深时是否应提升防守ETF/现金替代

该评分最终不直接输出“买/卖”，而是辅助输出：

- `目标权重区间`
- `增减方向`
- `是否暂停追价`

## 5.5.2 核心 ETF 回测辅助调整

这是一条正式设计要求：

`核心 ETF 也要建立观察/候选池，并通过低频轮动回测辅助持仓调整。`

注意这里的回测定位是：

- `辅助调整`
- `验证规则`
- `比较风格配置`

而不是：

- 高频切仓
- 用回测结果直接硬切全部核心仓

### 核心 ETF 回测应回答的问题

1. 当前的风格轮动规则是否仍有历史优势
2. 在不同风险环境下，应该偏向哪类 ETF
3. 当前的 ETF 权重调整是否值得执行

### 核心 ETF 回测主要用途

- 验证 `QQQ` 增配是否有胜率支持
- 验证 `SCHD/QUAL` 防守加配是否能改善回撤
- 验证 broad market 与 growth 的切换规则是否仍稳定
- 验证现金替代工具在风险环境下是否应提升比例

### 核心 ETF 回测输出建议

每个 ETF 或 ETF 组合层面建议输出：

- `rotation_score`
- `rotation_rank`
- `lookback_performance_3m`
- `lookback_performance_6m`
- `lookback_performance_12m`
- `relative_strength_vs_core_benchmark`
- `historical_rule_win_rate`
- `historical_rule_expectancy`
- `historical_rule_drawdown`
- `allocation_support_level`

### 核心 ETF 回测频率

不建议每小时运行。

建议节奏：

- `夜间`：运行完整 ETF 轮动回测
- `盘中`：只根据已有结论 + 最新价格更新状态，不重跑完整回测

### 核心 ETF 回测的约束

回测结果不能单独决定大幅换仓，必须经过纪律层审批。

即：

`ETF 候选池 -> 轮动评分 -> 低频回测验证 -> 纪律层审批 -> 核心仓权重调整建议`

这是正式决策链路。

此外，核心 ETF 回测结果在进入最终建议前，也应遵守：

- `最小权重变化阈值`
- `动作切换连续确认`
- `最小交易金额阈值`

即使历史回测支持某个方向，也不能绕过 ETF 防抖规则直接产生高频换仓建议。

## 5.6 ETF 组合级输出

核心 ETF 引擎不仅输出单 ETF 建议，还应输出组合级别 regime：

- `RISK_ON_GROWTH`
- `BALANCED`
- `DEFENSIVE_INCOME`
- `RISK_OFF`

系统最终要把 ETF 建议汇总成：

- 核心 ETF 当前权重
- 目标权重
- 增减方向
- 当前加仓优先级

---

## 6. 卫星仓雷达设计

## 6.1 卫星仓目标

卫星仓雷达的目标不是预测下一只神股，而是识别：

`中长期趋势刚被确认、但还没有极度过热的股票`

## 6.2 股票池分层

建议分 4 层：

### 1. 扫描宇宙

规模：

- 300-800 只

来源建议：

- S&P 500
- Nasdaq 100
- 半导体/AI 基础设施/高流动性股票
- 手工加入的主题股

### 2. 候选池

规模：

- `<=100`

这是系统真正持续跟踪的池子。

### 3. 深度分析池

规模：

- `Top 10-20`

会跑更重的分析：

- 回测
- Monte Carlo
- TCN / 深度模型
- 风险分析

### 4. 最终推荐池

规模：

- `Top 3`

这是用户真正应该重点研究或建仓的集合。

## 6.3 候选池夜间更新规则

夜间候选池更新建议按以下流程进行：

### Step 1. 基础清洗

过滤条件：

- 缺少必要历史数据
- 流动性过低
- 成交额过低
- 价格异常
- 近期重大数据缺失

### Step 2. 结构评分

先做轻量评分，不做重回测。

### Step 3. 候选池更新

保留稳定优先，不做大换血：

- 新进入候选池：需要达到阈值且最好连续数天改善
- 移出候选池：连续恶化或趋势破坏
- 候选池总数不超过 100

### Step 4. 深度分析

只对 Top 20 做更重分析：

- 回测
- Monte Carlo
- TCN 推理
- 事件/新闻增强
- 风险评估

### Step 5. 生成 Top 3

由评分器 + 纪律层共同裁决，不是纯分数排序。

## 6.4 候选池更新稳定性规则

为避免每日大换血，建议加入滞后与稳定规则：

- `entry persistence`: 进入候选池前需连续 N 次满足条件
- `exit persistence`: 退出候选池前需连续 N 次低于阈值
- `top3 cooldown`: Top 3 不应因一天噪声大幅变动

建议默认：

- `entry persistence = 2-3 nights`
- `exit persistence = 2-3 nights`

---

## 7. Top 3 推荐评分机制

## 7.1 总体原则

Top 3 不应该由单一模型决定。

建议采用：

- `结构评分`
- `回测验证`
- `风险惩罚`
- `纪律层审批`

## 7.2 评分框架

建议总分 100 分：

### A. 价格趋势（30）

- 3M relative strength
- 6M relative strength
- 12M trend quality
- 52 周高位结构
- 回撤是否浅于行业平均

### B. 基本面加速（20）

- 营收加速
- EPS / 利润率改善
- 指引改善
- 分析师预期上修

## 7.2.1 基本面数据层约束与分层评分

这是一条正式设计要求：

`基本面加速项不能假设系统能够长期、稳定、免费地自动拿到高质量分析师一致预期和管理层指引数据。`

因此，基本面加速分应拆成两层：

### A. 可稳定自动化部分

建议权重：`8-12`

可优先纳入：

- 历史营收增速变化
- EPS 同比/环比改善
- 毛利率趋势
- free cash flow 趋势
- 其他可由历史财报稳定推导出的结构指标

### B. 弱自动化增强部分

建议权重：`0-8`

仅在数据可用且 freshness 合格时加分：

- analyst estimate revision
- target price revision
- management guidance improvement
- earnings call 摘要中的语义改善信号

规则要求：

- 这部分`有数据才加分，没有数据不扣分`
- 必须显示 `source` 与 `freshness`
- 非财报季允许沿用上一季度数据，但应明确标记为 `stale`
- LLM 可参与摘要与解释，但不应伪造不存在的数据

这条约束的目标是：

- 避免因数据缺失而系统性低估基本面好的股票
- 避免把“难拿到的数据”伪装成稳定自动化评分来源
- 让评分器对数据质量保持诚实

### C. 行业/主题确认（15）

- 所属行业 ETF 强势
- 同行龙头联动
- 主题扩散
- 新闻/事件一致性

### D. 模型确认（15）

- TCN 方向
- TCN 概率
- TCN 预期收益
- Monte Carlo 分布

### E. 回测验证（10）

- 历史相似信号下表现
- 胜率
- payoff ratio
- max drawdown

### F. 风险惩罚（-20 到 0）

- 过热
- 离均线太远
- 财报前风险
- 极端波动
- 高相关拥挤

## 7.3 最终推荐约束

Top 3 还要经过以下约束：

- 同行业不宜过多
- 高相关股票不宜同时全上榜
- 已过热票即使高分也可降级为 `等待`
- 不满足纪律层时可不给满 3 只

系统应允许：

- `Top 3 = 0`
- `Top 3 = 1`
- `Top 3 = 2`

而不是为了凑数强行给 3 只。

## 7.4 推荐状态标签

每只候选股票输出状态标签：

- `WATCH`
- `PROBE`
- `CONFIRMED`
- `OVERHEATED_WAIT`
- `BROKEN`

建议含义：

- `WATCH`: 观察，不上仓位
- `PROBE`: 小仓试探
- `CONFIRMED`: 趋势确认，可较高权重
- `OVERHEATED_WAIT`: 强，但不追
- `BROKEN`: 趋势破坏，降级/退出

---

## 8. 仓位纪律层设计

## 8.1 纪律层职责

纪律层不是选标的，而是决定：

- 现在总体可不可以加仓
- 核心 ETF 能不能继续加
- 卫星仓可不可以开新仓
- 单票仓位能不能放大

## 8.2 纪律层输入

来自：

- risk gate
- scoreboard
- account snapshot
- correlation / concentration
- analysis freshness
- 事件风险
- 候选池稳定性

## 8.3 纪律层输出

固定输出：

- `HEAVY`
- `NORMAL`
- `LIGHT`
- `STOP`

并给出：

- `max_total_exposure_pct`
- `max_core_etf_increment_pct`
- `max_satellite_total_weight_pct`
- `max_single_satellite_weight_pct`
- `allow_new_buys`
- `allow_chasing`

## 8.4 纪律层默认硬规则

建议默认：

- 卫星仓总仓位上限：`10%-20%`
- 单只卫星仓上限：`3%-8%`
- 候选股分析过期时，不允许按高置信度建仓
- 风险 regime 为 `RISK_OFF` 时，不允许新增卫星仓
- 高相关卫星仓不同时重仓

## 8.5 纪律层反馈闭环与月度自评

这是一条正式设计要求：

`纪律层必须具备反馈闭环，但第一阶段只做可信度评估，不做自动自适应调参。`

建议增加一个月度自评模块，至少回答以下三个问题：

1. 上个月纪律层给出的限制，事后看是否合理
2. 纪律层方向判断与实际市场回报的一致性如何
3. `遵循纪律层建议的交易` 与 `忽略纪律层建议的交易`，哪一组表现更好

建议输出字段：

- `discipline_followed_trade_count`
- `discipline_ignored_trade_count`
- `discipline_followed_expectancy`
- `discipline_ignored_expectancy`
- `discipline_directional_hit_rate`
- `discipline_monthly_commentary`

边界约束：

- 第一阶段只做月报与信任校准
- 不自动修改纪律层阈值
- 不因为单月结果就自动重写 risk gate 逻辑

目标是让用户知道：

- 系统的纪律限制最近是否真有帮助
- 什么时候应该更信纪律层
- 什么时候需要人工复核而不是盲信

## 8.6 盘中监控只处理紧急信号

这是一条正式设计要求：

`盘中模块默认不负责生成新的常规交易机会，只负责监控紧急信号与计划内触发。`

建议盘中信号严格限制为两类：

### A. 紧急减仓 / 卖出类

- 持仓跌破夜间设定的 `risk_break_level`
- 持仓单日跌幅超过重大阈值
- 大盘出现极端风险事件
- 持仓命中高置信度负面事件

### B. 计划内买点触发类

- 核心 ETF 触达夜间计划中的理想买入区间
- 卫星仓候选触达夜间计划中的试探建仓区间

不应触发盘中提醒的情况包括：

- 正常波动范围内的小幅涨跌
- 候选池评分小幅变化
- 非关键排名变化
- 轻量摘要文案变化

目标是让盘中监控保持：

- `无事不打扰`
- `有事才提醒`

---

## 9. LLM 解释层设计

## 9.1 LLM 的职责

LLM 仅用于：

- 把量化信号转成自然语言
- 对新闻/事件做摘要
- 对 Top 3 给出解释
- 对 ETF 当前结论给出简明摘要

## 9.2 LLM 调用节奏

不在高频页面逐行实时调用。

建议只在以下时点调用：

- 夜间任务完成后
- 手动生成报告时
- 手动请求单票解释时
- Slack 请求解释时

## 9.3 LLM 缓存策略

输出缓存到：

- `llm_summary_cache.json`

按以下维度缓存：

- `symbol`
- `snapshot_generated_at`
- `summary_type`
- `model`

这样白天页面直接读缓存，避免频繁请求 API。

---

## 10. 页面改版设计

## 10.1 主页面结构

建议主页面改版为以下 5 个区域：

### Tab 1. 总览

显示：

- 明日是否有交易动作
- 当前纪律状态
- 当前核心 ETF regime
- 当前 Top 3 卫星仓
- 主要风险提示
- 最新夜间分析时间

### Tab 2. 核心 ETF

显示：

- ETF 候选池
- 当前启用 ETF
- 当前权重 / 目标权重
- 动作
- 买入区间
- 追价上限
- 减仓区间
- 系统摘要

### Tab 3. 卫星仓雷达

显示：

- 当前持有卫星仓
- 候选池 Top 10-20
- Top 3 推荐
- 状态标签
- 回测 / MC / TCN 核心结果
- 人工备注 + 系统摘要

### Tab 4. 纪律与风险

显示：

- risk gate
- scoreboard
- concentration
- correlation
- event risk
- analysis freshness
- 纪律层当前限制

### Tab 5. 报告与配置

显示：

- 盘前简报
- 夜间报告
- 全量分析报告
- 盘中提醒历史
- 收盘复盘报告
- 通知配置
- LLM 配置
- ETF 候选池配置
- 候选池规模配置

## 10.2 关注列表页面改造

当前关注列表建议改造成“卫星候选池面板”。

原 `备注` 字段已拆分为：

- `人工备注`
- `系统摘要`

后续还应加入：

- `状态标签`
- `排名变化`
- `入池天数`
- `连续改善天数`

## 10.3 持仓页面改造

持仓页建议拆成：

- `核心 ETF 持仓`
- `卫星仓持仓`

避免两类资产混在一个表格里。

## 10.4 Change Feed 分级是正式设计要求

全自动系统下， Change Feed 不是装饰，而是主体验的一部分。

因此必须采用 `High / Medium / Low` 三档分级：

### High

- 默认显示在 `Dashboard`
- 允许进入 Slack 摘要
- 示例：
  - 纪律层从 `NORMAL -> LIGHT`
  - 核心 ETF 动作切换
  - Top 3 新进入或被移除
  - 风险 gate 切换
  - 卫星仓状态从 `趋势确认 -> 趋势破坏`

### Medium

- `Dashboard` 可折叠展示
- 详情页完整保留
- 示例：
  - 候选池排名显著变化
  - ETF 权重区间轻微调整
  - 分析 freshness 从新鲜变为偏旧

### Low

- 不进入 `Dashboard` 主视图
- 只进入详情页或日志
- 示例：
  - 分数从 `72 -> 74`
  - 非关键文案变化
  - 次要事件摘要更新

正式要求：

- 低优先级变化默认不进入 Dashboard 主视图
- Dashboard 的 Change Feed 默认只突出 High
- Medium 应支持折叠查看
- Low 应保留到审计日志和详情页，而不是直接丢弃

---

## 11. 夜间任务设计

## 11.1 夜间流程总览

每晚主流程建议：

0. 检测并导入当日 `Robinhood Account activity CSV`（如有）
1. 更新持仓、成本价、可用现金与真实执行记录
2. 对昨日建议做执行回流与收盘复盘
3. 刷新市场数据
4. 刷新新闻/事件
5. 更新分析师共识
6. 更新核心 ETF 候选池与轮动回测
7. 更新核心 ETF 引擎
8. 更新候选池
9. 对 Top 20 做深度分析
10. 生成 Top 3 推荐
11. 运行纪律层
12. 生成`次日交易计划`与`盘前简报`
13. 生成 LLM 摘要缓存
14. 通过 `Slack / Email` 发送夜间报告与盘前简报

说明：

- 如果未检测到新 CSV，不应阻塞夜间流程，只需记录“无新增真实交易输入”
- Robinhood CSV 是真实执行闭环的主入口，但不是 nightly 的强制前置阻塞项

## 11.1.1 夜间流程幂等性与 manifest 是正式设计要求

夜间流程必须支持：

- 中途失败后断点恢复
- 下游步骤判断上游结果是否 fresh
- 避免把旧结果误当新结果继续消费

建议每个夜间步骤都写出独立阶段产物，例如：

- `market_data_stage.json`
- `events_stage.json`
- `core_etf_stage.json`
- `candidate_pool_stage.json`
- `discipline_stage.json`
- `report_stage.json`

并统一记录到：

- `storage/state/nightly_run_manifest.json`

正式要求：

- 下游步骤只能消费 `status=completed` 且 `is_fresh=true` 的上游结果
- 默认支持从失败步骤继续恢复，而不是盲目全量重跑
- `force` 模式下才允许显式覆盖已有阶段结果
- Nightly report 中应展示最近一次 nightly run 的完整状态摘要

这是全自动化场景下的基础可靠性要求，而不是可选增强。

## 11.2 候选池夜间回测策略

夜间回测建议只对 `Top 20` 运行，而不是对全市场或全部 100 只运行。

原因：

- 控制计算成本
- 降低夜间时长
- 让重分析资源集中在最有希望的票上

## 11.3 报告输出

夜间报告应新增三部分：

- `核心 ETF 建议`
- `候选池变化`
- `Top 3 推荐 + 原因`
- `明日有 / 无 交易动作`

此外建议新增：

- `nightly_run_status`
- `stale_inputs_detected`
- `step_failures_or_recoveries`
- `change_feed_highlights_by_priority`
- `discipline_monthly_feedback_snapshot`（若当月已有）

## 11.4 盘前简报与盘中提醒

系统应明确区分两类对外输出：

### A. 盘前简报

用途：

- 供用户在第二天开盘前主动查看
- 帮助判断当天是否要交易以及交易什么

建议内容：

- `明日建议：有动作 / 无动作`
- 核心 ETF 计划单
- 卫星仓计划单
- 每条建议的 `买入区间 / 建议仓位 / 失效条件 / 风险破坏位`
- 昨日真实执行与收盘复盘摘要（如有）

### B. 盘中提醒

用途：

- 仅在紧急事件或计划内条件触发时主动推送

建议内容：

- 触发的标的
- 触发类型
- 当前价格与计划区间关系
- 是否属于 `紧急减仓/卖出` 或 `计划内买点触发`
- 是否建议立即查看系统详情

## 11.5 通知投递通道

这是一条正式设计要求：

`无论夜间报告还是盘中提醒，都必须支持通过 Slack 和 Email 发送。`

要求如下：

- `夜间报告 / 盘前简报`：支持 `Slack` 与 `Email`
- `盘中紧急提醒`：支持 `Slack` 与 `Email`
- 渠道启用状态、发送频率、静默规则应纳入通知配置页统一管理
- 相同事件的多渠道投递应共享去重与 cooldown 逻辑

---

## 12. 建议新增模块与文件

## 12.1 模块建议

### `quant_core/portfolio/core_etf_engine.py`

职责：

- 管理核心 ETF 池
- 输出 ETF 建议与权重区间

### `quant_core/analytics/core_etf_rotation.py`

职责：

- 维护核心 ETF 候选池
- 运行低频轮动回测
- 输出 ETF 轮动评分
- 为核心 ETF 引擎提供回测辅助输入

### `quant_core/analytics/candidate_pool.py`

职责：

- 维护候选池
- 夜间更新
- 排名与稳定性控制

### `quant_core/execution/nightly_planner.py`

职责：

- 把 ETF / 卫星仓结论组装成次日交易计划单
- 生成“有动作 / 无动作”顶层结论
- 为盘前简报提供统一结构化输出

### `quant_core/execution/post_close_review.py`

职责：

- 导入 Robinhood CSV 后对昨日建议做执行回流
- 记录执行价、是否命中区间、是否主动放弃
- 为 scoreboard 提供“建议 -> 执行 -> 结果”三段式数据

### `quant_core/monitoring/intraday_monitor.py`

职责：

- 盘中监控紧急风险与计划内触发条件
- 默认保持静默
- 只在高优先级条件命中时触发提醒

### `quant_core/analytics/satellite_ranker.py`

职责：

- 计算 Top 3 分数
- 输出状态标签

### `quant_core/portfolio/discipline.py`

职责：

- 聚合 risk gate / scoreboard / concentration / freshness
- 输出最终仓位纪律建议

### `quant_core/llm/summary_builder.py`

职责：

- 基于量化快照与事件摘要生成 LLM prompt
- 产出 ETF / Top 3 / 候选池解释缓存

### `quant_core/notifications/delivery_router.py`

职责：

- 统一夜报、盘前简报、盘中提醒的投递
- 支持 `Slack / Email`
- 统一去重、优先级与 cooldown 逻辑

## 12.2 快照文件建议

- `storage/state/core_etf_snapshot.json`
- `storage/state/satellite_candidate_pool.json`
- `storage/state/discipline_snapshot.json`
- `storage/state/llm_summary_cache.json`

---

## 13. 实施阶段

## Phase 1: 配置与快照层

目标：

- ETF 池不再写死
- 候选池规则落配置
- 新快照文件结构确定

交付：

- `core_etf_universe.json`
- `satellite_universe.json`
- `engine_policy.json`
- 对应加载/保存逻辑

## Phase 2: 核心 ETF 引擎

目标：

- ETF 级别输出动作、权重、买入区间、减仓区间
- 建立核心 ETF 候选池与轮动回测辅助层
- 加入 ETF 防抖与最小调整阈值机制

交付：

- `core_etf_engine.py`
- `core_etf_rotation.py`
- `core_etf_snapshot.json`
- 核心 ETF 页面初版

## Phase 3: 候选池与 Top 3

目标：

- 夜间自动更新候选池
- 生成 Top 3
- 生成次日可执行计划单

交付：

- `candidate_pool.py`
- `satellite_ranker.py`
- `nightly_planner.py`
- 候选池快照与页面

## Phase 4: 仓位纪律层

目标：

- 形成最终 `HEAVY/NORMAL/LIGHT/STOP` 闭环
- 增加纪律层月度自评与可信度评估

交付：

- `discipline.py`
- `discipline_snapshot.json`
- 风险页面升级

## Phase 5: LLM 解释层

目标：

- 让系统摘要和夜间报告更可读

交付：

- `summary_builder.py`
- `llm_summary_cache.json`
- 通知配置页 LLM 区域已存在，进一步接入夜间任务

## Phase 6: 可靠性与变化管理

目标：

- 补上 nightly manifest 与分阶段状态文件
- 补上 Change Feed 分级体系
- 让 Dashboard / Slack / Nightly report 共享同一套变化优先级
- 对 stale 基本面数据、stale nightly 输出、缺失分析结果做明确可视化提示
- 让夜报、盘前简报、盘中提醒共享统一去重与投递规则

交付：

- `nightly_run_manifest.json`
- 分阶段 stage 输出设计
- Change Feed priority schema
- `delivery_router.py`
- 对应 UI / report / notification 消费规范

## Phase 7: 页面总改版

目标：

- 页面以“核心 ETF + 卫星仓 + 纪律层”为中心，而不是单票分散浏览

交付：

- 总览页
- 核心 ETF 页
- 卫星仓页
- 纪律与风险页

---

## 14. 测试策略

新增模块必须先补测试。

### 核心 ETF 引擎测试

- ETF 池配置加载
- ETF 启用/禁用切换
- 权重区间输出
- 买卖区间输出
- 失效条件输出
- 候选池规模约束
- 轮动回测输出
- 回测结果不能绕过纪律层直接大换仓
- 权重变化 `< 3%` 时不产生新动作
- 动作切换需要连续 `2` 个夜间周期确认
- 最小交易金额阈值生效

### 候选池测试

- 候选池上限 <= 100
- 入池/出池稳定规则
- Top 20 / Top 3 生成正确
- 无强信号时可正确输出 `无动作`
- 基本面弱自动化项缺失时不应被错误扣分
- stale 基本面数据必须被正确标记

### 纪律层测试

- 风险 regime 切换
- analysis freshness 降级
- 高相关约束
- 卫星仓上限约束
- 月度纪律自评统计是否正确
- followed vs ignored 分组归因是否正确

### LLM 测试

- 配置保存与预设
- OpenAI-compatible 调用
- 缓存键一致性

### UI / Workflow 测试

- Dashboard 首屏是否先展示纪律层
- 核心 ETF 与卫星仓是否严格分区
- 是否能一眼看到 Top 3 与核心权重建议
- 是否能一眼看到 `明日有 / 无 动作`
- 是否能一眼看到 freshness 与风险状态
- Change Feed 是否按 `High / Medium / Low` 正确分层
- 低优先级变化默认不进入 Dashboard 主视图

### Nightly Reliability 测试

- 夜间步骤失败后可从断点恢复
- stale 上游结果不会被下游错误消费
- manifest 状态写入完整
- `force` 模式会显式覆盖阶段结果
- 无新增 Robinhood CSV 时 nightly 仍可继续执行

### Execution / Review 测试

- Robinhood CSV 导入后能正确关联到前一晚建议
- 可区分“已执行 / 未执行 / 主动放弃 / 未触发”
- 收盘复盘能产出建议 -> 执行 -> 结果三段式记录

### Notification Delivery 测试

- 夜间报告可通过 `Slack / Email` 发送
- 盘前简报可通过 `Slack / Email` 发送
- 盘中紧急提醒可通过 `Slack / Email` 发送
- 多渠道发送共享去重与 cooldown 逻辑

---

## 15. 当前版本的直接开发顺序建议

如果按“投入产出比”排序，建议下一阶段按以下顺序推进：

1. `Phase 1`: ETF 池配置化 + 候选池配置化
2. `Phase 2`: 核心 ETF 引擎
3. `Phase 4`: 仓位纪律层
4. `Phase 3`: 候选池夜间自动更新 + Top 3
5. `Phase 6`: 可靠性与变化管理
6. `Phase 7`: 页面总改版
7. `Phase 5`: LLM 夜间解释缓存

原因：

- 先把“系统骨架”搭起来
- 再把“能不能买、买多少”这件事做稳
- 再把自动化可靠性和变化管理补齐
- 最后再加解释层

---

## 16. 一句话总结

这套系统的下一阶段目标不是“输出更多信号”，而是：

`先决定核心 ETF 怎么配，再决定最多 3 只卫星仓值不值得上，最后由纪律层决定能不能重仓。`

这才是适合单用户、长期可执行、能持续改进的量化交易辅助系统。

---

## 17. WebUI Redesign Spec

## 17.1 设计目标

新版 WebUI 的目标不是展示更多数据，而是帮助用户更快完成以下决策：

1. `今天能不能动仓`
2. `核心 ETF 该买什么、减什么、暂停什么`
3. `卫星仓最多看哪 3 只`
4. `哪些变化值得立刻注意`

UI 必须从“研究页导向”改为“决策驾驶舱导向”。

## 17.2 设计原则

- 首页先给`结论`，再给细节
- 先展示`纪律状态`，再展示买卖建议
- 核心 ETF 与卫星仓严格分区
- 表格只用于明细，不作为主决策入口
- 系统摘要与人工备注严格分离
- 所有关键建议都必须附带：
  - `原因`
  - `新鲜度`
  - `风险限制`
- UI 必须突出`变化`，而不是只显示静态快照

## 17.3 信息层级

页面整体信息层级固定为：

1. `全局风险状态`
2. `核心资产配置建议`
3. `卫星仓机会建议`
4. `风险与限制明细`
5. `报告 / 配置 / 深挖分析`

---

## 18. 页面级线框

## 18.1 页面总结构

建议主导航固定为 5 个页面：

1. `Dashboard`
2. `Core ETFs`
3. `Satellite Radar`
4. `Risk & Discipline`
5. `Reports & Config`

## 18.2 Dashboard 线框

目标：

- 每天打开后 30 秒内知道今天应不应该动手

线框建议：

```text
+--------------------------------------------------------------+
| App Title                                                    |
| Last nightly update | Data freshness | Slack/Alert status    |
+--------------------------------------------------------------+
| Discipline Status Card | Core ETF Regime Card | Risk Card    |
| HEAVY / NORMAL / LIGHT / STOP                                |
+--------------------------------------------------------------+
| Today Action List                                            |
| 1. Add VOO in buy zone                                       |
| 2. Pause new QQQ adds                                        |
| 3. Satellite slot available: 1                               |
+--------------------------------------------------------------+
| Core ETF Snapshot                                            |
| VOO | HOLD | target 55% | buy zone | trim zone              |
| QQQ | PAUSE_BUY | target 20% | too extended                 |
| SCHD| ACCUMULATE | target 15% | defensive support           |
+--------------------------------------------------------------+
| Top 3 Satellite Ideas                                        |
| 1. MSFT | CONFIRMED | 4% target | summary                    |
| 2. MU   | PROBE     | 2% target | summary                    |
| 3. BRK.B| WATCH     | 0%        | summary                    |
+--------------------------------------------------------------+
| Change Feed                                                  |
| - QQQ downgraded from HOLD to PAUSE_BUY                      |
| - MU entered Top 3                                           |
| - Discipline moved NORMAL -> LIGHT                           |
+--------------------------------------------------------------+
```

核心要求：

- 第一屏不要出现大表格
- 第一屏必须有明确动作建议
- 第一屏必须有变化提示

## 18.3 Core ETFs 页面线框

目标：

- 专门做核心资产配置，不混入个股

线框建议：

```text
+--------------------------------------------------------------+
| Core ETF Universe Controls                                   |
| Enabled ETFs | Regime selector | Weight policy | Refresh     |
+--------------------------------------------------------------+
| Portfolio Allocation Summary                                 |
| Current weights vs target weights vs cash buffer             |
+--------------------------------------------------------------+
| ETF Cards Grid                                               |
| ------------------------------------------------------------ |
| VOO                                                          |
| Action: HOLD                                                 |
| Current 48% | Target 55% | Range 50%-60%                    |
| Buy zone: xxx~xxx | Max chase: xxx                          |
| Trim zone: xxx~xxx | Risk break: xxx                        |
| Summary: ...                                                 |
| ------------------------------------------------------------ |
| QQQ                                                          |
| Action: PAUSE_BUY                                            |
| Current 26% | Target 20% | Range 15%-25%                    |
| Summary: ...                                                 |
| ------------------------------------------------------------ |
| SCHD                                                         |
| Action: ACCUMULATE                                           |
| Current 8% | Target 15% | Range 10%-20%                     |
| Summary: ...                                                 |
+--------------------------------------------------------------+
| Expanded Details                                             |
| trend | relative strength | volatility | MC | freshness     |
+--------------------------------------------------------------+
```

交互要求：

- 支持配置启用 ETF
- 支持显示当前 ETF 是否在买入区间
- 支持显示当前 ETF 是否过热、不可追

## 18.4 Satellite Radar 页面线框

目标：

- 把当前卫星仓、候选池、Top 3 合成一个完整视图

线框建议：

```text
+--------------------------------------------------------------+
| Satellite Capacity                                           |
| Max slots: 3 | Used: 2 | Available: 1 | Max total weight 15% |
+--------------------------------------------------------------+
| Current Satellite Holdings                                   |
| MSFT | CONFIRMED | 4.0% | exit guide | summary              |
| MU   | PROBE     | 2.0% | exit guide | summary              |
+--------------------------------------------------------------+
| Top 3 Recommendations                                        |
| 1. GOOGL | CONFIRMED      | target 3%-5% | why now          |
| 2. BRK.B | WATCH          | target 0%-2% | why not yet      |
| 3. ANET  | OVERHEATED_WAIT| target 0%    | why wait         |
+--------------------------------------------------------------+
| Candidate Pool Top 10-20                                     |
| Rank | Symbol | Stage | Score | Backtest | MC | Events      |
+--------------------------------------------------------------+
| Candidate Filters                                            |
| sector | score bucket | stage | changed today | held only    |
+--------------------------------------------------------------+
```

交互要求：

- 当前持有卫星仓与候选池必须上下分区
- Top 3 必须单独视觉强化
- “人工备注”不作为核心列，`系统摘要`才是核心解释列

## 18.5 Risk & Discipline 页面线框

目标：

- 把“为什么不能重仓/为什么不能追”讲清楚

线框建议：

```text
+--------------------------------------------------------------+
| Discipline Banner                                            |
| LIGHT | New buys limited | Max satellite 10%                |
+--------------------------------------------------------------+
| Risk Gate Cards                                              |
| Market regime | VIX | drawdown | benchmark vol              |
+--------------------------------------------------------------+
| Portfolio Constraints                                        |
| concentration | correlation | cash buffer | exposure         |
+--------------------------------------------------------------+
| Analysis Freshness                                           |
| core ETF freshness | satellite freshness | expired symbols   |
+--------------------------------------------------------------+
| Blocking Reasons                                             |
| - QQQ too extended                                           |
| - Satellite exposure already near cap                        |
| - Event risk elevated                                        |
+--------------------------------------------------------------+
| Scoreboard                                                   |
| win rate | expectancy | profit factor | current regime edge  |
+--------------------------------------------------------------+
```

交互要求：

- 所有限制都要显式写出原因
- 该页要成为“停手理由面板”

## 18.6 Reports & Config 页面线框

目标：

- 将研究、配置、报告全部收口，不与主决策页面混杂

线框建议：

```text
+--------------------------------------------------------------+
| Latest Reports                                               |
| Nightly report | Quant analysis report | PDF | JSON | MD     |
+--------------------------------------------------------------+
| Notifications                                                |
| Slack | Email | alert cadence                                |
+--------------------------------------------------------------+
| LLM Config                                                   |
| provider | model | base_url | test connection                |
+--------------------------------------------------------------+
| Core ETF Universe Config                                     |
| enabled ETF list | roles | ordering                          |
+--------------------------------------------------------------+
| Candidate Pool Config                                        |
| universe size | max pool=100 | deep analysis size | top3     |
+--------------------------------------------------------------+
| Manual Actions                                               |
| force refresh | force nightly run | force candidate rebuild  |
+--------------------------------------------------------------+
```

---

## 19. 每页字段清单

## 19.1 Dashboard 字段

- `last_nightly_update_at`
- `last_market_refresh_at`
- `discipline_regime`
- `discipline_reason_top_3`
- `core_etf_regime`
- `risk_regime`
- `today_action_items`
- `top_3_satellite_symbols`
- `change_feed_items`
- `analysis_expired_count`

## 19.2 Core ETFs 字段

每个 ETF 卡片显示：

- `symbol`
- `role`
- `enabled`
- `current_price`
- `current_weight_pct`
- `target_weight_pct`
- `target_weight_range_low_pct`
- `target_weight_range_high_pct`
- `action`
- `recommended_buy_zone_low`
- `recommended_buy_zone_high`
- `max_chase_price`
- `trim_zone_low`
- `trim_zone_high`
- `risk_break_level`
- `expected_return_3m`
- `expected_return_12m`
- `confidence`
- `signal_reason`
- `system_summary`
- `analysis_freshness`

## 19.3 Satellite Radar 字段

每个候选股票显示：

- `symbol`
- `stage`
- `rank`
- `score_total`
- `score_trend`
- `score_fundamental`
- `score_theme`
- `score_model`
- `score_backtest`
- `risk_penalty`
- `signal`
- `signal_reason`
- `recommended_weight_pct`
- `recommended_weight_range`
- `expected_return`
- `monte_carlo_expected_return`
- `monte_carlo_var`
- `backtest_total_return`
- `backtest_win_rate`
- `suggested_exit_price`
- `analysis_freshness`
- `changed_today`
- `system_summary`
- `manual_note`

## 19.4 Risk & Discipline 字段

- `discipline_regime`
- `allow_new_buys`
- `allow_chasing`
- `max_total_exposure_pct`
- `max_core_etf_increment_pct`
- `max_satellite_total_weight_pct`
- `max_single_satellite_weight_pct`
- `risk_gate_regime`
- `risk_gate_reasons`
- `vix`
- `benchmark_drawdown`
- `benchmark_volatility`
- `concentration_alerts`
- `correlation_alerts`
- `analysis_expired_symbols`
- `scoreboard_completed_trades`
- `scoreboard_win_rate`
- `scoreboard_expectancy`
- `scoreboard_profit_factor`

## 19.5 Reports & Config 字段

- `latest_nightly_report_paths`
- `latest_quant_report_paths`
- `slack_enabled`
- `email_enabled`
- `llm_enabled`
- `llm_provider`
- `llm_model`
- `core_etf_universe`
- `candidate_pool_settings`
- `manual_run_controls`

---

## 20. 组件设计

## 20.1 顶层组件

建议新增以下 UI 组件：

### `DashboardHeader`

职责：

- 展示最近更新时间
- 展示系统状态灯
- 展示当前环境摘要

### `DisciplineBanner`

职责：

- 以最醒目的方式展示 `HEAVY/NORMAL/LIGHT/STOP`
- 给出 1-2 条限制性原因

### `ActionChecklist`

职责：

- 列出今日最重要动作
- 列出“不要做什么”

### `CoreEtfCard`

职责：

- 单 ETF 展示卡片
- 显示动作、权重、价位区间、摘要

### `TopRecommendationCard`

职责：

- 展示卫星仓 Top 3
- 突出状态、建议仓位、摘要、退出参考

### `CandidatePoolTable`

职责：

- 展示 Top 10-20 候选池明细
- 支持排序与筛选

### `RiskConstraintPanel`

职责：

- 展示所有当前限制
- 告诉用户为什么不能加仓或为什么必须轻仓

### `ChangeFeedPanel`

职责：

- 展示“今天变化了什么”

### `ReportCenter`

职责：

- 展示最近报告
- 支持下载与查看

## 20.2 组件设计原则

- 主组件优先用卡片
- 次级组件可用表格
- 原因解释默认折叠或 tooltip 展示
- 同一组件内不要混合核心 ETF 与卫星仓

## 20.3 颜色与状态规范

颜色建议只用于状态，不用于装饰：

- `绿色`：可加仓 / 正常 / 确认
- `黄色`：观望 / 偏旧 / 谨慎
- `红色`：停手 / 风险退出 / 趋势破坏
- `灰色`：无数据 / 未启用 / 暂不行动

状态命名要全局一致，不能页面 A 叫 `BUY`、页面 B 叫 `ACCUMULATE`、页面 C 又叫 `可以买入`。

建议统一做映射层。

---

## 21. 用户日常操作路径

## 21.1 每天开盘前路径

用户路径建议：

1. 打开 `Dashboard`
2. 看 `DisciplineBanner`
3. 看 `Today Action List`
4. 看 `Core ETF Snapshot`
5. 看 `Top 3 Satellite Ideas`
6. 如果需要，再进入 `Risk & Discipline` 看限制原因

系统目标：

- 60 秒内完成当天总判断

## 21.2 盘中路径

用户路径建议：

1. 先看 `Dashboard` 是否有变化提醒
2. 如果有 ETF 动作变化，进入 `Core ETFs`
3. 如果有卫星仓升级/降级，进入 `Satellite Radar`
4. 如果系统显示 `LIGHT/STOP`，进入 `Risk & Discipline` 核查原因

系统目标：

- 盘中只处理变化，不做重复浏览

## 21.3 夜间复盘路径

用户路径建议：

1. 进入 `Reports & Config`
2. 查看最新 night report
3. 查看候选池变化
4. 查看 Top 3 变化
5. 查看 LLM 摘要和系统解释

系统目标：

- 夜间以复盘和准备次日为主，而不是重新人工找票

## 21.4 手动研究路径

用户路径建议：

1. 在 `Satellite Radar` 里点开某只候选股
2. 查看：
   - 分数构成
   - 回测
   - Monte Carlo
   - 事件摘要
   - 系统摘要
3. 决定是否加入人工重点关注

系统目标：

- 深挖行为从主页面剥离，避免打断日常决策节奏

## 21.5 手动执行交易后的路径

用户路径建议：

1. 通过 Robinhood CSV 或手动操作同步持仓
2. 点击强制刷新数据
3. 查看 `Dashboard`
4. 查看纪律层是否变化
5. 确认 Top 3 和核心 ETF 权重是否仍合理

系统目标：

- 用户交易后能快速看到系统状态是否已更新

---

## 22. WebUI 实施映射

## 22.1 建议新增页面模块

建议新增：

- `app/ui/dashboard_page.py`
- `app/ui/core_etf_page.py`
- `app/ui/satellite_page.py`
- `app/ui/risk_page.py`
- `app/ui/report_center_page.py`

## 22.2 建议新增组件模块

建议新增：

- `app/ui/components_dashboard.py`
- `app/ui/components_core_etf.py`
- `app/ui/components_satellite.py`
- `app/ui/components_risk.py`
- `app/ui/components_reports.py`

## 22.3 main.py 目标状态

`main.py` 最终只负责：

- session bootstrapping
- 数据加载
- 页面路由
- 顶层 flash notice

而不再负责大段页面绘制细节。

## 22.4 Phase 7 UI 改版顺序

建议顺序：

1. 先做 `Dashboard`
2. 再做 `Core ETFs`
3. 再做 `Risk & Discipline`
4. 再做 `Satellite Radar`
5. 最后做 `Reports & Config`

原因：

- 先做总览和纪律，立刻提升可用性
- 再做核心 ETF，最贴近账户主决策
- 最后再细化卫星仓雷达
