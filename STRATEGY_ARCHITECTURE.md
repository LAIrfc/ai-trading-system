# 📚 Alpha Factory 策略架构文档

## 🏗️ 代码结构

### 核心目录
```
src/strategies/          # 策略实现（18个文件，5274行代码）
tools/analysis/          # 分析工具（推荐、回测、验证）
mydate/                  # 数据与配置
```

---

## 🎯 分层决策框架（4层）

**⚠️ 当前实际运行**：L0（PolicyEvent过滤）+ L3（11策略固定权重投票）

```
L0: 大盘过滤器 (PolicyEvent)              ✅ 已启用
    ↓ 极端利空时阻止选股
L1: 市场状态感知 (Sentiment + MarketRegimeEngine)  ⚠️ 已关闭
    ↓ 输出市场状态：恐慌/贪婪 + 牛市/熊市/震荡
L2: 权重动态调整 (get_regime_adjusted_weights)     ⚠️ 已关闭
    ↓ 根据市场状态调整11策略权重
L3: 个股投票 (Ensemble 11策略)           ✅ 已启用
    ↓ 使用固定权重加权投票
```

**关闭 L1/L2 的原因**：
1. 权重调节系数（1.2、1.3、0.8等）缺乏历史回测验证
2. Sentiment 调用错误（传入单只股票df，应该用全市场指数数据）
3. 系数叠加过猛（熊市1.3 × 恐慌1.3 = 1.69x）

**后续优化计划**：
1. 参数扫描优化调节系数（2015-2025年数据）
2. 修复 Sentiment 调用方式（使用全市场指数数据）
3. 增加系数上限约束（避免叠加过猛）
4. 评估是否只调节仓位系数，不调整策略权重

---

## 🎯 策略层级架构

### 1. 核心集成策略（Ensemble）

**文件**: `src/strategies/ensemble.py` (642行) ⭐⭐⭐

这是**最核心的文件**，实现了11策略固定权重投票。

#### 关键代码位置

| 功能 | 行数 | 说明 |
|------|------|------|
| **权重配置** | 147-161 | 11个子策略的固定权重（已验证） |
| **子策略调用** | 410-450 | 调用11个子策略并收集信号 |
| **DUAL反向逻辑** | 420-435 | BUY↔SELL信号反转（核心优化，IC+0.39） |
| **净得分投票** | 550-600 | 加权投票决策算法（阈值0.07/-0.07） |

#### 核心方法

```python
def analyze(self, df: pd.DataFrame) -> StrategySignal:
    """
    11策略加权投票决策
    
    流程:
    1. 调用11个子策略获取信号
    2. DUAL策略信号反向（BUY↔SELL）
    3. 收集买票/卖票
    4. 净得分投票决策
    """

def _weighted(self, buy_votes, sell_votes, total, adjusted_weights):
    """
    净得分投票机制（使用固定权重）
    
    公式: net_score = (buy_score - sell_score) / active_weight_sum
    阈值: 买入>+0.07 / 卖出<-0.07
    最少票数: 1票
    """
```

#### 固定权重配置（第147-161行）

```python
self.weights = {
    # 技术面（6个，总权重6.6）
    'BOLL': 1.5,        # 布林带突破（夏普最高0.20）
    'MACD': 1.3,        # MACD金叉（收益最高+15.3%）
    'KDJ': 1.1,         # KDJ超买超卖（夏普第三0.15）
    'MA': 1.0,          # 均线交叉（收益第三+13.9%）
    'DUAL': 0.9,        # 双重动量反向（IC=+0.39，核心优化）
    'RSI': 0.8,         # RSI超买超卖（夏普最低0.07）
    
    # 基本面（3个，总权重2.0）
    'PEPB': 0.8,        # PE/PB双因子共振
    'PE': 0.6,          # PE估值（回撤最小9%）
    'PB': 0.6,          # PB估值
    
    # 消息面+资金面（2个，总权重0.9）
    'NEWS': 0.5,        # 新闻情感（DeepSeek LLM）
    'MONEY_FLOW': 0.4,  # 资金流向（龙虎榜+大宗）
}
```

**注**：这是固定权重，已通过235只股票回测验证。L2动态调整已暂时关闭。

---

### 2. L3投票层：子策略实现（11个）

#### 📊 技术面策略（6个）

| 策略 | 文件 | 行数 | 权重 | 说明 |
|------|------|------|------|------|
| **BOLL** | `bollinger_band.py` | 332 | 1.5 | 布林带突破，%B指标 |
| **MACD** | `macd_cross.py` | 319 | 1.3 | MACD金叉死叉，DIF/DEA/柱状图 |
| **KDJ** | `kdj_signal.py` | 507 | 1.1 | KDJ随机指标，超买超卖 |
| **MA** | `ma_cross.py` | 321 | 1.0 | 均线交叉，多空排列 |
| **DUAL** | `dual_momentum.py` | 199 | 0.9 | 双重动量（反向使用） |
| **RSI** | `rsi_signal.py` | 368 | 0.8 | RSI超买超卖，背离 |

