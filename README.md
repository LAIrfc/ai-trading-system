# AI量化交易系统（A股）

基于多策略组合的A股量化交易系统，支持策略选股、回测验证、持仓分析和实盘自动化交易。

**跨平台支持**：Windows 和 Linux 自动兼容，无需手动修改，开箱即用。

---

## 核心亮点

- **12大策略 x 5大维度**：技术+基本面+消息+政策+情绪+资金，全方位覆盖
- **双引擎并行选股**：均值回归（超跌反弹）+ 趋势跟随（强势突破），互补降低单策略风险
- **三代引擎自动切换**：v5.2（等权基线） / v6.1（因子正交+风险平价） / v6.4（生产级组合决策引擎），IC 驱动自动选择最优版本
- **v6.4.3 生产级引擎**（2026-03）：Conditional IC、Alpha 相关性惩罚、EWMA+Shrinkage 协方差、RU-CVaR 极端情景模拟、统一凸优化、路径稳定性、执行反馈闭环
- **3年实证回测**：863只股票 x 145个调仓周期，v6.4 累计+42.51%，最大回撤-43.16%，跑赢沪深300 约31%
- **本地缓存**：863只K线+815只PE/PB缓存，回测秒级完成
- **AI驱动分析**：新闻情感+政策事件（关键词40%+LLM语义60%）
- **资金追踪**：龙虎榜机构席位+大宗交易折价分析

---

## 风险警告

**本系统涉及真实资金交易，使用前请务必：**
- 充分理解股票交易风险，在模拟环境充分测试
- 设置严格的风控参数，遵守相关法律法规
- 本项目仅供学习和研究使用，使用者需自行承担一切交易风险

---

## 系统架构总览

```
全市场股票池（863只：沪深300 + 中证500 成分股）
    |
[L0: PolicyEvent 大盘过滤]
|   极度利空（央行/财政/监管重大政策）时暂停选股
    |
[12策略并行分析]
|   技术面 6 个 + 基本面 3 个 + 消息/政策/情绪/资金各 1 个
    |
[双引擎调度]
|-- 均值回归引擎 --> 超跌榜（TOP 15）
|   |   12策略加权打分，重 PB/BOLL/RSI 超卖信号
|   |   回测表现：2198笔，平均+0.80%，胜率52.55%
|
|-- 趋势引擎     --> 趋势榜（TOP 5）
|   |   4层因子（基础趋势/技术确认/相对强度/量价配合）
|   |   经 863只 x 3.3年 x 19种权重配置优化
    |
[HybridVersionSelector: IC 驱动版本切换]
|   根据实时因子 IC 自动选择处理版本：
|-- v5.2: 等权 + tanh（IC 低时使用，简单稳健）
|-- v6.1: 因子正交 + Rank Norm + Volatility Scaling
|-- v6.4: 生产级组合决策引擎（IC 高时使用，全部模块）
    |
[v6.4 处理链路]
    Alpha Layer --> Conditional IC --> Risk Model --> Optimizer --> Execution
    |
[双优股票识别]
|   同时出现在超跌榜和趋势榜的标记为"双优"（估值+动能双重确认）
    |
最终推荐（TOP 20 统一持仓权重 + 操作建议）
```

---

## 双引擎选股详解

### 引擎一：均值回归（超跌反弹）

**目标**：捕捉短期超跌后的反弹机会，寻找被市场过度惩罚的股票。

**12策略加权打分**（基于808只 x 3.3年回测优化的固定权重）：

| 策略 | 权重 | 核心逻辑 |
|------|------|---------|
| PB | 2.00 | 市净率处于3年历史低位（<20%分位），价值被低估 |
| BOLL | 1.95 | 价格触及布林带下轨（2倍标准差），短期超卖 |
| RSI | 1.82 | RSI(14) < 30，超卖区间，反弹概率大 |
| PE | 1.68 | 市盈率处于3年历史低位（<25%分位） |
| PEPB | 1.61 | PE+PB联合低估（双因子都在低位） |
| KDJ | 1.50 | K/D值在20以下形成金叉，超卖反转 |
| DUAL | 1.39 | 双核动量（绝对+相对动量同时触发） |
| MACD | 0.50 | DIF上穿DEA形成金叉（辅助确认） |
| MA | 0.30 | 短期均线上穿长期均线（辅助确认） |
| NEWS | 0.32 | 近24h新闻情感偏正面 |
| SENTIMENT | 0.32 | 全市场情绪未到恐慌（恐慌贪婪指数） |
| MONEY_FLOW | 0.30 | 龙虎榜机构净买入/大宗交易折价低 |

