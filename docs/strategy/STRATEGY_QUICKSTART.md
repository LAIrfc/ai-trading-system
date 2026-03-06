# 策略开发快速开始 🚀

欢迎使用AI量化交易系统的策略框架！本指南帮助您快速开始策略开发。

---

## ✅ 环境准备

### 1. 安装依赖

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 核心依赖
pip3 install --user pandas numpy akshare loguru

# 如果需要更多数据源
pip3 install --user tushare baostock
```

### 2. 验证安装

```bash
python3 -c "import akshare; print('✅ AKShare OK')"
python3 -c "import pandas; print('✅ Pandas OK')"
```

---

## 🎯 5分钟快速测试

### 方式1: 命令行测试（推荐）

```bash
# 测试均线策略 - 贵州茅台
python3 tools/validation/strategy_tester.py --strategy MA --stocks 600519

# 测试MACD策略 - 多只股票
python3 tools/validation/strategy_tester.py --strategy MACD --stocks 600519,000001,600036

# 测试RSI策略
python3 tools/validation/strategy_tester.py --strategy RSI --stocks 600519
```

### 方式2: 交互式测试

```bash
python3 tools/validation/strategy_tester.py --interactive
```

然后按提示选择策略和股票。

### 方式3: Python脚本

```python
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/wangxinghan/codetree/ai-trading-system')

from src.core.strategy.strategy_library import strategy_library
from src.data.realtime_data import MarketDataManager

# 1. 创建策略
strategy = strategy_library.get_strategy('MA', short_window=5, long_window=20)

# 2. 获取数据
data_manager = MarketDataManager()
market_data = data_manager.prepare_strategy_data(['600519'])

# 3. 生成信号
signals = strategy.generate_signals(market_data)

# 4. 查看信号
for signal in signals:
    print(f"{signal['action']}: {signal['stock_code']} @ {signal['price']:.2f}")
    print(f"原因: {signal['reason']}")
```

---

## 📚 内置策略说明

### 1. 均线策略 (MA)

**适用**: 趋势明显的市场

```python
strategy = strategy_library.get_strategy('MA', 
    short_window=5,   # 短期均线
    long_window=20    # 长期均线
)
```

**信号**:
- 🟢 买入: 短期均线上穿长期均线（金叉）
- 🔴 卖出: 短期均线下穿长期均线（死叉）

### 2. MACD策略

**适用**: 中期趋势判断

```python
strategy = strategy_library.get_strategy('MACD',
    fast_period=12,     # 快速周期
    slow_period=26,     # 慢速周期
    signal_period=9     # 信号周期
)
```

**信号**:
- 🟢 买入: MACD金叉（特别是在0轴上方）
- 🔴 卖出: MACD死叉

### 3. RSI策略

**适用**: 震荡市场

```python
strategy = strategy_library.get_strategy('RSI',
    period=14,        # RSI周期
    oversold=30,      # 超卖阈值
    overbought=70     # 超买阈值
)
```

**信号**:
- 🟢 买入: RSI < 30 (超卖)
- 🔴 卖出: RSI > 70 (超买)

---

## ✍️ 创建自己的策略

### 步骤1: 创建策略文件

创建文件 `my_first_strategy.py`:

```python
import sys
sys.path.insert(0, '/home/wangxinghan/codetree/ai-trading-system')

from typing import Dict, List
import pandas as pd
from src.core.strategy.base_strategy import BaseStrategy


class MyFirstStrategy(BaseStrategy):
    """
    我的第一个策略 - 简单示例
    
    规则:
    - 收盘价 > 5日均线 且 5日均线 > 20日均线 → 买入
    - 收盘价 < 5日均线 → 卖出
    """
    
    def __init__(self, ma_short=5, ma_long=20):
        super().__init__()
        self.ma_short = ma_short
        self.ma_long = ma_long
    
    def generate_signals(self, market_data: Dict) -> List[Dict]:
        """生成交易信号"""
        signals = []
        
        for stock_code, data in market_data.items():
            # 检查数据
            if not isinstance(data, pd.DataFrame) or len(data) < self.ma_long:
                continue
            
            # 计算均线
            data['MA_short'] = data['close'].rolling(self.ma_short).mean()
            data['MA_long'] = data['close'].rolling(self.ma_long).mean()
            
            # 获取最新数据
            latest = data.iloc[-1]
            price = latest['close']
            ma_short = latest['MA_short']
            ma_long = latest['MA_long']
            
            # 买入信号
            if price > ma_short and ma_short > ma_long:
                signals.append({
                    'stock_code': stock_code,
                    'action': 'buy',
                    'signal_type': 'trend_follow',
                    'reason': f'价格({price:.2f})>MA{self.ma_short}({ma_short:.2f})>MA{self.ma_long}({ma_long:.2f})',
                    'confidence': 0.7,
                    'target_position': 0.1,
                    'price': price,
                })
            
            # 卖出信号
            elif price < ma_short:
                signals.append({
                    'stock_code': stock_code,
                    'action': 'sell',
                    'signal_type': 'trend_reverse',
                    'reason': f'价格({price:.2f})<MA{self.ma_short}({ma_short:.2f})',
                    'confidence': 0.6,
                    'price': price,
                })
        
        return signals
    
    def calculate_position_size(self, signal: Dict, account_info: Dict) -> int:
        """计算仓位"""
        available = account_info.get('available_balance', 100000)
        target_pct = signal.get('target_position', 0.1)
        price = signal['price']
        
        quantity = int(available * target_pct / price / 100) * 100
        return max(100, quantity)


