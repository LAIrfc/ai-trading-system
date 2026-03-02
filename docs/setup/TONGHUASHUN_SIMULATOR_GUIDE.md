# 同花顺模拟交易使用指南 🎮

## 什么是同花顺模拟交易？

同花顺软件**内置的模拟炒股**功能，提供虚拟资金让您练习交易，**完全真实的交易环境**！

### ✅ 优势

- **官方提供** - 同花顺官方模拟交易
- **真实环境** - 界面、功能和实盘完全一致
- **虚拟资金** - 通常初始100万虚拟资金
- **实时行情** - 使用真实市场行情
- **排行榜** - 可以和其他模拟用户比拼
- **零风险** - 不会损失真实资金

### 🎯 与我们系统结合

**好消息**：我们的桌面自动化系统可以直接控制同花顺模拟交易账户！

---

## 🚀 快速开始

### 第1步：登录同花顺模拟交易

#### 方法1：在同花顺软件内

1. 打开同花顺客户端
2. 找到 "模拟炒股" 或 "模拟交易" 入口
   - 通常在顶部菜单栏
   - 或者在 "交易" 菜单中
3. 注册/登录模拟交易账户
4. 进入模拟交易界面

#### 方法2：直接启动

```bash
# 启动同花顺
/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp

# 在软件内切换到模拟交易账户
```

### 第2步：验证模拟账户

确认您已进入模拟交易：
- ✅ 账户资金显示（如100万）
- ✅ 可以看到"模拟"标识
- ✅ 快捷键可用（F1买入、F2卖出）

### 第3步：使用自动化系统

我们的自动化系统可以直接操作同花顺模拟交易！

---

## 🤖 自动化控制模拟交易

### 方式1：策略自动交易

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 运行策略+模拟交易
python3 examples/tonghuashun_strategy_trading.py
```

这个脚本会：
1. 检测同花顺是否运行
2. 使用策略生成信号
3. 自动在同花顺模拟账户执行交易
4. 查询账户和持仓

### 方式2：手动测试

```bash
# 测试桌面自动化
python3 examples/desktop_trading_auto.py
```

在配置中设置：
```python
TEST_CONFIG = {
    'action': 'buy',
    'stock_code': '600519',
    'price': 1800.0,
    'quantity': 100,
    'real_trade': True,  # 注意：这会在模拟账户实际下单
}
```

---

## 📝 详细使用流程

### 流程1：策略+模拟交易（推荐）

#### 准备工作

1. **打开同花顺，登录模拟账户**
2. **确保模拟交易界面可见**
3. **记下初始资金**

#### 运行策略

创建专门的模拟交易脚本 `my_simulator_trading.py`：

```python
#!/usr/bin/env python3
"""
同花顺模拟交易 + 策略自动执行
"""
import sys
sys.path.insert(0, '/home/wangxinghan/codetree/ai-trading-system')

import time
from datetime import datetime
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop
from src.core.strategy.strategy_library import strategy_library
from src.data.realtime_data import MarketDataManager

# 配置
MONITOR_STOCKS = ['600519', '000001', '600036']  # 监控的股票
STRATEGY_NAME = 'MA'  # 使用的策略
CHECK_INTERVAL = 60  # 检查间隔（秒）

