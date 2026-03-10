# 数据接口与容错获取规范

> 所有接口均为公开可调用（部分需注册获取密钥），优先匹配「主数据源 + 备用数据源」逻辑，可直接用于 Python 开发（如 `src/data/fetchers/data_prefetch.py`）。

---

## 〇、策略视角：各策略所需指标、接口与实现

各策略需要哪些指标、用了哪些接口、数据层与策略层如何对应。

### 各策略需要的指标/数据

| 策略 | 需要的指标/数据 |
|------|------------------|
| **MA** | 日线：open, high, low, close, volume（均线、乖离、量比） |
| **MACD** | 同上（close 算 DIF/DEA/柱） |
| **RSI** | 同上（close 算 RSI） |
| **BOLL** | 同上（close 算布林带） |
| **KDJ** | 同上（high, low, close 算 KDJ） |
| **DUAL** | 同上（动量/相对强度） |
| **PE** | 日线 + **PE 序列**（历史分位数）；可选 ROE/行业（baostock/akshare） |
| **PB** | 日线 + **PB 序列**（同上） |
| **Sentiment** | 日线(close/high/low 做趋势过滤) + **市场情绪指数 S、S_low、S_high**（多指标合成） |
| **NewsSentiment** | 日线(close 做预期差) + **个股新闻情感 S_news、篇数 N、来源权重** |
| **PolicyEvent** | **政策情感、是否重大利空、影响力** + 情绪 S_high + 指数涨跌幅(如沪深300) |
| **MoneyFlow** | **龙虎榜**（席位、净买/卖、占比）+ **大宗**（折价、买卖方、金额） |

归纳：技术 6 个 + DUAL 只需**个股日线**（OHLCV）；PE/PB 需日线 + **基本面 PE/PB/市值**；Sentiment 需日线 + **市场情绪指数**；NewsSentiment 需日线 + **个股新闻情感**；PolicyEvent 需**政策事件情感** + 情绪 + 指数；MoneyFlow 需**龙虎榜 + 大宗**。

### 按数据类型用的接口（主→备顺序）

| 数据类型 | 主→备顺序 | 接口 |
|----------|-----------|------|
| **个股日线 K 线** | 主→备1→备2→备3 | **Sina**（money.finance.sina getKLineData）→ **东方财富/akshare**（stock_zh_a_hist）→ **腾讯**（web.ifzq.gtimg.cn kline）→ **tushare**（pro.daily，config/TUSHARE_TOKEN） |
| **情绪指数** | 主→备→备2 | **akshare**（指数/截面）→ **tushare**（index_daily 等）→ **JoinQuant**（jqdatasdk 指数） |
| **个股新闻** | 主→备1→备2→备3 | **akshare**（stock_news_em）→ **东方财富搜索**（push2）→ **财联社**（CLS_API_KEY）→ **同花顺**（10JQKA_COOKIE） |
| **政策事件** | 主→备 | **政府网/发改委/央行**（爬虫）→ **财联社/同花顺** 政策 |
| **龙虎榜** | 主→备 | **akshare/东方财富** 龙虎榜 → **同花顺**（10JQKA_COOKIE） |
| **大宗交易** | 东方财富等 | 东方财富大宗接口 |
| **PE/PB/市值/ROE** | 主→备 | **baostock**（日 K 基本面、行业）→ **akshare**（财务指标等） |
| **指数日线**（沪深300 等） | 主→备→备2 | **akshare** → **tushare** → **JoinQuant** |

### 实现方式（数据层 → 策略层）

- **日线**：`data_prefetch.fetch_stock_daily()`，Sina → 东方财富(akshare) → 腾讯 → tushare；回测用 `load_kline_for_backtest()`，优先 `--local-kline` 下 parquet。
- **情绪**：`src/data/sentiment/sentiment_index` 合成 S/S_low/S_high；`SentimentStrategy` 用该序列 + 个股日线做趋势过滤。
- **新闻**：`src/data/news/news_fetcher`（akshare → 东方财富 → 财联社 → 同花顺）；`NewsSentimentStrategy` 调 `get_news_sentiment_v33(symbol)`。
- **政策**：`src/data/policy/policy_news`；`PolicyEventStrategy` 调 `get_policy_sentiment_v33()`，结合情绪 S_high、指数涨幅。
- **龙虎榜/大宗**：`src/data/money_flow/lhb`、`dzjy`；`MoneyFlowStrategy` 调 `get_lhb_signal`/`get_dzjy_signal`。
- **PE/PB**：`FundamentalFetcher`（baostock 为主，akshare 备用）；`PEStrategy`/`PBStrategy` 在回测里 merge 基本面到日线后算分位数。
- **回测本地化**：日线用 `--local-kline` + `backtest_prefetch.py`；新闻/政策/龙虎榜用 `BACKTEST_PREFETCH_DIR` + `backtest_prefetch_aux.py`。

