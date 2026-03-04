# AI量化交易系统 - 完整目录结构

> 生成时间：2026-03-02  
> 项目路径：`/home/wangxinghan/codetree/ai-trading-system`

## 📁 完整目录树

```
ai-trading-system/
│
├── 📄 根目录文件
│   ├── README.md                      # 项目主文档（功能说明、快速开始）
│   ├── LICENSE                        # MIT许可证 + 风险提示
│   ├── requirements.txt               # Python依赖包列表
│   ├── .gitignore                     # Git忽略规则
│   └── run_daily.py                   # ⭐ 每日策略分析入口（双核动量）
│
├── ⚙️ config/                         # 配置文件目录（详见 config/README.md）
│   ├── README.md                      # 配置说明（必读）
│   ├── trading_config.yaml(.example)  # 交易配置（主入口用）
│   ├── risk_config.yaml(.example)     # 风控配置（主入口用）
│   ├── news_source_weights.yaml       # 新闻源权重（V3.3）
│   ├── policy_overrides.yaml          # 政策标签人工覆盖（V3.3）
│   ├── data_sources.yaml              # 数据源说明（占位）
│   ├── signal_timing.yaml             # 信号时点规范（占位）
│   ├── trading_costs.yaml             # 交易成本与延迟（占位）
│   ├── policy_industry_mapping.yaml   # 政策行业映射（占位）
│   └── seat_alias.csv                 # 龙虎榜席位别名（占位）
│
├── 🧠 src/                            # 核心源代码
│   ├── __init__.py
│   ├── main.py                        # 主入口程序
│   │
│   ├── strategies/                    # 交易策略实现（11单策略+4组合，见 docs/strategy/STRATEGY_LIST.md）
│   │   ├── __init__.py
│   │   ├── base.py                    # 策略基类
│   │   ├── ma_cross.py                # MA均线交叉
│   │   ├── macd_cross.py              # MACD交叉
│   │   ├── rsi_signal.py              # RSI
│   │   ├── bollinger_band.py          # 布林带
│   │   ├── kdj_signal.py              # KDJ
│   │   ├── dual_momentum.py           # 双核动量（单股）
│   │   ├── fundamental_pe.py          # PE基本面
│   │   ├── fundamental_pb.py          # PB基本面
│   │   ├── fundamental_pe_pb.py       # PE+PB双因子
│   │   ├── sentiment.py               # 市场情绪（V3.3）
│   │   ├── news_sentiment.py          # 新闻情感（V3.3）
│   │   ├── policy_event.py            # 政策事件（V3.3）
│   │   ├── money_flow.py              # 龙虎榜/大宗（V3.3）
│   │   ├── ensemble.py                # 组合：7策略 / V33组合(11策略)
│   │   └── turnover_helper.py         # 换手率辅助
│   │
│   ├── core/                          # 核心框架模块
│   │   ├── __init__.py
│   │   ├── portfolio.py               # 持仓管理（虚拟持仓、交易执行）
│   │   ├── signal_engine.py           # 信号引擎（双核动量分析）
│   │   ├── trade_journal.py           # 交易日志生成
│   │   │
│   │   ├── risk/                      # 风控模块
│   │   │   ├── __init__.py
│   │   │   └── risk_manager.py        # 风险管理器
│   │   │
│   │   ├── strategy/                  # 策略框架（规则执行系统）
│   │   │   ├── __init__.py
│   │   │   ├── base_strategy.py      # 策略基类（框架层）
│   │   │   ├── strategy_executor.py  # 策略执行器（规则检查）
│   │   │   ├── strategy_library.py   # 策略库管理
│   │   │   ├── strategy_rule_engine.py  # 规则引擎
│   │   │   ├── strategy_document.py  # 策略文档管理
│   │   │   ├── dual_momentum_strategy.py  # 双核动量策略实现
│   │   │   └── example_strategy.py   # 策略示例
│   │   │
│   │   └── simulator/                 # 模拟交易
│   │       ├── __init__.py
│   │       └── paper_trading.py      # 纸面交易模拟器
│   │
│   ├── data/                          # 数据获取模块
│   │   ├── __init__.py
│   │   │
│   │   ├── fetchers/                  # 数据抓取器（新架构）
│   │   │   ├── __init__.py
│   │   │   ├── market_data.py        # 市场行情数据
│   │   │   ├── realtime_data.py      # 实时数据
│   │   │   ├── etf_data_fetcher.py   # ETF数据获取
│   │   │   ├── fundamental_fetcher.py  # 基本面数据（PE/PB/市值/ROE）
│   │   │   └── data_prefetch.py      # 日线主备容错（Sina→东方财富→腾讯），见 docs/data/API_INTERFACES_AND_FETCHERS.md
│   │   │
│   │   ├── collectors/                # 数据采集器
│   │   │   ├── __init__.py
│   │   │   └── market_data_collector.py
│   │   │
│   │   ├── etf_data_fetcher.py        # ← 兼容层（重导出）
│   │   ├── fundamental_fetcher.py    # ← 兼容层
│   │   └── realtime_data.py           # ← 兼容层
│   │
│   ├── api/                           # 券商接口层
│   │   ├── __init__.py
│   │   └── broker/                    # 券商自动化
│   │       ├── __init__.py
│   │       ├── tonghuashun_desktop.py    # 同花顺桌面客户端自动化
│   │       ├── tonghuashun_simulator.py  # 同花顺模拟炒股网页版
│   │       └── web_broker_base.py        # Web券商基类
│   │
│   ├── utils/                         # 工具模块
│   │   └── pool_loader.py             # 通用股票池加载器
│   │
│   ├── ai/                            # AI模块（预留扩展）
│   │   └── __init__.py
│   │
│   └── config/                        # 平台配置
│       └── platform_config.py        # 跨平台配置（Windows/Linux）
│
├── 🔧 tools/                          # 运维工具脚本
│   ├── README.md                      # 工具说明文档
│   │
│   ├── data/                          # 数据管理工具
│   │   ├── kline_fetcher.py          # K线数据获取工具
│   │   ├── refresh_stock_pool.py      # 股票池刷新（合并+基本面过滤）
│   │   └── quarterly_update.py       # 季度定期更新（指数成分+龙头）
│   │
│   ├── backtest/                      # 回测工具
│   │   ├── batch_backtest.py         # 大规模批量回测（500只股票）
│   │   ├── cross_validate.py         # 策略交叉验证
│   │   ├── backtest_dual_momentum.py  # 双核动量策略回测
│   │   └── compare_fundamental.py    # 技术策略 vs 基本面策略对比
│   │
│   ├── analysis/                      # 分析工具
│   │   ├── recommend_today.py        # ⭐ 每日选股推荐（MACD/7策略组合）
│   │   ├── analyze_single_stock.py   # 单股多策略分析（11大策略）
│   │   ├── portfolio_strategy_analysis.py  # 持仓多策略分析（11大策略）
│   │   └── generate_trade_report.py  # 双核动量交易报告生成
│   │
│   ├── optimization/                  # 参数优化
│   │   └── optimize_macd.py          # MACD参数优化
│   │
│   ├── portfolio/                    # 持仓管理
│   │   └── daily_check.py            # 每日持仓检查
│   │
│   └── validation/                    # 验证与手工测试（与 tests/ 单元测试区分）
│       ├── strategy_tester.py        # 策略测试器（交互式）
│       ├── test_fundamental.py       # 基本面策略测试
│       ├── test_industry_pe.py        # 行业PE测试
│       ├── test_pb_strategy.py       # PB策略测试
│       ├── test_turnover_helper.py   # 换手率辅助测试
│       ├── test_turnover_integration.py  # 换手率集成测试
│       ├── test_all_fundamental.py   # 所有基本面测试
│       ├── validate_turnover_effect.py   # 换手率效果验证
│       └── check_validation_progress.sh  # 验证进度检查脚本
│
├── 📖 examples/                       # 示例代码
│   ├── __init__.py
│   ├── get_kline_demo.py             # K线数据获取示例
│   ├── paper_trading_demo.py         # 模拟交易示例
│   ├── desktop_trading_demo.py       # 桌面交易示例
│   ├── desktop_trading_auto.py      # 桌面自动交易示例
│   ├── web_trading_demo.py          # 网页交易示例
│   ├── desktop_trading_demo.py      # 桌面交易示例
│   ├── strict_execution_demo.py     # 严格执行示例
│   └── my_strategy_template.py      # 策略模板
│
├── 🧪 tests/                          # 单元测试
│   ├── __init__.py
│   ├── simple_test.py                # 简单系统测试
│   ├── test_system.py                # 系统测试
│   ├── test_cross_platform.py        # 跨平台测试
│   ├── test_desktop_auto.py          # 桌面自动化测试
│   └── test_dual_momentum_quick.py   # 双核动量快速测试
│
├── 📜 scripts/                        # Shell/Bat脚本
│   ├── quick_start.sh                # 快速启动脚本
│   ├── run_desktop_trading.sh        # 桌面交易启动脚本
│   ├── install_direct.sh             # 直接安装脚本
│   ├── install_tkinter.sh            # Tkinter安装脚本
│   ├── fix_environment.sh            # 环境修复脚本
│   └── start_windows.bat             # Windows启动脚本
│
├── 📚 docs/                           # 文档目录（目录结构见本文件）
│   ├── DESIGN.md                      # 系统设计文档
│   │
│   ├── setup/                         # 安装和快速开始指南
│   │   ├── QUICK_START.md            # 通用快速开始
│   │   ├── WINDOWS_GUIDE.md          # Windows完整指南
│   │   ├── CROSS_PLATFORM.md         # 跨平台兼容说明
│   │   ├── DESKTOP_TRADING_GUIDE.md  # 桌面交易指南（含快速开始）
│   │   ├── WEB_TRADING_GUIDE.md      # 网页交易指南
│   │   ├── TONGHUASHUN_SIMULATOR_GUIDE.md  # 同花顺模拟器指南
│   │   ├── PAPER_TRADING_GUIDE.md   # 模拟交易指南
│   │   ├── KLINE_DATA_GUIDE.md      # K线数据获取指南
│   │   ├── TROUBLESHOOTING.md        # 故障排除
│   │   ├── TROUBLESHOOTING_TKINTER.md  # Tkinter故障排除
│   │   └── GIT_GUIDE.md              # Git使用指南
│   │
│   ├── strategy/                      # 策略文档
│   │   ├── STRATEGY_LIST.md           # 策略清单（11单策略+组合，与工具对应）
│   │   ├── STRATEGY_QUICKSTART.md     # 策略开发快速开始
│   │   ├── STRATEGY_DETAIL.md         # 策略详细说明（6大基础+组合+回测）
│   │   ├── STRATEGY_EXECUTION_GUIDE.md # 策略严格执行指南
│   │   ├── STRATEGY_HOLD_REASONS.md   # 策略观望/失败原因说明
│   │   ├── DUAL_MOMENTUM_GUIDE.md     # 双核动量指南（含策略规范与工作流）
│   │   ├── V33_DESIGN_SPEC.md         # V3.3 设计规格（含落地与评审摘要）
│   │   └── V33_落地与状态.md          # V3.3 完成状态
│   │
│   ├── fundamental/                   # 基本面分析文档
│   │   ├── FUNDAMENTAL_STRATEGY_GUIDE.md  # 基本面策略指南
│   │   ├── FUNDAMENTAL_DATA.md             # 基本面数据与分析、使用计划（合并）
│   │   ├── FUNDAMENTAL_REAL_TRADING_STANDARDS.md  # 实盘交易标准
│   │   ├── TURNOVER_RATE_ANALYSIS.md       # 换手率分析
│   │   └── TURNOVER_VALIDATION_RESULTS.md  # 换手率验证结果
│   │
│   ├── analysis/                      # 分析报告文档
│   │   ├── QUICK_REFERENCE.md        # 快速参考
│   │   ├── TRADE_ANALYSIS_REPORT.md  # 交易分析报告
│   │   └── VALIDATION_REPORT.md      # 验证报告
│   │
│   ├── reports/                       # 报告说明（实际报告输出在 mydate/daily_reports/）
│   │   └── README.md
│   │
│   └── images/                        # 图片资源
│       ├── dual_momentum_backtest_result.png  # 双核动量回测结果图
│       └── ths_screenshot.png         # 同花顺截图
│
├── 📊 mydate/                         # 数据文件目录（股票池、持仓、回测结果）
│   ├── stock_pool.json               # 赛道龙头池（100只，7大赛道）
│   ├── stock_pool_600.json           # 指数成分池（826只，HS300+ZZ500）
│   ├── stock_pool_all.json           # 综合股票池（869只=812个股+57ETF）
│   ├── etf_pool.json                 # ETF池（57只，8大类别）
│   ├── my_portfolio.json              # 我的持仓
│   ├── portfolio_state.json          # 持仓状态
│   ├── portfolio_daily_records.csv   # 持仓每日记录
│   ├── portfolio_daily_summary.csv   # 持仓每日摘要
│   ├── market_fundamental_cache.json  # 基本面数据缓存
│   ├── backtest_results.json         # 回测结果
│   ├── cross_validation_results.csv  # 交叉验证结果
│   ├── macd_param_optimization.csv   # MACD参数优化结果
│   ├── turnover_validation_results.json  # 换手率验证结果
│   ├── dual_momentum_trades.csv       # 双核动量交易记录
│   ├── trade_log.jsonl                # 交易日志（JSON Lines格式）
│   └── daily_reports/                 # 每日报告目录
│       ├── report_2026-02-24.md
│       ├── report_2026-02-25.md
│       └── daily_recommendation_2026-03-02.md
│
├── 💾 mycache/                        # 缓存文件目录
│   ├── fundamental/                   # 基本面数据缓存
│   │   ├── industry_all.json          # 行业分类数据
│   │   ├── industry_pe_cninfo_20260302.json  # 行业PE数据
│   │   ├── index_components_000300.json  # 沪深300成分股
│   │   └── index_components_000905.json  # 中证500成分股
│   └── market_data/                    # 市场数据缓存
│
├── 📝 mylog/                          # 日志文件目录
│   ├── backtest_500_log.txt           # 500只股票回测日志
│   ├── dual_momentum_backtest.log     # 双核动量回测日志
│   └── turnover_validation_150.log    # 换手率验证日志
│
└── 🐍 myvenv/                         # Python虚拟环境（本地开发用）
    ├── bin/                           # 可执行文件
    ├── lib/                           # Python库
    ├── include/                       # 头文件
    └── pyvenv.cfg                     # 虚拟环境配置
```

