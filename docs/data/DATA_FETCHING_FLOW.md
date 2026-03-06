# 数据获取流程完整说明

> 更新时间：2026-03-06  
> 版本：V3.4（增强版多源容错）

---

## 一、架构概览

### 1.1 核心组件

```
策略/分析工具
    ↓
UnifiedDataProvider (统一数据提供层)
    ↓
KlineAdapter (数据源适配器)
    ↓
实际数据源 (Sina/EastMoney/Tencent/Tushare/Akshare/Baostock/本地缓存)
```

### 1.2 设计原则

1. **策略层无感知**：策略只调用 `provider.get_kline()`，不关心底层数据源
2. **自动切换**：主数据源失败时自动切换到备用源，无需人工干预
3. **股票/ETF 分离**：股票和 ETF 使用不同的数据源顺序
4. **熔断保护**：连续失败的数据源自动熔断 5 分钟，避免浪费时间
5. **本地缓存兜底**：网络全部失败时，使用本地缓存数据

---

## 二、数据源配置

### 2.1 配置文件

`config/data_sources.yaml`:

```yaml
kline:
  # 股票数据源顺序（普通股票）
  sources: [sina, eastmoney, tencent, tushare]
  
  # ETF 数据源顺序（自动判断 ETF 时使用）
  # local_cache: 本地缓存（优先级最高，网络不稳时兜底）
  # akshare_etf: akshare 的新浪/网易/东方财富三源轮询
  # push2his_etf: 东方财富 push2his 直接接口
  # baostock_etf: baostock ETF 数据（部分 ETF 支持）
  etf_sources: [local_cache, akshare_etf, push2his_etf, baostock_etf]
```

### 2.2 数据源详情

#### 股票数据源

| 数据源 | 适配器类 | 说明 | 优先级 |
|--------|----------|------|--------|
| sina | SinaKlineAdapter | 新浪财经，速度快 | 1（主） |
| eastmoney | EastMoneyKlineAdapter | 东方财富 akshare | 2 |
| tencent | TencentKlineAdapter | 腾讯财经 | 3 |
| tushare | TushareKlineAdapter | tushare（需 token） | 4 |

#### ETF 数据源

| 数据源 | 适配器类 | 说明 | 优先级 |
|--------|----------|------|--------|
| local_cache | LocalCacheAdapter | 本地缓存（mycache/etf_kline, mydate/backtest_kline） | 1（最高） |
| akshare_etf | AkshareETFAdapter | akshare 三源轮询（新浪→网易→东方财富） | 2 |
| push2his_etf | Push2hisETFAdapter | 东方财富 push2his 直接接口 | 3 |
| baostock_etf | BaostockETFAdapter | baostock ETF（部分支持） | 4 |

---

## 三、数据获取流程

### 3.1 股票数据获取流程

```
1. 检查熔断状态
   ├─ 熔断中 → 跳过该源
   └─ 未熔断 → 继续

2. 尝试主数据源（sina）
   ├─ 成功 → 返回数据
   └─ 失败 → 重试 2 次
       ├─ 成功 → 返回数据
       └─ 失败 → 记录熔断，切换备用源

3. 尝试备用源 1（eastmoney）
   ├─ 成功 → 返回数据
   └─ 失败 → 记录熔断，继续

4. 尝试备用源 2（tencent）
   ├─ 检查 3 日连续失败
   ├─ 成功 → 返回数据
   └─ 失败 → 记录熔断，继续

5. 尝试备用源 3（tushare）
   ├─ 成功 → 返回数据
   └─ 失败 → 全部失败，返回空

6. 全部失败 → 返回空 DataFrame
```

### 3.2 ETF 数据获取流程

```
1. 尝试本地缓存（local_cache）
   ├─ 查找 mycache/etf_kline/{code}_*.csv
   ├─ 查找 mydate/backtest_kline/{code}.parquet
   ├─ 找到 → 读取并返回
   └─ 未找到 → 继续网络获取

2. 尝试 akshare_etf（内部三源轮询）
   ├─ 新浪 fund_etf_hist_sina
   ├─ 网易 fund_etf_hist_163
   ├─ 东方财富 fund_etf_hist_em
   ├─ 任一成功 → 返回数据
   └─ 全部失败 → 继续

3. 尝试 push2his_etf
   ├─ 东方财富 push2his 直接接口
   ├─ 成功 → 返回数据
   └─ 失败 → 继续

4. 尝试 baostock_etf
   ├─ baostock ETF 数据
   ├─ 成功 → 返回数据
   └─ 失败 → 全部失败

5. 全部失败 → 返回空 DataFrame
```

### 3.3 旧版 ETF 函数兜底（portfolio_strategy_analysis.py）

如果 UnifiedDataProvider 失败，`portfolio_strategy_analysis.py` 还会尝试旧版 ETF 获取函数：

