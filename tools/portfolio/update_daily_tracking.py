#!/usr/bin/env python3
"""
📝 每日跟踪文档自动更新

功能: 读取今日推荐报告，自动更新到 docs/DAILY_TRACKING.md

用法:
  python tools/portfolio/update_daily_tracking.py
"""

import sys
import os
import json
import re
from datetime import datetime

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRACKING_DOC = os.path.join(base_dir, 'docs', 'DAILY_TRACKING.md')
PORTFOLIO_FILE = os.path.join(base_dir, 'mydate', 'my_portfolio.json')
RECOMMENDATION_DIR = os.path.join(base_dir, 'tools', 'output')


def load_today_recommendation():
    """加载今日推荐报告"""
    today = datetime.now().strftime('%Y-%m-%d')
    report_file = os.path.join(RECOMMENDATION_DIR, f'daily_recommendation_{today}.md')
    
    if not os.path.exists(report_file):
        print(f"❌ 今日推荐报告不存在: {report_file}")
        return None
    
    with open(report_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 解析推荐表格（TOP 10）
    recommendations = []
    in_table = False
    for line in content.split('\n'):
        if line.startswith('| 排名'):
            in_table = True
            continue
        if in_table and line.startswith('|------'):
            continue
        if in_table and line.startswith('|'):
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if len(parts) >= 11:
                try:
                    recommendations.append({
                        'rank': int(parts[0]),
                        'code': parts[1],
                        'name': parts[2],
                        'price': float(parts[3]),
                        'score': float(parts[4]),
                        'buy': int(parts[5]),
                        'sell': int(parts[6]),
                        'hold': int(parts[7]),
                        'change_5d': parts[8],
                        'change_20d': parts[9],
                        'sector': parts[10],
                    })
                    if len(recommendations) >= 10:  # TOP 10
                        break
                except:
                    pass
    
    # 提取每只股票的详细分析
    for rec in recommendations:
        code = rec['code']
        # 查找该股票的详细分析部分
        pattern = f"### {rec['rank']}\\. {code} {rec['name']}.*?(?=###|$)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            detail = match.group(0)
            # 提取核心信号
            signals = []
            if 'MA金叉' in detail or 'MA上穿' in detail:
                signals.append('MA金叉')
            if 'MACD金叉' in detail or 'MACD上穿' in detail:
                signals.append('MACD金叉')
            if 'RSI超卖反弹' in detail:
                signals.append('RSI超卖')
            if '突破布林上轨' in detail:
                signals.append('布林突破')
            if 'KDJ金叉' in detail:
                signals.append('KDJ金叉')
            if '双重动量' in detail or '绝对动量' in detail:
                signals.append('双重动量')
            if 'PE低估' in detail or 'PE处于历史低位' in detail:
                signals.append('PE低估')
            if 'PB低估' in detail or 'PB处于历史低位' in detail:
                signals.append('PB低估')
            if '资金流入' in detail or '主力资金' in detail:
                signals.append('资金流入')
            if '利好新闻' in detail or '24h利好' in detail:
                signals.append('新闻利好')
            if '政策' in detail:
                signals.append('政策利好')
            
            rec['signals'] = signals[:3]  # 只取前3个核心信号
        else:
            rec['signals'] = []
    
    return {'date': today, 'recommendations': recommendations}


def load_portfolio():
    """加载持仓文件"""
    if not os.path.exists(PORTFOLIO_FILE):
        return {'holdings': []}
    
    with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_today_section(data, portfolio):
    """生成今日部分"""
    date = data['date']
    recs = data['recommendations']
    
    lines = [
        f"## 📅 {date}",
        "",
        "### 🎯 今日推荐 TOP 10",
        "",
        "| 排名 | 代码 | 名称 | 价格 | 得分 | 核心信号 | 5日涨 | 状态 |",
        "|------|------|------|------|------|----------|-------|------|",
    ]
    
    for rec in recs:
        signals_str = '+'.join(rec.get('signals', [])[:3]) if rec.get('signals') else '-'
        lines.append(
            f"| {rec['rank']} | {rec['code']} | {rec['name']} | {rec['price']:.2f} | "
            f"{rec['score']} | {signals_str} | {rec['change_5d']} | 🔲 |"
        )
    
    # 添加推荐理由
    lines.extend([
        "",
        "**推荐理由**：",
    ])
    
    for i, rec in enumerate(recs[:3], 1):  # 只解释前3名
        signals = rec.get('signals', [])
        if signals:
            signals_text = '、'.join(signals)
            lines.append(f"{i}. **{rec['code']} {rec['name']}**（得分{rec['score']}）：{signals_text}")
        else:
            lines.append(f"{i}. **{rec['code']} {rec['name']}**（得分{rec['score']}）：多策略共振")
    
    lines.extend([
        "",
        f"**完整报告**: `tools\\output\\daily_recommendation_{date}.md`",
        "",
        "---",
        "",
        "### 💼 当前持仓",
        "",
        "| 代码 | 名称 | 股数 | 成本 | 备注 |",
        "|------|------|------|------|------|",
    ])
    
    # 添加持仓
    cleared = []
    for h in portfolio.get('holdings', []):
        shares = h.get('shares', 0)
        if shares > 0:
            lines.append(
                f"| {h['code']} | {h['name']} | {shares:,} | {h['avg_cost']:.2f} | |"
            )
        elif h.get('comment'):
            cleared.append(f"{h['code']} {h['name']}({h['comment']})")
    
    if cleared:
        lines.append("")
        lines.append("**已清仓**: " + "、".join(cleared))
    
    lines.extend([
        "",
        "---",
        "",
        "### 📝 今日操作",
        "",
        "> 手动记录买入/卖出",
        "",
        "---",
        "",
    ])
    
    return '\n'.join(lines)


def update_tracking_doc():
    """更新跟踪文档"""
    print("\n" + "="*60)
    print("  📝 更新每日跟踪文档")
    print("="*60 + "\n")
    
    # 加载数据
    rec_data = load_today_recommendation()
    if not rec_data:
        return
    
    portfolio = load_portfolio()
    today = rec_data['date']
    
    # 读取现有文档
    if os.path.exists(TRACKING_DOC):
        with open(TRACKING_DOC, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        content = "# 📊 每日推荐与持仓\n\n> 最后更新: {}\n\n---\n\n".format(today)
    
    # 检查今日是否已存在
    if f"## 📅 {today}" in content:
        print(f"⚠️  {today} 已存在，跳过更新")
        print(f"💡 如需重新生成，请手动删除文档中的 {today} 部分")
        return
    
    # 生成新部分
    new_section = generate_today_section(rec_data, portfolio)
    
    # 插入到第一个历史日期之前
    lines = content.split('\n')
    insert_idx = None
    for i, line in enumerate(lines):
        if line.startswith('## 📅'):
            insert_idx = i
            break
        if line.startswith('## 💡 使用说明'):
            insert_idx = i
            break
    
    if insert_idx:
        lines.insert(insert_idx, new_section)
        new_content = '\n'.join(lines)
    else:
        new_content = content + '\n' + new_section
    
    # 更新时间戳
    new_content = re.sub(
        r'> 最后更新: \d{4}-\d{2}-\d{2}',
        f'> 最后更新: {today}',
        new_content
    )
    
    # 写入
    with open(TRACKING_DOC, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"✅ 已更新: docs\\DAILY_TRACKING.md")
    print(f"   日期: {today}")
    print(f"   推荐: TOP {len(rec_data['recommendations'])}")
    print(f"\n💡 打开查看: notepad docs\\DAILY_TRACKING.md")


if __name__ == '__main__':
    update_tracking_doc()
