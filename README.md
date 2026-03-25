# AI量化交易系统（A股）

基于多策略组合的A股量化交易系统，支持策略选股、回测验证、持仓分析和实盘自动化交易。

**跨平台支持**：Windows 和 Linux 自动兼容，无需手动修改，开箱即用。

---

## ⚠️ 风险警告

**本系统涉及真实资金交易，使用前请务必：**
- 充分理解股票交易风险，在模拟环境充分测试
- 设置严格的风控参数，遵守相关法律法规
- 本项目仅供学习和研究使用，使用者需自行承担一切交易风险

---

## 📊 当前策略状态（2026-03-25）

**核心策略**：11策略Ensemble（固定权重加权投票）

**实际运行架构**：
- ✅ **L0: PolicyEvent 大盘过滤器** - 极端利空时暂停选股
- ✅ **L3: 11策略加权投票** - 使用已验证的固定权重（基于235只股票回测）
- ❌ **L1: 市场状态感知** - 经验证后永久禁用（MarketRegimeEngine + Sentiment）
- ❌ **L2: 权重动态调整** - 经验证后永久禁用（动态权重不如固定权重）

**L1/L2 验证结论**（2026-03-24）：
- **L1层（市场状态感知）**：MarketRegimeEngine 基于MA交叉识别牛熊，但实测发现：
  - 识别滞后严重（MA交叉本身就是滞后指标）
  - 震荡市误判频繁（2024年震荡期错判为熊市）
  - 固定权重在所有市场状态下表现更稳定
- **L2层（动态权重调整）**：通过滚动窗口回测优化调整系数，但实测发现：
  - 固定权重夏普比率 **0.127** > 动态权重 0.115
  - 固定权重年化收益 **9.1%** > 动态权重 8.7%
  - 固定权重最大回撤 **-17.3%** < 动态权重 -18.2%
  - **结论**：保持固定权重，L1/L2层暂不启用

**关键特性**：
- DUAL 策略已反向（IC从-0.39提升至+0.39，p<0.000001）
- 净得分投票机制（阈值0.07/-0.07，最少1票）
- 11策略固定权重：BOLL(1.5), MACD(1.3), KDJ(1.1), MA(1.0), DUAL(0.9), RSI(0.8), PEPB(0.8), PE(0.6), PB(0.6), NEWS(0.5), MONEY_FLOW(0.4)
- **专题板块推荐**：支持自动追加专题板块分析（如核电+算电协同）

---

## 系统概览

| 模块 | 说明 |
|------|------|
| **每日推荐** | 11策略从808只股票池筛选TOP 20，自动生成增量跟踪文档 📊 |
| **专题板块推荐** | 自动追加专题板块分析（如核电+算电协同），无需手动操作 🔋 |
| **持仓跟踪** | 记录买入/卖出操作，追踪盈亏，每日自动更新 💼 |
| **策略选股** | 11策略 Full Ensemble（技术6+基本面3+消息面+资金面）从综合大池筛选，加权评分排序 |
| **持仓分析** | 对当前持仓跑全策略信号，给出操作建议和风险提示 |
| **策略回测** | 大规模批量回测（200+只股票 × 3年），支持本地数据缓存加速 |
| **自动化交易** | 同花顺桌面/网页自动化，可选功能 |

---

## 🚀 快速开始

### 安装依赖

```bash
# 核心依赖（策略选股 + 回测）
pip3 install --user pandas numpy akshare baostock loguru

# 桌面自动化（可选，仅自动交易需要）
sudo apt-get install python3-tk python3-dev -y
pip3 install --user pyautogui psutil pillow pyyaml
```

Windows 用户：双击 `scripts\start_windows.bat`，选择 `6` 安装依赖。

### 日常使用流程

#### 🆕 推荐：一键每日更新（Windows）

```bash
# 快速模式（5-10分钟）
scripts\daily_update.bat --quick

# 完整模式（30-45分钟，含股票池更新）
scripts\daily_update.bat
```

**自动完成**：
- ✅ 更新股票池（HS300/ZZ500/7大板块，721只）
- ✅ 生成今日TOP 30推荐（11策略分析）
- ✅ 更新每日跟踪文档
- ✅ 检查持仓盈亏

