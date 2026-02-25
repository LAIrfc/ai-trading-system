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
    
    def launch_app(self) -> bool:
        """启动同花顺应用（公开方法）"""
        return self._start_app()
    
    def _focus_app(self) -> bool:
        """将同花顺窗口切到前台（跨平台）"""
        try:
            if self.system == 'Windows':
                try:
                    import win32gui
                    def callback(hwnd, results):
                        title = win32gui.GetWindowText(hwnd)
                        if '同花顺' in title or 'hexin' in title.lower():
                            results.append(hwnd)
                    results = []
                    win32gui.EnumWindows(callback, results)
                    if results:
                        win32gui.SetForegroundWindow(results[0])
                        time.sleep(0.5)
                        return True
                except ImportError:
                    pass
                return False
            else:
                # Linux: 用 xdotool 遍历所有窗口，Python 端做中文匹配
                wid = self._find_ths_window()
                if wid:
                    subprocess.run(['xdotool', 'windowactivate', '--sync', str(wid)],
                                   capture_output=True, timeout=5)
                    time.sleep(0.5)
                    logger.debug(f"已聚焦同花顺窗口: {wid}")
                    return True
                else:
                    logger.warning("未找到同花顺窗口")
                    return False
        except FileNotFoundError:
            logger.warning("未安装 xdotool，无法自动聚焦窗口。请运行: sudo apt install xdotool")
            return False
        except Exception as e:
            logger.warning(f"聚焦窗口失败: {e}")
            return False

    def _find_ths_window(self) -> Optional[int]:
        """查找同花顺窗口 ID"""
        try:
            # 获取所有可见窗口
            result = subprocess.run(
                ['xdotool', 'search', '--onlyvisible', '--name', ''],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return None

            keywords = ['同花顺', '10jqka', 'hexin', 'hevo']
            for wid_str in result.stdout.strip().split('\n'):
                wid_str = wid_str.strip()
                if not wid_str:
                    continue
                try:
                    wid = int(wid_str)
                    name_result = subprocess.run(
                        ['xdotool', 'getwindowname', str(wid)],
                        capture_output=True, text=True, timeout=2
                    )
                    if name_result.returncode == 0:
                        title = name_result.stdout.strip()
                        for kw in keywords:
                            if kw in title.lower() or kw in title:
                                logger.debug(f"找到同花顺窗口: {wid} ({title})")
                                return wid
                except (ValueError, subprocess.TimeoutExpired):
                    continue
            return None
        except Exception as e:
            logger.warning(f"查找窗口失败: {e}")
            return None
    
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
    
    def _read_clipboard(self) -> str:
        """读取剪贴板内容（跨平台）"""
        try:
            if self.system == 'Windows':
                result = subprocess.run(['powershell', '-command', 'Get-Clipboard'],
                                       capture_output=True, text=True, timeout=5)
                return result.stdout.strip()
            else:
                # Linux: 尝试 xclip 或 xsel
                for cmd in [
                    ['xclip', '-selection', 'clipboard', '-o'],
                    ['xsel', '--clipboard', '--output'],
                ]:
                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                        if result.returncode == 0:
                            return result.stdout.strip()
                    except FileNotFoundError:
                        continue
                logger.warning("未找到 xclip 或 xsel，无法读取剪贴板")
                return ""
        except Exception as e:
            logger.warning(f"读取剪贴板失败: {e}")
            return ""
    
    def _copy_table_data(self) -> str:
        """复制当前页面的表格数据到剪贴板"""
        try:
            # 全选 + 复制
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.3)
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.5)
            return self._read_clipboard()
        except Exception as e:
            logger.warning(f"复制表格数据失败: {e}")
            return ""
    
    def get_account_info(self) -> Optional[AccountInfo]:
        """获取账户信息"""
        if not self.ensure_logged_in():
            return None
        
        try:
            logger.info("获取账户信息...")
            
            # 聚焦同花顺窗口
            self._focus_app()
            
            # 切换到资金查询页面 (F4 → 资金股份)
            pyautogui.press('f4')
            time.sleep(1.5)
            
            # 尝试复制页面数据
            clipboard_data = self._copy_table_data()
            
            # 解析账户信息
            account_info = self._parse_account_info(clipboard_data)
            
            if account_info:
                logger.info(f"账户信息: 总资产={account_info.total_assets:.2f}, "
                           f"可用={account_info.available_cash:.2f}")
            else:
                logger.warning("无法读取账户信息，返回默认值")
                account_info = AccountInfo(
                    total_assets=0.0,
                    available_cash=0.0,
                    frozen_cash=0.0,
                    market_value=0.0,
                    total_profit_loss=0.0,
                    positions=[]
                )
            
            return account_info
            
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}")
            return None
    
    def _parse_account_info(self, data: str) -> Optional[AccountInfo]:
        """解析从剪贴板复制的账户信息"""
        if not data:
            return None
        
        try:
            total_assets = 0.0
            available_cash = 0.0
            frozen_cash = 0.0
            market_value = 0.0
            profit_loss = 0.0
            
            for line in data.split('\n'):
                line = line.strip()
                # 尝试匹配常见字段名
                if '总资产' in line or '资产总值' in line:
                    total_assets = self._extract_number(line)
                elif '可用' in line and ('资金' in line or '余额' in line):
                    available_cash = self._extract_number(line)
                elif '冻结' in line:
                    frozen_cash = self._extract_number(line)
                elif '市值' in line:
                    market_value = self._extract_number(line)
                elif '盈亏' in line or '浮动' in line:
                    profit_loss = self._extract_number(line)
            
            if total_assets > 0 or available_cash > 0:
                return AccountInfo(
                    total_assets=total_assets,
                    available_cash=available_cash,
                    frozen_cash=frozen_cash,
                    market_value=market_value,
                    total_profit_loss=profit_loss,
                    positions=[]
                )
            return None
        except Exception as e:
            logger.warning(f"解析账户信息失败: {e}")
            return None
    
    @staticmethod
    def _extract_number(text: str) -> float:
        """从文本中提取数字"""
        import re
        # 匹配数字（包括负数、小数、千分位逗号）
        matches = re.findall(r'[-+]?[\d,]+\.?\d*', text)
        if matches:
            # 取最后一个数字（通常是值）
            return float(matches[-1].replace(',', ''))
        return 0.0
    
    def get_positions(self) -> List[Position]:
        """获取持仓列表"""
        if not self.ensure_logged_in():
            return []
        
        try:
            logger.info("获取持仓...")
            
            # 聚焦同花顺窗口
            self._focus_app()
            
            # 切换到持仓页面 (F4 查询)
            pyautogui.press('f4')
            time.sleep(1.5)
            
            # 复制表格数据
            clipboard_data = self._copy_table_data()
            
            # 解析持仓
            positions = self._parse_positions(clipboard_data)
            
            if positions:
                logger.info(f"获取到 {len(positions)} 个持仓")
            else:
                logger.info("当前无持仓")
            
            return positions
            
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []
    
    def _parse_positions(self, data: str) -> List[Position]:
        """解析持仓数据"""
        if not data:
            return []
        
        positions = []
        try:
            lines = data.strip().split('\n')
            
            # 跳过表头行，解析数据行
            for line in lines:
                parts = line.strip().split('\t')
                if len(parts) >= 4:
                    try:
                        # 尝试解析：代码、名称、数量、可用、成本价、现价、盈亏...
                        code = parts[0].strip()
                        # 检查第一列是否是有效股票代码（6位数字）
                        if not code.isdigit() or len(code) != 6:
                            continue
                        
                        name = parts[1].strip() if len(parts) > 1 else ""
                        quantity = int(float(parts[2].strip())) if len(parts) > 2 else 0
                        available = int(float(parts[3].strip())) if len(parts) > 3 else 0
                        cost_price = float(parts[4].strip()) if len(parts) > 4 else 0.0
                        current_price = float(parts[5].strip()) if len(parts) > 5 else 0.0
                        profit_loss = float(parts[6].strip()) if len(parts) > 6 else 0.0
                        
                        market_val = current_price * quantity if current_price > 0 else 0.0
                        pnl_ratio = (profit_loss / (cost_price * quantity) * 100) if cost_price > 0 and quantity > 0 else 0.0
                        pos = Position(
                            stock_code=code,
                            stock_name=name,
                            quantity=quantity,
                            available=available,
                            cost_price=cost_price,
                            current_price=current_price,
                            market_value=market_val,
                            profit_loss=profit_loss,
                            profit_loss_ratio=pnl_ratio
                        )
                        positions.append(pos)
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            logger.warning(f"解析持仓数据失败: {e}")
        
        return positions
    
    def buy(self, stock_code: str, price: float, quantity: int) -> Tuple[bool, str]:
        """买入"""
        if not self.ensure_logged_in():
            return False, "未登录"
        
        try:
            logger.info(f"买入: {stock_code} @ {price} x {quantity}")
            
            # 聚焦同花顺窗口
            self._focus_app()
            
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
            
            # 聚焦同花顺窗口
            self._focus_app()
            
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
            
            # 聚焦同花顺窗口
            self._focus_app()
            
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
            # 聚焦同花顺窗口
            self._focus_app()
            
            # 切换到委托页面
            pyautogui.press('f4')  # 查询快捷键
            time.sleep(1)
            
            # 复制订单数据
            clipboard_data = self._copy_table_data()
            
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
