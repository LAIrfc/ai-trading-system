# 基本面数据：分析与使用

> 合并自原 `FUNDAMENTAL_DATA_ANALYSIS.md` 与 `FUNDAMENTAL_DATA_USAGE_PLAN.md`。

---

## 一、已实现的基本面数据

### 1. 日频估值指标（`get_daily_basic`）

**数据来源**：tushare `daily_basic` 接口

| 字段 | 说明 | 用途 |
|------|------|------|
| **pe_ttm** | 滚动市盈率（TTM） | ✅ 已用于 PE 策略 |
| **pb** | 市净率 | ✅ 已用于 PB 策略 |
| **ps** | 市销率 | ⚠️ 已获取未用 |
| **market_cap** / **circ_market_cap** | 总/流通市值 | 📊 参考 |
| **turnover_rate** | 换手率 | 📊 参考 |

- 频率：日频；对齐：前向填充（ffill）；避免未来函数：仅用已发布数据。

### 2. 财务指标（`get_financial_indicators`）

**状态**：⚠️ 未实现（待扩展）。计划：ROE、净利润增长率、营收增长率、资产负债率、流动比率等，季频，按财报**发布日期**对齐到日频。

---

## 二、已实现的基本面策略

### PE 估值（`src/strategies/fundamental_pe.py`）✅

- 逻辑：PE < 历史 20% 分位 → BUY；PE > 80% 分位 → SELL；其余 HOLD。
- 滚动窗口默认 3 年（756 天）；异常值过滤 PE<0 或 >100；已入组合。

### PB 估值（`src/strategies/fundamental_pb.py`）✅

- 逻辑同 PE，基于 PB 分位数；支持分行业；ROE 过滤框架（待 ROE 数据后启用）。

### PE+PB 双因子（`src/strategies/fundamental_pe_pb.py`）✅

- 买入：PE 与 PB 均 <20% 分位；卖出：PE 或 PB >80% 分位；支持分行业与 ROE 过滤。

---

## 三、数据对齐与获取

- **对齐**：季频用财报**发布日期**（ann_date）前向填充到日频，避免未来函数。
- **真实数据**：`FundamentalFetcher(source='tushare')`，需配置 token。
- **回测**：`batch_backtest.py` 默认尝试真实数据，失败则用模拟数据。

---

## 四、使用计划与优先级（原 USAGE_PLAN 摘要）

**为什么先做 PE**：最常用、逻辑清晰；PB/PE+PB 已补上。

**数据使用建议**：
- **PB**：银行/地产等更有效，已实现。
- **市值**：可作股票池过滤或仓位因子。
- **换手率**：可作流动性过滤或技术策略辅助。
- **PS**：优先级低，可后续实现。

**实施建议**：PB 与 PE+PB 已实现；短期可加市值过滤与换手率辅助；中长期可扩展 ROE、财务健康等策略。

---

## 五、使用示例

### 单股测试

```python
from src.data.fetchers.fundamental_fetcher import FundamentalFetcher
from src.strategies.fundamental_pe import PEStrategy

# 获取日线数据
daily_df = fetch_sina('600000', 800)

# 合并基本面数据（真实数据）
fetcher = FundamentalFetcher(source='tushare')
fund_df = fetcher.get_daily_basic('600000', start_date='20200101', end_date='20231231')
df = fetcher.merge_to_daily(daily_df, fund_df)

# 运行PE策略
pe_strategy = PEStrategy()
signal = pe_strategy.analyze(df)
print(f"{signal.action} | conf={signal.confidence}")
```

### 模拟数据（仅用于测试流程）

```python
from src.data.fetchers.fundamental_fetcher import create_mock_fundamental_data

fund_df = create_mock_fundamental_data(daily_df, pe_range=(5, 50), pb_range=(0.5, 5.0))
```

⚠️ `create_mock_fundamental_data` 基于整个 DataFrame 生成，隐含未来信息，**仅用于测试流程，不可用于真实回测**。

### 数据源配置

```bash
# tushare（推荐，数据质量高）
export TUSHARE_TOKEN='your_token'
```

akshare 免费无需 token，但日频基本面接口不稳定，建议使用 tushare。

---

## 六、扩展新基本面策略

1. 参考 `src/strategies/fundamental_pe.py` 创建策略类，继承 `FundamentalQuantileBase`
2. 在 `src/strategies/__init__.py` 的 `STRATEGY_REGISTRY` 中注册
3. 在 `src/data/fetchers/fundamental_fetcher.py` 中添加对应数据获取方法

注意事项：
- 只能使用**已发布的财报数据**（按 ann_date 对齐，不按 end_date）
- 基本面数据用 `ffill` 前向填充，不能用未来数据
- 分位数计算支持全历史（默认）和滚动窗口（`rolling_window=1260` 即 5 年）

---

## 七、相关文档

- [FUNDAMENTAL_REAL_TRADING_STANDARDS](FUNDAMENTAL_REAL_TRADING_STANDARDS.md) — 实盘标准与已知缺口  
- [TURNOVER_VALIDATION_RESULTS](TURNOVER_VALIDATION_RESULTS.md) — 换手率过滤验证结果  