## 📋 关键文件说明

### 🎯 核心入口文件

| 文件 | 说明 | 用途 |
|------|------|------|
| `run_daily.py` | 每日策略分析入口 | 双核动量轮动策略每日运行 |
| `src/main.py` | 主程序入口 | 系统主入口（预留） |

### 📊 数据文件

| 文件/目录 | 说明 | 数量/内容 |
|-----------|------|----------|
| `mydate/stock_pool_all.json` | 综合股票池 | 869只（812个股+57ETF） |
| `mydate/stock_pool.json` | 赛道龙头池 | 100只（7大赛道） |
| `mydate/stock_pool_600.json` | 指数成分池 | 826只（HS300+ZZ500） |
| `mydate/etf_pool.json` | ETF池 | 57只（8大类别） |
| `mydate/my_portfolio.json` | 持仓数据 | 当前持仓 |
| `mydate/daily_reports/` | 每日报告 | 策略分析报告 |

### 🔧 核心工具

| 工具 | 路径 | 功能 |
|------|------|------|
| 每日选股推荐 | `tools/analysis/recommend_today.py` | 多策略组合选股 |
| 持仓分析 | `tools/analysis/portfolio_strategy_analysis.py` | 11大策略分析持仓 |
| 批量回测 | `tools/backtest/batch_backtest.py` | 大规模回测验证 |
| 股票池刷新 | `tools/data/refresh_stock_pool.py` | 更新股票池 |
| 策略测试器 | `tools/validation/strategy_tester.py` | 交互式策略测试 |

