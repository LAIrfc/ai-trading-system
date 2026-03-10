# 数据接口层架构设计

## 📋 目录
- [架构概览](#架构概览)
- [设计原则](#设计原则)
- [分层架构](#分层架构)
- [接口抽象](#接口抽象)
- [使用示例](#使用示例)
- [扩展指南](#扩展指南)

---

## 🏗️ 架构概览

我们的系统已经实现了**完整的数据接口层抽象**，策略层与数据源完全解耦：

```
┌─────────────────────────────────────────────────────────────┐
│                    策略层 (Strategies)                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ MA策略   │  │ MACD策略 │  │  PE策略  │  │ 组合策略 │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
└───────┼─────────────┼─────────────┼─────────────┼──────────┘
        │             │             │             │
        └─────────────┴─────────────┴─────────────┘
                      │
        ┌─────────────▼─────────────────────────────────────┐
        │         统一数据接口层 (Provider Layer)            │
        │  ┌─────────────────────────────────────────────┐  │
        │  │  UnifiedDataProvider (统一数据提供者)       │  │
        │  │  - get_kline()      # K线数据               │  │
        │  │  - get_realtime()   # 实时行情               │  │
        │  │  - get_fundamental()# 基本面数据             │  │
        │  └─────────────────────────────────────────────┘  │
        └───────────────────────┬───────────────────────────┘
                                │
        ┌───────────────────────┴───────────────────────────┐
        │           适配器层 (Adapter Layer)                 │
        │  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
        │  │  Sina    │  │EastMoney │  │ Tencent  │       │
        │  │ Adapter  │  │ Adapter  │  │ Adapter  │       │
        │  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
        │  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐       │
        │  │ Tushare  │  │ Akshare  │  │ Baostock │       │
        │  │ Adapter  │  │ Adapter  │  │ Adapter  │       │
        │  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
        │  ┌────┴─────┐  ┌────┴─────┐                      │
        │  │LocalCache│  │Push2his  │                      │
        │  │ Adapter  │  │ETFAdapter│                      │
        │  └────┬─────┘  └────┬─────┘                      │
        └───────┼─────────────┼────────────────────────────┘
                │             │
        ┌───────▼─────────────▼───────────────────────────┐
        │          底层数据源 (Data Sources)               │
        │  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
        │  │新浪财经  │  │东方财富  │  │腾讯财经  │      │
        │  └──────────┘  └──────────┘  └──────────┘      │
        │  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
        │  │ Tushare  │  │ Akshare  │  │ Baostock │      │
        │  └──────────┘  └──────────┘  └──────────┘      │
        │  ┌──────────┐                                    │
        │  │本地缓存  │                                    │
        │  └──────────┘                                    │
        └─────────────────────────────────────────────────┘
```

---

## 🎯 设计原则

### 1. **单一职责原则 (SRP)**
- **策略层**：只关心交易逻辑，不关心数据来源
- **Provider层**：提供统一接口，管理数据源切换
- **Adapter层**：适配不同数据源的API差异
- **Fetcher层**：封装底层HTTP请求和数据解析

### 2. **开闭原则 (OCP)**
- 新增数据源：只需添加新Adapter，无需修改策略代码
- 修改数据源优先级：只需修改配置文件
- 扩展数据类型：在Provider层添加新方法

### 3. **依赖倒置原则 (DIP)**
- 策略依赖抽象接口（UnifiedDataProvider）
- 不依赖具体数据源实现（Sina/EastMoney）

### 4. **接口隔离原则 (ISP)**
- KlineAdapter：专注K线数据
- FundamentalFetcher：专注基本面数据
- RealtimeDataFetcher：专注实时行情

---

## 📚 分层架构

### 第一层：策略层 (Strategy Layer)
**位置**: `src/strategies/`

**职责**: 
- 实现交易逻辑
- 调用统一数据接口
- 返回标准化信号

**示例**:
```python
# src/strategies/ma_cross.py
from .base import Strategy, StrategySignal

class MACrossStrategy(Strategy):
    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        # df 由外部传入，策略不关心数据来源
        ma5 = df['close'].rolling(5).mean()
        ma20 = df['close'].rolling(20).mean()
        
        if ma5.iloc[-1] > ma20.iloc[-1]:
            return StrategySignal(action='BUY', confidence=0.8, ...)
        else:
            return StrategySignal(action='SELL', confidence=0.7, ...)
```

**特点**:
- ✅ **不直接导入** akshare/baostock/tushare
- ✅ **不调用** 具体的数据获取函数
- ✅ **只接收** 标准化的DataFrame
- ✅ **只返回** 标准化的Signal

---

### 第二层：统一接口层 (Provider Layer)
**位置**: `src/data/provider/`

**核心类**: `UnifiedDataProvider`

**职责**:
- 提供统一的数据获取接口
- 管理多数据源fallback
- 实现熔断机制
- 数据格式标准化

**接口定义**:
```python
# src/data/provider/data_provider.py
class UnifiedDataProvider:
    def get_kline(
        self, 
        symbol: str, 
        start_date: str = None,
        end_date: str = None,
        datalen: int = None,
        is_etf: bool = None
    ) -> pd.DataFrame:
        """
        获取K线数据（统一接口）
        
        Returns:
            DataFrame with columns: [date, open, high, low, close, volume, amount]
        """
        # 自动选择数据源，fallback机制
        for adapter in self._adapters:
            try:
                df = adapter.fetch(symbol, start_date, end_date)
                if df is not None and len(df) > 0:
                    return df
            except Exception as e:
                logger.warning(f"{adapter.name} failed: {e}")
                continue
        
        return pd.DataFrame()  # 所有源都失败
```

**配置驱动**:
```yaml
# config/data_sources.yaml
kline:
  sources:  # 股票数据源优先级
    - sina
    - eastmoney
    - tencent
    - tushare
    - baostock
  
  etf_sources:  # ETF数据源优先级
    - local_cache
    - akshare_etf
    - push2his_etf
    - baostock_etf
```

---

### 第三层：适配器层 (Adapter Layer)
**位置**: `src/data/provider/adapters.py`

**基类**: `KlineAdapter`

**职责**:
- 适配不同数据源的API
- 统一返回格式
- 处理异常和重试

**适配器注册表**:
```python
# src/data/provider/adapters.py
KLINE_ADAPTER_REGISTRY = {
    'sina': SinaKlineAdapter(),
    'eastmoney': EastMoneyKlineAdapter(),
    'tencent': TencentKlineAdapter(),
    'tushare': TushareKlineAdapter(),
    'baostock': BaostockKlineAdapter(),
    'akshare_etf': AkshareETFAdapter(),
    'push2his_etf': Push2hisETFAdapter(),
    'local_cache': LocalCacheAdapter(),
}
```

**适配器实现示例**:
```python
class SinaKlineAdapter(KlineAdapter):
    name = 'sina'
    
    def fetch(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        # 1. 调用新浪API
        url = f'http://hq.sinajs.cn/list={self._format_symbol(symbol)}'
        resp = requests.get(url, timeout=10)
        
        # 2. 解析数据
        data = self._parse_sina_response(resp.text)
        
        # 3. 转换为标准格式
        df = pd.DataFrame(data)
        df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount']]
        
        return df
```

---

### 第四层：数据获取层 (Fetcher Layer)
**位置**: `src/data/fetchers/`

**核心类**:
- `FundamentalFetcher`: 基本面数据（PE/PB/ROE）
- `RealtimeDataFetcher`: 实时行情
- `ETFDataFetcher`: ETF专用数据
- `MarketData`: 市场数据采集

**职责**:
- 封装底层HTTP请求
- 数据解析和清洗
- 缓存管理
- 错误处理

**示例**:
```python
# src/data/fetchers/fundamental_fetcher.py
class FundamentalFetcher:
    def get_pe_pb_data(self, code: str) -> dict:
        """
        获取PE/PB数据（多数据源fallback）
        
        优先级: baostock > eastmoney > akshare
        """
        # 1. 尝试baostock
        try:
            import baostock as bs
            bs.login()
            data = self._fetch_from_baostock(code)
            bs.logout()
            if data:
                return data
        except Exception as e:
            logger.debug(f"baostock failed: {e}")
        
        # 2. 尝试东方财富
        try:
            data = self._fetch_from_eastmoney(code)
            if data:
                return data
        except Exception as e:
            logger.debug(f"eastmoney failed: {e}")
        
        # 3. 尝试akshare
        try:
            import akshare as ak
            data = self._fetch_from_akshare(code)
            if data:
                return data
        except Exception as e:
            logger.debug(f"akshare failed: {e}")
        
        return None
```

---

## 🔌 接口抽象

### 1. K线数据接口

**抽象基类**:
```python
# src/data/provider/base.py
from abc import ABC, abstractmethod
import pandas as pd

# 标准K线列名
KLINE_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']

class KlineAdapter(ABC):
    """K线数据适配器基类"""
    
    name: str = ''  # 适配器名称
    
    @abstractmethod
    def fetch(
        self, 
        symbol: str, 
        start_date: str, 
        end_date: str
    ) -> pd.DataFrame:
        """
        获取K线数据
        
        Args:
            symbol: 股票代码（如 '600000'）
            start_date: 开始日期 'YYYY-MM-DD'
            end_date: 结束日期 'YYYY-MM-DD'
        
        Returns:
            DataFrame with columns: KLINE_COLUMNS
            按日期升序排列
        """
        pass
```

### 2. 基本面数据接口

**接口定义**:
```python
# src/data/fetchers/fundamental_fetcher.py
class FundamentalFetcher:
    """基本面数据获取器（统一接口）"""
    
    def get_pe_pb_data(self, code: str) -> dict:
        """获取PE/PB数据"""
        pass
    
    def get_financial_indicators(self, code: str) -> pd.DataFrame:
        """获取财务指标（ROE/净利润率等）"""
        pass
    
    def get_industry_classification(self, code: str) -> str:
        """获取行业分类"""
        pass
    
    def get_daily_basic(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取日频基本面数据"""
        pass
```

### 3. 实时数据接口

**接口定义**:
```python
# src/data/fetchers/realtime_data.py
class RealtimeDataFetcher:
    """实时行情获取器"""
    
    def get_realtime_price(self, stock_code: str) -> Optional[float]:
        """获取实时价格"""
        pass
    
    def get_realtime_quotes(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """批量获取实时行情"""
        pass
```

---

## 💡 使用示例

### 示例1: 策略中使用统一接口

```python
# tools/analysis/analyze_single_stock.py
from src.data.provider import get_default_kline_provider

def analyze_stock(code: str):
    # 1. 获取统一数据提供者
    provider = get_default_kline_provider()
    
    # 2. 获取K线数据（自动fallback）
    df = provider.get_kline(
        symbol=code,
        start_date='2023-01-01',
        end_date='2026-03-06'
    )
    
    # 3. 传递给策略分析
    strategy = MACrossStrategy()
    signal = strategy.analyze(df)
    
    return signal
```

### 示例2: 回测中使用统一接口

```python
# src/backtest/backtest_engine.py
from src.data.provider import get_default_kline_provider

class BacktestEngine:
    def __init__(self):
        self.provider = get_default_kline_provider()
    
    def run_backtest(self, code: str, strategy: Strategy):
        # 获取历史数据（统一接口）
        df = self.provider.get_kline(
            symbol=code,
            start_date=self.start_date,
            end_date=self.end_date
        )
        
        # 运行回测
        for i in range(len(df)):
            window = df.iloc[:i+1]
            signal = strategy.analyze(window)
            self.execute_signal(signal)
```

### 示例3: 添加新数据源

```python
# src/data/provider/adapters.py

# 1. 实现新适配器
class YahooFinanceAdapter(KlineAdapter):
    name = 'yahoo'
    
    def fetch(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        import yfinance as yf
        
        # 转换股票代码格式
        ticker = f"{symbol}.SS" if symbol.startswith('6') else f"{symbol}.SZ"
        
        # 获取数据
        stock = yf.Ticker(ticker)
        df = stock.history(start=start_date, end=end_date)
        
        # 转换为标准格式
        df = df.reset_index()
        df.columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'dividends', 'stock_splits']
        df['amount'] = df['close'] * df['volume']
        df = df[KLINE_COLUMNS]
        
        return df

# 2. 注册适配器
KLINE_ADAPTER_REGISTRY['yahoo'] = YahooFinanceAdapter()
```

```yaml
# 3. 更新配置文件
# config/data_sources.yaml
kline:
  sources:
    - sina
    - yahoo        # 新增数据源
    - eastmoney
    - tencent
```

**完成！无需修改任何策略代码！**

---

## 📊 当前架构状态

### ✅ 已实现的抽象

| 模块 | 抽象层 | 状态 | 说明 |
|------|--------|------|------|
| **K线数据** | UnifiedDataProvider | ✅ 完成 | 支持8+数据源fallback |
| **基本面数据** | FundamentalFetcher | ✅ 完成 | baostock/akshare/东财 |
| **实时行情** | RealtimeDataFetcher | ✅ 完成 | 新浪/东财/腾讯 |
| **ETF数据** | ETFDataFetcher | ✅ 完成 | 专用适配器 |
| **新闻数据** | NewsFetcher | ⚠️ 部分 | 策略层有直接调用 |
| **龙虎榜数据** | MoneyFlowFetcher | ⚠️ 部分 | 策略层有直接调用 |

### ⚠️ 需要改进的地方

#### 1. 策略层仍有少量直接调用

**问题代码**:
```python
# src/strategies/policy_event.py (第25行)
import akshare as ak  # ❌ 策略直接导入数据源

# src/strategies/news_sentiment.py (第50行)
from src.data.news import fetch_stock_news  # ⚠️ 可以接受，但最好通过Provider
```

**建议改进**:
```python
# 改进方案1: 通过Provider获取
from src.data.provider import get_default_data_provider

class PolicyEventStrategy(Strategy):
    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        provider = get_default_data_provider()
        policy_data = provider.get_policy_events(self.symbol)  # 统一接口
        ...
```

#### 2. 部分工具脚本直接调用底层接口

**问题代码**:
```python
# tools/data/refresh_stock_pool.py (第50行)
def fetch_realtime_info(codes: list, session=None) -> dict:
    # 直接调用东方财富API
    url = 'http://push2.eastmoney.com/api/qt/stock/get'
    ...
```

**建议改进**:
```python
# 使用统一接口
from src.data.fetchers import FundamentalFetcher

fetcher = FundamentalFetcher()
fundamental_data = fetcher.get_pe_pb_data(code)  # 自动fallback
```

---

## 🚀 扩展指南

### 添加新数据类型

**步骤**:
1. 在Provider层添加新方法
2. 在Fetcher层实现具体逻辑
3. 更新配置文件

**示例：添加财报数据接口**:

```python
# 1. src/data/provider/data_provider.py
class UnifiedDataProvider:
    def get_financial_report(
        self, 
        symbol: str, 
        report_type: str = 'income'
    ) -> pd.DataFrame:
        """获取财务报表数据"""
        fetcher = FundamentalFetcher()
        return fetcher.get_financial_report(symbol, report_type)

# 2. src/data/fetchers/fundamental_fetcher.py
class FundamentalFetcher:
    def get_financial_report(self, code: str, report_type: str) -> pd.DataFrame:
        # 多数据源fallback
        for source in ['tushare', 'akshare', 'eastmoney']:
            try:
                data = self._fetch_report_from(source, code, report_type)
                if data is not None:
                    return data
            except Exception as e:
                logger.debug(f"{source} failed: {e}")
        return pd.DataFrame()

# 3. 策略中使用
class FundamentalStrategy(Strategy):
    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        provider = get_default_kline_provider()
        income_stmt = provider.get_financial_report(self.symbol, 'income')
        # 分析财报数据...
```

---

## 📈 架构优势

### 1. **可维护性**
- 数据源变更只需修改Adapter层
- 策略代码无需改动
- 配置文件统一管理

### 2. **可测试性**
- 可以mock UnifiedDataProvider进行单元测试
- 策略测试不依赖真实数据源
- 适配器可以独立测试

### 3. **可扩展性**
- 新增数据源：添加Adapter + 更新配置
- 新增数据类型：添加Provider方法 + Fetcher实现
- 无需修改现有代码

### 4. **高可用性**
- 自动fallback机制
- 熔断保护
- 本地缓存优先

### 5. **性能优化**
- 数据缓存
- 批量请求
- 并发获取

---

## 🎯 最佳实践

### DO ✅

1. **策略层只依赖抽象接口**
```python
from src.data.provider import get_default_kline_provider

provider = get_default_kline_provider()
df = provider.get_kline(symbol, start_date, end_date)
```

2. **通过配置文件管理数据源**
```yaml
# config/data_sources.yaml
kline:
  sources:
    - sina
    - eastmoney
```

3. **新数据源实现Adapter接口**
```python
class NewSourceAdapter(KlineAdapter):
    name = 'new_source'
    def fetch(self, symbol, start_date, end_date):
        # 实现获取逻辑
        pass
```

### DON'T ❌

1. **策略层直接导入数据源库**
```python
# ❌ 不要这样做
import akshare as ak
import baostock as bs
```

2. **策略层直接调用HTTP请求**
```python
# ❌ 不要这样做
import requests
resp = requests.get('http://hq.sinajs.cn/...')
```

3. **硬编码数据源选择**
```python
# ❌ 不要这样做
if source == 'sina':
    data = fetch_from_sina()
elif source == 'eastmoney':
    data = fetch_from_eastmoney()
```

---

## 📝 总结

### 当前架构特点

✅ **完全解耦**: 策略层与数据源完全分离  
✅ **统一接口**: 所有数据通过Provider获取  
✅ **配置驱动**: 数据源优先级由配置文件管理  
✅ **自动容错**: 多数据源自动fallback  
✅ **易于扩展**: 新增数据源无需修改策略  
✅ **高可用性**: 熔断机制 + 本地缓存  

### 架构成熟度

| 维度 | 评分 | 说明 |
|------|------|------|
| **抽象程度** | ⭐⭐⭐⭐⭐ | 完整的三层抽象 |
| **解耦程度** | ⭐⭐⭐⭐☆ | 策略层基本解耦，少量直接调用 |
| **可扩展性** | ⭐⭐⭐⭐⭐ | 新增数据源仅需添加Adapter |
| **可维护性** | ⭐⭐⭐⭐⭐ | 配置驱动，易于管理 |
| **可测试性** | ⭐⭐⭐⭐☆ | 支持mock，但部分策略耦合 |

### 改进建议

1. **消除策略层直接调用**: 将 `policy_event.py` 和 `news_sentiment.py` 中的直接调用改为通过Provider
2. **统一工具脚本接口**: 将 `refresh_stock_pool.py` 等工具改为使用统一接口
3. **完善文档**: 为每个Adapter添加详细的API文档
4. **增加监控**: 添加数据源健康度监控和告警

---

**结论**: 我们的系统已经实现了**高质量的数据接口层抽象**，策略层与数据源基本解耦，符合工业级标准。少量遗留的直接调用可以通过重构逐步消除。

---

## 📦 板块适配器（Sector Adapters）

除 K 线适配器外，系统还实现了板块成分股适配器，供 `refresh_stock_pool.py` 使用：

| 适配器类 | 数据源 | 说明 |
|----------|--------|------|
| `AkshareSectorAdapter` | akshare 概念板块 | 优先级最高，数据最全 |
| `EastMoneySectorAdapter` | 东方财富板块 API | 概念板块细分，但不稳定 |
| `SinaSectorAdapter` | 新浪行业板块 | 接口稳定，传统行业覆盖好 |
| `BaostockSectorAdapter` | baostock 行业 | 本地库，无网络限制 |
| `LocalSectorAdapter` | 本地关键词匹配 | 100% 可用，兜底方案 |

**调用示例**:

```python
from src.data.provider.data_provider import get_default_kline_provider

provider = get_default_kline_provider()

# 获取光伏板块成分股（5层自动切换）
stocks = provider.get_sector_stocks(
    sector_config={
        'akshare': ['光伏概念'],
        'eastmoney': ['BK1031'],
        'sina': [],
        'baostock': [],
        'keywords': ['光伏', '太阳能', '隆基', '通威', ...],
    },
    target=15
)
```

详细的板块数据源配置（7大赛道 `SECTOR_BOARDS` 完整配置）见 `docs/data/DATA_SOURCE_PRIORITY.md`。
