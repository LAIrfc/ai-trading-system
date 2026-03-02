# 网页自动化交易指南

## 概述

本系统支持通过浏览器自动化进行交易，特别适合使用模拟盘（如同花顺模拟炒股）进行策略调试和验证。

## 为什么使用网页自动化？

### 优势

1. **快速验证**: 无需等待券商API申请，立即开始测试
2. **真实环境**: 模拟盘环境与实盘高度相似
3. **零成本**: 模拟交易不需要真实资金
4. **安全**: 在模拟环境充分测试后再上实盘
5. **通用性**: 理论上支持任何有网页版的交易系统

### 劣势

1. **速度较慢**: 相比API，网页操作有延迟
2. **稳定性**: 网页改版需要更新选择器
3. **维护成本**: 需要适配不同券商的页面

## 环境准备

### 1. 安装依赖

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 激活虚拟环境
source venv/bin/activate

# 安装Selenium
pip install selenium==4.15.2
pip install webdriver-manager==4.0.1
```

### 2. 安装Chrome浏览器

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install google-chrome-stable

# 或者下载ChromeDriver
# https://chromedriver.chromium.org/downloads
```

### 3. 验证安装

```python
from selenium import webdriver

# 测试Chrome驱动
driver = webdriver.Chrome()
driver.get("https://www.baidu.com")
print("浏览器启动成功!")
driver.quit()
```

## 同花顺模拟炒股配置

### 1. 注册账号

