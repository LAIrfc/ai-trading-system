# 模拟交易指南 📝

## 什么是模拟交易？

模拟交易（Paper Trading/虚拟交易）是使用**虚拟资金**进行交易测试，**完全安全，无任何资金风险**！

### ✅ 优势

- **零风险** - 使用虚拟资金，不会损失真金白银
- **真实环境** - 使用实时行情数据
- **完整功能** - 买卖、持仓、盈亏计算
- **策略测试** - 验证策略是否有效
- **学习工具** - 熟悉交易流程

---

## 🚀 快速开始

### 方式1: 手动交易模式（推荐新手）

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 启动模拟交易
python3 examples/paper_trading_demo.py

# 选择 1 - 手动交易模式
```

**功能**：
- 自己控制买卖时机
- 查看账户和持仓
- 查看成交记录
- 更新实时价格

### 方式2: 策略自动模式（测试策略）

```bash
python3 examples/paper_trading_demo.py

# 选择 2 - 策略自动模式
# 选择策略（MA/MACD/RSI）
# 输入要监控的股票
```

**功能**：
- 策略自动生成信号
- 自动执行买卖
- 实时监控盈亏
- 30秒循环一次

---

## 📊 手动交易演示

### 启动

```bash
python3 examples/paper_trading_demo.py
# 选择 1
```

### 操作菜单

```
操作菜单:
1. 买入
2. 卖出
3. 查看账户
4. 查看持仓
5. 查看成交
6. 更新市场价格
0. 退出
```

### 买入流程

```
请选择: 1

股票代码: 600519

600519 - 贵州茅台
当前价: 1800.00元
涨跌幅: +0.28%

买入价格 (默认1800.00): 1800
买入数量 (100的倍数): 100

✅ 买入成功!
   订单号: ORDER_20260224_143000_0001
   成交价: 1800.00元
   数量: 100股
   金额: 180,000.00元
```

### 卖出流程

```
请选择: 2

当前持仓:
1. 600519 - 100股 @ 1800.00元

股票代码: 600519

持仓: 100股
成本价: 1800.00元
当前价: 1850.00元

卖出价格 (默认1850.00): 1850
卖出数量 (最多100): 100

✅ 卖出成功!
   订单号: ORDER_20260224_144500_0002
   成交价: 1850.00元
   数量: 100股
   金额: 185,000.00元
```

### 查看账户

```
请选择: 3

============================================================
  模拟账户摘要
============================================================

💰 资金情况:
   初始资金: 100,000.00元
   可用资金: 105,000.00元
   持仓市值: 0.00元
   总资产:   105,000.00元

📈 盈亏:
   盈亏金额: +5,000.00元
   盈亏比例: +5.00%

📊 持仓 (0只):
   暂无持仓

📝 统计:
   订单数: 2
   成交数: 2

============================================================
```

---

## 🤖 策略自动交易演示

### 启动

```bash
python3 examples/paper_trading_demo.py
# 选择 2
```

### 选择策略

```
选择策略:
1. MA (均线策略)
2. MACD策略
3. RSI策略

请选择 (1-3): 1
```

### 输入股票

```
输入股票代码（多个用逗号分隔，如600519,000001）: 600519,000001

📊 监控股票: 600519, 000001
🔄 策略运行中... (按Ctrl+C停止)
```

### 运行过程

```
--- 第1轮 14:30:00 ---
✅ 生成了 1 个信号:

🟢 买入 信号
   股票: 600519
   原因: 短期MA5上穿长期MA20
   价格: 1800.00元
   置信度: 70%
   ✅ 买入成功: 500股

💰 账户: 总资产100,000元 | 盈亏+0元(+0.00%) | 持仓1只

等待30秒...

--- 第2轮 14:30:30 ---
⚪ 无交易信号

💰 账户: 总资产100,500元 | 盈亏+500元(+0.50%) | 持仓1只

等待30秒...
```

### 停止策略

按 `Ctrl+C` 停止，系统会：
1. 停止策略
2. 保存账户数据
3. 显示最终摘要

```
⚠️  策略已停止

保存账户数据...
✅ 账户已保存到: data/paper_trading_strategy_20260224_143000.json

============================================================
  模拟账户摘要
============================================================
...
```

---

## 💻 Python代码使用

### 基础用法

```python
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/wangxinghan/codetree/ai-trading-system')

from src.core.simulator.paper_trading import PaperTradingAccount

# 创建模拟账户（10万初始资金）
account = PaperTradingAccount(initial_capital=100000.0)

# 买入
success, order_id = account.buy('600519', 1800.0, 100)
if success:
    print(f"买入成功，订单号: {order_id}")

# 卖出
success, order_id = account.sell('600519', 1850.0, 100)
if success:
    print(f"卖出成功，订单号: {order_id}")

# 查看账户
account.print_summary()
```

### 更新市场价格

```python
from src.data.realtime_data import MarketDataManager

# 获取实时价格
manager = MarketDataManager()
quotes = manager.get_realtime_data(['600519'])

# 更新账户持仓价格
prices = {code: quote['price'] for code, quote in quotes.items() if quote}
account.update_market_prices(prices)
```

### 与策略集成

```python
from src.core.strategy.strategy_library import strategy_library
from src.data.realtime_data import MarketDataManager

# 创建账户和策略
account = PaperTradingAccount(100000.0)
strategy = strategy_library.get_strategy('MA')

# 获取数据
manager = MarketDataManager()
market_data = manager.prepare_strategy_data(['600519'])

# 生成信号
signals = strategy.generate_signals(market_data)

