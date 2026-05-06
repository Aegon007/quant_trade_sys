# 量化持仓追踪与策略回测系统

一个基于 Streamlit 的本地量化投资组合工具，用于管理持仓、维护观察列表、刷新行情、生成量化信号、执行策略回测，并在组合层面提示行业集中度和相关性风险。

> 说明：本项目用于研究、学习和辅助决策，不构成投资建议。真实交易前请结合账户风险、税务、流动性和券商规则独立判断。

## 功能概览

- 持仓管理：支持添加、编辑、删除和部分卖出持仓，最小交易单位为 `0.001` share，适合 Robinhood 等支持 fractional shares 的账户。
- 观察列表：维护关注股票、备注和目标买入价，并可刷新最新价格。
- 实时行情：通过 Yahoo Finance 获取持仓和观察列表价格，并使用本地缓存减少重复请求。
- 单股策略信号：为持仓或关注股票显示买入、持有、卖出信号和原因。
- 仓位建议：结合当前持仓、目标仓位和回测结果，给出加仓、减仓、退出或观望建议。
- 组合级建议：分析行业集中度和高相关股票组合，避免只看单只股票信号而忽略整体风险。
- 策略回测：支持 Backtrader 和 PyBroker 两个回测引擎，输出收益、夏普比率、最大回撤、胜率和资金曲线。
- 策略插件化：新增策略时优先通过 `config/strategies.json` 配置类路径和信号函数路径，减少修改注册代码。
- 深度学习模型：内置 TCN 深度学习策略，可自动适配 CUDA、Apple Silicon MPS 或纯 CPU 环境。
- 本地数据文件：持仓、观察列表、交易记录、价格缓存都保存在本地 JSON 文件中，无需数据库。

## 快速开始

### 1. 创建环境

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 启动应用

```bash
streamlit run main.py
```

启动后在浏览器中打开 Streamlit 提供的本地地址。默认界面支持中文和英文切换。

### 3. 运行测试

```bash
PYTHONPYCACHEPREFIX=/tmp/pycache .venv/bin/python -m unittest discover -s tests -v
```

当前测试覆盖 fractional shares、数据文件同步、策略注册、组合建议、仓位建议、回测引擎适配和 RSI 参数修复等关键路径。

## 手工维护持仓与观察列表

除了通过 UI 添加和编辑，也可以直接维护 `portfolio_input.json`。系统会在启动或页面重跑时检测这个文件：当它比运行时文件 `portfolio_data.json` 更新时，会自动导入。侧边栏也提供“从文件重新加载持仓/关注”按钮，可以强制同步。

`portfolio_input.json` 是个人数据文件，已经加入 `.gitignore`。仓库中提供了 [portfolio_input.example.json](portfolio_input.example.json) 作为格式参考。

```json
{
  "holdings": [
    {
      "symbol": "AAPL",
      "shares": 0.125,
      "cost": 180.5,
      "sector": "Technology"
    },
    {
      "symbol": "IAU",
      "shares": 1.0,
      "cost": 90.4,
      "sector": "Gold"
    }
  ],
  "watchlist": [
    {
      "symbol": "MSFT",
      "notes": "Wait for pullback",
      "target_buy": 390.0
    }
  ]
}
```

同步规则：

- `symbol` 会自动转成大写。
- `shares` 必须大于等于 `0.001`。
- `cost` 是持仓成本价，`sector` 用于组合行业集中度分析。
- `current_price` 和 `last_price` 可以省略；系统会按股票代码尽量保留已有运行时价格。
- 如果文件中只写 `holdings` 或只写 `watchlist`，未写的部分会保留当前运行时数据。
- 如果需要清空某一部分，请显式写成空数组，例如 `"watchlist": []`。

## 数据文件说明

- `portfolio_input.json`：手工维护入口，适合批量修改持仓和观察列表，不提交到 Git。
- `portfolio_data.json`：应用运行时数据，保存当前持仓、观察列表、最新价格和更新时间。
- `price_cache.json`：行情缓存文件，减少短时间内重复请求。
- `transactions.json`：卖出操作产生的交易记录。
- `config/strategies.json`：策略配置文件，控制 UI 展示、回测策略类和信号函数。

## 策略与回测

当前内置策略包括：

- 双均线交叉：`MA(20)` 和 `MA(50)` 金叉买入、死叉卖出。
- 布林带反转：价格接近下轨时关注反弹，回到中轨附近考虑止盈。
- MACD 金叉死叉：动能转强买入，动能转弱卖出。
- RSI 超买超卖：低位回升买入，高位回落卖出。
- LightGBM ML 策略：基于滚动训练预测未来收益方向。
- 集成投票策略：组合 LightGBM、CatBoost、XGBoost 的预测概率。
- TCN 深度学习策略：使用一维时序卷积网络学习最近一段技术特征序列，预测未来上涨概率和条件预期收益。

