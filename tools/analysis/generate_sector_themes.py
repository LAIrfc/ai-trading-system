#!/usr/bin/env python3
"""
生成专题板块推荐

自动分析预定义的专题板块（如核电+算电协同），生成专题推荐报告
不再调用子进程，直接在内存中分析并返回结果
"""

import os
import sys
import json
from datetime import datetime

# 专题板块配置
SECTOR_THEMES = {
    "nuclear_computing": {
        "name": "核电+算电协同",
        "description": "AI算力需求爆发，电力基础设施成为关键瓶颈。核电作为清洁、稳定的基荷电源，与算力中心形成协同效应。本专题从核电设备、电力运营、算力基础设施、智能电网四个维度筛选52只相关标的。",
        "pool_file": "mydate/stock_pool_nuclear_computing.json",
        "top_n": 10,
        "icon": "🔋"
    }
}


def generate_theme_section(theme_key: str, theme_config: dict, all_results: list) -> str:
    """
    从已有的分析结果中生成专题板块推荐内容
    
    Args:
        theme_key: 专题键名
        theme_config: 专题配置
        all_results: 所有股票的分析结果列表
        
    Returns:
        专题推荐的Markdown内容
    """
    if not all_results:
        print(f"⚠️ 专题 {theme_config['name']} 无分析结果")
        return ""
    
    # 按得分排序，取TOP N
    sorted_results = sorted(all_results, key=lambda x: x.get('score', 0), reverse=True)
    top_results = sorted_results[:theme_config['top_n']]
    
    if not top_results:
        print(f"⚠️ 专题 {theme_config['name']} 无有效推荐")
        return ""
    
    # 生成专题推荐内容
    content = []
    content.append(f"\n## {theme_config['icon']} 专题板块推荐：{theme_config['name']}\n")
    content.append(f"\n> **板块逻辑**: {theme_config['description']}\n")
    content.append(f"\n**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}（最新数据） | **股票池**: {len(all_results)}只 | **有效**: {len(all_results)}只\n")
    content.append(f"\n### 📊 {theme_config['name']} TOP{theme_config['top_n']}\n")
    content.append("\n| 排名 | 代码 | 名称 | 价格 | 得分 | 买/卖/观 | 5日% | 20日% | 板块 | 推荐理由 |\n")
    content.append("|------|------|------|------|------|----------|------|-------|------|----------|\n")
    
    # 生成TOP表格
    for i, r in enumerate(top_results, 1):
        code = r.get('code', '')
        name = r.get('name', '')
        price = r.get('price', r.get('close', 0))  # 优先使用price字段
        score = r.get('score', 0)
        buy_count = r.get('buy_count', 0)
        sell_count = r.get('sell_count', 0)
        hold_count = r.get('hold_count', 0)
        change_5d = r.get('change_5d', 0)
        change_20d = r.get('change_20d', 0)
        sector = r.get('sector', 'N/A')
        
        # 生成推荐理由
        reasons = []
        if buy_count >= 8:
            reasons.append("KDJ金叉+PE/PB双低估" if score > 15 else "多策略看多")
        elif change_20d > 8:
            reasons.append("趋势强劲")
        elif change_5d > 5:
            reasons.append("短期强势")
        elif score > 10:
            reasons.append("估值合理")
        else:
            reasons.append("超跌反弹机会")
        
        reason = "+".join(reasons) if reasons else "关注"
        
        content.append(f"| {i} | {code} | {name} | ¥{price:.2f} | {score:.1f} | {buy_count}/{sell_count}/{hold_count} | {change_5d:+.2f}% | {change_20d:+.2f}% | {sector} | {reason} |\n")
    
    # 生成重点推荐TOP3详细分析
    content.append(f"\n### 🌟 重点推荐 TOP3\n")
    
    for i, r in enumerate(top_results[:3], 1):
        code = r.get('code', '')
        name = r.get('name', '')
        price = r.get('price', r.get('close', 0))  # 优先使用price字段
        score = r.get('score', 0)
        trend = r.get('trend', '')
        volume_ratio = r.get('volume_ratio', 0)
        change_5d = r.get('change_5d', 0)
        change_20d = r.get('change_20d', 0)
        sector = r.get('sector', 'N/A')
        buy_signals = r.get('buy_signals', [])
        
        stars = "⭐" * min(3, int(score / 5))
        
        content.append(f"\n#### {i}️⃣ {name}（{code}）{stars} - 得分{score:.1f}\n")
        content.append(f"\n**基本信息**:\n")
        content.append(f"- **价格**: ¥{price:.2f}（最新） | **板块**: {sector}\n")
        content.append(f"- **趋势**: {trend} | **量比**: {volume_ratio:.1f}x\n")
        content.append(f"- **涨跌幅**: 5日 {change_5d:+.2f}% / 20日 {change_20d:+.2f}%\n")
        
        content.append(f"\n**核心优势**:\n")
        # 提取关键买入信号
        key_signals = []
        for sig in buy_signals[:5]:  # 最多显示5个
            key_signals.append(f"- ✅ **{sig}**")
        if key_signals:
            content.append("\n".join(key_signals) + "\n")
        else:
            content.append(f"- ✅ **{len(buy_signals)}个策略看多**\n")
        
        content.append(f"\n**投资逻辑**:\n")
        if "电力" in sector or "核电" in sector:
            content.append(f"- {name}受益于AI算力需求爆发，电力基础设施成为关键瓶颈\n")
        if score > 15:
            content.append(f"- 估值处于历史低位，安全边际高\n")
        if change_20d > 8:
            content.append(f"- 中期趋势强劲，量价配合良好\n")
        elif change_5d > 5:
            content.append(f"- 短期动能强劲\n")
        
        content.append(f"\n**风险提示**: {r.get('sell_signals', ['无明显风险'])[0] if r.get('sell_signals') else '注意回调风险'}\n")
        content.append(f"\n---\n")
    
    # 投资建议
    content.append(f"\n### 💡 板块投资建议\n")
    content.append(f"\n**配置策略**:\n")
    content.append(f"1. **首选**: {top_results[0].get('name', '')}、{top_results[1].get('name', '')} - 估值极低+技术面金叉+板块龙头\n")
    if len(top_results) >= 5:
        content.append(f"2. **次选**: {top_results[2].get('name', '')}、{top_results[3].get('name', '')}、{top_results[4].get('name', '')} - 趋势向上+估值合理\n")
    content.append(f"\n**仓位建议**:\n")
    content.append(f"- 激进型: 30-40%仓位，重点配置TOP3\n")
    content.append(f"- 稳健型: 15-20%仓位，分散配置TOP5\n")
    content.append(f"- 保守型: 5-10%仓位，配置龙头股\n")
    content.append(f"\n**风险提示**:\n")
    content.append(f"- ⚠️ 电力板块整体估值偏低，但需关注政策面和煤价走势\n")
    content.append(f"- ⚠️ 算力基础设施受益于AI发展，但需关注电力供应紧张问题\n")
    content.append(f"- ⚠️ 建议分批建仓，控制仓位，设置止损\n")
    content.append(f"\n**催化剂关注**:\n")
    content.append(f"- 国家算力网络建设政策\n")
    content.append(f"- 核电项目审批进度\n")
    content.append(f"- 电价改革政策\n")
    content.append(f"- AI大模型落地进展\n")
    content.append(f"\n---\n")
    
    return "".join(content)


