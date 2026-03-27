# AI量化交易系统（A股）

基于多策略组合的A股量化交易系统，支持策略选股、回测验证、持仓分析和实盘自动化交易。

**跨平台支持**：Windows 和 Linux 自动兼容，无需手动修改，开箱即用。

---

## ✨ 核心亮点

🎯 **12大策略 × 5大维度**：技术+基本面+消息+政策+情绪+资金，全方位覆盖  
🚀 **双引擎架构**：均值回归+趋势跟随并行，兼顾超跌反弹和强势突破  
⭐ **v6.1机构级升级**（2026-03）：因子正交化、Rank Normalization、Soft Regime、风险平价  
📊 **大规模验证**：808只股票×3.3年×58万次计算，权重经数据优化  
💰 **基本面深度**：PE/PB历史分位数（3年滚动窗口），动态估值调整  
📰 **AI驱动分析**：新闻情感+政策事件（关键词40%+LLM语义60%）  
💼 **资金追踪**：龙虎榜机构席位+大宗交易折价分析  
🔬 **因子监控**：IC/IR实时监控，因子有效性持续跟踪  
⚡ **秒级响应**：863只K线+815只PE/PB本地缓存，回测秒级完成  

---

## ⚠️ 风险警告

**本系统涉及真实资金交易，使用前请务必：**
- 充分理解股票交易风险，在模拟环境充分测试
- 设置严格的风控参数，遵守相关法律法规
- 本项目仅供学习和研究使用，使用者需自行承担一切交易风险

---

## 📊 当前策略状态（2026-03-26）

**核心架构**：双引擎调度系统（v5.2）🚀

### 🎯 完整策略体系（12大策略 × 5大维度）

| 维度 | 策略 | 权重 | 说明 |
|------|------|------|------|
| **技术面** | MA/MACD/RSI/BOLL/KDJ/DUAL | 0.3-2.0 | 6大经典技术指标 |
| **基本面** | PE/PB/PEPB | 1.61-2.0 | 市盈率/市净率历史分位数估值（3年滚动窗口） |
| **消息面** | NEWS | 0.32 | 24h新闻情感分析（关键词40%+LLM60%） |
| **政策面** | POLICY | L0过滤 | 央行/财政/监管政策监控（极度利空时暂停选股） |
| **情绪面** | SENTIMENT | 0.32 | 全市场恐慌贪婪指数（多指标Z-score合成） |
| **资金面** | MONEY_FLOW | 0.3 | 龙虎榜机构动向+大宗交易折价分析 |

**v6.1技术细节**：见 [V6.1_SUMMARY.md](V6.1_SUMMARY.md)

---

### 🏗️ 双引擎调度架构

**架构流程**：
```
股票池（808只）
    ↓
[L0: 政策面大盘过滤]
    ↓
[12策略并行分析]
    ↓
[双引擎调度]
├── 均值回归引擎 → 超跌榜（TOP 15）
└── 趋势引擎 → 趋势榜（TOP 5）
    ↓
[双优股票识别] ⭐
    ↓
最终推荐（TOP 20）
```

#### 均值回归引擎（Mean Reversion）
**目标**：捕捉超跌反弹机会

**策略权重**（基于808只×3.3年回测优化）：
- 核心：PB(2.0), BOLL(1.95), RSI(1.82), PE(1.68), PEPB(1.61), KDJ(1.5), DUAL(1.39)
- 技术确认：MACD(0.5), MA(0.3)
- 辅助：NEWS(0.32), SENTIMENT(0.32), MONEY_FLOW(0.3)

**回测表现**（808只股票，2023-2026）：
- 交易次数：2,198笔
- 平均收益：+0.80%（5日持仓）
- 胜率：52.55%
- Sharpe：0.163

#### 趋势引擎（Trend Following）
**目标**：捕捉强势上涨趋势

**v6.1机构级升级**（2026-03-27）：
- ✅ 因子正交化：消除重复下注（相关性0.45→0.00）
- ✅ Rank Normalization：稳定得分分布（[-1, 1]）
- ✅ Soft Regime Score：平滑权重切换（连续市场状态）
- ✅ Volatility Scaling：风险平价（目标波动率15%）
- ✅ 混合策略：IC动态切换v5.2/v6.1（自适应市场环境）

