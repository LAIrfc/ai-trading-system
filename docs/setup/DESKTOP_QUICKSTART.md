# 桌面客户端快速开始 🚀

> 您已经安装了同花顺客户端？太好了！这是最简单的方式！

## ✨ 5分钟快速开始

### Step 1: 安装依赖 (1分钟)

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 激活虚拟环境
source venv/bin/activate

# 安装桌面自动化库
pip install pyautogui psutil pillow
```

### Step 2: 一键运行 (30秒)

```bash
# 运行启动脚本
./scripts/run_desktop_trading.sh
```

就这么简单！程序会：
1. ✅ 自动启动同花顺客户端
2. ✅ 自动登录（如果已保存密码）
3. ✅ 显示交互菜单

### Step 3: 选择模式

程序会提示选择：

**模式1: 手动交易模式** (推荐新手)
- 程序启动同花顺
- 你可以手动操作
- 也可以让程序自动执行

**模式2: 自动化交易模式**
- 程序完全自动化
- 策略信号 → 规则检查 → 自动交易

## 🎯 工作原理

```
你的策略 → 生成信号 → 规则检查 → 键盘快捷键 → 同花顺执行
```

使用同花顺的标准快捷键：
- **F1**: 买入
- **F2**: 卖出
- **F3**: 撤单
- **F4**: 查询

## 💡 示例代码

```python
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

# 初始化
broker = TonghuashunDesktop({'auto_start': True})

# 登录（会自动启动应用）
if broker.login():
    # 买入100股
    success, result = broker.buy(
        stock_code='600519',  # 贵州茅台
        price=1800.0,
        quantity=100
    )
    
    if success:
        print("✅ 交易成功!")
    
    # 清理
    broker.close()
```

## ⚙️ 配置说明

程序会自动检测同花顺路径：
```
/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp
```

如果已经：
- ✅ 勾选了"记住密码"
- ✅ 可以自动登录

那么程序会完全自动化！

## 🎓 进阶使用

### 1. 集成到策略

```python
# 初始化
broker = TonghuashunDesktop(config)
executor = StrategyExecutor(...)

broker.login()

# 策略循环
while True:
    # 生成信号
    signals = my_strategy.generate_signals(...)
    
    for signal in signals:
        # 规则检查
        order = executor.process_signal(signal, market_data)
        
        if order:
            # 执行交易
            broker.buy(...)
    
    time.sleep(300)  # 5分钟
```

### 2. 定时任务

```bash
# 每天10:00自动运行
crontab -e

# 添加：
0 10 * * 1-5 /home/wangxinghan/codetree/ai-trading-system/scripts/run_desktop_trading.sh
```

## 📚 更多文档

| 文档 | 说明 |
|------|------|
| [DESKTOP_TRADING_GUIDE.md](docs/DESKTOP_TRADING_GUIDE.md) | 详细使用指南 |
| [STRATEGY_EXECUTION_GUIDE.md](docs/STRATEGY_EXECUTION_GUIDE.md) | 策略执行说明 |
| [QUICK_START.md](docs/QUICK_START.md) | 完整入门教程 |

## ⚠️ 重要提示

1. **测试模式**: 第一次使用建议选择"手动模式"观察流程
2. **小额测试**: 先用最小单位（100股）测试
3. **规则设置**: 在`config/strategy_rules.yaml`中配置交易规则
4. **审计日志**: 所有操作都会记录到`data/audit/`

## 🆚 为什么选择桌面版？

| 特性 | 桌面版 | 网页版 |
|------|--------|--------|
| 速度 | ⚡ 快 | 较慢 |
| 稳定性 | 💪 高 | 受改版影响 |
| 配置 | 🎯 简单 | 需要维护选择器 |
| 登录 | 🔐 自动 | 需要每次登录 |
| 推荐度 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |

## 🚀 立即开始

```bash
cd /home/wangxinghan/codetree/ai-trading-system
./scripts/run_desktop_trading.sh
```

**就是这么简单！**

---

💡 **提示**: 如果同花顺客户端路径不同，可以在代码中修改 `APP_PATH` 变量。

📖 **帮助**: 遇到问题？查看 [常见问题](docs/DESKTOP_TRADING_GUIDE.md#常见问题)

祝交易顺利！📈