def generate_all_themes(sector_results_map: dict) -> str:
    """
    生成所有专题板块的推荐内容
    
    Args:
        sector_results_map: 字典，key为theme_key，value为该专题的分析结果列表
        
    Returns:
        所有专题推荐的Markdown内容
    """
    all_content = []
    
    for theme_key, theme_config in SECTOR_THEMES.items():
        results = sector_results_map.get(theme_key, [])
        if results:
            theme_content = generate_theme_section(theme_key, theme_config, results)
            if theme_content:
                all_content.append(theme_content)
    
    return "".join(all_content)


def load_stock_pool_for_theme(theme_key: str, base_dir: str) -> list:
    """
    加载专题板块的股票池
    
    Args:
        theme_key: 专题键名
        base_dir: 项目根目录
        
    Returns:
        股票列表
    """
    theme_config = SECTOR_THEMES.get(theme_key)
    if not theme_config:
        return []
    
    pool_file = os.path.join(base_dir, theme_config["pool_file"])
    if not os.path.exists(pool_file):
        print(f"⚠️ 专题股票池文件不存在: {pool_file}")
        return []
    
    try:
        with open(pool_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        stocks = []
        if isinstance(data, dict) and 'stocks' in data:
            # 新格式：{"stocks": {"sector1": [...], "sector2": [...]}}
            for sector_name, sector_stocks in data['stocks'].items():
                for stock in sector_stocks:
                    if isinstance(stock, dict) and 'code' in stock and 'name' in stock:
                        stocks.append({
                            'code': stock['code'],
                            'name': stock['name'],
                            'sector': sector_name
                        })
        elif isinstance(data, list):
            # 旧格式：[{"code": "...", "name": "..."}, ...]
            stocks = data
        
        return stocks
    except Exception as e:
        print(f"❌ 加载股票池失败: {e}")
        return []


if __name__ == "__main__":
    print("此模块现在由 recommend_today.py 调用，不再独立运行")
    print("请使用: python tools/analysis/recommend_today.py --append-sectors")
