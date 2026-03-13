# 📊 每日推荐与持仓跟踪 - 完整说明

> **一页纸讲清楚** | 2026-03-13

---

## 🎯 这个系统是干什么的？

**帮你每天自动选股，记录你的买卖操作，追踪持仓收益。**

---

## 📁 核心文件（只有3个）

### 1. `docs\DAILY_TRACKING.md` ⭐
**你每天要看的主文档**

包含：
- 📊 今日推荐 TOP 5（从721只股票池筛选）
- 💼 你的当前持仓
- 📝 你的买卖记录

### 2. `scripts\daily_update.bat`
**一键脚本**，每天运行一次

### 3. `tools\portfolio\update_daily_tracking.py`
**自动化工具**（被脚本调用，你不用管）

---

## 🚀 每天怎么用？

### 方式A：一键模式（推荐）

```bash
# 每天盘前运行
scripts\daily_update.bat --quick

# 查看推荐
notepad docs\DAILY_TRACKING.md
```

⏱️ **耗时**: 5-10分钟

---

### 方式B：手动模式

```bash
# 1. 生成推荐
.\.python\py311\python.exe tools\analysis\recommend_today.py --pool mydate\stock_pool_all.json --strategy full_11 --top 30

# 2. 更新文档
.\.python\py311\python.exe tools\portfolio\update_daily_tracking.py

# 3. 查看
notepad docs\DAILY_TRACKING.md
```

---

## 📊 文档长什么样？

打开 `docs\DAILY_TRACKING.md`，你会看到：

```markdown
## 📅 2026-03-13

### 🎯 今日推荐 TOP 5

| 代码 | 名称 | 价格 | 得分 | 5日涨 | 20日涨 | 状态 |
|------|------|------|------|-------|--------|------|
| 002120 | 韵达股份 | 7.00 | 10.5 | +2.34% | +0.29% | 🔲 |
| 002429 | 兆驰股份 | 11.94 | 8.3 | +12.64% | +26.22% | 🔲 |

### 💼 当前持仓

| 代码 | 名称 | 股数 | 成本 | 备注 |
|------|------|------|------|------|
| 600118 | 中国卫星 | 300 | 100.42 | |
| 601099 | 太平洋 | 2,500 | 4.14 | |

### 📝 今日操作

> 买入后手动记录一行
```

---

## 🤔 怎么看推荐？

### 看这3个指标

1. **得分**
   - ≥ 10：🔥 强烈推荐
   - 8-10：⭐ 可以考虑
   - < 8：观望

2. **5日涨幅**
   - +2% ~ +8%：✅ 启动初期，好入场点
   - +10% ~ +15%：⚠️ 有点高，谨慎
   - > +15%：🚫 追高风险大

3. **20日涨幅**
   - 正值：趋势向上
   - 负值：趋势向下

### 例子

```
002120 韵达股份  得分10.5  5日涨+2.34%
→ 得分高，涨幅适中，可以买入
```

```
002429 兆驰股份  得分8.3  5日涨+12.64%
→ 得分还行，但涨太多了，等回调
```

---

## 💼 买入后怎么记录？

### 方式A：自动同步（推荐）

```bash
# 1. 更新持仓文件
.\.python\py311\python.exe tools\portfolio\sync_portfolio.py --buy 002120 --shares 1000 --price 7.05

# 2. 手动编辑文档
notepad docs\DAILY_TRACKING.md
# 在"今日操作"下加一行：
# 买入 002120 1000股@7.05，原因：推荐TOP1
```

---

### 方式B：纯手动（最简单）

```bash
# 1. 手动改持仓文件
notepad mydate\my_portfolio.json
# 加一行：
# {"code": "002120", "name": "韵达股份", "shares": 1000, "avg_cost": 7.05}

# 2. 手动改跟踪文档
notepad docs\DAILY_TRACKING.md
# 在"今日操作"下加一行：
# 买入 002120 1000股@7.05
```

---

## 📈 卖出后怎么记录？

### 方式A：自动同步

```bash
# 1. 更新持仓（减少股数）
.\.python\py311\python.exe tools\portfolio\sync_portfolio.py --sell 002120 --shares 500

# 2. 手动编辑文档
notepad docs\DAILY_TRACKING.md
# 加一行：
# 卖出 002120 500股@7.50，收益+6.4%
```

---

### 方式B：纯手动

```bash
# 1. 手动改持仓文件
notepad mydate\my_portfolio.json
# 把 "shares": 1000 改成 "shares": 500

# 2. 手动改跟踪文档
notepad docs\DAILY_TRACKING.md
# 加一行：
# 卖出 002120 500股@7.50，收益+6.4%
```

---

## 🔄 完整流程示例

### 周一早上（09:00）

```bash
# 1. 运行一键脚本
scripts\daily_update.bat --quick

# 等待5-10分钟...

# 2. 打开文档看推荐
notepad docs\DAILY_TRACKING.md
```

**你看到**：
```
TOP 1: 002120 韵达股份  得分10.5  价格7.00
TOP 2: 002429 兆驰股份  得分8.3   价格11.94
```

---

### 周一盘中（10:30）

**决定买入 002120**