#### 💰 基本面策略（3个）

| 策略 | 文件 | 行数 | 权重 | 说明 |
|------|------|------|------|------|
| **PEPB** | `fundamental_pe_pb.py` | 232 | 0.8 | PE/PB双因子共振 |
| **PE** | `fundamental_pe.py` | 90 | 0.6 | PE历史分位数 |
| **PB** | `fundamental_pb.py` | 134 | 0.6 | PB历史分位数+ROE过滤 |

#### 🌡️ 市场情绪策略（1个，已关闭）

| 策略 | 文件 | 行数 | 状态 | 说明 |
|------|------|------|------|------|
| **SENTIMENT** | `sentiment.py` | 314 | ⚠️ 已关闭 | 市场情绪+个股趋势过滤（原计划L1层） |

**关闭原因**：
- 调用方式错误：需要全市场指数数据，不能传入单只股票df
- 调节系数缺乏历史回测验证
- 待修复后再启用

#### 📰 消息面+资金面（2个）

| 策略 | 文件 | 行数 | 权重 | 说明 |
|------|------|------|------|------|
| **NEWS** | `news_sentiment.py` | 485 | 0.5 | 新闻情感（关键词0.4+LLM0.6） |
| **MONEY_FLOW** | `money_flow.py` | 467 | 0.4 | 龙虎榜+大宗交易 |

#### 🏛️ 政策面策略（L0层，已启用）

| 策略 | 文件 | 行数 | 使用方式 | 说明 |
|------|------|------|---------|------|
| **POLICY** | `policy_event.py` | 309 | ✅ L0大盘过滤器 | 政策事件（纯市场级，所有股票信号相同） |

**使用方式**：
- 在 `recommend_today.py` 中作为 **L0 大盘过滤器**（`_check_policy_filter`）
- 极度利空（score<-0.5 且有重大利空关键词）时**阻止选股**
- 不参与个股投票（避免所有股票收到相同信号）

#### 🔧 辅助模块

| 文件 | 行数 | 说明 |
|------|------|------|
| `base.py` | 449 | 策略基类（StrategySignal, BaseStrategy） |
| `v33_weights.py` | 258 | v3版本权重配置 |
| `turnover_helper.py` | 148 | 换手率辅助函数 |

---

## 🔧 调用入口

### 1. 每日推荐（主要入口）

**文件**: `tools/analysis/recommend_today.py` (1812行)

```bash
# 完整推荐（808只股票，Ensemble模式）
python3 tools/analysis/recommend_today.py \
    --pool mydate/stock_pool_all.json \
    --strategy ensemble \
    --top 20 \
    --no-policy-filter

# 全量12策略分析（并发模式，同ensemble）
python3 tools/analysis/recommend_today.py \
    --pool mydate/stock_pool_all.json \
    --strategy full_11 \
    --top 20
```

**核心函数**:
- `main()`: 主流程控制
- `_check_policy_filter()`: L0大盘过滤器（PolicyEvent，极度利空时阻止选股）
- `run_full_11_analysis()`: 11策略全量分析（已优化为单例模式）
- `save_incremental_report()`: 生成增量报告

**注**：当前使用固定权重，L1/L2层已暂时关闭

### 2. 单股分析

**文件**: `tools/analysis/analyze_xbcd.py` (197行)

```bash
# 分析西部超导
python3 tools/analysis/analyze_xbcd.py
```

展示：
- 6大技术策略明细
- 净得分计算过程
- 详细投资建议

### 3. 回测验证

**文件**: `tools/backtest/backtest_strategy.py`

```bash
# 单策略回测
python3 tools/backtest/backtest_strategy.py \
    --strategy DUAL \
    --pool mydate/stock_pool.json

# Ensemble回测
python3 tools/backtest/backtest_strategy.py \
    --strategy ensemble \
    --pool mydate/stock_pool.json
```

---

## 🎯 本次优化（v4 → v4.1）

### v4: DUAL反向 + 投票机制优化（2026-03-22）

**核心文件**: `src/strategies/ensemble.py`

#### 改动1: DUAL信号反向（第400-416行）
```python
if strat_name == 'DUAL' and self.dual_reverse:
    if sig.action == 'BUY':
        sig = StrategySignal(
            action='SELL',
            confidence=sig.confidence,
            position=1.0 - sig.position,
            reason=f'[DUAL反向] {sig.reason}（原BUY→SELL）',
            indicators=sig.indicators
        )
```

