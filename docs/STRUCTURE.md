# 项目目录结构

> 更新日期：2026-03-02

```
ai-trading-system/
│
├── src/                           # 🧠 核心源码
│   ├── strategies/                # 交易策略实现
│   │   ├── base.py                    # 策略基类
│   │   ├── macd_cross.py              # MACD交叉策略
│   │   ├── ma_cross.py                # 均线交叉策略（含换手率辅助）
│   │   ├── rsi_signal.py              # RSI信号策略
│   │   ├── bollinger_band.py          # 布林带策略
│   │   ├── kdj_signal.py              # KDJ信号策略
│   │   ├── fundamental_pe.py          # PE基本面策略（分行业分位数）
│   │   ├── fundamental_pb.py          # PB基本面策略
│   │   ├── fundamental_pe_pb.py       # PE+PB双因子策略
│   │   ├── ensemble.py                # 组合投票策略
│   │   ├── dual_momentum.py           # 双核动量策略
│   │   └── turnover_helper.py         # 换手率辅助模块
│   │
│   ├── core/                      # 核心框架
│   │   ├── portfolio.py               # 持仓管理
│   │   ├── signal_engine.py           # 信号引擎
│   │   ├── trade_journal.py           # 交易日志
│   │   ├── risk/                      # 风控模块
│   │   │   └── risk_manager.py            # 风险管理器
│   │   ├── strategy/                  # 策略框架
│   │   │   ├── base_strategy.py           # 策略基类（框架层）
│   │   │   ├── strategy_executor.py       # 策略执行器
│   │   │   ├── strategy_library.py        # 策略库
│   │   │   └── strategy_rule_engine.py    # 规则引擎
│   │   └── simulator/                # 模拟交易
│   │       └── paper_trading.py           # 纸面交易
│   │
│   ├── data/                      # 数据获取
│   │   ├── fetchers/                  # 数据抓取器
│   │   │   ├── fundamental_fetcher.py     # 基本面数据（PE/PB/市值）
│   │   │   ├── etf_data_fetcher.py        # ETF数据
│   │   │   ├── market_data.py             # 行情数据
│   │   │   └── realtime_data.py           # 实时数据
│   │   ├── collectors/                # 数据采集器
│   │   │   └── market_data_collector.py
│   │   ├── fundamental_fetcher.py     # ← 兼容层（重导出）
│   │   ├── etf_data_fetcher.py        # ← 兼容层
│   │   └── realtime_data.py           # ← 兼容层
│   │
│   ├── api/                       # 券商接口
│   │   └── broker/
│   │       ├── tonghuashun_desktop.py     # 同花顺桌面端
│   │       ├── tonghuashun_simulator.py   # 同花顺模拟
│   │       └── web_broker_base.py         # Web券商基类
│   │
│   ├── utils/                     # 工具模块
│   │   └── pool_loader.py             # 通用股票池加载器
│   │
│   ├── ai/                        # AI模块（预留）
│   ├── config/                    # 平台配置
│   └── main.py                    # 主入口
│
├── tools/                         # 🔧 运维工具
│   ├── data/                      # 数据管理
│   │   ├── refresh_stock_pool.py      # 股票池刷新（合并+基本面过滤）
│   │   ├── quarterly_update.py        # 季度定期更新
│   │   └── kline_fetcher.py           # K线数据获取
│   │
│   ├── backtest/                  # 回测工具
│   │   ├── batch_backtest.py          # 大规模批量回测
│   │   ├── cross_validate.py          # 策略交叉验证
│   │   └── backtest_dual_momentum.py  # 双核动量回测
│   │
│   ├── analysis/                  # 分析工具
│   │   ├── recommend_today.py         # 每日选股推荐
│   │   └── generate_trade_report.py   # 交易报告生成
│   │
│   ├── optimization/              # 参数优化
│   │   └── optimize_macd.py           # MACD参数优化
│   │
│   ├── portfolio/                 # 持仓管理
│   │   └── daily_check.py            # 每日持仓检查
│   │
│   └── testing/                   # 测试验证
│       ├── validate_turnover_effect.py    # 换手率效果验证
│       ├── test_fundamental.py        # 基本面策略测试
│       ├── test_industry_pe.py        # 行业PE测试
│       ├── test_pb_strategy.py        # PB策略测试
│       └── ...
│
├── mydate/                        # 📊 数据文件（股票池、持仓、回测结果等）
│   ├── stock_pool_all.json            # ★ 综合股票池（869只=812个股+57ETF）
│   ├── stock_pool.json                # 赛道龙头池（100只，7大赛道）
│   ├── stock_pool_600.json            # 指数成分池（826只，HS300+ZZ500）
│   ├── etf_pool.json                  # ETF池（57只，8大类别）
│   ├── market_fundamental_cache.json  # 基本面数据缓存
│   ├── my_portfolio.json              # 我的持仓
│   ├── portfolio_state.json           # 持仓状态
│   ├── backtest_results.json          # 回测结果
│   ├── daily_reports/                 # 每日报告
│   └── trade_log.jsonl                # 交易日志
│
├── mycache/                       # 💾 缓存文件（基本面数据、市场数据）
│   └── market_data/                    # 市场数据缓存
│
├── mylog/                         # 📝 日志文件
│   └── *.log                           # 各类日志
│
├── config/                        # ⚙️ 配置文件
│   ├── trading_config.yaml            # 交易配置（主配置）
│   ├── risk_config.yaml               # 风控配置
│   └── *.yaml.example                 # 配置模板
│
├── docs/                          # 📚 文档
│   ├── DESIGN.md                      # 系统设计
│   ├── STRUCTURE.md                   # 目录结构（本文件）
│   ├── strategy/                      # 策略文档
│   ├── fundamental/                   # 基本面文档
│   ├── setup/                         # 安装/部署文档
│   ├── analysis/                      # 分析报告文档
│   ├── reports/                       # 生成的报告
│   └── images/                        # 图片资源
│
├── examples/                      # 📖 示例代码
├── tests/                         # 🧪 单元测试
├── scripts/                       # 📜 Shell脚本
├── mylog/                         # 📝 日志文件（新目录）
├── logs/                          # 📝 日志（旧目录，保留兼容）
├── mycache/                       # 💾 缓存文件（新目录）
├── cache/                         # 💾 缓存（旧目录，保留兼容）
│
├── run_daily.py                   # 每日运行入口
├── requirements.txt               # Python依赖
├── README.md                      # 项目说明
└── LICENSE                        # 开源协议
```

