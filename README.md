# AI量化交易系统（A股）

## 项目简介

基于人工智能的A股量化交易系统，支持策略回测、实盘交易、风险控制和策略文档维护。

**🌐 跨平台支持**：
- ✅ Windows和Linux **自动兼容**，使用相同代码
- ✅ 自动检测系统并适配配置
- ✅ 无需手动修改，开箱即用

详见：[跨平台兼容说明](CROSS_PLATFORM.md) | [Windows指南](WINDOWS_GUIDE.md)

## ⚠️ 风险警告

**本系统涉及真实资金交易，使用前请务必：**
- 充分理解股票交易风险
- 在模拟环境充分测试
- 设置严格的风控参数
- 遵守相关法律法规
- 投资有风险，入市需谨慎

## 系统特性

### 核心功能
- ✅ 实时行情数据获取
- ✅ 多因子特征工程
- ✅ AI模型训练与预测
- ✅ 策略回测引擎
- ✅ 实盘交易执行
- ✅ 多层风控系统
- ✅ **策略文档驱动的严格执行** ⭐
- ✅ **规则引擎和合规检查** ⭐
- ✅ **完整审计追踪** ⭐
- ✅ 策略文档自动维护
- ✅ **双核动量轮动策略（完整实现）** 🆕

### 技术特点
- 模块化设计，易于扩展
- 完善的风控机制
- **策略规则强制执行，避免情绪化交易**
- **所有交易决策可追溯、可复盘**
- 支持多策略并行
- 策略版本管理
- 审批工作流（可选）
- 详细的日志记录

## 🚀 5分钟快速开始

### 🪟 Windows 用户

Windows完全支持！使用更简单：

```powershell
# 安装依赖
pip install pandas numpy akshare loguru

# 双击运行（推荐）
start_windows.bat

# 或命令行
python tools\kline_fetcher.py 600519
python tools\strategy_tester.py --interactive
```

**详见**：[Windows 使用指南](WINDOWS_GUIDE.md) ⭐

---

### 🐧 Linux 用户

```bash
# 安装依赖
pip3 install --user pandas numpy akshare loguru

# 运行测试
python3 tools/kline_fetcher.py 600519
python3 tools/strategy_tester.py --interactive
```

---

### 选择你的起点

#### 📊 策略开发（推荐新手）

开始开发和测试交易策略：

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 1. 安装核心依赖
pip3 install --user pandas numpy akshare loguru

# 2. 获取K线数据（日线/周线/月线）
python3 tools/kline_fetcher.py 600519

# 3. 测试内置策略
python3 tools/strategy_tester.py --interactive

# 4. 查看策略指南
cat STRATEGY_QUICKSTART.md
```

**特点**：
- ✅ **实时K线数据**（和同花顺一致）📈
- ✅ 不需要券商账号
- ✅ 可以先研究策略
- ✅ 用历史数据验证
- ✅ 安全无风险

详见：
- **[K线数据获取指南](KLINE_DATA_GUIDE.md)** 📊
- **[策略开发快速开始](STRATEGY_QUICKSTART.md)** ⭐
- **[模拟交易指南](PAPER_TRADING_GUIDE.md)** 🎮 NEW!

---

#### 🎮 模拟交易（安全测试）⭐ NEW!

使用虚拟资金测试策略，零风险！

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 启动模拟交易
python3 examples/paper_trading_demo.py

# 两种模式：
# 1. 手动交易 - 自己控制买卖
# 2. 策略自动 - 策略自动交易
```

**特点**：
- ✅ **零风险** - 使用虚拟资金，完全安全
- ✅ **真实数据** - 实时行情，真实手续费
- ✅ **完整功能** - 买卖、持仓、盈亏计算
- ✅ **策略测试** - 验证策略有效性
- ✅ **数据保存** - 可回放分析

详见：**[模拟交易指南](PAPER_TRADING_GUIDE.md)** 🎮

---

#### 🤖 桌面交易（实盘交易）

使用同花顺客户端进行实盘交易：

### ⚠️ 首次使用必看

**如果遇到 tkinter 警告导致程序退出：**

```bash
# 先安装系统依赖（需要sudo）
sudo apt-get install python3-tk python3-dev -y
```

