# 回测与实盘规范（V3.3 Phase 6）

> 配套 [V3.3 设计规格](V33_DESIGN_SPEC.md)、[落地计划](V33_IMPLEMENTATION_PLAN.md)。  
> 用于回测框架与实盘执行时的一致性约束与校验说明。

---

## 6.1 未来函数约束

回测中须显式遵守以下时点，避免使用未来数据：

| 策略/数据 | 约束说明 |
|-----------|----------|
| 情绪 | 仅使用 T 日及以前的数据计算 T 日 S、S_low、S_high；T+1 确认用 T+1 收盘后数据，执行 T+2 开盘。 |
| 新闻/消息 | 信号从**新闻发布时间之后**生效；回测时新闻时间戳不得晚于当前 K 线时间。 |
| 政策 | 同上，政策发布时间之后生效；去重与时间以政府官网为准。 |
| 龙虎榜/大宗 | T 日交易 T+1 披露，信号在 **T+2 开盘** 可用；回测中不得在 T+1 及更早使用 T 日龙虎榜/大宗结果。 |

**已实现**：`src/core/backtest_constraints.py` 提供 `filter_news_by_time`、`filter_policy_by_time`、`is_lhb_visible_at_date`、`filter_lhb_by_visible_date`、`check_sentiment_no_future`。回测框架在每根 K 线/每日截面调用上述接口过滤数据即可。`tools/backtest/batch_backtest.py` 支持 `--check-future` 时输出校验提示。

---

## 6.2 参数敏感性

对关键参数做 ±20% 或文档约定区间的敏感性分析，筛选**收益/回撤比变异系数最小**的参数组：

| 策略 | 参数 | 默认 | 敏感性区间 |
|------|------|------|------------|
| 情绪 | 20/80 分位 | S_low/S_high | [16, 24] / [76, 84] 或 16/24/76/84 |
| 新闻 | 情感阈值 | 0.3 / -0.3 | [0.24, 0.36] / [-0.36, -0.24] |
| 趋势过滤 | ADX 阈值 | 25 | [20, 30] |

**已实现**：`tools/optimization/v33_sensitivity.py` 对新闻情感阈值（buy_threshold / sell_threshold）做网格扫描，按收益/回撤比变异系数 CV 最小筛选参数。用法：`python3 tools/optimization/v33_sensitivity.py [--stocks 20] [--strategy news]`。

---

## 6.3 成本与延迟

与 `config/trading_costs.yaml`、`config/signal_timing.yaml` 保持一致：

- **成本**：滑点、佣金、印花税按配置注入回测与实盘。
- **延迟**：  
  - 通用：信号产生后 **5 分钟** 再下单。  
  - 盘后新闻：次日开盘或次日开盘后 15 分钟执行。  
  - 情绪：T+1 收盘确认、T+2 开盘执行（见 [SENTIMENT_TECH](SENTIMENT_TECH.md)）。  
  - 龙虎榜/大宗：T+2 开盘执行。

回测中应对每笔订单应用相同延迟与成本，以便与实盘可比。

---

## 6.4 人工覆盖接口

- **政策标签修正**：提供入口（配置或管理接口）对政策新闻的利好/利空/影响力进行人工修正；修正**次日生效**，不追溯历史回测。  
- **修正日志**：记录修正时间、原文 ID、修正前后标签，便于审计与复盘。

**已实现**：`config/policy_overrides.yaml` 为覆盖表；`src/data/policy/policy_overrides.py` 提供 `get_policy_override(policy_id)`、`policy_id_from_row(date, title)`。`get_policy_sentiment_v33` 中每条政策先查覆盖再回退自动标注；修正次日生效由运维在覆盖表中填写/更新实现。

---

**文档版本**：V3.3 Phase 6  
**相关**：[V33_IMPLEMENTATION_PLAN](V33_IMPLEMENTATION_PLAN.md) | [SENTIMENT_TECH](SENTIMENT_TECH.md) | [V33_落地与状态](V33_落地与状态.md)