**4层因子体系**（基于IC分析优化）：
```python
# v6.1权重（基于IC=0.43/0.32/0.17/0.04）
base_trend = 0.42       # 基础趋势（IC=0.43，最强）
tech_confirm = 0.20     # 技术确认（IC=0.17，降低）
relative_strength = 0.30 # 相对强度（IC=0.32，大幅提升）
volume_confirm = 0.08   # 量价配合（IC=0.04，降低）

# v5.2权重（固定权重）
base_trend = 0.40
tech_confirm = 0.30
relative_strength = 0.10
volume_confirm = 0.20
```

**混合策略**（自动切换）：
- IC高（base≥0.20, rs≥0.15）→ 使用v6.1
- IC低 → 使用v5.2
- 当前IC=0.43/0.32 → 使用v6.1 ✅

**因子IC验证**（200股×5日预测）：
- Base Trend：IC=0.43，Q5组+2.66% vs Q1组-2.02%
- Relative Strength：IC=0.32，Q5组+3.23%
- Tech Confirm：IC=0.17（中等）
- Volume Confirm：IC=0.04（较弱）

**回测表现**（v5.2基线，808只股票，2023-2026）：
- 交易次数：741笔
- 平均收益：+0.26%（5日持仓）
- 胜率：42.78%
- Sharpe：0.023
- 最大单笔收益：+148.78%

**权重优化验证**（2026-03-26完成）：
- 测试规模：808只股票 × 740个交易日 × 19种权重配置
- 总计算量：约58万次因子计算
- 结果：当前配置（0.4/0.3/0.1/0.2）为最优解

#### 双优股票识别（v5.0.2）⭐
**定义**：同时出现在超跌榜和趋势榜的股票
- 既有超跌反弹的估值支撑
- 又有趋势向上的动能确认
- 在报告中用"⭐ 双优"标记

---

### 🔬 数据源与质量保证

**多源降级机制**：
```
Akshare（首选）→ Sina → Eastmoney → Tencent → Tushare → Baostock
```

**本地缓存**：
- K线数据：`mydate/backtest_kline/`（863只，805条/股）
- PE/PB数据：`mydate/pe_cache/`（815只，528条/股）
- 时间跨度：2022-11-28 至 2026-03-26（约3.3年）

**异常处理**：
- 自动过滤异常值（PE>100、PB<0、ST股票）
- 数据缺失时跳过该策略
- 网络超时自动重试（最多3次）
- 基本面数据滞后时动态调整（根据股价变化）

---

## 💡 系统特色

| 特性 | 说明 |
|------|------|
| **多维度覆盖** | 技术+基本面+消息+政策+情绪+资金，6大维度12大策略 ✅ |
| **双引擎架构** | 均值回归+趋势跟随并行，兼顾超跌反弹和强势突破 🚀 |
| **大规模验证** | 808只×3.3年回测，权重经58万次计算优化 📊 |
| **基本面深度** | PE/PB历史分位数（3年滚动窗口），动态调整估值 💰 |
| **消息政策** | 新闻情感+政策事件（关键词40%+LLM60%），预期差校验 📰 |
| **资金追踪** | 龙虎榜机构席位+大宗交易折价分析 💼 |
| **双优识别** | 自动识别同时满足超跌和趋势的双优股票 ⭐ |
| **本地缓存** | 863只K线+815只PE/PB缓存，回测秒级响应 ⚡ |
| **专题板块** | 自动追加专题分析（核电+算电协同等） 🔋 |
| **增量报告** | 每日推荐自动追加，持仓置顶，历史可追溯 📝 |

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

#### 🆕 推荐：每日选股（双引擎调度）

```bash
# 标准模式：12策略 × 808只股票 → TOP 20推荐（自动根据IC选择v5.2/v6.1）
python3 tools/analysis/recommend_today.py --strategy full_12 --top 20

# 强制使用v5.2（IC低时）
python3 tools/analysis/recommend_today.py --strategy full_12 --force-version v5.2

# 强制使用v6.1（IC高时）
python3 tools/analysis/recommend_today.py --strategy full_12 --force-version v6.1

# 含专题板块：自动追加核电+算电协同等专题分析
python3 tools/analysis/recommend_today.py --strategy full_12 --top 20 --append-sectors

# 仅更新持仓分析（不重新扫描股票池）
python3 tools/analysis/recommend_today.py --only-holdings
```

**输出报告**：
- 主报告：`mydate/daily_reports/daily_recommendation.md`（增量更新）
- 每日归档：`mydate/daily_reports/daily_recommendation_YYYY-MM-DD.md`

