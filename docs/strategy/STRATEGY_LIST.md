# 策略清单（完整）

> 项目内所有策略与组合的索引，便于查阅和工具对接。  
> 更新：2026-03-24

---

## 一、单策略（共 14 个，其中 12 个入 EnsembleStrategy）

### 技术面策略（6 个）

| 注册名 | 类名 | 文件 | 权重 | 独立Sharpe |
|--------|------|------|------|-----------|
| BOLL | BollingerBandStrategy | `bollinger_band.py` | 1.95 | 0.18 |
| RSI | RSIStrategy | `rsi_signal.py` | 1.82 | 0.14 |
| KDJ | KDJStrategy | `kdj_signal.py` | 1.50 | 0.14 |
| DUAL | DualMomentumSingleStrategy | `dual_momentum.py` | 1.39 | 0.24（反向） |
| MACD | MACDStrategy | `macd_cross.py` | 1.13 | 0.08 |
| MA | MACrossStrategy | `ma_cross.py` | 0.88 | 0.07 |

> DUAL 策略 IC 为 -0.39，反向使用后 IC 变为 +0.39，Sharpe 0.24（所有策略中第三高）。

### 基本面策略（3 个）

| 注册名 | 类名 | 文件 | 权重 | 独立Sharpe |
|--------|------|------|------|-----------|
| PB | PBStrategy | `fundamental_pb.py` | 2.00 | 0.38 |
| PE | PEStrategy | `fundamental_pe.py` | 1.68 | 0.25 |
| PEPB | PE_PB_CombinedStrategy | `fundamental_pe_pb.py` | 1.61 | 0.22 |

> 2026-03-24 已用 baostock 批量补全 839 只股票的日频 PE(TTM)/PB(MRQ) 数据到 parquet 文件中。
> 基本面策略在 836 只股票独立回测中表现最优（PB Sharpe 0.38 为全策略第一）。

### 消息面 + 情绪面 + 资金面策略（3 个）

| 注册名 | 类名 | 文件 | 权重 | 说明 |
|--------|------|------|------|------|
| NEWS | NewsSentimentStrategy | `news_sentiment.py` | 0.32 | 新闻情感（关键词+LLM 融合） |
| SENTIMENT | SentimentStrategy | `sentiment.py` | 0.32 | 市场情绪Z-score + 个股趋势过滤 |
| MONEY_FLOW | MoneyFlowStrategy | `money_flow.py` | 0.30 | 龙虎榜+大宗（回测中无历史数据，权重最低） |

### 市场级策略（1 个，不入 Ensemble L3投票层）

| 注册名 | 类名 | 文件 | 说明 | 状态 |
|--------|------|------|------|------|
| PolicyEvent | PolicyEventStrategy | `policy_event.py` | 政策事件过滤，L0层 | ✅ 启用 |

> **PolicyEvent** 在 `recommend_today.py` 中作为 L0 大盘过滤层，政策极度利空时暂停选股。

### 其他（1 个，接口不兼容）

| 注册名 | 类名 | 文件 | 说明 |
|--------|------|------|------|
| DualMomentum | DualMomentumStrategy | `core/dual_momentum_strategy.py` | ETF 轮动专用，MultiIndex 接口 |

---

## 二、组合策略

### EnsembleStrategy（主力组合，12 子策略）

