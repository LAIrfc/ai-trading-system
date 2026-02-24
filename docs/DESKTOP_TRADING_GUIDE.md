# 桌面客户端自动化交易指南

## 概述

本系统支持直接控制同花顺桌面客户端，相比网页版有以下优势：

- ✅ **更稳定**: 使用本地应用，不受网页改版影响
- ✅ **更快**: 键盘快捷键操作，无需等待页面加载
- ✅ **更简单**: 如果已保存密码，可以自动登录
- ✅ **更可靠**: 不需要维护页面元素选择器

## 环境准备

### 1. 确认同花顺已安装

```bash
# 检查应用是否存在
ls -l /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp

# 如果存在，应该显示文件信息
```

### 2. 配置自动登录

在同花顺客户端中：
1. 登录一次
2. 勾选"记住密码"
3. 下次启动会自动登录

### 3. 安装Python依赖

```bash
cd /home/wangxinghan/codetree/ai-trading-system
source venv/bin/activate

# 安装桌面自动化库
pip install pyautogui==0.9.54
pip install psutil==5.9.5
pip install pillow==10.0.0
```

### 4. 测试安装

```python
import pyautogui
import psutil

# 测试鼠标移动
pyautogui.moveTo(100, 100, duration=1)
print("✅ pyautogui工作正常")

# 测试进程检测
for proc in psutil.process_iter(['name']):
    if 'python' in proc.info['name'].lower():
        print(f"✅ psutil工作正常")
        break
```

## 使用方式

### 快速开始

```bash
# 运行桌面交易演示
python examples/desktop_trading_demo.py
```

程序会：
1. 🚀 自动启动同花顺客户端
2. ⏳ 等待登录完成（如已保存密码会自动登录）
3. 📊 提供交互式菜单

### 编程使用

```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

# 配置
config = {
    'auto_start': True,           # 自动启动应用
    'screenshot_on_error': True,  # 出错时截图
    'operation_delay': 0.5,       # 操作延迟（秒）
}

# 初始化
broker = TonghuashunDesktop(config)

# 登录（会自动启动应用）
if broker.login():
    # 买入
    success, order_id = broker.buy(
        stock_code='600519',
        price=1800.0,
        quantity=100
    )
    
    if success:
        print(f"✅ 交易成功: {order_id}")
    
    # 登出
    broker.logout()

# 关闭应用
broker.close()
```

## 工作原理

### 1. 进程管理

```python
# 检查应用是否运行
broker._is_app_running()  # 返回 True/False

# 启动应用
broker._start_app()

# 关闭应用
broker._close_app()
```

### 2. 键盘操作

使用同花顺的标准快捷键：

| 快捷键 | 功能 |
|--------|------|
| F1 | 买入 |
| F2 | 卖出 |
| F3 | 撤单 |
| F4 | 查询 |
| Ctrl+A | 全选 |
| Enter | 确认 |
| Tab | 切换输入框 |

```python
# 按键
pyautogui.press('f1')  # 打开买入界面

# 组合键
pyautogui.hotkey('ctrl', 'a')  # 全选

# 输入文本
pyautogui.write('600519')  # 输入股票代码
```

### 3. 鼠标操作

```python
# 移动鼠标
pyautogui.moveTo(x, y, duration=1)

# 点击
pyautogui.click(x, y)

# 双击
pyautogui.doubleClick(x, y)
```

### 4. 图像识别（可选）

准备截图用于图像识别：

```bash
# 创建图片目录
mkdir -p config/images/tonghuashun

# 截图保存按钮等界面元素
```

使用：

```python
# 点击图片（如果找到）
broker._click_image('buy_button.png')
```

## 买卖操作流程

### 买入流程

```
1. 按F1进入买入界面
2. 输入股票代码
3. 按Enter确认代码
4. 按Tab切换到价格输入框
5. 输入价格
6. 按Tab切换到数量输入框
7. 输入数量
8. 按Enter确认
9. 按Y确认对话框
```

代码实现：

```python
def buy(self, stock_code: str, price: float, quantity: int):
    # 1. 打开买入界面
    pyautogui.press('f1')
    time.sleep(1)
    
    # 2. 输入代码
    pyautogui.hotkey('ctrl', 'a')
    pyautogui.write(stock_code)
    pyautogui.press('enter')
    time.sleep(1)
    
    # 3. 输入价格
    pyautogui.press('tab')
    pyautogui.hotkey('ctrl', 'a')
    pyautogui.write(str(price))
    
    # 4. 输入数量
    pyautogui.press('tab')
    pyautogui.hotkey('ctrl', 'a')
    pyautogui.write(str(quantity))
    
    # 5. 确认
    pyautogui.press('enter')
    time.sleep(1)
    pyautogui.press('y')
```

### 卖出流程

与买入类似，只是使用F2快捷键。

## 集成到策略系统

### 完整示例