**选股逻辑**：每只股票跑12个策略 → 加权求和得到总分 → 按总分排序 → 取 TOP 15。

**回测表现**（808只，2023-01 ~ 2026-03）：
- 交易次数：2,198笔，持仓周期：5日
- 平均收益：+0.80% | 胜率：52.55% | Sharpe：0.163
- 最大单笔：+42.89% | 最大亏损：-18.07%

### 引擎二：趋势跟随（强势突破）

**目标**：捕捉中短期上涨趋势，跟随强势股的惯性。

**4层因子体系**（经863只 x 740日 x 19种权重组合优化，当前配置 Sharpe 最优=0.440）：

| 因子 | 权重 | IC | 计算方式 |
|------|------|-----|---------|
| base_trend | 0.40 | 0.43 | `(均线排列得分 x 0.6 + 波动率调整动量 x 0.4) x ADX强度 x 趋势稳定性`。均线排列：MA5>MA10（+0.2）, MA10>MA20（+0.3）, MA20>MA60（+0.5），归一化到[-1,1]。ADX强度=clip((ADX-20)/10, 0, 1)。趋势稳定性=最近20日上涨天数占比 |
| tech_confirm | 0.30 | 0.17 | `(MA因子 + MACD因子 + 布林因子) / 3`。MA因子=(MA5-MA20)/MA20。MACD因子=MACD柱/50日标准差。布林因子=(价格-下轨)/(上轨-下轨)-0.5 |
| relative_strength | 0.10 | 0.32 | 20日收益率，按全市场横截面做 z-score 标准化（均值0，标准差1），clip到[-3,3]。衡量个股相对全市场的强弱 |
| volume_confirm | 0.20 | 0.04 | `5日价格变化率 x log(5日均量/20日均量)`。量价齐升为正，缩量下跌为负 |

**得分合成**（根据版本不同）：
- **v5.2**：`tanh(0.4*base + 0.3*tech + 0.1*rs + 0.2*vol)`，等权分配
- **v6.1**：先正交化去除因子相关 → Rank Normalization → 动态权重（根据regime连续调整） → Volatility Scaling风险平价
- **v6.4**：正交化 → Alpha相关性惩罚 → Conditional IC → 预期收益率 → 凸优化器统一求解最优权重

**市场状态感知**（Soft Regime Score）：
- 基于沪深300指数的 MA20/MA60 趋势 + 20日波动率，连续打分 [-1, +1]
- 趋势市（score > 0）：权重偏向 base_trend（0.5），趋势榜扩大到 10 只
- 震荡市（score < 0）：权重均衡分配，趋势榜缩小到 5 只

**回测表现**（808只，2023-01 ~ 2026-03）：
- 交易次数：741笔，持仓周期：5日
- 平均收益：+0.26% | 胜率：42.78% | Sharpe：0.023
- 最大单笔：+148.78%（爆发力强）| 最大亏损：-27.77%

### 双优股票识别

同时出现在超跌榜和趋势榜的股票标记为"双优"：
- 既有超跌反弹的**估值支撑**（PE/PB低位）
- 又有趋势向上的**动能确认**（因子得分高）
- 在报告中用 "双优" 标记，风险收益比最优

---

## 版本演进与 IC 驱动切换

### v5.2 — 双引擎基线
- 均值回归 + 趋势跟随并行
- 趋势引擎：固定因子权重（0.4/0.3/0.1/0.2）+ tanh 压缩 + 等权分配
- 适用场景：因子 IC 较低时，简单策略反而更稳健

### v6.1 — 机构级因子升级
- **因子正交化**：Gram-Schmidt 残差化，消除 base_trend 与 tech_confirm 之间的线性相关（0.45→0.00），避免重复下注
- **Rank Normalization**：将因子得分转为横截面百分位排名 [-1, 1]，替代 tanh，不同 regime 下 scale 稳定
- **Soft Regime Score**：连续市场状态指标 [-1, +1]，替代"趋势/震荡"硬标签，权重平滑过渡
- **Volatility Scaling**：按个股波动率的倒数分配权重，实现风险平价（低波动股权重大，高波动股权重小）

### v6.4.3 — 生产级组合决策引擎（当前最新）
在 v6.1 基础上新增 5 个核心模块，形成完整的组合决策系统：

