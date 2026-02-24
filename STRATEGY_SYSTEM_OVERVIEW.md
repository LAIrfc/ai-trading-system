# 策略系统概览 📊

恭喜！策略系统已经搭建完成。这是您现在拥有的完整功能。

---

## 🎯 系统架构

```
ai-trading-system/
├── src/
│   ├── core/strategy/
│   │   ├── base_strategy.py           # 策略基类
│   │   ├── strategy_library.py        # 策略库（含3个内置策略）
│   │   ├── strategy_executor.py       # 策略执行器
│   │   └── strategy_rule_engine.py    # 规则引擎
│   │
│   └── data/
│       ├── realtime_data.py            # 实时行情数据
│       └── collectors/                 # 数据采集器
│
├── tools/
│   └── strategy_tester.py              # 策略测试工具
│
├── examples/
│   ├── my_strategy_template.py         # 策略模板
│   ├── desktop_trading_demo.py         # 桌面交易演示
│   └── desktop_trading_auto.py         # 自动化交易演示
│
└── docs/
    ├── STRATEGY_GUIDE.md               # 策略开发指南
    ├── STRATEGY_QUICKSTART.md          # 快速开始
    └── DESKTOP_TRADING_GUIDE.md        # 桌面交易指南
```

---

## ✅ 已实现的功能

### 1. 实时行情数据 📡

**数据源**: AKShare（免费，无需API key）

**功能**:
- ✅ 获取实时价格
- ✅ 批量获取多只股票行情
- ✅ 获取历史K线数据（日/周/月）
- ✅ 市场概览统计
- ✅ 股票搜索
- ✅ 数据缓存机制

**使用示例**:
```python
from src.data.realtime_data import RealtimeDataFetcher

fetcher = RealtimeDataFetcher()
price = fetcher.get_realtime_price('600519')
print(f"茅台现价: {price}")
```

---

### 2. 内置交易策略 📈

#### 策略1: 均线策略 (MA)
- 金叉/死叉判断
- 参数可调：短期/长期周期
- 适用：趋势市场

#### 策略2: MACD策略
- MACD金叉/死叉
- 柱状图转正/转负
- 适用：中期趋势

#### 策略3: RSI策略
- 超买/超卖判断
- RSI回升/回落
- 适用：震荡市场

**使用示例**:
```python
from src.core.strategy.strategy_library import strategy_library

# 使用内置策略
strategy = strategy_library.get_strategy('MA', short_window=5, long_window=20)

# 或者使用自定义策略
from my_strategy_template import MyStrategy
strategy = MyStrategy()
```

---

### 3. 策略测试工具 🧪

**命令行测试**:
```bash
# 交互式
python3 tools/strategy_tester.py --interactive

# 快速测试
python3 tools/strategy_tester.py --strategy MA --stocks 600519

# 多股票测试
python3 tools/strategy_tester.py --strategy MACD --stocks 600519,000001,600036
```

**功能**:
- ✅ 快速测试任意策略
- ✅ 实时获取市场数据
- ✅ 显示交易信号
- ✅ 显示最新行情
- ✅ 支持参数配置

---

### 4. 策略开发框架 ✍️

**策略模板**: `examples/my_strategy_template.py`

**核心方法**:
```python
class MyStrategy(BaseStrategy):
    def generate_signals(self, market_data):
        """生成买卖信号"""
        # 你的策略逻辑
        pass
    
    def calculate_position_size(self, signal, account_info):
        """计算仓位"""
        # 你的仓位管理逻辑
        pass
```

**特点**:
- ✅ 继承自BaseStrategy，接口统一
- ✅ 支持参数配置
- ✅ 内置测试代码
- ✅ 详细注释说明

---

### 5. 数据管理 💾

**MarketDataManager** - 智能数据管理器

**功能**:
- ✅ 数据缓存（避免频繁请求）
- ✅ 自动更新（可配置间隔）
- ✅ 合并实时+历史数据
- ✅ 为策略准备标准化数据

**使用示例**:
```python
from src.data.realtime_data import MarketDataManager

manager = MarketDataManager(update_interval=3)

# 为策略准备数据
market_data = manager.prepare_strategy_data(
    stock_codes=['600519', '000001'],
    historical_days=100
)

# market_data格式:
# {
#     '600519': DataFrame(包含open, high, low, close, volume),
#     '000001': DataFrame(...)
# }
```

---

### 6. 规则引擎 + 风控 🛡️

**StrategyRuleEngine** - 强制执行交易规则

**功能**:
- ✅ 入场规则检查
- ✅ 出场规则检查
- ✅ 仓位限制
- ✅ 价格范围限制
- ✅ 自定义规则

**StrategyExecutor** - 策略执行器

**功能**:
- ✅ 信号生成
- ✅ 规则验证
- ✅ 风控检查
- ✅ 订单管理
- ✅ 审计日志

---

### 7. 桌面交易 🤖

**TonghuashunDesktop** - 同花顺桌面自动化

**功能**:
- ✅ 自动启动同花顺
- ✅ 自动登录（需已保存密码）
- ✅ 键盘快捷键交易（F1买入/F2卖出）
- ✅ 查询账户/持仓/订单
- ✅ 比网页版更稳定

**使用示例**:
```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

broker = TonghuashunDesktop({'auto_start': True, 'auto_login': True})
broker.launch_app()
broker.login()

# 买入
success, result = broker.buy('600519', 1000.0, 100)
```

