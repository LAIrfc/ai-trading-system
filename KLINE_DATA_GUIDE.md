# K线数据获取指南 📊

## 快速开始

### 📡 数据来源

使用 **AKShare** 免费数据源，数据来自交易所，和同花顺显示的**完全一致**！

### ✅ 支持的数据类型

- ✅ **实时价格** - 延迟3-5秒
- ✅ **日K线** - OHLCV完整数据
- ✅ **周K线** - 周级别数据
- ✅ **月K线** - 月级别数据
- ✅ **前复权** - 处理过除权除息
- ✅ **历史任意时间段**

---

## 🚀 三种使用方式

### 方式1: 命令行工具（最快）⭐

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 获取贵州茅台日K线（最近30天）
python3 tools/kline_fetcher.py 600519

# 获取周K线（最近60天）
python3 tools/kline_fetcher.py 600519 --period weekly --days 60

# 获取月K线
python3 tools/kline_fetcher.py 600519 --period monthly --days 365

# 对比历史和实时
python3 tools/kline_fetcher.py 600519 --compare

# 导出到CSV
python3 tools/kline_fetcher.py 600519 --export

# 查看常用股票代码
python3 tools/kline_fetcher.py --list
```

**输出示例**：
```
================================================================================
  获取 600519 的K线数据
================================================================================

📅 时间范围: 20240101 ~ 20260224
📊 周期: daily
🔍 正在获取数据...

✅ 成功获取 30 条K线数据

📈 数据统计:
   最高价: 1850.00
   最低价: 1620.00
   平均价: 1735.50
   最新价: 1800.00
   总成交量: 12500万手

📊 最近10个交易日K线:
--------------------------------------------------------------------------------
日期         开盘     最高     最低     收盘     涨跌幅%   成交量(万手)
--------------------------------------------------------------------------------
2026-02-10   1750.00  1800.00  1740.00  1795.00  +1.25    250
2026-02-11   1795.00  1810.00  1780.00  1800.00  +0.28    280
...

🔴 实时行情:
   名称: 贵州茅台
   当前价: 1800.00
   涨跌幅: +0.28%
   今开: 1795.00
   昨收: 1795.00
   最高: 1810.00
   最低: 1780.00
   成交量: 280万手
   成交额: 50.4亿
   时间: 2026-02-24 14:30:00
```

---

### 方式2: Python代码

```python
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/wangxinghan/codetree/ai-trading-system')

from src.data.realtime_data import RealtimeDataFetcher

# 创建数据获取器
fetcher = RealtimeDataFetcher(data_source='akshare')

# 获取K线数据
df = fetcher.get_historical_data(
    stock_code='600519',      # 股票代码
    start_date='20240101',    # 开始日期
    end_date='20260224',      # 结束日期
    period='daily'            # 周期: daily, weekly, monthly
)

# 查看数据
print(df.head())
print(f"\n总计: {len(df)}天数据")

# 获取最新价格
print(f"最新收盘价: {df['close'].iloc[-1]:.2f}")

# 计算均线
df['MA5'] = df['close'].rolling(window=5).mean()
df['MA20'] = df['close'].rolling(window=20).mean()
print(f"MA5: {df['MA5'].iloc[-1]:.2f}")
print(f"MA20: {df['MA20'].iloc[-1]:.2f}")
```

**数据格式**：
```
DataFrame结构:
- index: 日期 (DatetimeIndex)
- open: 开盘价
- high: 最高价
- low: 最低价
- close: 收盘价
- volume: 成交量
- amount: 成交额
- change_pct: 涨跌幅
```

---

### 方式3: 完整演示

```bash
# 运行完整演示（包含5个示例）
python3 examples/get_kline_demo.py
```

演示内容：
1. 获取基础K线数据
2. 获取实时行情
3. 为策略准备数据（历史+实时）
4. 获取不同周期K线
5. 导出数据到CSV/Excel

---

## 📈 实时数据获取

### 获取单只股票实时价格

```python
from src.data.realtime_data import RealtimeDataFetcher

fetcher = RealtimeDataFetcher()

# 快速获取价格
price = fetcher.get_realtime_price('600519')
print(f"茅台现价: {price}元")
```

### 获取多只股票实时行情

```python
# 批量获取
quotes = fetcher.get_realtime_quotes(['600519', '000001', '600036'])

for code, quote in quotes.items():
    print(f"{code} - {quote['name']}")
    print(f"  价格: {quote['price']:.2f}")
    print(f"  涨跌幅: {quote['change_pct']:+.2f}%")
    print(f"  成交量: {quote['volume']/10000:.0f}万手")
```

**实时数据包含**：
```python
{
    'code': '600519',
    'name': '贵州茅台',
    'price': 1800.00,         # 当前价
    'change_pct': 0.28,       # 涨跌幅%
    'change_amount': 5.00,    # 涨跌额
    'volume': 2800000,        # 成交量
    'amount': 5040000000,     # 成交额
    'open': 1795.00,          # 今开
    'high': 1810.00,          # 最高
    'low': 1780.00,           # 最低
    'pre_close': 1795.00,     # 昨收
    'timestamp': datetime,    # 时间戳
}
```

---

## 🎯 策略开发中使用

### 为策略准备完整数据

```python
from src.data.realtime_data import MarketDataManager

