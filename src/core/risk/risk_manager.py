"""
风险管理器
实现多层风控机制
"""

from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger


class RiskManager:
    """风险管理器"""
    
    def __init__(self, config: Dict):
        """
        初始化风险管理器
        
        Args:
            config: 风控配置
        """
        self.config = config
        self.account_config = config.get('account_risk', {})
        self.strategy_config = config.get('strategy_risk', {})
        self.stock_config = config.get('stock_risk', {})
        self.trading_limits = config.get('trading_limits', {})
        
        # 风控状态
        self.is_circuit_breaker_triggered = False
        self.daily_loss = 0.0
        self.max_drawdown = 0.0
        self.trading_halted = False
        
        # 统计信息
        self.daily_trades_count = 0
        self.stock_trades_count = {}  # {stock_code: count}
        self.last_trade_time = {}  # {stock_code: timestamp}
        
    def check_account_risk(self, account_info: Dict) -> Tuple[bool, str]:
        """
        检查账户级风控
        
        Args:
            account_info: 账户信息
            
        Returns:
            (是否通过, 原因)
        """
        # 检查最大回撤
        current_drawdown = account_info.get('drawdown', 0.0)
        max_drawdown = self.account_config.get('max_drawdown', 0.20)
        
        if current_drawdown > max_drawdown:
            msg = f"最大回撤超限: {current_drawdown:.2%} > {max_drawdown:.2%}"
            logger.error(msg)
            self.trigger_emergency_exit("max_drawdown_reached")
            return False, msg
        
        # 检查单日亏损
        daily_loss_limit = self.account_config.get('daily_loss_limit', 0.05)
        daily_pnl_ratio = account_info.get('daily_pnl_ratio', 0.0)
        
        if daily_pnl_ratio < -daily_loss_limit:
            msg = f"单日亏损超限: {daily_pnl_ratio:.2%} < -{daily_loss_limit:.2%}"
            logger.error(msg)
            self.trigger_emergency_exit("daily_loss_limit_reached")
            return False, msg
        
        # 检查现金储备
        cash = account_info.get('cash', 0.0)
        min_cash = self.account_config.get('min_cash_reserve', 50000)
        
        if cash < min_cash:
            msg = f"现金储备不足: {cash:.2f} < {min_cash:.2f}"
            logger.warning(msg)
            return False, msg
        
        return True, "账户风控检查通过"
    
    def check_position_risk(self, stock_code: str, 
                           order_value: float,
                           current_position: float,
                           total_value: float) -> Tuple[bool, str]:
        """
        检查持仓风控
        
        Args:
            stock_code: 股票代码
            order_value: 订单金额
            current_position: 当前持仓金额
            total_value: 总资产
            
        Returns:
            (是否通过, 原因)
        """
        # 计算新的持仓金额
        new_position = current_position + order_value
        position_ratio = new_position / total_value
        
        # 检查单股最大仓位
        max_single = self.stock_config.get('max_single_position', 0.15)
        
        if position_ratio > max_single:
            msg = f"{stock_code} 单股仓位超限: {position_ratio:.2%} > {max_single:.2%}"
            logger.warning(msg)
            return False, msg
        
        # 检查单笔交易限制
        max_order = self.trading_limits.get('max_order_value', 500000)
        min_order = self.trading_limits.get('min_order_value', 5000)
        
        if abs(order_value) > max_order:
            msg = f"单笔交易金额超限: {abs(order_value):.2f} > {max_order:.2f}"
            logger.warning(msg)
            return False, msg
        
        if abs(order_value) < min_order:
            msg = f"单笔交易金额过小: {abs(order_value):.2f} < {min_order:.2f}"
            logger.warning(msg)
            return False, msg
        
        return True, "持仓风控检查通过"
    
    def check_trading_frequency(self, stock_code: str) -> Tuple[bool, str]:
        """
        检查交易频率限制
        
        Args:
            stock_code: 股票代码
            
        Returns:
            (是否通过, 原因)
        """
        # 检查单日总交易次数
        max_daily = self.trading_limits.get('max_daily_trades', 50)
        if self.daily_trades_count >= max_daily:
            msg = f"单日交易次数超限: {self.daily_trades_count} >= {max_daily}"
            logger.warning(msg)
            return False, msg
        
        # 检查单股交易次数
        max_stock_trades = self.trading_limits.get('max_stock_trades_per_day', 5)
        stock_count = self.stock_trades_count.get(stock_code, 0)
        
        if stock_count >= max_stock_trades:
            msg = f"{stock_code} 单日交易次数超限: {stock_count} >= {max_stock_trades}"
            logger.warning(msg)
            return False, msg
        
        return True, "交易频率检查通过"
    
    def check_stop_loss(self, stock_code: str,
                       entry_price: float,
                       current_price: float) -> Tuple[bool, str]:
        """
        检查止损
        
        Args:
            stock_code: 股票代码
            entry_price: 入场价格
            current_price: 当前价格
            
        Returns:
            (是否触发止损, 原因)
        """
        pnl_ratio = (current_price - entry_price) / entry_price
        stop_loss = self.stock_config.get('stop_loss', -0.08)
        
        if pnl_ratio <= stop_loss:
            msg = f"{stock_code} 触发止损: {pnl_ratio:.2%} <= {stop_loss:.2%}"
            logger.warning(msg)
            return True, msg
        
        return False, "未触发止损"
    
    def check_stop_profit(self, stock_code: str,
                         entry_price: float,
                         current_price: float) -> Tuple[bool, str]:
        """
        检查止盈
        
        Args:
            stock_code: 股票代码
            entry_price: 入场价格
            current_price: 当前价格
            
        Returns:
            (是否触发止盈, 原因)
        """
        pnl_ratio = (current_price - entry_price) / entry_price
        stop_profit = self.stock_config.get('stop_profit', 0.20)
        
        if pnl_ratio >= stop_profit:
            msg = f"{stock_code} 触发止盈: {pnl_ratio:.2%} >= {stop_profit:.2%}"
            logger.info(msg)
            return True, msg
        
        return False, "未触发止盈"
    
    def calculate_var(self, returns: pd.Series, confidence: float = 0.95) -> float:
        """
        计算VaR (Value at Risk)
        
        Args:
            returns: 收益率序列
            confidence: 置信度
            
        Returns:
            VaR值
        """
        if len(returns) == 0:
            return 0.0
        
        var = np.percentile(returns, (1 - confidence) * 100)
        return abs(var)
    
    def calculate_max_drawdown(self, equity_curve: pd.Series) -> float:
        """
        计算最大回撤
        
        Args:
            equity_curve: 权益曲线
            
        Returns:
            最大回撤
        """
        if len(equity_curve) == 0:
            return 0.0
        
        cumulative = equity_curve.cummax()
        drawdown = (equity_curve - cumulative) / cumulative
        max_dd = drawdown.min()
        
        return abs(max_dd)
    
    def check_market_risk(self, market_data: Dict) -> Tuple[bool, str]:
        """
        检查市场风险
        
        Args:
            market_data: 市场数据
            
        Returns:
            (是否可以交易, 原因)
        """
        market_config = self.config.get('market_risk', {})
        
        # 检查市场波动率
        market_volatility = market_data.get('volatility', 0.0)
        max_volatility = market_config.get('max_market_volatility', 0.03)
        
        if market_volatility > max_volatility:
            msg = f"市场波动率过高: {market_volatility:.2%} > {max_volatility:.2%}"
            logger.warning(msg)
            return False, msg
        
        # 检查熔断机制
        circuit_breaker = market_config.get('circuit_breaker', {})
        if circuit_breaker.get('enabled', True):
            index_change = market_data.get('index_change', 0.0)
            trigger_threshold = circuit_breaker.get('trigger_threshold', -0.05)
            
            if index_change <= trigger_threshold:
                msg = f"市场熔断触发: 指数跌幅 {index_change:.2%} <= {trigger_threshold:.2%}"
                logger.error(msg)
                self.trigger_circuit_breaker()
                return False, msg
        
        return True, "市场风险检查通过"
    
    def trigger_circuit_breaker(self):
        """触发熔断机制"""
        self.is_circuit_breaker_triggered = True
        self.trading_halted = True
        logger.critical("⚠️ 市场熔断机制已触发，交易已暂停！")
        
    def trigger_emergency_exit(self, reason: str):
        """
        触发紧急平仓
        
        Args:
            reason: 触发原因
        """
        logger.critical(f"🚨 紧急平仓触发: {reason}")
        self.trading_halted = True
        # 这里应该调用平仓逻辑
        
    def reset_daily_counters(self):
        """重置每日计数器"""
        self.daily_trades_count = 0
        self.stock_trades_count = {}
        self.daily_loss = 0.0
        logger.info("每日风控计数器已重置")
        
    def record_trade(self, stock_code: str):
        """
        记录交易
        
        Args:
            stock_code: 股票代码
        """
        self.daily_trades_count += 1
        self.stock_trades_count[stock_code] = self.stock_trades_count.get(stock_code, 0) + 1
        self.last_trade_time[stock_code] = datetime.now()
        
    def get_risk_report(self) -> Dict:
        """
        生成风控报告
        
        Returns:
            风控报告字典
        """
        return {
            'trading_halted': self.trading_halted,
            'circuit_breaker_triggered': self.is_circuit_breaker_triggered,
            'daily_trades_count': self.daily_trades_count,
            'max_drawdown': self.max_drawdown,
            'daily_loss': self.daily_loss,
        }
