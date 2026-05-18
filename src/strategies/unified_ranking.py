"""
统一榜单架构 — 6层分级 × 产业主线标签

将三个独立模型（主推荐、翻倍股、十倍股）的结果汇总为统一的分层输出。

6层榜单:
  1. 三优共振  — 超级主线龙头  — 核心仓  — 1月-2年
  2. A类双优   — 中期主升浪    — 重仓    — 1-6月
  3. B类波段   — 事件驱动      — 波段仓  — 1-8周
  4. 主推荐    — 短线趋势      — 交易仓  — 数天-数周
  5. 翻倍候选  — 景气扩散      — 潜伏仓  — 3-6月
  6. 十倍观察池 — 长期产业      — 观察底仓 — 3-5年

共振判定:
  - 三优: 在主推中 + 翻倍评分≥50 + 十倍评分≥300（三维共振，极稀缺）
  - A类: 翻倍评分≥35 + 十倍评分≥180（不要求在主推中）
  - B类: 翻倍评分≥35 + 在主推中（不要求十倍强）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 产业主线标签映射
# ============================================================

INDUSTRY_THEME_KEYWORDS: Dict[str, List[str]] = {
    'AI电力': [
        '电力', '电源', '变压器', 'UPS', '配电', '智能电网', '开关',
        '南网科技', '思源电气', '国电南瑞', '许继电气', '平高电气',
        '数据中心电力', '备用电源', '燃气轮机', '燃机',
    ],
    'AI高速互联': [
        'CPO', '光模块', '光互联', '硅光', '光引擎', '光通信', '光纤',
        '光芯片', '高速连接器', 'PCB', '交换机', '路由器',
        '新易盛', '中际旭创', '天孚通信', '光迅科技', '华工科技',
        '沪电股份', '深南电路', '生益电子',
    ],
    '储能': [
        '储能', '锂电', '钠电', '固态电池', 'BMS', 'PCS', '液冷储能',
        '电芯', '充电桩', '换电', '虚拟电厂', '豪鹏', '宁德', '亿纬',
        '派能科技', '阳光电源', '科陆电子',
    ],
    '功率半导体': [
        '功率', 'IGBT', 'SiC', 'MOSFET', 'GaN', '碳化硅', '氮化镓',
        '功率器件', '模块封装', '斯达半导', '扬杰科技', '士兰微',
        '时代电气', '宏微科技', '新洁能', '东微半导',
    ],
    '燃机供应链': [
        '燃气轮机', '燃机', '叶片', '高温合金', '涡轮', '航发',
        '东方电气', '上海电气', '哈尔滨电气', '航发动力',
        '钢研高纳', '抚顺特钢', '图南股份',
    ],
    '机器人电气化': [
        '机器人', '减速器', '伺服电机', '控制器', '灵巧手', '丝杠',
        '谐波', '行星减速', '编码器', '力传感', '人形机器人',
        '绿的谐波', '南方精工', '兆丰股份', '汇川技术',
        '鸣志电器', '禾川科技', '步科股份',
    ],
    '国产算力': [
        '国产算力', '华为昇腾', '寒武纪', '海光信息', '龙芯',
        '景嘉微', '壁仞', '摩尔线程', '国产GPU', '信创',
        '飞腾', '鲲鹏', '申威', '曙光', '中科',
    ],
    'AI算力': [
        '算力', 'GPU', 'AI芯片', '智算中心', '数据中心', 'HBM',
        '服务器', '液冷', 'AI训练', '英伟达概念', '光力科技',
        '工业富联', '华勤技术',
    ],
    '半导体': [
        '半导体', '芯片', '晶圆', '封装测试', '集成电路', 'IC设计',
        'EDA', '光刻', '存储', 'MCU', '模拟芯片', 'SOC',
        '中芯国际', '韦尔股份', '兆易创新', '紫光国微',
    ],
    '低空经济': [
        '低空', 'eVTOL', '无人机', '飞行汽车', '通航', '空管',
        '亿航智能', '纵横股份', '中无人机', '万丰奥威',
    ],
    '卫星互联网': [
        '卫星', '北斗', '低轨', '星链', '遥感', '通信卫星',
        '中国星网', '航天宏图', '超图软件',
    ],
    '自动驾驶': [
        '自动驾驶', '智驾', '激光雷达', '域控', '线控底盘',
        '高精地图', 'L4', '车路协同', '德赛西威', '经纬恒润',
    ],
    '创新药': [
        '创新药', '靶向', '抗体', 'ADC', 'GLP-1', 'mRNA',
        '基因治疗', '细胞治疗', 'CDMO', '新药研发',
    ],
    '新材料': [
        '新材料', '胶膜', '密封胶', '导热材料', '碳纤维', '特种玻璃',
        '石英', '气凝胶', '回天新材', '壹石通',
    ],
}


def match_industry_theme(
    name: str,
    sector: str = '',
    matched_tracks: Optional[List[str]] = None,
    matched_sectors: Optional[List[str]] = None,
) -> str:
    """
    匹配产业主线标签。

    基于股票名称、所属行业、以及十倍/翻倍模型已匹配的赛道关键词来判定。
    返回最匹配的产业主线标签，无匹配返回空字符串。
    """
    search_text = f"{name} {sector}"
    if matched_tracks:
        search_text += ' ' + ' '.join(matched_tracks)
    if matched_sectors:
        search_text += ' ' + ' '.join(matched_sectors)

    best_theme = ''
    best_score = 0

    for theme, keywords in INDUSTRY_THEME_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in search_text)
        if score > best_score:
            best_score = score
            best_theme = theme

    return best_theme if best_score > 0 else ''


# ============================================================
# 榜单分级数据结构
# ============================================================

@dataclass
class RankedStock:
    """统一榜单中的单只股票"""
    code: str
    name: str
    tier: str                          # 'triple' / 'A' / 'B' / 'main' / 'doubler' / 'tenbagger'
    industry_theme: str = ''           # 产业主线标签
    # 各模型评分
    main_rank: Optional[int] = None    # 在主推荐中的排名（1-based, None=不在主推荐中）
    doubler_score: float = 0.0         # 翻倍股评分 0-100
    doubler_grade: str = ''            # S/A/B/C/D
    tenbagger_score: float = 0.0       # 十倍股评分 0-700
    tenbagger_grade: str = ''          # S/A/B/C/D
    # 补充信息
    matched_tracks: List[str] = field(default_factory=list)
    matched_sectors: List[str] = field(default_factory=list)
    catalysts: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)


TIER_META = {
    'triple': ('🏆 三优共振榜（极稀缺，全仓级）', '核心仓', '1月-2年', '超级主线龙头'),
    'A':      ('⭐ A类：双优共振榜（重仓级）', '重仓', '1-6月', '中期主升浪'),
    'B':      ('🔥 B类：翻倍+主推共振（波段仓）', '波段仓', '1-8周', '事件驱动'),
    'main':   ('📈 主推荐榜（短期操作）', '交易仓', '数天-数周', '短线趋势'),
    'doubler':('💎 翻倍候选榜（中期布局）', '潜伏仓', '3-6月', '景气扩散'),
    'tenbagger': ('🌱 十倍候选观察池（长期跟踪）', '观察底仓', '3-5年', '长期产业'),
}


# ============================================================
# 核心：统一分级逻辑
# ============================================================

def build_unified_ranking(
    recommend_results: List[dict],
    tenbagger_results: List,
    doubler_results: List,
    top_n_main: int = 15,
) -> List[RankedStock]:
    """
    将三个模型的结果汇总为统一的分层榜单。

    Args:
        recommend_results: 主推荐结果列表，每项含 code/name 等字段，按排名有序
        tenbagger_results: TenbaggerResult 列表
        doubler_results: DoublerResult 列表
        top_n_main: 主推荐取前N只

    Returns:
        按层级排序的 RankedStock 列表
    """
    main_codes = [r['code'] for r in recommend_results[:top_n_main]]
    main_map = {r['code']: (i + 1, r) for i, r in enumerate(recommend_results[:top_n_main])}
    # 三优: 只要在主推范围内即可（不限排名），真正的筛选靠翻倍+十倍双高
    main_top30_threshold = top_n_main
    main_top50_threshold = top_n_main

    tb_map = {tr.code: tr for tr in (tenbagger_results or [])}
    db_map = {dr.code: dr for dr in (doubler_results or [])}

    all_codes: Set[str] = set(main_codes) | set(tb_map.keys()) | set(db_map.keys())

    tier_triple: List[RankedStock] = []
    tier_a: List[RankedStock] = []
    tier_b: List[RankedStock] = []
    tier_main: List[RankedStock] = []
    tier_doubler: List[RankedStock] = []
    tier_tenbagger: List[RankedStock] = []

    assigned: Set[str] = set()

    for code in all_codes:
        in_main = code in main_map
        main_rank = main_map[code][0] if in_main else None
        main_info = main_map[code][1] if in_main else {}

        tb = tb_map.get(code)
        db = db_map.get(code)

        name = ''
        if tb:
            name = tb.name
        elif db:
            name = db.name
        elif main_info:
            name = main_info.get('name', '')

        tb_score = tb.tenbagger_score if tb else 0.0
        tb_grade = tb.tenbagger_grade if tb else ''
        db_score = db.doubler_score if db else 0.0
        db_grade = db.doubler_grade if db else ''

        matched_tracks = tb.matched_tracks if tb else []
        matched_sectors = db.matched_sectors if db else []
        catalysts = db.catalysts if db else []
        strengths = tb.strengths if tb else []

        industry_theme = match_industry_theme(
            name,
            sector=main_info.get('sector', ''),
            matched_tracks=matched_tracks,
            matched_sectors=matched_sectors,
        )

        stock = RankedStock(
            code=code,
            name=name,
            tier='',
            industry_theme=industry_theme,
            main_rank=main_rank,
            doubler_score=db_score,
            doubler_grade=db_grade,
            tenbagger_score=tb_score,
            tenbagger_grade=tb_grade,
            matched_tracks=matched_tracks,
            matched_sectors=matched_sectors,
            catalysts=catalysts,
            strengths=strengths,
        )

        is_main_top30 = in_main and main_rank <= main_top30_threshold
        is_main_top50 = in_main and main_rank <= main_top50_threshold
        is_doubler_strong = db_score >= 50
        is_doubler_mid = db_score >= 35
        is_tenbagger_strong = tb_score >= 300
        is_tenbagger_mid = tb_score >= 180

        # 三优共振: 在主推中 + 翻倍≥40 + 十倍≥200（三维共振）
        if is_main_top30 and is_doubler_strong and is_tenbagger_strong:
            stock.tier = 'triple'
            tier_triple.append(stock)
            assigned.add(code)
        # A类双优: 翻倍≥35 + 十倍≥180（不要求在主推中）
        elif is_doubler_mid and is_tenbagger_mid:
            stock.tier = 'A'
            tier_a.append(stock)
            assigned.add(code)
        # B类波段: 翻倍≥35 + 在主推中
        elif is_doubler_mid and is_main_top50:
            stock.tier = 'B'
            tier_b.append(stock)
            assigned.add(code)

    # 剩余的归入各自的基础榜单
    for code in main_codes:
        if code not in assigned:
            info = main_map[code][1]
            rank = main_map[code][0]
            tb = tb_map.get(code)
            db = db_map.get(code)
            name = info.get('name', '')
            matched_tracks = tb.matched_tracks if tb else []
            matched_sectors = db.matched_sectors if db else []
            industry_theme = match_industry_theme(
                name, sector=info.get('sector', ''),
                matched_tracks=matched_tracks,
                matched_sectors=matched_sectors,
            )
            stock = RankedStock(
                code=code, name=name, tier='main',
                industry_theme=industry_theme,
                main_rank=rank,
                doubler_score=db.doubler_score if db else 0.0,
                doubler_grade=db.doubler_grade if db else '',
                tenbagger_score=tb.tenbagger_score if tb else 0.0,
                tenbagger_grade=tb.tenbagger_grade if tb else '',
                matched_tracks=matched_tracks,
                matched_sectors=matched_sectors,
                catalysts=db.catalysts if db else [],
                strengths=tb.strengths if tb else [],
            )
            tier_main.append(stock)
            assigned.add(code)

    for dr in (doubler_results or []):
        if dr.code not in assigned and dr.doubler_score >= 30 and dr.doubler_grade in ('S', 'A', 'B', 'C'):
            tb = tb_map.get(dr.code)
            matched_tracks = tb.matched_tracks if tb else []
            industry_theme = match_industry_theme(
                dr.name, matched_tracks=matched_tracks,
                matched_sectors=dr.matched_sectors,
            )
            stock = RankedStock(
                code=dr.code, name=dr.name, tier='doubler',
                industry_theme=industry_theme,
                doubler_score=dr.doubler_score,
                doubler_grade=dr.doubler_grade,
                tenbagger_score=tb.tenbagger_score if tb else 0.0,
                tenbagger_grade=tb.tenbagger_grade if tb else '',
                matched_tracks=matched_tracks,
                matched_sectors=dr.matched_sectors,
                catalysts=dr.catalysts,
            )
            tier_doubler.append(stock)
            assigned.add(dr.code)

    for tr in (tenbagger_results or []):
        if tr.code not in assigned and tr.tenbagger_score >= 150:
            db = db_map.get(tr.code)
            matched_sectors = db.matched_sectors if db else []
            industry_theme = match_industry_theme(
                tr.name, matched_tracks=tr.matched_tracks,
                matched_sectors=matched_sectors,
            )
            stock = RankedStock(
                code=tr.code, name=tr.name, tier='tenbagger',
                industry_theme=industry_theme,
                tenbagger_score=tr.tenbagger_score,
                tenbagger_grade=tr.tenbagger_grade,
                doubler_score=db.doubler_score if db else 0.0,
                doubler_grade=db.doubler_grade if db else '',
                matched_tracks=tr.matched_tracks,
                matched_sectors=matched_sectors,
                strengths=tr.strengths,
                catalysts=db.catalysts if db else [],
            )
            tier_tenbagger.append(stock)
            assigned.add(tr.code)

    # 排序
    tier_triple.sort(key=lambda s: s.tenbagger_score + s.doubler_score * 7, reverse=True)
    tier_a.sort(key=lambda s: s.tenbagger_score + s.doubler_score * 7, reverse=True)
    tier_b.sort(key=lambda s: s.doubler_score, reverse=True)
    tier_main.sort(key=lambda s: s.main_rank or 999)
    tier_doubler.sort(key=lambda s: s.doubler_score, reverse=True)
    tier_tenbagger.sort(key=lambda s: s.tenbagger_score, reverse=True)

    result = tier_triple + tier_a + tier_b + tier_main + tier_doubler + tier_tenbagger
    return result


# ============================================================
# 输出渲染
# ============================================================

def render_unified_ranking(ranked: List[RankedStock]) -> str:
    """
    将分级结果渲染为 Markdown 报告。
    """
    if not ranked:
        return ""

    lines: List[str] = []
    lines.append("\n## 📊 统一分层榜单\n")
    lines.append("> 三套推荐（双优/翻倍/十倍）交叉共振分级。层级越高，确定性越强。\n")

    current_tier = ''
    for stock in ranked:
        if stock.tier != current_tier:
            current_tier = stock.tier
            title, position_attr, period, nature = TIER_META[current_tier]
            lines.append(f"\n### {title}\n")
            lines.append(f"> {position_attr} | {period} | {nature}\n")

            if current_tier == 'triple':
                lines.append("| # | 代码 | 名称 | 产业主线 | 十倍评分 | 翻倍评分 | 主推排名 | 核心逻辑 |")
                lines.append("|---|------|------|----------|----------|----------|----------|----------|")
            elif current_tier == 'A':
                lines.append("| # | 代码 | 名称 | 产业主线 | 十倍评分 | 翻倍评分 | 核心逻辑 |")
                lines.append("|---|------|------|----------|----------|----------|----------|")
            elif current_tier == 'B':
                lines.append("| # | 代码 | 名称 | 产业主线 | 翻倍评分 | 主推排名 | 催化事件 |")
                lines.append("|---|------|------|----------|----------|----------|----------|")
            elif current_tier == 'main':
                lines.append("| # | 代码 | 名称 | 产业主线 | 主推排名 | 翻倍评分 | 十倍评分 |")
                lines.append("|---|------|------|----------|----------|----------|----------|")
            elif current_tier == 'doubler':
                lines.append("| # | 代码 | 名称 | 产业主线 | 翻倍评分 | 评级 | 催化事件 |")
                lines.append("|---|------|------|----------|----------|------|----------|")
            elif current_tier == 'tenbagger':
                lines.append("| # | 代码 | 名称 | 产业主线 | 十倍评分 | 评级 | 核心优势 |")
                lines.append("|---|------|------|----------|----------|------|----------|")

            rank_in_tier = 0

        rank_in_tier += 1
        theme_tag = f"【{stock.industry_theme}】" if stock.industry_theme else ''
        logic = '、'.join((stock.strengths[:1] + stock.catalysts[:1])) if (stock.strengths or stock.catalysts) else '-'

        if current_tier == 'triple':
            lines.append(
                f"| {rank_in_tier} | {stock.code} | {stock.name} | {theme_tag} | "
                f"**{stock.tenbagger_score:.0f}**/700 | {stock.doubler_score:.0f}/100 | "
                f"TOP{stock.main_rank} | {logic} |"
            )
        elif current_tier == 'A':
            lines.append(
                f"| {rank_in_tier} | {stock.code} | {stock.name} | {theme_tag} | "
                f"**{stock.tenbagger_score:.0f}**/700 | {stock.doubler_score:.0f}/100 | "
                f"{logic} |"
            )
        elif current_tier == 'B':
            catalyst_str = '、'.join(stock.catalysts[:2]) if stock.catalysts else '-'
            lines.append(
                f"| {rank_in_tier} | {stock.code} | {stock.name} | {theme_tag} | "
                f"{stock.doubler_score:.0f}/100 | TOP{stock.main_rank} | {catalyst_str} |"
            )
        elif current_tier == 'main':
            lines.append(
                f"| {rank_in_tier} | {stock.code} | {stock.name} | {theme_tag} | "
                f"TOP{stock.main_rank} | {stock.doubler_score:.0f} | {stock.tenbagger_score:.0f} |"
            )
        elif current_tier == 'doubler':
            catalyst_str = '、'.join(stock.catalysts[:2]) if stock.catalysts else '-'
            lines.append(
                f"| {rank_in_tier} | {stock.code} | {stock.name} | {theme_tag} | "
                f"{stock.doubler_score:.0f}/100 | {stock.doubler_grade} | {catalyst_str} |"
            )
        elif current_tier == 'tenbagger':
            strength_str = '、'.join(stock.strengths[:2]) if stock.strengths else '-'
            lines.append(
                f"| {rank_in_tier} | {stock.code} | {stock.name} | {theme_tag} | "
                f"**{stock.tenbagger_score:.0f}**/700 | {stock.tenbagger_grade} | {strength_str} |"
            )

    # 统计摘要
    tier_counts = {}
    theme_counts: Dict[str, int] = {}
    for s in ranked:
        tier_counts[s.tier] = tier_counts.get(s.tier, 0) + 1
        if s.industry_theme:
            theme_counts[s.industry_theme] = theme_counts.get(s.industry_theme, 0) + 1

    lines.append("\n---\n")
    lines.append("**榜单统计**：")
    summary_parts = []
    for tier_key in ['triple', 'A', 'B', 'main', 'doubler', 'tenbagger']:
        if tier_key in tier_counts:
            emoji = TIER_META[tier_key][0].split(' ')[0]
            summary_parts.append(f"{emoji}{tier_counts[tier_key]}只")
    lines.append(' | '.join(summary_parts))

    if theme_counts:
        lines.append("\n**产业主线分布**：")
        sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
        theme_parts = [f"【{t}】×{c}" for t, c in sorted_themes[:8]]
        lines.append('  '.join(theme_parts))

    lines.append("")
    return "\n".join(lines)