## 股票池体系

| 文件 | 内容 | 数量 | 用途 |
|------|------|------|------|
| `stock_pool_all.json` | 综合池（个股+ETF，含过滤） | 869只 | **主力池**，推荐/回测/扫描 |
| `stock_pool.json` | 7大赛道龙头 | 100只 | 精选快速扫描 |
| `stock_pool_600.json` | HS300+ZZ500成分 | 826只 | 指数成分基础 |
| `etf_pool.json` | 行业/宽基/跨境ETF | 57只 | ETF独立分析 |

### 过滤规则
- PE TTM：0 ~ 100（排除亏损和泡沫）
- 市值：> 30亿
- 排除ST / *ST / 退市

### 更新机制
```bash
# 日常合并刷新
python3 tools/data/refresh_stock_pool.py

# 季度更新（指数成分+龙头+基本面）
python3 tools/data/quarterly_update.py

# 检查是否需要更新
python3 tools/data/quarterly_update.py --check
```

## 策略体系

| 策略 | 类型 | 文件 | 说明 |
|------|------|------|------|
| MACD交叉 | 技术面 | `macd_cross.py` | 金叉/死叉信号 |
| MA交叉 | 技术面 | `ma_cross.py` | 均线交叉+换手率辅助 |
| RSI信号 | 技术面 | `rsi_signal.py` | 超买超卖 |
| 布林带 | 技术面 | `bollinger_band.py` | 通道突破 |
| KDJ信号 | 技术面 | `kdj_signal.py` | 随机指标 |
| PE策略 | 基本面 | `fundamental_pe.py` | 分行业PE分位数 |
| PB策略 | 基本面 | `fundamental_pb.py` | 市净率 |
| PE+PB双因子 | 基本面 | `fundamental_pe_pb.py` | 双因子共振 |
| 组合投票 | 集成 | `ensemble.py` | 多策略加权投票 |

## 常用命令

```bash
# 每日持仓检查
python3 tools/portfolio/daily_check.py

# 今日选股推荐
python3 tools/analysis/recommend_today.py --pool stock_pool_all.json

# 大规模回测
python3 tools/backtest/batch_backtest.py --pool data/stock_pool_all.json --count 500

# MACD参数优化
python3 tools/optimization/optimize_macd.py
```
