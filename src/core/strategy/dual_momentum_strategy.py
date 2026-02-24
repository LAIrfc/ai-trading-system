"""
双核动量轮动策略 (Dual Momentum Rotational Strategy)

实现思路：
1. 绝对动量：当前价格 > N日均线，过滤掉下跌趋势的资产
2. 相对动量：计算M日涨幅，选择涨幅最大的K个资产
3. 定期调仓：每F个交易日重新计算并调整持仓
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from loguru import logger

from .base_strategy import BaseStrategy


class DualMomentumStrategy(BaseStrategy):
    """双核动量轮动策略"""
    
    def __init__(self, config: Dict):
        """
        初始化策略
        
        Args:
            config: 策略配置
                - absolute_period (int): 绝对动量周期N，默认200
                - relative_period (int): 相对动量周期M，默认60
                - rebalance_days (int): 调仓频率F，默认20
                - top_k (int): 持有资产数量K，默认1
                - etf_pool (List[str]): ETF池，默认['510300', '159949', '513100', '518880', '511520']
                - stop_loss (float): 单个持仓止损比例，默认-0.10
                - market_crash_threshold (float): 市场熔断阈值，默认-0.05
                - min_volume (float): 最小日均成交额（万元），默认5000
                - max_position (float): 单一资产最大仓位，默认0.30
        """
        super().__init__('双核动量轮动策略', config)
        
        # 策略参数
        self.absolute_period = config.get('absolute_period', 200)  # N
        self.relative_period = config.get('relative_period', 60)   # M
        self.rebalance_days = config.get('rebalance_days', 20)     # F
        self.top_k = config.get('top_k', 1)                        # K
        
        # ETF观察池
        self.etf_pool = config.get('etf_pool', [
            '510300',  # 沪深300
            '159949',  # 创业板50
            '513100',  # 纳指ETF
            '518880',  # 黄金ETF
            '511520',  # 国债ETF
        ])
        
        # 风控参数
        self.stop_loss = config.get('stop_loss', -0.10)                    # -10%止损
        self.market_crash_threshold = config.get('market_crash_threshold', -0.05)  # -5%熔断
        self.min_volume = config.get('min_volume', 5000)                   # 5000万日均成交额
        self.max_position = config.get('max_position', 0.30)               # 30%最大仓位
        
        # 状态变量
        self.last_rebalance_date = None
        self.days_since_rebalance = 0
        self.current_holdings = {}  # {code: {'price': float, 'shares': int}}
        self.blacklist = set()  # 止损黑名单
        self.emergency_mode = False  # 熔断模式
        self.emergency_until = None  # 熔断解除时间
        
        logger.info(f"双核动量策略初始化完成 | N={self.absolute_period}, M={self.relative_period}, "
                   f"F={self.rebalance_days}, K={self.top_k}")
    
    def calculate_absolute_momentum(self, data: pd.DataFrame) -> Dict[str, bool]:
        """
        计算绝对动量 - 判断是否通过N日均线过滤
        
        Args:
            data: 包含所有ETF数据的DataFrame
                  columns: MultiIndex (code, field)
                  index: DatetimeIndex
                  
        Returns:
            Dict[code, passed]: 是否通过绝对动量测试
        """
        results = {}
        
        for code in self.etf_pool:
            if code not in data.columns.get_level_values(0):
                logger.warning(f"ETF {code} 数据缺失，跳过")
                results[code] = False
                continue
            
            try:
                # 获取收盘价
                close_prices = data[code]['close']
                
                # 计算N日均线
                ma_n = close_prices.rolling(window=self.absolute_period).mean()
                
                # 当前价格 vs 均线
                current_price = close_prices.iloc[-1]
                current_ma = ma_n.iloc[-1]
                
                passed = current_price > current_ma
                results[code] = passed
                
                logger.debug(f"{code} | 当前价格={current_price:.2f}, "
                            f"{self.absolute_period}日均线={current_ma:.2f}, "
                            f"通过={'✓' if passed else '✗'}")
                
            except Exception as e:
                logger.error(f"计算 {code} 绝对动量失败: {e}")
                results[code] = False
        
        return results
    
    def calculate_relative_momentum(self, data: pd.DataFrame, candidates: List[str]) -> Dict[str, float]:
        """
        计算相对动量 - 过去M日的涨幅
        
        Args:
            data: 包含所有ETF数据的DataFrame
            candidates: 通过绝对动量测试的ETF代码列表
            
        Returns:
            Dict[code, momentum_score]: 动量得分（涨幅）
        """
        scores = {}
        
        for code in candidates:
            try:
                close_prices = data[code]['close']
                
                # 计算M日涨幅
                current_price = close_prices.iloc[-1]
                m_days_ago_price = close_prices.iloc[-self.relative_period]
                
                momentum = (current_price / m_days_ago_price) - 1
                scores[code] = momentum
                
                logger.debug(f"{code} | {self.relative_period}日涨幅={momentum*100:.2f}%")
                
            except Exception as e:
                logger.error(f"计算 {code} 相对动量失败: {e}")
                scores[code] = -999  # 赋予极低分数
        
        return scores
    
    def check_liquidity(self, data: pd.DataFrame, code: str) -> bool:
        """
        检查流动性 - 日均成交额是否满足要求
        
        Args:
            data: ETF数据
            code: ETF代码
            
        Returns:
            bool: 是否满足流动性要求
        """
        try:
            # 计算近20日平均成交额（元）
            volume = data[code]['volume']
            close = data[code]['close']
            turnover = (volume * close).tail(20).mean()
            
            # 转换为万元
            turnover_wan = turnover / 10000
            
            passed = turnover_wan >= self.min_volume
            
            if not passed:
                logger.warning(f"{code} 流动性不足: {turnover_wan:.0f}万 < {self.min_volume}万")
            
            return passed
            
        except Exception as e:
            logger.error(f"检查 {code} 流动性失败: {e}")
            return False
    
    def check_stop_loss(self, data: pd.DataFrame) -> List[str]:
        """
        检查持仓是否触发止损
        
        Returns:
            List[code]: 需要止损的ETF代码列表
        """
        to_stop = []
        
        for code, holding in self.current_holdings.items():
            try:
                current_price = data[code]['close'].iloc[-1]
                buy_price = holding['price']
                
                pnl = (current_price / buy_price) - 1
                
                if pnl <= self.stop_loss:
                    logger.warning(f"触发止损 | {code} | 买入价={buy_price:.2f}, "
                                 f"当前价={current_price:.2f}, 亏损={pnl*100:.2f}%")
                    to_stop.append(code)
                    self.blacklist.add(code)  # 加入黑名单
                    
            except Exception as e:
                logger.error(f"检查 {code} 止损失败: {e}")
        
        return to_stop
    
    def check_market_crash(self, data: pd.DataFrame) -> bool:
        """
        检查是否发生市场崩盘（以沪深300为基准）
        
        Returns:
            bool: 是否触发熔断
        """
        try:
            # 使用沪深300作为市场基准
            if '510300' not in data.columns.get_level_values(0):
                return False
            
            close_prices = data['510300']['close']
            today_return = (close_prices.iloc[-1] / close_prices.iloc[-2]) - 1
            
            if today_return <= self.market_crash_threshold:
                logger.error(f"市场熔断！单日跌幅 {today_return*100:.2f}% <= {self.market_crash_threshold*100:.2f}%")
                self.emergency_mode = True
                self.emergency_until = datetime.now() + timedelta(hours=24)
                return True
                
        except Exception as e:
            logger.error(f"检查市场熔断失败: {e}")
        
        return False
    
    def should_rebalance(self, current_date: datetime) -> bool:
        """判断是否应该调仓"""
        if self.last_rebalance_date is None:
            return True
        
        self.days_since_rebalance += 1
        
        if self.days_since_rebalance >= self.rebalance_days:
            return True
        
        return False
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data: 市场数据，MultiIndex columns (code, field)
            
        Returns:
            signals: DataFrame with columns ['code', 'signal', 'reason', 'momentum_score']
                    signal: 1=买入, 0=持有, -1=卖出
        """
        signals_list = []
        current_date = data.index[-1]
        
        logger.info(f"\n{'='*60}")
        logger.info(f"生成交易信号 | 日期: {current_date.strftime('%Y-%m-%d')}")
        logger.info(f"{'='*60}")
        
        # 1. 检查熔断模式
        if self.emergency_mode:
            if datetime.now() < self.emergency_until:
                logger.warning("处于熔断模式，清空所有持仓")
                for code in self.current_holdings.keys():
                    signals_list.append({
                        'code': code,
                        'signal': -1,
                        'reason': '熔断保护',
                        'momentum_score': 0
                    })
                return pd.DataFrame(signals_list)
            else:
                logger.info("熔断模式解除")
                self.emergency_mode = False
        
        # 2. 检查市场崩盘
        if self.check_market_crash(data):
            for code in self.current_holdings.keys():
                signals_list.append({
                    'code': code,
                    'signal': -1,
                    'reason': '市场熔断',
                    'momentum_score': 0
                })
            return pd.DataFrame(signals_list)
        
        # 3. 检查止损
        stop_codes = self.check_stop_loss(data)
        for code in stop_codes:
            signals_list.append({
                'code': code,
                'signal': -1,
                'reason': '触发止损',
                'momentum_score': 0
            })
        
        # 4. 判断是否需要调仓
        if not self.should_rebalance(current_date):
            logger.info(f"距离上次调仓 {self.days_since_rebalance} 天，未到调仓日")
            # 持有现有仓位
            for code in self.current_holdings.keys():
                if code not in stop_codes:  # 排除已止损的
                    signals_list.append({
                        'code': code,
                        'signal': 0,
                        'reason': '持有',
                        'momentum_score': 0
                    })
            return pd.DataFrame(signals_list)
        
        # 5. 调仓日：重新计算动量
        logger.info("到达调仓日，重新计算动量")
        
        # 5.1 计算绝对动量
        absolute_results = self.calculate_absolute_momentum(data)
        candidates = [code for code, passed in absolute_results.items() 
                     if passed and code not in self.blacklist]
        
        logger.info(f"通过绝对动量测试: {candidates}")
        
        # 5.2 过滤流动性
        liquid_candidates = [code for code in candidates 
                            if self.check_liquidity(data, code)]
        
        logger.info(f"通过流动性测试: {liquid_candidates}")
        
        # 5.3 如果没有合格资产，清仓
        if len(liquid_candidates) == 0:
            logger.warning("没有合格资产，清空所有持仓")
            for code in self.current_holdings.keys():
                signals_list.append({
                    'code': code,
                    'signal': -1,
                    'reason': '无合格资产',
                    'momentum_score': 0
                })
            self.last_rebalance_date = current_date
            self.days_since_rebalance = 0
            return pd.DataFrame(signals_list)
        
        # 5.4 计算相对动量
        momentum_scores = self.calculate_relative_momentum(data, liquid_candidates)
        
        # 5.5 排序并选择前K个
        sorted_assets = sorted(momentum_scores.items(), key=lambda x: x[1], reverse=True)
        top_assets = sorted_assets[:self.top_k]
        
        logger.info(f"动量排名前{self.top_k}:")
        for rank, (code, score) in enumerate(top_assets, 1):
            logger.info(f"  {rank}. {code}: {score*100:.2f}%")
        
        # 5.6 生成交易信号
        target_codes = set([code for code, score in top_assets])
        current_codes = set(self.current_holdings.keys())
        
        # 卖出不在目标中的
        to_sell = current_codes - target_codes
        for code in to_sell:
            signals_list.append({
                'code': code,
                'signal': -1,
                'reason': '轮出',
                'momentum_score': momentum_scores.get(code, 0)
            })
            logger.info(f"轮出: {code}")
        
        # 买入新目标
        to_buy = target_codes - current_codes
        for code in to_buy:
            signals_list.append({
                'code': code,
                'signal': 1,
                'reason': '轮入',
                'momentum_score': momentum_scores[code]
            })
            logger.info(f"轮入: {code} (动量={momentum_scores[code]*100:.2f}%)")
        
        # 持有已在目标中的
        to_hold = target_codes & current_codes
        for code in to_hold:
            signals_list.append({
                'code': code,
                'signal': 0,
                'reason': '持有',
                'momentum_score': momentum_scores[code]
            })
            logger.info(f"持有: {code}")
        
        # 更新调仓日期
        self.last_rebalance_date = current_date
        self.days_since_rebalance = 0
        
        # 清空黑名单（新调仓周期）
        self.blacklist.clear()
        
        return pd.DataFrame(signals_list)
    
    def calculate_position_size(self, signal: int, current_price: float, 
                               account_value: float, **kwargs) -> int:
        """
        计算仓位大小
        
        Args:
            signal: 交易信号 (1=买入)
            current_price: 当前价格
            account_value: 账户总价值
            
        Returns:
            shares: 股数（手）
        """
        if signal != 1:
            return 0
        
        # 等权重分配
        position_value = account_value / self.top_k
        
        # 限制最大仓位
        max_value = account_value * self.max_position
        position_value = min(position_value, max_value)
        
        # 计算股数（向下取整到100的倍数）
        shares = int(position_value / current_price / 100) * 100
        
        return shares
    
    def update_holdings(self, code: str, signal: int, price: float, shares: int):
        """更新持仓记录"""
        if signal == 1:  # 买入
            self.current_holdings[code] = {
                'price': price,
                'shares': shares
            }
        elif signal == -1:  # 卖出
            if code in self.current_holdings:
                del self.current_holdings[code]
    
    def get_strategy_info(self) -> Dict:
        """获取策略信息"""
        return {
            'name': '双核动量轮动策略',
            'version': 'v1.0',
            'type': '中频趋势跟踪 / 资产配置',
            'timeframe': '日线',
            'parameters': {
                'absolute_period': self.absolute_period,
                'relative_period': self.relative_period,
                'rebalance_days': self.rebalance_days,
                'top_k': self.top_k,
                'stop_loss': self.stop_loss,
                'market_crash_threshold': self.market_crash_threshold,
            },
            'etf_pool': self.etf_pool,
            'current_holdings': list(self.current_holdings.keys()),
            'blacklist': list(self.blacklist),
            'emergency_mode': self.emergency_mode,
        }
