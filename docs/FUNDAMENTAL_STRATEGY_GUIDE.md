# 基本面策略使用指南

## 概述

基本面策略已集成到交易系统中，与技术面策略形成互补。当前已实现 **PE估值策略**，后续可扩展ROE、PB等策略。

## 已实现策略

### 1. PE估值策略 (`PEStrategy`)

**原理**：
- 当PE低于历史20%分位数时买入（估值低估）
- 当PE高于历史80%分位数时卖出（估值高估）
- 其他情况持有

**参数**：
- `low_quantile`: 买入阈值分位数（默认0.2）
- `high_quantile`: 卖出阈值分位数（默认0.8）

**特点**：
- 信号强度随分位数动态调整（越极端信号越强）
- 仓位随信号强度动态调整
- 避免未来函数：只使用已发布的基本面数据

## 数据获取

### 当前实现（模拟数据）

系统默认使用**模拟基本面数据**（用于测试），避免依赖外部API：

```python
from src.data.fundamental_fetcher import create_mock_fundamental_data

# 创建模拟PE/PB数据
fund_df = create_mock_fundamental_data(daily_df, pe_range=(5, 50), pb_range=(0.5, 5.0))
```

### 真实数据源（可选）

如需使用真实基本面数据，需要：

1. **安装数据源库**：
   ```bash
   pip install akshare  # 免费，无需token
   # 或
   pip install tushare   # 需要token，数据更全
   ```

2. **配置数据源**：
   ```python
   from src.data.fundamental_fetcher import FundamentalFetcher
   
   # 使用 tushare（需要先设置token）
   import tushare as ts
   ts.set_token('your_token')
   
   fetcher = FundamentalFetcher(source='tushare')
   fund_df = fetcher.get_daily_basic(code, start_date='20200101', end_date='20231231')
   ```

3. **合并到日线数据**：
   ```python
   merged_df = fetcher.merge_to_daily(daily_df, fund_df, fill_method='ffill')
   ```

## 集成到组合策略

PE策略已自动注册到 `EnsembleStrategy`，无需额外配置：

```python
from src.strategies.ensemble import EnsembleStrategy

ensemble = EnsembleStrategy()
# PE策略已包含在子策略中
print(ensemble.sub_strategies.keys())
# ['MA', 'MACD', 'RSI', 'BOLL', 'KDJ', 'DUAL', 'PE']
```

**权重配置**：
- PE策略默认权重：`1.0`（中等）
- 可根据回测表现调整权重

## 回测使用

### 批量回测（已集成）

`batch_backtest.py` 已自动启用基本面数据：

```bash
python3 tools/batch_backtest.py --count 100
```

系统会：
1. 自动为每只股票生成模拟基本面数据
2. 合并到日线数据
3. 运行PE策略回测
4. 包含在组合策略投票中

### 单股票测试

```python
from src.data.fundamental_fetcher import create_mock_fundamental_data, FundamentalFetcher
from src.strategies.fundamental_pe import PEStrategy

# 获取日线数据
daily_df = fetch_sina('600000', 800)

# 合并基本面数据
fund_df = create_mock_fundamental_data(daily_df)
fetcher = FundamentalFetcher()
df = fetcher.merge_to_daily(daily_df, fund_df)

# 运行PE策略
pe_strategy = PEStrategy()
signal = pe_strategy.analyze(df)
print(f"{signal.action} | conf={signal.confidence} | pos={signal.position}")
```

## 扩展新基本面策略

### 1. 创建策略类

参考 `src/strategies/fundamental_pe.py`：

```python
from .base import Strategy, StrategySignal

class ROEStrategy(Strategy):
    name = 'ROE盈利改善'
    description = '基于ROE连续提升的盈利改善策略'
    
    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        # df 必须包含 'roe' 列
        if 'roe' not in df.columns:
            return StrategySignal('HOLD', 0.0, '缺少ROE数据', 0.5)
        
        # 策略逻辑...
        return StrategySignal(...)
```

### 2. 注册到组合策略

修改 `src/strategies/ensemble.py`：

```python
from .fundamental_roe import ROEStrategy

# 在 __init__ 中添加
self.sub_strategies['ROE'] = ROEStrategy()
self.weights['ROE'] = 1.0
```

### 3. 数据获取

在 `fundamental_fetcher.py` 中添加ROE数据获取方法：

```python
def get_roe_data(self, code: str, ...) -> pd.DataFrame:
    # 从财报中提取ROE（通常为季频）
    # 对齐到日频（ffill填充）
    pass
```

## 注意事项

### 1. 未来函数

⚠️ **必须避免未来函数**：
- 只能使用**已发布的财报数据**
- 使用财报**发布日期**（ann_date）而非财报截止日期（end_date）
- 基本面数据用 `ffill` 填充（前向填充），不能用未来数据
- **模拟数据警告**：`create_mock_fundamental_data` 基于整个DataFrame生成，隐含未来信息，仅用于测试流程，不可用于真实回测

### 2. 分位数计算

PE策略支持两种分位数计算方式：
- **全部历史**（默认）：使用所有历史PE数据计算分位数
  - 优点：样本量大，统计稳定
  - 缺点：早期估值中枢可能影响当前判断
- **滚动窗口**（可选）：只使用最近N天的PE数据
  - 优点：反映近期估值水平，避免早期数据干扰
  - 缺点：样本量小，可能波动较大
  - 使用：`PEStrategy(rolling_window=1260)`  # 5年窗口

### 3. 数据源配置

**tushare配置**（推荐）：
```python
# 方式1: 环境变量
export TUSHARE_TOKEN='your_token'

# 方式2: 代码中设置
import tushare as ts
ts.set_token('your_token')
```

**akshare**：
- 免费，无需token
- 但日频基本面接口不稳定，当前返回空
- 建议使用 tushare

### 2. 数据频率对齐

- 基本面数据通常为**季频/年频**
- 需要对齐到**日频**（使用 `ffill` 填充）
- 确保数据在回测时点可用

### 3. 行业差异

- 不同行业PE/PB差异巨大
- 当前实现使用**全历史分位数**（跨行业）
- 建议后续扩展为**分行业分位数**（更精确）

### 4. 数据缺失处理

- 如果基本面数据缺失，策略返回 `HOLD` 信号（不影响回测）
- 组合策略会自动忽略缺失数据的子策略

## 测试

运行测试脚本验证功能：

```bash
python3 tools/test_fundamental.py
```

测试内容：
1. ✅ 基本面数据合并
2. ✅ PE策略信号生成
3. ✅ 组合策略集成

## 后续优化方向

1. **真实数据源集成**：接入 tushare/akshare 获取真实PE/PB数据
2. **分行业分位数**：按行业计算PE分位数，提高精度
3. **多因子策略**：ROE、PB、净利润增长率等综合打分
4. **财务健康策略**：资产负债率、流动比率等风险指标
5. **财报发布延迟**：考虑财报发布延迟，避免未来函数

## 参考

- PE策略实现：`src/strategies/fundamental_pe.py`
- 数据获取模块：`src/data/fundamental_fetcher.py`
- 测试脚本：`tools/test_fundamental.py`