**报告内容**：
1. 我的持仓概览
2. 今日持仓操作建议
3. 每日推荐TOP 20（超跌榜15只 + 趋势榜5只）
4. 双优股票识别 ⭐
5. 专题板块推荐（可选）
6. 历史推荐记录

---

#### 数据更新（每周执行）

```bash
# 更新K线缓存（增量更新，约5-10分钟）
python3 tools/data/backtest_prefetch.py \
  --pool mydate/stock_pool_all.json --update \
  --out-dir mydate/backtest_kline --workers 8

# 更新PE/PB基本面数据（约10-15分钟）
python3 tools/data/prefetch_pe_cache.py --update

# 刷新股票池（季度执行，同步指数成分调整）
python3 tools/data/refresh_stock_pool.py
```

---

#### 单股深度分析

```bash
# 分析单只股票（12策略完整分析）
python3 tools/analysis/analyze_single_stock.py 688122 --name "西部超导"

# 输出：
# - 12策略信号详情
# - 技术指标图表
# - 基本面估值分析
# - 消息情绪汇总
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

## 🎯 完整策略体系（12大策略 × 5大维度）

### 五大维度全覆盖

| 维度 | 策略数 | 具体策略 | 数据源 |
|------|-------|---------|--------|
| **技术面** | 6个 | MA, MACD, RSI, BOLL, KDJ, DUAL | K线数据（本地缓存） |
| **基本面** | 3个 | PE, PB, PEPB | PE/PB历史数据（3年滚动窗口） |
| **消息面** | 1个 | NEWS | 东方财富/新浪财经/同花顺（关键词40%+LLM60%） |
| **政策面** | 1个 | POLICY | 央行/财政/监管政策（关键词40%+LLM60%） |
| **情绪面** | 1个 | SENTIMENT | 恐慌贪婪指数/涨跌停/成交量/融资融券 |
| **资金面** | 1个 | MONEY_FLOW | 龙虎榜（机构席位）+大宗交易（折价率） |

**完整策略说明**：见 [STRATEGY_OVERVIEW.md](STRATEGY_OVERVIEW.md)

---

### 🏗️ 双引擎调度架构（v5.2）

**架构设计**：
- ✅ **L0: PolicyEvent 大盘过滤器** - 极端利空时暂停选股
- ✅ **双引擎并行调度** - 均值回归 + 趋势跟随，智能融合
- ❌ **L1/L2: 动态权重调整** - 经验证后永久禁用（固定权重更优）

#### 1️⃣ 均值回归引擎（超跌反弹）

**策略权重**（基于808只×3.3年回测优化）：
```python
MR_WEIGHTS = {
    # 核心均值回归策略
    'PB': 2.0, 'BOLL': 1.95, 'RSI': 1.82, 'PE': 1.68, 
    'PEPB': 1.61, 'KDJ': 1.5, 'DUAL': 1.39,
    # 技术确认（低权重）
    'MACD': 0.5, 'MA': 0.3,
    # 辅助因子
    'NEWS': 0.32, 'SENTIMENT': 0.32, 'MONEY_FLOW': 0.3
}
```

**回测表现**（2023-01-01 至 2026-03-26）：
- 交易：2,198笔 | 平均收益：+0.80% | 胜率：52.55% | Sharpe：0.163
- 最大单笔收益：+42.89% | 最大单笔亏损：-18.07%

#### 2️⃣ 趋势引擎（趋势跟随）

**4层因子体系**（经808只×3.3年×19种配置优化，Sharpe 0.440）：
```python
# 最优权重配置（2026-03-26验证）
TREND_WEIGHTS = {
    'base_trend': 0.4,        # 基础趋势（ADX+均线排列+波动率动量）
    'tech_confirm': 0.3,      # 技术确认（MACD/KDJ/布林带金叉死叉）
    'relative_strength': 0.1, # 相对强度（个股vs沪深300指数）
    'volume_confirm': 0.2     # 量价配合（价升量增/价跌量缩）
}
```

**权重优化过程**：
- 测试规模：808只股票 × 740个交易日 × 19种权重组合
- 总计算量：约58万次因子计算
- 运行时间：28分钟（8进程并行）
- 验证结果：当前配置为Sharpe最优（0.440），覆盖365只股票（45%）

**回测表现**（2023-01-01 至 2026-03-26）：
- 交易：741笔 | 平均收益：+0.26% | 胜率：42.78% | Sharpe：0.023
- 最大单笔收益：+148.78% | 最大单笔亏损：-27.77%

#### 3️⃣ 市场状态感知

| 市场状态 | 判断条件 | 超跌榜 | 趋势榜 |
|---------|---------|--------|--------|
| 趋势市 | MA20/MA60斜率 > 3% | 10只 | 10只 |
| 震荡市 | MA20/MA60斜率 ≤ 3% | 15只 | 5只 |

#### 4️⃣ 双优股票识别（v5.0.2）⭐

**定义**：同时出现在超跌榜和趋势榜的股票
- 既有超跌反弹的估值支撑
- 又有趋势向上的动能确认
- 风险收益比更优
- 在报告中用"⭐ 双优"标记

---

## 📊 股票池与数据

### 股票池配置

| 文件 | 说明 | 数量 | 过滤规则 |
|------|------|------|---------|
| `mydate/stock_pool_all.json` | 综合池（沪深300+中证500） | **808只** | PE∈(0,100]、市值>30亿、非ST |
| `mydate/stock_pool_nuclear_computing.json` | 专题池（核电+算电协同） | 52只 | 核电设备/电力/算力/智能电网 |
| `mydate/stock_pool.json` | 赛道龙头池 | 48只 | 光伏/机器人/半导体/有色/证券/创新药/商业航天 |
| `mydate/etf_pool.json` | ETF池 | 57只 | 宽基/科技/消费/金融/周期/医药/地产/跨境 |

### 本地数据缓存

| 数据类型 | 目录 | 数量 | 时间跨度 | 更新频率 |
|---------|------|------|---------|---------|
| K线数据 | `mydate/backtest_kline/` | 863只 | 2022-11至2026-03（805条/股） | 每周 |
| PE/PB数据 | `mydate/pe_cache/` | 815只 | 2022-11至2026-03（528条/股） | 每周 |
| 新闻数据 | 实时获取 | - | 24小时内 | 实时 |
| 政策数据 | 实时获取 | - | 近期重大政策 | 实时 |
| 龙虎榜 | 实时获取 | - | 近3日 | 实时 |

### 数据源与容错

**多源降级机制**：
```
Akshare（首选）→ Sina → Eastmoney → Tencent → Tushare → Baostock
```

**异常处理**：
- 自动过滤异常值（PE>100、PB<0、ST股票）
- 数据缺失时跳过该策略
- 网络超时自动重试（最多3次）
- 基本面数据滞后时动态调整（根据股价变化）

```bash
# 刷新综合股票池（重新拉取成分股 + 基本面过滤）
python3 tools/data/refresh_stock_pool.py