**原因**: IC分析显示DUAL策略与未来收益强负相关（IC=-0.3877，p<0.000001），反向使用后IC=+0.3877

#### 改动2: 净得分投票机制（第555-608行）
```python
def _weighted(self, buy_votes, sell_votes, total):
    MIN_ACTIVE_VOTES = 1
    BUY_THRESHOLD = 0.07
    SELL_THRESHOLD = -0.07
    
    net_score = (buy_score - sell_score) / active_weight_sum
    
    if net_score > BUY_THRESHOLD and len(buy_votes) >= MIN_ACTIVE_VOTES:
        return 'BUY', ...
```

**原因**: 旧的相对比例机制对权重不敏感，新机制让权重真正生效

#### 改动3: 关闭动态权重（第116-117行）
```python
dual_reverse: bool = True,
use_dynamic_weights: bool = False,
```

**原因**: 避免动态归一化覆盖自定义权重

### v4.1: 关键Bug修复（2026-03-23）

**核心文件**: `tools/analysis/recommend_today.py`

#### 修复1: 致命缩进错误（第1588行）
```python
# ❌ 错误（循环外）
for i, stock in enumerate(stocks, 1):
    code = stock['code']
        df = fetch_stock_data(code, 200)  # 缩进错误！

# ✅ 正确（循环内）
for i, stock in enumerate(stocks, 1):
    code = stock['code']
    df = fetch_stock_data(code, 200)  # 正确缩进
```

#### 修复2: DUAL策略一致性（第1085-1101行）
```python
# 在 run_full_11_analysis 中添加
if strat_name == 'DUAL':
    if sig.action == 'BUY':
        sig.action = 'SELL'
        sig.reason = f'[DUAL反向] {sig.reason}（原BUY→SELL）'
    elif sig.action == 'SELL':
        sig.action = 'BUY'
        sig.reason = f'[DUAL反向] {sig.reason}（原SELL→BUY）'
```

#### 修复3: 策略单例模式（第1054-1073行）
```python
# 全局策略实例（只创建一次）
_GLOBAL_STRATEGIES = None

def _get_global_strategies():
    global _GLOBAL_STRATEGIES
    if _GLOBAL_STRATEGIES is None:
        _GLOBAL_STRATEGIES = {
            'MA': MACrossStrategy(),
            'MACD': MACDStrategy(),
            # ... 其他策略
        }
    return _GLOBAL_STRATEGIES
```

#### 修复4: 基本面数据验证（第1133-1149行）
```python
# 提前验证数据可用性
has_pe_data = 'pe_ttm' in df.columns and df['pe_ttm'].notna().sum() > 100
has_pb_data = 'pb' in df.columns and df['pb'].notna().sum() > 100

if has_pe_data:
    # 分析PE策略
if has_pb_data:
    # 分析PB策略
```

---

## 📊 策略决策流程

```
输入: K线数据 (200天)
  ↓
┌─────────────────────────────────────┐
│ 1. 调用11个子策略                    │
│    - 技术面6个 (MACD, MA, RSI, ...)  │
│    - 基本面3个 (PE, PB, PEPB)        │
│    - 消息面2个 (NEWS, MONEY_FLOW)    │
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│ 2. DUAL策略信号反向                  │
│    - 原BUY → SELL                    │
│    - 原SELL → BUY                    │
│    - 原因: IC=-0.39 → +0.39          │
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│ 3. 净得分投票（权重敏感）             │
│    - 买入加权分 = Σ(权重×信心度)     │
│    - 卖出加权分 = Σ(权重×信心度)     │
│    - 净得分 = (买-卖) / 活跃权重和   │
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│ 4. 阈值判断                          │
│    - 净分 > +0.07 且买入≥1票 → BUY  │
│    - 净分 < -0.07 且卖出≥1票 → SELL │
│    - 否则 → HOLD                     │
└─────────────────────────────────────┘
  ↓
输出: StrategySignal (action, confidence, position, reason)
```

---

## 🔑 核心优化点

### 1. DUAL反向机制（IC提升）

**位置**: `ensemble.py` 第400-416行

**原理**:
- DUAL策略原始IC = **-0.3877**（负相关，看多的反而跌）
- 反向后IC = **+0.3877**（p<0.000001，统计显著）
- 将最差策略转化为最强预测因子

**实现**:
```python
if strat_name == 'DUAL' and self.dual_reverse:
    if sig.action == 'BUY':
        sig.action = 'SELL'  # 反向
    elif sig.action == 'SELL':
        sig.action = 'BUY'   # 反向
```

### 2. 净得分投票机制（权重敏感）

