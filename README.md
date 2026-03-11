# AI量化交易系统（A股）

## 项目简介

基于人工智能的A股量化交易系统，支持策略选股、回测、实盘交易和风险控制。

**跨平台支持**：Windows 和 Linux 自动兼容，无需手动修改，开箱即用。

详见：[跨平台兼容说明](docs/setup/CROSS_PLATFORM.md) | [Windows完整指南](docs/setup/WINDOWS_GUIDE.md)

## ⚠️ 风险警告

**本系统涉及真实资金交易，使用前请务必：**
- 充分理解股票交易风险
- 在模拟环境充分测试
- 设置严格的风控参数
- 遵守相关法律法规

---

## 系统特性

- **9 单策略 + 5 组合**：MA/MACD/RSI/BOLL/KDJ/DUAL（技术面 6 个）、PE/PB/PEPB（基本面 3 个）；情绪/新闻/政策/资金流（V3.3 扩展 4 个）；EnsembleStrategy（9 子策略加权投票）/保守/均衡/激进/V33 组合
- **策略选股**：多策略组合从股票池挑选优质股票，综合评分排序
- **单股/持仓分析**：跑遍 11 单策略 + PE/PB + 5 组合，给出买卖建议
- **双核动量 ETF 轮动**：完整实现，含回测、可视化、月度调仓
- **策略回测引擎**：支持大规模批量回测、本地数据预取、未来函数检查
- **多层风控**：账户/策略/个股/系统四层风控
- **自动化交易（可选）**：支持同花顺桌面客户端和网页自动化

---

## 🚀 快速开始

### 安装依赖

```bash
# 策略选股（最小依赖）
pip3 install --user pandas numpy akshare loguru

# 桌面自动化（可选）
sudo apt-get install python3-tk python3-dev -y
pip3 install --user pyautogui psutil pillow pyyaml
```

Windows 用户：双击 `scripts\start_windows.bat`，选择 `6` 安装依赖。

### 核心功能入口

```bash
# 策略选股（从股票池选出 TOP 20）
python3 tools/analysis/recommend_today.py --pool mydate/stock_pool.json --strategy ensemble --top 20

# 单股多策略分析（11 单策略 + PE/PB + 5 组合）
python3 tools/analysis/analyze_single_stock.py 600519 --name "贵州茅台"

# 持仓分析
python3 tools/analysis/portfolio_strategy_analysis.py

# ETF 轮动回测
python3 tools/backtest/backtest_dual_momentum.py
```

---

## 🎯 策略选股系统

系统核心功能：**根据多策略组合从股票池中挑选优质股票**。

### 支持的策略

**技术面（6 个）**：MA（均线交叉）、MACD、RSI、BOLL（布林带）、KDJ、DUAL（双核动量单股）

**基本面（3 个）**：PE（历史 PE 分位数）、PB（历史 PB 分位数）、PEPB（PE+PB 双因子联合低估）

**V3.3 扩展（4 个）**：Sentiment（市场情绪）、NewsSentiment（新闻情感）、PolicyEvent（政策事件）、MoneyFlow（龙虎榜/大宗）

**组合策略（5 个）**：**EnsembleStrategy**（9 子策略加权投票，含持仓成本止损感知）、保守、均衡、激进、**V33**（13 子策略，重大利空优先）

详见 [策略清单](docs/strategy/STRATEGY_LIST.md)。

### 使用方法

```bash
# 7 策略 Ensemble 选股（MA+MACD+RSI+BOLL+KDJ+DUAL+PE），TOP 20
python3 tools/analysis/recommend_today.py --pool mydate/stock_pool_all.json --strategy ensemble --top 20

# 单 MACD 策略选股
python3 tools/analysis/recommend_today.py --pool mydate/stock_pool.json --strategy macd --top 10

# 单股跑遍所有策略
python3 tools/analysis/analyze_single_stock.py 600519 --name "贵州茅台"

# 持仓多策略分析
python3 tools/analysis/portfolio_strategy_analysis.py
```

### 输出内容

