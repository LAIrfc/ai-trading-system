#!/usr/bin/env python3
"""
双核动量轮动策略 - 完整回测脚本

用法:
    python backtest_dual_momentum.py

功能:
    1. 自动下载ETF数据
    2. 运行双核动量策略回测
    3. 输出完整的回测报告
    4. 绘制净值曲线和分析图表
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from loguru import logger
from typing import Dict, List

from src.data.etf_data_fetcher import ETFDataFetcher
from src.core.strategy.dual_momentum_strategy import DualMomentumStrategy


# 设置中文字体（避免图表乱码）
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


class DualMomentumBacktest:
    """双核动量策略回测引擎"""
    
    def __init__(self, initial_capital: float = 1000000, commission: float = 0.0002):
        """
        初始化回测引擎
        
        Args:
            initial_capital: 初始资金（元）
            commission: 手续费率（双边）
        """
        self.initial_capital = initial_capital
        self.commission = commission
        
        # 回测状态
        self.cash = initial_capital
        self.holdings = {}  # {code: shares}
        self.portfolio_values = []  # 每日净值
        self.trades = []  # 交易记录
        self.daily_returns = []  # 每日收益率
        
        logger.info(f"回测引擎初始化 | 初始资金={initial_capital:,.0f}元, 手续费={commission*10000:.1f}‱")
    
    def execute_trade(self, code: str, signal: int, price: float, shares: int, date: datetime):
        """
        执行交易
        
        Args:
            code: 资产代码
            signal: 信号 (1=买入, -1=卖出)
            price: 价格
            shares: 股数
            date: 日期
        """
        if signal == 1:  # 买入
            cost = price * shares * (1 + self.commission)
            if cost > self.cash:
                logger.warning(f"资金不足: 需要{cost:.2f}, 可用{self.cash:.2f}")
                return
            
            self.cash -= cost
            self.holdings[code] = self.holdings.get(code, 0) + shares
            
            self.trades.append({
                'date': date,
                'code': code,
                'action': '买入',
                'price': price,
                'shares': shares,
                'amount': cost,
                'commission': price * shares * self.commission
            })
            
            logger.info(f"买入 | {date.strftime('%Y-%m-%d')} | {code} | "
                       f"{shares}股 @ {price:.2f} = {cost:,.2f}元")
        
        elif signal == -1:  # 卖出
            if code not in self.holdings or self.holdings[code] == 0:
                logger.warning(f"没有持仓: {code}")
                return
            
            actual_shares = min(shares, self.holdings[code]) if shares > 0 else self.holdings[code]
            revenue = price * actual_shares * (1 - self.commission)
            
            self.cash += revenue
            self.holdings[code] -= actual_shares
            if self.holdings[code] == 0:
                del self.holdings[code]
            
            self.trades.append({
                'date': date,
                'code': code,
                'action': '卖出',
                'price': price,
                'shares': actual_shares,
                'amount': revenue,
                'commission': price * actual_shares * self.commission
            })
            
            logger.info(f"卖出 | {date.strftime('%Y-%m-%d')} | {code} | "
                       f"{actual_shares}股 @ {price:.2f} = {revenue:,.2f}元")
    
    def calculate_portfolio_value(self, data: pd.DataFrame, date_idx: int) -> float:
        """计算当前组合总价值"""
        stock_value = 0
        
        for code, shares in self.holdings.items():
            if code in data.columns.get_level_values(0):
                price = data[code]['close'].iloc[date_idx]
                stock_value += price * shares
        
        total_value = self.cash + stock_value
        return total_value
    
    def run(self, strategy: DualMomentumStrategy, data: pd.DataFrame) -> Dict:
        """
        运行回测
        
        Args:
            strategy: 策略实例
            data: 市场数据
            
        Returns:
            回测结果字典
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"开始回测")
        logger.info(f"{'='*80}")
        logger.info(f"数据周期: {data.index[0].strftime('%Y-%m-%d')} -> {data.index[-1].strftime('%Y-%m-%d')}")
        logger.info(f"交易日数: {len(data)}")
        
        # 确保数据足够
        min_data_points = max(strategy.absolute_period, strategy.relative_period) + 10
        if len(data) < min_data_points:
            logger.error(f"数据不足: 需要至少 {min_data_points} 个交易日")
            return {}
        
        # 从第 min_data_points 天开始回测
        start_idx = min_data_points
        
        for i in range(start_idx, len(data)):
            current_date = data.index[i]
            
            # 使用截至当前的所有历史数据
            historical_data = data.iloc[:i+1]
            
            # 生成信号
            signals = strategy.generate_signals(historical_data)
            
            if signals.empty:
                # 无信号，记录净值
                portfolio_value = self.calculate_portfolio_value(data, i)
                self.portfolio_values.append({
                    'date': current_date,
                    'value': portfolio_value,
                    'cash': self.cash
                })
                continue
            
            # 执行交易
            for _, signal_row in signals.iterrows():
                code = signal_row['code']
                signal = signal_row['signal']
                
                if code not in data.columns.get_level_values(0):
                    continue
                
                current_price = data[code]['close'].iloc[i]
                
                if signal == 1:  # 买入
                    shares = strategy.calculate_position_size(
                        signal=1,
                        current_price=current_price,
                        account_value=self.cash + sum([
                            data[c]['close'].iloc[i] * s 
                            for c, s in self.holdings.items() 
                            if c in data.columns.get_level_values(0)
                        ])
                    )
                    if shares > 0:
                        self.execute_trade(code, 1, current_price, shares, current_date)
                        strategy.update_holdings(code, 1, current_price, shares)
                
                elif signal == -1:  # 卖出
                    shares = self.holdings.get(code, 0)
                    if shares > 0:
                        self.execute_trade(code, -1, current_price, shares, current_date)
                        strategy.update_holdings(code, -1, current_price, shares)
            
            # 记录每日净值
            portfolio_value = self.calculate_portfolio_value(data, i)
            self.portfolio_values.append({
                'date': current_date,
                'value': portfolio_value,
                'cash': self.cash
            })
            
            # 计算日收益率
            if len(self.portfolio_values) > 1:
                prev_value = self.portfolio_values[-2]['value']
                daily_return = (portfolio_value / prev_value) - 1
                self.daily_returns.append(daily_return)
        
        # 生成回测报告
        report = self.generate_report()
        
        logger.info(f"\n{'='*80}")
        logger.info("回测完成")
        logger.info(f"{'='*80}")
        
        return report
    
    def generate_report(self) -> Dict:
        """生成回测报告"""
        if len(self.portfolio_values) == 0:
            return {}
        
        # 转换为 DataFrame
        portfolio_df = pd.DataFrame(self.portfolio_values)
        portfolio_df = portfolio_df.set_index('date')
        
        # 计算指标
        final_value = portfolio_df['value'].iloc[-1]
        total_return = (final_value / self.initial_capital) - 1
        
        # 年化收益率
        days = (portfolio_df.index[-1] - portfolio_df.index[0]).days
        years = days / 365
        annual_return = (1 + total_return) ** (1 / years) - 1
        
        # 最大回撤
        cumulative_max = portfolio_df['value'].cummax()
        drawdown = (portfolio_df['value'] - cumulative_max) / cumulative_max
        max_drawdown = drawdown.min()
        
        # 夏普比率 (假设无风险利率=3%)
        risk_free_rate = 0.03
        if len(self.daily_returns) > 0:
            daily_returns = np.array(self.daily_returns)
            excess_returns = daily_returns - (risk_free_rate / 252)
            sharpe_ratio = np.sqrt(252) * excess_returns.mean() / (excess_returns.std() + 1e-8)
        else:
            sharpe_ratio = 0
        
        # 卡玛比率
        calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0
        
        # 胜率
        if len(self.daily_returns) > 0:
            win_rate = len([r for r in self.daily_returns if r > 0]) / len(self.daily_returns)
        else:
            win_rate = 0
        
        # 交易统计
        num_trades = len(self.trades)
        total_commission = sum([t['commission'] for t in self.trades])
        
        report = {
            'initial_capital': self.initial_capital,
            'final_value': final_value,
            'total_return': total_return,
            'annual_return': annual_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'calmar_ratio': calmar_ratio,
            'win_rate': win_rate,
            'num_trades': num_trades,
            'total_commission': total_commission,
            'portfolio_df': portfolio_df,
            'trades_df': pd.DataFrame(self.trades),
        }
        
        # 打印报告
        print(f"\n{'='*60}")
        print("回测报告")
        print(f"{'='*60}")
        print(f"初始资金:       {self.initial_capital:>15,.2f} 元")
        print(f"最终资产:       {final_value:>15,.2f} 元")
        print(f"总收益率:       {total_return:>15.2%}")
        print(f"年化收益率:     {annual_return:>15.2%}")
        print(f"最大回撤:       {max_drawdown:>15.2%}")
        print(f"夏普比率:       {sharpe_ratio:>15.2f}")
        print(f"卡玛比率:       {calmar_ratio:>15.2f}")
        print(f"日胜率:         {win_rate:>15.2%}")
        print(f"交易次数:       {num_trades:>15} 次")
        print(f"手续费总计:     {total_commission:>15,.2f} 元")
        print(f"{'='*60}\n")
        
        return report
    
    def plot_results(self, report: Dict, save_path: str = None):
        """绘制回测结果"""
        if 'portfolio_df' not in report:
            logger.error("无回测数据可绘制")
            return
        
        portfolio_df = report['portfolio_df']
        
        fig, axes = plt.subplots(3, 1, figsize=(14, 10))
        
        # 1. 净值曲线
        axes[0].plot(portfolio_df.index, portfolio_df['value'], linewidth=2, label='策略净值')
        axes[0].axhline(self.initial_capital, color='gray', linestyle='--', label='初始资金')
        axes[0].set_title('投资组合净值曲线', fontsize=14, fontweight='bold')
        axes[0].set_ylabel('净值（元）', fontsize=12)
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        
        # 2. 收益率曲线
        returns = (portfolio_df['value'] / self.initial_capital - 1) * 100
        axes[1].plot(portfolio_df.index, returns, linewidth=2, color='green', label='累计收益率')
        axes[1].axhline(0, color='gray', linestyle='--')
        axes[1].set_title('累计收益率', fontsize=14, fontweight='bold')
        axes[1].set_ylabel('收益率 (%)', fontsize=12)
        axes[1].legend()
        axes[1].grid(True, alpha=0.3)
        
        # 3. 回撤曲线
        cumulative_max = portfolio_df['value'].cummax()
        drawdown = (portfolio_df['value'] - cumulative_max) / cumulative_max * 100
        axes[2].fill_between(portfolio_df.index, drawdown, 0, color='red', alpha=0.3, label='回撤')
        axes[2].set_title('回撤曲线', fontsize=14, fontweight='bold')
        axes[2].set_ylabel('回撤 (%)', fontsize=12)
        axes[2].set_xlabel('日期', fontsize=12)
        axes[2].legend()
        axes[2].grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            logger.info(f"图表已保存: {save_path}")
        
        plt.show()


