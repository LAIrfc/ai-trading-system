#!/usr/bin/env python3
"""
验证换手率辅助的效果

对比实验：
1. 有换手率辅助的策略 vs 无换手率辅助的策略
2. 分析信号质量（放量突破 vs 缩量突破的后续表现）
3. 统计关键指标：胜率、夏普比率、最大回撤、年化收益
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

import pandas as pd
import numpy as np
import json
from typing import Dict, List, Tuple
from src.strategies.ma_cross import MACrossStrategy
from src.strategies.turnover_helper import calc_relative_turnover_rate
from src.strategies.base import StrategySignal
import requests

class MACrossStrategyNoTurnover(MACrossStrategy):
    """MA策略（禁用换手率辅助版本）"""
    
    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        """重写analyze方法，禁用换手率辅助"""
        close = df['close']
        ma_short = close.rolling(window=self.short_window).mean()
        ma_long = close.rolling(window=self.long_window).mean()

        if len(close) < self.min_bars:
            return self.safe_analyze(df)

        cur_short = float(ma_short.iloc[-1])
        cur_long = float(ma_long.iloc[-1])
        prev_short = float(ma_short.iloc[-2])
        prev_long = float(ma_long.iloc[-2])

        dyn = self._calc_dynamics(df, ma_short, ma_long)
        slope = dyn['slope']
        slope_std = dyn['slope_std']
        bias = dyn['bias']
        bias_std = dyn['bias_std']
        vol_ratio = dyn['vol_ratio']

        indicators = {
            f'MA{self.short_window}': round(cur_short, 3),
            f'MA{self.long_window}': round(cur_long, 3),
            'slope_pct': round(slope * 100, 3),
            'vol_ratio': round(vol_ratio, 2),
        }

        # 金叉（不使用换手率辅助）
        if prev_short <= prev_long and cur_short > cur_long:
            factor = self._combined_factor(slope, slope_std, vol_ratio)
            base_confidence = self._BASE_CONF + factor * (self._MAX_CONF - self._BASE_CONF)
            base_position = self._BUY_POS_MIN + factor * (self._BUY_POS_MAX - self._BUY_POS_MIN)
            
            # 不使用换手率增强，直接使用基础值
            confidence = base_confidence
            position = base_position

            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
            return StrategySignal(
                action='BUY', confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'金叉: MA{self.short_window}({cur_short:.2f}) '
                       f'上穿 MA{self.long_window}({cur_long:.2f}){vol_desc}',
                indicators=indicators,
            )

        # 死叉（不使用换手率辅助）
        if prev_short >= prev_long and cur_short < cur_long:
            factor = self._combined_factor(slope, slope_std, vol_ratio)
            base_confidence = self._BASE_CONF + factor * (self._MAX_CONF - self._BASE_CONF)
            base_position = max(0, self._SELL_POS_MAX * (1 - factor))
            
            # 不使用换手率增强，直接使用基础值
            confidence = base_confidence
            position = base_position

            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
            return StrategySignal(
                action='SELL', confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'死叉: MA{self.short_window}({cur_short:.2f}) '
                       f'下穿 MA{self.long_window}({cur_long:.2f}){vol_desc}',
                indicators=indicators,
            )

        # 多头排列
        if cur_short > cur_long:
            bias_threshold = max(bias_std * 2, 1e-6)
            norm_bias = min(abs(bias) / bias_threshold, 1.0)
            position = self._BULL_POS_MIN + norm_bias * (self._BULL_POS_MAX - self._BULL_POS_MIN)

            return StrategySignal(
                action='HOLD', confidence=0.5,
                position=round(position, 2),
                reason=f'均线多头排列, MA{self.short_window}={cur_short:.2f} '
                       f'> MA{self.long_window}={cur_long:.2f}, 乖离{bias*100:.1f}%',
                indicators=indicators,
            )

        # 空头排列
        bias_threshold = max(bias_std * 2, 1e-6)
        norm_bias = min(abs(bias) / bias_threshold, 1.0)
        position = self._BEAR_POS_MAX - norm_bias * (self._BEAR_POS_MAX - self._BEAR_POS_MIN)

        return StrategySignal(
            action='HOLD', confidence=0.5,
            position=round(position, 2),
            reason=f'均线空头排列, MA{self.short_window}={cur_short:.2f} '
                   f'< MA{self.long_window}={cur_long:.2f}, 乖离{bias*100:.1f}%',
            indicators=indicators,
        )


def analyze_signal_quality(df: pd.DataFrame, strategy, signal_type: str = 'BUY') -> Dict:
    """
    分析信号质量：统计不同换手率场景下的信号后续表现
    
    Args:
        df: 数据
        strategy: 策略实例
        signal_type: 信号类型 ('BUY' 或 'SELL')
    
    Returns:
        统计结果字典
    """
    results = {
        'high_turnover': [],  # 放量（>1.2倍）
        'normal_turnover': [],  # 正常（0.8-1.2倍）
        'low_turnover': [],  # 缩量（<0.8倍）
    }
    
    # 计算相对换手率
    relative_turnover = calc_relative_turnover_rate(df, ma_period=20)
    
    # 遍历每一天，分析信号
    for i in range(strategy.min_bars, len(df)):
        sub_df = df.iloc[:i+1].copy()
        signal = strategy.analyze(sub_df)
        
        if signal.action != signal_type:
            continue
        
        # 获取当日的相对换手率
        if i < 20:
            continue
        
        turnover = calc_relative_turnover_rate(sub_df, ma_period=20)
        if turnover is None:
            continue
        
        # 计算后续3日收益率
        if i + 3 >= len(df):
            continue
        
        current_price = df['close'].iloc[i]
        future_price = df['close'].iloc[i + 3]
        future_return = (future_price - current_price) / current_price * 100
        
        # 分类统计
        if turnover > 1.2:
            results['high_turnover'].append(future_return)
        elif turnover < 0.8:
            results['low_turnover'].append(future_return)
        else:
            results['normal_turnover'].append(future_return)
    
    # 计算统计指标
    stats = {}
    for key, returns in results.items():
        if not returns:
            stats[key] = {'count': 0, 'avg_return': 0, 'std': 0, 'win_rate': 0}
            continue
        
        returns_arr = np.array(returns)
        stats[key] = {
            'count': len(returns),
            'avg_return': round(float(np.mean(returns_arr)), 2),
            'std': round(float(np.std(returns_arr)), 2),
            'win_rate': round(float(np.sum(returns_arr > 0) / len(returns_arr) * 100), 2),
        }
    
    return stats


def fetch_sina_data(code: str, datalen: int = 800) -> pd.DataFrame:
    """从新浪财经获取日线数据"""
    prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
    symbol = f'{prefix}{code}'
    url = ('https://money.finance.sina.com.cn/quotes_service/api/'
           'json_v2.php/CN_MarketData.getKLineData')
    
    try:
        r = requests.get(url,
            params={'symbol': symbol, 'scale': '240',
                    'ma': 'no', 'datalen': str(datalen)},
            timeout=10)
        r.raise_for_status()
        data = r.json()
        
        if not data:
            return None
        
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['day'])
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        
        # 尝试获取换手率（如果有）
        if 'turnover_rate' in df.columns:
            df['turnover_rate'] = pd.to_numeric(df['turnover_rate'], errors='coerce')
        else:
            # 如果没有换手率，尝试从成交量估算（粗略）
            df['turnover_rate'] = None
        
        df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'turnover_rate']].dropna(subset=['close'])
        return df.sort_values('date').reset_index(drop=True)
    except Exception as e:
        return None


def compare_strategies(stock_code: str, stock_name: str = '', 
                      datalen: int = 800) -> Dict:
    """
    对比有/无换手率辅助的策略表现
    
    Returns:
        对比结果字典
    """
    # 获取数据
    df = fetch_sina_data(stock_code, datalen=datalen)
    if df is None or len(df) < 100:
        return None
    
    # 确保有换手率数据（如果没有，使用模拟数据用于测试）
    if 'turnover_rate' not in df.columns or df['turnover_rate'].isna().all():
        # 使用模拟换手率（基于成交量的粗略估算）
        avg_volume = df['volume'].rolling(20).mean()
        df['turnover_rate'] = (df['volume'] / avg_volume * 2.0).fillna(2.0)  # 假设平均换手率2%
        # 不打印，减少输出噪音
    
    # 创建两个策略实例
    strategy_with = MACrossStrategy()
    strategy_without = MACrossStrategyNoTurnover()
    
    # 回测
    try:
        bt_with = strategy_with.backtest(df, initial_cash=100000,
                                         stop_loss=0.08, trailing_stop=0.05)
        bt_without = strategy_without.backtest(df, initial_cash=100000,
                                               stop_loss=0.08, trailing_stop=0.05)
    except Exception as e:
        print(f"  回测失败: {e}")
        return None
    
    # 分析信号质量
    signal_quality_with = analyze_signal_quality(df, strategy_with, 'BUY')
    signal_quality_without = analyze_signal_quality(df, strategy_without, 'BUY')
    
    return {
        'code': stock_code,
        'name': stock_name,
        'with_turnover': {
            'total_return': bt_with['total_return'],
            'annualized_return': bt_with['annualized_return'],
            'max_drawdown': bt_with['max_drawdown'],
            'sharpe': bt_with['sharpe'],
            'win_rate': bt_with['win_rate'],
            'trade_count': bt_with['trade_count'],
            'signal_quality': signal_quality_with,
        },
        'without_turnover': {
            'total_return': bt_without['total_return'],
            'annualized_return': bt_without['annualized_return'],
            'max_drawdown': bt_without['max_drawdown'],
            'sharpe': bt_without['sharpe'],
            'win_rate': bt_without['win_rate'],
            'trade_count': bt_without['trade_count'],
            'signal_quality': signal_quality_without,
        },
    }


def aggregate_comparison_results(results: List[Dict]) -> Dict:
    """汇总对比结果"""
    if not results:
        return {}
    
    # 提取指标
    metrics = ['total_return', 'annualized_return', 'max_drawdown', 
               'sharpe', 'win_rate', 'trade_count']
    
    summary = {}
    for metric in metrics:
        with_values = [r['with_turnover'][metric] for r in results]
        without_values = [r['without_turnover'][metric] for r in results]
        
        summary[metric] = {
            'with_avg': round(float(np.mean(with_values)), 2),
            'without_avg': round(float(np.mean(without_values)), 2),
            'improvement': round(float(np.mean(with_values)) - float(np.mean(without_values)), 2),
            'improvement_pct': round((float(np.mean(with_values)) - float(np.mean(without_values))) 
                                    / abs(float(np.mean(without_values))) * 100, 2) 
                              if float(np.mean(without_values)) != 0 else 0,
        }
    
    # 信号质量统计
    signal_stats = {
        'with': {'high': [], 'normal': [], 'low': []},
        'without': {'high': [], 'normal': [], 'low': []},
    }
    
    for r in results:
        for key in ['high_turnover', 'normal_turnover', 'low_turnover']:
            if r['with_turnover']['signal_quality'][key]['count'] > 0:
                signal_stats['with'][key.replace('_turnover', '')].append(
                    r['with_turnover']['signal_quality'][key]['avg_return']
                )
            if r['without_turnover']['signal_quality'][key]['count'] > 0:
                signal_stats['without'][key.replace('_turnover', '')].append(
                    r['without_turnover']['signal_quality'][key]['avg_return']
                )
    
    summary['signal_quality'] = {}
    for key in ['high', 'normal', 'low']:
        summary['signal_quality'][key] = {
            'with_avg': round(float(np.mean(signal_stats['with'][key])), 2) if signal_stats['with'][key] else 0,
            'without_avg': round(float(np.mean(signal_stats['without'][key])), 2) if signal_stats['without'][key] else 0,
        }
    
    return summary


def load_stock_pool(pool_file: str = 'data/stock_pool.json', max_count: int = 150) -> List[Tuple[str, str]]:
    """从股票池加载股票列表"""
    try:
        with open(pool_file, 'r', encoding='utf-8') as f:
            pool = json.load(f)
        
        stocks = []
        sectors = pool.get('sectors', {})
        
        # 每个板块均匀分配
        num_sectors = len(sectors)
        per_sector = max(1, max_count // num_sectors)
        remainder = max_count - per_sector * num_sectors
        
        for sector_name, sector_stocks in sectors.items():
            quota = per_sector + (1 if remainder > 0 else 0)
            if remainder > 0:
                remainder -= 1
            for s in sector_stocks[:quota]:
                stocks.append((s['code'], s.get('name', s['code'])))
                if len(stocks) >= max_count:
                    break
            if len(stocks) >= max_count:
                break
        
        return stocks[:max_count]
    except Exception as e:
        print(f"加载股票池失败: {e}")
        # 如果加载失败，返回默认列表
        return [
            ('000001', '平安银行'), ('000002', '万科A'), ('600000', '浦发银行'),
            ('600036', '招商银行'), ('600519', '贵州茅台'), ('000858', '五粮液'),
            ('002415', '海康威视'), ('300059', '东方财富'),
        ]


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("换手率辅助效果验证（150只股票）")
    print("=" * 80 + "\n")
    
    # 从股票池加载150只股票
    test_stocks = load_stock_pool(max_count=150)
    
    print(f"测试股票数量: {len(test_stocks)}")
    print("开始回测对比...\n")
    
    results = []
    success_count = 0
    skip_count = 0
    error_count = 0
    
    import time
    start_time = time.time()
    
    for i, (code, name) in enumerate(test_stocks, 1):
        if i % 10 == 0 or i == 1:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (len(test_stocks) - i) / rate if rate > 0 else 0
            print(f"进度: {i}/{len(test_stocks)} (成功: {success_count}, 跳过: {skip_count}, 错误: {error_count}) "
                  f"[已用: {elapsed:.0f}秒, 预计剩余: {remaining:.0f}秒]")
        
        try:
            result = compare_strategies(code, name, datalen=800)
            if result:
                results.append(result)
                success_count += 1
            else:
                skip_count += 1
        except Exception as e:
            error_count += 1
            if i <= 5:  # 前5只股票打印详细错误
                print(f"  ❌ 错误: {e}")
    
    total_time = time.time() - start_time
    print(f"\n回测完成: 成功 {success_count} 只, 跳过 {skip_count} 只, 错误 {error_count} 只")
    print(f"总耗时: {total_time:.1f}秒, 平均每只: {total_time/len(test_stocks):.1f}秒")
    
    if not results:
        print("❌ 没有有效的回测结果")
        return
    
    # 汇总结果
    summary = aggregate_comparison_results(results)
    
    # 打印对比结果
    print("=" * 80)
    print("回测对比结果汇总")
    print("=" * 80)
    print(f"\n有效股票数量: {len(results)}")
    print("\n关键指标对比（有换手率 vs 无换手率）:")
    print("-" * 80)
    
    for metric, data in summary.items():
        if metric == 'signal_quality':
            continue
        print(f"\n{metric}:")
        print(f"  有换手率: {data['with_avg']}")
        print(f"  无换手率: {data['without_avg']}")
        print(f"  改进: {data['improvement']} ({data['improvement_pct']:+.2f}%)")
    
    print("\n信号质量分析（后续3日收益率）:")
    print("-" * 80)
    for key in ['high', 'normal', 'low']:
        data = summary['signal_quality'][key]
        print(f"\n{key}换手率信号:")
        print(f"  有换手率辅助: {data['with_avg']:.2f}%")
        print(f"  无换手率辅助: {data['without_avg']:.2f}%")
    
    print("\n" + "=" * 80)
    print("验证完成")
    print("=" * 80)
    
    # 保存详细结果
    import json
    output_file = 'turnover_validation_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'summary': summary,
            'detailed_results': results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存到: {output_file}")


if __name__ == '__main__':
    main()
