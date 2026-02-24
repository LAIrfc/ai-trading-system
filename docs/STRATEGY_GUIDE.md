## 交易策略指南 📊

本指南帮助您收集、开发和测试交易策略。

---

## 📚 策略库

系统已内置以下策略：

### 1. 均线策略 (MA Strategy)

**原理**：
- 金叉（短期均线上穿长期均线）→ 买入
- 死叉（短期均线下穿长期均线）→ 卖出

**参数**：
- `short_window`: 短期均线周期（默认5日）
- `long_window`: 长期均线周期（默认20日）
- `stop_loss`: 止损比例（默认5%）
- `take_profit`: 止盈比例（默认15%）

**适用场景**：趋势明显的市场

**使用示例**：
```python
from src.core.strategy.strategy_library import MAStrategy

strategy = MAStrategy(short_window=5, long_window=20)
```

---

### 2. MACD策略

**原理**：
- MACD线上穿信号线（金叉）→ 买入
- MACD线下穿信号线（死叉）→ 卖出
- MACD柱状图由负转正 → 买入

**参数**：
- `fast_period`: 快速EMA周期（默认12）
- `slow_period`: 慢速EMA周期（默认26）
- `signal_period`: 信号线周期（默认9）

**适用场景**：中期趋势判断

**使用示例**：
```python
from src.core.strategy.strategy_library import MACDStrategy

strategy = MACDStrategy(fast_period=12, slow_period=26, signal_period=9)
```

---

### 3. RSI策略

**原理**：
- RSI < 30 → 超卖，买入信号
- RSI > 70 → 超买，卖出信号

**参数**：
- `period`: RSI周期（默认14）
- `oversold`: 超卖阈值（默认30）
- `overbought`: 超买阈值（默认70）

**适用场景**：震荡市场

**使用示例**：
```python
from src.core.strategy.strategy_library import RSIStrategy

strategy = RSIStrategy(period=14, oversold=30, overbought=70)
```

---

## ✍️ 如何添加自己的策略

### 步骤1：创建策略类

在 `src/core/strategy/my_strategies.py` 创建新文件：

```python
from typing import Dict, List
import pandas as pd
from src.core.strategy.base_strategy import BaseStrategy


class MyCustomStrategy(BaseStrategy):
    """
    我的自定义策略
    
    策略说明：
    - 买入条件：...
    - 卖出条件：...
    - 止损：...
    """
    
    def __init__(self, param1=10, param2=20):
        super().__init__()
        self.param1 = param1
        self.param2 = param2
    
    def generate_signals(self, market_data: Dict) -> List[Dict]:
        """
        生成交易信号
        
        Args:
            market_data: {股票代码: DataFrame(包含OHLCV数据)}
            
        Returns:
            信号列表，每个信号是一个字典：
            {
                'stock_code': '600519',
                'action': 'buy' or 'sell',
                'signal_type': '信号类型标识',
                'reason': '信号原因说明',
                'confidence': 0.0-1.0,  # 信号置信度
                'target_position': 0.0-1.0,  # 目标仓位比例
                'price': 100.0,  # 价格
            }
        """
        signals = []
        
        for stock_code, data in market_data.items():
            if not isinstance(data, pd.DataFrame) or len(data) < 20:
                continue
            
            # 计算你的指标
            current_price = data['close'].iloc[-1]
            
            # 你的买入逻辑
            if self._should_buy(data):
                signals.append({
                    'stock_code': stock_code,
                    'action': 'buy',
                    'signal_type': 'my_buy_signal',
                    'reason': '满足买入条件',
                    'confidence': 0.8,
                    'target_position': 0.1,
                    'price': current_price,
                })
            
            # 你的卖出逻辑
            elif self._should_sell(data):
                signals.append({
                    'stock_code': stock_code,
                    'action': 'sell',
                    'signal_type': 'my_sell_signal',
                    'reason': '满足卖出条件',
                    'confidence': 0.7,
                    'price': current_price,
                })
        
        return signals
    
    def _should_buy(self, data: pd.DataFrame) -> bool:
        """判断是否应该买入"""
        # 实现你的买入逻辑
        return False
    
    def _should_sell(self, data: pd.DataFrame) -> bool:
        """判断是否应该卖出"""
        # 实现你的卖出逻辑
        return False
    
    def calculate_position_size(self, signal: Dict, account_info: Dict) -> int:
        """
        计算仓位大小
        
        Args:
            signal: 交易信号
            account_info: 账户信息 {'available_balance': 可用资金}
            
        Returns:
            购买股数（必须是100的整数倍）
        """
        available_cash = account_info.get('available_balance', 0)
        target_position = signal.get('target_position', 0.1)
        price = signal['price']
        
        target_value = available_cash * target_position
        quantity = int(target_value / price / 100) * 100
        
        return max(100, quantity)
```

