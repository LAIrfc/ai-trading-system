# MA/MACD 技术确认因子验证计划

## 背景

经过深入讨论，我们采用了**方案3（折中方案）**：
- MA/MACD 以降低的权重（MA=0.3, MACD=0.5）参与 `mr_score` 计算
- 定位为"技术确认因子"，避免选到"跌跌不休"的股票
- 避免与 `trend_score` 的重复计算

## 理论假设

### ✅ 预期优势
1. **提高成功率**：MA/MACD 金叉能过滤掉持续下跌的超跌股
2. **避免价值陷阱**：技术确认信号降低"跌跌不休"的风险
3. **互补而非叠加**：降权后与 trend_score 形成互补

### ⚠️ 潜在风险
1. **延迟入场**：等待技术确认可能错过最佳买点
2. **假突破**：MA/MACD 金叉可能是假信号
3. **过度优化**：权重 0.3/0.5 可能不是最优值

## 验证方法

### 方法1：对比回测（推荐）⭐

**目标**：对比三种配置的历史表现

**配置对比**：
```python
# 配置A：完全排除 MA/MACD（方案1）
MR_STRATEGY_NAMES_A = {'PB', 'PE', 'PEPB', 'DUAL', 'BOLL', 'RSI', 'KDJ', 'MONEY_FLOW', 'NEWS', 'SENTIMENT'}

# 配置B：降权 MA/MACD（方案3，当前）
MR_WEIGHTS_B = {'MA': 0.3, 'MACD': 0.5, ...}
MR_STRATEGY_NAMES_B = {..., 'MA', 'MACD'}

# 配置C：原权重 MA/MACD（方案2）
MR_WEIGHTS_C = {'MA': 0.88, 'MACD': 1.13, ...}
MR_STRATEGY_NAMES_C = {..., 'MA', 'MACD'}
```

**评估指标**：
- Sharpe 比率（风险调整后收益）
- 年化收益率
- 最大回撤
- 胜率（正收益占比）
- 平均持有天数

**执行命令**：
```bash
# 1. 修改 backtest_dual_engine.py 增加三种配置对比
# 2. 运行回测
python3 tools/optimization/backtest_dual_engine.py --online --pool mydate/stock_pool_all.json --stocks 200 --workers 8

# 3. 分析结果
cat results/dual_engine_backtest/comparison_*.json
```

**预期结果**：
- 如果配置B（降权）的 Sharpe 最高 → 方案3正确 ✅
- 如果配置A（排除）的 Sharpe 最高 → 应回退到方案1 ⚠️
- 如果配置C（原权重）的 Sharpe 最高 → 应采用方案2 ⚠️

---

### 方法2：实盘观察（辅助）

**目标**：观察未来1-2周的实际推荐效果

**步骤**：
1. **每日记录**：
   ```bash
   # 运行推荐
   python3 tools/analysis/recommend_today.py --strategy full_12 --top 20
   
   # 保存结果
   cp mydate/daily_reports/daily_recommendation.md mydate/daily_reports/archive/$(date +%Y%m%d).md
   ```

2. **跟踪指标**：
   - 超跌榜中有多少只股票在未来5日/10日上涨
   - 有 MA/MACD 确认的股票 vs 无确认的股票表现对比
   - 是否出现"跌跌不休"的股票

3. **每周总结**：
   - 统计胜率、平均涨幅
   - 分析失败案例（是技术确认失效？还是基本面问题？）

**预期结果**：
- 如果有技术确认的股票胜率明显更高 → 方案3正确 ✅
- 如果差异不明显 → 考虑回退到方案1（更简洁）⚠️

---

### 方法3：案例分析（深入）

**目标**：分析具体股票的行为差异

**步骤**：
1. **选取样本**：
   - 找出在配置A和配置B中排名差异最大的10只股票
   - 例如：在配置A中排名第5，在配置B中排名第15