```bash
# 方式1：用工具（自动计算成本）
.\.python\py311\python.exe tools\portfolio\sync_portfolio.py --buy 002120 --shares 1000 --price 7.05

# 方式2：手动改文件
notepad mydate\my_portfolio.json
# 加一行持仓
```

然后手动在 `DAILY_TRACKING.md` 里记一笔：
```markdown
### 📝 今日操作

买入 002120 1000股@7.05，原因：推荐TOP1
```

---

### 周五盘中（14:00）

**决定卖出 002120（已涨到7.50，+6.4%）**

```bash
# 方式1：用工具
.\.python\py311\python.exe tools\portfolio\sync_portfolio.py --sell 002120 --shares 1000

# 方式2：手动改文件
notepad mydate\my_portfolio.json
# 把股数改成0
```

然后在文档里记一笔：
```markdown
卖出 002120 1000股@7.50，收益+6.4%，持有5天
```

---

## 📊 系统工作原理

### 数据流

```
股票池(721只)
    ↓
11策略分析
    ↓
生成推荐报告 (tools/output/daily_recommendation_*.md)
    ↓
自动提取TOP 5
    ↓
更新到 DAILY_TRACKING.md
    ↓
你看推荐，决定买入
    ↓
手动记录操作
```

### 推荐是怎么生成的？

1. **股票池**: 721只（HS300 + ZZ500 + 7大板块龙头）
2. **策略分析**: 11个策略（MA/MACD/RSI/BOLL/KDJ/双重动量/PE/PB/资金流/情绪/政策）
3. **综合评分**: 每个策略投票（BUY/SELL/HOLD），加权计算总分
4. **排序输出**: 按得分从高到低排序，输出TOP 30

**举例**：
- 002120 韵达股份：MA买入、MACD买入、双重动量买入、政策利好 → 得分10.5
- 002429 兆驰股份：MACD买入、RSI买入、BOLL买入 → 得分8.3

---

## 🗂️ 文件说明

### 你需要关注的

| 文件 | 作用 | 你需要做什么 |
|------|------|-------------|
| `docs\DAILY_TRACKING.md` | 主文档 | 每天看，买入后手动记一笔 |
| `mydate\my_portfolio.json` | 持仓文件 | 买入/卖出后更新（手动或用工具） |

### 自动生成的

| 文件 | 作用 | 说明 |
|------|------|------|
| `tools\output\daily_recommendation_*.md` | 详细推荐报告 | 每天自动生成，包含TOP 30 |
| `mydate\stock_pool_all.json` | 股票池 | 721只股票，每周更新 |
| `mydate\portfolio_backups\` | 持仓备份 | 自动备份，防止误操作 |

### 工具脚本

| 文件 | 作用 |
|------|------|
| `scripts\daily_update.bat` | 一键更新脚本 |
| `tools\portfolio\update_daily_tracking.py` | 文档更新工具 |
| `tools\portfolio\sync_portfolio.py` | 持仓同步工具（可选） |

---

## 💡 常见问题

### Q: 每天必须更新股票池吗？
**A**: 不用。股票池每周更新一次就够了（周一用完整模式）。

```bash
# 周一
scripts\daily_update.bat  # 完整更新

# 周二-周五
scripts\daily_update.bat --quick  # 快速模式
```

---

### Q: 我可以只手动记录，不用工具吗？
**A**: 完全可以！

**最简单的方式**：
1. 每天运行 `scripts\daily_update.bat --quick`
2. 打开 `docs\DAILY_TRACKING.md` 看推荐
3. 买入后，直接在文档里手动写一行
4. 手动改 `mydate\my_portfolio.json` 更新持仓

**工具的作用**：
- `sync_portfolio.py`：帮你自动计算平均成本（补仓时有用）
- 如果你不补仓，或者自己会算，就不需要这个工具

---

### Q: 推荐准吗？
**A**: 系统基于11个策略的综合判断，但不保证100%准确。

**建议**：
- 得分≥10的股票，胜率较高
- 结合自己的判断，不要盲目跟
- 严格止损（-8%）

---

### Q: 持仓文件格式是什么？
**A**: JSON格式，很简单：

```json
{
  "updated": "2026-03-13",
  "holdings": [
    {
      "code": "002120",
      "name": "韵达股份",
      "shares": 1000,
      "avg_cost": 7.05
    }
  ]
}
```

买入就加一行，卖出就改股数。

---

## 🎓 完整示例

### 场景：周一买入，周五卖出

#### 周一 09:00（盘前）

```bash
scripts\daily_update.bat --quick
```

**输出**：
```
[2/3] 生成推荐...
✅ 完成

[3/3] 更新文档...
✅ 已更新: docs\DAILY_TRACKING.md
```

---

#### 周一 09:15（查看推荐）

```bash
notepad docs\DAILY_TRACKING.md
```

**看到**：
```markdown
## 📅 2026-03-10

### 🎯 今日推荐 TOP 5