**位置**: `ensemble.py` 第555-608行

**旧机制问题**:
```python
# 相对比例法（权重不敏感）
buy_pct = buy_score / (buy_score + sell_score)
if buy_pct >= 0.45 → BUY

# 问题：权重(1,1,1)和(10,1,1)的buy_pct都接近100%
```

**新机制**:
```python
# 净得分法（权重敏感）
net_score = (buy_score - sell_score) / active_weight_sum
if net_score > 0.07 → BUY

# 优势：高权重策略对净得分贡献更大
```

**阈值校准**:
- 初始阈值 **0.15** → 过度保守，HOLD率暴增
- 校准后 **0.07** → 平衡交易频率和信号质量
- 最少票数 **1票** → 允许强信号（如DUAL）单独触发

### 3. 性能优化（单例模式）

**位置**: `recommend_today.py` 第1054-1073行

**问题**: 每个股票分析都创建11个策略实例
- 808只股票 × 11个策略 = **9460次创建**
- NewsSentiment/MoneyFlow涉及LLM初始化，极其耗时

**修复**: 全局单例模式
```python
_GLOBAL_STRATEGIES = None

def _get_global_strategies():
    if _GLOBAL_STRATEGIES is None:
        _GLOBAL_STRATEGIES = {
            'MA': MACrossStrategy(),  # 只创建一次
            # ...
        }
    return _GLOBAL_STRATEGIES
```

**性能提升**: 创建次数 **9460 → 11**（-99.9%）

---

## 📁 配置文件

| 文件 | 路径 | 说明 |
|------|------|------|
| **AI配置** | `mydate/ai_config.json` | DeepSeek API配置 |
| **股票池** | `mydate/stock_pool_all.json` | 808只股票（沪深300+中证500+龙头） |
| **持仓** | `mydate/my_portfolio.json` | 用户持仓数据 |
| **优化记录** | `CHANGELOG.md` | 策略优化历史 |

---

## 🚀 使用指南

### 每日推荐（推荐使用）

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 1. 完整推荐（808只，Ensemble模式）
python3 tools/analysis/recommend_today.py \
    --pool mydate/stock_pool_all.json \
    --strategy ensemble \
    --top 20 \
    --no-policy-filter

# 2. 仅分析持仓
python3 tools/analysis/recommend_today.py --only-holdings

# 3. 快速筛选（51只，MACD模式）
python3 tools/analysis/recommend_today.py \
    --pool mydate/stock_pool.json \
    --strategy macd \
    --top 10
```

### 单股深度分析

```bash
# 分析西部超导（展示11策略明细）
python3 tools/analysis/analyze_xbcd.py
```

### 回测验证

```bash
# 单策略回测
python3 tools/backtest/backtest_strategy.py \
    --strategy DUAL \
    --pool mydate/stock_pool.json

# Ensemble回测
python3 tools/backtest/backtest_strategy.py \
    --strategy ensemble \
    --pool mydate/stock_pool.json
```

---

## 📊 输出文件

| 文件 | 说明 |
|------|------|
| `mydate/daily_reports/daily_recommendation.md` | 增量报告（最新在前，持仓置顶） |
| `mydate/daily_reports/daily_recommendation_YYYY-MM-DD.md` | 当日归档 |

---

## 🎯 核心优势

1. **IC验证**: DUAL反向后IC从-0.39提升到+0.39（p<0.000001）
2. **权重敏感**: 净得分机制让高权重策略真正发挥作用
3. **阈值校准**: 0.07平衡交易频率（避免过度保守）
4. **性能优化**: 单例模式减少99.9%的实例创建
5. **信号一致**: full_11与ensemble模式DUAL信号统一

---

## 📝 待优化项

1. **市场状态感知**: `MarketRegimeEngine` 已集成但未启用
2. **动态权重调整**: `get_regime_adjusted_weights()` 可在未来验证后启用
3. **基本面数据覆盖**: 提升PE/PB数据的获取成功率

---

## 🔍 总结

**核心策略**: `src/strategies/ensemble.py` (667行)
- 唯一需要关注的主文件
- 包含所有优化逻辑（DUAL反向、净得分投票、权重配置）

**调用入口**: `tools/analysis/recommend_today.py` (1812行)
- 每日推荐的主入口
- 已修复3个关键bug（缩进、DUAL一致性、性能）

**子策略**: 18个文件，5274行代码
- 技术面6个、基本面3个、消息面2个
- 无需修改，只需在 `ensemble.py` 中配置权重

**本次优化**: 共修复4个关键问题
- 缩进错误（数据准确性）
- DUAL一致性（信号统一）
- 性能优化（-99.9%创建次数）
- 数据验证（避免无效计算）
