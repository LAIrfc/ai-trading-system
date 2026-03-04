# 配置文件说明

本目录包含交易、风控与 V3.3 策略相关配置。配置文件均可提交；若含账号/密钥请自行注意安全。

## 一、运行时会被代码加载的配置

| 文件 | 用途 | 说明 |
|------|------|------|
| **trading_config.yaml** | 交易与市场配置 | 主入口 `src/main.py` 使用。账户、交易时间、数据源、策略等。需从 `trading_config.yaml.example` 复制后修改。 |
| **risk_config.yaml** | 风控参数 | 主入口 `src/main.py` 使用。账户/策略/个股/市场风控。需从 `risk_config.yaml.example` 复制后修改。 |
| **news_source_weights.yaml** | 新闻源权重 | `src/data/news/source_weights.py` 加载。新闻情感置信度 = 基础 × 新闻源权重。 |
| **policy_overrides.yaml** | 政策标签人工覆盖 | `src/data/policy/policy_overrides.py` 加载。策略先查此表再回退自动标注，修正次日生效。 |

## 二、模板（需复制为正式配置）

| 文件 | 复制为 | 说明 |
|------|--------|------|
| **trading_config.yaml.example** | trading_config.yaml | 交易配置模板。 |
| **risk_config.yaml.example** | risk_config.yaml | 风控配置模板。 |

## 三、规范/占位（当前无代码加载，供文档与后续接入）

| 文件 | 用途 | 说明 |
|------|------|------|
| **data_sources.yaml** | V3.3 数据源说明 | 情绪/新闻/政策/龙虎榜等数据源与更新频率，设计文档用。 |
| **signal_timing.yaml** | 信号生效时点 | 情绪/新闻/政策/龙虎榜的 T、T+1、T+2 约定，执行层与回测须一致。见 `docs/strategy/SENTIMENT_TECH.md`。 |
| **trading_costs.yaml** | 交易成本与延迟 | 滑点、佣金、印花税、延迟，回测/实盘对齐用。见 `docs/strategy/BACKTEST_AND_LIVE_SPEC.md`。 |
| **policy_industry_mapping.yaml** | 政策行业扩散 | 行业关键词 → 申万行业/指数，占位，对接数据源后填写。 |
| **seat_alias.csv** | 龙虎榜席位别名 | 标准席位名 → 别名，占位，龙虎榜解析用。 |

## 四、快速开始

仅跑策略/回测、不跑 `src/main.py` 时，可不配置交易/风控。若使用主入口：

```bash
cp config/trading_config.yaml.example config/trading_config.yaml
cp config/risk_config.yaml.example config/risk_config.yaml
# 编辑 trading_config.yaml、risk_config.yaml 填入实际参数
```

自动化交易（同花顺等）的账号与规则配置见 `docs/setup/` 对应指南，本目录不提供 `broker_config`/`strategy_rules` 模板，需自行创建。