- 每只股票的 11 单策略 + PE/PB + 5 组合信号（买入/卖出/观望）
- 综合评分和排名
- 资金流状态
- 推荐理由和建议仓位

---

## 📊 股票池管理

股票池文件位于 `mydate/` 目录：

| 文件 | 说明 |
|------|------|
| `stock_pool.json` | 赛道龙头池（光伏/机器人/半导体/有色/证券/创新药/商业航天，约 48 只） |
| `stock_pool_all.json` | 综合池（沪深300+中证500经基本面过滤，660 只个股 + 57 只 ETF） |
| `etf_pool.json` | ETF 池（宽基/科技/消费/金融/周期/医药/地产/跨境，57 只） |

```bash
# 刷新股票池（含基本面过滤）
python3 tools/data/refresh_stock_pool.py

# 季度更新（同步指数成分调整）
python3 tools/data/quarterly_update.py
```

过滤规则：PE 0-100、市值 > 30亿、非ST股票。

---

## 📈 策略回测

### 大规模批量回测

```bash
# 先预取日线到本地（显著提速）
python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool_all.json --all --out-dir mydate/backtest_kline --workers 4

# 再跑回测（自动读本地数据）
python3 tools/backtest/batch_backtest.py --pool mydate/stock_pool_all.json --count 300 --local-kline mydate/backtest_kline
```

详见 [数据接口与容错](docs/data/API_INTERFACES_AND_FETCHERS.md)。

### 双核动量 ETF 轮动回测

```bash
# 完整回测（自动下载数据 + 生成报告 + 绘制图表）
python3 tools/backtest/backtest_dual_momentum.py

# 快速测试（1 分钟）
python3 tests/test_dual_momentum_quick.py
```

策略原理：绝对动量（价格 > 200日均线）+ 相对动量（选涨幅最大的）+ 每月调仓。

详见 [双核动量策略指南](docs/strategy/DUAL_MOMENTUM_GUIDE.md)。

---

## 🤖 自动化交易（可选）

> 自动化交易是可选功能。你也可以只用策略选股功能，根据推荐结果**手动交易**。

### 方式1：桌面客户端自动化（推荐）

```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

broker = TonghuashunDesktop({'auto_start': True})
if broker.login():
    broker.buy('600519', 1800.0, 100)
    broker.close()
```

详见 [桌面交易指南](docs/setup/DESKTOP_TRADING_GUIDE.md)。

### 方式2：网页自动化

```python
from src.api.broker.tonghuashun_simulator import TonghuashunSimulator

broker = TonghuashunSimulator({'username': '...', 'password': '...', 'headless': False})
if broker.login():
    broker.buy('600519', 1800.0, 100)
    broker.logout()
broker.close()
```

详见 [网页交易指南](docs/setup/WEB_TRADING_GUIDE.md)。

---

## 🎮 模拟交易

```bash
python3 examples/paper_trading_demo.py
# 模式1: 手动交易  模式2: 策略自动
```

详见 [模拟交易指南](docs/setup/PAPER_TRADING_GUIDE.md)。

---

## 项目结构

