#!/usr/bin/env python3
"""
对指定股票做全面分析：14策略 + 十倍股模型 + 翻倍股模型
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import argparse
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--codes', nargs='+', required=True)
    parser.add_argument('--names', nargs='+', required=True)
    args = parser.parse_args()

    codes = args.codes
    names = args.names
    assert len(codes) == len(names)

    print(f"\n{'='*70}")
    print(f"全面分析 {len(codes)} 只股票: 14策略 + 十倍股 + 翻倍股")
    print(f"{'='*70}\n")

    from src.data.fetchers.data_prefetch import DataPrefetch
    from src.strategies.ensemble import EnsembleStrategy

    dp = DataPrefetch()
    ensemble = EnsembleStrategy()

    stock_results = []

    for i, (code, name) in enumerate(zip(codes, names)):
        print(f"\n[{i+1}/{len(codes)}] 分析 {name}({code})...", flush=True)
        t0 = time.time()

        try:
            kline = dp.get_kline(code, days=120)
            if kline is None or kline.empty:
                print(f"  ❌ 无K线数据，跳过")
                continue

            daily_basic = dp.get_daily_basic(code)

            price = float(kline['close'].iloc[-1])
            print(f"  📊 最新价: {price:.2f}", flush=True)

            result = ensemble.analyze(code, name, kline,
                                       daily_basic=daily_basic,
                                       sector='')

            if result is None:
                print(f"  ❌ 策略分析失败")
                continue

            sr = {
                'code': code,
                'name': name,
                'price': price,
                'sector': '',
                'signals': [],
                'buy_count': 0,
                'sell_count': 0,
                'hold_count': 0,
            }

            if hasattr(result, 'strategy_signals'):
                for sname, sig in result.strategy_signals.items():
                    sr['signals'].append((sname, sig.action, sig.confidence, sig.reason))
                    if sig.action == 'BUY':
                        sr['buy_count'] += 1
                    elif sig.action == 'SELL':
                        sr['sell_count'] += 1
                    else:
                        sr['hold_count'] += 1

            if hasattr(result, 'action'):
                sr['final_action'] = result.action
            if hasattr(result, 'confidence'):
                sr['final_confidence'] = result.confidence
            if hasattr(result, 'net_score'):
                sr['net_score'] = result.net_score
            if hasattr(result, 'suggested_position'):
                sr['position'] = result.suggested_position

            if daily_basic:
                sr['market_cap'] = daily_basic.get('total_mv', daily_basic.get('market_cap'))
                sr['pe_ttm'] = daily_basic.get('pe_ttm')
                sr['pe_quantile'] = daily_basic.get('pe_quantile')
                sr['pb'] = daily_basic.get('pb')
                sr['pb_quantile'] = daily_basic.get('pb_quantile')
                sr['volume_ratio'] = daily_basic.get('volume_ratio', 1.0)

            close = kline['close']
            if len(close) >= 5:
                sr['change_5d'] = (float(close.iloc[-1]) / float(close.iloc[-5]) - 1) * 100
            if len(close) >= 20:
                sr['change_20d'] = (float(close.iloc[-1]) / float(close.iloc[-20]) - 1) * 100
            if len(close) >= 60:
                sr['change_60d'] = (float(close.iloc[-1]) / float(close.iloc[-60]) - 1) * 100

            hi = float(close.max())
            lo = float(close.min())
            sr['dist_high'] = (price / hi - 1) * 100 if hi > 0 else 0
            sr['dist_low'] = (price / lo - 1) * 100 if lo > 0 else 0

            from src.strategies.ensemble import _trend_label
            if len(kline) >= 20:
                ma5 = float(close.rolling(5).mean().iloc[-1])
                ma10 = float(close.rolling(10).mean().iloc[-1])
                ma20 = float(close.rolling(20).mean().iloc[-1])
                sr['trend'] = _trend_label(ma5, ma10, ma20, price)
            else:
                sr['trend'] = ''

            sr['earnings_growth'] = None
            sr['fundamental_score'] = 0.0

            stock_results.append(sr)

            print(f"\n  === {name}({code}) 14策略详情 ===")
            print(f"  最新价: {price:.2f} | 5日: {sr.get('change_5d',0):.1f}% | 20日: {sr.get('change_20d',0):.1f}%")
            print(f"  市值: {sr.get('market_cap','N/A')} | PE: {sr.get('pe_ttm','N/A')} | PB: {sr.get('pb','N/A')}")
            print(f"  趋势: {sr.get('trend','N/A')}")
            print(f"  综合: {sr.get('final_action','N/A')} conf={sr.get('final_confidence','N/A')} net_score={sr.get('net_score','N/A')}")
            print(f"  BUY:{sr['buy_count']} SELL:{sr['sell_count']} HOLD:{sr['hold_count']}")
            print()

            for sname, sig in result.strategy_signals.items():
                icon = '🟢' if sig.action == 'BUY' else ('🔴' if sig.action == 'SELL' else '⚪')
                print(f"    {icon} {sname:18s} {sig.action:5s} conf={sig.confidence:.2f}  {sig.reason[:80]}")

            elapsed = time.time() - t0
            print(f"\n  ⏱ 耗时: {elapsed:.1f}s", flush=True)

        except Exception as e:
            import traceback
            print(f"  ❌ 异常: {e}")
            traceback.print_exc()

    print(f"\n\n{'='*70}")
    print("十倍股模型评估")
    print(f"{'='*70}\n")

    try:
        from src.strategies.tenbagger_model import batch_evaluate_tenbagger
        tb_results = batch_evaluate_tenbagger(stock_results, top_n=len(stock_results))
        for i, tr in enumerate(tb_results, 1):
            print(f"  [{i}] {tr.name}({tr.code})")
            print(f"      总分: {tr.tenbagger_score:.0f}/700 评级: {tr.tenbagger_grade}")
            print(f"      赛道:{tr.score_track:.0f} 市值:{tr.score_mcap:.0f} 壁垒:{tr.score_moat:.0f} "
                  f"拐点:{tr.score_earning:.0f} 替代:{tr.score_replace:.0f} 催化:{tr.score_catalyst:.0f} "
                  f"估值:{tr.score_value:.0f}")
            if tr.matched_tracks:
                print(f"      赛道匹配: {', '.join(tr.matched_tracks[:3])}")
            if tr.risk_flags:
                print(f"      风险: {', '.join(tr.risk_flags)}")
            print()
    except Exception as e:
        print(f"  ❌ 十倍股模型异常: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'='*70}")
    print("翻倍股模型评估")
    print(f"{'='*70}\n")

    try:
        from src.strategies.doubler_model import batch_evaluate_doubler
        db_results = batch_evaluate_doubler(stock_results, top_n=len(stock_results))
        for i, dr in enumerate(db_results, 1):
            print(f"  [{i}] {dr.name}({dr.code})")
            print(f"      总分: {dr.doubler_score:.0f}/100 评级: {dr.doubler_grade}")
            print(f"      行业热度:{dr.sector_heat:.0%} 资金强度:{dr.capital_intensity:.0%} "
                  f"催化密度:{dr.catalyst_density:.0%} 预期差:{dr.expectation_diff:.0%} "
                  f"筹码:{dr.chip_concentration:.0%}")
            if hasattr(dr, 'hot_sector') and dr.hot_sector:
                print(f"      赛道: {dr.hot_sector}")
            if hasattr(dr, 'catalyst_desc') and dr.catalyst_desc:
                print(f"      催化: {dr.catalyst_desc}")
            print()
    except Exception as e:
        print(f"  ❌ 翻倍股模型异常: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'='*70}")
    print("分析完成!")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()
