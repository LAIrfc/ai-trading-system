# 快速参考卡片 🎯

## 🆕 双核动量轮动策略（NEW!）

**一键回测ETF轮动策略**

```bash
# 快速测试（1分钟）
python3 tests/test_dual_momentum_quick.py

# 完整回测（5分钟，生成报告+图表）
python3 tools/backtest/backtest_dual_momentum.py
```

**策略原理**：
- 绝对动量：价格 > 200日均线 → 只买牛市资产
- 相对动量：选涨幅最大的 → 永远骑最快的马
- 每月调仓：自动轮换 → 熊市自动空仓

**适合标的**：沪深300/创业板50/纳指ETF/黄金/国债

**完整指南**：[DUAL_MOMENTUM_GUIDE.md](DUAL_MOMENTUM_GUIDE.md) ⭐

---

## 🪟 Windows vs 🐧 Linux

### Windows 用户

```powershell
# 使用反斜杠 \
python tools\data\kline_fetcher.py 600519
python examples\paper_trading_demo.py

# 或双击运行
scripts/start_windows.bat
```

### Linux 用户

```bash
# 使用正斜杠 /
python3 tools/data/kline_fetcher.py 600519
python3 examples/paper_trading_demo.py
```

**更多详情**：[Windows使用指南](WINDOWS_GUIDE.md)

---

## 🎮 模拟交易（零风险测试）⭐ NEW!

### 启动模拟交易
```bash
# 启动
python3 examples/paper_trading_demo.py

# 模式1: 手动交易（自己控制）
# 模式2: 策略自动（策略自动执行）
```

### Python代码
```python
from src.core.simulator.paper_trading import PaperTradingAccount

# 创建模拟账户（10万初始资金）
account = PaperTradingAccount(initial_capital=100000.0)

# 买入
success, order_id = account.buy('600519', 1800.0, 100)

# 卖出
success, order_id = account.sell('600519', 1850.0, 100)

# 查看账户
account.print_summary()
```

详见：**[模拟交易指南](PAPER_TRADING_GUIDE.md)**

---

## 📊 策略开发（最常用）

### 测试内置策略
```bash
# 交互式
python3 tools/validation/strategy_tester.py --interactive

# 测试均线策略
python3 tools/validation/strategy_tester.py --strategy MA --stocks 600519

# 测试MACD策略
python3 tools/validation/strategy_tester.py --strategy MACD --stocks 600519,000001

# 测试RSI策略
python3 tools/validation/strategy_tester.py --strategy RSI --stocks 600519
```

### 创建新策略
```bash
# 1. 复制模板
cp examples/my_strategy_template.py my_new_strategy.py

# 2. 编辑
nano my_new_strategy.py

# 3. 测试
python3 my_new_strategy.py
```

### 使用策略（Python）
```python
from src.core.strategy.strategy_library import strategy_library
from src.data.realtime_data import MarketDataManager

# 创建策略
strategy = strategy_library.get_strategy('MA', short_window=5, long_window=20)

# 获取数据
manager = MarketDataManager()
data = manager.prepare_strategy_data(['600519'])

# 生成信号
signals = strategy.generate_signals(data)
print(signals)
```

---

## 📡 获取K线数据（NEW!）⭐

### 命令行工具（最快）
```bash
# 获取日K线
python3 tools/data/kline_fetcher.py 600519

# 获取周K线
python3 tools/data/kline_fetcher.py 600519 --period weekly

# 对比历史和实时
python3 tools/data/kline_fetcher.py 600519 --compare

# 导出CSV
python3 tools/data/kline_fetcher.py 600519 --export

# 查看常用股票
python3 tools/data/kline_fetcher.py --list
```

### 完整演示
```bash
python3 examples/get_kline_demo.py
```

---

## 📡 获取数据（Python代码）

### 获取K线数据
```python
from src.data.realtime_data import RealtimeDataFetcher

fetcher = RealtimeDataFetcher()

# 日K线
df = fetcher.get_historical_data('600519', 
    start_date='20240101',
    end_date='20260224',
    period='daily'
)

# 查看数据
print(df.tail())  # 最近5天
print(f"收盘价: {df['close'].iloc[-1]:.2f}")
```

### 实时价格
```python
from src.data.realtime_data import RealtimeDataFetcher

fetcher = RealtimeDataFetcher()

# 单只股票
price = fetcher.get_realtime_price('600519')

# 多只股票
quotes = fetcher.get_realtime_quotes(['600519', '000001'])
```

### 历史数据
```python
# 获取最近100天
df = fetcher.get_historical_data('600519', days=100)

# 指定日期
df = fetcher.get_historical_data('600519', 
    start_date='20240101',
    end_date='20241231'
)
```

---

## 🤖 桌面交易

### 快速测试
```bash
python3 test_desktop_auto.py
```

### 自动化交易
```bash
# 编辑配置
nano examples/desktop_trading_auto.py

# 修改 TEST_CONFIG 部分，然后运行
python3 examples/desktop_trading_auto.py
```

### 手动交易演示
```bash
python3 examples/desktop_trading_demo.py
```

---

## 📚 文档速查

