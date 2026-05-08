# 运行命令汇总

本文档汇总项目常用运行命令，便于复制执行。所有命令均在项目根目录下执行（即 `ai-trading-system/`）。

---

## 一、回测数据（存 + 更新）

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

- 输出目录：`mydate/backtest_kline`，每只股票一个 `{code}.parquet`，另生成 `manifest.json`。

### 2. 定期：更新本地数据（拉取最新日线）

```bash
python3 tools/data/backtest_prefetch.py --update --out-dir mydate/backtest_kline --datalen 800 --workers 4
```

- 对已有缓存逐只拉取最新数据并覆盖，更新后 `manifest.json` 会包含 `failed_codes`（未拉取成功的代码）。

---

## 二、回测

### 1. V6.4 回测

```bash
python3 tools/analysis/backtest_v64.py --pool mydate/stock_pool_all.json --count 300
```

---

## 三、分析与选股

### 1. 每日选股推荐

```bash
# 默认 14 策略 ensemble（推荐）
python3 tools/analysis/recommend_today.py

# 指定股票池
python3 tools/analysis/recommend_today.py --pool mydate/stock_pool_all.json --strategy ensemble

# 使用缓存数据（非交易时段推荐）
python3 tools/analysis/recommend_today.py --cache-only
```

### 2. 单股多策略分析

```bash
python3 tools/analysis/analyze_single_stock.py 002015 --name "协鑫能科"
```

### 3. 推荐回测追踪

```bash
# 统计历史推荐的 T+5/T+20 胜率和收益
python3 tools/analysis/track_recommendations.py
python3 tools/analysis/track_recommendations.py --top 10 --since 2026-04-21
```

### 4. 突破回踩扫描

```bash
python3 tools/analysis/breakout_pullback_scanner.py
```

---

## 四、数据与股票池

### 1. 刷新股票池

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

### 2. PE/PB 缓存预取

```bash
python3 tools/data/prefetch_pe_cache.py --pool mydate/stock_pool_all.json --update
```

### 3. 季度更新

```bash
python3 tools/data/quarterly_update.py
python3 tools/data/quarterly_update.py --check
```

---

## 五、参数优化与验证

### 1. 策略剔除实验

```bash
python3 tools/optimization/strategy_ablation.py --pool mydate/stock_pool_all.json --limit 30
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

### 4. Factor IC 监控

```bash
python3 tools/analysis/monitor_factor_ic.py
```

---

## 六、推荐日常流程（简要）

| 步骤 | 命令 |
|------|------|
| 1. 更新本地K线缓存 | `python3 tools/data/backtest_prefetch.py --update --workers 4` |
| 2. 更新PE/PB缓存 | `python3 tools/data/prefetch_pe_cache.py --pool mydate/stock_pool_all.json --update` |
| 3. 每日选股 | `python3 tools/analysis/recommend_today.py` |
| 4. 查看推荐胜率 | `python3 tools/analysis/track_recommendations.py` |

各脚本均支持 `--help` 查看完整参数说明。

---

## 七、Windows vs Linux 路径差异

| 操作 | Windows | Linux/macOS |
|------|---------|-------------|
| 路径分隔符 | `\` | `/` |
| Python 命令 | `python` | `python3` |
| 策略测试 | `python tools\validation\strategy_tester.py` | `python3 tools/validation/strategy_tester.py` |

Windows 用户详见 `docs/setup/WINDOWS_GUIDE.md`。