# 季度更新（同步指数成分调整）
python3 tools/data/quarterly_update.py
```

---

## 📈 大规模回测验证

### 双引擎回测结果（808只股票，2023-2026，3.3年）

**测试规模**：
- 股票池：808只（沪深300+中证500成分股）
- 时间跨度：2023-01-01 至 2026-03-26（约3.3年，740个交易日）
- 持仓周期：5日
- 选股数量：超跌榜TOP 15 + 趋势榜TOP 5

**回测结果对比**：

| 引擎 | 交易次数 | 平均收益 | 胜率 | Sharpe | 最大单笔收益 | 最大单笔亏损 |
|------|---------|---------|------|--------|------------|------------|
| **均值回归** | 2,198笔 | **+0.80%** | **52.55%** | **0.163** | +42.89% | -18.07% |
| **趋势跟随** | 741笔 | +0.26% | 42.78% | 0.023 | **+148.78%** | -27.77% |

**结论**：
- 均值回归策略更稳健（高胜率、高Sharpe、低回撤）
- 趋势策略波动更大但有超高爆发潜力（最大单笔+148.78%）
- 双引擎互补，降低单一策略风险

---

### 趋势引擎权重优化（2026-03-26完成）

**优化目标**：找出4层因子的最优权重配置

**测试规模**：
- 股票数量：808只
- 历史数据：3.3年（2022-11-28 至 2026-03-26）
- 回测区间：740个交易日，每20日采样
- 权重组合：19种
- 总计算量：约58万次因子计算
- 运行时间：28分钟（8进程并行）

**TOP 5 权重配置**：

| 排名 | 基础趋势 | 技术确认 | 相对强度 | 量价配合 | 平均收益 | 胜率 | Sharpe | 有效股票 |
|------|---------|---------|---------|---------|---------|------|--------|----------|
| **🥇 1** | **0.4** | **0.3** | **0.1** | **0.2** | **+2.15%** | **53.42%** | **0.440** | **365只** |
| 🥈 2 | 0.5 | 0.3 | 0.1 | 0.1 | +2.44% | 52.10% | 0.331 | 135只 |
| 🥉 3 | 0.4 | 0.2 | 0.2 | 0.2 | +2.53% | 53.78% | 0.314 | 141只 |
| 4 | 0.3 | 0.4 | 0.1 | 0.2 | +2.22% | 56.03% | 0.310 | 383只 |

**验证结论**：当前配置（0.4/0.3/0.1/0.2）为最优解！
- Sharpe最高（0.440）
- 覆盖面最广（365只，45%）
- 收益与胜率均衡

详细结果：`results/trend_weights_optimization.json`

---

### 运行批量回测

```bash
# 第一步：预取 K 线数据到本地（首次，约 1-2 小时）
python3 tools/data/backtest_prefetch.py \
  --pool mydate/stock_pool_all.json --all \
  --out-dir mydate/backtest_kline --workers 8