```
ai-trading-system/
├── README.md
├── requirements.txt
├── run_daily.py             # ETF 轮动每日分析入口
│
├── config/                  # 配置文件
│   ├── trading_config.yaml(.example)
│   ├── risk_config.yaml(.example)
│   ├── data_sources.yaml    # 数据源优先级配置
│   └── news_source_weights.yaml、policy_overrides.yaml 等
│
├── src/                     # 核心源代码
│   ├── main.py              # 统一 CLI 入口
│   ├── strategies/          # 11 单策略 + 5 组合（见 docs/strategy/STRATEGY_LIST.md）
│   ├── core/                # 核心模块
│   │   ├── base_strategy.py     # 策略基类（BaseStrategy）
│   │   ├── dual_momentum_strategy.py  # 双核动量策略
│   │   ├── momentum_math.py     # 动量计算共用函数
│   │   ├── strategy_rule_engine.py    # 策略规则引擎
│   │   ├── strategy_executor.py       # 策略执行器
│   │   ├── backtest_constraints.py    # 回测未来函数约束
│   │   ├── risk/            # 风险管理
│   │   └── simulator/       # 模拟交易
│   ├── etf_rotation/        # ETF 轮动系统（信号引擎/持仓/交易日志）
│   ├── data/                # 数据服务
│   │   ├── provider/        # 统一数据层（UnifiedDataProvider + 适配器）
│   │   ├── fetchers/        # 数据获取（行情/基本面/ETF）
│   │   ├── sentiment/       # 市场情绪指数
│   │   ├── news/            # 新闻情感
│   │   ├── policy/          # 政策事件
│   │   └── money_flow/      # 龙虎榜/大宗交易
│   ├── api/broker/          # 券商自动化（同花顺桌面/网页）
│   └── config/              # 平台配置
│
├── tools/                   # 工具脚本（详见 tools/README.md）
├── tests/                   # 测试代码
├── examples/                # 使用示例
├── scripts/                 # Shell/Bat 启动脚本
├── docs/                    # 文档
├── mydate/                  # 数据文件（股票池、持仓、回测结果）
├── mycache/                 # 缓存文件（基本面、K线）
├── mylog/                   # 日志
└── myoutput/                # 输出（图表、报告）
```

---

## 策略与设计文档

| 文档 | 说明 |
|------|------|
| [V3.3 设计规格](docs/strategy/V33_DESIGN_SPEC.md) | 情绪/消息/政策/龙虎榜完整设计规格与落地状态 |
| [回测与实盘规范](docs/strategy/BACKTEST_AND_LIVE_SPEC.md) | 未来函数约束、参数敏感性、成本与延迟 |
| [策略清单](docs/strategy/STRATEGY_LIST.md) | 11 单策略 + 5 组合与工具对应关系 |
| [策略详解](docs/strategy/STRATEGY_DETAIL.md) | 各策略信号逻辑、参数、置信度映射 |
| [策略开发快速开始](docs/strategy/STRATEGY_QUICKSTART.md) | 5 分钟上手策略开发 |
| [双核动量指南](docs/strategy/DUAL_MOMENTUM_GUIDE.md) | ETF 轮动策略完整使用指南 |
| [策略执行指南](docs/strategy/STRATEGY_EXECUTION_GUIDE.md) | 规则引擎、审批流程、审计日志 |
| [数据接口与容错](docs/data/API_INTERFACES_AND_FETCHERS.md) | 各策略数据接口、主备切换、回测预取 |
| [数据层架构](docs/architecture/DATA_LAYER_ARCHITECTURE.md) | 四层架构设计与扩展指南 |
| [运行命令汇总](docs/RUN_COMMANDS.md) | 常用命令一页汇总 |

---

## 策略开发

新策略继承 `src.strategies.base.Strategy`，接收 K 线 DataFrame，返回 `StrategySignal`：

```python
from src.strategies.base import Strategy, StrategySignal

class MyStrategy(Strategy):
    def analyze(self, df, **kwargs) -> StrategySignal:
        # df: date, open, high, low, close, volume, amount
        # 返回 StrategySignal(action, confidence, position, reason, indicators)
        pass
```

在 `src/strategies/__init__.py` 的 `STRATEGY_REGISTRY` 中注册后即可用于所有工具。

详见 [策略开发快速开始](docs/strategy/STRATEGY_QUICKSTART.md)。

---

## 风控系统

四层风控：
1. **账户级**：单日最大亏损、总仓位、现金储备
2. **策略级**：单策略仓位、回撤控制、夏普比率监控
3. **个股级**：单股最大仓位、止损止盈、涨跌停限制
4. **系统级**：交易频率限制、异常检测、紧急熔断

---

## 注意事项

1. **合规性**：确保交易行为符合监管要求
2. **资金安全**：建议使用独立账户，设置止损
3. **测试充分**：实盘前务必充分回测和模拟
4. **持续监控**：实盘运行时需要密切监控

## 许可证

本项目仅供学习和研究使用，使用者需自行承担一切交易风险。

---

**再次提醒：股市有风险，投资需谨慎！**