详见：[SIMPLE_START.md](SIMPLE_START.md) | [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

### 一键启动 (桌面交易)

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 0. 安装系统依赖（首次必须）
sudo apt-get install python3-tk python3-dev -y

# 1. 安装Python依赖
pip3 install --user pyautogui psutil pillow loguru pyyaml

# 2. 测试系统
python3 simple_test.py

# 3. 一键运行
./scripts/run_desktop_trading.sh
```

**就这么简单！** 如果同花顺已安装且保存了密码，程序会自动登录。

📖 **桌面版详细教程**: [DESKTOP_QUICKSTART.md](DESKTOP_QUICKSTART.md)

### 或使用网页版

```bash
# 运行网页交易演示
python examples/web_trading_demo.py
```

### 详细步骤

1. **环境配置**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **注册同花顺模拟炒股**
   - 访问 https://t.10jqka.com.cn/
   - 免费注册账号

3. **配置文件**
   ```bash
   cp config/broker_config.yaml.example config/broker_config.yaml
   cp config/strategy_rules.yaml.example config/strategy_rules.yaml
   # 编辑 broker_config.yaml 填入账号密码
   ```

4. **开始交易**
   ```bash
   python examples/web_trading_demo.py
   ```

**📚 完整教程**: [快速入门指南](docs/QUICK_START.md)

### 3. 数据准备

```bash
# 下载历史数据
python scripts/download_data.py --start 20200101 --end 20241231

# 计算因子数据
python scripts/calculate_factors.py
```

### 4. 🆕 双核动量轮动策略（完整实现）

**新增功能**：完整的双核动量轮动策略，包含数据获取、回测、可视化！

#### 快速开始

```bash
# 运行完整回测（自动下载数据 + 生成报告 + 绘制图表）
python backtest_dual_momentum.py
```

#### 什么是双核动量策略？

- **绝对动量**：只买处于上升趋势的资产（价格 > 200日均线）
- **相对动量**：在合格资产中，选择涨幅最大的持有
- **定期轮动**：每月调整一次，永远持有最强的资产

**适合标的**：沪深300、创业板50、纳指ETF、黄金ETF、债券ETF

**核心优势**：
- ✅ 熊市保护（自动空仓）
- ✅ 追踪最强趋势
- ✅ 完整风控（止损、熔断）
- ✅ 一键回测验证

#### 使用指南

```bash
# 快速测试（1分钟）
python test_dual_momentum_quick.py

# 完整回测（5分钟）
python backtest_dual_momentum.py

# 查看策略文档
cat strategies/dual_momentum_strategy.md

# 查看使用教程
cat DUAL_MOMENTUM_GUIDE.md
```

**📚 完整教程**：[双核动量策略使用指南](DUAL_MOMENTUM_GUIDE.md) ⭐

---

### 5. 其他策略回测

```bash
# 运行回测
python src/core/backtest/backtest_runner.py --strategy your_strategy --start 20230101 --end 20231231
```

### 6. 实盘交易（谨慎！）

```bash
# 启动实盘交易（确保已充分测试）
python src/main.py --mode live --strategy your_strategy
```

## 项目结构

```
ai-trading-system/
├── config/                 # 配置文件
│   ├── trading_config.yaml    # 交易参数配置
│   ├── risk_config.yaml       # 风控参数配置
│   └── strategy_config.yaml   # 策略参数配置
├── data/                   # 数据目录
│   ├── market_data/           # 市场行情数据
│   ├── factor_data/           # 因子数据
│   └── models/                # 训练好的模型
├── src/                    # 源代码
│   ├── core/                  # 核心模块
│   │   ├── strategy/          # 策略引擎
│   │   ├── risk/              # 风险管理
│   │   ├── execution/         # 交易执行
│   │   └── backtest/          # 回测系统
│   ├── ai/                    # AI模块
│   │   ├── features/          # 特征工程
│   │   ├── models/            # AI模型
│   │   └── prediction/        # 预测服务
│   ├── data/                  # 数据服务
│   │   ├── collectors/        # 数据采集
│   │   └── processors/        # 数据处理
│   └── api/                   # API接口
│       ├── broker/            # 券商接口
│       └── market/            # 行情接口
├── tests/                  # 测试代码
├── docs/                   # 策略文档
├── logs/                   # 日志文件
└── scripts/                # 工具脚本
```

## 风控系统

系统内置多层风控机制：

1. **账户级风控**
   - 单日最大亏损限制
   - 总仓位限制
   - 现金储备要求

2. **策略级风控**
   - 单策略仓位限制
   - 回撤控制
   - 夏普比率监控

3. **个股级风控**
   - 单股最大仓位
   - 止损止盈
   - 涨跌停限制

4. **系统级风控**
   - 交易频率限制
   - 异常检测
   - 紧急熔断

## 策略开发

### 创建新策略

```python
from src.core.strategy.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self, config):
        super().__init__(config)
        
    def generate_signals(self, market_data):
        """生成交易信号"""
        # 实现您的策略逻辑
        pass
        
    def calculate_position_size(self, signal, risk_metrics):
        """计算仓位大小"""
        # 实现仓位管理逻辑
        pass