### 步骤2：注册策略

```python
from src.core.strategy.strategy_library import strategy_library
from my_strategies import MyCustomStrategy

# 注册到策略库
strategy_library.register_strategy(
    name='MyCustom',
    strategy_class=MyCustomStrategy,
    description='我的自定义策略 - 简短描述'
)
```

### 步骤3：使用策略

```python
# 获取策略实例
strategy = strategy_library.get_strategy('MyCustom', param1=15, param2=25)

# 准备市场数据
from src.data.realtime_data import MarketDataManager

data_manager = MarketDataManager()
market_data = data_manager.prepare_strategy_data(['600519', '000001'])

# 生成信号
signals = strategy.generate_signals(market_data)

for signal in signals:
    print(f"{signal['stock_code']}: {signal['action']} - {signal['reason']}")
```

---

## 🧪 策略测试

### 快速测试

使用 `tools/strategy_tester.py` 快速测试策略：

```bash
python3 tools/strategy_tester.py --strategy MA --stocks 600519,000001
```

### 回测

```python
from src.core.backtest.backtester import Backtester

# 创建回测器
backtester = Backtester(
    strategy=strategy,
    initial_capital=100000,
    start_date='20240101',
    end_date='20241231'
)

# 运行回测
results = backtester.run(['600519', '000001'])

# 查看结果
print(f"总收益率: {results['total_return']:.2%}")
print(f"夏普比率: {results['sharpe_ratio']:.2f}")
print(f"最大回撤: {results['max_drawdown']:.2%}")
```

---

## 📊 常用技术指标

系统提供了常用技术指标计算：

```python
import pandas as pd
from src.utils.indicators import TechnicalIndicators

data = pd.DataFrame(...)  # 你的OHLCV数据

indicators = TechnicalIndicators(data)

# 移动平均线
ma5 = indicators.sma(5)
ma20 = indicators.sma(20)
ema12 = indicators.ema(12)

# MACD
macd, signal, histogram = indicators.macd()

# RSI
rsi = indicators.rsi(14)

# 布林带
upper, middle, lower = indicators.bollinger_bands(20, 2)

# KDJ
k, d, j = indicators.kdj()

# 成交量指标
obv = indicators.obv()

# ATR (平均真实波幅)
atr = indicators.atr(14)
```

---

## 💡 策略开发建议

### 1. 从简单开始
- 先实现单一指标策略
- 验证信号是否正确
- 逐步增加复杂度

### 2. 充分回测
- 至少用1年历史数据回测
- 测试不同市场环境（牛市、熊市、震荡市）
- 注意过拟合风险

### 3. 风控第一
- 设置止损止盈
- 控制单笔仓位
- 限制最大回撤

### 4. 参数优化
- 不要过度优化参数
- 保持策略逻辑简单清晰
- 定期review和调整

### 5. 实盘前
- 模拟盘测试至少1个月
- 记录每笔交易的原因
- 总结经验教训

---

## 📝 策略文档模板

建议为每个策略创建文档：

```markdown
# [策略名称]

## 策略概述
- 策略类型：趋势跟踪/均值回归/...
- 适用市场：A股/港股/...
- 时间周期：日线/小时/...

## 买入条件
1. 条件1
2. 条件2
3. ...

## 卖出条件
1. 条件1
2. 条件2
3. ...

## 止损止盈
- 止损：-5%
- 止盈：+15%

## 参数说明
- 参数1: 说明
- 参数2: 说明

## 回测结果
- 测试期间：2023-01-01 到 2024-01-01
- 总收益率：XX%
- 年化收益率：XX%
- 夏普比率：XX
- 最大回撤：XX%
- 胜率：XX%

## 注意事项
- ...
- ...
```

---

## 🔗 相关文档

- [回测指南](BACKTEST_GUIDE.md)
- [风控配置](RISK_MANAGEMENT.md)
- [API文档](API_REFERENCE.md)

---

## 💬 交流讨论

欢迎分享你的策略！