2. **分析原因**：
   ```python
   # 对比分析脚本
   code = '600519'  # 示例
   
   # 配置A得分（无MA/MACD）
   mr_score_A = PB_score + PE_score + BOLL_score + ...
   
   # 配置B得分（含MA/MACD）
   mr_score_B = mr_score_A + 0.3*MA_score + 0.5*MACD_score
   
   # 查看K线图和技术指标
   print(f"MA金叉: {ma_cross_up}")
   print(f"MACD柱: {macd_hist}")
   print(f"得分差异: {mr_score_B - mr_score_A}")
   ```

3. **跟踪后续表现**：
   - 记录这些股票未来10日的涨跌
   - 判断 MA/MACD 确认是否有效

---

## 验证时间表

| 阶段 | 任务 | 预计时间 | 负责人 |
|------|------|---------|--------|
| Week 1 | 修改回测工具，增加三种配置对比 | 2小时 | AI助手 |
| Week 1 | 运行200只股票回测（在线数据） | 30分钟 | 用户 |
| Week 1 | 分析回测结果，得出初步结论 | 1小时 | 用户+AI |
| Week 2-3 | 实盘观察，每日记录推荐效果 | 每天5分钟 | 用户 |
| Week 3 | 案例分析，深入研究差异股票 | 2小时 | 用户+AI |
| Week 3 | 最终决策：保留/调整/回退方案 | - | 用户 |

---

## 决策标准

### ✅ 保留方案3（降权MA/MACD）的条件

至少满足以下**2项**：
1. 回测 Sharpe 比配置A高 10% 以上
2. 实盘胜率比配置A高 5% 以上
3. 最大回撤比配置A低 20% 以上
4. 用户主观感觉推荐质量更好

### ⚠️ 回退到方案1（排除MA/MACD）的条件

如果出现以下**任一**情况：
1. 回测 Sharpe 比配置A低
2. 实盘出现多次"跌跌不休"的股票（MA/MACD确认失效）
3. 用户主观感觉推荐质量变差

### 🔄 调整权重的条件

如果：
1. 方案3比方案1好，但不如方案2（原权重）
2. 可以尝试调整权重到中间值（MA=0.5-0.7, MACD=0.7-0.9）

---

## 当前状态

- ✅ 代码已修改（MA=0.3, MACD=0.5）
- ✅ 语法检查通过
- ⏳ 等待回测验证
- ⏳ 等待实盘观察

---

## 下一步行动

### 立即执行（今天）

1. **修改回测工具**：
   ```bash
   # 编辑 tools/optimization/backtest_dual_engine.py
   # 增加三种配置的对比逻辑
   ```

2. **运行快速回测**（50只股票，验证逻辑）：
   ```bash
   python3 tools/optimization/backtest_dual_engine.py --online --pool mydate/stock_pool_all.json --stocks 50 --workers 8
   ```

### 本周执行

3. **运行完整回测**（200-300只股票）：
   ```bash
   python3 tools/optimization/backtest_dual_engine.py --online --pool mydate/stock_pool_all.json --stocks 200 --workers 8
   ```

4. **分析结果，做出初步判断**

### 后续执行

5. **开始实盘观察**（每日记录）
6. **案例分析**（深入研究差异股票）
7. **最终决策**（3周后）

---

## 附录：权重敏感性分析

如果有时间，可以测试更多权重组合：

| 配置 | MA权重 | MACD权重 | 说明 |
|------|--------|----------|------|
| A | 0 | 0 | 完全排除 |
| B1 | 0.2 | 0.3 | 极低权重 |
| B2 | 0.3 | 0.5 | 当前方案 ⭐ |
| B3 | 0.5 | 0.7 | 中等权重 |
| B4 | 0.7 | 0.9 | 较高权重 |
| C | 0.88 | 1.13 | 原权重 |

通过对比找出最优权重组合。

---

## 结论

这是一个**理论假设**，需要通过**数据验证**。我们已经完成了代码修改，现在需要：

1. ✅ 回测验证（客观数据）
2. ✅ 实盘观察（真实表现）
3. ✅ 案例分析（深入理解）

**3周后，我们将根据验证结果做出最终决策。**
