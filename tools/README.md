# 工具脚本目录

## 目录结构

```
tools/
├── backtest/              # 回测相关工具
│   ├── batch_backtest.py       # 大规模批量回测（500只股票×3年）
│   ├── cross_validate.py      # 策略交叉验证
│   └── backtest_dual_momentum.py  # 双核动量策略回测
│
├── optimization/          # 参数优化工具
│   └── optimize_macd.py       # MACD参数优化
│
├── analysis/              # 分析报告工具
│   ├── generate_trade_report.py  # 生成交易报告
│   └── recommend_today.py        # 今日推荐（选股）
│
├── data/                  # 数据工具
│   ├── kline_fetcher.py        # K线数据获取
│   ├── refresh_stock_pool.py   # 刷新股票池（含基本面过滤）
│   └── quarterly_update.py     # 季度定期更新（指数成分+龙头+基本面）
│
└── testing/               # 测试工具
    ├── test_fundamental.py     # 基本面策略测试
    └── strategy_tester.py      # 策略测试器
```

## 使用说明

### 回测工具

```bash
# 大规模回测（500只股票，3年数据）
python3 tools/backtest/batch_backtest.py --count 500

# 策略交叉验证
python3 tools/backtest/cross_validate.py
```

### 参数优化

```bash
# MACD参数优化
python3 tools/optimization/optimize_macd.py
```

### 分析报告

```bash
# 生成交易报告
python3 tools/analysis/generate_trade_report.py

# 今日推荐
python3 tools/analysis/recommend_today.py
```

### 数据工具

```bash
# 获取K线数据
python3 tools/data/kline_fetcher.py 600000

# 刷新综合股票池（合并个股+ETF，基本面过滤）
python3 tools/data/refresh_stock_pool.py

# 不过滤直接合并
python3 tools/data/refresh_stock_pool.py --no-filter

# 重新获取赛道龙头
python3 tools/data/refresh_stock_pool.py --refresh-sectors

# 验证池内股票数据可用性
python3 tools/data/refresh_stock_pool.py --verify

# 季度更新（指数成分+龙头+基本面缓存）
python3 tools/data/quarterly_update.py

# 检查是否需要季度更新
python3 tools/data/quarterly_update.py --check
```

### 测试工具

```bash
# 测试基本面策略
python3 tools/testing/test_fundamental.py

# 策略测试器
python3 tools/testing/strategy_tester.py
```