```
技术面 6 个：MA / MACD / RSI / BOLL / KDJ / DUAL（反向）
基本面 3 个：PE / PB / PEPB
消息面 1 个：NEWS（关键词+LLM 融合）
情绪面 1 个：SENTIMENT（市场情绪+个股过滤）
资金面 1 个：MONEY_FLOW（龙虎榜+大宗）
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `mode` | `weighted` | 加权净得分投票 |
| `net_buy_threshold` | `0.07` | 净得分买入阈值（正在优化中） |
| `net_sell_threshold` | `-0.07` | 净得分卖出阈值 |
| `MIN_ACTIVE_VOTES` | `1` | 至少1个策略同向才触发 |
| `dual_reverse` | `True` | DUAL 信号反向使用 |
| `holding_cost` | `None` | 传入持仓成本后启用止损感知 |
| `stop_loss_pct` | `-8%` | 硬止损线 |
| `warn_loss_pct` | `-5%` | 预警线 |

**权重配置**（2026-03-24 基于 836 只股票全量回测校准，composite 方法）：

| 策略 | 权重 | 独立Sharpe | 正收益率 |
|------|------|-----------|---------|
| PB | 2.00 | 0.38 | 76.0% |
| BOLL | 1.95 | 0.18 | 72.5% |
| RSI | 1.82 | 0.14 | 66.6% |
| PE | 1.68 | 0.25 | 62.1% |
| PEPB | 1.61 | 0.22 | 59.0% |
| KDJ | 1.50 | 0.14 | 64.6% |
| DUAL | 1.39 | 0.24 | 67.6% |
| MACD | 1.13 | 0.08 | 57.9% |
| MA | 0.88 | 0.07 | 55.1% |
| SENTIMENT | 0.32 | — | — |
| NEWS | 0.32 | — | — |
| MONEY_FLOW | 0.30 | 0.00 | 0% |

> 权重 = composite(0.4×Sharpe + 0.3×正收益率 + 0.3×胜率)，归一化到 [0.3, 2.0]。
> Ensemble 整体验证：300只股票回测 avg Sharpe 0.073（旧权重 0.002），提升 32 倍。

**决策优先级**（从高到低）：
1. 硬止损（亏损 ≤ -8%）→ 无条件 SELL  
2. 重大利空（任一 SELL 含「重大利空」）→ 直接 SELL  
3. 净得分投票决策（weighted 模式）  
4. 持仓预警（-5%~-8% 且无 BUY）→ 建议减仓 SELL  

### 预设组合（均继承 EnsembleStrategy，12 子策略）

| 注册名 | 类名 | 模式 | 说明 |
|--------|------|------|------|
| 保守组合 | ConservativeEnsemble | majority | buy≥50%、sell≥34%，保护优先 |
| 均衡组合 | BalancedEnsemble | majority | 买入/卖出均需 ≥50% |
| 激进组合 | AggressiveEnsemble | weighted | 阈值 0.35，反应更灵敏 |
| V33组合 | V33EnsembleStrategy | — | **EnsembleStrategy 别名**（兼容旧代码） |

---

## 四、辅助模块（不直接输出买卖信号）

| 模块 | 文件 | 说明 |
|------|------|------|
| 换手率辅助 | `turnover_helper.py` | 换手率过滤/约束，供策略或回测使用 |
| 策略基类 | `base.py` | `Strategy`、`StrategySignal` 定义 |
| 动态权重 | `v33_weights.py` | ADX/HV20 市场状态、乘数表、7 日冷却 |

---

## 五、代码位置与注册表

- **策略实现目录**：`src/strategies/`
- **注册表**：`src/strategies/__init__.py` 中的 `STRATEGY_REGISTRY`
- **动态权重与名单**：`src/strategies/v33_weights.py` 中 `V33_STRATEGY_NAMES`（与 EnsembleStrategy 11 子策略一致）

获取所有策略实例：`get_all_strategies()`；列出名称与参数：`list_strategies()`。

---

## 六、工具与策略对应关系

| 工具 | 路径 | 使用的策略 |
|------|------|------------|
| 每日选股推荐 | `tools/analysis/recommend_today.py` | 政策面大盘过滤（PolicyEvent）+ 单 MACD 或 11 策略 EnsembleStrategy |
| 单股多策略分析 | `tools/analysis/analyze_single_stock.py` | 11 单策略 + PE/PB + 5 组合（含 Ensemble/V33） |
| 持仓多策略分析 | `tools/analysis/portfolio_strategy_analysis.py` | 11 大策略（技术6+消息面+资金面+基本面） |
| 交易报告生成 | `tools/analysis/generate_trade_report.py` | 双核动量轮动（ETF 轮动），非单股策略库 |
| 批量回测 | `tools/backtest/batch_backtest.py` | 可配置策略；支持 `--check-future` 未来函数校验 |

---

## 七、文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 策略详解 | [STRATEGY_DETAIL.md](STRATEGY_DETAIL.md) | 所有策略原理、参数、信号逻辑 |
| 回测与实盘规范 | [BACKTEST_AND_LIVE_SPEC.md](BACKTEST_AND_LIVE_SPEC.md) | 回测引擎规范 |
| V3.3 设计规格 | [V33_DESIGN_SPEC.md](V33_DESIGN_SPEC.md) | V3.3 情绪/政策/资金流策略设计 |
| 情绪技术说明 | [SENTIMENT_TECH.md](SENTIMENT_TECH.md) | 情绪指数计算方法 |
| PE/PB 缓存指南 | [../data/PE_CACHE_GUIDE.md](../data/PE_CACHE_GUIDE.md) | 基本面数据缓存机制与使用 |
| 数据接口规范 | [../data/API_INTERFACES_AND_FETCHERS.md](../data/API_INTERFACES_AND_FETCHERS.md) | 数据获取接口与容错规范 |
| 基本面数据说明 | [../data/FUNDAMENTAL_DATA.md](../data/FUNDAMENTAL_DATA.md) | 行业PE/PB/ROE数据说明 |
| 换手率验证结果 | [../data/TURNOVER_VALIDATION_RESULTS.md](../data/TURNOVER_VALIDATION_RESULTS.md) | 换手率辅助效果验证 |
