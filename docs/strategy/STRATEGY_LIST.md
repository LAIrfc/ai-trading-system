# 策略清单（完整）

> 项目内所有策略与组合的索引，便于查阅和工具对接。  
> 更新：2026-03

---

## 一、单策略（共 11 个，入组合）

| 注册名 | 类名 | 文件 | 说明 |
|--------|------|------|------|
| MA | MACrossStrategy | `ma_cross.py` | 均线交叉 |
| MACD | MACDStrategy | `macd_cross.py` | MACD 交叉 |
| RSI | RSIStrategy | `rsi_signal.py` | RSI 相对强弱 |
| BOLL | BollingerBandStrategy | `bollinger_band.py` | 布林带 |
| KDJ | KDJStrategy | `kdj_signal.py` | KDJ 随机指标 |
| DUAL | DualMomentumSingleStrategy | `dual_momentum.py` | 双核动量（单股） |
| PE | PEStrategy | `fundamental_pe.py` | 基本面 PE 分位数 |
| Sentiment | SentimentStrategy | `sentiment.py` | 市场情绪（V3.3：S/S_low/S_high + 趋势过滤） |
| NewsSentiment | NewsSentimentStrategy | `news_sentiment.py` | 新闻情感（V3.3：24h N、S_news、预期差） |
| PolicyEvent | PolicyEventStrategy | `policy_event.py` | 政策事件（V3.3：S_high、重大利空） |
| MoneyFlow | MoneyFlowStrategy | `money_flow.py` | 龙虎榜/大宗（V3.3） |

以上均在 `STRATEGY_REGISTRY` 中，且全部进入 **V33组合**（11 子策略）。

---

## 二、仅分析工具使用的单策略（未入注册表）

| 名称 | 类名 | 文件 | 说明 |
|------|------|------|------|
| PB | PBStrategy | `fundamental_pb.py` | 基本面 PB 分位数，在单股/持仓分析中与 PE 并列展示 |

另有 `fundamental_pe_pb.py`（PE+PB 双因子），当前未在分析工具中默认使用。

---

## 三、组合策略（4 个）

| 注册名 | 类名 | 子策略 | 说明 |
|--------|------|--------|------|
| 保守组合 | ConservativeEnsemble | MA, MACD, RSI, BOLL, KDJ, DUAL, PE（7 个） | 投票阈值更严 |
| 均衡组合 | BalancedEnsemble | 同上 7 个 | 默认阈值 |
| 激进组合 | AggressiveEnsemble | 同上 7 个 | 投票阈值更松 |
| V33组合 | V33EnsembleStrategy | 上述 11 个单策略 | 重大利空优先、卖出×1.2、新策略仓位 40%、动态权重与 7 日冷却 |

- **EnsembleStrategy**（无中文注册名）：7 策略组合，被 `recommend_today.py` 的 `--strategy ensemble` 使用。
- **V33EnsembleStrategy**：需传 `symbol`，用于单股或持仓分析中的「V33 综合结论」。

---

## 四、辅助模块（不直接输出买卖信号）

| 模块 | 文件 | 说明 |
|------|------|------|
| 换手率辅助 | `turnover_helper.py` | 换手率过滤/约束，供策略或回测使用 |
| 策略基类 | `base.py` | `Strategy`、`StrategySignal` 定义 |

---

## 五、代码位置与注册表

- **策略实现目录**：`src/strategies/`
- **注册表**：`src/strategies/__init__.py` 中的 `STRATEGY_REGISTRY`
- **V3.3 权重与名单**：`src/core/v33_weights.py` 中 `V33_STRATEGY_NAMES`（与 V33 组合 11 子策略一致）

获取所有策略实例：`get_all_strategies()`；列出名称与参数：`list_strategies()`。

---

## 六、工具与策略对应关系

| 工具 | 路径 | 使用的策略 |
|------|------|------------|
| 单股多策略分析 | `tools/analysis/analyze_single_stock.py` | 11 大单策略：MA, MACD, RSI, BOLL, KDJ, DUAL, Sentiment, NewsSentiment, PolicyEvent, MoneyFlow, PE, PB（共 12 项展示，PE/PB 各 1） |
| 持仓多策略分析 | `tools/analysis/portfolio_strategy_analysis.py` | 同上 11 大策略 |
| 每日选股推荐 | `tools/analysis/recommend_today.py` | 单 MACD 或 7 策略组合（EnsembleStrategy：MA+MACD+RSI+BOLL+KDJ+DUAL+PE），不含情绪/消息/政策/龙虎榜；可选 PB 过滤 |
| 交易报告生成 | `tools/analysis/generate_trade_report.py` | 双核动量轮动（ETF 轮动），非单股策略库 |
| 批量回测 | `tools/backtest/batch_backtest.py` | 可配置策略；支持 `--check-future` 未来函数校验 |

若要在「每日推荐」中使用 V33 组合（11 策略 + 情绪/消息/政策/龙虎榜），需在 `recommend_today.py` 中增加对 `V33EnsembleStrategy(symbol=code)` 的调用或选项。

---

## 七、文档索引

- **策略所需指标与接口**：见 [数据接口与容错获取规范](../data/API_INTERFACES_AND_FETCHERS.md) 第「〇、策略视角」
- 设计规格： [V33_DESIGN_SPEC](V33_DESIGN_SPEC.md)
- 落地与状态： [V33_落地与状态](V33_落地与状态.md)
- 情绪技术说明： [SENTIMENT_TECH](SENTIMENT_TECH.md)
- 回测与实盘规范： [BACKTEST_AND_LIVE_SPEC](BACKTEST_AND_LIVE_SPEC.md)
- 策略优化路线图： [STRATEGY_OPTIMIZATION_ROADMAP](STRATEGY_OPTIMIZATION_ROADMAP.md)
