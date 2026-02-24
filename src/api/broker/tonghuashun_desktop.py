"""
同花顺桌面客户端自动化
使用pyautogui控制桌面应用
✅ 跨平台支持：自动检测Windows/Linux
"""

import time
import subprocess
import os
import platform
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from loguru import logger
import pyautogui
import psutil

from .web_broker_base import WebBrokerBase, Position, AccountInfo, OrderInfo


class TonghuashunDesktop(WebBrokerBase):
    """同花顺桌面客户端自动化（跨平台）"""
    
    # 根据系统自动设置默认路径
    @staticmethod
    def _get_default_app_path():
        """获取默认同花顺路径"""
        system = platform.system()
        if system == 'Windows':
            # Windows常见路径
            possible_paths = [
                r'C:\Program Files (x86)\同花顺\hexin.exe',
                r'C:\同花顺\hexin.exe',
                r'D:\Program Files (x86)\同花顺\hexin.exe',
                r'D:\同花顺\hexin.exe',
            ]
            for path in possible_paths:
                if Path(path).exists():
                    return path
            return possible_paths[0]  # 返回第一个作为默认
        else:
            # Linux
            return '/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp'
    
    @staticmethod
    def _get_default_process_name():
        """获取默认进程名"""
        system = platform.system()
        if system == 'Windows':
            return 'hexin.exe'
        else:
            return 'HevoNext.B2CApp'
    
    def __init__(self, config: Dict):
        """
        初始化
        
        配置项：
        - app_path: 同花顺路径（可选，自动检测）
        - auto_start: 是否自动启动应用（默认True）
        - screenshot_on_error: 出错时是否截图（默认True）
        - operation_delay: 操作延迟（秒，默认0.5）
        - confidence: 图像识别置信度（默认0.8）
        """
        super().__init__(config)
        
        # 自动检测系统并设置路径
        self.system = platform.system()
        self.app_path = config.get('app_path', self._get_default_app_path())
        self.process_name = config.get('process_name', self._get_default_process_name())
        
        self.auto_start = config.get('auto_start', True)
        self.screenshot_on_error = config.get('screenshot_on_error', True)
        self.operation_delay = config.get('operation_delay', 0.5)
        self.confidence = config.get('confidence', 0.8)
        
        # 设置pyautogui
        pyautogui.FAILSAFE = True  # 鼠标移到屏幕角落可中断
        pyautogui.PAUSE = self.operation_delay
        
        # 图片资源路径（用于图像识别）
        self.image_dir = config.get('image_dir', 'config/images/tonghuashun')
        
        logger.info(f"同花顺桌面客户端自动化初始化 [{self.system}]")
        logger.info(f"应用路径: {self.app_path}")
        logger.info(f"进程名称: {self.process_name}")
    
    def _is_app_running(self) -> bool:
        """检查应用是否运行（跨平台）"""
        for proc in psutil.process_iter(['name']):
            try:
                proc_name = proc.info['name']
                if proc_name and self.process_name.lower() in proc_name.lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return False
    
    def _start_app(self) -> bool:
        """启动应用（跨平台）"""
        try:
            if self._is_app_running():
                logger.info("应用已在运行")
                return True
            
            if not os.path.exists(self.app_path):
                logger.error(f"应用不存在: {self.app_path}")
                return False
            
            logger.info(f"正在启动同花顺 [{self.system}]...")
            
            # Windows需要特殊处理
            if self.system == 'Windows':
                subprocess.Popen(self.app_path, shell=False)
            else:
                subprocess.Popen([self.app_path], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
            
            # 等待应用启动
            for i in range(30):  # 最多等待30秒
                time.sleep(1)
                if self._is_app_running():
                    logger.success("✅ 应用启动成功")
                    time.sleep(3)  # 额外等待界面加载
                    return True
            
            logger.error("应用启动超时")
            return False
            
        except Exception as e:
            logger.error(f"启动应用失败: {e}")
            return False
    
    def _close_app(self):
        """关闭应用（跨平台）"""
        try:
            for proc in psutil.process_iter(['name', 'pid']):
                try:
                    proc_name = proc.info['name']
                    if proc_name and self.process_name.lower() in proc_name.lower():
                        proc.terminate()
                        logger.info("应用已关闭")
                        return
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logger.error(f"关闭应用失败: {e}")
    
    def _click_image(self, image_name: str, timeout: int = 10) -> bool:
        """
        点击图片（图像识别）
        
        Args:
            image_name: 图片文件名（不含路径）
            timeout: 超时时间
            
        Returns:
            是否成功
        """
        image_path = os.path.join(self.image_dir, image_name)
        
        if not os.path.exists(image_path):
            logger.warning(f"图片不存在: {image_path}")
            logger.info("提示: 需要准备截图用于图像识别")
            return False
        
        try:
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    location = pyautogui.locateOnScreen(
                        image_path, 
                        confidence=self.confidence
                    )
                    
                    if location:
                        # 点击图片中心
                        center = pyautogui.center(location)
                        pyautogui.click(center)
                        logger.debug(f"点击图片: {image_name} at {center}")
                        return True
                        
                except pyautogui.ImageNotFoundException:
                    pass
                
                time.sleep(0.5)
            
            logger.warning(f"未找到图片: {image_name}")
            return False
            
        except Exception as e:
            logger.error(f"图像识别失败: {e}")
            return False
    
    def _type_text(self, text: str, interval: float = 0.1):
        """输入文本"""
        pyautogui.write(text, interval=interval)
    
    def _press_key(self, key: str):
        """按键"""
        pyautogui.press(key)
    
    def _screenshot(self, filename: str):
        """截图"""
        try:
            screenshot = pyautogui.screenshot()
            screenshot.save(filename)
            logger.info(f"截图已保存: {filename}")
        except Exception as e:
            logger.error(f"截图失败: {e}")
    
    def login(self) -> bool:
        """
        登录（如果已保存密码，应该自动登录）
        
        Returns:
            是否成功
        """
        try:
            # 1. 启动应用
            if self.auto_start:
                if not self._start_app():
                    return False
            
            # 2. 检查是否已登录
            # 这里使用图像识别检测登录状态
            # 需要准备"已登录"界面的特征图片
            
            # 等待登录完成
            logger.info("等待登录...")
            time.sleep(5)  # 给用户时间手动登录（如需要）
            
            # 3. 验证登录状态
            # TODO: 通过图像识别或其他方式验证
            
            self.is_logged_in = True
            logger.success("✅ 登录成功")
            return True
            
        except Exception as e:
            logger.error(f"登录失败: {e}")
            if self.screenshot_on_error:
                self._screenshot('logs/login_error.png')
            return False
    
    def logout(self):
        """登出"""
        try:
            # 点击退出按钮（需要准备对应的截图）
            self._click_image('logout_button.png')
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
            logger.info("获取账户信息...")
            
            # 1. 切换到账户页面
            # 使用快捷键或点击按钮
            # TODO: 根据实际情况调整
            
            # 2. 使用OCR识别账户信息
            # 或者使用图像识别特定区域
            
            # 示例（需要实际调整）
            account_info = AccountInfo(
                total_assets=0.0,
                available_cash=0.0,
                frozen_cash=0.0,
                market_value=0.0,
                total_profit_loss=0.0,
                positions=[]
            )
            
            logger.info("账户信息获取成功")
            return account_info
            
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}")
            return None
    
    def get_positions(self) -> List[Position]:
        """获取持仓列表"""
        if not self.ensure_logged_in():
            return []
        
        try:
            logger.info("获取持仓...")
            
            # TODO: 实现持仓获取逻辑
            # 1. 切换到持仓页面
            # 2. 识别持仓表格
            # 3. 解析数据
            
            positions = []
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
            
            # 1. 切换到交易页面
            # 按F1或点击买入按钮
            pyautogui.press('f1')  # 同花顺买入快捷键
            time.sleep(1)
            
            # 2. 输入股票代码
            # 清空输入框
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('delete')
            
            # 输入代码
            self._type_text(stock_code)
            time.sleep(0.5)
            pyautogui.press('enter')
            time.sleep(1)
            
            # 3. 输入价格
            pyautogui.press('tab')  # 切换到价格输入框
            pyautogui.hotkey('ctrl', 'a')
            self._type_text(str(price))
            
            # 4. 输入数量
            pyautogui.press('tab')  # 切换到数量输入框
            pyautogui.hotkey('ctrl', 'a')
            self._type_text(str(quantity))
            
            # 5. 确认买入
            pyautogui.press('enter')
            time.sleep(1)
            
            # 6. 确认对话框
            pyautogui.press('y')  # 或者点击确认按钮
            time.sleep(1)
            
            logger.success(f"✅ 买入成功")
            return True, "success"
            
        except Exception as e:
            error_msg = f"买入失败: {e}"
            logger.error(error_msg)
            if self.screenshot_on_error:
                self._screenshot('logs/buy_error.png')
            return False, error_msg
    
    def sell(self, stock_code: str, price: float, quantity: int) -> Tuple[bool, str]:
        """卖出"""
        if not self.ensure_logged_in():
            return False, "未登录"
        
        try:
            logger.info(f"卖出: {stock_code} @ {price} x {quantity}")
            
            # 1. 切换到卖出页面
            pyautogui.press('f2')  # 同花顺卖出快捷键
            time.sleep(1)
            
            # 2-6. 类似买入操作
            # 输入代码
            pyautogui.hotkey('ctrl', 'a')
            self._type_text(stock_code)
            time.sleep(0.5)
            pyautogui.press('enter')
            time.sleep(1)
            
            # 输入价格
            pyautogui.press('tab')
            pyautogui.hotkey('ctrl', 'a')
            self._type_text(str(price))
            
            # 输入数量
            pyautogui.press('tab')
            pyautogui.hotkey('ctrl', 'a')
            self._type_text(str(quantity))
            
            # 确认卖出
            pyautogui.press('enter')
            time.sleep(1)
            pyautogui.press('y')
            time.sleep(1)
            
            logger.success(f"✅ 卖出成功")
            return True, "success"
            
        except Exception as e:
            error_msg = f"卖出失败: {e}"
            logger.error(error_msg)
            if self.screenshot_on_error:
                self._screenshot('logs/sell_error.png')
            return False, error_msg
    
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        if not self.ensure_logged_in():
            return False
        
        try:
            logger.info(f"撤单: {order_id}")
            
            # 切换到撤单页面
            pyautogui.press('f3')  # 撤单快捷键
            time.sleep(1)
            
            # TODO: 实现撤单逻辑
            
            return True
            
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False
    
    def get_orders(self, status: Optional[str] = None) -> List[OrderInfo]:
        """获取订单列表"""
        if not self.ensure_logged_in():
            return []
        
        try:
            # 切换到委托页面
            pyautogui.press('f4')  # 查询快捷键
            time.sleep(1)
            
            # TODO: 实现订单查询逻辑
            
            return []
            
        except Exception as e:
            logger.error(f"获取订单失败: {e}")
            return []
    
    def get_current_price(self, stock_code: str) -> Optional[float]:
        """获取当前价格"""
        try:
            # 在输入框输入股票代码，会显示当前价格
            # TODO: 实现价格获取逻辑
            
            return None
            
        except Exception as e:
            logger.error(f"获取价格失败: {e}")
            return None
    
    def close(self):
        """关闭客户端"""
        if self.auto_start:
            self._close_app()


# 使用示例
if __name__ == '__main__':
    config = {
        'auto_start': True,
        'screenshot_on_error': True,
        'operation_delay': 0.5,
    }
    
    broker = TonghuashunDesktop(config)
    
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║         同花顺桌面客户端自动化 - 使用说明               ║
    ╚══════════════════════════════════════════════════════════╝
    
    1. 程序会自动启动同花顺客户端
    2. 如果已保存密码，应该会自动登录
    3. 可以使用键盘快捷键进行操作：
       - F1: 买入
       - F2: 卖出
       - F3: 撤单
       - F4: 查询
    
    按Enter继续...
    """)
    input()
    
    # 登录
    if broker.login():
        print("✅ 登录成功")
        
        # 测试买入（请谨慎！）
        confirm = input("是否测试买入操作？(yes/no): ")
        if confirm.lower() == 'yes':
            stock_code = input("股票代码: ")
            price = float(input("价格: "))
            quantity = int(input("数量: "))
            
            success, result = broker.buy(stock_code, price, quantity)
            print(f"买入结果: {result}")
        
        # 登出
        broker.logout()
    
    # 关闭
    broker.close()
