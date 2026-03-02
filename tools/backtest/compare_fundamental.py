t #!/usr/bin/env python3
"""
对比回测：纯技术面 vs 技术面+基本面

验证PE/PB/ROE基本面优化是否真的有效。

设计：
- A组（纯技术面）：MACD信号直接交易
- B组（技术+基本面）：MACD信号 + PE/PB估值过滤 + ROE质量过滤
  规则：
  1. MACD发出BUY且PE分位<50% → 买入（低估+技术共振）
  2. MACD发出BUY但PE分位>80% → 不买（技术买但估值太贵）
  3. MACD发出SELL或PE分位>80% → 卖出
  4. ROE连续3年<8%的股票 → 直接排除（价值陷阱）

指标对比：
- 总收益率、年化收益率、最大回撤、胜率、夏普比率
"""

import sys
import os
import time
import json
import warnings
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
warnings.filterwarnings('ignore')

from src.strategies.macd_cross import MACDStrategy
from src.strategies.fundamental_pe import PEStrategy
from src.strategies.fundamental_pb import PBStrategy
from src.strategies.base import StrategySignal
from src.data.fetchers.fundamental_fetcher import FundamentalFetcher


# ============================================================
# 数据获取
# ============================================================

def fetch_data_bs(code: str, datalen: int = 800) -> pd.DataFrame:
    """用baostock获取日K线+PE/PB"""
    import baostock as bs
    
    prefix = 'sh' if code.startswith(('5', '6', '9')) else 'sz'
    bs_code = f'{prefix}.{code}'
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=int(datalen * 1.6))).strftime('%Y-%m-%d')
    
    # 获取行情+PE/PB
    rs = bs.query_history_k_data_plus(
        bs_code,
        'date,open,high,low,close,volume,amount,peTTM,pbMRQ,turn',
        start_date=start_date,
        end_date=end_date,
        frequency='d',
        adjustflag='2',  # 前复权
    )
    
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    
    if not rows:
        return pd.DataFrame()
    
    df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 
                                      'volume', 'amount', 'pe_ttm', 'pb', 'turnover_rate'])
    df['date'] = pd.to_datetime(df['date'])
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pe_ttm', 'pb', 'turnover_rate']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df.dropna(subset=['close'], inplace=True)
    return df


# ============================================================
# 增强MACD策略（带基本面过滤）
# ============================================================