1. **Conditional IC Learning**（`src/alpha/conditional_ic.py`）
   - 按市场 regime 分 3 桶（熊/震荡/牛）独立计算因子 IC
   - EWMA 平滑（20日半衰期），置信区间加权（样本少则权重低），防塌陷 clip [0.05, 0.3]
   - 效果：IC 不再是固定标量，而是随市场状态动态调整

2. **Alpha 相关性惩罚**（`src/alpha/alpha_penalty.py`）
   - 拥挤度惩罚：`alpha_final = alpha - lambda * (alpha^T @ factor_cov @ alpha) * alpha`
   - 非线性映射：`sign(a) * |a|^1.5`，放大尾部强信号，压制中间噪音
   - 效果：避免多因子共振导致隐性集中风险

3. **EWMA + Shrinkage 协方差**（`src/risk/risk_model.py`）
   - 30日半衰期 EWMA 协方差 + 对角矩阵收缩（强度0.2）
   - 效果：快速响应波动率与相关性突变，比等权历史协方差更及时

4. **极端情景模拟 CVaR**（`src/risk/risk_model.py`）
   - 最差 5% 历史场景放大：`shock = 1 + shock_factor * (1 - regime_prob)`（恐慌时放大更多）
   - Regime 自适应压力乘数：`stress = 1 + 3 * (1 - regime_prob)`
   - Rockafellar-Uryasev 精确凸形式（`t + 1/(alpha*T) * sum(max(loss-t, 0))`）
   - 效果：预测未来尾部风险，而非仅放大历史

5. **统一凸优化器**（`src/optimizer/unified_optimizer.py`）
   - 目标函数：`max ER_adj - lambda_risk * (0.7*Variance + 0.3*CVaR) - lambda_cost * (Turnover + Impact) - lambda_smooth * PathPenalty`
   - 硬约束：单票 <= 10%，总杠杆 <= 1.5，L2范数 <= 1.2，组合波动率 <= 15%，趋势股占比 <= 20%
   - 路径稳定性：二阶差分惩罚 `||w - 2*w_{t-1} + w_{t-2}||^2`，防止每期大幅调仓
   - 求解器优先级：CLARABEL > SCS > ECOS > OSQP，全部失败自动降级到解析等权+风险调整
   - 效果：趋势与均值回归信号统一纳入同一个优化框架，输出最优持仓权重

6. **执行反馈闭环**（`src/execution/feedback.py`）
   - 冲击深度模型：`impact = (trade_size / ADV) ^ gamma`
   - 真实成交反馈：`gamma_new = 0.95 * gamma + 0.05 * ratio * gamma`（ratio = 实际滑点/预期冲击）
   - 恐慌市自动放大成本向量
   - 效果：用真实成交数据持续修正模型，防止回测偏离实盘

### IC 驱动自动切换（`src/strategies/hybrid_selector.py`）

系统根据实时因子 IC 自动选择最优版本：
- IC 高（base_trend >= 0.20 且 rs >= 0.15）→ 使用 **v6.4**
- IC 中等 → 使用 **v6.1**
- IC 低 → 回退到 **v5.2**（简单策略在因子失效时更稳健）

---

## 回测验证结果（2023-03 ~ 2026-03，3.0年）

回测条件：863只股票，每5个交易日调仓，扣除非线性交易成本（`turnover^1.3 * 0.3%`），含持仓延续性（旧仓在 top_N*2 内保留）。

| 指标 | v5.2 | v6.1 | v6.4 | 沪深300 |
|------|------|------|------|---------|
| 累计收益 | +44.17% | +35.14% | +42.51% | +11.59% |
| 年化收益 | +12.98% | +10.57% | +12.54% | +3.73% |
| 年化波动率 | 41.32% | 38.12% | 39.93% | -- |
| 夏普比率 | 0.31 | 0.28 | 0.31 | -- |
| 最大回撤 | -43.79% | -43.46% | **-43.16%** | -- |
| Calmar比率 | 0.30 | 0.24 | 0.29 | -- |
| 胜率 | 48.97% | 46.90% | 47.59% | -- |
| 平均换手率 | 73.93% | 82.39% | **73.72%** | -- |

**分阶段表现：**