| 文档 | 用途 | 阅读时间 |
|------|------|----------|
| **[PAPER_TRADING_GUIDE.md](PAPER_TRADING_GUIDE.md)** | **模拟交易指南** 🎮 | **10分钟 ⭐** |
| [STRATEGY_QUICKSTART.md](STRATEGY_QUICKSTART.md) | 策略开发入门 | 10分钟 ⭐ |
| [KLINE_DATA_GUIDE.md](KLINE_DATA_GUIDE.md) | K线数据获取 | 10分钟 |
| [STRATEGY_DETAIL.md](../strategy/STRATEGY_DETAIL.md) | 策略详解（6大基础+组合+回测） | 20分钟 ⭐ |
| [STRATEGY_LIST.md](../strategy/STRATEGY_LIST.md) | 策略清单与工具对应 | 5分钟 |
| [SIMPLE_START.md](SIMPLE_START.md) | 环境配置 | 5分钟 |
| [DESKTOP_TRADING_GUIDE.md](../setup/DESKTOP_TRADING_GUIDE.md) | 桌面交易指南 | 10分钟 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 问题排查 | 按需查阅 |

---

## 🔧 常用命令

### 安装依赖
```bash
# 策略开发（最小依赖）
pip3 install --user pandas numpy akshare loguru

# 桌面交易
pip3 install --user pyautogui psutil pillow
sudo apt-get install python3-tk python3-dev -y

# 完整依赖
pip3 install --user -r requirements.txt
```

### 测试系统
```bash
# 简单测试
python3 tests/simple_test.py

# 桌面自动化测试
python3 test_desktop_auto.py

# 策略测试
python3 tools/validation/strategy_tester.py --list
```

---

## 💡 内置策略参数

### MA Strategy (均线)
```python
strategy = strategy_library.get_strategy('MA',
    short_window=5,    # 短期均线（默认5）
    long_window=20,    # 长期均线（默认20）
    stop_loss=0.05,    # 止损5%
    take_profit=0.15   # 止盈15%
)
```

### MACD Strategy
```python
strategy = strategy_library.get_strategy('MACD',
    fast_period=12,    # 快速周期
    slow_period=26,    # 慢速周期
    signal_period=9    # 信号周期
)
```

### RSI Strategy
```python
strategy = strategy_library.get_strategy('RSI',
    period=14,         # RSI周期
    oversold=30,       # 超卖阈值
    overbought=70      # 超买阈值
)
```

---

## 🎯 快速场景

### 场景1：我想用模拟交易测试策略（推荐）⭐
```bash
python3 examples/paper_trading_demo.py
# 选择 2 - 策略自动模式
# 选择策略（如MA）
# 输入股票（如600519,000001）
# 观察策略自动交易
```

### 场景2：我想测试一个策略
```bash
python3 tools/validation/strategy_tester.py --interactive
# 按提示选择策略和股票
```

### 场景2：我想开发新策略
```bash
cp examples/my_strategy_template.py my_strategy.py
nano my_strategy.py  # 编辑策略逻辑
python3 my_strategy.py  # 测试
```

### 场景3：我想看某只股票的实时数据
```python
from src.data.realtime_data import RealtimeDataFetcher

fetcher = RealtimeDataFetcher()
quote = fetcher.get_realtime_quotes(['600519'])['600519']

print(f"价格: {quote['price']}")
print(f"涨跌幅: {quote['change_pct']}%")
```

### 场景4：我想用同花顺自动交易
```bash
# 1. 确保同花顺已安装
ls /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp

# 2. 运行演示
python3 examples/desktop_trading_auto.py
```

---

## 🆘 遇到问题？

### 问题：数据获取失败
```bash
# 升级akshare
pip3 install --user --upgrade akshare

# 检查网络
ping baidu.com
```

### 问题：tkinter警告
```bash
sudo apt-get install python3-tk python3-dev -y
```

### 问题：找不到模块
```bash
# 检查Python路径
python3 -c "import sys; print(sys.path)"

# 确保在正确目录
cd /home/wangxinghan/codetree/ai-trading-system
```

### 问题：同花顺无法启动
```bash
# 手动测试
/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp

# 检查进程
ps aux | grep HevoNext
```

---

## 🔗 外部资源

### 数据源
- AKShare: https://akshare.akfamily.xyz/
- Tushare: https://tushare.pro/
- 东方财富: http://quote.eastmoney.com/

### 学习资源
- 聚宽社区: https://www.joinquant.com/
- 优矿: https://uqer.datayes.com/
- 量化投资书籍推荐

### 工具
- 同花顺模拟炒股
- 东方财富模拟交易

---

## 📞 快速联系

遇到问题？查看：
1. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - 常见问题
2. [STRATEGY_DETAIL.md](../strategy/STRATEGY_DETAIL.md) - 策略说明
3. 代码注释 - 所有代码都有详细注释

---

**记住**: 
- 📊 测试策略：`python3 tools/validation/strategy_tester.py --interactive`
- ✍️ 创建策略：`cp examples/my_strategy_template.py my_strategy.py`
- 📖 查看文档：`cat STRATEGY_QUICKSTART.md`

**Happy Trading! 🚀**