### 统一数据接入层（DataProvider）

日线已抽象为 **DataProvider + 适配器**，策略/回测/采集器只调统一接口，换源或调主备仅改配置：

- **接口**：`get_default_kline_provider().get_kline(symbol, start_date=..., end_date=..., datalen=...)`，返回统一 schema：`date, open, high, low, close, volume`（及可选 `data_source`、`fetched_at`）。
- **适配器**：`SinaKlineAdapter`、`EastMoneyKlineAdapter`、`TencentKlineAdapter`、`TushareKlineAdapter`（见 `src/data/provider/adapters.py`），各封装单一数据源。
- **配置**：`config/data_sources.yaml` 的 `kline.sources: [sina, eastmoney, tencent, tushare]`，或 `config/trading_config.yaml` 的 `data.kline_sources`。调整顺序即调整主备，无需改策略代码。
- **调用方**：`data_prefetch.fetch_stock_daily`、`RealtimeDataFetcher.get_historical_data`（日线）、`AkShareCollector.get_daily_bars`、`TushareCollector.get_daily_bars` 均经 DataProvider 获取日线。

---

## 一、各类策略具体接口明细

### 1.1 基础数据接口（对应 fetch_sina / 指数日线）

#### 1.1.1 主数据源：Sina 财经接口（fetch_sina）

| 项目 | 说明 |
|------|------|
| **接口用途** | 获取个股实时行情、日线数据（适配「fetch_sina 接口异常」场景） |
| **请求地址** | `http://hq.sinajs.cn/list=sh600000,sz000001`（多标的逗号分隔；sh=沪市，sz=深市） |
| **请求方式** | GET（无需密钥） |
| **核心参数** | `list=标的代码`（如 sh600000=浦发银行） |
| **返回格式** | JavaScript 字符串，可拆分提取开盘价、收盘价、成交量等 |
| **日线 K 线** | 日线历史另用：`https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData`，params: `symbol`, `scale=240`, `ma=no`, `datalen` |
| **调用注意** | 添加 `timeout=10`，捕获 `ConnectionError`/`TimeoutError`，异常时切换备用接口 |

#### 1.1.2 备用数据源 1：东方财富 API

| 项目 | 说明 |
|------|------|
| **接口用途** | 替代 Sina，获取个股/指数行情、日线数据 |
| **请求地址** | `https://push2.eastmoney.com/api/qt/stock/get` |
| **请求方式** | GET（无需密钥） |
| **核心参数** | `secid=0.000001`（0=深市，1=沪市，后接标的代码）；`fields=f43,f57,f58,f60,f169`（开盘、收盘、成交量、换手率等） |
| **返回格式** | JSON，解析 `data` 字段 |
| **日线** | 可通过 akshare `stock_zh_a_hist(symbol, period="daily", start_date, end_date)` 间接使用东方财富源 |

#### 1.1.3 备用数据源 2：腾讯财经 API

| 项目 | 说明 |
|------|------|
| **接口用途** | 备用获取个股行情，适配 Sina/东方财富双异常场景 |
| **请求地址** | `https://qt.gtimg.cn/q=sh600000,sz000001` |
| **请求方式** | GET（无需密钥） |
| **核心参数** | `q=标的代码`（多标的逗号分隔） |
| **返回格式** | JavaScript 字符串，按固定分隔符拆分 |
| **日线** | `https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={symbol},day,,,{datalen}&_var=kline_day&r=0.{ts}` |

---

### 1.2 情绪因子策略接口（对应 Sentiment 策略）

#### 1.2.1 主数据源：akshare

| 项目 | 说明 |
|------|------|
| **接口用途** | 情绪指数所需 6 大指标（涨跌家数比、换手率等） |
| **安装** | `pip install akshare`（Python 3.7+） |
| **示例** | `ak.market_zh_a_spot()`（涨跌家数）；`ak.index_zh_a_daily(symbol="000300")`（沪深300日线/换手率）；`ak.stock_margin_trade_summary(symbol="sh")`（融资买入） |
| **注意** | 添加 `timeout=15`，异常时切换 tushare/JoinQuant |

