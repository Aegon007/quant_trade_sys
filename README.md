# 📊 Portfolio & Watchlist Tracker with ML Signals

基于 Streamlit 的轻量级投资组合追踪与量化信号系统，集成 LightGBM 机器学习策略。

## ✨ 功能亮点

- **持仓管理**：添加、编辑、删除持仓，自动计算盈亏与市值。
- **实时行情**：一键刷新 Yahoo Finance 最新价格，支持缓存。
- **关注列表**：记录潜在标的，设置目标买入价。
- **交易记录**：卖出时自动记录，统计累计盈亏。
- **量化策略回测**：双均线、布林带、MACD、RSI 及 **LightGBM ML 策略**。
- **动态交易信号**：根据选定策略，为每只持仓生成“买入/持有/卖出”信号。
- **ML 策略（新增）**：基于 LightGBM 梯度提升树，集成滚动训练与超参数优化。
- **组合风险分析**：计算组合 Beta（vs SPY）及持仓相关性矩阵。
- **模块化设计**：策略配置与代码分离，便于扩展。

## 🚀 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行应用
streamlit run main.py
```

## 📁 项目结构

```
.
├── main.py                 # 主入口
├── ui_components.py        # UI 组件
├── data_utils.py           # 数据持久化与行情缓存
├── transactions.py         # 交易记录
├── quant_analysis.py       # 传统技术指标与策略
├── ml_strategy.py          # ML 策略核心（LightGBM + Optuna）
├── strategy_ui.py          # 策略选择与信号路由
├── config/
│   └── strategies.json     # 策略配置
└── README.md
```

## 🤖 ML 策略说明

LightGBM 策略使用以下设计：

| 组件 | 说明 |
|------|------|
| 特征工程 | 20+ 技术因子（动量、波动率、RSI、MACD 等） |
| 训练方式 | Walk-Forward 滚动窗口，每 20 个交易日重新训练 |
| 超参数优化 | Optuna 自动搜索最优参数 |
| 信号生成 | 预测上涨概率 > 0.55 买入，< 0.45 卖出 |
| 风险控制 | 最大持仓 20 天，强制止盈止损 |

**注意**：ML 策略需要至少 252 个交易日的历史数据，冷启动时可能无法生成信号。

## 📝 许可证

本项目仅供个人学习与投资研究使用。