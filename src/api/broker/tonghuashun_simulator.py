"""
同花顺模拟炒股网页自动化
"""

import time
from typing import Dict, List, Optional, Tuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from loguru import logger

from .web_broker_base import WebBrokerBase, Position, AccountInfo, OrderInfo


class TonghuashunSimulator(WebBrokerBase):
    """同花顺模拟炒股"""
    
    # 网址
    URL_LOGIN = "https://t.10jqka.com.cn/"  # 同花顺模拟炒股登录页
    URL_TRADE = "https://t.10jqka.com.cn/circle/index/"  # 交易页面
    
    def __init__(self, config: Dict):
        """
        初始化
        
        配置项：
        - username: 用户名
        - password: 密码
        - headless: 是否无头模式（默认False，建议调试时用False）
        - implicit_wait: 隐式等待时间（秒）
        """
        super().__init__(config)
        
        self.username = config.get('username')
        self.password = config.get('password')
        self.headless = config.get('headless', False)
        self.implicit_wait = config.get('implicit_wait', 10)
        
        if not self.username or not self.password:
            raise ValueError("需要配置username和password")
        
        logger.info("同花顺模拟炒股初始化")
    
    def _init_driver(self):
        """初始化浏览器驱动"""
        if self.driver:
            return
        
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--disable-gpu')
        
        # 反检测设置
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # 设置窗口大小
        chrome_options.add_argument('--window-size=1920,1080')
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(self.implicit_wait)
            
            # 执行CDP命令防止检测
            self.driver.execute_cdp_cmd(
                'Page.addScriptToEvaluateOnNewDocument',
                {'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'}
            )
            
            logger.info("浏览器驱动初始化成功")
        except Exception as e:
            logger.error(f"浏览器驱动初始化失败: {e}")
            logger.error("请确保已安装Chrome浏览器和ChromeDriver")
            raise
    
    def login(self) -> bool:
        """
        登录同花顺模拟炒股
        
        Returns:
            是否成功
        """
        try:
            self._init_driver()
            
            logger.info("正在访问同花顺模拟炒股...")
            self.driver.get(self.URL_LOGIN)
            time.sleep(2)
            
            # 等待登录框出现
            logger.info("等待登录框...")
            
            # 注意：实际的元素选择器需要根据同花顺的实际页面结构调整
            # 这里提供一个通用模板，需要根据实际情况修改
            
            try:
                # 点击登录按钮（如果有）
                login_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CLASS_NAME, "login-btn"))
                )
                login_btn.click()
                time.sleep(1)
            except TimeoutException:
                logger.debug("未找到登录按钮，可能已在登录页面")
            
            # 输入用户名
            logger.info("输入用户名...")
            username_input = self.driver.find_element(By.ID, "username")  # 需要根据实际调整
            username_input.clear()
            username_input.send_keys(self.username)
            
            # 输入密码
            logger.info("输入密码...")
            password_input = self.driver.find_element(By.ID, "password")  # 需要根据实际调整
            password_input.clear()
            password_input.send_keys(self.password)
            
            # 点击登录
            submit_btn = self.driver.find_element(By.ID, "submit")  # 需要根据实际调整
            submit_btn.click()
            
            # 等待登录成功
            time.sleep(3)
            
            # 验证登录状态
            if self._check_login_success():
                self.is_logged_in = True
                logger.success("✅ 登录成功")
                return True
            else:
                logger.error("❌ 登录失败")
                return False
                
        except Exception as e:
            logger.error(f"登录过程出错: {e}")
            return False
    
    def _check_login_success(self) -> bool:
        """检查是否登录成功"""
        try:
            # 检查是否存在用户信息元素
            # 需要根据实际页面调整
            user_element = self.driver.find_element(By.CLASS_NAME, "user-info")
            return user_element is not None
        except NoSuchElementException:
            return False
    
    def logout(self):
        """登出"""
        try:
            # 点击退出按钮
            logout_btn = self.driver.find_element(By.CLASS_NAME, "logout-btn")
            logout_btn.click()
            time.sleep(1)
            
            self.is_logged_in = False
            logger.info("已登出")
        except Exception as e:
            logger.error(f"登出失败: {e}")
    
    def get_account_info(self) -> Optional[AccountInfo]:
        """获取账户信息"""
        if not self.ensure_logged_in():
            return None
        
        try:
            # 进入账户页面
            self._navigate_to_account()
            
            # 解析账户信息
            # 以下选择器需要根据实际页面调整
            total_assets = self._parse_float(self._get_text('.total-assets'))
            available_cash = self._parse_float(self._get_text('.available-cash'))
            market_value = self._parse_float(self._get_text('.market-value'))
            total_profit_loss = self._parse_float(self._get_text('.total-profit'))
            
            # 获取持仓
            positions = self.get_positions()
            
            account_info = AccountInfo(
                total_assets=total_assets,
                available_cash=available_cash,
                frozen_cash=0.0,  # 需要从页面解析
                market_value=market_value,
                total_profit_loss=total_profit_loss,
                positions=positions
            )
            
            logger.info(f"账户总资产: {total_assets:,.2f}元")
            return account_info
            
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}")
            return None
    
    def get_positions(self) -> List[Position]:
        """获取持仓列表"""
        if not self.ensure_logged_in():
            return []
        
        try:
            # 进入持仓页面
            self._navigate_to_positions()
            
            positions = []
            
            # 查找持仓表格
            # 需要根据实际页面调整
            rows = self.driver.find_elements(By.CSS_SELECTOR, '.position-table tbody tr')
            
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, 'td')
                
                if len(cols) >= 8:
                    position = Position(
                        stock_code=cols[0].text,
                        stock_name=cols[1].text,
                        quantity=int(cols[2].text.replace(',', '')),
                        available=int(cols[3].text.replace(',', '')),
                        cost_price=float(cols[4].text),
                        current_price=float(cols[5].text),
                        market_value=float(cols[6].text.replace(',', '')),
                        profit_loss=float(cols[7].text.replace(',', '')),
                        profit_loss_ratio=float(cols[8].text.replace('%', '')) / 100
                    )
                    positions.append(position)
            
            logger.info(f"获取到{len(positions)}个持仓")
            return positions
            
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []
    
    def buy(self, stock_code: str, price: float, quantity: int) -> Tuple[bool, str]:
        """买入"""
        if not self.ensure_logged_in():
            return False, "未登录"
        
        try:
            logger.info(f"买入: {stock_code} @ {price} x {quantity}")
            
            # 进入交易页面
            self._navigate_to_trade()
            
            # 切换到买入tab
            buy_tab = self.driver.find_element(By.CSS_SELECTOR, '.tab-buy')
            buy_tab.click()
            time.sleep(0.5)
            
            # 输入股票代码
            code_input = self.driver.find_element(By.ID, 'stock-code-buy')
            code_input.clear()
            code_input.send_keys(stock_code)
            time.sleep(1)  # 等待股票信息加载
            
            # 输入价格
            price_input = self.driver.find_element(By.ID, 'buy-price')
            price_input.clear()
            price_input.send_keys(str(price))
            
            # 输入数量
            quantity_input = self.driver.find_element(By.ID, 'buy-quantity')
            quantity_input.clear()
            quantity_input.send_keys(str(quantity))
            
            # 点击买入按钮
            buy_btn = self.driver.find_element(By.ID, 'btn-buy')
            buy_btn.click()
            
            # 等待确认框
            time.sleep(1)
            
            # 点击确认
            confirm_btn = self.driver.find_element(By.CSS_SELECTOR, '.confirm-buy')
            confirm_btn.click()
            
            # 等待结果
            time.sleep(2)
            
            # 获取订单结果
            result_text = self._get_text('.trade-result')
            
            if '成功' in result_text:
                order_id = self._extract_order_id(result_text)
                logger.success(f"✅ 买入成功，订单号: {order_id}")
                return True, order_id
            else:
                logger.error(f"❌ 买入失败: {result_text}")
                return False, result_text
                
        except Exception as e:
            error_msg = f"买入操作失败: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    def sell(self, stock_code: str, price: float, quantity: int) -> Tuple[bool, str]:
        """卖出"""
        if not self.ensure_logged_in():
            return False, "未登录"
        
        try:
            logger.info(f"卖出: {stock_code} @ {price} x {quantity}")
            
            # 进入交易页面
            self._navigate_to_trade()
            
            # 切换到卖出tab
            sell_tab = self.driver.find_element(By.CSS_SELECTOR, '.tab-sell')
            sell_tab.click()
            time.sleep(0.5)
            
            # 输入股票代码
            code_input = self.driver.find_element(By.ID, 'stock-code-sell')
            code_input.clear()
            code_input.send_keys(stock_code)
            time.sleep(1)
            
            # 输入价格
            price_input = self.driver.find_element(By.ID, 'sell-price')
            price_input.clear()
            price_input.send_keys(str(price))
            
            # 输入数量
            quantity_input = self.driver.find_element(By.ID, 'sell-quantity')
            quantity_input.clear()
            quantity_input.send_keys(str(quantity))
            
            # 点击卖出按钮
            sell_btn = self.driver.find_element(By.ID, 'btn-sell')
            sell_btn.click()
            
            # 确认
            time.sleep(1)
            confirm_btn = self.driver.find_element(By.CSS_SELECTOR, '.confirm-sell')
            confirm_btn.click()
            
            time.sleep(2)
            
            # 获取结果
            result_text = self._get_text('.trade-result')
            
            if '成功' in result_text:
                order_id = self._extract_order_id(result_text)
                logger.success(f"✅ 卖出成功，订单号: {order_id}")
                return True, order_id
            else:
                logger.error(f"❌ 卖出失败: {result_text}")
                return False, result_text
                
        except Exception as e:
            error_msg = f"卖出操作失败: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        if not self.ensure_logged_in():
            return False
        
        try:
            logger.info(f"撤单: {order_id}")
            
            # 进入委托页面
            self._navigate_to_orders()
            
            # 查找订单并撤销
            cancel_btn = self.driver.find_element(
                By.CSS_SELECTOR, 
                f'tr[data-order-id="{order_id}"] .btn-cancel'
            )
            cancel_btn.click()
            
            # 确认撤单
            time.sleep(0.5)
            confirm_btn = self.driver.find_element(By.CSS_SELECTOR, '.confirm-cancel')
            confirm_btn.click()
            
            time.sleep(1)
            
            logger.success(f"✅ 撤单成功: {order_id}")
            return True
            
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False
    
    def get_orders(self, status: Optional[str] = None) -> List[OrderInfo]:
        """获取订单列表"""
        if not self.ensure_logged_in():
            return []
        
        try:
            # 进入委托页面
            self._navigate_to_orders()
            
            orders = []
            
            # 查找订单表格
            rows = self.driver.find_elements(By.CSS_SELECTOR, '.order-table tbody tr')
            
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, 'td')
                
                if len(cols) >= 8:
                    order_status = cols[7].text
                    
                    # 状态过滤
                    if status and order_status != status:
                        continue
                    
                    order = OrderInfo(
                        order_id=cols[0].text,
                        stock_code=cols[1].text,
                        stock_name=cols[2].text,
                        action=cols[3].text,
                        price=float(cols[4].text),
                        quantity=int(cols[5].text.replace(',', '')),
                        filled_quantity=int(cols[6].text.replace(',', '')),
                        status=order_status,
                        submit_time=cols[8].text
                    )
                    orders.append(order)
            
            logger.info(f"获取到{len(orders)}个订单")
            return orders
            
        except Exception as e:
            logger.error(f"获取订单失败: {e}")
            return []
    
    def get_current_price(self, stock_code: str) -> Optional[float]:
        """获取当前价格"""
        try:
            # 可以通过交易页面的报价获取
            self._navigate_to_trade()
            
            # 输入股票代码触发报价
            code_input = self.driver.find_element(By.ID, 'stock-code-buy')
            code_input.clear()
            code_input.send_keys(stock_code)
            time.sleep(1)
            
            # 读取当前价
            price_element = self.driver.find_element(By.CLASS_NAME, 'current-price')
            price = float(price_element.text)
            
            return price
            
        except Exception as e:
            logger.error(f"获取价格失败: {e}")
            return None
    
    # 辅助方法
    
    def _navigate_to_account(self):
        """导航到账户页面"""
        try:
            account_link = self.driver.find_element(By.LINK_TEXT, '账户')
            account_link.click()
            time.sleep(1)
        except Exception as e:
            logger.debug(f"导航到账户页面: {e}")
    
    def _navigate_to_positions(self):
        """导航到持仓页面"""
        try:
            positions_link = self.driver.find_element(By.LINK_TEXT, '持仓')
            positions_link.click()
            time.sleep(1)
        except Exception as e:
            logger.debug(f"导航到持仓页面: {e}")
    
    def _navigate_to_trade(self):
        """导航到交易页面"""
        try:
            if self.driver.current_url != self.URL_TRADE:
                self.driver.get(self.URL_TRADE)
                time.sleep(2)
        except Exception as e:
            logger.debug(f"导航到交易页面: {e}")
    
    def _navigate_to_orders(self):
        """导航到委托页面"""
        try:
            orders_link = self.driver.find_element(By.LINK_TEXT, '委托')
            orders_link.click()
            time.sleep(1)
        except Exception as e:
            logger.debug(f"导航到委托页面: {e}")
    
    def _get_text(self, selector: str) -> str:
        """获取元素文本"""
        try:
            element = self.driver.find_element(By.CSS_SELECTOR, selector)
            return element.text.strip()
        except Exception:
            return ""
    
    def _parse_float(self, text: str) -> float:
        """解析浮点数"""
        try:
            # 移除逗号和其他符号
            cleaned = text.replace(',', '').replace('元', '').replace('+', '').strip()
            return float(cleaned)
        except Exception:
            return 0.0
    
    def _extract_order_id(self, text: str) -> str:
        """从结果文本中提取订单号"""
        # 需要根据实际返回格式调整
        import re
        match = re.search(r'订单号[:：](\d+)', text)
        if match:
            return match.group(1)
        return ""


# 使用示例
if __name__ == '__main__':
    config = {
        'username': 'your_username',
        'password': 'your_password',
        'headless': False,  # 调试时建议用False，可以看到浏览器操作
    }
    
    broker = TonghuashunSimulator(config)
    
    # 登录
    if broker.login():
        # 获取账户信息
        account = broker.get_account_info()
        if account:
            print(f"总资产: {account.total_assets:,.2f}元")
            print(f"可用资金: {account.available_cash:,.2f}元")
            print(f"持仓数: {len(account.positions)}")
        
        # 获取持仓
        positions = broker.get_positions()
        for pos in positions:
            print(f"{pos.stock_name}({pos.stock_code}): {pos.quantity}股, "
                  f"盈亏: {pos.profit_loss:+.2f}元 ({pos.profit_loss_ratio:+.2%})")
        
        # 买入示例
        # success, result = broker.buy('600519', 1800.0, 100)
        # print(f"买入结果: {success}, {result}")
        
        # 登出
        broker.logout()
    
    # 关闭浏览器
    broker.close()
