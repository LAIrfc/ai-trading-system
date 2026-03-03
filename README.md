# AI量化交易系统（A股）

## 项目简介

基于人工智能的A股量化交易系统，支持策略回测、实盘交易、风险控制和策略文档维护。

**🌐 跨平台支持**：
- ✅ Windows和Linux **自动兼容**，使用相同代码
- ✅ 自动检测系统并适配配置
- ✅ 无需手动修改，开箱即用

详见：[跨平台兼容说明](docs/setup/CROSS_PLATFORM.md) | [Windows完整指南](docs/setup/WINDOWS_GUIDE.md) | [Windows快速导航](docs/setup/WINDOWS_README.md)

## ⚠️ 风险警告

**本系统涉及真实资金交易，使用前请务必：**
- 充分理解股票交易风险
- 在模拟环境充分测试
- 设置严格的风控参数
- 遵守相关法律法规
- 投资有风险，入市需谨慎

## 系统特性

### 核心功能
- ✅ **策略选股系统** ⭐ - 多策略组合从股票池挑选优质股票
- ✅ **股票池管理** - 支持多个股票池（100只/800只/全市场），定期更新
- ✅ **持仓分析** - 使用8个策略分析持仓，给出买卖建议
- ✅ **8个内置策略** - MA/MACD/RSI/BOLL/KDJ/DUAL/PE/PB，可单独或组合使用
- ✅ **基本面分析** - PE/PB估值、ROE筛选、行业PE分位数、资金流分析
- ✅ 实时行情数据获取
- ✅ 策略回测引擎
- ✅ 多层风控系统
- ✅ **自动化交易（可选）** - 支持桌面客户端和网页自动化
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

## 🚀 快速开始

> **选择你的起点**：
> - 🪟 **Windows用户** → [Windows快速导航](docs/setup/WINDOWS_README.md) | [Windows完整指南](docs/setup/WINDOWS_GUIDE.md)
> - 🐧 **Linux用户** → [通用快速开始](docs/setup/QUICK_START.md)
> - 🖥️ **桌面客户端用户** → [桌面客户端快速开始](docs/setup/DESKTOP_QUICKSTART.md)
> - 🔧 **遇到tkinter错误** → [Tkinter故障排除](docs/setup/TROUBLESHOOTING_TKINTER.md)

### 🪟 Windows 用户

Windows完全支持！使用更简单：

```powershell
# 安装依赖
pip install pandas numpy akshare loguru

# 双击运行（推荐）
scripts\start_windows.bat

# 或命令行
python tools\kline_fetcher.py 600519
python tools\strategy_tester.py --interactive
```

**详见**：[Windows完整指南](docs/setup/WINDOWS_GUIDE.md) | [Windows快速导航](docs/setup/WINDOWS_README.md) ⭐

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

#### 🎯 策略选股（核心功能）⭐ 推荐

**根据策略从股票池中挑选优质股票，系统核心功能！**

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 1. 使用7策略组合（MA+MACD+RSI+BOLL+KDJ+DUAL+PE）从股票池选股
python3 tools/analysis/recommend_today.py --pool mydate/stock_pool_600.json --strategy ensemble --top 20

# 2. 使用单MACD策略选股
python3 tools/analysis/recommend_today.py --pool mydate/stock_pool.json --strategy macd --top 10