访问 [同花顺模拟炒股](https://t.10jqka.com.cn/) 注册账号

### 2. 配置连接

```python
from src.api.broker.tonghuashun_simulator import TonghuashunSimulator

config = {
    'username': 'your_username',      # 用户名
    'password': 'your_password',      # 密码
    'headless': False,                # 是否无头模式
    'implicit_wait': 10,              # 等待时间(秒)
}

broker = TonghuashunSimulator(config)
```

### 3. 测试登录

```python
if broker.login():
    print("登录成功!")
    
    # 获取账户信息
    account = broker.get_account_info()
    print(f"总资产: {account.total_assets:,.2f}元")
    
    # 登出
    broker.logout()
    
# 关闭浏览器
broker.close()
```

## 页面元素适配

### 重要提示

**网页元素选择器需要根据实际页面调整！**

同花顺（或其他券商）的网页可能会改版，导致选择器失效。你需要：

1. 使用Chrome开发者工具（F12）查看页面结构
2. 找到对应元素的ID、Class或CSS选择器
3. 更新 `tonghuashun_simulator.py` 中的选择器

### 示例：查找登录按钮

1. 打开同花顺模拟炒股页面
2. 按F12打开开发者工具
3. 点击"元素选择器"图标
4. 点击登录按钮
5. 在Elements标签页查看HTML结构

```html
<!-- 示例HTML -->
<button id="login-btn" class="btn btn-primary">登录</button>
```

更新代码：

```python
# 原来的代码
login_btn = self.driver.find_element(By.ID, "submit")

# 更新为
login_btn = self.driver.find_element(By.ID, "login-btn")
# 或者
login_btn = self.driver.find_element(By.CSS_SELECTOR, ".btn-primary")
```

### 常见选择器

| 方法 | 示例 | 说明 |
|------|------|------|
| `By.ID` | `"username"` | 通过ID查找 |
| `By.CLASS_NAME` | `"login-btn"` | 通过类名查找 |
| `By.CSS_SELECTOR` | `".btn-primary"` | 通过CSS选择器 |
| `By.XPATH` | `"//button[@id='login']"` | 通过XPath |
| `By.LINK_TEXT` | `"登录"` | 通过链接文字 |

## 集成到策略系统

### 完整示例

```python
from src.api.broker.tonghuashun_simulator import TonghuashunSimulator
from src.core.strategy import StrategyExecutor, StrategyRuleEngine
from src.core.risk import RiskManager

# 1. 初始化券商接口
broker_config = {
    'username': 'your_username',
    'password': 'your_password',
    'headless': False,
}
broker = TonghuashunSimulator(broker_config)

# 2. 登录
if not broker.login():
    print("登录失败")
    exit(1)

# 3. 初始化策略系统
rule_engine = StrategyRuleEngine("my_strategy")
risk_manager = RiskManager(risk_config)
executor = StrategyExecutor(
    strategy_name="my_strategy",
    strategy_document=strategy_doc,
    rule_engine=rule_engine,
    risk_manager=risk_manager
)

# 4. 生成交易信号
signal = {
    'stock_code': '600519',
    'action': 'buy',
    'target_position': 0.10,
}

# 5. 获取当前价格
current_price = broker.get_current_price(signal['stock_code'])

market_data = {
    signal['stock_code']: {
        'price': current_price,
        'volume': 50000000,
    }
}

# 6. 策略执行器处理（规则+风控检查）
order = executor.process_signal(signal, market_data)

if order:
    # 7. 计算交易数量
    account = broker.get_account_info()
    target_value = account.total_assets * signal['target_position']
    quantity = int(target_value / current_price / 100) * 100  # 整百股
    
    # 8. 执行交易
    success, order_id = broker.buy(
        stock_code=signal['stock_code'],
        price=current_price,
        quantity=quantity
    )
    
    if success:
        print(f"交易成功! 订单号: {order_id}")
    else:
        print(f"交易失败: {order_id}")
else:
    print("信号被拒绝")

# 9. 清理
broker.logout()
broker.close()
```

## 自动化交易流程

### 定时执行策略

```python
import schedule
import time

def run_strategy():
    """执行策略"""
    print(f"[{datetime.now()}] 执行策略...")
    
    # 1. 登录
    if not broker.login():
        logger.error("登录失败")
        return
    
    try:
        # 2. 获取账户和持仓信息
        account = broker.get_account_info()
        positions = broker.get_positions()
        
        # 3. 策略计算（生成信号）
        signals = my_strategy.generate_signals(market_data, positions)
        
        # 4. 处理每个信号
        for signal in signals:
            # 规则和风控检查
            order = executor.process_signal(signal, market_data)
            
            if order:
                # 执行交易
                if signal['action'] == 'buy':
                    success, result = broker.buy(...)
                elif signal['action'] == 'sell':
                    success, result = broker.sell(...)
                    
                if success:
                    logger.info(f"交易成功: {result}")
        
    finally:
        # 5. 登出
        broker.logout()

# 每隔30分钟执行一次
schedule.every(30).minutes.do(run_strategy)

# 或者在特定时间执行
schedule.every().day.at("10:00").do(run_strategy)
schedule.every().day.at("14:00").do(run_strategy)

# 主循环
while True:
    schedule.run_pending()
    time.sleep(60)
```

## 调试技巧

### 1. 可视化模式

调试时使用 `headless=False`，可以看到浏览器操作：

```python
config = {
    'headless': False,  # 显示浏览器
}
```

### 2. 截图保存

操作失败时保存截图：

```python
try:
    login_btn.click()
except Exception as e:
    # 保存截图
    self.driver.save_screenshot('error.png')
    logger.error(f"操作失败: {e}")
```

### 3. 增加等待时间

如果页面加载慢，增加等待时间：

```python
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 显式等待（最多等待10秒）
element = WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.ID, "myElement"))
)
```

### 4. 打印页面信息

```python
# 打印当前URL
print(self.driver.current_url)

# 打印页面源码
print(self.driver.page_source)

# 打印标题
print(self.driver.title)
```

## 常见问题

### Q1: ChromeDriver版本不匹配

**错误**: `This version of ChromeDriver only supports Chrome version XX`

**解决**:
```bash
# 使用webdriver-manager自动管理
pip install webdriver-manager

# 代码中使用
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install())
)
```

### Q2: 元素找不到

**错误**: `NoSuchElementException`

**解决**:
1. 检查选择器是否正确
2. 增加等待时间
3. 使用显式等待
4. 检查是否在iframe中

```python
# 切换到iframe
iframe = driver.find_element(By.ID, "myframe")
driver.switch_to.frame(iframe)

# 切换回主页面
driver.switch_to.default_content()
```

### Q3: 页面加载慢

**解决**:
```python
# 增加隐式等待
driver.implicitly_wait(20)

# 或使用显式等待
WebDriverWait(driver, 20).until(
    EC.presence_of_element_located((By.ID, "element"))
)

# 等待页面加载完成
driver.execute_script("return document.readyState") == "complete"
```

### Q4: 反爬虫检测

有些网站会检测Selenium，解决方法：

```python
options = webdriver.ChromeOptions()

# 禁用自动化标识
options.add_experimental_option('excludeSwitches', ['enable-automation'])
options.add_experimental_option('useAutomationExtension', False)

driver = webdriver.Chrome(options=options)

# 移除webdriver特征
driver.execute_cdp_cmd(
    'Page.addScriptToEvaluateOnNewDocument',
    {'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'}
)
```

## 其他券商适配

### 适配流程

1. 创建新的类，继承 `WebBrokerBase`
2. 实现所有抽象方法
3. 根据实际页面更新选择器
4. 测试各项功能

### 示例模板

```python
from src.api.broker.web_broker_base import WebBrokerBase

class MyBrokerSimulator(WebBrokerBase):
    """我的券商模拟盘"""
    
    def login(self) -> bool:
        # 实现登录逻辑
        pass
    
    def get_account_info(self) -> Optional[AccountInfo]:
        # 实现获取账户信息
        pass
    
    def buy(self, stock_code, price, quantity) -> Tuple[bool, str]:
        # 实现买入逻辑
        pass
    
    # ... 实现其他方法
```

## 安全建议

1. **不要提交密码**: 配置文件加入 `.gitignore`
2. **使用环境变量**: 

```python
import os

config = {
    'username': os.getenv('BROKER_USERNAME'),
    'password': os.getenv('BROKER_PASSWORD'),
}
```

3. **限制权限**: 仅在测试环境使用
4. **定期更新**: 及时更新依赖库
5. **异常处理**: 完善的错误处理和日志

## 运行演示

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 激活虚拟环境
source venv/bin/activate

# 运行演示
python examples/web_trading_demo.py
```

## 总结

网页自动化交易是在真正对接券商API之前，验证策略和系统的最佳方式：

✅ **优点**:
- 快速开始，无需等待API申请
- 真实模拟环境
- 零成本测试

⚠️ **注意**:
- 需要维护页面选择器
- 速度较API慢
- 适合低频策略

建议流程：
1. **阶段1**: 网页模拟盘验证策略逻辑
2. **阶段2**: 继续优化和回测
3. **阶段3**: 对接真实券商API
4. **阶段4**: 小资金实盘测试
5. **阶段5**: 正式运行

祝交易顺利！📈