```
1. get_etf_data_akshare()
2. get_etf_data_marketdata()
3. get_etf_data_direct()
```

这提供了额外的容错层。

---

## 四、熔断机制

### 4.1 熔断规则

- **触发条件**：数据源连续失败 3 次
- **熔断时长**：300 秒（5 分钟）
- **例外**：`local_cache` 不受熔断限制（纯本地操作）

### 4.2 熔断状态

位于 `src/data/fetchers/data_prefetch.py`:

```python
_circuit_state = {
    "sina": [0, 0.0],          # [连续失败次数, 最后失败时间戳]
    "eastmoney": [0, 0.0],
    "tencent": [0, 0.0],
    "tushare": [0, 0.0],
    "akshare_etf": [0, 0.0],
    "push2his_etf": [0, 0.0],
    "baostock_etf": [0, 0.0],
    "local_cache": [0, 0.0],
}
```

### 4.3 腾讯特殊规则

腾讯数据源有额外的 **3 日连续失败** 检查：
- 如果连续 3 个自然日都失败，暂时移除并告警
- 避免长期依赖不稳定的数据源

---

## 五、本地缓存机制

### 5.1 缓存目录

| 目录 | 用途 | 格式 |
|------|------|------|
| `mycache/etf_kline/` | ETF 日线缓存 | `{code}_{YYYYMMDD}.csv` |
| `mydate/backtest_kline/` | 回测数据缓存 | `{code}.parquet` |
| `mycache/market_data/` | MarketData 自动缓存 | `{code}_{days}_{YYYYMMDD}.csv` |

### 5.2 缓存策略

1. **自动保存**：
   - `portfolio_strategy_analysis.py` 获取 ETF 数据成功后自动保存到 `mycache/etf_kline/`
   - `MarketData` 类自动缓存到 `mycache/market_data/`

2. **缓存有效期**：
   - 交易时间内（9:00-16:00）：1 小时
   - 非交易时间：12 小时

3. **缓存查找**：
   - 按修改时间排序，优先使用最新的缓存文件
   - 支持多种格式：`.csv`、`.parquet`
   - 支持带日期后缀和不带日期后缀的文件名

### 5.3 手动预热缓存

使用 `tools/data/prefetch_etf_cache.py` 提前缓存 ETF 数据：

```bash
# 从持仓文件读取 ETF 并预热
python3 tools/data/prefetch_etf_cache.py --from-portfolio

# 指定 ETF 代码
python3 tools/data/prefetch_etf_cache.py --codes 512480,159770,510300
```

---

## 六、使用示例

### 6.1 策略中使用

```python
from src.data.provider.data_provider import get_default_kline_provider

# 获取股票数据
provider = get_default_kline_provider()
df = provider.get_kline('600118', datalen=800, min_bars=60)

# 获取 ETF 数据（自动判断）
df_etf = provider.get_kline('512480', datalen=800, min_bars=60)

# 手动指定是否为 ETF
df_etf2 = provider.get_kline('159770', datalen=800, min_bars=60, is_etf=True)
```

### 6.2 分析工具中使用

`tools/analysis/portfolio_strategy_analysis.py` 和 `tools/analysis/analyze_single_stock.py` 已自动使用 UnifiedDataProvider，无需修改调用代码。

---

## 七、故障排查

### 7.1 常见问题

#### 问题 1：所有数据源均失败

**现象**：
```
⚠️  所有数据源均失败，历史数据不足，无法运行策略分析
```

**解决方案**：
1. 检查网络连接
2. 查看熔断状态（是否所有源都被熔断）
3. 使用本地缓存：
   ```bash
   # 检查是否有缓存
   ls mycache/etf_kline/
   ls mydate/backtest_kline/
   ```
4. 手动预热缓存（网络恢复后）：
   ```bash
   python3 tools/data/prefetch_etf_cache.py --from-portfolio
   ```

#### 问题 2：ETF 数据获取失败

**现象**：
```
⚠️  baostock 数据不足，尝试 ETF 专用接口...
❌ 所有数据源均失败
```

**解决方案**：
1. 确认 ETF 代码正确（6 位数，5/159 开头）
2. 检查本地缓存：
   ```bash
   ls mycache/etf_kline/{code}_*.csv
   ```
3. 如果有旧缓存但日期不是今天，仍然可用（LocalCacheAdapter 会自动找最新的）
4. 手动从其他工具获取并保存：
   ```bash
   python3 tools/analysis/analyze_single_stock.py {code}
   ```

#### 问题 3：熔断导致无法获取数据

**现象**：
```
[data_prefetch] 数据源 sina 连续失败达 3 次，熔断 300 秒
```

**解决方案**：
1. 等待 5 分钟后自动恢复
2. 或重启 Python 进程（熔断状态在内存中）
3. 或切换到其他备用源（自动进行）

---

## 八、性能优化