**查看结果**: `docs\DAILY_TRACKING.md`

---

#### 传统方式（分步执行）

```bash
# 第一步：更新本地数据缓存（每周/每月执行一次）
python3 tools/data/backtest_prefetch.py --update --out-dir mydate/backtest_kline --workers 4
python3 tools/data/prefetch_pe_cache.py --update

# 第二步：今日选股推荐（从 808 只综合池选出 TOP 20）
python3 tools/analysis/recommend_today.py --strategy full_11 --top 20

# 🆕 今日推荐 + 专题板块（自动整合，推荐使用）
python3 tools/analysis/recommend_today.py --strategy full_11 --top 20 --append-sectors

# 第三步：仅更新持仓分析（不重新扫描股票池）
python3 tools/analysis/recommend_today.py --only-holdings

# 可选：单股深度分析
python3 tools/analysis/analyze_single_stock.py 600519 --name "贵州茅台"
```

---

## 🔋 专题板块推荐（新功能）

**自动整合专题板块分析到每日推荐报告**

### 使用方法

```bash
# 生成每日推荐 + 自动追加专题板块分析
python3 tools/analysis/recommend_today.py --strategy full_11 --top 20 --append-sectors
```

### 功能特点

- ✅ **自动整合**：专题推荐自动追加到主报告末尾，不覆盖主推荐
- ✅ **数据一致**：使用相同的缓存数据，确保时间戳一致
- ✅ **性能优化**：专题分析使用缓存，避免重复网络请求
- ✅ **可扩展**：可轻松添加更多专题（在 `SECTOR_THEMES` 中配置）

### 当前支持的专题

| 专题 | 股票池 | 说明 |
|------|--------|------|
| 核电+算电协同 | 52只 | AI算力需求爆发，电力基础设施成为关键瓶颈。核电作为清洁、稳定的基荷电源，与算力中心形成协同效应 |

### 报告结构

生成的报告包含：
1. **我的持仓** - 当前持仓概览
2. **今日持仓操作建议** - 基于最新策略信号的持仓操作建议
3. **每日推荐** - 全市场808只股票的TOP20推荐
4. **🔋 专题板块推荐** - 核电+算电协同TOP10（自动追加）
5. **历史推荐** - 往日推荐记录

### 添加新专题

在 `tools/analysis/generate_sector_themes.py` 中配置：

```python
SECTOR_THEMES = {
    "your_theme_key": {
        "name": "您的专题名称",
        "description": "专题投资逻辑说明",
        "pool_file": "mydate/stock_pool_your_theme.json",
        "top_n": 10,
        "icon": "🎯"
    }
}
```

---

## 🎯 策略体系

### 9 个单策略

**技术面（6个）**

| 策略 | 文件 | 信号逻辑 | 回测夏普 | 回测收益 |
|------|------|----------|----------|----------|
| MA | `ma_cross.py` | 短期均线上穿长期均线 | 0.12 | +13.9% |
| MACD | `macd_cross.py` | MACD 金叉/死叉 + 柱状图变化 | 0.16 | +15.3% |
| RSI | `rsi_signal.py` | RSI 超卖反弹 / 超买回落 | 0.07 | +10.2% |
| BOLL | `bollinger_band.py` | 价格触及布林带下轨反弹 | **0.20** | +15.0% |
| KDJ | `kdj_signal.py` | KDJ 金叉 / 死叉 | 0.15 | +13.5% |
| DUAL | `dual_momentum.py` | 绝对动量 + 相对动量单股版 | — | — |

> 回测数据：235只股票，3年历史（2022-2025），含手续费。BOLL 综合表现最优（夏普最高、回撤最小13.9%）。

**基本面（3个）**

| 策略 | 文件 | 信号逻辑 | 回测夏普 | 回测收益 |
|------|------|----------|----------|----------|
| PE | `fundamental_pe.py` | 当前PE低于历史30%分位数 → 低估买入 | 0.11 | +8.2% |
| PB | `fundamental_pb.py` | 当前PB低于历史30%分位数 → 低估买入 | — | — |
| PEPB | `fundamental_pe_pb.py` | PE + PB 双因子同时低估，信号更强 | — | — |