| 市场状态 | v5.2 | v6.1 | v6.4 |
|---------|------|------|------|
| 牛市（42期） | +2.51%/期, 胜率60% | +2.28%/期, 胜率60% | +2.46%/期, 胜率60% |
| 熊市（29期） | -1.16%/期, 胜率38% | -1.20%/期, 胜率28% | -1.24%/期, 胜率31% |
| 震荡市（74期） | -0.17%/期, 胜率47% | -0.15%/期, 胜率47% | **-0.14%/期**, 胜率47% |

**核心结论：**
- 三版本均大幅跑赢沪深300（超额30%+），因子体系有效
- v6.4 最大回撤最小（-43.16%）、换手率最低（73.72%），风险控制最优
- v6.4 在震荡市表现最好（每期仅亏0.14%），soft regime + alpha penalty 的防过拟合能力突出
- v6.1 波动率最低（38.12%），volatility scaling 有效但压低了收益弹性
- v5.2 牛市进攻性最强（+2.51%/期），简单等权在趋势明确时收益弹性最大
- 回测脚本：`tools/analysis/backtest_v64.py`

---

## 策略体系（12大策略 x 5大维度）

### 技术面策略（6个）

| 策略 | 均值回归权重 | 核心逻辑 |
|------|------------|---------|
| MA | 0.30 | 短期均线（MA5/10）上穿长期均线（MA20/60），趋势转多 |
| MACD | 0.50 | DIF上穿DEA形成金叉，MACD柱由负转正，动能反转 |
| RSI | 1.82 | RSI(14) < 30 超卖买入，> 70 超买卖出 |
| BOLL | 1.95 | 价格触及布林带下轨（20日均线-2倍标准差），超卖反弹 |
| KDJ | 1.50 | K/D值在20以下形成金叉，随机指标超卖区反转 |
| DUAL | 1.39 | 双核动量：绝对动量（自身涨跌）+ 相对动量（vs指数）同时为正 |

### 基本面策略（3个）

| 策略 | 均值回归权重 | 核心逻辑 |
|------|------------|---------|
| PE | 1.68 | 当前PE处于3年历史分位数 < 25%，估值低位买入 |
| PB | 2.00 | 当前PB处于3年历史分位数 < 20%，破净/低估值买入 |
| PEPB | 1.61 | PE和PB同时处于历史低位（双因子联合低估），安全边际最高 |

PE/PB 使用3年滚动窗口（约528个交易日），每日计算当前值在历史中的百分位排名。低分位表示当前估值处于历史低位，有均值回归的空间。

### 消息/政策/情绪/资金策略（4个）

| 策略 | 权重 | 数据源 | 核心逻辑 |
|------|------|--------|---------|
| NEWS | 0.32 | 东方财富/新浪/同花顺 | 近24h新闻情感分析（关键词匹配40% + LLM语义理解60%），正面情绪加分 |
| POLICY | L0过滤 | 央行/财政/监管公告 | 极度利空（降准降息重大转向、IPO暂停等）时全市场暂停选股 |
| SENTIMENT | 0.32 | 涨跌停/成交量/融资融券 | 恐慌贪婪指数（多指标Z-score合成），极度恐慌时逆向加分 |
| MONEY_FLOW | 0.30 | 龙虎榜/大宗交易 | 机构席位净买入 + 大宗交易折价率分析，跟踪聪明钱 |

### 趋势引擎 — 4层因子体系

| 因子 | 权重 | IC | 计算方式 |
|------|------|-----|---------|
| base_trend | 0.40 | 0.43 | ADX趋势强度 x (均线排列得分 x 0.6 + 波动率调整动量 x 0.4) x 趋势稳定性 |
| tech_confirm | 0.30 | 0.17 | (MA因子 + MACD柱标准化 + 布林带位置) / 3 |
| relative_strength | 0.10 | 0.32 | 20日收益率横截面z-score，clip[-3, 3] |
| volume_confirm | 0.20 | 0.04 | 5日价格变化 x log(5日均量/20日均量) |

---

## 快速开始

### 安装依赖

```bash
# 核心依赖
pip3 install --user pandas numpy akshare baostock loguru scikit-learn scipy cvxpy

# 桌面自动化（可选，仅自动交易需要）
sudo apt-get install python3-tk python3-dev -y
pip3 install --user pyautogui psutil pillow pyyaml
```

Windows 用户：双击 `scripts\start_windows.bat`，选择 `6` 安装依赖。

### 每日选股（最常用）

