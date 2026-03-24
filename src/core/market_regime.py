"""
市场状态识别引擎 (MarketRegimeEngine)

功能：
- 基于沪深300指数判断当前市场状态
- 状态分类：bull（牛市）、bear（熊市）、sideways（震荡）
- 用于动态调整策略权重

判断规则：
1. 趋势判断：MA20 vs MA200
2. 波动率判断：当前波动率 vs 历史波动率
3. 综合判断：
   - 牛市：MA20 > MA200 且 波动率 < 历史均值
   - 熊市：MA20 < MA200 且 波动率 > 历史均值
   - 震荡：其他情况

用法：
    engine = MarketRegimeEngine()
    regime = engine.get_current_regime()  # 'bull', 'bear', 'sideways'
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# 进程级缓存：避免重复获取指数数据
_REGIME_CACHE: Dict[str, Tuple[str, str, pd.DataFrame]] = {}


class MarketRegimeEngine:
    """市场状态识别引擎"""
    
    def __init__(self, 
                 index_symbol: str = "000300",  # 沪深300
                 short_ma: int = 20,
                 long_ma: int = 200,
                 vol_window: int = 20,
                 vol_lookback: int = 252):
        """
        Parameters:
            index_symbol: 指数代码（默认沪深300）
            short_ma: 短期均线周期
            long_ma: 长期均线周期
            vol_window: 波动率计算窗口
            vol_lookback: 历史波动率参考周期
        """
        self.index_symbol = index_symbol
        self.short_ma = short_ma
        self.long_ma = long_ma
        self.vol_window = vol_window
        self.vol_lookback = vol_lookback
        
        self.index_data: Optional[pd.DataFrame] = None
        self.regime_series: Optional[pd.Series] = None
    
    def _fetch_index_data(self, days: int = 400) -> Optional[pd.DataFrame]:
        """
        获取指数数据（使用baostock，最稳定）
        
        Returns:
            DataFrame with columns: date, close, high, low
        """
        today = datetime.now().strftime("%Y%m%d")
        cache_key = f"{self.index_symbol}_{days}"
        
        # 检查缓存（当天有效）
        if cache_key in _REGIME_CACHE:
            cached_date, cached_data_date, cached_df = _REGIME_CACHE[cache_key]
            if cached_date == today:
                logger.debug(f"[MarketRegime] 使用缓存的{self.index_symbol}数据")
                return cached_df
        
        try:
            import baostock as bs
            
            # 登录baostock
            lg = bs.login()
            if lg.error_code != '0':
                logger.error(f"[MarketRegime] baostock登录失败: {lg.error_msg}")
                return None
            
            # 计算日期范围
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days + 30)).strftime("%Y-%m-%d")
            
            # 沪深300指数代码映射
            index_code_map = {
                '000300': 'sh.000300',  # 沪深300
                '000001': 'sh.000001',  # 上证指数
                '399001': 'sz.399001',  # 深证成指
            }
            
            bs_code = index_code_map.get(self.index_symbol, f'sh.{self.index_symbol}')
            
            # 获取指数数据
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close",
                start_date=start_date,
                end_date=end_date,
                frequency="d"
            )
            
            if rs.error_code != '0':
                logger.error(f"[MarketRegime] 获取指数数据失败: {rs.error_msg}")
                bs.logout()
                return None
            
            # 转换为DataFrame
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            bs.logout()
            
            if not data_list:
                logger.warning(f"[MarketRegime] 指数数据为空")
                return None
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            df['date'] = pd.to_datetime(df['date'])
            for col in ['open', 'high', 'low', 'close']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df.dropna(subset=['close']).sort_values('date').reset_index(drop=True)
            
            if len(df) < 50:
                logger.warning(f"[MarketRegime] 指数数据不足: {len(df)}条")
                return None
            
            # 缓存
            _REGIME_CACHE[cache_key] = (today, today, df)
            logger.info(f"[MarketRegime] 获取{self.index_symbol}数据成功: {len(df)}条")
            return df
            
        except Exception as e:
            logger.error(f"[MarketRegime] 获取指数数据失败: {e}")
            try:
                bs.logout()
            except:
                pass
            return None
    
    def classify_regime(self, df: Optional[pd.DataFrame] = None) -> pd.Series:
        """
        对整个时间序列进行市场状态分类
        
        Parameters:
            df: 指数数据（如果为None，则自动获取）
        
        Returns:
            pd.Series: 每日的市场状态 ('bull', 'bear', 'sideways')
        """
        if df is None:
            df = self._fetch_index_data()
        
        if df is None or df.empty:
            return pd.Series()
        
        self.index_data = df.copy()
        
        # 计算技术指标
        df['ma20'] = df['close'].rolling(self.short_ma).mean()
        df['ma200'] = df['close'].rolling(self.long_ma).mean()
        
        # 计算波动率
        df['returns'] = df['close'].pct_change()
        df['vol20'] = df['returns'].rolling(self.vol_window).std()
        df['vol_mean'] = df['vol20'].rolling(self.vol_lookback).mean()
        
        # 分类规则
        conditions = [
            # 牛市：短期均线 > 长期均线 且 波动率 < 历史均值
            (df['ma20'] > df['ma200']) & (df['vol20'] < df['vol_mean']),
            # 熊市：短期均线 < 长期均线 且 波动率 > 历史均值
            (df['ma20'] < df['ma200']) & (df['vol20'] > df['vol_mean']),
        ]
        choices = ['bull', 'bear']
        df['regime'] = np.select(conditions, choices, default='sideways')
        
        self.regime_series = df.set_index('date')['regime']
        return self.regime_series
    
    def get_regime(self, date: Optional[datetime] = None) -> str:
        """
        获取特定日期的市场状态
        
        Parameters:
            date: 日期（如果为None，返回最新状态）
        
        Returns:
            'bull', 'bear', 'sideways'
        """
        if self.regime_series is None or self.regime_series.empty:
            self.classify_regime()
        
        if self.regime_series is None or self.regime_series.empty:
            return 'sideways'  # 默认值
        
        if date is None:
            return str(self.regime_series.iloc[-1])
        
        # 查找最接近的日期
        try:
            if isinstance(date, str):
                date = pd.to_datetime(date)
            
            # 找到小于等于目标日期的最近日期
            valid_dates = self.regime_series.index[self.regime_series.index <= date]
            if len(valid_dates) == 0:
                return 'sideways'
            
            closest_date = valid_dates[-1]
            return str(self.regime_series.loc[closest_date])
        except Exception as e:
            logger.debug(f"获取市场状态失败: {e}")
            return 'sideways'
    
    def get_current_regime(self) -> str:
        """获取当前最新的市场状态"""
        return self.get_regime(None)
    
    def get_regime_stats(self) -> Dict[str, any]:
        """
        获取市场状态统计信息
        
        Returns:
            {
                'current': str,
                'distribution': {'bull': 0.3, 'bear': 0.2, 'sideways': 0.5},
                'recent_changes': List[Tuple[date, regime]],
                'days_in_current': int
            }
        """
        if self.regime_series is None or self.regime_series.empty:
            self.classify_regime()
        
        if self.regime_series is None or self.regime_series.empty:
            return {}
        
        current = str(self.regime_series.iloc[-1])
        
        # 状态分布
        value_counts = self.regime_series.value_counts()
        total = len(self.regime_series)
        distribution = {
            regime: round(count / total, 3)
            for regime, count in value_counts.items()
        }
        
        # 最近的状态变化
        regime_changes = []
        prev_regime = None
        for date, regime in self.regime_series.items():
            if regime != prev_regime:
                regime_changes.append((date.strftime('%Y-%m-%d'), regime))
                prev_regime = regime
        
        # 当前状态持续天数
        days_in_current = 1
        for i in range(len(self.regime_series) - 2, -1, -1):
            if self.regime_series.iloc[i] == current:
                days_in_current += 1
            else:
                break
        
        return {
            'current': current,
            'distribution': distribution,
            'recent_changes': regime_changes[-10:],  # 最近10次变化
            'days_in_current': days_in_current
        }
    
    def print_regime_report(self):
        """打印市场状态报告"""
        stats = self.get_regime_stats()
        if not stats:
            print("⚠️ 无法获取市场状态数据")
            return
        
        print("="*60)
        print("📊 市场状态识别报告")
        print("="*60)
        print(f"当前状态: {stats['current'].upper()}")
        print(f"持续天数: {stats['days_in_current']}天")
        print()
        
        print("历史分布:")
        for regime, pct in sorted(stats['distribution'].items(), key=lambda x: x[1], reverse=True):
            bar = "█" * int(pct * 50)
            print(f"  {regime:>10}: {pct:>6.1%} {bar}")
        print()
        
        print("最近状态变化:")
        for date, regime in stats['recent_changes']:
            print(f"  {date}: {regime}")
        print("="*60)


if __name__ == '__main__':
    # 测试代码
    engine = MarketRegimeEngine()
    engine.classify_regime()
    engine.print_regime_report()