> 基本面数据来源：Baostock，本地缓存于 `mydate/pe_cache/`（779只股票），详见 [PE缓存指南](docs/data/PE_CACHE_GUIDE.md)。

### EnsembleStrategy（主力组合策略）

11个子策略加权投票，综合技术面、基本面、消息面和资金面信号：

```
买入条件：加权得分 ≥ 0.45，且至少 2 个策略同时发出买入信号
卖出条件：加权得分 ≤ -0.45，且至少 2 个策略同时发出卖出信号
```

**当前权重配置**（基于回测结果优化）：

| 策略 | 权重 | 依据 |
|------|------|------|
| BOLL | 1.5 | 夏普最高(0.20)、回撤最小(13.9%) |
| MACD | 1.3 | 收益最高(+15.3%)，夏普第二(0.16) |
| KDJ | 1.1 | 夏普第三(0.15)，盈利率70.6% |
| MA | 1.0 | 收益第三(+13.9%) |
| DUAL | 0.9 | 绝对+相对动量，保守权重 |
| RSI | 0.8 | 夏普最低(0.07)，降权 |
| PEPB | 0.8 | 双因子共振，信号强但数据要求高 |
| PE | 0.6 | 回撤最小(9%)，辅助过滤 |
| PB | 0.6 | 单因子PB |
| Sentiment | 0.7 | 市场情绪指数，V3.3多指标合成 |
| NEWS | 0.5 | 新闻情感+LLM分析 |
| PolicyEvent | 0.7 | 政策面事件识别 |
| MoneyFlow | 0.4 | 龙虎榜+大宗资金流 |

**持仓成本感知**：传入 `avg_cost` 时，自动触发止损（-8%）和预警（-5%）逻辑。
**重大利空优先**：任一策略触发"重大利空"关键词时，无条件卖出，不经投票。
**动态权重**：根据沪深300市场状态（牛市/熊市/震荡）自动调整各策略权重。

---

## 📊 股票池

| 文件 | 说明 | 数量 |
|------|------|------|
| `mydate/stock_pool_all.json` | 综合池（沪深300+中证500经基本面过滤） | **808只** |
| `mydate/stock_pool_nuclear_computing.json` | 专题池（核电+算电协同：核电设备/电力运营/算力基础设施/智能电网） | 52只 |
| `mydate/stock_pool.json` | 赛道龙头池（光伏/机器人/半导体/有色/证券/创新药/商业航天） | 约48只 |
| `mydate/etf_pool.json` | ETF池（宽基/科技/消费/金融/周期/医药/地产/跨境） | 57只 |

**过滤规则**（综合池）：PE 0-100、市值 > 30亿、非ST股票。

**专题池配置**：在 `tools/analysis/generate_sector_themes.py` 的 `SECTOR_THEMES` 中配置，支持自动追加到每日推荐报告。

```bash
# 刷新综合股票池（重新拉取成分股 + 基本面过滤）
python3 tools/data/refresh_stock_pool.py

# 季度更新（同步指数成分调整）
python3 tools/data/quarterly_update.py
```

---

## 📈 策略回测

### 最新回测结果（2022-2025，235只股票）

| 策略 | 平均收益 | 夏普比率 | 最大回撤 | 盈利率 |
|------|----------|----------|----------|--------|
| BOLL | +15.0% | **0.20** | **13.9%** | 74.0% |
| MACD | +15.3% | 0.16 | 19.7% | 65.5% |
| KDJ | +13.5% | 0.15 | 18.6% | 70.6% |
| MA | +13.9% | 0.12 | 18.8% | 63.8% |
| RSI | +10.2% | 0.07 | 16.1% | 68.5% |
| PE | +8.2% | 0.11 | **9.0%** | 56.2% |
| Ensemble | +9.1% | 0.05 | 17.3% | 63.0% |

> Ensemble 当前权重已基于上表结果优化（BOLL/MACD 提权），下次回测可验证效果。

### 运行批量回测