#### 1.2.2 备用数据源 1：tushare

| 项目 | 说明 |
|------|------|
| **接口用途** | 替代 akshare，获取情绪因子指标 |
| **准备** | 注册 https://tushare.pro/ 获取 token |
| **示例** | `pro.daily_basic(trade_date=...)`（涨跌家数）；`pro.opt_daily(...)`（期权 PCR）；`pro.index_daily(ts_code='399300.SZ')`（指数、HV20） |

#### 1.2.3 备用数据源 2：JoinQuant

| 项目 | 说明 |
|------|------|
| **接口用途** | akshare/tushare 双异常时，获取期权 PCR、波动率等 |
| **准备** | 注册 https://www.joinquant.com/ 开通 API |
| **注意** | 本地运行可能受限，建议作为备选或通过研究环境导出数据 |

---

### 1.3 消息面策略接口（News Sentiment / Money Flow）

#### 1.3.1 个股新闻情感

| 数据源 | 地址/方式 | 说明 |
|--------|-----------|------|
| **主：财联社** | `https://api.cls.cn/v1/information/list`，POST，需 APIKey | `keyword=个股名/代码`，`type=news`，`page`/`page_size`；情感得分缺失时可标题关键词简易打分 |
| **备1：同花顺** | `https://news.10jqka.com.cn/tapp/news/get_news_list`，GET，需 cookie | `code=600519`，`page`，`size`，`type=0`（0=新闻，1=公告） |
| **备2：东方财富** | `https://push2.eastmoney.com/api/qt/ulist.np/get`，GET | `secid=1.600519`（1=沪 0=深），`fields=f1,f2,f3,f12,f13,f14,f15,f16` |

#### 1.3.2 龙虎榜 / 大宗交易

| 数据源 | 地址/方式 | 说明 |
|--------|-----------|------|
| **主：东方财富龙虎榜** | `https://push2.eastmoney.com/api/qt/clist/get`，GET | `fid=f62`，`po=1,pz=50,pn=1,np=1`，`fields=f12,f14,f2,f3,f18,f20,f21,f23,f24,f25,f26`（席位、成交额等） |
| **备1：同花顺龙虎榜** | `https://data.10jqka.com.cn/lhb/ggcx/`，GET，需 cookie | `date=yyyy-mm-dd`，`page=1`；返回 HTML，BeautifulSoup 解析 |
| **大宗：交易所** | 上交所/深交所 disclosure 页面，GET，HTML 解析 | 可能反爬/动态加载，失败可切东方财富大宗接口 |

---

### 1.4 政策面策略接口（Policy Event）

| 数据源 | 说明 |
|--------|------|
| **主：政府官网** | 中国政府网/发改委/央行政策库，requests + BeautifulSoup，需 headers 模拟浏览器 |
| **备1：财联社政策** | `https://api.cls.cn/v1/information/list`，POST，`category=policy` |
| **备2：同花顺政策** | `https://data.10jqka.com.cn/policy/`，GET，cookie，`type=1/2/3`（国家/部委/地方） |

---

## 二、逐类接口分析与建议

### 2.1 基础数据（Sina / 东方财富 / 腾讯）

- **可行性**：新浪接口仍可用；东方财富最稳定；腾讯偶有变动。三者互补。
- **建议**：维护「市场代码映射表」（600/601/603→沪市 1；000/002/300→深市 0）；腾讯放最后并做健康检查（连续 3 天失败可暂时移除并告警）；缺失字段用 NaN 填充并统一标准化。
- **统一封装**：`fetch_stock_base(symbol)` 按「东方财富→Sina→腾讯」或「Sina→东方财富→腾讯」优先级尝试，返回标准化字典（open, close, volume, turnover 等）；回测预取全量日线存本地 CSV/Parquet；实盘可加熔断（连续失败 3 次禁用 30 分钟）。

### 2.2 情绪因子（akshare / tushare / JoinQuant）

- **可行性**：akshare 便捷但依赖上游；tushare 需 token 与积分限制；JoinQuant 质量高但学习成本高。
- **建议**：每指标独立函数 + 失败自动降级 tushare；tushare 预取时限流（如 time.sleep）并用批量接口；JoinQuant 作备选或预导数据；期权 PCR 缺失时可权重置 0 或用认沽/认购成交额比替代。
- **回测**：预取全量历史到本地，回测时读本地。

### 2.3 消息面（财联社 / 同花顺 / 东方财富）

