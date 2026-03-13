# 策略清单（完整）

> 项目内所有策略与组合的索引，便于查阅和工具对接。  
> 更新：2026-03-12

---

## 一、单策略（共 14 个，其中 11 个入 EnsembleStrategy）

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

### 消息面 + 资金面策略（2 个，入 EnsembleStrategy）

| 注册名 | 类名 | 文件 | 说明 |
|--------|------|------|------|
| NEWS | NewsSentimentStrategy | `news_sentiment.py` | 新闻情感（24h N、S_news、关键词0.4+LLM0.6 融合、预期差） |
| MONEY_FLOW | MoneyFlowStrategy | `money_flow.py` | 龙虎榜连续2日同席位 + 大宗折价/买卖方 |

### 市场级策略（2 个，不入 Ensemble，作独立/过滤层）

| 注册名 | 类名 | 文件 | 说明 |
|--------|------|------|------|
| Sentiment | SentimentStrategy | `sentiment.py` | 市场情绪综合指数（S/S_low/S_high），市场级 |
| PolicyEvent | PolicyEventStrategy | `policy_event.py` | 政策事件（关键词+LLM 融合），市场级，作选股前大盘过滤 |

> PolicyEvent 在每日选股入口 `recommend_today.py` 中作为大盘过滤层：政策极度利空时暂停选股；可用 `--no-policy-filter` 强制跳过。

### 其他（1 个，接口不兼容）

| 注册名 | 类名 | 文件 | 说明 |
|--------|------|------|------|
| DualMomentum | DualMomentumStrategy | `core/dual_momentum_strategy.py` | ETF 轮动专用，MultiIndex 接口 |

---

## 二、组合策略

### EnsembleStrategy（主力组合，11 子策略）

```
技术面 6 个：MA / MACD / RSI / BOLL / KDJ / DUAL
基本面 3 个：PE / PB / PEPB
消息面 1 个：NEWS（关键词+LLM 融合）
资金面 1 个：MONEY_FLOW（龙虎榜+大宗）
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
| `symbol` / `stock_name` | — | NEWS/MONEY_FLOW 需要；选股时 `set_symbol()` 逐股注入 |

**权重配置**（基于 v3 回测 + 保守估计）：

| 策略 | 权重 | 说明 |
|------|------|------|
| BOLL | 1.5 | 夏普最高(0.20)、回撤最小(13.8%) |
| MACD | 1.3 | 收益最高(+15.3%)，夏普第二(0.16) |
| KDJ | 1.1 | 夏普第三(0.15)，盈利率70.6% |
| MA | 1.0 | 收益第三(+13.9%) |
| DUAL | 0.9 | 无单独回测数据，保守权重 |
| RSI | 0.8 | 夏普最低(0.07)，降权 |
| PEPB | 0.8 | 双因子共振，数据要求高 |
| PE | 0.6 | 回撤最小(9%)，辅助过滤 |
| PB | 0.6 | 单因子 PB |
| NEWS | 0.5 | 关键词+LLM 融合，触发频率中等 |
| MONEY_FLOW | 0.4 | 龙虎榜+大宗，触发频率低但质量高 |

**决策优先级**（从高到低）：
1. 硬止损（亏损 ≤ -8%）→ 无条件 SELL  
2. 重大利空（任一 SELL 含「重大利空」）→ 直接 SELL  
3. 投票决策（weighted / majority / unanimous / any）  
4. 持仓预警（-5%~-8% 且无 BUY）→ 建议减仓 SELL  

**动态权重**：`v33_weights` 根据沪深300 ADX/HV20 判断趋势/震荡市，自动调节各策略权重，7 日冷却。

**持仓成本感知**：
- 传入 `holding_cost` 后，每次 `analyze()` 计算当前盈亏
- 亏损超过 `-8%` → 直接返回 SELL
- 亏损在 `-5%~-8%` 且无 BUY 支撑 → 降级为 SELL 建议减仓

**仓位管理**：
- BUY 且置信 ≥ 70% → 建议仓位 80%
- BUY 且置信 < 70% → 建议仓位 50%
- SELL → 建议仓位 0%
- HOLD → 取各子策略建议仓位均值

### 预设组合（均继承 EnsembleStrategy，11 子策略）

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