```bash
# 第一步：预取 K 线数据到本地（首次，约 1-2 小时）
python3 tools/data/backtest_prefetch.py \
  --pool mydate/stock_pool_all.json --all \
  --out-dir mydate/backtest_kline --workers 4

# 第二步：预取 PE/PB 数据（基本面策略需要）
python3 tools/data/prefetch_pe_cache.py --update

# 第三步：跑回测（自动读本地缓存，约 30-60 分钟）
python3 tools/backtest/batch_backtest.py \
  --pool mydate/stock_pool_all.json --count 300 \
  --local-kline mydate/backtest_kline

# 后台运行（防止终端关闭中断）
nohup python3 tools/backtest/batch_backtest.py \
  --pool mydate/stock_pool_all.json --count 300 \
  --local-kline mydate/backtest_kline \
  > mylog/backtest.log 2>&1 &

# 定期更新 K 线缓存（每周执行）
python3 tools/data/backtest_prefetch.py \
  --update --out-dir mydate/backtest_kline --workers 4
```

回测结果保存至 `mydate/backtest_results_v3.json`。

### ETF 轮动回测（历史功能）

双核动量 ETF 轮动策略现已不再作为主要交易策略使用，仅保留回测工具供参考。
当前主要策略为 `full_11` 11策略综合评分选股。

---

## 🤖 自动化交易（可选）

> 自动化交易是可选功能。可以只用策略选股，根据推荐结果**手动交易**。

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
│   └── data_sources.yaml    # 数据源优先级配置
│
├── src/                     # 核心源代码
│   ├── strategies/          # 9 单策略 + 5 组合
│   │   ├── base.py              # 策略基类（Strategy / StrategySignal）
│   │   ├── ma_cross.py          # MA 均线交叉
│   │   ├── macd_cross.py        # MACD
│   │   ├── rsi_signal.py        # RSI
│   │   ├── bollinger_band.py    # BOLL 布林带
│   │   ├── kdj_signal.py        # KDJ
│   │   ├── dual_momentum.py     # DUAL 双核动量单股
│   │   ├── fundamental_pe.py    # PE 历史分位数
│   │   ├── fundamental_pb.py    # PB 历史分位数
│   │   ├── fundamental_pe_pb.py # PEPB 双因子联合低估
│   │   └── ensemble.py          # EnsembleStrategy（9子策略加权投票）
│   ├── core/                # 核心工具模块
│   │   ├── momentum_math.py         # 动量计算共用函数
│   │   ├── backtest_constraints.py  # 回测未来函数约束
│   │   └── dual_momentum_strategy.py # ETF轮动核心逻辑
│   ├── etf_rotation/        # ETF 轮动系统（信号引擎/持仓/交易日志）
│   ├── data/                # 数据服务
│   │   ├── provider/        # 统一数据层（UnifiedDataProvider + 多源适配器）
│   │   └── fetchers/        # 数据获取（行情/基本面/ETF）
│   ├── api/broker/          # 券商自动化（同花顺桌面/网页）
│   └── config/              # 平台配置
│
├── tools/                   # 工具脚本（详见 tools/README.md）
│   ├── analysis/            # 选股推荐、单股分析、持仓分析
│   │   ├── recommend_today.py       # 每日推荐主脚本（支持 --append-sectors）
│   │   └── generate_sector_themes.py # 专题板块推荐生成器
│   ├── backtest/            # 批量回测、ETF轮动回测、交叉验证
│   ├── data/                # K线预取、PE缓存、股票池刷新
│   ├── optimization/        # 参数优化（含 L1/L2 验证工具）
│   │   ├── optimize_regime_weights.py   # L2层权重调整验证
│   │   ├── optimize_thresholds.py       # 信号阈值优化
│   │   └── calibrate_weights.py         # 策略权重校准
│   └── validation/          # 策略验证、数据源测试
│
├── tests/                   # 单元测试 + 集成测试
├── examples/                # 使用示例（模拟交易 / K线获取 / 桌面自动化）
├── scripts/                 # Shell/Bat 启动脚本
├── docs/                    # 文档（见下方文档索引）
│
├── mydate/                  # 数据文件
│   ├── stock_pool_all.json  # 综合股票池（808只）
│   ├── stock_pool_nuclear_computing.json  # 专题池：核电+算电协同（52只）
│   ├── stock_pool.json      # 赛道龙头池（48只）
│   ├── my_portfolio.json    # 当前持仓
│   ├── daily_reports/       # 每日推荐报告
│   │   ├── daily_recommendation.md  # 主报告（增量更新）
│   │   ├── daily_recommendation_YYYY-MM-DD.md  # 每日归档
│   │   └── trading_review.md  # 交易复盘记录
│   ├── backtest_kline/      # K线本地缓存（863只，parquet格式）
│   ├── pe_cache/            # PE/PB历史数据缓存（815只，parquet格式）
│   ├── optimized_regime_weights.json  # L2层权重优化结果
│   └── backtest_results_v3.json  # 最新回测结果
│
├── mycache/                 # 基本面缓存（ROE / 行业PE）
├── mylog/                   # 运行日志
└── myoutput/                # 输出（图表、报告）
```

---

## 策略开发

新策略继承 `src.strategies.base.Strategy`，接收 K 线 DataFrame，返回 `StrategySignal`：

```python
from src.strategies.base import Strategy, StrategySignal