# 第二步：预取 PE/PB 数据（基本面策略需要）
python3 tools/data/prefetch_pe_cache.py --update

# 第三步：运行双引擎回测（808只股票，约30分钟）
python3 tools/optimization/backtest_dual_lists.py --stocks 808

# 第四步：趋势引擎权重优化（19种配置，约30分钟）
python3 tools/optimization/optimize_trend_weights.py

# 定期更新 K 线缓存（每周执行）
python3 tools/data/backtest_prefetch.py \
  --update --out-dir mydate/backtest_kline --workers 8
```

回测结果保存至：
- 双引擎回测：`results/backtest_dual_YYYYMMDD_HHMMSS/`
- 权重优化：`results/trend_weights_optimization.json`

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

## 📚 文档索引

### 核心文档

| 文档 | 说明 |
|------|------|
| **[STRATEGY_OVERVIEW.md](STRATEGY_OVERVIEW.md)** | **完整策略体系说明（12大策略×5大维度）** ⭐ |
| [DUAL_ENGINE_GUIDE.md](DUAL_ENGINE_GUIDE.md) | 双引擎调度架构使用指南 |
| [BACKTEST_RESULTS_PHASE2.md](BACKTEST_RESULTS_PHASE2.md) | 趋势引擎Phase 2回测结果 |
| [L2_VALIDATION_REPORT.md](L2_VALIDATION_REPORT.md) | 动态权重调整验证报告（结论：固定权重更优） |

### 策略文档

| 文档 | 说明 |
|------|------|
| [策略清单](docs/strategy/STRATEGY_LIST.md) | 12策略完整清单与工具对应关系 |
| [策略详解](docs/strategy/STRATEGY_DETAIL.md) | 各策略信号逻辑、参数、置信度映射 |
| [策略开发快速开始](docs/strategy/STRATEGY_QUICKSTART.md) | 5分钟上手策略开发 |
| [回测与实盘规范](docs/strategy/BACKTEST_AND_LIVE_SPEC.md) | 未来函数约束、参数敏感性、成本与延迟 |
| [V3.3 设计规格](docs/strategy/V33_DESIGN_SPEC.md) | 情绪/消息/政策/龙虎榜完整设计规格 |

### 数据文档

| 文档 | 说明 |
|------|------|
| [PE缓存指南](docs/data/PE_CACHE_GUIDE.md) | PE/PB历史数据缓存机制（815只×528条） |
| [K线数据指南](docs/setup/KLINE_DATA_GUIDE.md) | K线缓存预取、增量更新（863只×805条） |
| [数据接口与容错](docs/data/API_INTERFACES_AND_FETCHERS.md) | 多源降级、异常处理 |

### 系统文档

| 文档 | 说明 |
|------|------|
| [运行命令汇总](docs/RUN_COMMANDS.md) | 常用命令一页汇总 |
| [Alpha Factory设计文档](docs/alpha_factory_design.md) | L0-L3分层架构设计 |
| [跨平台兼容说明](docs/setup/CROSS_PLATFORM.md) | Windows/Linux兼容 |
| [Windows完整指南](docs/setup/WINDOWS_GUIDE.md) | Windows环境配置 |

---

**股市有风险，投资需谨慎！**