- **建议**：财联社免费版限次，可仅对重点股实时拉取；同花顺需 cookie 维护，作最后备选；东方财富解析时固定字段索引；新闻去重（标题 SimHash/编辑距离 + 时间 5 分钟内）。回测建议用预置新闻数据集或盘后增量入库，盘中读库。

### 2.4 龙虎榜 / 大宗

- **建议**：东方财富为主；席位名称需映射表；同花顺 HTML 多备选 XPath；交易所爬取控制频率+代理。大宗 T+1 披露，建议收盘后 17:00 统一抓取，次日使用。

### 2.5 政策面

- **建议**：政府站模块化解析+监控，失败切财联社；政策利好/利空采用「规则+人工复核」；定期爬取（如 22:00）+ 代理与随机延迟。

---

## 三、整合到容错机制中的关键点

### 3.1 统一数据获取层（DataFetcher）

- **主备切换**：按可配置优先级尝试，失败自动下一备用。
- **超时**：统一如 `timeout=10`（行情）/ `15`（情绪）。
- **重试**：指数退避（1s、2s、4s），最大次数可配置。
- **熔断**：连续失败 N 次（如 3）则禁用 T 秒（如 300），半开启再试。
- **日志**：记录接口、耗时、状态、失败原因；数据加时间戳与源标识。

### 3.2 回测与实盘分离

- **回测**：数据预取存本地（CSV/Parquet/SQLite），策略通过 `BACKTEST_MODE=True` 从本地读，不走网络。
- **实盘**：完整网络请求 + 缓存 + 熔断；盘前更新情绪/政策等，盘中尽量用缓存；记录接口调用日志。

### 3.3 缓存策略

- **层级**：内存（单次运行）→ 本地文件（跨日）→ 可选分布式。
- **失效**：日频数据至次日 0 点；实时行情可 5 分钟。
- **键**：含 `data_type`、`source`、`symbol`、`date_range`、`params_hash`；定期清理过期缓存。

### 3.4 异常与监控

- **日志**：主失败备成功→WARNING；全部失败→ERROR；数据缺失导致 HOLD→INFO。
- **监控**：各接口成功率、耗时、备用触发占比、缓存命中率、数据延迟、缓存使用率。
- **告警**：关键接口连续失败超过阈值（如 3 次）邮件/钉钉告警。

---

## 四、落地实施步骤

1. **第一阶段**：验证各接口可用性，封装基础获取函数，实现主备切换与标准化输出，编写单接口/组合测试脚本。
2. **第二阶段**：回测数据准备——优先 tushare 等批量下载，清洗复权/停牌/缺失值，统一格式；历史至少 3 年存 Parquet/SQLite；策略增加 `BACKTEST_MODE`，回测时读本地；预取脚本可配置定期自动运行。
3. **第三阶段**：实盘集成——DataFetcher 实现缓存与熔断，配置日志与告警；小规模实盘 1–2 周观察稳定性。
4. **第四阶段**：持续维护——定期检查接口变更，监控数据质量，优化缓存与熔断参数。

---

## 五、合规与成本

- 免费接口注意使用条款（如东方财富禁止商用）；政府站遵守 robots.txt、控制频率。
- 成本大致：免费接口 0 元（维护成本高）；tushare 积分制；财联社可有免费额度；专业数据商（如 Wind）适合机构。

---

## 六、与本项目代码的对应关系

| 文档模块 | 项目位置 |
|----------|----------|
| 统一日线 DataProvider | `src/data/provider/`（`base.py`、`adapters.py`、`data_provider.py`）；`fetch_stock_daily` 内部调用 `get_default_kline_provider().get_kline()` |
| 基础日线 fetch_sina | `tools/backtest/batch_backtest.py` 中 `fetch_sina`；`src/data/fetchers/data_prefetch.py` 统一封装（经 DataProvider） |
| 情绪指数 | `src/data/sentiment/sentiment_index.py`（akshare + tushare 备用） |
| 新闻/政策/龙虎榜 | `src/data/news/`、`src/data/policy/`、`src/data/money_flow/`；策略内 try/except + 备用 + 回测预取占位 |
| 回测预取与 BACKTEST_MODE | `src/strategies/base.py` 中 `_BACKTEST_ACTIVE`；各策略 `prepare_backtest` 与预取缓存 |
| 回测日线本地预取 | `tools/data/backtest_prefetch.py`；`batch_backtest.py --local-kline` 读本地 Parquet |

---

## 七、回测数据预取流程（两步走）

与第四阶段「回测数据准备」一致：先预取日线落盘，再回测时优先读本地，避免重复网络请求。