# 测试代码
if __name__ == "__main__":
    from src.data.realtime_data import MarketDataManager
    
    # 创建策略
    strategy = MyFirstStrategy(ma_short=5, ma_long=20)
    
    # 获取数据
    data_manager = MarketDataManager()
    market_data = data_manager.prepare_strategy_data(['600519'])
    
    # 生成信号
    signals = strategy.generate_signals(market_data)
    
    # 显示结果
    if signals:
        for signal in signals:
            print(f"\n{signal['action'].upper()}: {signal['stock_code']}")
            print(f"价格: {signal['price']:.2f}")
            print(f"原因: {signal['reason']}")
            print(f"置信度: {signal['confidence']*100:.0f}%")
    else:
        print("当前无交易信号")
```

### 步骤2: 测试策略

```bash
python3 my_first_strategy.py
```

### 步骤3: 注册到策略库（可选）

```python
from src.core.strategy.strategy_library import strategy_library

strategy_library.register_strategy(
    name='MyFirst',
    strategy_class=MyFirstStrategy,
    description='我的第一个策略'
)
```

---

## 🧪 实时行情数据

### 获取实时价格

```python
from src.data.realtime_data import RealtimeDataFetcher

fetcher = RealtimeDataFetcher(data_source='akshare')

# 单只股票
price = fetcher.get_realtime_price('600519')
print(f"贵州茅台当前价格: {price}")

# 多只股票
quotes = fetcher.get_realtime_quotes(['600519', '000001'])
for code, quote in quotes.items():
    print(f"{code}: {quote['price']:.2f} ({quote['change_pct']:+.2f}%)")
```

### 获取历史数据

```python
# 获取最近100天数据
df = fetcher.get_historical_data('600519', days=100)

print(df.tail())  # 显示最后5天
print(f"数据量: {len(df)}天")
```

### 市场概览

```python
overview = fetcher.get_market_overview()

print(f"上涨: {overview['rising']}")
print(f"下跌: {overview['falling']}")
print(f"涨停: {overview['limit_up']}")
print(f"跌停: {overview['limit_down']}")
```

---

## 📊 策略对比

测试多个策略，找出最适合的：

```python
from src.core.strategy.strategy_library import strategy_library
from src.data.realtime_data import MarketDataManager

# 准备数据
data_manager = MarketDataManager()
stocks = ['600519', '000001', '600036']
market_data = data_manager.prepare_strategy_data(stocks)

# 测试所有策略
strategies = ['MA', 'MACD', 'RSI']

for strategy_name in strategies:
    print(f"\n{'='*60}")
    print(f"测试策略: {strategy_name}")
    print('='*60)
    
    strategy = strategy_library.get_strategy(strategy_name)
    signals = strategy.generate_signals(market_data)
    
    print(f"生成信号数: {len(signals)}")
    for signal in signals:
        print(f"  {signal['action']}: {signal['stock_code']} - {signal['reason']}")
```

---

## 🎓 进阶功能

### 1. 组合策略

```python
class ComboStrategy(BaseStrategy):
    """组合多个策略的信号"""
    
    def __init__(self):
        super().__init__()
        self.ma_strategy = MAStrategy()
        self.rsi_strategy = RSIStrategy()
    
    def generate_signals(self, market_data):
        ma_signals = self.ma_strategy.generate_signals(market_data)
        rsi_signals = self.rsi_strategy.generate_signals(market_data)
        
        # 合并信号，提高置信度
        # ...实现你的组合逻辑
        
        return combined_signals
```

### 2. 添加过滤条件

```python
def generate_signals(self, market_data):
    signals = []
    
    for stock_code, data in market_data.items():
        # 基本信号
        if self._basic_condition(data):
            
            # 添加过滤
            if self._volume_filter(data):  # 成交量过滤
                if self._volatility_filter(data):  # 波动率过滤
                    signals.append(...)
    
    return signals
```

### 3. 动态仓位管理

```python
def calculate_position_size(self, signal, account_info):
    base_size = super().calculate_position_size(signal, account_info)
    
    # 根据置信度调整
    confidence = signal.get('confidence', 0.5)
    adjusted_size = int(base_size * confidence)
    
    # 根据波动率调整
    # ...
    
    return adjusted_size
```

---

## 📖 相关文档

- [策略详细说明（6大基础+组合+回测）](STRATEGY_DETAIL.md)
- [策略清单与工具对应](STRATEGY_LIST.md)
- [回测与实盘规范](BACKTEST_AND_LIVE_SPEC.md)

---

## 💡 提示

1. **从简单开始** - 先实现一个简单策略，验证数据流程
2. **充分测试** - 用历史数据回测，确保逻辑正确
3. **小资金试水** - 实盘前用小资金测试
4. **持续优化** - 记录每笔交易，定期review
5. **风控第一** - 永远设置止损

---

## 🆘 常见问题

### Q: 获取数据失败？

A: 检查网络连接和akshare是否安装：
```bash
pip3 install --user --upgrade akshare
```

### Q: 没有生成信号？

A: 可能当前市场条件不满足策略规则，这是正常的。尝试：
- 测试其他股票
- 调整策略参数
- 检查历史数据是否足够

### Q: 如何调试策略？

A: 在策略代码中添加打印：
```python
print(f"当前价格: {price}, MA5: {ma5}, MA20: {ma20}")
```

---

开始构建您的第一个策略吧！ 🚀
