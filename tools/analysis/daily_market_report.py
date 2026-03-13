#!/usr/bin/env python3
"""
每日市场全景报告生成器

整合所有数据源 + AI 分析，生成一份完整的每日市场报告：
1. 大盘指数行情
2. 市场情绪快照（涨跌家数、涨跌停、成交额、北向资金）
3. 热点概念/行业板块排行
4. 板块资金流向
5. 自选股/持仓诊断
6. AI 综合分析结论

用法::

    # 生成报告（默认输出到 output/ 目录）
    python tools/analysis/daily_market_report.py

    # 带持仓分析
    python tools/analysis/daily_market_report.py --portfolio

    # 指定 AI provider
    python tools/analysis/daily_market_report.py --provider deepseek

    # 不使用 AI（仅数据报告）
    python tools/analysis/daily_market_report.py --no-ai
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.data.fetchers.market_panorama import (
    format_panorama_for_prompt,
    get_full_market_panorama,
)
from src.data.ai_analyst import (
    check_ai_config,
    generate_market_analysis,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def load_portfolio() -> List[Dict]:
    """加载持仓信息。支持 list 格式或 dict(holdings=[...]) 格式。"""
    portfolio_file = os.path.join(
        os.path.dirname(__file__), "..", "..", "mydate", "my_portfolio.json"
    )
    if os.path.exists(portfolio_file):
        try:
            with open(portfolio_file, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                holdings = data.get("holdings", [])
                # 只返回还有持仓的（shares > 0）
                return [h for h in holdings if h.get("shares", 0) > 0]
        except Exception as e:
            logger.warning("加载持仓失败: %s", e)
    return []


def format_portfolio_for_prompt(portfolio: List[Dict]) -> str:
    """将持仓信息格式化为 AI prompt 文本。"""
    if not portfolio:
        return ""
    lines = []
    for item in portfolio:
        code = item.get("code", "")
        name = item.get("name", code)
        cost = item.get("cost") or item.get("avg_cost", 0)
        volume = item.get("volume") or item.get("shares", 0)
        lines.append(f"  {name}({code}): 持仓{volume}股, 成本{cost:.2f}元")
    return "\n".join(lines)


def get_stock_pool_top_picks(top_n: int = 10) -> str:
    """获取股票池中推荐度最高的个股作为重点分析对象。"""
    pool_file = os.path.join(
        os.path.dirname(__file__), "..", "..", "mydate", "stock_pool.json"
    )
    if not os.path.exists(pool_file):
        return ""
    try:
        with open(pool_file, "r") as f:
            pool = json.load(f)
        if isinstance(pool, list):
            stocks = pool[:top_n]
        elif isinstance(pool, dict):
            stocks = list(pool.keys())[:top_n]
        else:
            return ""
        return "关注股票池: " + ", ".join(str(s) for s in stocks)
    except Exception:
        return ""


def format_report_markdown(
    panorama: Dict,
    ai_analysis: str,
    portfolio: Optional[List[Dict]] = None,
) -> str:
    """生成 Markdown 格式的完整报告。"""
    now = datetime.now()
    lines = []

    lines.append(f"# 每日市场全景报告")
    lines.append(f"**{now.strftime('%Y-%m-%d %H:%M')}**\n")
    lines.append("---\n")

    # 数据源
    lines.append("## 数据来源\n")
    lines.append("| 数据项 | 来源 | 状态 |")
    lines.append("|--------|------|------|")
    lines.append("| 指数行情 | 腾讯财经 API | 实时 |")
    lines.append("| 涨跌统计 | 新浪财经 / AKShare | 实时 |")
    lines.append("| 板块排行 | 新浪财经 / AKShare | 实时 |")
    lines.append("| 资金流向 | AKShare / 新浪(备用) | 实时 |")
    lines.append("| 北向资金 | AKShare | 实时 |")
    ai_cfg = check_ai_config()
    ai_status = f"{ai_cfg['provider']}/{ai_cfg['model']}" if ai_cfg["has_key"] else "未配置"
    lines.append(f"| AI 分析 | {ai_status} | {'启用' if ai_cfg['has_key'] else '未启用'} |")
    lines.append("")

    # AI 核心结论
    lines.append("---\n")
    lines.append("## AI 核心结论\n")
    lines.append(ai_analysis)
    lines.append("")

    # 指数行情
    indices = panorama.get("indices", [])
    if indices:
        lines.append("---\n")
        lines.append("## 大盘指数\n")
        lines.append("| 指数 | 点位 | 涨跌幅 |")
        lines.append("|------|------|--------|")
        for idx in indices:
            arrow = "▲" if (idx.get("change_pct") or 0) > 0 else "▼"
            lines.append(
                f"| {idx['name']} | {idx.get('price', 'N/A')} | "
                f"{arrow} {idx.get('change_pct', 0):+.2f}% |"
            )
        lines.append("")

    # 市场情绪
    snap = panorama.get("market_snapshot", {})
    if snap.get("total_stocks"):
        lines.append("---\n")
        lines.append("## 市场情绪\n")

        rising = snap.get("rising", 0)
        falling = snap.get("falling", 0)
        if rising > falling * 2:
            mood = "极度火热"
        elif rising > falling * 1.5:
            mood = "偏暖"
        elif falling > rising * 2:
            mood = "极度恐慌"
        elif falling > rising * 1.5:
            mood = "偏冷"
        else:
            mood = "中性震荡"

        total_amount_yi = snap.get("total_amount", 0) / 1e8
        lines.append(f"**情绪判断: {mood}**\n")
        lines.append(f"- 上涨: **{rising}**只 | 下跌: **{falling}**只 | 平盘: {snap.get('flat', 0)}只")
        lines.append(f"- 涨停: {snap.get('limit_up', 'N/A')}只 | 跌停: {snap.get('limit_down', 'N/A')}只")
        lines.append(f"- 两市成交额: **{total_amount_yi:.0f}亿元**")
        lines.append(f"- 全A平均涨幅: {snap.get('avg_change_pct', 0):+.3f}%")
        if snap.get("north_bound_net") is not None:
            nb = snap["north_bound_net"]
            nb_emoji = "流入" if nb > 0 else "流出"
            lines.append(f"- 北向资金: **{nb_emoji} {abs(nb):.2f}亿元**")
        lines.append("")

    # 热点板块
    concepts = panorama.get("hot_concepts", [])
    if concepts:
        lines.append("---\n")
        lines.append("## 热点概念板块 TOP10\n")
        lines.append("| 排名 | 板块 | 涨跌幅 | 领涨股 |")
        lines.append("|------|------|--------|--------|")
        for i, s in enumerate(concepts[:10], 1):
            leader = s.get("leader_stock", "")
            lines.append(
                f"| {i} | {s['name']} | {s.get('change_pct', 0):+.2f}% | {leader} |"
            )
        lines.append("")

    industries = panorama.get("hot_industries", [])
    if industries:
        lines.append("## 热点行业板块 TOP10\n")
        lines.append("| 排名 | 板块 | 涨跌幅 | 领涨股 |")
        lines.append("|------|------|--------|--------|")
        for i, s in enumerate(industries[:10], 1):
            leader = s.get("leader_stock", "")
            lines.append(
                f"| {i} | {s['name']} | {s.get('change_pct', 0):+.2f}% | {leader} |"
            )
        lines.append("")

    # 资金流向
    cf = panorama.get("concept_fund_flow", [])
    idf = panorama.get("industry_fund_flow", [])
    if cf or idf:
        lines.append("---\n")
        lines.append("## 板块资金流向\n")

        if cf:
            lines.append("### 概念板块资金流入 TOP5\n")
            lines.append("| 板块 | 涨跌幅 | 主力净流入 | 净占比 |")
            lines.append("|------|--------|-----------|--------|")
            for s in cf[:5]:
                inflow = s.get("main_net_inflow")
                inflow_str = f"{inflow / 1e8:.2f}亿" if inflow else "N/A"
                pct_str = f"{s.get('main_net_pct', 0):.2f}%" if s.get("main_net_pct") else "N/A"
                lines.append(
                    f"| {s['name']} | {s.get('change_pct', 0):+.2f}% | {inflow_str} | {pct_str} |"
                )
            lines.append("")

        if idf:
            lines.append("### 行业板块资金流入 TOP5\n")
            lines.append("| 板块 | 涨跌幅 | 主力净流入 | 净占比 |")
            lines.append("|------|--------|-----------|--------|")
            for s in idf[:5]:
                inflow = s.get("main_net_inflow")
                inflow_str = f"{inflow / 1e8:.2f}亿" if inflow else "N/A"
                pct_str = f"{s.get('main_net_pct', 0):.2f}%" if s.get("main_net_pct") else "N/A"
                lines.append(
                    f"| {s['name']} | {s.get('change_pct', 0):+.2f}% | {inflow_str} | {pct_str} |"
                )
            lines.append("")

    # 持仓诊断
    if portfolio:
        lines.append("---\n")
        lines.append("## 持仓概览\n")
        lines.append("| 股票 | 代码 | 持仓量 | 成本价 |")
        lines.append("|------|------|--------|--------|")
        for item in portfolio:
            code = item.get("code", "")
            name = item.get("name", code)
            cost = item.get("cost") or item.get("avg_cost", 0)
            volume = item.get("volume") or item.get("shares", 0)
            lines.append(f"| {name} | {code} | {volume}股 | {cost:.2f} |")
        lines.append("")

    # 页脚
    lines.append("---\n")
    fetch_time = panorama.get("fetch_time_sec", 0)
    lines.append(
        f"*数据更新: {now.strftime('%Y-%m-%d %H:%M:%S')} | "
        f"采集耗时: {fetch_time}s | "
        f"AI: {ai_status}*\n"
    )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="每日市场全景报告")
    parser.add_argument("--portfolio", action="store_true", help="包含持仓分析")
    parser.add_argument("--no-ai", action="store_true", help="不使用AI分析")
    parser.add_argument("--provider", type=str, default=None, help="AI provider (deepseek/qwen/minimax)")
    parser.add_argument("--output", type=str, default=None, help="输出文件路径")
    parser.add_argument("--concept-top", type=int, default=10, help="概念板块TOP N")
    parser.add_argument("--industry-top", type=int, default=10, help="行业板块TOP N")
    args = parser.parse_args()

    print("=" * 60)
    print("  每日市场全景报告生成器")
    print("=" * 60)

    # 1. 采集全景数据
    print("\n[1/3] 采集市场全景数据...")
    start = time.time()
    panorama = get_full_market_panorama(
        concept_top=args.concept_top,
        industry_top=args.industry_top,
    )
    print(f"  数据采集完成，耗时 {time.time() - start:.1f}s")

    # 2. AI 分析
    print("\n[2/3] 生成分析报告...")
    panorama_text = format_panorama_for_prompt(panorama)

    portfolio = []
    portfolio_text = ""
    if args.portfolio:
        portfolio = load_portfolio()
        portfolio_text = format_portfolio_for_prompt(portfolio)
        if portfolio:
            print(f"  已加载持仓: {len(portfolio)}只")

    stock_pool_text = get_stock_pool_top_picks()

    if args.no_ai:
        ai_analysis = (
            "（AI 分析已跳过，仅展示数据报告）\n\n"
            + panorama_text
        )
    else:
        llm_kwargs = {}
        if args.provider:
            llm_kwargs["provider"] = args.provider

        ai_analysis = generate_market_analysis(
            panorama_text=panorama_text,
            portfolio_text=portfolio_text,
            extra_context=stock_pool_text,
            **llm_kwargs,
        )

    # 3. 生成报告
    print("\n[3/3] 格式化报告...")
    report = format_report_markdown(panorama, ai_analysis, portfolio if args.portfolio else None)

    # 输出
    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "output")
    os.makedirs(output_dir, exist_ok=True)

    if args.output:
        output_path = args.output
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        output_path = os.path.join(output_dir, f"market_report_{today}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n报告已保存到: {output_path}")
    print("=" * 60)

    # 在终端也打印核心摘要
    print("\n" + "=" * 40)
    print("  核心摘要")
    print("=" * 40)

    indices = panorama.get("indices", [])
    for idx in indices:
        arrow = "▲" if (idx.get("change_pct") or 0) > 0 else "▼"
        print(f"  {idx['name']}: {idx.get('price', 'N/A')} {arrow}{idx.get('change_pct', 0):+.2f}%")

    snap = panorama.get("market_snapshot", {})
    if snap.get("total_stocks"):
        total_yi = snap.get("total_amount", 0) / 1e8
        print(f"\n  涨: {snap.get('rising', 0)} | 跌: {snap.get('falling', 0)} | "
              f"涨停: {snap.get('limit_up', 0)} | 跌停: {snap.get('limit_down', 0)}")
        print(f"  成交额: {total_yi:.0f}亿")
        if snap.get("north_bound_net") is not None:
            print(f"  北向: {snap['north_bound_net']:+.2f}亿")

    concepts = panorama.get("hot_concepts", [])
    if concepts:
        print(f"\n  热点: ", end="")
        print(" | ".join(f"{s['name']}({s.get('change_pct', 0):+.1f}%)" for s in concepts[:5]))

    print()


if __name__ == "__main__":
    main()
