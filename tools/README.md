# 工具脚本目录

**运行命令汇总**：见 [docs/RUN_COMMANDS.md](../docs/RUN_COMMANDS.md)，常用命令一页汇总，便于复制执行。

## 目录结构

```
tools/
├── backtest/              # 回测
│   ├── batch_backtest.py           # 大规模批量回测（支持 --check-future、--local-kline）
│   ├── cross_validate.py           # 策略交叉验证
│   ├── backtest_dual_momentum.py   # 双核动量 ETF 轮动回测
│   └── compare_fundamental.py      # 技术 vs 基本面对比
│
├── optimization/          # 参数优化
│   ├── optimize_macd.py            # MACD 参数优化
│   └── v33_sensitivity.py          # V3.3 参数敏感性（新闻阈值等）
│
├── analysis/              # 分析报告（策略见 docs/strategy/STRATEGY_LIST.md）
│   ├── recommend_today.py          # 每日选股推荐（MACD 或多策略组合）
│   ├── analyze_single_stock.py     # 单股 11 大策略分析
│   ├── portfolio_strategy_analysis.py  # 持仓 11 大策略分析
│   └── generate_trade_report.py    # 双核动量交易报告
│
├── data/                  # 数据获取与管理
│   ├── backtest_prefetch.py        # 回测日线预取（存/更新 parquet）
│   ├── backtest_prefetch_aux.py    # 回测辅助数据预取（新闻/政策/龙虎榜）
│   ├── view_backtest_kline.py      # 查看本地回测数据（历史价格/失败列表）
│   ├── prefetch_etf_cache.py       # ETF 缓存预热
│   ├── kline_fetcher.py            # K 线获取（单只）
│   ├── refresh_stock_pool.py       # 综合股票池刷新（含基本面过滤，统一接口层多源切换）
│   ├── update_fundamental_cache.py # 更新基本面缓存（市值/PE/PB）
│   ├── test_data_sources.py        # 数据源可用性测试
│   └── quarterly_update.py         # 季度更新（指数成分+龙头+基本面）
│
├── portfolio/             # 持仓
│   └── daily_check.py              # 每日持仓检查
│
└── validation/            # 验证与手工测试（与 tests/ 单元测试区分）
    ├── strategy_tester.py          # 策略测试器（交互式）
    ├── test_fundamental.py         # PE 策略测试
    ├── test_all_fundamental.py     # 全部基本面策略测试
    ├── test_industry_pe.py         # 行业 PE 测试
    ├── test_pb_strategy.py         # PB 策略测试
    ├── test_turnover_helper.py     # 换手率辅助单元测试
    ├── test_turnover_integration.py # 换手率集成测试
    ├── validate_turnover_effect.py  # 换手率效果回测验证
    └── validate_unified_data_layer.py # 统一数据层验证
```

## 使用说明

### 回测工具

```bash
# 大规模回测（500只股票，3年数据）
python3 tools/backtest/batch_backtest.py --count 500

# 策略交叉验证
python3 tools/backtest/cross_validate.py
```

**回测数据：存 + 更新，再用最新数据验证策略**  
慢的主要原因是每只股票都从网络拉日线；存到本地后，还需**定期更新**拉取新数据，再用更新后的数据跑回测验证策略。

- **首次：存股票池里的数据**（预取到本地）：
  ```bash
  python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool_all.json --all --out-dir mydate/backtest_kline --workers 4
  ```
  会在 `mydate/backtest_kline` 下生成每只 `{code}.parquet` 和 `manifest.json`。
- **定期：更新拉取新数据**（在已有缓存上覆盖为最新日线，便于验证策略）：
  ```bash
  python3 tools/data/backtest_prefetch.py --update --out-dir mydate/backtest_kline --datalen 800 --workers 4
  ```
  更新完成后用同一目录跑回测即可得到基于最新数据的回测结果。
- **回测**：若存在 `mydate/backtest_kline` 且含 parquet，`batch_backtest` 会**自动优先读本地**；也可显式指定：
  ```bash
  python3 tools/backtest/batch_backtest.py --pool mydate/stock_pool_all.json --count 300 --local-kline mydate/backtest_kline
  ```
- 使用 V3.3 时还可预取/更新新闻/政策/龙虎榜，回测时加 `--local-aux mydate/backtest_aux`。

### 参数优化

```bash
# MACD参数优化
python3 tools/optimization/optimize_macd.py
```

### 分析报告

```bash
# 每日选股推荐（默认 MACD；可选 --strategy ensemble 使用 7 策略组合）
python3 tools/analysis/recommend_today.py
python3 tools/analysis/recommend_today.py --pool stock_pool_600.json --strategy ensemble

# 单股多策略分析（11 大策略：技术+情绪+消息+政策+龙虎榜+PE/PB）
python3 tools/analysis/analyze_single_stock.py 002015
python3 tools/analysis/analyze_single_stock.py 002015 --name "协鑫能科"

# 持仓多策略分析（同上 11 大策略）
python3 tools/analysis/portfolio_strategy_analysis.py

# 双核动量交易报告（ETF 轮动）
python3 tools/analysis/generate_trade_report.py
```

### 数据工具

```bash
# 回测日线预取（存）与更新（拉新数据后验证策略）
python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool_all.json --all --out-dir mydate/backtest_kline --workers 4
python3 tools/data/backtest_prefetch.py --update --out-dir mydate/backtest_kline --workers 4

# 查看哪只股票、历史价格（或导出 CSV），以及未拉取成功的代码
python3 tools/data/view_backtest_kline.py 000425
python3 tools/data/view_backtest_kline.py 600519 --csv
python3 tools/data/view_backtest_kline.py --list-failed

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

### 验证工具

```bash
# 策略测试器（交互式）
python3 tools/validation/strategy_tester.py --interactive

# 基本面策略测试
python3 tools/validation/test_fundamental.py
python3 tools/validation/test_all_fundamental.py

# 换手率效果验证
python3 tools/validation/validate_turnover_effect.py

# 统一数据层验证
python3 tools/validation/validate_unified_data_layer.py

# 数据源可用性测试
python3 tools/data/test_data_sources.py
```
