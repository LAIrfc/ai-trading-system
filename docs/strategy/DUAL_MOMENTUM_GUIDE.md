# 双核动量轮动策略 - 使用指南

## 📖 目录

1. [快速开始](#快速开始)
2. [策略原理](#策略原理)
3. [参数调优](#参数调优)
4. [回测分析](#回测分析)
5. [实盘使用](#实盘使用)
6. [常见问题](#常见问题)

---

## 🚀 快速开始

### 1. 一键运行回测

```bash
cd /home/wangxinghan/codetree/ai-trading-system
python3 tools/backtest/backtest_dual_momentum.py
```

**预期结果：**
- 自动下载 ETF 数据（沪深300、创业板50、纳指、黄金、国债）
- 运行2020-至今的完整回测
- 输出回测报告（收益率、回撤、夏普比率等）
- 生成净值曲线图
- 保存交易记录到 CSV

### 2. 策略规范

完整的策略逻辑、参数表、风控与执行规则见本文档下方 **[策略规范（完整）](#策略规范完整)**。

---

## 📊 策略原理

### 核心思想

**永远持有最强趋势的资产**

这个策略不预测未来，只应对当下。通过两个模块来实现：

#### 1. 绝对动量（过滤器）🛡️

```
条件: 当前价格 > 200日均线
作用: 只在牛市参与，熊市空仓
```

**例子：**
- 沪深300 当前3800点，200日均线3600点 → ✅ 通过
- 创业板50 当前2200点，200日均线2400点 → ❌ 不通过

#### 2. 相对动量（选择器）🏆

```
得分 = (当前价格 / 60日前价格) - 1
选择: 得分最高的资产
```

**例子：**
- 沪深300 过去60日涨幅 +5% → 得分 0.05
- 纳指ETF 过去60日涨幅 +12% → 得分 0.12 ✅ 选这个！

### 交易流程

```
每20个交易日（约1个月）:
1. 计算所有资产的绝对动量 → 筛选出"牛市"资产
2. 计算相对动量 → 排序找出最强的
3. 对比当前持仓 → 如果不是最强的，就换掉
4. 如果没有合格资产 → 空仓
```

---

## 策略规范（完整）

> 以下为策略完整规范（原 `dual_momentum_strategy.md` 内容合并于此）。

**版本**：v1.0 | **类型**：中频趋势跟踪/资产配置 | **标的**：A股主流ETF（510300/159949/513100/518880/511520 等）

### 策略逻辑摘要

- **绝对动量（过滤器）**：当前价格 > N日均线（如200日）→ 进入备选池；否则排除。
- **相对动量（选择器）**：动量得分 = 当前价/M日前价 - 1，取排名前 K 位。
- **调仓**：每 F 个交易日重算；无合格资产则空仓。

### 参数表

| 参数名 | 符号 | 建议值 | 说明 |
|--------|------|--------|------|
| 绝对动量周期 | N | 200 | 牛熊判断均线 |
| 相对动量周期 | M | 60 | 涨幅计算周期 |
| 调仓频率 | F | 20 | 交易日 |
| 持有数量 | K | 1 | 排名前 K 位 |

### 风控

- **硬性止损**：单资产亏损 -10% 立即清仓，当月不再买入。
- **黑天鹅**：单日大盘跌幅 -5% 触发熔断，清仓并观察。
- **流动性**：仅交易日均成交额 > 5000 万的 ETF。
- **仓位**：单标的不超过总资金 30%（K=1 时可满仓）。

### 执行与回测

- 调仓：每月末或每周五收盘前；收盘前 30 分钟计算，15 分钟执行。
- 回测：初始 100 万，手续费万二，滑点 0.2%，2020 至今；评估年化、最大回撤、夏普、换手率等。

---

## 🔧 参数调优

### 可调参数

| 参数 | 默认值 | 调整方向 | 影响 |
|------|--------|---------|------|
| `absolute_period` (N) | 200 | 150 / 250 | 越大越保守，对熊市反应越慢 |
| `relative_period` (M) | 60 | 20 / 120 | 越小越激进，交易频率越高 |
| `rebalance_days` (F) | 20 | 5 / 40 | 越小越频繁调仓，成本越高 |
| `top_k` (K) | 1 | 2 / 3 | 越大越分散，波动越小 |

### 如何调参

#### 方法1：修改配置文件

编辑 `tools/backtest/backtest_dual_momentum.py` 中的 `strategy_config`:

```python
strategy_config = {
    'absolute_period': 150,  # 改成150，对趋势反应更快
    'relative_period': 120,   # 改成120，看更长期的动量
    'rebalance_days': 10,     # 改成10，更频繁调仓
    'top_k': 2,               # 改成2，持有前2名分散风险
}
```

#### 方法2：批量测试

创建参数扫描脚本 `test_params.py`：

```python
from tools.backtest_dual_momentum import *

# 测试不同的N值
for N in [150, 200, 250]:
    for M in [20, 60, 120]:
        strategy_config['absolute_period'] = N
        strategy_config['relative_period'] = M
        
        strategy = DualMomentumStrategy(strategy_config)
        backtest = DualMomentumBacktest(1000000, 0.0002)
        report = backtest.run(strategy, data)
        
        print(f"N={N}, M={M} | 年化收益={report['annual_return']:.2%}, 最大回撤={report['max_drawdown']:.2%}")
```

---

## 📈 回测分析

### 查看回测报告

运行回测后，你会看到：

```
============================================================
回测报告
============================================================
初始资金:          1,000,000.00 元
最终资产:          1,650,000.00 元
总收益率:                 65.00%
年化收益率:               13.25%
最大回撤:                -18.50%
夏普比率:                  1.85
卡玛比率:                  0.72
日胜率:                   52.30%
交易次数:                    24 次
手续费总计:            3,200.00 元
============================================================
```

### 关键指标解读

#### 年化收益率
- **好**: > 15%
- **中等**: 8% - 15%
- **差**: < 8%

#### 最大回撤
- **好**: < 20%
- **中等**: 20% - 30%
- **差**: > 30%

#### 夏普比率
- **好**: > 2.0
- **中等**: 1.0 - 2.0
- **差**: < 1.0

### 查看交易记录

```bash
cat dual_momentum_trades.csv
```

或用 Excel/Numbers 打开查看每一笔交易的详情。

---

## 💼 实盘使用

### 方法1：手动交易（推荐新手）

1. **每月固定时间运行策略**（比如每月最后一个交易日收盘前）

```python
# 运行策略获取信号
from src.data.etf_data_fetcher import quick_fetch_etf_data
from src.core.strategy.dual_momentum_strategy import DualMomentumStrategy

data = quick_fetch_etf_data(years=3)
strategy = DualMomentumStrategy(strategy_config)
signals = strategy.generate_signals(data)

print(signals)
```

2. **根据信号手动下单**
   - 信号=1 (买入) → 在交易软件中手动买入
   - 信号=-1 (卖出) → 手动卖出
   - 信号=0 (持有) → 不操作

### 方法2：自动交易（需要同花顺桌面客户端）

使用内置的桌面自动化模块：

```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

broker = TonghuashunDesktop(config)
broker.connect()

# 根据信号自动下单
for _, signal_row in signals.iterrows():
    if signal_row['signal'] == 1:
        broker.buy(signal_row['code'], price, shares)
    elif signal_row['signal'] == -1:
        broker.sell(signal_row['code'], price, shares)
```

### 方法3：内置模拟账户测试

先在模拟账户中测试：

```python
from src.core.simulator.paper_trading import PaperTradingAccount

account = PaperTradingAccount(initial_capital=1000000)
# ... 执行交易 ...
account.print_summary()
```

---

## 🔥 实战技巧

### 1. 周期选择

- **月度调仓 (F=20)**: 适合长期投资者，交易成本低
- **双周调仓 (F=10)**: 适合中期投资者，平衡收益与成本
- **周度调仓 (F=5)**: 适合短期投资者，需要接受更高成本

### 2. 持仓数量

- **K=1**: 集中最强资产，收益潜力大，但波动也大
- **K=2**: 分散风险，净值更平滑
- **K=3**: 更稳健，但可能稀释收益

### 3. 风控建议

✅ **必须严格执行**:
- 单个持仓止损 -10%
- 市场单日跌超 -5% 立即清仓
- 只交易流动性好的 ETF

❌ **不要做**:
- 不要频繁手动干预策略
- 不要在策略信号之外随意加仓
- 不要因为短期回撤就放弃策略

---

## ❓ 常见问题

### Q1: 数据获取失败怎么办？

**A:** 检查网络，或者使用缓存：

```python
fetcher = ETFDataFetcher()
data = fetcher.get_etf_pool_data(codes, start_date, end_date, use_cache=True)
```

### Q2: 回测结果不理想怎么办？

**A:** 尝试：
1. 延长数据周期（测试更长时间）
2. 调整参数（参考上面的调参指南）
3. 增加 ETF 池（加入更多大类资产）

### Q3: 实盘会和回测一样吗？

**A:** 不会完全一样，因为：
- 回测没有滑点和冲击成本
- 实际交易可能停牌或流动性不足
- 人的情绪干预

**建议**: 实盘预期收益 = 回测收益 × 0.7

### Q4: 可以用于股票吗？

**A:** 可以，但需要修改：
1. 扩大观察池（从5个ETF扩展到50-100只股票）
2. 增加 K 值（持有前10-20名）
3. 加强风控（个股波动比ETF大）

### Q5: 什么时候应该停止使用策略？

**A:** 如果出现：
- 连续6个月跑输基准（如沪深300）
- 最大回撤超过 40%
- 市场结构性改变（如交易规则变化）

---

## 📚 扩展阅读

### 策略优化方向

1. **动态参数**: 根据市场波动率自动调整N和M
2. **多因子融合**: 加入估值、成交量等因子
3. **风险平价**: 根据波动率分配仓位
4. **机器学习**: 用AI预测动量持续性

### 相关论文

- *Dual Momentum Investing* by Gary Antonacci
- *A Quantitative Approach to Tactical Asset Allocation* by Faber (2007)

---

## 🛠️ 技术支持

如果遇到问题：

1. 查看日志: `logs/dual_momentum_backtest.log`
2. 阅读策略规范：本文档 [策略规范（完整）](#策略规范完整)
3. 查看源代码：`src/core/signal_engine.py`、`tools/backtest/backtest_dual_momentum.py`

---

## 完整工作流（数据→策略→执行→回测→优化→实盘）

> 以下由原 `DUAL_MOMENTUM_WORKFLOW.md` 合并于此，便于一站式查阅。

### 整体架构

| 层级 | 职责 |
|------|------|
| **数据层** | ETF 历史数据（baostock/东方财富）→ MultiIndex DataFrame |
| **策略层** | 绝对动量过滤、相对动量排序、风控检查、信号生成 |
| **执行层** | 回测 / 模拟 / 同花顺桌面实盘 |

### 六阶段概要

1. **数据准备**：`ETFDataFetcher` 获取 5 只 ETF（510300/159949/513100/518880/511520），输出统一格式。
2. **策略计算**：每 20 交易日执行绝对动量→流动性过滤→相对动量排序→生成买卖信号。
3. **交易执行**：回测引擎 / 模拟账户 / 同花顺桌面三种模式。
4. **回测与评估**：年化、最大回撤、夏普、卡玛、换手率；输出净值曲线与交易记录。
5. **参数优化**：单参数扫描（N/M/F/K），避免过拟合，重视样本外验证。
6. **实盘部署**：回测与模拟通过后，每月末按信号执行（手动或桌面自动化），并记录日志。

### 文件对应关系

| 阶段 | 文件 |
|------|------|
| 数据 | `src/data/fetchers/`、ETF 数据获取 |
| 策略与回测 | `src/core/signal_engine.py`、`tools/backtest/backtest_dual_momentum.py` |
| 实盘 | `src/api/broker/tonghuashun_desktop.py` |
| 模拟 | `src/core/simulator/paper_trading.py` |

### 日常命令速查

```bash
# 快速查看当前信号
python3 tests/test_dual_momentum_quick.py

# 完整回测
python3 tools/backtest/backtest_dual_momentum.py

# 桌面自动化执行（实盘）
./scripts/run_desktop_trading.sh
```

### 核心理念

- **纪律 > 预测**：按策略执行，不掺情绪。
- **风控 > 收益**：止损与熔断优先。
- **系统 > 直觉**：信任回测验证过的系统。
- **简单 > 复杂**：参数少、逻辑清晰更稳健。
- **记录 > 回忆**：每笔交易留日志，复盘靠数据。

---

**祝交易顺利！记住：纪律 > 预测 📈**
