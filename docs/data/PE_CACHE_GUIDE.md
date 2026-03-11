# PE/PB 缓存机制说明

> 更新日期：2026-03-11

基本面策略（PE、PB、PEPB）依赖历史 PE/PB 数据计算历史分位数。由于实时 API 只能获取当日数据，系统通过**本地缓存**存储历史数据，并支持增量更新。

---

## 缓存目录结构

```
mydate/pe_cache/
├── 000001.parquet   ← 平安银行历史 PE/PB
├── 000002.parquet   ← 万科A历史 PE/PB
├── 600519.parquet   ← 贵州茅台历史 PE/PB
└── ...              ← 每只股票一个文件
```

每个 parquet 文件包含以下列：

| 列名 | 类型 | 说明 |
|------|------|------|
| `date` | datetime | 交易日期 |
| `pe_ttm` | float | 滚动市盈率（TTM） |
| `pb` | float | 市净率 |

---

## 数据来源

通过 **Baostock** API 获取，覆盖 A 股所有个股的历史 PE/PB 数据。

> ETF 没有 PE/PB 数据，缓存文件不存在时策略自动跳过，不影响技术策略投票。

---

## 缓存管理工具

### 1. 初始化/全量拉取

首次使用或需要重建缓存时，对指定股票池全量拉取历史数据：

```bash
# 对 stock_pool_all.json 中所有股票全量拉取（约需 30-60 分钟）
python3 tools/data/prefetch_pe_cache.py --pool mydate/stock_pool_all.json

# 对单只股票全量拉取
python3 tools/data/prefetch_pe_cache.py --code 600519

# 强制刷新（忽略已有缓存，重新全量拉取）
python3 tools/data/prefetch_pe_cache.py --pool mydate/stock_pool_all.json --refresh
```

### 2. 增量更新

每次运行回测前，自动更新缓存到最新日期：

```bash
# 增量更新（只拉取上次缓存日期之后的新数据）
python3 tools/data/prefetch_pe_cache.py --pool mydate/stock_pool_all.json --update
```

增量更新逻辑：
```
读取缓存最后日期
  ├── 距今 ≤ 1 天 → 已是最新，跳过
  ├── 距今 > 1 天 → 拉取 (last_date+1) 到今天的新数据，合并去重
  └── 缓存损坏   → 全量重新拉取
```

### 3. 回测时自动更新

`batch_backtest.py` 在加载 PE 缓存时会自动触发增量更新：

```python
# batch_backtest.py 内部逻辑
df = _load_pe_cache(code, df, auto_update=True)  # auto_update=True 时自动增量更新
```

---

## 缓存文件格式

```python
import pandas as pd

# 读取
df = pd.read_parquet('mydate/pe_cache/600519.parquet')
print(df.tail())
#          date   pe_ttm    pb
# 2026-03-07  28.5   9.2
# 2026-03-10  28.3   9.1
# 2026-03-11  28.1   9.0

# 查看最新日期
last_date = df['date'].max()
```

---

## 常见问题

**Q：为什么基本面策略显示"缺少 pe_ttm 数据"？**  
A：该股票没有 PE 缓存文件，或缓存文件中该日期段没有数据。运行 `prefetch_pe_cache.py` 初始化缓存。

**Q：ETF 的基本面策略为什么总是 HOLD？**  
A：ETF 没有 PE/PB 数据，这是正常行为。策略会自动跳过，不影响技术策略的投票结果。

**Q：PE 缓存多久需要更新一次？**  
A：每个交易日更新一次即可。`batch_backtest.py` 在运行时会自动增量更新，无需手动操作。

**Q：如何检查缓存是否是最新的？**  
```bash
python3 -c "
import os, pandas as pd
d = 'mydate/pe_cache'
files = os.listdir(d)
dates = [pd.read_parquet(f'{d}/{f}')['date'].max() for f in files[:5]]
print([str(d.date()) for d in dates])
"
```

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `tools/data/prefetch_pe_cache.py` | PE/PB 缓存管理工具（全量/增量） |
| `tools/backtest/batch_backtest.py` | 回测时自动调用增量更新 |
| `src/strategies/fundamental_base.py` | 基本面策略基类，读取缓存计算分位数 |
| `src/strategies/fundamental_pe.py` | PE 策略实现 |
| `src/strategies/fundamental_pb.py` | PB 策略实现 |
| `src/strategies/fundamental_pe_pb.py` | PE+PB 双因子策略实现 |