# 执行交易
for signal in signals:
    if signal['action'] == 'buy':
        quantity = 100  # 简化示例
        account.buy(signal['stock_code'], signal['price'], quantity)
    elif signal['action'] == 'sell':
        if signal['stock_code'] in account.positions:
            pos = account.positions[signal['stock_code']]
            account.sell(signal['stock_code'], signal['price'], pos.quantity)
```

### 保存和加载

```python
# 保存账户
account.save_to_file('data/my_account.json')

# 查看账户信息
info = account.get_account_info()
print(f"总资产: {info['total_assets']:.2f}元")
print(f"盈亏: {info['total_profit']:+.2f}元")

# 获取持仓
positions = account.get_positions()
for pos in positions:
    print(f"{pos['stock_code']}: {pos['profit']:+.2f}元")

# 获取成交记录
trades = account.get_trades()
print(f"共成交 {len(trades)} 笔")
```

---

## 📊 功能详解

### 1. 账户功能

- ✅ **初始资金**: 默认10万，可自定义
- ✅ **手续费**: 万三（可配置）
- ✅ **印花税**: 卖出时千分之一
- ✅ **最小手续费**: 5元
- ✅ **资金管理**: 自动计算可用资金
- ✅ **持仓管理**: 成本价、市值、盈亏

### 2. 交易功能

- ✅ **买入**: 限价买入，检查资金
- ✅ **卖出**: 限价卖出，检查持仓
- ✅ **数量限制**: 100股起，100的倍数
- ✅ **即时成交**: 模拟立即成交
- ✅ **订单记录**: 完整订单历史
- ✅ **成交记录**: 详细成交信息

### 3. 查询功能

- ✅ **账户信息**: 资金、持仓、盈亏
- ✅ **持仓列表**: 每只股票详情
- ✅ **订单列表**: 所有订单
- ✅ **成交记录**: 所有成交
- ✅ **实时更新**: 更新持仓市价

### 4. 数据保存

- ✅ **JSON格式**: 易于查看和分析
- ✅ **完整记录**: 账户、持仓、订单、成交
- ✅ **时间戳**: 记录操作时间
- ✅ **可重复**: 随时查看历史

---

## 🎓 使用建议

### 新手学习路径

1. **第1周**: 手动交易模式
   - 熟悉买卖流程
   - 理解盈亏计算
   - 观察市场波动

2. **第2周**: 小额测试
   - 用少量资金试水
   - 测试不同股票
   - 总结交易经验

3. **第3周**: 策略测试
   - 测试内置策略
   - 观察策略表现
   - 理解信号生成

4. **第4周+**: 自定义策略
   - 开发自己的策略
   - 模拟盘验证
   - 持续优化

### 风险提示

虽然是模拟交易，但建议：

- ❗ **认真对待** - 当成真实交易
- ❗ **遵守规则** - 不要随意修改
- ❗ **记录总结** - 记录每笔交易原因
- ❗ **控制仓位** - 练习资金管理
- ❗ **设置止损** - 培养风控意识

### 实盘前检查清单

在进入实盘前，确保：

- [ ] 模拟盘至少运行1个月
- [ ] 盈利稳定，不是靠运气
- [ ] 理解策略原理和风险
- [ ] 有完整的交易计划
- [ ] 设置了止损止盈
- [ ] 控制单笔仓位<30%
- [ ] 心态平和，不追涨杀跌

---

## 📈 示例场景

### 场景1: 测试均线策略

```bash
# 1. 启动策略模式
python3 examples/paper_trading_demo.py
# 选择 2

# 2. 选择MA策略
# 输入 1

# 3. 输入股票
600519,000001,600036

# 4. 观察运行
# 等待策略生成信号和执行交易

# 5. 按Ctrl+C停止
# 查看最终收益
```

### 场景2: 手动练习交易

```bash
# 1. 启动手动模式
python3 examples/paper_trading_demo.py
# 选择 1

# 2. 买入茅台
选择 1
输入 600519
输入价格和数量

# 3. 等待一段时间

# 4. 更新价格
选择 6

# 5. 卖出
选择 2
选择 600519

# 6. 查看盈亏
选择 3
```

---

## 🆘 常见问题

**Q: 模拟交易的数据是实时的吗？**  
A: 是的，使用的是实时行情数据（延迟3-5秒）。

**Q: 手续费怎么计算？**  
A: 买入：万三手续费；卖出：万三手续费+千一印花税，最低5元。

**Q: 可以保存账户吗？**  
A: 可以，退出时会自动保存到 `data/` 目录。

**Q: 支持T+0吗？**  
A: 模拟交易支持T+0，可以当天买入卖出（实盘A股是T+1）。

**Q: 初始资金可以改吗？**  
A: 可以，修改代码中的 `initial_capital` 参数。

**Q: 策略模式可以手动干预吗？**  
A: 不建议。策略模式是测试策略的自动执行能力。

---

## 📚 相关文档

- [策略开发指南](STRATEGY_QUICKSTART.md)
- [K线数据获取](KLINE_DATA_GUIDE.md)
- [快速参考](QUICK_REFERENCE.md)

---

## 🎯 下一步

### 立即开始

```bash
cd /home/wangxinghan/codetree/ai-trading-system
python3 examples/paper_trading_demo.py
```

### 推荐流程

1. **手动模式** - 熟悉交易流程
2. **策略模式** - 测试内置策略
3. **自定义策略** - 开发自己的策略
4. **持续优化** - 根据模拟结果调整
5. **实盘准备** - 通过检查清单后小资金实盘

---

**开始你的模拟交易之旅！** 📈

记住：
> "模拟盘赚钱不难，难的是持续稳定盈利。"  
> "把模拟盘当成实盘，才能在实盘中盈利。"

祝交易顺利！🚀