def main():
    """主函数"""
    # 配置日志（回测时减少输出，只显示 WARNING 以上）
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="WARNING"
    )
    logger.add("logs/dual_momentum_backtest.log", rotation="10 MB", level="DEBUG")
    
    print("="*80)
    print("双核动量轮动策略 - 回测系统")
    print("="*80)
    
    # 1. 获取数据
    logger.info("步骤 1/4: 下载ETF数据...")
    
    etf_codes = ['510300', '159949', '513100', '518880', '511520']
    start_date = '20200101'
    end_date = datetime.now().strftime('%Y%m%d')
    
    fetcher = ETFDataFetcher()
    data = fetcher.get_etf_pool_data(etf_codes, start_date, end_date)
    
    if data.empty:
        logger.error("数据获取失败，退出")
        return
    
    # 填充缺失值
    data = fetcher.fill_missing_data(data)
    
    # 验证数据
    if not fetcher.validate_data(data, min_length=250):
        logger.error("数据验证失败，退出")
        return
    
    logger.info(f"数据准备完成: {data.shape[0]} 个交易日, {len(etf_codes)} 个ETF")
    
    # 2. 初始化策略
    logger.info("\n步骤 2/4: 初始化双核动量策略...")
    
    strategy_config = {
        'absolute_period': 200,      # N=200日均线
        'relative_period': 60,        # M=60日动量
        'rebalance_days': 20,         # F=20日（月度）调仓
        'top_k': 1,                   # K=1 持有最强的1个
        'etf_pool': etf_codes,
        'stop_loss': -0.10,           # -10%止损
        'market_crash_threshold': -0.05,  # -5%熔断
        'min_volume': 5000,           # 5000万流动性
        'max_position': 0.30,         # 30%最大仓位
    }
    
    strategy = DualMomentumStrategy(strategy_config)
    
    # 3. 运行回测
    logger.info("\n步骤 3/4: 运行回测...")
    
    backtest = DualMomentumBacktest(
        initial_capital=1000000,  # 100万
        commission=0.0002         # 万分之2
    )
    
    report = backtest.run(strategy, data)
    
    if not report:
        logger.error("回测失败")
        return
    
    # 4. 绘制结果
    logger.info("\n步骤 4/4: 生成可视化...")
    
    backtest.plot_results(report, save_path='dual_momentum_backtest_result.png')
    
    # 保存交易记录
    if 'trades_df' in report and not report['trades_df'].empty:
        report['trades_df'].to_csv('dual_momentum_trades.csv', index=False, encoding='utf-8-sig')
        logger.info("交易记录已保存: dual_momentum_trades.csv")
    
    logger.info("\n✅ 回测完成！")


if __name__ == '__main__':
    main()