| 代码 | 名称 | 价格 | 得分 | 5日涨 | 状态 |
|------|------|------|------|-------|------|
| 002120 | 韵达股份 | 7.00 | 10.5 | +2.34% | 🔲 |
```

**决策**：得分10.5很高，5日涨幅+2.34%不算高，可以买！

---

#### 周一 10:30（买入）

**实际成交**：1000股 @ 7.05元

**记录方式1**（用工具）：
```bash
.\.python\py311\python.exe tools\portfolio\sync_portfolio.py --buy 002120 --shares 1000 --price 7.05
```

**记录方式2**（手动）：
```bash
# 编辑 mydate\my_portfolio.json
notepad mydate\my_portfolio.json

# 加一行：
{
  "code": "002120",
  "name": "韵达股份",
  "shares": 1000,
  "avg_cost": 7.05
}
```

**然后在文档里记一笔**：
```bash
notepad docs\DAILY_TRACKING.md

# 在"今日操作"下加：
买入 002120 1000股@7.05，原因：推荐TOP1
```

---

#### 周五 14:00（卖出）

**当前价格**：7.50元（+6.4%）

**决策**：止盈离场

```bash
# 方式1：用工具
.\.python\py311\python.exe tools\portfolio\sync_portfolio.py --sell 002120 --shares 1000

# 方式2：手动改持仓文件
notepad mydate\my_portfolio.json
# 把 "shares": 1000 改成 "shares": 0
```

**在文档里记一笔**：
```bash
notepad docs\DAILY_TRACKING.md

# 在"今日操作"下加：
卖出 002120 1000股@7.50，收益+6.4%，持有5天
```

---

## 📊 关键数据文件

### `mydate\my_portfolio.json`（你的持仓）

```json
{
  "updated": "2026-03-13",
  "note": "持仓数据",
  "holdings": [
    {
      "code": "600118",
      "name": "中国卫星",
      "shares": 300,
      "avg_cost": 100.42
    },
    {
      "code": "002120",
      "name": "韵达股份",
      "shares": 1000,
      "avg_cost": 7.05
    }
  ]
}
```

**字段说明**：
- `code`: 股票代码
- `name`: 股票名称
- `shares`: 持仓股数（0表示已清仓）
- `avg_cost`: 平均成本

---

### `mydate\stock_pool_all.json`（股票池）

包含721只股票：
- HS300成分股（300只）
- ZZ500成分股（500只）
- 7大板块龙头（70只，去重后）

**更新频率**：每周一次（周一用完整模式）

---

### `tools\output\daily_recommendation_*.md`（推荐报告）

完整的TOP 30推荐，包含：
- 详细的技术指标
- 各策略的具体信号
- 买入/卖出原因

**用途**：`DAILY_TRACKING.md` 只显示TOP 5，想看更多就打开这个

---

## 🛠️ 工具说明

### `scripts\daily_update.bat`

**作用**：串联3个步骤
1. 更新股票池（可选，`--quick`跳过）
2. 生成推荐
3. 更新文档

**参数**：
- 无参数：完整更新（30-45分钟）
- `--quick`：快速模式（5-10分钟）

---

### `tools\portfolio\sync_portfolio.py`

**作用**：自动更新持仓文件

**功能**：
- 买入：自动添加持仓
- 补仓：自动计算新的平均成本
- 卖出：自动减少股数
- 清仓：自动标记"已清仓"
- 自动备份：每次修改前备份

**用法**：
```bash
# 买入
--buy <代码> --shares <股数> --price <价格>

# 卖出
--sell <代码> --shares <股数>

# 清仓
--sell <代码> --shares all
```

**优点**：自动计算，不会算错  
**缺点**：多一步命令

**你可以选择用或不用**，手动改文件也完全OK。

---

### `tools\portfolio\update_daily_tracking.py`

**作用**：自动更新 `DAILY_TRACKING.md`

**工作原理**：
1. 读取 `tools\output\daily_recommendation_*.md`
2. 提取TOP 5推荐
3. 读取 `mydate\my_portfolio.json`
4. 生成今日部分，插入到文档

**你不需要直接运行**，`daily_update.bat` 会调用它。

---

## 📅 维护建议

### 每天（5分钟）
```bash
scripts\daily_update.bat --quick
notepad docs\DAILY_TRACKING.md
```

### 每周一（30分钟）
```bash
scripts\daily_update.bat  # 不加 --quick，完整更新股票池
```

### 买入/卖出后（1分钟）
手动在文档里记一行，就这么简单。

---

## 🎯 总结

### 核心就3个文件

1. **`docs\DAILY_TRACKING.md`** - 你每天看的主文档
2. **`scripts\daily_update.bat`** - 每天运行一次
3. **`mydate\my_portfolio.json`** - 你的持仓（买入/卖出后更新）

### 每天只需2步

1. **盘前**：`scripts\daily_update.bat --quick`（5-10分钟）
2. **查看**：`notepad docs\DAILY_TRACKING.md`

### 买入后记录

**最简单**：直接在文档里手动写一行  
**稍复杂**：用 `sync_portfolio.py` 自动更新持仓文件

---

## 🚀 立即开始

```bash
# 第一次使用
scripts\daily_update.bat --quick

# 查看推荐
notepad docs\DAILY_TRACKING.md

# 就这么简单！
```

---

**有问题随时问我！** 💬