```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop
from src.core.strategy import StrategyExecutor, StrategyRuleEngine
from src.core.risk import RiskManager

# 1. 初始化组件
broker = TonghuashunDesktop(config)
rule_engine = StrategyRuleEngine("my_strategy")
risk_manager = RiskManager(risk_config)

executor = StrategyExecutor(
    strategy_name="my_strategy",
    strategy_document=strategy_doc,
    rule_engine=rule_engine,
    risk_manager=risk_manager
)

# 2. 登录
if not broker.login():
    print("登录失败")
    exit(1)

# 3. 运行策略
while True:
    # 生成信号
    signals = my_strategy.generate_signals(market_data, positions)
    
    for signal in signals:
        # 规则和风控检查
        order = executor.process_signal(signal, market_data)
        
        if order:
            # 执行交易
            if signal['action'] == 'buy':
                success, result = broker.buy(
                    signal['stock_code'],
                    current_price,
                    100
                )
            elif signal['action'] == 'sell':
                success, result = broker.sell(
                    signal['stock_code'],
                    current_price,
                    100
                )
            
            if success:
                logger.info(f"交易成功: {result}")
    
    # 等待下一轮
    time.sleep(300)  # 5分钟

# 4. 清理
broker.logout()
broker.close()
```

## 定时任务

### 使用crontab

```bash
# 编辑crontab
crontab -e

# 添加定时任务（每天10:00执行）
0 10 * * 1-5 cd /home/wangxinghan/codetree/ai-trading-system && /home/wangxinghan/codetree/ai-trading-system/venv/bin/python scripts/daily_trading.py
```

### Python定时器

```python
import schedule
import time

def run_strategy():
    """执行策略"""
    broker = TonghuashunDesktop(config)
    
    try:
        if broker.login():
            # 执行交易逻辑
            pass
    finally:
        broker.close()

# 每隔30分钟执行
schedule.every(30).minutes.do(run_strategy)

# 主循环
while True:
    schedule.run_pending()
    time.sleep(60)
```

## 安全注意事项

### 1. 防止误操作

```python
# 设置安全区域（鼠标移到角落中断）
pyautogui.FAILSAFE = True

# 操作延迟（给用户反应时间）
pyautogui.PAUSE = 0.5
```

### 2. 出错时截图

```python
config = {
    'screenshot_on_error': True,  # 启用错误截图
}

# 错误时会自动保存到 logs/目录
```

### 3. 测试模式

先用小金额测试：

```python
# 测试买入最小单位
broker.buy('600519', 1800.0, 100)  # 100股
```

### 4. 监控日志

```python
# 查看操作日志
tail -f logs/trading.log
```

## 常见问题

### Q1: 应用启动失败

**检查**:
```bash
# 检查文件是否存在
ls -l /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp

# 检查权限
chmod +x /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp

# 手动启动测试
/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp
```

### Q2: 键盘输入失效

**原因**: 同花顺窗口未获得焦点

**解决**:
```python
# 确保窗口在前台
import pygetwindow as gw

windows = gw.getWindowsWithTitle('同花顺')
if windows:
    windows[0].activate()
```

### Q3: 输入速度过快

**解决**: 增加延迟

```python
config = {
    'operation_delay': 1.0,  # 增加到1秒
}
```

### Q4: 如何调试

```python
# 启用调试日志
logger.add("logs/debug.log", level="DEBUG")

# 每步操作后截图
pyautogui.screenshot('step1.png')
```

## 性能优化

### 1. 减少等待时间

```python
# 不用固定等待
time.sleep(2)

# 改用条件等待（需要图像识别）
while not found_element():
    time.sleep(0.1)
```

### 2. 批量操作

```python
# 批量下单
orders = [order1, order2, order3]

for order in orders:
    broker.buy(...)
    time.sleep(1)  # 短暂延迟
```

### 3. 重用应用实例

```python
# 不要每次都启动/关闭应用
broker = TonghuashunDesktop({'auto_start': True})

try:
    broker.login()
    
    # 执行多个操作
    for signal in signals:
        broker.buy(...)
        
finally:
    broker.close()  # 最后才关闭
```

## 与网页版对比

| 特性 | 桌面版 | 网页版 |
|------|--------|--------|
| 稳定性 | ✅ 高 | ⚠️ 中（受改版影响） |
| 速度 | ✅ 快 | ⚠️ 较慢 |
| 配置 | ✅ 简单 | ⚠️ 需要维护选择器 |
| 跨平台 | ❌ 仅Linux | ✅ 全平台 |
| 依赖 | pyautogui | Selenium+ChromeDriver |

## 总结

桌面客户端自动化是**最推荐**的方案，因为：

✅ **更稳定**: 不受网页改版影响  
✅ **更快速**: 键盘操作比网页快  
✅ **更简单**: 配置少，维护简单  
✅ **更可靠**: 使用官方客户端  

建议流程：
1. **阶段1**: 桌面客户端模拟盘（1-3个月）
2. **阶段2**: 策略优化和验证
3. **阶段3**: 对接券商API（可选）
4. **阶段4**: 小资金实盘测试
5. **阶段5**: 正式运行

祝交易顺利！📈