### 📚 重要文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 项目说明 | `README.md` | 功能、快速开始、使用指南 |
| 系统设计 | `docs/DESIGN.md` | 架构设计、模块说明 |
| 目录结构 | 本文件 `DIRECTORY_OVERVIEW.md` | 项目结构详细说明（原 STRUCTURE 已合并） |
| Windows指南 | `docs/setup/WINDOWS_GUIDE.md` | Windows完整使用指南 |
| 策略快速开始 | `docs/strategy/STRATEGY_QUICKSTART.md` | 策略开发快速开始 |
| 策略详解 | `docs/strategy/STRATEGY_DETAIL.md` | 6大基础策略+组合+回测 |
| 双核动量指南 | `docs/strategy/DUAL_MOMENTUM_GUIDE.md` | 双核动量策略与规范 |
| 数据接口与容错 | `docs/data/API_INTERFACES_AND_FETCHERS.md` | 主备数据源、接口明细、落地步骤 |

## 🗂️ 目录分类统计

### 代码文件统计

- **策略实现**: 17个策略相关文件（`src/strategies/`，含11单策略+4组合+辅助，见 STRATEGY_LIST.md）
- **核心模块**: 16个核心文件（`src/core/`）
- **数据获取**: 7个数据文件（`src/data/`）
- **工具脚本**: 19个工具文件（`tools/`）
- **示例代码**: 9个示例文件（`examples/`）
- **测试代码**: 6个测试文件（`tests/`）

