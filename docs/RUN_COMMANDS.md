# 运行命令汇总

本文档汇总项目常用运行命令，便于复制执行。所有命令均在项目根目录下执行（即 `ai-trading-system/`）。

---

## 一、回测数据（存 + 更新 + 查看）

**本地股票池数据记录**：预取/更新完成后，在 `mydate/backtest_kline/manifest.json` 中会记录：
- `pool`：使用的股票池文件（如 `mydate/stock_pool_all.json`）
- `codes`：池子内全部标的代码列表
- `prefetch_time` / `last_update`：预取时间、最后更新时间
- `datalen`：每只 K 线根数（如 800）
- `success_count` / `fail_count`：成功、失败数量
- `failed_codes`：未拉取成功的股票代码列表

### 1. 首次：按股票池预取日线到本地

```bash
python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool_all.json --all --out-dir mydate/backtest_kline --workers 4
```

- 输出目录：`mydate/backtest_kline`，每只股票一个 `{code}.parquet`，另生成 `manifest.json`（即上面的本地池子数据记录）。

### 2. 定期：更新本地数据（拉取最新日线）

```bash
python3 tools/data/backtest_prefetch.py --update --out-dir mydate/backtest_kline --datalen 800 --workers 4
```

- 对已有缓存逐只拉取最新数据并覆盖，更新后 `manifest.json` 会包含 `failed_codes`（未拉取成功的代码）。

### 3. 查看某只股票历史价格

```bash
# 终端查看（最近 20 条 + 最早 5 条）
python3 tools/data/view_backtest_kline.py 000425

# 导出 CSV（Excel 可打开）
python3 tools/data/view_backtest_kline.py 000425 --csv

# 列出未拉取成功的股票代码
python3 tools/data/view_backtest_kline.py --list-failed
```

---

## 二、批量回测

### 1. 使用本地 K 线跑回测（推荐，快）

```bash
python3 tools/backtest/batch_backtest.py --pool mydate/stock_pool_all.json --count 300 --local-kline mydate/backtest_kline
```

- 若存在 `mydate/backtest_kline` 且含 parquet，可不写 `--local-kline`，脚本会自动使用该目录。
- 结果默认写入：`mydate/backtest_results.json`。

### 2. 指定结果输出路径

```bash
python3 tools/backtest/batch_backtest.py --pool mydate/stock_pool_all.json --count 300 --output mydate/backtest_results_v3.json
```

### 3. 策略交叉验证

```bash
python3 tools/backtest/cross_validate.py
```

---

## 三、分析与选股

### 1. 每日选股推荐

```bash
# 默认 MACD
python3 tools/analysis/recommend_today.py

# 11 策略组合（技术6+基本面3+消息面+资金面，推荐）
python3 tools/analysis/recommend_today.py --pool mydate/stock_pool_all.json --strategy ensemble
```

### 2. 单股多策略分析

```bash
python3 tools/analysis/analyze_single_stock.py 002015
python3 tools/analysis/analyze_single_stock.py 002015 --name "协鑫能科"
```

### 3. 持仓多策略分析

```bash
python3 tools/analysis/portfolio_strategy_analysis.py
```

### 4. 双核动量交易报告（ETF 轮动）

```bash
python3 tools/analysis/generate_trade_report.py
```

---

## 四、数据与股票池

### 1. 单只 K 线获取

```bash
python3 tools/data/kline_fetcher.py 600000
```

### 2. 刷新股票池

```bash
# 全量刷新（合并个股+ETF，基本面过滤）
python3 tools/data/refresh_stock_pool.py

# 不过滤直接合并
python3 tools/data/refresh_stock_pool.py --no-filter

# 重新获取赛道龙头
python3 tools/data/refresh_stock_pool.py --refresh-sectors

# 验证池内股票数据可用性
python3 tools/data/refresh_stock_pool.py --verify
```

### 3. 季度更新

```bash
python3 tools/data/quarterly_update.py
python3 tools/data/quarterly_update.py --check
```

---

## 五、参数优化与验证

### 1. MACD 参数优化

```bash
python3 tools/optimization/optimize_macd.py
```

### 2. 策略测试器

```bash
python3 tools/validation/strategy_tester.py
python3 tools/validation/strategy_tester.py --interactive
```

### 3. 基本面策略测试

```bash
python3 tools/validation/test_all_fundamental.py
```

---

## 六、推荐日常流程（简要）

| 步骤 | 命令 |
|------|------|
| 1. 更新本地K线缓存 | `python3 tools/data/backtest_prefetch.py --update --workers 4` |
| 2. 更新PE/PB缓存 | `python3 tools/data/prefetch_pe_cache.py --pool mydate/stock_pool_all.json --update` |
| 3. 跑批量回测 | `python3 tools/backtest/batch_backtest.py --pool mydate/stock_pool_all.json --count 300 --output mydate/backtest_results_v3.json` |
| 4. 每日选股 | `python3 tools/analysis/recommend_today.py --pool mydate/stock_pool_all.json --strategy ensemble` |
| 5. 查未成功标的 | `python3 tools/data/view_backtest_kline.py --list-failed` |
| 6. 查某只历史价格 | `python3 tools/data/view_backtest_kline.py 000425` 或 `--csv` |

更多说明见 `tools/README.md` 与各脚本 `--help`。

---

## 七、Windows vs Linux 路径差异

| 操作 | Windows | Linux/macOS |
|------|---------|-------------|
| 路径分隔符 | `\` | `/` |
| Python 命令 | `python` | `python3` |
| 批量回测 | `python tools\backtest\batch_backtest.py` | `python3 tools/backtest/batch_backtest.py` |
| 策略测试 | `python tools\validation\strategy_tester.py` | `python3 tools/validation/strategy_tester.py` |
| K线获取 | `python tools\data\kline_fetcher.py 600519` | `python3 tools/data/kline_fetcher.py 600519` |
| 启动脚本 | `scripts\start_windows.bat` | `bash scripts/start.sh` |

Windows 用户也可直接双击 `scripts/start_windows.bat`。详见 `docs/setup/WINDOWS_GUIDE.md`。