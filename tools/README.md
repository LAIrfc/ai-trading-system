# 工具脚本目录

**运行命令汇总**：见 [docs/RUN_COMMANDS.md](../docs/RUN_COMMANDS.md)，常用命令一页汇总，便于复制执行。

## 目录结构

```
tools/
├── analysis/              # 分析报告
│   ├── recommend_today.py          # 每日选股（政策面过滤 + 14策略 Ensemble）
│   ├── analyze_single_stock.py     # 单股分析（技术面+14策略，--full 启用完整分析）
│   ├── track_recommendations.py    # 推荐回测追踪（T+5/T+20 胜率）
│   ├── backtest_v64.py             # v6.4 回测
│   ├── sector_analyze.py           # 板块/个股定向14策略分析
│   ├── breakout_pullback_scanner.py # 突破回踩扫描器
│   ├── ab_test_changes.py          # A/B 策略变更回测
│   ├── monitor_factor_ic.py        # 因子 IC 监控
│   └── generate_sector_themes.py   # 生成板块主题
│
├── data/                  # 数据获取与管理
│   ├── backtest_prefetch.py        # 回测日线预取（存/更新 parquet）
│   ├── prefetch_pe_cache.py        # PE 缓存预热
│   ├── prefetch_etf_cache.py       # ETF 缓存预热
│   ├── refresh_stock_pool.py       # 综合股票池刷新（含基本面过滤，统一接口层多源切换）
│   ├── update_fundamental_cache.py # 更新基本面缓存（市值/PE/PB）
│   ├── backfill_pe_pb.py           # 回填 PE/PB 历史数据
│   └── quarterly_update.py         # 季度更新（指数成分+龙头+基本面）
│
├── portfolio/             # 持仓
│   ├── daily_check.py              # 每日持仓检查
│   ├── sync_portfolio.py           # 同步持仓
│   └── update_daily_tracking.py    # 更新每日跟踪
│
├── optimization/          # 策略优化
│   ├── strategy_ablation.py        # 策略剔除实验
│   └── strategy_activation_rate.py # 策略活跃度诊断
│
└── validation/            # 验证与手工测试（与 tests/ 单元测试区分）
    ├── strategy_tester.py          # 策略测试器（交互式）
    ├── test_all_fundamental.py     # 全部基本面策略测试
    ├── test_industry_pe.py         # 行业 PE 测试
    ├── test_pb_strategy.py         # PB 策略测试
    ├── test_turnover_helper.py     # 换手率辅助单元测试
    └── validate_unified_data_layer.py # 统一数据层验证
```

## 使用说明

### 分析报告

```bash
# 每日选股推荐（政策面过滤 + 14策略 Ensemble）
python3 tools/analysis/recommend_today.py --pool mydate/stock_pool_all.json --strategy ensemble
python3 tools/analysis/recommend_today.py --pool mydate/stock_pool_all.json --top 10

# 单股分析（快速模式：技术面+估值+量价）
python3 tools/analysis/analyze_single_stock.py 002015 协鑫能科

# 单股完整分析（含14策略+新闻）
python3 tools/analysis/analyze_single_stock.py 002015 协鑫能科 --full

# v6.4 回测
python3 tools/analysis/backtest_v64.py

# 推荐回测追踪（T+5/T+20 胜率）
python3 tools/analysis/track_recommendations.py
python3 tools/analysis/track_recommendations.py --top 10 --since 2026-04-21

# 因子 IC 监控
python3 tools/analysis/monitor_factor_ic.py

# 板块/个股定向分析
python3 tools/analysis/sector_analyze.py --codes "688122,603019" --names "西部超导,中科曙光"
```

### 数据工具

```bash
# 回测日线预取（存）与更新（拉新数据后验证策略）
python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool_all.json --all --out-dir mydate/backtest_kline --workers 4
python3 tools/data/backtest_prefetch.py --update --out-dir mydate/backtest_kline --workers 4

# 刷新综合股票池（合并个股+ETF，基本面过滤）
python3 tools/data/refresh_stock_pool.py

# 不过滤直接合并
python3 tools/data/refresh_stock_pool.py

# 验证池内股票数据可用性
python3 tools/data/refresh_stock_pool.py --verify

# PE 缓存预热 / 更新
python3 tools/data/prefetch_pe_cache.py --update

# 季度更新（指数成分+龙头+基本面缓存）
python3 tools/data/quarterly_update.py

# 检查是否需要季度更新
python3 tools/data/quarterly_update.py --check
```

### 持仓工具

```bash
# 每日持仓检查
python3 tools/portfolio/daily_check.py

# 同步持仓
python3 tools/portfolio/sync_portfolio.py

# 更新每日跟踪
python3 tools/portfolio/update_daily_tracking.py
```

### 验证工具

```bash
# 策略测试器（交互式）
python3 tools/validation/strategy_tester.py --interactive

# 基本面策略测试
python3 tools/validation/test_all_fundamental.py

# 统一数据层验证
python3 tools/validation/validate_unified_data_layer.py
```