# 3. 分析持仓（使用所有8个策略）
python3 tools/analysis/portfolio_strategy_analysis.py
```

**功能特点**：
- ✅ **多策略组合** - 7个技术策略 + 1个基本面策略，综合评分
- ✅ **股票池管理** - 支持多个股票池（100只/800只/全市场）
- ✅ **基本面过滤** - PE/PB估值、ROE筛选、行业PE分位数
- ✅ **资金流分析** - 主力资金流向信号
- ✅ **持仓分析** - 多策略分析现有持仓，给出买卖建议
- ✅ **实时数据** - 使用最新行情数据
- ✅ **评分排序** - 按综合评分推荐TOP N只股票

**输出内容**：
- 📊 每只股票的8个策略信号（买入/卖出/观望）
- 📈 综合评分和排名
- 💰 资金流状态
- 📋 推荐理由和建议仓位

详见：
- **[策略选股工具说明](#策略选股系统)** ⭐
- **[股票池管理](#股票池管理)**
- **[持仓分析](#持仓分析)**

---

#### 📊 策略开发（学习策略）

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
cat docs/strategy/STRATEGY_QUICKSTART.md
```

**特点**：
- ✅ **实时K线数据**（和同花顺一致）📈
- ✅ 不需要券商账号
- ✅ 可以先研究策略
- ✅ 用历史数据验证
- ✅ 安全无风险

详见：
- **[K线数据获取指南](docs/setup/KLINE_DATA_GUIDE.md)** 📊
- **[策略开发快速开始](docs/strategy/STRATEGY_QUICKSTART.md)** ⭐

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

详见：**[模拟交易指南](docs/setup/PAPER_TRADING_GUIDE.md)** 🎮

---

#### 🤖 桌面交易（实盘交易）

使用同花顺客户端进行实盘交易：

### ⚠️ 首次使用必看

**如果遇到 tkinter 警告导致程序退出：**

```bash
# 先安装系统依赖（需要sudo）
sudo apt-get install python3-tk python3-dev -y
```

详见：[Tkinter故障排除](docs/setup/TROUBLESHOOTING_TKINTER.md) | [故障排除](docs/setup/TROUBLESHOOTING.md)

---

### 一键启动 (桌面交易)

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 0. 安装系统依赖（首次必须）
sudo apt-get install python3-tk python3-dev -y

# 1. 安装Python依赖
pip3 install --user pyautogui psutil pillow loguru pyyaml

# 2. 测试系统
python3 tests/simple_test.py

# 3. 一键运行
./scripts/run_desktop_trading.sh
```

**就这么简单！** 如果同花顺已安装且保存了密码，程序会自动登录。

📖 **桌面版详细教程**: [桌面客户端快速开始](docs/setup/DESKTOP_QUICKSTART.md)

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

**📚 完整教程**: [快速入门指南](docs/setup/QUICK_START.md)

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
python tools/backtest_dual_momentum.py
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
python tests/test_dual_momentum_quick.py

# 完整回测（5分钟）
python tools/backtest_dual_momentum.py

# 查看策略文档
cat docs/strategy/DUAL_MOMENTUM_GUIDE.md
```

**📚 完整教程**：[双核动量策略使用指南](docs/strategy/DUAL_MOMENTUM_GUIDE.md) ⭐

---

### 5. 其他策略回测

```bash
# 运行回测
python src/core/backtest/backtest_runner.py --strategy your_strategy --start 20230101 --end 20231231
```

---

## 🎯 策略选股系统（核心功能）

### 功能概述

系统核心功能：**根据多策略组合从股票池中挑选优质股票**，帮助你做出投资决策。

### 快速使用

```bash
# 从800只股票池中，使用7策略组合选出TOP 20
python3 tools/analysis/recommend_today.py \
    --pool mydate/stock_pool_600.json \
    --strategy ensemble \
    --top 20 \
    --fundamental

# 从100只股票池中，使用MACD策略选出TOP 10
python3 tools/analysis/recommend_today.py \
    --pool mydate/stock_pool.json \
    --strategy macd \
    --top 10
```

### 支持的策略

系统内置 **8个策略**，可单独使用或组合使用：

**技术面策略（6个）**：
1. **MA（均线交叉）** - 均线多头/空头排列
2. **MACD** - MACD金叉/死叉
3. **RSI** - 相对强弱指标
4. **BOLL（布林带）** - 价格突破上下轨
5. **KDJ** - 随机指标
6. **DUAL（双动量）** - 价格动量 + 均线确认