```bash
# 标准模式：12策略 x 863只股票 -> TOP 20 推荐（自动选择 v5.2/v6.1/v6.4）
python3 tools/analysis/recommend_today.py --strategy full_12 --top 20

# 强制使用 v6.4（生产级引擎）
python3 tools/analysis/recommend_today.py --strategy full_12 --force-version v6.4

# 强制使用 v5.2（简单稳健）
python3 tools/analysis/recommend_today.py --strategy full_12 --force-version v5.2

# 含专题板块（核电+算电协同等）
python3 tools/analysis/recommend_today.py --strategy full_12 --top 20 --append-sectors

# 仅更新持仓分析（不重新扫描股票池）
python3 tools/analysis/recommend_today.py --only-holdings

# 使用缓存数据（离线模式，不联网）
python3 tools/analysis/recommend_today.py --strategy full_12 --cache-only
```

**输出报告**：
- 主报告：`mydate/daily_reports/daily_recommendation.md`（增量更新，历史可追溯）
- 每日归档：`mydate/daily_reports/daily_recommendation_YYYY-MM-DD.md`

**报告内容**：
1. 我的持仓概览（当前持仓 + 盈亏）
2. 今日持仓操作建议（加仓/减仓/止损/持有）
3. 超跌榜 TOP 15（均值回归引擎推荐）
4. 趋势榜 TOP 5（趋势引擎推荐）
5. 双优股票（同时上两个榜的标记）
6. v6.4 组合优化诊断（优化器状态、权重分布、风险指标）
7. 历史推荐记录

### 回测验证

```bash
# v5.2 / v6.1 / v6.4 三版本对比回测（863只 x 3年，约80秒）
python3 tools/analysis/backtest_v64.py
```

### 数据更新（每周执行）

```bash
# 更新K线缓存（增量更新，约5-10分钟）
python3 tools/data/backtest_prefetch.py \
  --pool mydate/stock_pool_all.json --update \
  --out-dir mydate/backtest_kline --workers 8

# 更新PE/PB基本面数据（约10-15分钟）
python3 tools/data/prefetch_pe_cache.py --update

# 刷新股票池（季度执行，同步指数成分调整）
python3 tools/data/refresh_stock_pool.py
```

### 单股深度分析

```bash
# 12策略完整分析
python3 tools/analysis/analyze_single_stock.py 688122 --name "西部超导"
```

---

## 数据源与缓存

**多源降级机制**（任一源失败自动切换下一个）：
```
Akshare（首选）-> Sina -> Eastmoney -> Tencent -> Tushare -> Baostock
```

**指数数据专用通道**：`fetch_index_daily` 独立于股票数据熔断机制，使用指数专用 API，确保沪深300等指数数据可靠获取，不受个股数据源故障影响。

**熔断机制**：单个数据源连续失败 3 次后熔断 60 秒，期间自动跳过该源，避免无效重试。

| 数据类型 | 目录 | 数量 | 时间跨度 | 更新频率 |
|---------|------|------|---------|---------|
| K线数据 | `mydate/backtest_kline/` | 863只 | 2022-11 至 2026-03（~805条/股） | 每周 |
| PE/PB数据 | `mydate/pe_cache/` | 815只 | 2022-11 至 2026-03（~528条/股） | 每周 |
| 新闻/政策 | 实时获取 | - | 近24h | 实时 |
| 龙虎榜/大宗交易 | 实时获取 | - | 近3日 | 实时 |

### 股票池配置

| 文件 | 说明 | 数量 | 过滤规则 |
|------|------|------|---------|
| `mydate/stock_pool_all.json` | 综合池（沪深300+中证500） | 808只 | PE∈(0,100]、市值>30亿、非ST |
| `mydate/stock_pool_nuclear_computing.json` | 专题池（核电+算电协同） | 52只 | 核电设备/电力/算力/智能电网 |
| `mydate/stock_pool.json` | 赛道龙头池 | 48只 | 光伏/机器人/半导体/有色/证券/创新药/商业航天 |
| `mydate/etf_pool.json` | ETF池 | 57只 | 宽基/科技/消费/金融/周期/医药/地产/跨境 |

---

## 项目结构