### 文档文件统计

- **安装指南**: 13个文档（`docs/setup/`）
- **策略文档**: 12个文档（`docs/strategy/`，已合并/删除冗余后）
- **基本面文档**: 5个文档（`docs/fundamental/`，DATA 合并后）
- **分析报告**: 3个文档（`docs/analysis/`）

### 数据文件统计

- **股票池**: 4个JSON文件（100/826/869只股票）
- **持仓数据**: 3个JSON文件 + 2个CSV文件
- **回测结果**: 多个JSON/CSV文件
- **缓存数据**: 基本面数据、市场数据缓存

## 🚀 快速导航

### 新手入门
1. 阅读 `README.md` 了解项目
2. 查看 `docs/setup/QUICK_START.md` 快速开始
3. 运行 `tools/analysis/recommend_today.py` 体验选股功能

### 策略开发
1. 阅读 `docs/strategy/STRATEGY_QUICKSTART.md`
2. 参考 `examples/my_strategy_template.py` 创建策略
3. 使用 `tools/validation/strategy_tester.py` 测试策略

### 每日运行
1. 运行 `run_daily.py` 执行双核动量策略
2. 查看 `mydate/daily_reports/` 生成的报告
3. 使用 `tools/portfolio/daily_check.py` 检查持仓

### 数据分析
1. 使用 `tools/data/kline_fetcher.py` 获取K线数据
2. 运行 `tools/backtest/batch_backtest.py` 进行回测
3. 查看 `docs/analysis/` 中的分析报告

---

**最后更新**: 2026-03-04  
**项目路径**: `/home/wangxinghan/codetree/ai-trading-system`
