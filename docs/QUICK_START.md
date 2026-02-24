# 快速入门指南

欢迎使用AI量化交易系统！本指南将帮助您在10分钟内开始第一次模拟交易。

## 第一步：环境配置 (2分钟)

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 运行快速启动脚本
./scripts/quick_start.sh

# 或者手动配置
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 第二步：注册模拟盘账号 (3分钟)

1. 访问 [同花顺模拟炒股](https://t.10jqka.com.cn/)
2. 注册账号（免费）
3. 记下用户名和密码

## 第三步：配置策略规则 (2分钟)

```bash
# 复制配置模板
cp config/strategy_rules.yaml.example config/strategy_rules.yaml
cp config/broker_config.yaml.example config/broker_config.yaml

# 编辑broker_config.yaml，填入同花顺账号
vim config/broker_config.yaml
```

修改以下内容：

```yaml
tonghuashun_simulator:
  username: "your_username"  # 改成你的用户名
  password: "your_password"  # 改成你的密码
  headless: false  # 第一次建议用false观察流程
```

## 第四步：运行第一个交易 (3分钟)

```bash
# 运行网页交易演示
python examples/web_trading_demo.py
```

程序会：
1. 🔐 自动打开浏览器并登录同花顺
2. 💰 显示你的账户信息
3. 📊 等待你选择操作

**尝试以下操作：**

- 选择 `1` 查看账户信息
- 选择 `2` 查看持仓
- 选择 `3` 模拟策略买入（会先检查规则！）

## 🎉 恭喜！你已经完成第一次自动化交易

## 下一步学习

### 1. 理解策略规则系统

```bash
# 查看策略执行演示
python examples/strict_execution_demo.py
```

这个演示展示：
- ✅ 如何定义策略规则
- ✅ 规则如何自动检查交易信号
- ✅ 规则违反时如何拒绝交易
- ✅ 完整的审计追踪

### 2. 自定义策略规则

编辑 `config/strategy_rules.yaml`，例如：

```yaml
entry_rules:
  - rule_id: "my_price_rule"
    name: "我的价格限制"
    description: "只买10-50元的股票"
    condition:
      type: "price_range"
      min_price: 10.0
      max_price: 50.0
    mandatory: true  # 强制执行
```

### 3. 编写自己的策略

创建 `my_strategy.py`：

```python
from src.core.strategy.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    def generate_signals(self, market_data, current_positions):
        """生成交易信号"""
        signals = []
        
        # 你的策略逻辑
        # ...
        
        return signals
```

### 4. 集成到自动交易

```python
from src.api.broker.tonghuashun_simulator import TonghuashunSimulator
from src.core.strategy import StrategyExecutor

# 初始化
broker = TonghuashunSimulator(config)
executor = StrategyExecutor(...)

# 登录
broker.login()

# 运行策略
signals = my_strategy.generate_signals(...)

for signal in signals:
    # 自动进行规则和风控检查
    order = executor.process_signal(signal, market_data)
    
    if order:
        # 执行交易
        success, result = broker.buy(...)
```

## 常见问题

### Q: 浏览器打不开？

**A**: 检查Chrome是否安装：

```bash
# Ubuntu
sudo apt install google-chrome-stable

# 或下载ChromeDriver
# https://chromedriver.chromium.org/
```

### Q: 登录失败？

**A**: 
1. 检查用户名密码是否正确
2. 尝试手动登录网页版确认账号状态
3. 查看浏览器窗口，可能需要验证码

### Q: 找不到页面元素？

**A**: 同花顺可能改版了，需要更新选择器：

1. 按 F12 打开开发者工具
2. 找到对应元素的ID/Class
3. 更新 `tonghuashun_simulator.py` 中的选择器

详见 [网页自动化交易指南](WEB_TRADING_GUIDE.md)

### Q: 交易被拒绝？

**A**: 这是正常的风控机制！查看原因：

```python
# 查看审计日志
logs = executor.get_audit_logs(order_id)
for log in logs:
    print(log.event_type, log.details)
```

可能原因：
- 价格超出规则限制
- 仓位超限
- 交易时间不符
- 流动性不足

## 学习路径

### 🌱 初学者 (第1-2周)

1. ✅ 完成快速入门
2. ✅ 理解策略规则系统
3. ✅ 尝试修改规则参数
4. ✅ 运行几天模拟交易

**目标**: 熟悉系统操作，理解规则重要性

### 🌿 进阶 (第3-4周)

1. ✅ 学习回测系统
2. ✅ 编写简单策略（如动量策略）
3. ✅ 优化策略参数
4. ✅ 添加自定义规则

**目标**: 能够开发和测试自己的策略

### 🌳 高级 (第5-8周)

1. ✅ 集成AI模型
2. ✅ 多策略组合
3. ✅ 高级风控
4. ✅ 性能优化

**目标**: 构建完整的量化交易系统

### 🚀 实盘准备 (第9-12周)

1. ✅ 长期模拟盘验证（至少3个月）
2. ✅ 对接真实券商API
3. ✅ 小资金实盘测试
4. ✅ 监控和优化

**目标**: 安全上线实盘交易

## 重要文档

| 文档 | 说明 |
|------|------|
| [README.md](../README.md) | 项目总览 |
| [DESIGN.md](DESIGN.md) | 系统设计 |
| [STRATEGY_EXECUTION_GUIDE.md](STRATEGY_EXECUTION_GUIDE.md) | 策略执行详解 |
| [WEB_TRADING_GUIDE.md](WEB_TRADING_GUIDE.md) | 网页交易指南 |

## 获取帮助

遇到问题？

1. 📖 查看文档目录
2. 🔍 搜索代码注释
3. 🐛 检查日志文件 `logs/`
4. 💡 参考示例代码 `examples/`

## 下一步

选择你的学习路径：

- **想快速测试？** → 继续使用 `web_trading_demo.py`
- **想理解规则？** → 运行 `strict_execution_demo.py`
- **想开发策略？** → 查看 `src/core/strategy/example_strategy.py`
- **想了解设计？** → 阅读 `docs/DESIGN.md`

**记住：策略的价值在于严格执行，而非频繁调整！** 📈

祝交易顺利！🚀