```

## 策略严格执行系统 ⭐

本系统的核心特色是**策略规则强制执行**机制，确保所有交易都严格按照预定规则进行：

### 工作原理

```
交易信号 → 规则检查 → 风控检查 → 审批(可选) → 执行 → 审计记录
```

### 快速使用

```python
from src.core.strategy import StrategyRuleEngine, StrategyExecutor

# 1. 加载策略规则
rule_engine = StrategyRuleEngine("my_strategy")
rule_engine.import_rules("config/strategy_rules.json")

# 2. 创建执行器
executor = StrategyExecutor(
    strategy_name="my_strategy",
    strategy_document=strategy_doc,
    rule_engine=rule_engine,
    risk_manager=risk_manager
)

# 3. 处理信号（自动检查规则）
order = executor.process_signal(signal, market_data)

# 4. 查看审计日志
logs = executor.get_audit_logs(order_id=order.order_id)
```

**详细文档**: 请查看 [策略严格执行指南](docs/STRATEGY_EXECUTION_GUIDE.md)

### 核心优势

- ✅ **纪律性**: 避免情绪化交易，严格执行规则
- ✅ **可追溯**: 每笔交易都有完整的审计记录
- ✅ **可复盘**: 基于数据持续优化策略规则
- ✅ **风险可控**: 多层规则自动拦截风险交易

## 自动化交易 🌐

本系统支持两种自动化方式，无需等待券商API申请即可开始测试！

### 方式1: 桌面客户端自动化 ⭐ (推荐)

直接控制本地安装的同花顺客户端：

```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

# 配置（如已保存密码可自动登录）
config = {'auto_start': True}
broker = TonghuashunDesktop(config)

# 自动启动并登录
if broker.login():
    # 买入（使用F1快捷键）
    broker.buy('600519', 1800.0, 100)
    broker.close()
```

**优势**: 
- ✅ 更稳定 - 不受网页改版影响
- ✅ 更快速 - 键盘快捷键操作
- ✅ 更简单 - 已保存密码可自动登录
- ✅ 已安装就能用 - 路径: `/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp`

**详细文档**: [桌面自动化指南](docs/DESKTOP_TRADING_GUIDE.md)

### 方式2: 网页自动化

通过浏览器控制网页版同花顺：

### 支持的平台

- ✅ **同花顺桌面客户端** - 推荐，更稳定
- ✅ **同花顺模拟炒股网页版** - 开箱即用
- ✅ **其他券商模拟盘** - 可自行适配

### 快速开始

```python
from src.api.broker.tonghuashun_simulator import TonghuashunSimulator

# 配置
config = {
    'username': 'your_username',
    'password': 'your_password',
    'headless': False,  # 可以看到浏览器操作
}

# 初始化
broker = TonghuashunSimulator(config)

# 登录
if broker.login():
    # 获取账户信息
    account = broker.get_account_info()
    print(f"总资产: {account.total_assets:,.2f}元")
    
    # 买入
    success, order_id = broker.buy('600519', 1800.0, 100)
    
    # 登出
    broker.logout()

broker.close()
```

**详细文档**: [网页自动化交易指南](docs/WEB_TRADING_GUIDE.md)

### 为什么使用网页自动化？

- ⚡ **快速验证**: 无需API申请，立即开始测试
- 💰 **零成本**: 模拟盘交易不需要真实资金
- 🛡️ **安全**: 在模拟环境充分测试后再上实盘
- 🔄 **真实**: 模拟盘环境与实盘高度相似

## 数据源

支持的数据源：
- **akshare**：免费，数据全面
- **tushare**：需要积分，数据质量高
- **baostock**：免费，适合历史回测

## 券商接口

支持的券商（需自行申请）：
- 华泰证券
- 中信证券
- 国金证券
- 其他支持程序化交易的券商

## 监控和报警

- 实时PnL监控
- 策略性能监控
- 风险指标监控
- 微信/邮件报警

## 注意事项

1. **合规性**：确保交易行为符合监管要求
2. **资金安全**：建议使用独立账户，设置止损
3. **测试充分**：实盘前务必充分回测和模拟
4. **持续监控**：实盘运行时需要密切监控
5. **风险分散**：不要把所有资金投入一个策略

## 开发路线图

- [ ] Phase 1: 数据采集和预处理
- [ ] Phase 2: 回测引擎开发
- [ ] Phase 3: AI模型集成
- [ ] Phase 4: 风控系统完善
- [ ] Phase 5: 实盘接口对接
- [ ] Phase 6: 监控和报警系统
- [ ] Phase 7: 策略文档系统

## 许可证

本项目仅供学习和研究使用，使用者需自行承担一切交易风险。

## 联系方式

如有问题或建议，请提交 Issue。

---

**再次提醒：股市有风险，投资需谨慎！**