### 步骤 1：预取日线到本地 Parquet

```bash
# 从股票池预取 50 只，每只 800 条日线，写入 mydate/backtest_kline/
python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool.json --count 50 --datalen 800

# 指定输出目录与并发
python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool.json --count 100 --out-dir mydate/backtest_kline --workers 4
```

- 输出：`{out-dir}/{code}.parquet`，每只标的一个文件。
- 数据源：主 Sina → 备东方财富(akshare) → 备腾讯（与 `data_prefetch.fetch_stock_daily` 一致）。

### 步骤 2：回测时使用本地 K 线

```bash
# 优先读 mydate/backtest_kline/，缺失的标的再走网络
python3 tools/backtest/batch_backtest.py --pool mydate/stock_pool.json --count 50 --local-kline mydate/backtest_kline

# 或绝对路径
python3 tools/backtest/batch_backtest.py --local-kline /path/to/backtest_kline --v33 --count 20
```

- `--local-kline` 未指定或目录下无对应 `{code}.parquet` 时，仍调用 `fetch_sina`（网络）获取该标的。
- 建议：先跑预取脚本再跑回测，可显著减少回测时的网络请求与耗时。

### 预取自动化与过期检查

- **过期检查**：使用 `--check DAYS` 仅检查本地 Parquet 是否在 DAYS 天内更新（按文件 mtime），不拉取数据。缺失或过期的标的会打印并退出码 1，便于脚本或 cron 判断是否需要重跑预取。
  ```bash
  python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool.json --out-dir mydate/backtest_kline --check 7
  ```
- **自动化建议**：可配置 cron 定期执行预取（如每周或每月），再跑回测；或先执行 `--check 7`，若退出码非 0 再执行预取。

---

## 八、K 线数据源配置与熔断机制

### 8.1 数据源配置（`config/data_sources.yaml`）

```yaml
kline:
  sources: [sina, eastmoney, tencent, tushare]          # 股票数据源顺序
  etf_sources: [local_cache, akshare_etf, push2his_etf, baostock_etf]  # ETF 数据源顺序
```

| 数据源 | 适配器类 | 说明 | 优先级 |
|--------|----------|------|--------|
| sina | SinaKlineAdapter | 新浪财经，速度快 | 1（主） |
| eastmoney | EastMoneyKlineAdapter | 东方财富 akshare | 2 |
| tencent | TencentKlineAdapter | 腾讯财经 | 3 |
| tushare | TushareKlineAdapter | tushare（需 token） | 4 |
| local_cache | LocalCacheAdapter | 本地缓存（ETF 最高优先） | 1（ETF） |
| akshare_etf | AkshareETFAdapter | akshare 三源轮询（新浪→网易→东方财富） | 2（ETF） |
| push2his_etf | Push2hisETFAdapter | 东方财富 push2his 直接接口 | 3（ETF） |
| baostock_etf | BaostockETFAdapter | baostock ETF（部分支持） | 4（ETF） |

### 8.2 熔断机制

- **触发条件**：数据源连续失败 3 次
- **熔断时长**：300 秒（5 分钟）；`local_cache` 不受熔断限制
- **腾讯特殊规则**：连续 3 个自然日失败则暂时移除并触发 `TENCENT_3DAY_ALERT_CALLBACK`
- **内存缓存**：同一标的 5 分钟内重复请求直接返回缓存（key: `(code, datalen)`）

熔断状态位于 `src/data/fetchers/data_prefetch.py`：

```python
_circuit_state = {
    "sina": [0, 0.0],       # [连续失败次数, 最后失败时间戳]
    "eastmoney": [0, 0.0],
    "tencent": [0, 0.0],
    "tushare": [0, 0.0],
    "akshare_etf": [0, 0.0],
    "push2his_etf": [0, 0.0],
    "baostock_etf": [0, 0.0],
    "local_cache": [0, 0.0],
}
```

### 8.3 本地缓存目录

| 目录 | 用途 | 格式 |
|------|------|------|
| `mycache/etf_kline/` | ETF 日线缓存 | `{code}_{YYYYMMDD}.csv` |
| `mydate/backtest_kline/` | 回测数据缓存 | `{code}.parquet` |
| `mycache/market_data/` | MarketData 自动缓存 | `{code}_{days}_{YYYYMMDD}.csv` |

缓存有效期：交易时间内（9:00-16:00）1 小时；非交易时间 12 小时。

### 8.4 故障排查