### 8.1 内存缓存

`data_prefetch.py` 中有日线内存缓存：
- TTL：300 秒（5 分钟）
- Key：`(code, datalen)`
- 同一标的短时间内多次请求会直接返回缓存

### 8.2 批量获取建议

如果需要批量获取多只股票数据：
1. 使用 `batch_backtest.py` 的预取逻辑
2. 或使用 `tools/data/prefetch_etf_cache.py` 预热 ETF 缓存
3. 避免短时间内重复请求同一标的

---

## 九、监控与日志

### 9.1 日志级别

- **INFO**：数据源切换、缓存命中
- **WARNING**：数据源失败、熔断触发
- **DEBUG**：详细的请求/响应信息

### 9.2 监控指标

`src/data/monitor.py` 中的 `record_fetch()` 记录：
- 数据源名称
- 成功/失败
- 耗时
- 是否使用备用源

---

## 十、最佳实践

### 10.1 日常使用

1. **定期预热缓存**（每天或每周）：
   ```bash
   python3 tools/data/prefetch_etf_cache.py --from-portfolio
   ```

2. **检查缓存状态**：
   ```bash
   ls -lh mycache/etf_kline/
   ls -lh mydate/backtest_kline/
   ```

3. **清理过期缓存**（可选）：
   ```bash
   # 删除 7 天前的缓存
   find mycache/etf_kline/ -name "*.csv" -mtime +7 -delete
   ```

### 10.2 网络不稳定时

1. **优先使用本地缓存**：
   - 确保 `etf_sources` 中 `local_cache` 在最前面
   - 定期预热缓存，避免依赖实时网络

2. **调整重试策略**：
   - 修改 `data_provider.py` 中的 `retries` 参数
   - 或在配置中增加超时时间

3. **使用离线模式**：
   - 仅使用本地缓存和 backtest_kline 数据
   - 适合回测和历史分析

---

## 十一、扩展新数据源

### 11.1 添加新适配器

1. 在 `src/data/provider/adapters.py` 中创建新类：

```python
class MyNewAdapter(KlineAdapter):
    @property
    def source_id(self) -> str:
        return "my_new_source"
    
    def get_kline(self, symbol: str, **kwargs) -> pd.DataFrame:
        # 实现数据获取逻辑
        # 返回标准格式：date, open, high, low, close, volume
        pass
```

2. 注册到 `KLINE_ADAPTER_REGISTRY`:

```python
KLINE_ADAPTER_REGISTRY = {
    ...
    "my_new_source": MyNewAdapter,
}
```

3. 在 `config/data_sources.yaml` 中配置：

```yaml
kline:
  sources: [my_new_source, sina, eastmoney, ...]
```

4. 在 `data_prefetch.py` 中添加熔断状态：

```python
_circuit_state = {
    ...
    "my_new_source": [0, 0.0],
}
```

---

## 十二、故障恢复清单

### 12.1 网络故障

- [ ] 检查网络连接
- [ ] 查看熔断日志
- [ ] 确认本地缓存是否可用
- [ ] 等待熔断恢复（5 分钟）或重启进程

### 12.2 数据源故障

- [ ] 检查数据源 API 是否正常（浏览器测试）
- [ ] 切换到备用数据源（修改配置）
- [ ] 使用本地缓存模式

### 12.3 ETF 特定问题

- [ ] 确认 ETF 代码格式正确
- [ ] 检查 `etf_sources` 配置顺序
- [ ] 确认本地缓存目录存在且有数据
- [ ] 尝试手动预热缓存

---

## 十三、总结

### 13.1 改进点

相比旧版本，新的数据获取流程有以下改进：

1. **统一接口**：所有数据获取通过 `UnifiedDataProvider`，代码更简洁
2. **自动切换**：主备数据源自动切换，无需手动干预
3. **熔断保护**：避免在失败的数据源上浪费时间
4. **本地缓存兜底**：网络不稳定时仍能正常分析
5. **股票/ETF 分离**：针对不同类型使用最优数据源
6. **多层容错**：UnifiedDataProvider + 旧版函数 + 本地缓存，三层保障

### 13.2 关键文件

| 文件 | 说明 |
|------|------|
| `src/data/provider/data_provider.py` | 统一数据提供层 |
| `src/data/provider/adapters.py` | 各数据源适配器 |
| `src/data/provider/base.py` | 适配器基类 |
| `src/data/fetchers/data_prefetch.py` | 底层数据获取与熔断逻辑 |
| `config/data_sources.yaml` | 数据源配置 |
| `tools/data/prefetch_etf_cache.py` | ETF 缓存预热工具 |

### 13.3 使用建议

1. **生产环境**：定期预热缓存，确保本地有最新数据
2. **开发环境**：使用默认配置即可，自动多源切换
3. **离线环境**：仅配置 `local_cache`，使用预先下载的数据