**基本面策略（2个）**：
7. **PE（市盈率估值）** - 分行业PE分位数
8. **PB（市净率估值）** - 分行业PB分位数 + ROE过滤

**组合策略**：
- **Ensemble（7策略组合）** - 综合6个技术策略 + PE策略，加权投票

### 选股流程

```
股票池 → 获取数据 → 策略分析 → 基本面过滤 → 资金流分析 → 综合评分 → TOP N推荐
```

### 输出内容

选股报告包含：
- 📊 每只股票的8个策略信号（买入/卖出/观望）
- 📈 综合评分和排名
- 💰 资金流状态
- 📋 推荐理由和建议仓位

**详细输出格式**：请查看 `tools/analysis/recommend_today.py` 的运行结果或代码注释。

---

## 📊 股票池管理

### 股票池文件

系统支持多个股票池，位于 `mydate/` 目录：

- **stock_pool.json** - 100只精选股票（7大热门板块龙头）
- **stock_pool_600.json** - 800只股票（HS300 + ZZ500成分股）
- **stock_pool_all.json** - 全市场股票（含ETF）
- **etf_pool.json** - ETF池（行业ETF + 宽基ETF）

### 股票池结构

```json
{
  "description": "800只股票池（HS300 + ZZ500）",
  "created_at": "2026-02-25",
  "stocks": {
    "证券": [
      {"code": "600030", "name": "中信证券", "pe_ttm": 15.2, "market_cap_yi": 3500},
      ...
    ],
    "银行": [...],
    ...
  }
}
```

### 股票池更新

```bash
# 刷新股票池（包含基本面过滤）
python3 tools/data/refresh_stock_pool.py

# 季度更新（同步指数成分调整）
python3 tools/data/quarterly_update.py
```

### 股票池过滤规则

- ✅ PE 0-100（排除异常值）
- ✅ 市值 > 30亿
- ✅ 非ST股票
- ✅ 可选的ROE过滤（PB策略）

---

## 💼 持仓分析

### 功能说明

使用所有8个策略分析你的持仓，给出买卖建议。

### 使用方法

```bash
# 分析持仓（使用所有8个策略）
python3 tools/analysis/portfolio_strategy_analysis.py

# 每日持仓检查（包含策略分析）
python3 tools/portfolio/daily_check.py
```

### 持仓文件

持仓数据保存在 `mydate/my_portfolio.json`，具体格式和示例请查看工具文档。

### 分析输出

分析报告包含：
- 📊 每只持仓的8个策略信号（买入/卖出/观望）
- 💰 实时价格和盈亏情况
- 📈 综合建议（买入/卖出/观望）
- 💡 资金流状态（如有）

**详细说明**：请查看 `tools/analysis/portfolio_strategy_analysis.py` 的代码注释和输出示例。

---

## 📈 策略回测验证

### 大规模回测

```bash
# 对股票池中的500只股票进行回测
python3 tools/backtest/batch_backtest.py \
    --pool mydate/stock_pool_600.json \
    --count 500 \
    --datalen 800
```

### 策略对比回测

```bash
# 对比纯技术策略 vs 技术+基本面策略
python3 tools/backtest/compare_fundamental.py
```

## 策略与设计文档

与**策略体系升级（情绪/消息/政策）**相关的设计规格与落地说明：

