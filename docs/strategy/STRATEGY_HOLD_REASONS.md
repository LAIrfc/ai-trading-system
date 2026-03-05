# 策略返回「观望/失败」常见原因说明

单股分析或回测时，部分策略会显示「观望」且理由为「无数据/获取失败/数据不足」。本文说明**实现方式**与常见原因。

---

## 1. NewsSentiment：无近期新闻或获取失败

### 实现方式（数据流）

- **策略层**：`src/strategies/news_sentiment.py`  
  - 先调 `get_news_sentiment_v33(symbol)`（24h 同向 N 篇、S_news、新闻源权重）；若为 `None` 再调旧版 `_get_news_sentiment_legacy(symbol)`（近期 N 篇情感均值）。  
  - 两者都为 `None` 时返回 HOLD，理由为「无近期新闻或获取失败」。

- **数据层**：`src/data/news/news_v33.py` → `src/data/news/news_fetcher.py` 的 `fetch_stock_news(symbol, max_items)`。  
  - **主**：`akshare.stock_news_em(symbol=symbol)`（东方财富个股新闻）。  
  - **备1**：东方财富搜索 API `search-api-web.eastmoney.com/search/jsonp`，keyword=股票代码。  
  - **备2**：财联社 `api.cls.cn/v1/information/list`，POST，**需环境变量 `CLS_API_KEY`**。  
  - **备3**：同花顺新闻，**需环境变量 `10JQKA_COOKIE`**。  
  任一成功即返回 DataFrame（title, content, date, source），再经情感打分、24h 窗口、同向篇数等算出 S_news；全部失败或返回空则上游得到空，最终显示「无近期新闻或获取失败」。

### 触发条件与常见原因

- **触发条件**：`_get_news_sentiment_v33(symbol)` 返回 `None`，且旧版 `_get_news_sentiment_legacy(symbol)` 也返回 `None`。

- **常见原因**：  
  - **网络/接口**：akshare、东方财富搜索、财联社、同花顺 全部超时或连接失败（与当前环境访问外网/东方财富受限有关）。  
  - **数据为空**：接口成功但该标的近期无新闻，或去重/24h 过滤后无有效条目。  
  - **环境**：未配置 `CLS_API_KEY` / `10JQKA_COOKIE` 时，只有 akshare + 东方财富两个源，任一失败就容易落到「无近期新闻」。

### 改进建议

- 配置 `CLS_API_KEY`、`10JQKA_COOKIE`，增加财联社/同花顺备用源。  
- 网络不稳时可对 `fetch_stock_news` 增加重试或适当放大超时。

---

## 2. PolicyEvent：无政策面数据或获取失败

### 实现方式（数据流）

- **策略层**：`src/strategies/policy_event.py`  
  - 先调 `get_policy_sentiment_v33(max_news)`（政策情感 + 是否重大利空 + 影响力）；若为 `None` 再调旧版 `_get_policy_legacy(max_news)`。  
  - 两者都为 `None` 时返回 HOLD，理由为「无政策面数据或获取失败」。

- **数据层**：`src/data/policy/policy_news.py` 的 `fetch_policy_news(max_items)`。  
  - **主**：政府官网（中国政府网 gov.cn 政策/要闻列表），requests + BeautifulSoup，需标题含「政策/国务院/宏观」等。  
  - **备1**：东方财富搜索 API，keyword=`"政策 降准 减税 央行 宏观"`。  
  - **备2**：财联社 `api.cls.cn/v1/information/list`，`category=policy`，**需 `CLS_API_KEY`**。  
  - **备3**：同花顺政策页 `data.10jqka.com.cn/policy/`，**需 `10JQKA_COOKIE`**。  
  取到列表后由 `policy_keywords.score_policy_text` / `has_major_negative` 等打分，聚合为情感与重大利空标志；全部失败或返回空则上游为 `None`，最终显示「无政策面数据或获取失败」。

### 触发条件与常见原因

- **触发条件**：V3.3 政策情感与旧版 `_get_policy_legacy()` 均返回 `None`。

- **常见原因**：  
  - **主/备用接口**：政府网、东方财富关键词、财联社 policy、同花顺政策 全部失败或返回空。  
  - **解析失败**：政府网/同花顺 HTML 改版，选择器失效。  
  - **环境**：未配置 `CLS_API_KEY` / `10JQKA_COOKIE` 时，仅政府网 + 东方财富，易空。