**所有数据源均失败**：检查网络 → 查看熔断状态 → 确认本地缓存 → 等待 5 分钟或重启进程。

**ETF 数据获取失败**：确认代码格式（6 位，5/159 开头）→ 检查 `mycache/etf_kline/{code}_*.csv` → 手动预热：
```bash
python3 tools/data/prefetch_etf_cache.py --from-portfolio
python3 tools/data/prefetch_etf_cache.py --codes 512480,159770,510300
```

### 8.5 扩展新数据源

1. 在 `src/data/provider/adapters.py` 中创建适配器类（继承 `KlineAdapter`）
2. 注册到 `KLINE_ADAPTER_REGISTRY`
3. 在 `config/data_sources.yaml` 的 `kline.sources` 中配置
4. 在 `data_prefetch.py` 的 `_circuit_state` 中添加熔断状态

---

## 九、文档与实现差异（待办）

以下为文档一～五中已规划、当前代码尚未完全落地的部分，便于按优先级补齐。

| 文档章节 | 内容 | 当前状态 | 建议 |
|----------|------|----------|------|
| **1.2 情绪** | 6 大指标独立函数：涨跌家数比、换手率、融资买入、期权 PCR、新高新低比、波动率；主 akshare → 备 tushare → 备2 JoinQuant | **已实现**：`get_advance_decline_ratio_series`、`get_turnover_rate_series`、`get_margin_buy_ratio_series`、`get_option_pcr_series`、`get_new_high_low_ratio_series`、`get_volatility_index_series`；`get_sentiment_series_v2` 用 6 指标合成，缺项权重 0 | 期权 PCR 依赖 akshare 期权接口，缺则自动置 0 |
| **1.3.1 新闻** | 主 财联社 api.cls.cn（需 APIKey）；备1 同花顺 get_news_list（需 cookie）；备2 东方财富 | **已实现**：主 akshare → 东方财富 search → 财联社（CLS_API_KEY）→ 同花顺（10JQKA_COOKIE）；`_fetch_via_cls` / `_fetch_via_10jqka` 环境变量启用 | 有 key/cookie 时自动启用备用 |
| **1.3.2 龙虎榜** | 备1 同花顺 data.10jqka.com.cn/lhb/ggcx/ HTML 解析 | **已实现**：akshare 失败/无数据时调用 `_fetch_lhb_10jqka`（需 10JQKA_COOKIE） | 列表与个股明细接口区分见 data_prefetch.fetch_eastmoney_lhb |
| **1.3.2 大宗** | 交易所 disclosure；失败切东方财富大宗 | **已实现**：akshare 失败/无数据时调用 `_fetch_dzjy_eastmoney`（push2 clist） | 交易所 disclosure 可选 |
| **1.4 政策** | 主 政府官网；备1 财联社 category=policy；备2 同花顺 | **已实现**：主 `_fetch_policy_via_gov`（政府网简单版）→ 东方财富 → 财联社 → 同花顺 | 政府网可扩展更多栏目 |
| **2.1 基础** | 腾讯连续 3 天失败可暂时移除并告警 | **已实现**：`_tencent_fail_dates` 按自然日记录，`_tencent_allow_by_3day()` 跳过并触发 `TENCENT_3DAY_ALERT_CALLBACK` | 告警回调由调用方注册 |
| **2.3 消息** | 新闻去重（5 分钟时间窗）；回测预置新闻数据集 | **已实现**：`dedup_news(..., time_window_minutes=5)`；`backtest_prefetch_aux.py` + `BACKTEST_PREFETCH_DIR` + `--local-aux` | 新闻/政策/龙虎榜回测读本地 Parquet |
| **3.3 缓存** | 键含 data_type/source/symbol/date_range/params_hash；本地文件缓存；定期清理过期 | **已实现**：`src/data/cache_utils.py`（`_make_key`、`get_cached`/`set_cached`、`clear_expired_file_cache`、`CACHE_ROOT`） | 可按需接入各 fetch |
| **3.4 监控告警** | 成功率、耗时、备用触发占比；连续失败邮件/钉钉告警 | **已实现**：`src/data/monitor.py`（`record_fetch`、`get_stats`、`ALERT_CALLBACK`、`send_alert_dingding`/`send_alert_email`）；data_prefetch 已埋点 | 配置 DINGDING_WEBHOOK 或 SMTP_* 启用 |
| **3.1 数据标识** | 数据加时间戳与源标识 | **已实现**：`_tag_df_source(df, source)` 为日线添加 `data_source`、`fetched_at` 列 | 日线返回已带标识 |
