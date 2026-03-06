"""
操盘日志系统
每次运行策略分析后，生成一份完整的 Markdown 格式日志
记录: 市场状态、策略分析过程、决策理由、持仓变化
"""

import os
import json
from datetime import datetime
from typing import Dict
from loguru import logger

from src.core.signal_engine import Signal
from src.core.portfolio import Portfolio
from src.data.market_data import ETF_POOL


DAILY_LOG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'daily_reports')


def generate_daily_report(signal: Signal, analysis: dict,
                          portfolio: Portfolio,
                          current_prices: Dict[str, dict] = None) -> str:
    """
    生成每日操盘日志（Markdown 格式）

    Returns:
        日志文件路径
    """
    os.makedirs(DAILY_LOG_DIR, exist_ok=True)

    date_str = signal.date or datetime.now().strftime('%Y-%m-%d')
    filename = f"report_{date_str}.md"
    filepath = os.path.join(DAILY_LOG_DIR, filename)

    lines = []

    # 标题
    lines.append(f"# 📋 操盘日志 {date_str}")
    lines.append(f"")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 策略: 双核动量轮动策略 v1.0")
    lines.append(f"")

    # ===== 市场快照 =====
    lines.append(f"## 一、市场快照")
    lines.append(f"")
    lines.append(f"| ETF | 代码 | 收盘价 | 日成交额(亿) |")
    lines.append(f"|-----|------|--------|-------------|")
    if current_prices:
        for code, info in current_prices.items():
            lines.append(
                f"| {info.get('short', code)} | {code} | "
                f"{info.get('close', 0):.4f} | {info.get('amount', 0)/1e8:.2f} |"
            )
    lines.append(f"")

    # ===== 绝对动量分析 =====
    lines.append(f"## 二、绝对动量分析（趋势过滤）")
    lines.append(f"")
    abs_data = analysis.get('absolute_momentum', {})
    if abs_data:
        N = 200  # TODO: 从分析中获取
        lines.append(f"判断标准: **当前价格 > {N}日均线** → 上升趋势 ✅")
        lines.append(f"")
        lines.append(f"| ETF | 当前价 | MA{N} | 价格/均线 | 判定 |")
        lines.append(f"|-----|--------|-------|----------|------|")
        for code, info in abs_data.items():
            if isinstance(info, dict) and 'price' in info:
                status = '✅ 通过' if info.get('above_ma') else '❌ 不通过'
                lines.append(
                    f"| {info.get('name', code)} | {info['price']:.4f} | "
                    f"{info['ma']:.4f} | {info.get('ratio', 0):.4f} | {status} |"
                )
            elif isinstance(info, dict) and 'status' in info:
                lines.append(
                    f"| {code} | - | - | - | ⚠️ {info['status']} "
                    f"({info.get('data_count', 0)}/{info.get('required', 0)}) |"
                )
        lines.append(f"")

    qualified = analysis.get('qualified_pool', [])
    lines.append(f"**备选池:** {len(qualified)} 个资产通过绝对动量测试")
    lines.append(f"")

    # ===== 相对动量排名 =====
    lines.append(f"## 三、相对动量排名（强弱选择）")
    lines.append(f"")
    ranking = analysis.get('ranking', [])
    if ranking:
        lines.append(f"| 排名 | ETF | 过去60日涨幅 | 是否选中 |")
        lines.append(f"|------|-----|-------------|---------|")
        for item in ranking:
            selected = '🏆 **选中**' if item['rank'] == 1 else ''
            lines.append(
                f"| #{item['rank']} | {item['name']} | "
                f"{item['momentum']:+.2f}% | {selected} |"
            )
    else:
        lines.append(f"⚠️ 无资产通过绝对动量测试，备选池为空。")
    lines.append(f"")

    # ===== 风控检查 =====
    lines.append(f"## 四、风控检查")
    lines.append(f"")
    risk = analysis.get('risk_check', {})
    if risk.get('passed', True):
        lines.append(f"✅ 风控检查通过，无异常。")
    else:
        lines.append(f"🚨 **风控触发:**")
        for r in risk.get('reasons', []):
            lines.append(f"- {r}")
    lines.append(f"")

    # ===== 交易决策 =====
    lines.append(f"## 五、交易决策")
    lines.append(f"")

    action_emoji = {
        'BUY': '🟢 买入',
        'SELL': '🔴 卖出',
        'SWITCH': '🔄 换仓',
        'HOLD': '⏸️ 持有',
        'EMPTY': '⬜ 空仓',
        'ERROR': '❌ 异常',
    }

    lines.append(f"### 信号: {action_emoji.get(signal.action, signal.action)}")
    lines.append(f"")
    if signal.code:
        lines.append(f"- **标的:** {signal.name} (`{signal.code}`)")
        lines.append(f"- **价格:** {signal.price:.4f}")
    lines.append(f"- **决策理由:** {signal.reason}")
    lines.append(f"")

    if signal.action == 'SWITCH':
        details = signal.details
        lines.append(f"### 换仓明细")
        lines.append(f"")
        lines.append(f"| 操作 | 标的 | 价格 |")
        lines.append(f"|------|------|------|")
        lines.append(
            f"| 卖出 | {details.get('sell_name', '')} | "
            f"{details.get('sell_price', 0):.4f} (盈亏 {details.get('sell_pnl_pct', 0):+.2f}%) |"
        )
        lines.append(
            f"| 买入 | {details.get('buy_name', '')} | {details.get('buy_price', 0):.4f} |"
        )
        lines.append(f"")

    # ===== 持仓状态 =====
    lines.append(f"## 六、当前持仓")
    lines.append(f"")
    lines.append(f"```")
    lines.append(portfolio.get_summary(
        {code: info['close'] for code, info in current_prices.items()} if current_prices else None
    ))
    lines.append(f"```")
    lines.append(f"")

    # ===== 历史交易 =====
    trades = portfolio.get_trade_history()
    if trades:
        lines.append(f"## 七、历史交易记录")
        lines.append(f"")
        lines.append(f"| 日期 | 操作 | 标的 | 价格 | 数量 | 盈亏 | 理由 |")
        lines.append(f"|------|------|------|------|------|------|------|")
        for t in trades[-20:]:  # 最近20笔
            pnl_str = f"{t.get('pnl', 0):+.2f}" if t.get('pnl', 0) != 0 else '-'
            reason_short = t.get('reason', '')[:30]
            lines.append(
                f"| {t['date']} | {t['action']} | {t['name']} | "
                f"{t['price']:.4f} | {t['shares']} | {pnl_str} | {reason_short} |"
            )
        lines.append(f"")

    # 写入文件
    content = '\n'.join(lines)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    logger.info(f"📝 操盘日志已生成: {filepath}")
    return filepath