回测流程：

1. 在“量化分析”页选择股票。
2. 选择策略和回测引擎，默认推荐 Backtrader。
3. 运行回测，查看累计收益、夏普比率、最大回撤、胜率和资金曲线。
4. 系统会结合回测结果和当前持仓，生成更偏仓位管理的建议。

## 新增策略

新增策略时，优先使用配置式扩展，不需要修改 `strategy_registry.py` 或 `strategy_ui.py`。

### 1. 实现策略类

策略类需要继承 `engine.base.BaseStrategy`，并实现 `init()` 和 `next(i)`：

```python
from engine.base import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self, window=20):
        super().__init__({"window": window})
        self.window = window
        self.ma = None

    def init(self):
        self.ma = self.data["Close"].rolling(self.window).mean()

    def next(self, i):
        if i < self.window:
            return None
        if self.data["Close"].iloc[i] > self.ma.iloc[i]:
            return {"action": "BUY", "size": 100}
        return {"action": "HOLD", "size": 0}
```

### 2. 实现当前信号函数

信号函数用于 UI 中显示某只股票当前是买入、持有还是卖出：

```python
def get_my_signal(symbol, window=20):
    return "HOLD", f"{symbol} 暂无明确突破信号"
```

### 3. 添加配置

在 `config/strategies.json` 的 `strategies` 数组中添加：

```json
{
  "id": "my_strategy",
  "name": "我的策略",
  "description": "策略说明",
  "strategy_class": "strategies.my_strategy.MyStrategy",
  "signal_function": "strategies.my_strategy.get_my_signal",
  "params": {
    "window": 20
  }
}
```

如果策略类构造函数接收整个参数字典，而不是展开后的关键字参数，可以加：

```json
{
  "params_mode": "dict"
}
```

## 深度学习策略

`deep_tcn` 是第一版深度学习量化模型，设计目标是稳、轻、容易回测，而不是一开始就堆很大的 Transformer。它复用现有技术指标特征，并把最近 `sequence_length` 天的特征序列输入 Temporal CNN。

默认设备参数为：

```json
{
  "device": "auto"
}
```

自动选择顺序：

- 有 NVIDIA GPU 时使用 `cuda`。
- 在 Apple Silicon Mac 且 PyTorch 支持 MPS 时使用 `mps`。
- 其他环境自动回落到 `cpu`。

如果当前环境没有安装 PyTorch，系统不会崩溃，深度学习策略会返回 `HOLD` 并提示依赖缺失。安装方式：

```bash
pip install "torch>=2.2.0"
```

## 组合级建议

组合建议不只看单个股票信号，还会结合整体风险：

- 行业集中度：如果某个 `sector` 的市值占比过高，会提示可能需要降低集中度或增加其他板块暴露。
- 相关性拥挤：如果两个持仓历史收益相关性过高，且合计仓位较大，会提示避免同时继续加仓。
- 缺失价格：如果持仓没有现价，组合建议会提示这些标的暂未纳入组合级计算。

为了让行业集中度分析更准确，建议在 `portfolio_input.json` 或 UI 编辑持仓时维护 `sector`。

## 目录结构

```text
.
├── main.py                         # Streamlit 应用入口
├── data_utils.py                   # 数据加载、保存、行情刷新和手工文件同步
├── quant_analysis.py               # 技术指标、信号和风险分析
├── portfolio_advisor.py            # 组合行业集中度和相关性建议
├── position_advisor.py             # 仓位管理建议
├── strategy_registry.py            # 配置驱动的策略实例化
├── strategy_ui.py                  # 策略配置加载和当前信号计算
├── engine/                         # Backtrader / PyBroker 回测适配器
├── strategies/                     # 内置策略实现
├── config/strategies.json          # 策略配置
├── portfolio_input.example.json    # 手工持仓文件示例
└── tests/                          # 单元测试
```

## 开发约定

- 优先使用 TDD：先补测试，再修改实现。
- 新增功能后运行完整测试：`python -m unittest discover -s tests -v`。
- 不要把个人运行数据提交到 Git，例如 `portfolio_input.json`、`portfolio_data.json`、`price_cache.json`、`transactions.json`。
- 新增策略优先走 `config/strategies.json`，只有通用接口无法表达时再修改注册逻辑。
