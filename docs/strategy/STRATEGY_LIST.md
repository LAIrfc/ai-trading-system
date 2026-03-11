# 策略清单（完整）

> 项目内所有策略与组合的索引，便于查阅和工具对接。  
> 更新：2026-03-11

---

## 一、单策略（共 9 个，入 EnsembleStrategy）

### 技术面策略（6 个）

| 注册名 | 类名 | 文件 | 说明 |
|--------|------|------|------|
| MA | MACrossStrategy | `ma_cross.py` | 均线交叉（MA5/MA20 金叉死叉） |
| MACD | MACDStrategy | `macd_cross.py` | MACD 金叉死叉 |
| RSI | RSIStrategy | `rsi_signal.py` | RSI 超买超卖 + 拐头确认 |
| BOLL | BollingerBandStrategy | `bollinger_band.py` | 布林带上下轨突破 |
| KDJ | KDJStrategy | `kdj_signal.py` | KDJ 低位金叉 |
| DUAL | DualMomentumSingleStrategy | `dual_momentum.py` | 双核动量（价格站上MA60 + 20日动量） |

### 基本面策略（3 个）

| 注册名 | 类名 | 文件 | 说明 |
|--------|------|------|------|
| PE | PEStrategy | `fundamental_pe.py` | PE 历史分位数（需本地 PE 缓存） |
| PB | PBStrategy | `fundamental_pb.py` | PB 历史分位数（需本地 PE 缓存） |
| PEPB | PE_PB_CombinedStrategy | `fundamental_pe_pb.py` | PE+PB 双因子联合低估 |

> 基本面策略依赖本地 PE/PB 缓存（`mydate/pe_cache/`），ETF 无 PE/PB 数据时自动跳过，不影响技术策略投票。
> 缓存管理见 [PE_CACHE_GUIDE](../data/PE_CACHE_GUIDE.md)。

### V3.3 扩展策略（4 个，仅入 V33 组合）

| 注册名 | 类名 | 文件 | 说明 |
|--------|------|------|------|
| Sentiment | SentimentStrategy | `sentiment.py` | 市场情绪（S/S_low/S_high + 趋势过滤） |
| NewsSentiment | NewsSentimentStrategy | `news_sentiment.py` | 新闻情感（24h N、S_news、预期差） |
| PolicyEvent | PolicyEventStrategy | `policy_event.py` | 政策事件（S_high、重大利空） |
| MoneyFlow | MoneyFlowStrategy | `money_flow.py` | 龙虎榜/大宗资金流 |

---

## 二、组合策略

### EnsembleStrategy（主力组合，9 子策略）

```
技术面 6 个：MA / MACD / RSI / BOLL / KDJ / DUAL
基本面 3 个：PE / PB / PEPB
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `mode` | `weighted` | 加权投票（各策略有不同权重） |
| `buy_threshold` | `0.45` | 加权买入票数占比阈值 |
| `sell_threshold` | `0.45` | 加权卖出票数占比阈值 |
| `MIN_ACTIVE_VOTES` | `2` | 至少2个策略同向才触发信号 |
| `holding_cost` | `None` | 传入持仓成本后启用止损感知 |
| `stop_loss_pct` | `-8%` | 硬止损线，触发后直接输出 SELL |
| `warn_loss_pct` | `-5%` | 预警线，无买入支撑时建议减仓 |

**权重配置：**

| 策略 | 权重 | 说明 |
|------|------|------|
| MACD | 1.2 | 短线最优，权重最高 |
| DUAL | 1.0 | 趋势确认 |
| MA/RSI/BOLL/KDJ | 0.8 | 标准技术指标 |
| PEPB | 0.8 | 双因子基本面，权重较高 |
| PE/PB | 0.6 | 单因子基本面 |

**持仓成本感知（新增）：**
- 传入 `holding_cost` 后，每次 `analyze()` 会计算当前盈亏
- 亏损超过 `-8%` → 直接返回 SELL（优先级最高，覆盖所有技术信号）
- 亏损在 `-5%~-8%` 且无 BUY 支撑 → 降级为 SELL 建议减仓

**仓位管理（新增）：**
- BUY 且置信 ≥ 70% → 建议仓位 80%
- BUY 且置信 < 70% → 建议仓位 50%
- SELL → 建议仓位 0%
- HOLD → 取各子策略建议仓位均值

### 其他组合（保守/均衡/激进/V33）

| 注册名 | 类名 | 子策略 | 说明 |
|--------|------|--------|------|
| 保守组合 | ConservativeEnsemble | 技术面 6 个 + PE | 投票阈值更严 |
| 均衡组合 | BalancedEnsemble | 同上 7 个 | 默认阈值 |
| 激进组合 | AggressiveEnsemble | 同上 7 个 | 投票阈值更松 |
| V33组合 | V33EnsembleStrategy | 技术 6 + 基本面 3 + V3.3 扩展 4（共 13 个） | 重大利空优先、动态权重与 7 日冷却 |

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
| 单股多策略分析 | `tools/analysis/analyze_single_stock.py` | 9 大单策略：MA, MACD, RSI, BOLL, KDJ, DUAL（技术面6）+ PE, PB, PEPB（基本面3） |
| 持仓多策略分析 | `tools/analysis/portfolio_strategy_analysis.py` | 同上 9 大策略 |
| 每日选股推荐 | `tools/analysis/recommend_today.py` | 单 MACD 或 9 策略 EnsembleStrategy（技术6+基本面3，加权投票） |
| 交易报告生成 | `tools/analysis/generate_trade_report.py` | 双核动量轮动（ETF 轮动），非单股策略库 |
| 批量回测 | `tools/backtest/batch_backtest.py` | 可配置策略；支持 `--check-future` 未来函数校验 |

若要在「每日推荐」中使用 V33 组合（含情绪/消息/政策/龙虎榜），需在 `recommend_today.py` 中增加对 `V33EnsembleStrategy(symbol=code)` 的调用或选项。

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