### 改进建议

- 配置财联社/同花顺后，政策面多两个备用源。  
- 政府网 URL 或选择器变化时，需更新 `policy_news._fetch_policy_via_gov`。

---

## 3. MoneyFlow：龙虎榜/大宗接口异常且无有效缓存

**触发条件**：`_get_money_flow_signal(symbol)` 中龙虎榜+大宗均无信号（返回 `None`），且拉取过程异常或无数据，且近 7 日缓存也没有该标的的历史信号。

**常见原因**：
- **该标的近期无龙虎榜/大宗**：600118 若近期未上龙虎榜、无大宗成交，则正常无信号。
- **接口失败**：akshare 龙虎榜/大宗、同花顺(10JQKA_COOKIE)、东方财富大宗 请求超时或解析失败。
- **缓存为空**：首次分析该标的且接口失败时，7 日缓存无数据。

**改进建议**：
- 龙虎榜/大宗本身是「事件型」数据，很多股票长期无记录，显示观望是合理行为。
- 若需提高成功率，可配置 `10JQKA_COOKIE` 启用同花顺龙虎榜备用。

---

## 4. PE：PE数据不足(需793条，实际61条)

**触发条件**：PE 策略在 `analyze()` 内对 `df['pe_ttm']` 做 `dropna()` 后，再过滤为 `0 < pe_ttm <= 100`，得到序列长度 `< self.min_bars`。

**原因说明**：
- 日线合并后，`pe_ttm` 非空约有 793 条（ffill 后），故单股分析里把 `min_bars` 设为 793。
- PE 策略会**剔除 PE>100**（视为异常/极高估值），中国卫星 PE(TTM) 约 1893，历史中大量日期 PE>100，过滤后只剩 61 条，小于 793，因此报「需793条，实际61条」。

**改进建议**：
- 对高估值/亏损股放宽 PE 上限或单独分支（例如 PE>100 时只做「高估」提示而不要求 min_bars）。
- 或在单股分析里，将 PE 的 `min_bars` 设为 `min(rolling_window, 实际有效PE条数)`，避免要求「全区间有效」导致高 PE 股永远不足。

---

## 5. PB：PB数据不足(需793条，实际789条) 或 PB中性

**情况 A——数据不足**：与 PE 类似，`min_bars` 被设为 793（来自 `df['pb'].notna().sum()`），但 PB 策略会过滤 `0 < pb <= 20`，过滤后若为 789 条，则差 4 条不满足 793，从而报「需793条，实际789条」。

**情况 B——PB中性**：若有效条数足够，则按分位数判断；分位数处于中性区间（未达买入/卖出阈值）时，会返回「PB中性(分位xx%，当前PB=xx)」，这是正常信号而非失败。

**改进建议**：
- 单股分析里，PB 的 `min_bars` 不要用「全表非空数量」，而用「过滤后有效条数」与 `rolling_window` 的较小值，例如：  
  `min_bars = min(rolling_window, len(df[(df['pb']>0) & (df['pb']<=20)].dropna()))`，这样 789 条即可通过。
- 若希望 PB 在「数据基本满足但差几条」时也能运行，可将 `min_bars` 设为略小于有效条数（例如 700），仅用于单股展示。

---

## 小结

| 策略         | 主要原因                         | 可做改进 |
|--------------|----------------------------------|----------|
| NewsSentiment | 接口失败/无新闻/未配置备用       | 配置 CLS/同花顺、加强重试 |
| PolicyEvent   | 政策接口全失败或解析空           | 配置备用、检查政府网解析 |
| MoneyFlow     | 该股无近期龙虎榜/大宗或接口失败  | 属正常；可配同花顺备用 |
| PE            | 高 PE 被过滤(>100) 后有效条数不足 | 放宽 PE 上限或降低 min_bars 要求 |
| PB            | min_bars 与过滤后条数不一致或中性 | 用过滤后条数设 min_bars；中性为正常 |

上述逻辑在 `src/strategies/` 与 `tools/analysis/analyze_single_stock.py` 中，按需可对 PE/PB 的 min_bars 和 PE 的过滤上限做小范围修改。