```
ai-trading-system/
|-- README.md                       # 本文件
|-- requirements.txt                # Python 依赖
|
|-- config/                         # 配置文件
|   |-- optimizer_config.yaml       # v6.4 优化器/风险/IC/执行参数（核心配置）
|   |-- trading_config.yaml         # 交易参数（止损线、仓位上限等）
|   |-- risk_config.yaml            # 风控参数
|   `-- data_sources.yaml           # 数据源优先级配置
|
|-- src/                            # 核心源代码
|   |-- strategies/                 # 策略模块
|   |   |-- base.py                     # 策略基类（Strategy / StrategySignal）
|   |   |-- ma_cross.py                 # MA 均线交叉
|   |   |-- macd_cross.py               # MACD 金叉死叉
|   |   |-- rsi_signal.py               # RSI 超买超卖
|   |   |-- bollinger_band.py           # BOLL 布林带
|   |   |-- kdj_signal.py               # KDJ 超卖金叉
|   |   |-- dual_momentum.py            # DUAL 双核动量
|   |   |-- fundamental_pe.py           # PE 历史分位数估值
|   |   |-- fundamental_pb.py           # PB 历史分位数估值
|   |   |-- fundamental_pe_pb.py        # PEPB 双因子联合低估
|   |   |-- news_sentiment.py           # NEWS 新闻情感分析
|   |   |-- policy_event.py             # POLICY 政策事件过滤
|   |   |-- sentiment.py                # SENTIMENT 恐慌贪婪指数
|   |   |-- money_flow.py               # MONEY_FLOW 资金流向
|   |   |-- ensemble.py                 # 组合策略（12策略加权投票）
|   |   |-- trend_strategies.py         # 趋势引擎（4层因子）
|   |   |-- market_regime_v6.py         # Soft Regime Score（连续市场状态）
|   |   `-- hybrid_selector.py          # IC 驱动版本切换（v5.2/v6.1/v6.4）
|   |
|   |-- factors/                    # v6.1 因子处理
|   |   |-- orthogonalization.py        # Gram-Schmidt 因子正交化
|   |   `-- normalization.py            # Rank Normalization
|   |
|   |-- alpha/                      # v6.4 Alpha 模块
|   |   |-- conditional_ic.py           # Conditional IC Learning（分桶+EWMA+置信）
|   |   `-- alpha_penalty.py            # Alpha 相关性惩罚 + 非线性映射
|   |
|   |-- risk/                       # v6.4 风险模型
|   |   `-- risk_model.py               # EWMA+Shrinkage 协方差 + 极端情景 CVaR
|   |
|   |-- optimizer/                  # v6.4 统一优化器
|   |   `-- unified_optimizer.py        # 凸优化（cvxpy）+ 解析降级
|   |
|   |-- execution/                  # v6.4 执行层
|   |   `-- feedback.py                 # 冲击深度模型 + EWMA 反馈闭环
|   |
|   |-- data/                       # 数据服务
|   |   |-- provider/                   # UnifiedDataProvider（多源+熔断）
|   |   `-- fetchers/                   # K线/基本面/指数数据获取
|   |       `-- data_prefetch.py        # fetch_index_daily（指数专用通道）
|   |
|   |-- api/broker/                 # 券商自动化（同花顺桌面/网页）
|   |-- core/                       # 核心工具（动量计算、回测约束）
|   `-- etf_rotation/               # ETF 轮动系统
|
|-- tools/                          # 工具脚本
|   |-- analysis/
|   |   |-- recommend_today.py          # 每日推荐主脚本（全流程入口）
|   |   |-- backtest_v64.py             # v5.2/v6.1/v6.4 三版本对比回测
|   |   |-- monitor_factor_ic.py        # 因子 IC 监控
|   |   `-- generate_sector_themes.py   # 专题板块推荐生成器
|   `-- data/                       # 数据预取与维护
|       |-- backtest_prefetch.py        # K线数据批量预取（增量更新）
|       |-- prefetch_pe_cache.py        # PE/PB 基本面数据预取
|       |-- refresh_stock_pool.py       # 股票池刷新（季度）
|       `-- quarterly_update.py         # 季度综合更新
|
|-- mydate/                         # 数据文件
|   |-- stock_pool_all.json             # 综合股票池（808只）
|   |-- my_portfolio.json               # 当前持仓
|   |-- backtest_kline/                 # K线缓存（863只 parquet）
|   |-- pe_cache/                       # PE/PB缓存（815只 parquet）
|   `-- daily_reports/                  # 每日推荐报告
|       |-- daily_recommendation.md         # 主报告（增量更新）
|       `-- daily_recommendation_YYYY-MM-DD.md  # 每日归档
|
|-- results/                        # 运行时持久化状态
|   |-- conditional_ic_state.json       # Conditional IC 学习状态
|   |-- execution_feedback.json         # 执行反馈闭环状态（gamma 等）
|   `-- trend_weights_optimization.json # 趋势权重优化结果
|
|-- tests/                          # 单元测试
|-- examples/                       # 使用示例（模拟交易/K线获取）
|-- scripts/                        # Shell/Bat 启动脚本
`-- docs/                           # 详细文档（策略/数据/部署）
```

---

## 风控系统

| 层级 | 控制内容 |
|------|----------|
| 账户级 | 单日最大亏损、总仓位上限、现金储备比例 |
| 策略级 | 单策略仓位上限、回撤控制、夏普比率监控 |
| 个股级 | 单股最大仓位（10%）、止损(-8%)、止盈、涨跌停限制 |
| 系统级 | 交易频率限制、异常检测、紧急熔断 |
| v6.4组合级 | 组合波动率硬约束 <= 15%、CVaR 尾部风险控制、路径平滑（防风格跳跃）、L2范数 <= 1.2（防隐性杠杆） |
| 数据级 | 自动过滤异常值（PE>100、PB<0、ST股票）、数据缺失跳过、网络超时重试3次、数据源熔断降级 |

---

## 自动化交易（可选）

> 自动化交易是可选功能。可以只用策略选股，根据推荐结果**手动交易**。

### 桌面客户端自动化（推荐）

```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