class MyStrategy(Strategy):
    def analyze(self, df, **kwargs) -> StrategySignal:
        # df 列：date, open, high, low, close, volume, amount
        # 返回 StrategySignal(action='buy'/'sell'/'hold',
        #                     confidence=0.0~1.0,
        #                     position=0.0~1.0,
        #                     reason='信号说明',
        #                     indicators={})
        pass
```

在 `src/strategies/__init__.py` 的 `STRATEGY_REGISTRY` 中注册后即可用于所有工具：

```python
from src.strategies import STRATEGY_REGISTRY
STRATEGY_REGISTRY['MyStrategy'] = MyStrategy
```

详见 [策略开发快速开始](docs/strategy/STRATEGY_QUICKSTART.md)。

---

## 风控系统

四层风控，层层把关：

| 层级 | 控制内容 |
|------|----------|
| 账户级 | 单日最大亏损、总仓位上限、现金储备比例 |
| 策略级 | 单策略仓位上限、回撤控制、夏普比率监控 |
| 个股级 | 单股最大仓位、止损(-8%)止盈、涨跌停限制 |
| 系统级 | 交易频率限制、异常检测、紧急熔断 |

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [运行命令汇总](docs/RUN_COMMANDS.md) | 常用命令一页汇总，便于复制执行 |
| [策略清单](docs/strategy/STRATEGY_LIST.md) | 9 单策略 + 5 组合完整清单与工具对应关系 |
| [策略详解](docs/strategy/STRATEGY_DETAIL.md) | 各策略信号逻辑、参数、置信度映射 |
| [策略开发快速开始](docs/strategy/STRATEGY_QUICKSTART.md) | 5 分钟上手策略开发 |
| [双核动量指南](docs/strategy/DUAL_MOMENTUM_GUIDE.md) | ETF 轮动策略完整使用指南 |
| [回测与实盘规范](docs/strategy/BACKTEST_AND_LIVE_SPEC.md) | 未来函数约束、参数敏感性、成本与延迟 |
| [Alpha Factory设计文档](docs/alpha_factory_design.md) | L0-L3分层架构设计，L1/L2验证结论 |
| [L2层验证报告](L2_VALIDATION_REPORT.md) | 动态权重调整验证报告（结论：固定权重更优） |
| [PE缓存指南](docs/data/PE_CACHE_GUIDE.md) | PE/PB历史数据缓存机制与使用说明 |
| [K线数据指南](docs/setup/KLINE_DATA_GUIDE.md) | K线缓存预取、增量更新、格式说明 |
| [数据接口与容错](docs/data/API_INTERFACES_AND_FETCHERS.md) | 各策略数据接口、主备切换 |
| [V3.3 设计规格](docs/strategy/V33_DESIGN_SPEC.md) | 情绪/消息/政策/龙虎榜完整设计规格 |
| [跨平台兼容说明](docs/setup/CROSS_PLATFORM.md) | Windows/Linux 兼容说明 |
| [Windows完整指南](docs/setup/WINDOWS_GUIDE.md) | Windows 环境配置与使用 |

---

**股市有风险，投资需谨慎！**