def main():
    print("="*60)
    print("  同花顺模拟交易 + 策略自动执行")
    print("="*60)
    
    # 提示
    print("\n⚠️  重要提示:")
    print("1. 请确保同花顺已打开并登录模拟交易账户")
    print("2. 请确保模拟交易界面可见")
    print("3. 策略会自动执行交易，请注意观察")
    
    input("\n按Enter键开始...")
    
    # 初始化
    broker = TonghuashunDesktop({'auto_start': False})
    strategy = strategy_library.get_strategy(STRATEGY_NAME)
    data_manager = MarketDataManager()
    
    print(f"\n✅ 策略: {STRATEGY_NAME}")
    print(f"✅ 监控股票: {', '.join(MONITOR_STOCKS)}")
    print(f"✅ 检查间隔: {CHECK_INTERVAL}秒")
    print("\n🔄 开始运行... (Ctrl+C 停止)\n")
    
    cycle = 0
    
    try:
        while True:
            cycle += 1
            print(f"\n{'='*60}")
            print(f"第{cycle}轮 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print('='*60)
            
            # 1. 获取市场数据
            print("📊 获取市场数据...")
            market_data = data_manager.prepare_strategy_data(
                MONITOR_STOCKS, 
                historical_days=100
            )
            
            # 2. 生成信号
            print("🔍 分析生成信号...")
            signals = strategy.generate_signals(market_data)
            
            if signals:
                print(f"\n✅ 发现 {len(signals)} 个交易信号:")
                
                for signal in signals:
                    code = signal['stock_code']
                    action = signal['action']
                    price = signal['price']
                    reason = signal['reason']
                    
                    emoji = "🟢 买入" if action == 'buy' else "🔴 卖出"
                    print(f"\n{emoji}")
                    print(f"   股票: {code}")
                    print(f"   价格: {price:.2f}")
                    print(f"   原因: {reason}")
                    
                    # 确认执行
                    confirm = input("\n   执行此交易? (y/n, 默认y): ").strip().lower()
                    if confirm in ['', 'y', 'yes']:
                        # 3. 执行交易
                        if action == 'buy':
                            quantity = 100  # 可以根据资金动态计算
                            print(f"   🔄 执行买入: {code} {quantity}股 @ {price:.2f}")
                            success, result = broker.buy(code, price, quantity)
                        else:
                            quantity = 100  # 实际应查询持仓
                            print(f"   🔄 执行卖出: {code} {quantity}股 @ {price:.2f}")
                            success, result = broker.sell(code, price, quantity)
                        
                        if success:
                            print(f"   ✅ 交易成功!")
                        else:
                            print(f"   ❌ 交易失败: {result}")
                    else:
                        print("   ⏭️  跳过")
            else:
                print("⚪ 无交易信号")
            
            # 4. 查询账户（可选）
            try:
                print("\n💰 查询账户信息...")
                account = broker.get_account_info()
                print(f"   可用资金: {account.get('available_balance', 'N/A')}")
                
                positions = broker.get_positions()
                print(f"   持仓数: {len(positions)}只")
            except Exception as e:
                print(f"   ⚠️  查询失败: {e}")
            
            # 5. 等待下一轮
            print(f"\n⏰ 等待{CHECK_INTERVAL}秒...")
            time.sleep(CHECK_INTERVAL)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  策略已停止")
    
    finally:
        print("\n✅ 程序结束")

if __name__ == "__main__":
    main()
```

保存后运行：

```bash
chmod +x my_simulator_trading.py
python3 my_simulator_trading.py
```

---

## 🎯 快捷键操作

同花顺模拟交易支持的快捷键（和实盘一样）：

| 快捷键 | 功能 | 说明 |
|--------|------|------|
| **F1** | 买入 | 打开买入窗口 |
| **F2** | 卖出 | 打开卖出窗口 |
| **F3** | 撤单 | 撤销未成交订单 |
| **F4** | 查询 | 查询持仓/资金 |

我们的自动化系统会自动使用这些快捷键！

---

## 📊 模拟交易功能

### 可以做什么

- ✅ **买入股票** - 使用虚拟资金买入
- ✅ **卖出股票** - 卖出持仓
- ✅ **查询持仓** - 查看持有的股票
- ✅ **查询资金** - 查看可用资金
- ✅ **查询成交** - 查看历史成交
- ✅ **查询委托** - 查看待成交订单
- ✅ **撤单** - 取消未成交订单

### 限制

- ⚠️ **T+1交易** - 当天买入的股票次日才能卖出
- ⚠️ **涨跌停限制** - 不能超过涨跌停价格
- ⚠️ **最小单位** - 买入必须100股的整数倍
- ⚠️ **手续费** - 有模拟手续费（通常很低）

---

## 💡 使用建议

### 测试流程

1. **第1周：手动测试**
   - 在同花顺手动买卖
   - 熟悉模拟交易界面
   - 记录交易过程

2. **第2周：自动化测试**
   - 使用我们的脚本
   - 先测试查询功能
   - 再测试交易功能

3. **第3周：策略测试**
   - 运行策略自动交易
   - 观察策略表现
   - 记录盈亏

4. **第4周+：优化**
   - 分析交易记录
   - 优化策略参数
   - 持续改进

### 注意事项

1. **确保同花顺运行** - 自动化前先手动打开
2. **保持界面可见** - 不要最小化或切换
3. **网络稳定** - 确保网络连接正常
4. **及时查看** - 注意观察交易执行情况
5. **记录日志** - 保存交易记录供分析

---

## 🔍 故障排查

### 问题1：无法执行交易

**检查**：
- [ ] 同花顺是否打开？
- [ ] 是否登录模拟账户？
- [ ] 模拟交易界面是否可见？
- [ ] 快捷键是否可用？

**测试**：
```bash
# 测试快捷键
python3 -c "
import pyautogui
import time
time.sleep(3)  # 切换到同花顺窗口
pyautogui.press('f1')  # 应该弹出买入窗口
"
```

### 问题2：找不到买入/卖出窗口

**原因**：窗口位置或界面布局不同

**解决**：
1. 手动按F1确认买入窗口能打开
2. 调整同花顺界面，让交易窗口在固定位置
3. 必要时修改代码中的坐标

### 问题3：价格输入错误

**解决**：
- 确保价格在涨跌停范围内
- 检查价格格式（保留2位小数）
- 使用实时价格而非过期价格

---

## 📈 实战案例

### 案例1：测试均线策略

```bash
# 1. 打开同花顺模拟交易
/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp

# 2. 登录模拟账户，查看初始资金

# 3. 运行策略
python3 my_simulator_trading.py

# 4. 观察策略执行
# - 信号生成
# - 自动交易
# - 账户变化

# 5. 一段时间后停止（Ctrl+C）

# 6. 在同花顺查看：
# - 持仓盈亏
# - 历史成交
# - 资金变化
```

### 案例2：单次测试

```python
#!/usr/bin/env python3
"""测试单次买入"""
import sys
sys.path.insert(0, '/home/wangxinghan/codetree/ai-trading-system')

from src.api.broker.tonghuashun_desktop import TonghuashunDesktop
from src.data.realtime_data import RealtimeDataFetcher

# 初始化
broker = TonghuashunDesktop({'auto_start': False})
fetcher = RealtimeDataFetcher()

# 获取实时价格
price = fetcher.get_realtime_price('600519')
print(f"贵州茅台当前价: {price}元")

# 确认
input("按Enter在模拟账户买入100股...")

# 执行买入
success, result = broker.buy('600519', price, 100)

if success:
    print("✅ 买入成功!")
    print("请在同花顺查看持仓")
else:
    print(f"❌ 买入失败: {result}")
```

---

## 🎓 进阶技巧

### 1. 定时执行

使用cron定时运行策略：

```bash
# 编辑crontab
crontab -e

# 添加：每小时执行一次
0 * * * * cd /home/wangxinghan/codetree/ai-trading-system && python3 my_simulator_trading.py >> logs/trading.log 2>&1
```

### 2. 多策略组合

```python
# 同时运行多个策略
strategies = ['MA', 'MACD', 'RSI']

for strategy_name in strategies:
    strategy = strategy_library.get_strategy(strategy_name)
    signals = strategy.generate_signals(market_data)
    # 合并信号，执行交易
```

### 3. 风控管理

```python
# 添加风控检查
def check_risk(signal, account_info):
    # 单笔最大10%资金
    if signal_value > account_info['total'] * 0.1:
        return False
    
    # 持仓不超过5只
    if len(positions) >= 5:
        return False
    
    return True
```

---

## 📚 相关文档

- [桌面交易指南](DESKTOP_TRADING_GUIDE.md) - 详细的桌面自动化说明
- [策略开发快速开始](STRATEGY_QUICKSTART.md) - 开发交易策略
- [K线数据获取](KLINE_DATA_GUIDE.md) - 获取市场数据

---

## 🎯 下一步

### 立即开始

1. **打开同花顺，登录模拟交易**
2. **运行测试脚本**：
   ```bash
   python3 examples/desktop_trading_auto.py
   ```
3. **观察执行结果**

### 推荐流程

```
同花顺模拟交易
    ↓
手动测试（熟悉界面）
    ↓
自动化测试（测试脚本）
    ↓
策略自动交易（策略+自动化）
    ↓
持续优化（分析改进）
    ↓
准备实盘
```

---

## ⚠️ 重要提醒

1. **模拟≠实盘** - 模拟交易没有滑点、情绪压力
2. **充分测试** - 至少运行1个月以上
3. **记录分析** - 详细记录每笔交易
4. **风控第一** - 设置止损，控制仓位
5. **小资金实盘** - 即使模拟盈利，实盘也要从小资金开始

---

**开始您的同花顺模拟交易之旅！** 📈🎮

有问题随时查看文档或调试代码。祝交易顺利！🚀