class EnhancedMACDStrategy(MACDStrategy):
    """MACD + PE/PB基本面增强策略"""
    
    name = 'MACD+基本面'
    
    def __init__(self, roe_passes: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.pe_strat = PEStrategy()
        self.pb_strat = PBStrategy()
        self.roe_passes = roe_passes  # 是否通过ROE过滤
        self.min_bars = 60  # PE/PB需要数据
    
    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        """MACD信号 + 基本面过滤"""
        
        # 1. 先获取MACD技术信号
        macd_sig = super().analyze(df)
        
        # 2. 获取PE信号
        pe_sig = None
        if 'pe_ttm' in df.columns and df['pe_ttm'].notna().sum() > 60:
            try:
                pe_sig = self.pe_strat.safe_analyze(df)
            except Exception:
                pass
        
        # 3. 获取PB信号
        pb_sig = None
        if 'pb' in df.columns and df['pb'].notna().sum() > 60:
            try:
                pb_sig = self.pb_strat.safe_analyze(df)
            except Exception:
                pass
        
        # 4. ROE过滤（不通过直接降低置信度）
        roe_penalty = 0.0
        if not self.roe_passes:
            roe_penalty = 0.15
        
        # ---- 综合决策 ----
        pe_quantile = None
        if pe_sig and pe_sig.indicators:
            pe_quantile = pe_sig.indicators.get('pe_quantile')
        
        pb_quantile = None
        if pb_sig and pb_sig.indicators:
            pb_quantile = pb_sig.indicators.get('pb_quantile')
        
        # 增强逻辑
        if macd_sig.action == 'BUY':
            # MACD买入 + 基本面确认
            bonus = 0.0
            penalty = 0.0
            reason_parts = [macd_sig.reason]
            
            # PE确认
            if pe_quantile is not None:
                if pe_quantile < 0.3:
                    bonus += 0.10  # PE低估加分
                    reason_parts.append(f'PE低估({pe_quantile:.0%})')
                elif pe_quantile > 0.8:
                    penalty += 0.20  # PE高估减分
                    reason_parts.append(f'PE高估({pe_quantile:.0%})⚠️')
            
            # PB确认
            if pb_quantile is not None:
                if pb_quantile < 0.3:
                    bonus += 0.05
                elif pb_quantile > 0.8:
                    penalty += 0.10
            
            # ROE惩罚
            if roe_penalty > 0:
                penalty += roe_penalty
                reason_parts.append('ROE不达标⚠️')
            
            # 如果惩罚太大，降级为HOLD
            if penalty > 0.25:
                return StrategySignal(
                    action='HOLD',
                    confidence=max(0.1, macd_sig.confidence - penalty),
                    position=0.3,
                    reason=f'技术买入但基本面不佳({"; ".join(reason_parts)})',
                    indicators=macd_sig.indicators,
                )
            
            new_conf = min(0.95, max(0.1, macd_sig.confidence + bonus - penalty))
            new_pos = min(0.95, max(0.3, macd_sig.position + bonus - penalty))
            
            return StrategySignal(
                action='BUY',
                confidence=round(new_conf, 2),
                position=round(new_pos, 2),
                reason='; '.join(reason_parts),
                indicators=macd_sig.indicators,
            )
        
        elif macd_sig.action == 'SELL':
            # 卖出信号不需要基本面确认（止损优先）
            # 但如果PE极度高估，增强卖出信号
            bonus = 0.0
            if pe_quantile is not None and pe_quantile > 0.8:
                bonus += 0.1
            
            return StrategySignal(
                action='SELL',
                confidence=min(0.95, macd_sig.confidence + bonus),
                position=max(0.0, macd_sig.position),
                reason=macd_sig.reason,
                indicators=macd_sig.indicators,
            )
        
        else:
            # HOLD信号：如果PE极度低估，提升仓位
            if pe_quantile is not None and pe_quantile < 0.2:
                return StrategySignal(
                    action='HOLD',
                    confidence=0.5,
                    position=min(0.7, macd_sig.position + 0.1),
                    reason=f'{macd_sig.reason}; PE极度低估({pe_quantile:.0%})',
                    indicators=macd_sig.indicators,
                )
            return macd_sig


# ============================================================
# 回测对比
# ============================================================

def run_comparison(stocks: list, datalen: int = 800):
    """运行对比回测"""
    import baostock as bs
    bs.login()
    
    fetcher = FundamentalFetcher()
    
    pure_macd = MACDStrategy(fast_period=12, slow_period=30, signal_period=9)
    
    results_a = []  # 纯技术
    results_b = []  # 技术+基本面
    
    skipped_by_roe = 0
    enhanced_by_pe = 0
    total = len(stocks)
    
    print(f"\n{'='*90}")
    print(f"对比回测：纯MACD vs MACD+基本面 | {total}只股票 | {datalen}条K线(约{datalen/240:.1f}年)")
    print(f"{'='*90}")
    print(f"{'序号':>4} {'代码':>8} {'名称':>8} {'纯MACD收益':>12} {'增强收益':>12} {'差值':>8} {'PE分位':>8} {'ROE':>10}")
    print(f"{'-'*90}")
    
    for i, stock in enumerate(stocks, 1):
        code = stock['code']
        name = stock['name']
        
        try:
            # 获取数据（含PE/PB）
            df = fetch_data_bs(code, datalen)
            if df.empty or len(df) < 100:
                continue
            
            # A组：纯MACD回测
            bt_a = pure_macd.backtest(df, initial_cash=100000, 
                                       stop_loss=0.08, trailing_stop=0.05)
            
            # ROE检查
            roe_passes, roe_val, roe_reason = fetcher.get_roe_for_filter(code)
            
            # B组：MACD+基本面回测
            enhanced = EnhancedMACDStrategy(
                roe_passes=roe_passes,
                fast_period=12, slow_period=30, signal_period=9
            )
            bt_b = enhanced.backtest(df, initial_cash=100000,
                                      stop_loss=0.08, trailing_stop=0.05)
            
            ret_a = bt_a['total_return']
            ret_b = bt_b['total_return']
            diff = ret_b - ret_a
            
            # PE分位信息
            pe_q_str = '-'
            if 'pe_ttm' in df.columns:
                pe_valid = df['pe_ttm'].dropna()
                pe_valid = pe_valid[(pe_valid > 0) & (pe_valid <= 100)]
                if len(pe_valid) > 60:
                    pe_q = (pe_valid < pe_valid.iloc[-1]).sum() / len(pe_valid)
                    pe_q_str = f'{pe_q:.0%}'
            
            roe_str = f'{roe_val:.1f}%' if roe_val else '-'
            if not roe_passes:
                roe_str += '❌'
                skipped_by_roe += 1
            
            if abs(diff) > 1:
                enhanced_by_pe += 1
            
            results_a.append({
                'code': code, 'name': name,
                'total_return': ret_a,
                'max_drawdown': bt_a['max_drawdown'],
                'win_rate': bt_a['win_rate'],
                'trade_count': bt_a['trade_count'],
                'sharpe': bt_a['sharpe'],
            })
            
            results_b.append({
                'code': code, 'name': name,
                'total_return': ret_b,
                'max_drawdown': bt_b['max_drawdown'],
                'win_rate': bt_b['win_rate'],
                'trade_count': bt_b['trade_count'],
                'sharpe': bt_b['sharpe'],
            })
            
            # 打印进度
            diff_str = f'{diff:+.1f}%'
            if diff > 2:
                diff_str = f'🟢{diff:+.1f}%'
            elif diff < -2:
                diff_str = f'🔴{diff:+.1f}%'
            
            print(f"{i:>4} {code:>8} {name:>8} {ret_a:>+10.1f}% {ret_b:>+10.1f}% "
                  f"{diff_str:>8} {pe_q_str:>8} {roe_str:>10}")
            
        except Exception as e:
            print(f"{i:>4} {code:>8} {name:>8} ❌ {str(e)[:40]}")
        
        # 每20只暂停
        if i % 20 == 0:
            time.sleep(0.5)
    
    bs.logout()
    fetcher._bs_logout()
    
    return results_a, results_b, skipped_by_roe, enhanced_by_pe


def print_summary(results_a, results_b, skipped_by_roe, enhanced_by_pe):
    """打印汇总对比"""
    if not results_a or not results_b:
        print("❌ 无有效结果")
        return
    
    df_a = pd.DataFrame(results_a)
    df_b = pd.DataFrame(results_b)
    
    print(f"\n{'='*90}")
    print(f"{'📊 回测结果汇总':^90}")
    print(f"{'='*90}")
    
    metrics = [
        ('有效股票数', len(df_a), len(df_b)),
        ('', '', ''),
        ('平均收益率', f"{df_a['total_return'].mean():.2f}%", f"{df_b['total_return'].mean():.2f}%"),
        ('收益率中位数', f"{df_a['total_return'].median():.2f}%", f"{df_b['total_return'].median():.2f}%"),
        ('收益率标准差', f"{df_a['total_return'].std():.2f}%", f"{df_b['total_return'].std():.2f}%"),
        ('', '', ''),
        ('盈利股票占比', f"{(df_a['total_return'] > 0).mean():.1%}", f"{(df_b['total_return'] > 0).mean():.1%}"),
        ('亏损>10%占比', f"{(df_a['total_return'] < -10).mean():.1%}", f"{(df_b['total_return'] < -10).mean():.1%}"),
        ('盈利>20%占比', f"{(df_a['total_return'] > 20).mean():.1%}", f"{(df_b['total_return'] > 20).mean():.1%}"),
        ('', '', ''),
        ('平均最大回撤', f"{df_a['max_drawdown'].mean():.2f}%", f"{df_b['max_drawdown'].mean():.2f}%"),
        ('平均胜率', f"{df_a['win_rate'].mean():.1f}%", f"{df_b['win_rate'].mean():.1f}%"),
        ('平均交易次数', f"{df_a['trade_count'].mean():.1f}", f"{df_b['trade_count'].mean():.1f}"),
        ('平均夏普比率', f"{df_a['sharpe'].mean():.3f}", f"{df_b['sharpe'].mean():.3f}"),
    ]
    
    print(f"{'指标':>20} {'纯MACD(A)':>18} {'MACD+基本面(B)':>18} {'差异':>15}")
    print(f"{'-'*75}")
    
    for name, val_a, val_b in metrics:
        if name == '':
            print()
            continue
        
        # 计算差异
        diff = ''
        try:
            if isinstance(val_a, str) and '%' in val_a and isinstance(val_b, str) and '%' in val_b:
                a_num = float(val_a.replace('%', ''))
                b_num = float(val_b.replace('%', ''))
                d = b_num - a_num
                if '回撤' in name or '亏损' in name:
                    # 回撤和亏损越小越好
                    diff = f'{"🟢" if d < 0 else "🔴"}{d:+.2f}%'
                else:
                    diff = f'{"🟢" if d > 0 else "🔴"}{d:+.2f}%'
            elif isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                diff = f'{val_b - val_a:+.1f}'
        except:
            pass
        
        print(f"{name:>20} {str(val_a):>18} {str(val_b):>18} {diff:>15}")
    
    print(f"\n{'─'*75}")
    print(f"  ROE不达标被降权: {skipped_by_roe} 只")
    print(f"  PE/PB影响交易: {enhanced_by_pe} 只（收益差>1%）")
    
    # 胜出统计
    paired = pd.merge(df_a[['code','total_return']], df_b[['code','total_return']], 
                       on='code', suffixes=('_a', '_b'))
    b_wins = (paired['total_return_b'] > paired['total_return_a']).sum()
    a_wins = (paired['total_return_a'] > paired['total_return_b']).sum()
    ties = (paired['total_return_a'] == paired['total_return_b']).sum()
    
    print(f"\n  逐只对比: 增强胜出 {b_wins} 只 | 纯技术胜出 {a_wins} 只 | 持平 {ties} 只")
    
    avg_diff = paired['total_return_b'].mean() - paired['total_return_a'].mean()
    print(f"  平均收益提升: {avg_diff:+.2f}%")
    
    if avg_diff > 0:
        print(f"\n  ✅ 结论：基本面优化有效，平均每只股票多赚 {avg_diff:.2f}%")
    elif avg_diff < -0.5:
        print(f"\n  ⚠️ 结论：基本面过滤在此样本中偏保守，平均少赚 {abs(avg_diff):.2f}%")
        print(f"     但回撤和风控可能更优，需要看最大回撤和亏损比例")
    else:
        print(f"\n  📊 结论：差异不大（{avg_diff:+.2f}%），基本面主要起风控作用")


def main():
    # 加载股票池
    pool_file = os.path.join(os.path.dirname(__file__), '../../data/stock_pool_600.json')
    with open(pool_file, 'r') as f:
        pool = json.load(f)
    
    all_stocks = []
    sectors = pool.get('stocks', pool.get('sectors', {}))
    for sector_name, sector_stocks in sectors.items():
        for s in sector_stocks:
            all_stocks.append({
                'code': s['code'],
                'name': s.get('name', s['code']),
                'sector': sector_name,
            })
    
    # 从每个行业取一些，共约100只
    import random
    random.seed(42)
    
    # 按行业分组，每个行业最多取5只
    from collections import defaultdict
    by_sector = defaultdict(list)
    for s in all_stocks:
        by_sector[s['sector']].append(s)
    
    selected = []
    for sector, stocks in by_sector.items():
        random.shuffle(stocks)
        selected.extend(stocks[:5])
    
    # 最多100只
    if len(selected) > 100:
        random.shuffle(selected)
        selected = selected[:100]
    
    print(f"从 {len(all_stocks)} 只股票中选取 {len(selected)} 只进行对比回测")
    print(f"覆盖 {len(by_sector)} 个行业")
    
    start_time = time.time()
    
    results_a, results_b, skipped_by_roe, enhanced_by_pe = run_comparison(
        selected, datalen=800
    )
    
    elapsed = time.time() - start_time
    
    print_summary(results_a, results_b, skipped_by_roe, enhanced_by_pe)
    
    print(f"\n⏱️  总耗时: {elapsed:.0f}秒")
    print(f"✅ 对比回测完成!")


if __name__ == '__main__':
    main()
