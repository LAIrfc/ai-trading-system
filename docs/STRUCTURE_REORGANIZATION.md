# 代码结构整理方案

## 当前问题

1. **策略系统重复**：
   - `src/strategies/` - 新统一策略系统（当前主要使用）
   - `src/core/strategy/` - 旧策略系统（可能已废弃）

2. **工具脚本混杂**：
   - `tools/` 下所有脚本平铺，没有分类

3. **数据模块分散**：
   - `src/data/` 下有多个数据获取文件
   - 部分功能重复

4. **文档可能重复**：
   - 多个文档描述相似内容

## 整理方案

### 1. 策略系统统一

**保留**：`src/strategies/`（新系统，功能完整）
- 统一接口：`StrategySignal`
- 完整回测引擎
- 7个策略（6技术+1基本面）

**处理**：`src/core/strategy/`
- 如果已废弃，移动到 `src/core/strategy/_deprecated/`
- 或标记为旧版，在文档中说明

### 2. 工具脚本分类

```
tools/
├── backtest/              # 回测相关
│   ├── batch_backtest.py
│   ├── cross_validate.py
│   └── backtest_dual_momentum.py
├── optimization/          # 参数优化
│   └── optimize_macd.py
├── analysis/              # 分析报告
│   ├── generate_trade_report.py
│   └── recommend_today.py
├── data/                   # 数据工具
│   ├── kline_fetcher.py
│   └── refresh_stock_pool.py
└── testing/                # 测试工具
    ├── test_fundamental.py
    └── strategy_tester.py
```

### 3. 数据模块整理

```
src/data/
├── __init__.py
├── fetchers/               # 数据获取器
│   ├── __init__.py
│   ├── market_data.py      # 市场数据（日线）
│   ├── realtime_data.py    # 实时行情
│   ├── fundamental_fetcher.py  # 基本面数据
│   └── etf_data_fetcher.py     # ETF数据
├── collectors/            # 数据采集器（保留）
│   └── market_data_collector.py
└── processors/            # 数据处理器（保留）
```

### 4. 文档整理

```
docs/
├── README.md              # 主文档
├── guides/                 # 使用指南
│   ├── QUICK_START.md
│   ├── STRATEGY_GUIDE.md
│   └── FUNDAMENTAL_STRATEGY_GUIDE.md
├── reference/              # 参考文档
│   ├── STRATEGY_DETAIL.md
│   └── API_REFERENCE.md
└── deprecated/            # 已废弃文档
    └── (旧文档移动到这里)
```

## 实施步骤

1. ✅ 创建新的目录结构
2. ✅ 移动文件到对应目录
3. ✅ 更新所有导入路径
4. ✅ 更新文档引用
5. ✅ 测试确保功能正常