| 文档 | 说明 |
|------|------|
| [**V3.3 设计规格书**](docs/strategy/V33_DESIGN_SPEC.md) | 情绪、消息、政策三大类策略的完整设计规格（信号规则、参数表、附录） |
| [**V3.3 落地计划**](docs/strategy/V33_IMPLEMENTATION_PLAN.md) | 分阶段实施计划（Phase 0～6）、与现有代码衔接方式 |
| [**V3 设计评审**](docs/strategy/V3_DESIGN_REVIEW.md) | 对设计文档的审阅意见与澄清建议 |
| [**策略优化路线图**](docs/strategy/STRATEGY_OPTIMIZATION_ROADMAP.md) | 情绪/消息/政策/龙虎榜的优化方向与实施进度 |
| [**V3.3 落地与状态**](docs/strategy/V33_落地与状态.md) | Phase 0～6 完成情况、产出、落地过程与自检（已全部落地） |
| [**回测与实盘规范**](docs/strategy/BACKTEST_AND_LIVE_SPEC.md) | 未来函数约束、参数敏感性、成本与延迟、人工覆盖（Phase 6） |
| [**策略清单**](docs/strategy/STRATEGY_LIST.md) | 11 单策略 + 4 组合、注册表、与各分析/回测工具的对应关系 |

其他策略文档：[策略开发快速开始](docs/strategy/STRATEGY_QUICKSTART.md) | [策略详解](docs/strategy/STRATEGY_DETAIL.md) | [双核动量指南](docs/strategy/DUAL_MOMENTUM_GUIDE.md) | [策略严格执行指南](docs/strategy/STRATEGY_EXECUTION_GUIDE.md)

---

## 项目结构

```
ai-trading-system/
├── README.md               # 项目说明
├── LICENSE                  # 许可证
├── requirements.txt         # Python 依赖
│
├── config/                 # 配置文件
│   ├── trading_config.yaml
│   ├── risk_config.yaml
│   └── *.yaml.example         # 配置模板
│
├── src/                    # 核心源代码
│   ├── main.py                # 主入口
│   ├── core/                  # 核心模块
│   │   ├── strategy/             # 策略引擎（含双核动量策略）
│   │   ├── risk/                 # 风险管理
│   │   ├── execution/            # 交易执行
│   │   ├── backtest/             # 回测系统
│   │   └── simulator/            # 模拟交易
│   ├── ai/                    # AI 模块
│   ├── data/                  # 数据服务
│   │   ├── etf_data_fetcher.py   # ETF 数据获取
│   │   ├── realtime_data.py      # 实时数据
│   │   └── collectors/           # 数据采集器
│   ├── api/                   # 接口层
│   │   └── broker/               # 券商自动化（同花顺桌面/网页）
│   └── config/                # 平台配置
│
├── tools/                  # 工具脚本
│   ├── backtest_dual_momentum.py # 回测工具
│   ├── generate_trade_report.py  # 交易报告生成
│   ├── kline_fetcher.py          # K线数据获取
│   └── strategy_tester.py        # 策略测试器
│
├── tests/                  # 测试代码
├── examples/               # 使用示例
├── scripts/                # Shell/Bat 脚本
├── docs/                   # 所有文档（指南、设计、报告）
│   └── setup/              # 安装和快速开始指南
├── mydate/                 # 数据文件（股票池、持仓、回测结果等）
├── mycache/                # 缓存文件（基本面数据、市场数据）
├── mylog/                  # 日志文件
└── myoutput/               # 输出文件（图表、报告等）
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

**详细文档**: 请查看 [策略严格执行指南](docs/strategy/STRATEGY_EXECUTION_GUIDE.md)

### 核心优势

- ✅ **纪律性**: 避免情绪化交易，严格执行规则
- ✅ **可追溯**: 每笔交易都有完整的审计记录
- ✅ **可复盘**: 基于数据持续优化策略规则
- ✅ **风险可控**: 多层规则自动拦截风险交易

## 🤖 自动化交易（可选）

> **说明**：自动化交易功能是可选的。你可以：
> - ✅ 使用策略选股功能，根据推荐结果**手动交易**
> - ✅ 或使用自动化功能，让系统自动执行交易

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

**详细文档**: [桌面自动化指南](docs/setup/DESKTOP_TRADING_GUIDE.md)

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

**详细文档**: [网页自动化交易指南](docs/setup/WEB_TRADING_GUIDE.md)

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