---

## 🚀 快速开始

### 新手推荐：从测试内置策略开始

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 1. 安装依赖
pip3 install --user pandas numpy akshare loguru

# 2. 交互式测试
python3 tools/strategy_tester.py --interactive
```

### 进阶：开发自己的策略

```bash
# 1. 复制模板
cp examples/my_strategy_template.py my_first_strategy.py

# 2. 编辑策略逻辑
nano my_first_strategy.py

# 3. 测试
python3 my_first_strategy.py
```

### 高级：实盘交易

```bash
# 1. 确保同花顺已安装并配置
ls /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp

# 2. 运行演示
python3 examples/desktop_trading_auto.py
```

---

## 📊 数据流程

```
1. 实时数据获取
   ↓
2. 历史数据合并
   ↓
3. 策略分析
   ↓
4. 生成信号
   ↓
5. 规则检查
   ↓
6. 风控验证
   ↓
7. 执行交易
   ↓
8. 记录审计
```

---

## 🎓 学习路径

### 第1周：理解系统
1. 阅读 [STRATEGY_QUICKSTART.md](STRATEGY_QUICKSTART.md)
2. 测试内置策略，理解信号生成
3. 阅读策略库代码 `src/core/strategy/strategy_library.py`

### 第2周：开发策略
1. 复制策略模板 `my_strategy_template.py`
2. 实现一个简单策略（如均线策略的变体）
3. 测试你的策略

### 第3周：优化策略
1. 添加更多指标（MACD、RSI等）
2. 组合多个条件
3. 调整参数，观察效果

### 第4周：回测验证
1. 用历史数据回测
2. 计算收益率、夏普比率
3. 分析最大回撤

### 第5周：模拟交易
1. 在模拟盘测试
2. 记录每笔交易
3. 总结经验

### 第6周+：实盘交易
1. 小资金实盘
2. 持续监控和优化
3. 记录和复盘

---

## 💡 下一步建议

### 1. 收集策略灵感

**推荐来源**:
- 📚 量化书籍（《量化投资策略与技术》等）
- 🌐 量化社区（聚宽、优矿、米筐等）
- 📊 技术分析书籍
- 💬 量化交流群

**策略类型**:
- 趋势跟踪
- 均值回归
- 突破策略
- 网格交易
- 动量策略
- 反转策略

### 2. 完善技术指标库

当前可以添加：
- KDJ指标
- 布林带
- ATR（波动率）
- OBV（成交量）
- CCI、BOLL等

### 3. 开发回测系统

核心功能：
- 历史数据回测
- 绩效指标计算
- 可视化分析
- 参数优化

### 4. 增强风控系统

- 动态止损止盈
- 最大回撤控制
- 仓位动态调整
- 相关性分析

---

## 📖 文档索引

- **[README.md](README.md)** - 项目总览
- **[STRATEGY_QUICKSTART.md](STRATEGY_QUICKSTART.md)** - 策略快速开始 ⭐
- **[STRATEGY_GUIDE.md](docs/STRATEGY_GUIDE.md)** - 策略开发详细指南
- **[SIMPLE_START.md](SIMPLE_START.md)** - 环境配置
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - 问题排查
- **[DESKTOP_QUICKSTART.md](DESKTOP_QUICKSTART.md)** - 桌面交易快速开始
- **[DESKTOP_TRADING_GUIDE.md](docs/DESKTOP_TRADING_GUIDE.md)** - 桌面交易详细指南

---

## 🛠️ 工具清单

### 开发工具
- `tools/strategy_tester.py` - 策略测试
- `examples/my_strategy_template.py` - 策略模板
- `examples/desktop_trading_auto.py` - 自动化交易

### 核心模块
- `src/core/strategy/` - 策略相关
- `src/data/` - 数据相关
- `src/api/broker/` - 券商接口

---

## 💬 接下来做什么？

### 立即可以做的：

1. **测试内置策略** ⏱️ 5分钟
   ```bash
   python3 tools/strategy_tester.py --strategy MA --stocks 600519
   ```

2. **查看策略代码** ⏱️ 10分钟
   ```bash
   cat src/core/strategy/strategy_library.py
   ```

3. **创建第一个策略** ⏱️ 30分钟
   ```bash
   cp examples/my_strategy_template.py my_first_strategy.py
   nano my_first_strategy.py
   python3 my_first_strategy.py
   ```

### 需要进一步开发的：

- [ ] 技术指标库完善
- [ ] 回测系统
- [ ] 可视化图表
- [ ] 策略组合
- [ ] 实时监控面板
- [ ] 通知系统（微信/邮件）

---

## 🎉 总结

您现在拥有一个功能完整的量化交易策略系统：

✅ **数据获取** - 实时+历史数据  
✅ **策略框架** - 3个内置策略 + 可扩展  
✅ **测试工具** - 快速验证策略  
✅ **交易执行** - 桌面自动化  
✅ **风控系统** - 规则引擎  
✅ **完整文档** - 从入门到精通  

**开始您的量化交易之旅吧！** 🚀

---

有任何问题，随时查阅文档或调试代码。记住：

> "先在模拟盘测试，再用小资金实盘，最后逐步放大。"  
> "策略简单有效，风控严格到位。"  
> "持续学习优化，记录总结复盘。"

祝交易顺利！📈
