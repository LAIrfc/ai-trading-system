# 项目结构说明

## 目录结构

```
ai-trading-system/
├── src/                    # 核心源代码
│   ├── strategies/        # 策略模块（统一策略系统）
│   │   ├── base.py        # 策略基类 + 回测引擎
│   │   ├── ma_cross.py    # MA均线交叉策略
│   │   ├── macd_cross.py  # MACD策略
│   │   ├── rsi_signal.py  # RSI策略
│   │   ├── bollinger_band.py  # 布林带策略
│   │   ├── kdj_signal.py  # KDJ策略
│   │   ├── dual_momentum.py  # 双核动量策略
│   │   ├── fundamental_pe.py  # PE估值策略（基本面）
│   │   └── ensemble.py    # 组合策略
│   │
│   ├── data/              # 数据模块
│   │   ├── fetchers/      # 数据获取器
│   │   │   ├── market_data.py      # 市场数据
│   │   │   ├── realtime_data.py    # 实时行情
│   │   │   ├── fundamental_fetcher.py  # 基本面数据
│   │   │   └── etf_data_fetcher.py  # ETF数据
│   │   ├── collectors/    # 数据采集器
│   │   └── processors/   # 数据处理器
│   │
│   ├── core/              # 核心模块
│   │   ├── strategy/      # 旧策略系统（可能已废弃）
│   │   ├── risk/          # 风控模块
│   │   └── simulator/     # 模拟交易
│   │
│   └── api/               # 外部接口
│       ├── broker/        # 券商接口
│       └── market/        # 市场接口
│
├── tools/                 # 工具脚本（已分类）
│   ├── backtest/          # 回测工具
│   ├── optimization/      # 参数优化
│   ├── analysis/          # 分析报告
│   ├── data/              # 数据工具
│   └── testing/           # 测试工具
│
├── docs/                  # 文档
│   ├── guides/            # 使用指南
│   ├── reference/         # 参考文档
│   └── deprecated/        # 已废弃文档
│
├── examples/              # 示例代码
├── tests/                 # 测试代码
├── data/                  # 数据目录
├── config/                 # 配置文件
└── scripts/               # 脚本文件
```

## 核心模块说明

### 策略系统 (`src/strategies/`)

**统一策略接口**：所有策略继承 `Strategy` 基类，返回 `StrategySignal`

**已实现策略**：
- 技术面：MA, MACD, RSI, BOLL, KDJ, DUAL（6个）
- 基本面：PE（1个）
- 组合：Ensemble（3种模式）

### 数据模块 (`src/data/`)

**数据获取器** (`fetchers/`)：
- `market_data.py`: 市场数据（日线）
- `realtime_data.py`: 实时行情
- `fundamental_fetcher.py`: 基本面数据（PE/PB/ROE）
- `etf_data_fetcher.py`: ETF数据

**向后兼容**：`from src.data.fundamental_fetcher import ...` 仍然可用

### 工具脚本 (`tools/`)

**分类组织**：
- `backtest/`: 回测相关
- `optimization/`: 参数优化
- `analysis/`: 分析报告
- `data/`: 数据工具
- `testing/`: 测试工具

## 导入路径

### 推荐使用（新路径）

```python
# 策略
from src.strategies.ma_cross import MACrossStrategy
from src.strategies.ensemble import EnsembleStrategy

# 数据获取器
from src.data.fetchers.fundamental_fetcher import FundamentalFetcher
from src.data.fetchers.realtime_data import RealtimeDataFetcher
```

### 向后兼容（旧路径）

```python
# 以下导入仍然可用
from src.data.fundamental_fetcher import FundamentalFetcher
from src.data.realtime_data import RealtimeDataFetcher
```

## 注意事项

1. **策略系统**：主要使用 `src/strategies/`，`src/core/strategy/` 为旧系统
2. **数据获取**：统一使用 `src/data/fetchers/` 下的模块
3. **工具脚本**：已按功能分类，便于查找和维护