broker = TonghuashunDesktop({'auto_start': True})
if broker.login():
    broker.buy('600519', 1800.0, 100)
    broker.close()
```

详见 [桌面交易指南](docs/setup/DESKTOP_TRADING_GUIDE.md)。

### 网页自动化

```python
from src.api.broker.tonghuashun_simulator import TonghuashunSimulator

broker = TonghuashunSimulator({'username': '...', 'password': '...', 'headless': False})
if broker.login():
    broker.buy('600519', 1800.0, 100)
    broker.logout()
broker.close()
```

详见 [网页交易指南](docs/setup/WEB_TRADING_GUIDE.md)。

---

## 策略开发

新策略继承 `src.strategies.base.Strategy`：

```python
from src.strategies.base import Strategy, StrategySignal

class MyStrategy(Strategy):
    def analyze(self, df, **kwargs) -> StrategySignal:
        # df 列: date, open, high, low, close, volume, amount
        # 返回 StrategySignal(action='buy'/'sell'/'hold',
        #                     confidence=0.0~1.0,
        #                     position=0.0~1.0,
        #                     reason='信号说明',
        #                     indicators={})
        pass
```

在 `src/strategies/__init__.py` 的 `STRATEGY_REGISTRY` 中注册后即可用于所有工具。

详见 [策略开发快速开始](docs/strategy/STRATEGY_QUICKSTART.md)。

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [config/optimizer_config.yaml](config/optimizer_config.yaml) | v6.4 优化器/风险/IC/执行全部参数 |
| [docs/strategy/STRATEGY_DETAIL.md](docs/strategy/STRATEGY_DETAIL.md) | 12策略信号逻辑、参数、置信度映射 |
| [docs/strategy/STRATEGY_QUICKSTART.md](docs/strategy/STRATEGY_QUICKSTART.md) | 5分钟上手策略开发 |
| [docs/strategy/BACKTEST_AND_LIVE_SPEC.md](docs/strategy/BACKTEST_AND_LIVE_SPEC.md) | 回测与实盘规范 |
| [docs/data/PE_CACHE_GUIDE.md](docs/data/PE_CACHE_GUIDE.md) | PE/PB缓存机制说明 |
| [docs/data/API_INTERFACES_AND_FETCHERS.md](docs/data/API_INTERFACES_AND_FETCHERS.md) | 数据接口与容错 |
| [docs/setup/KLINE_DATA_GUIDE.md](docs/setup/KLINE_DATA_GUIDE.md) | K线缓存预取指南 |
| [docs/setup/CROSS_PLATFORM.md](docs/setup/CROSS_PLATFORM.md) | 跨平台兼容说明 |
| [docs/setup/DESKTOP_TRADING_GUIDE.md](docs/setup/DESKTOP_TRADING_GUIDE.md) | 桌面自动化交易指南 |
| [docs/setup/WEB_TRADING_GUIDE.md](docs/setup/WEB_TRADING_GUIDE.md) | 网页自动化交易指南 |

---

**股市有风险，投资需谨慎！**
