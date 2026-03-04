# 桌面客户端交易指南

> 直接控制同花顺桌面客户端，比网页版更稳定、更快、更简单。

---

## 一、5 分钟快速开始

### 1. 安装依赖

```bash
cd /path/to/ai-trading-system
source venv/bin/activate
pip install pyautogui psutil pillow
```

### 2. 一键运行

```bash
./scripts/run_desktop_trading.sh
```

程序会：自动启动同花顺、自动登录（若已保存密码）、显示交互菜单。

### 3. 选择模式

- **手动交易模式**（推荐新手）：程序启动同花顺，你可手动操作或让程序执行。
- **自动化交易模式**：策略信号 → 规则检查 → 自动交易。

### 4. 工作原理简述

```
你的策略 → 生成信号 → 规则检查 → 键盘快捷键 → 同花顺执行
```

常用快捷键：**F1** 买入、**F2** 卖出、**F3** 撤单、**F4** 查询。

### 5. 最小示例

```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

broker = TonghuashunDesktop({'auto_start': True})
if broker.login():
    success, result = broker.buy(stock_code='600519', price=1800.0, quantity=100)
    if success:
        print("✅ 交易成功!")
    broker.close()
```

同花顺路径（Linux）：`/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp`。若已勾选「记住密码」，可完全自动登录。

**更多文档**：[QUICK_START.md](QUICK_START.md) | [WINDOWS_GUIDE.md](WINDOWS_GUIDE.md) | [TROUBLESHOOTING_TKINTER.md](TROUBLESHOOTING_TKINTER.md) | [策略执行指南](../strategy/STRATEGY_EXECUTION_GUIDE.md)

---

## 二、环境准备（详细）

### 1. 确认同花顺已安装

```bash
ls -l /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp
```

### 2. 配置自动登录

在同花顺中登录一次并勾选「记住密码」，下次启动会自动登录。

### 3. 安装 Python 依赖（版本可选）

```bash
pip install pyautogui psutil pillow
```

### 4. 测试安装

```python
import pyautogui, psutil
pyautogui.moveTo(100, 100, duration=1)
# 若可移动则 pyautogui/psutil 正常
```

---

## 三、使用方式

### 快速演示

```bash
python examples/desktop_trading_demo.py
```

### 编程使用

```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

config = {
    'auto_start': True,
    'screenshot_on_error': True,
    'operation_delay': 0.5,
}
broker = TonghuashunDesktop(config)
if broker.login():
    success, order_id = broker.buy('600519', 1800.0, 100)
    broker.logout()
broker.close()
```

---

## 四、工作原理（键盘 / 鼠标）

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| F1 | 买入 |
| F2 | 卖出 |
| F3 | 撤单 |
| F4 | 查询 |
| Ctrl+A | 全选 |
| Enter | 确认 |
| Tab | 切换输入框 |

### 买入流程（代码逻辑）

1. 按 F1 进入买入界面  
2. 输入股票代码 → Enter  
3. Tab 到价格 → 输入价格  
4. Tab 到数量 → 输入数量  
5. Enter → Y 确认  

---

## 五、集成到策略系统

```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop
from src.core.strategy import StrategyExecutor
from src.core.risk import RiskManager

broker = TonghuashunDesktop(config)
# ... 初始化 executor, risk_manager ...

if broker.login():
    while True:
        signals = my_strategy.generate_signals(market_data, positions)
        for signal in signals:
            order = executor.process_signal(signal, market_data)
            if order:
                broker.buy(...)  # 或 broker.sell(...)
        time.sleep(300)
broker.close()
```

---

## 六、定时任务

```bash
crontab -e
# 每天 10:00 执行（周一至五）
0 10 * * 1-5 /path/to/ai-trading-system/scripts/run_desktop_trading.sh
```

---

## 七、安全与注意

- 设置 `pyautogui.FAILSAFE = True`（鼠标移到角落可中断）。
- 首次使用建议手动模式、最小单位（如 100 股）测试。
- 规则配置：`config/strategy_rules.yaml`（若使用执行器）。
- 出错时可开启 `screenshot_on_error: True`，截图保存到日志目录。

---

## 八、常见问题

**Q: 应用启动失败**  
检查路径与权限：`ls -l /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp`，必要时 `chmod +x`。

**Q: 键盘输入无效**  
确保同花顺窗口获得焦点（可配合 pygetwindow 激活窗口）。

**Q: 输入过快**  
增大配置中的 `operation_delay`（如 1.0 秒）。

**Q: 如何调试**  
启用 DEBUG 日志；每步后 `pyautogui.screenshot('step.png')` 排查。

---

## 九、与网页版对比

| 特性 | 桌面版 | 网页版 |
|------|--------|--------|
| 稳定性 | 高 | 受改版影响 |
| 速度 | 快 | 较慢 |
| 配置 | 简单 | 需维护选择器 |
| 登录 | 可自动 | 常需每次登录 |

建议：先桌面模拟盘 1–3 个月 → 策略优化 → 再考虑小资金实盘或券商 API。

祝交易顺利。