# 创建数据管理器
manager = MarketDataManager(data_source='akshare')

# 准备数据（自动合并历史+实时）
market_data = manager.prepare_strategy_data(
    stock_codes=['600519', '000001'],
    historical_days=100  # 最近100天
)

# market_data 格式:
# {
#     '600519': DataFrame(100天历史 + 今日实时),
#     '000001': DataFrame(...)
# }

# 直接用于策略
from src.core.strategy.strategy_library import strategy_library

strategy = strategy_library.get_strategy('MA')
signals = strategy.generate_signals(market_data)
```

**智能功能**：
- ✅ 自动缓存（避免频繁请求）
- ✅ 自动更新（可配置间隔）
- ✅ 合并历史+实时（形成完整K线）
- ✅ 标准化格式（直接用于策略）

---

## 💾 数据导出

### 导出为CSV

```python
import pandas as pd
from src.data.realtime_data import RealtimeDataFetcher

fetcher = RealtimeDataFetcher()
df = fetcher.get_historical_data('600519')

# 导出CSV
df.to_csv('data/600519_kline.csv')
print("✅ 数据已保存")
```

### 导出为Excel

```python
# 需要安装: pip3 install --user openpyxl
df.to_excel('data/600519_kline.xlsx')
```

### 使用命令行工具导出

```bash
# 自动导出CSV
python3 tools/kline_fetcher.py 600519 --export

# 文件会保存到: data/600519_daily_kline_20260224.csv
```

---

## 🔍 数据质量

### 数据来源
- **AKShare** → 东方财富/新浪财经 → **交易所官方数据**
- 和同花顺、通达信显示的**完全一致**

### 数据特点
- ✅ **免费** - 无需API key
- ✅ **实时** - 延迟3-5秒（行情软件级别）
- ✅ **完整** - OHLCV + 涨跌幅 + 成交额
- ✅ **复权** - 自动前复权处理
- ✅ **准确** - 来自官方渠道

### 更新频率
- **实时数据**: 每3秒更新一次
- **历史数据**: 每日收盘后更新

---

## 📊 常用代码片段

### 1. 检测金叉

```python
df = fetcher.get_historical_data('600519')

df['MA5'] = df['close'].rolling(window=5).mean()
df['MA20'] = df['close'].rolling(window=20).mean()

current = df.iloc[-1]
previous = df.iloc[-2]

if previous['MA5'] <= previous['MA20'] and current['MA5'] > current['MA20']:
    print("🟢 金叉出现！")
```

### 2. 计算涨跌幅

```python
df = fetcher.get_historical_data('600519', days=10)

# 最近10天涨跌幅
for idx, row in df.iterrows():
    change_pct = row.get('change_pct', 0)
    print(f"{idx.strftime('%Y-%m-%d')}: {change_pct:+.2f}%")

# 10天累计涨幅
total_change = (df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100
print(f"\n10天累计: {total_change:+.2f}%")
```

### 3. 找最高/最低价

```python
df = fetcher.get_historical_data('600519', days=30)

max_price = df['high'].max()
min_price = df['low'].min()
max_date = df[df['high'] == max_price].index[0]
min_date = df[df['low'] == min_price].index[0]

print(f"30天最高: {max_price:.2f} ({max_date.strftime('%Y-%m-%d')})")
print(f"30天最低: {min_price:.2f} ({min_date.strftime('%Y-%m-%d')})")
```

### 4. 成交量分析

```python
df = fetcher.get_historical_data('600519', days=20)

df['volume_ma5'] = df['volume'].rolling(window=5).mean()

latest = df.iloc[-1]
if latest['volume'] > latest['volume_ma5'] * 1.5:
    print("📊 成交量放大！")
```

---

## 🆘 常见问题

### Q: 数据和同花顺不一样？
A: 数据来源相同，可能是：
- 时间延迟（实时数据有3-5秒延迟）
- 复权方式不同（我们使用前复权）
- 刷新时机不同

### Q: 获取数据失败？
A: 检查：
```bash
# 1. 升级AKShare
pip3 install --user --upgrade akshare

# 2. 检查网络
ping baidu.com

# 3. 测试数据源
python3 -c "import akshare as ak; df=ak.stock_zh_a_spot_em(); print('OK')"
```

### Q: 数据太慢？
A: 使用数据管理器缓存：
```python
from src.data.realtime_data import MarketDataManager

manager = MarketDataManager(update_interval=5)  # 5秒内复用缓存
data = manager.get_realtime_data(['600519'])
```

### Q: 需要分钟级数据？
A: AKShare免费版只提供日K线，分钟级需要：
- Tushare Pro（付费）
- 新浪财经接口（不稳定）
- 券商API（需要开户）

---

## 📚 相关文档

- [策略开发快速开始](STRATEGY_QUICKSTART.md)
- [策略系统概览](STRATEGY_SYSTEM_OVERVIEW.md)
- [快速参考](QUICK_REFERENCE.md)

---

## 💡 下一步

1. **测试获取数据**:
   ```bash
   python3 tools/kline_fetcher.py 600519
   ```

2. **运行完整演示**:
   ```bash
   python3 examples/get_kline_demo.py
   ```

3. **在策略中使用**:
   ```bash
   python3 tools/strategy_tester.py --strategy MA --stocks 600519
   ```

---

**数据就绪，开始量化交易！** 📈🚀
