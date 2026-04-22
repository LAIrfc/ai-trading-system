"""
短周期翻倍股模型 (3-6个月)

与十倍股模型的本质区别：
  - 十倍股：重利润质量、PEG、长期赛道壁垒 → 3-5年
  - 翻倍股：重资金强度、催化密度、预期差、筹码结构 → 3-6月

翻倍概率公式:
  doubler_score = (
      W_HEAT  * sector_heat        # 行业热度 (赛道β爆发)
    + W_FUND  * capital_intensity   # 资金强度 (主力集中流入)
    + W_CATA  * catalyst_density    # 催化密度 (事件驱动)
    + W_EXPD  * expectation_diff    # 预期差 (市场未充分定价)
    + W_CHIP  * chip_concentration  # 筹码集中度 (控盘+辨识度)
  )

筛选条件：
  - 市值: 30-500亿 (放宽至500亿，中市值科技龙头也可翻倍)
  - 位置: 刚突破平台，非已翻倍高位
  - 催化: 未来3个月至少1个重大催化事件
  - 技术: 均线多头、放量突破
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 权重配置
W_HEAT = 0.25   # 行业热度
W_FUND = 0.25   # 资金强度
W_CATA = 0.20   # 催化密度
W_EXPD = 0.15   # 预期差
W_CHIP = 0.15   # 筹码集中度

# 热门赛道 → 基准热度分
HOT_SECTORS_2026 = {
    'AI算力':      0.95, 'CPO':         0.95, '光模块':      0.90,
    '机器人':      0.90, '人形机器人':  0.92, '减速器':      0.85,
    '半导体':      0.85, '芯片':        0.85, '封装':        0.80,
    '光刻胶':      0.82, 'EDA':         0.78, '存储':        0.80,
    '储能':        0.85, '固态电池':    0.88, '新能源车':    0.75,
    '低空经济':    0.88, 'eVTOL':       0.90, '无人机':      0.82,
    '并购重组':    0.80, '军工':        0.75, '卫星互联网':  0.82,
    '光伏':        0.70, '风电':        0.68, '碳纤维':      0.72,
    '医疗器械':    0.65, '创新药':      0.70, '游戏':        0.72,
    '数据要素':    0.78, '信创':        0.75, '华为':        0.80,
    '鸿蒙':        0.78, '苹果链':      0.75, '自动驾驶':    0.80,
    '新材料':      0.72, '风电':        0.68, '卫星':        0.82,
}

SECTOR_KEYWORDS = {
    'AI算力': ['算力', 'GPU', '服务器', 'AI芯片', '智算', '英伟达', '数据中心', '交换机', 'HBM', 'AI训练'],
    'CPO': ['CPO', '光互联', '硅光', '光引擎', '共封装'],
    '光模块': ['光模块', '光通信', '光纤', '光电', '旭创', '新易盛', '光迅', '光芯片'],
    '机器人': ['机器人', '减速器', '伺服', '控制器', '灵巧手', '人形', '丝杠', '谐波'],
    '半导体': ['半导体', '芯片', '晶圆', '封装', '测试', '集成电路', 'IC', '功率器件',
               'IGBT', 'SiC', 'MOSFET', '扬杰', '斯达', '韦尔', '兆易', '紫光'],
    '储能': ['储能', '电池', '锂电', '钠电', '液冷', '充电桩', 'BMS', '豪鹏', '宁德', '比亚迪电池'],
    '低空经济': ['低空', 'eVTOL', '无人机', '飞行汽车', '通航', '亿航'],
    '并购重组': ['重组', '借壳', '资产注入', '并购', '要约收购'],
    '光伏': ['光伏', '太阳能', '组件', '逆变器', '硅片', '电池片', 'EVA', 'POE',
             '胶膜', '封装材料', '背板', '银浆', '焊带', '回天'],
    '新能源车': ['新能源车', '电动车', '智驾', '座舱', '域控', '线控', '汽车电子', '电驱'],
    '军工': ['军工', '航天', '航空', '导弹', '雷达', '国防', '碳纤维', '复合材料'],
    '游戏': ['游戏', '手游', '端游', '电竞', '二次元', '网络', '冰川', '吉比特', '三七'],
    '新材料': ['新材料', '胶膜', '粘合剂', '密封胶', '导热', '碳纤维', '特种玻璃', '石英'],
    '风电': ['风电', '风力', '轴承', '叶片', '塔筒', '海上风电', '新强联'],
    '卫星': ['卫星', '北斗', '通信卫星', '遥感', '星链', '低轨'],
}


@dataclass
class DoublerResult:
    """单只股票的短周期翻倍评估结果"""
    code: str
    name: str
    doubler_score: float          # 0-100
    doubler_grade: str            # S/A/B/C/D
    sector_heat: float = 0.0     # 0-1
    capital_intensity: float = 0.0
    catalyst_density: float = 0.0
    expectation_diff: float = 0.0
    chip_concentration: float = 0.0
    matched_sectors: List[str] = field(default_factory=list)
    catalysts: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    position_status: str = ''    # 突破/盘整/高位/低位
    details: Dict[str, float] = field(default_factory=dict)

    @property
    def is_candidate(self) -> bool:
        return self.doubler_grade in ('S', 'A')


def _dynamic_heat_adjust(static_heat: float, change_20d: float, news_count: int) -> float:
    """
    动态热度修正：关注"变化率"而非绝对值。

    刚开始变热 > 已经很热（倒U型）。
    """
    bonus = 0.0
    if 5 < change_20d <= 25:
        bonus += 0.05
    elif change_20d > 50:
        bonus -= 0.05
    if news_count >= 3 and change_20d <= 30:
        bonus += 0.03
    elif news_count >= 5:
        bonus -= 0.02
    return float(np.clip(static_heat + bonus, 0.0, 1.0))


def _match_hot_sectors(name: str, sector: str, news_titles: List[str] = None,
                       change_20d: float = 0.0, news_count: int = 0) -> Tuple[List[str], float]:
    """匹配热门赛道，返回命中的赛道列表和最高热度分（含动态修正）"""
    text = f"{name} {sector} " + " ".join(news_titles or [])
    
    matched = []
    for sec_name, keywords in SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw in text or kw.upper() in text.upper():
                matched.append(sec_name)
                break
    
    matched = list(set(matched))
    
    if not matched:
        return [], 0.3
    
    max_heat = max(HOT_SECTORS_2026.get(s, 0.5) for s in matched)
    if len(matched) >= 3:
        max_heat = min(1.0, max_heat + 0.05)
    elif len(matched) >= 2:
        max_heat = min(1.0, max_heat + 0.03)
    
    max_heat = _dynamic_heat_adjust(max_heat, change_20d, news_count)
    
    return matched, max_heat


def _score_capital_intensity(
    volume_ratio: float,
    change_5d: float,
    change_20d: float,
    buy_count: int,
    fund_flow_signal: str = 'neutral',
    trend: str = '',
) -> float:
    """评估资金强度 (0-1)"""
    score = 0.0
    
    # 量比: 温和放量(1.2-3.0)最佳
    if 1.5 <= volume_ratio <= 3.0:
        score += 0.30
    elif 1.2 <= volume_ratio < 1.5 or 3.0 < volume_ratio <= 4.0:
        score += 0.20
    elif volume_ratio > 4.0:
        score += 0.15  # 过度放量，可能出货
    elif 0.8 <= volume_ratio < 1.2:
        score += 0.10
    
    # 短期动能: 连续上涨说明资金认可
    if 5 < change_5d <= 12:
        score += 0.25
    elif 2 < change_5d <= 5:
        score += 0.20
    elif 12 < change_5d <= 20:
        score += 0.15
    elif change_5d > 20:
        score += 0.05  # 过快，追高风险
    elif 0 < change_5d <= 2:
        score += 0.10
    
    # 中期趋势
    if 10 < change_20d <= 30:
        score += 0.20
    elif 3 < change_20d <= 10:
        score += 0.15
    elif 30 < change_20d <= 50:
        score += 0.10
    elif change_20d > 50:
        score += 0.05  # 短期涨幅过大
    elif 0 < change_20d <= 3:
        score += 0.08
    
    # 策略买入信号数量
    if buy_count >= 3:
        score += 0.15
    elif buy_count >= 2:
        score += 0.10
    elif buy_count >= 1:
        score += 0.05
    
    # 资金流方向
    if fund_flow_signal == 'bullish':
        score += 0.10
    elif fund_flow_signal == 'bearish':
        score -= 0.05
    
    return float(np.clip(score, 0.0, 1.0))


def _score_catalyst_density(
    earnings_growth: Optional[float],
    news_sentiment: float,
    news_count: int,
    has_earnings_surprise: bool = False,
    catalyst_keywords: List[str] = None,
) -> Tuple[float, List[str]]:
    """评估催化密度 (0-1)"""
    score = 0.0
    catalysts = []
    
    # 业绩催化
    if earnings_growth is not None:
        if earnings_growth > 200:
            score += 0.30
            catalysts.append(f"业绩暴增{earnings_growth:+.0f}%")
        elif earnings_growth > 100:
            score += 0.25
            catalysts.append(f"业绩高增{earnings_growth:+.0f}%")
        elif earnings_growth > 50:
            score += 0.20
            catalysts.append(f"业绩预增{earnings_growth:+.0f}%")
        elif earnings_growth > 20:
            score += 0.10
    
    if has_earnings_surprise:
        score += 0.10
        catalysts.append("超预期")
    
    # 新闻热度
    if news_count >= 5 and news_sentiment > 0.3:
        score += 0.25
        catalysts.append(f"新闻密集利好({news_count}篇)")
    elif news_count >= 3 and news_sentiment > 0.2:
        score += 0.15
        catalysts.append(f"近期利好({news_count}篇)")
    elif news_count >= 1 and news_sentiment > 0.1:
        score += 0.08
    
    # 催化关键词
    if catalyst_keywords:
        kw_catalysts = {
            '定增': '定增扩产', '重组': '并购重组', '大客户': '大客户导入',
            '新订单': '新订单催化', '产能': '产能释放', '扩产': '扩产兑现',
            '中标': '中标催化', '政策': '政策催化', '出海': '出海加速',
            '涨价': '涨价催化', '进口替代': '国产替代', '集采': '集采中标',
        }
        for kw in catalyst_keywords:
            for trigger, label in kw_catalysts.items():
                if trigger in kw:
                    score += 0.08
                    catalysts.append(label)
                    break
    
    return float(np.clip(score, 0.0, 1.0)), catalysts


def _score_expectation_diff(
    pe_ttm: Optional[float],
    pe_quantile: Optional[float],
    pb_quantile: Optional[float],
    earnings_growth: Optional[float],
    sector_heat: float,
    change_60d: float = 0.0,
) -> float:
    """
    评估预期差 (0-1)
    
    关键：短期翻倍不是"越便宜越好"，而是"市场还愿不愿意继续讲故事"。
    最佳预期差 = 赛道够热 + 估值不算贵 + 业绩有弹性 + 股价还没完全反映
    """
    score = 0.0
    
    # 估值合理性 (不是越低越好，而是不能太贵)
    if pe_ttm is not None and pe_ttm > 0:
        if pe_ttm < 15:
            score += 0.15  # 低PE，但可能是周期股
        elif pe_ttm < 30:
            score += 0.25  # 合理PE，预期差最大区间
        elif pe_ttm < 50:
            score += 0.20  # 略贵但可接受
        elif pe_ttm < 80:
            score += 0.10
        else:
            score += 0.05  # 太贵
    elif pe_ttm is not None and pe_ttm < 0:
        # 亏损但赛道热→市场愿意给估值
        if sector_heat > 0.7:
            score += 0.15
    else:
        score += 0.10  # 无数据
    
    # 估值分位: 不在极端高位
    if pe_quantile is not None:
        if pe_quantile < 0.3:
            score += 0.15  # 历史低位
        elif pe_quantile < 0.5:
            score += 0.20  # 中低位，预期差最大
        elif pe_quantile < 0.7:
            score += 0.10
        else:
            score += 0.03  # 高位，预期差小
    
    # PEG隐含预期差
    if pe_ttm is not None and pe_ttm > 0 and earnings_growth is not None and earnings_growth > 0:
        peg = pe_ttm / earnings_growth
        if peg < 0.3:
            score += 0.20  # 严重低估
        elif peg < 0.6:
            score += 0.15
        elif peg < 1.0:
            score += 0.10
        elif peg < 1.5:
            score += 0.05
    
    # 股价位置: 刚起涨最佳 (60日涨幅不太大)
    if 0 < change_60d <= 20:
        score += 0.15  # 刚启动
    elif 20 < change_60d <= 40:
        score += 0.10  # 中途
    elif 40 < change_60d <= 60:
        score += 0.05  # 有些贵了
    elif change_60d > 60:
        score += 0.00  # 太高，翻倍空间被压缩
    elif -20 < change_60d <= 0:
        score += 0.10  # 回踩
    elif change_60d <= -20:
        score += 0.05  # 可能趋势转弱
    
    return float(np.clip(score, 0.0, 1.0))


def _score_chip_concentration(
    market_cap: Optional[float],  # 亿
    volume_ratio: float,
    change_5d: float,
    change_20d: float,
    dist_high: float,
    trend: str,
) -> float:
    """
    评估筹码集中度 (0-1)
    
    流通市值不大 + 股东户数下降 + 龙头辨识度高 → 一致预期形成后加速
    """
    score = 0.0
    
    # 市值档位: <50亿最容易筹码集中，>300亿需要更大资金
    if market_cap is not None:
        if market_cap < 50:
            score += 0.30
        elif market_cap < 100:
            score += 0.25
        elif market_cap < 200:
            score += 0.20
        elif market_cap < 300:
            score += 0.15
        elif market_cap < 500:
            score += 0.10
        else:
            score += 0.05
    else:
        score += 0.10
    
    # 趋势集中: 多头排列→筹码趋于一致
    if '多头' in trend:
        score += 0.25
    elif '偏多' in trend:
        score += 0.15
    elif '交叉' in trend:
        score += 0.10
    
    # 位置集中: 突破新高=筹码解套完毕
    if dist_high >= 0:
        score += 0.20  # 突破新高
    elif dist_high > -5:
        score += 0.15
    elif dist_high > -15:
        score += 0.10
    
    # 涨跌一致性: 5日和20日同向上涨
    if change_5d > 0 and change_20d > 0:
        score += 0.15
    elif change_5d > 0 or change_20d > 0:
        score += 0.08
    
    return float(np.clip(score, 0.0, 1.0))


def _assess_position(
    change_5d: float,
    change_20d: float,
    change_60d: float,
    dist_high: float,
    dist_low: float,
    trend: str,
) -> Tuple[str, List[str]]:
    """
    评估股价位置，识别风险
    返回: (位置描述, 风险标识列表)
    """
    risks = []
    
    if change_60d > 80:
        risks.append("60日涨幅过大(+{:.0f}%)，追高风险".format(change_60d))
    if change_20d > 40:
        risks.append("20日涨幅过大(+{:.0f}%)".format(change_20d))
    if dist_high >= 0:
        position = '突破新高'
    elif dist_high > -5:
        position = '接近新高'
    elif dist_high > -15:
        position = '中位偏高'
    elif dist_high > -30:
        position = '中位'
    else:
        position = '低位'
        if '空头' in trend:
            risks.append("空头排列下行趋势")
    
    if '多头' in trend and change_5d > 0:
        position += '，趋势向上'
    
    return position, risks


def evaluate_doubler(
    code: str,
    name: str,
    sector: str = '',
    price: float = 0.0,
    market_cap: Optional[float] = None,  # 亿
    pe_ttm: Optional[float] = None,
    pe_quantile: Optional[float] = None,
    pb_quantile: Optional[float] = None,
    change_5d: float = 0.0,
    change_20d: float = 0.0,
    change_60d: float = 0.0,
    dist_high: float = 0.0,
    dist_low: float = 0.0,
    volume_ratio: float = 1.0,
    trend: str = '',
    buy_count: int = 0,
    sell_count: int = 0,
    fund_flow_signal: str = 'neutral',
    earnings_growth: Optional[float] = None,
    has_earnings_surprise: bool = False,
    news_sentiment: float = 0.0,
    news_count: int = 0,
    news_titles: List[str] = None,
    catalyst_keywords: List[str] = None,
) -> DoublerResult:
    """
    计算短周期翻倍评分。

    返回 DoublerResult (0-100分)。
    """
    # 市值门槛（全部软惩罚，不硬切——牛市中大票也可能翻倍）
    _large_cap_penalty = 1.0
    risk_flags_early = []
    if market_cap is not None:
        if market_cap < 30:
            return DoublerResult(
                code=code, name=name, doubler_score=10.0,
                doubler_grade='D', risk_flags=[f'市值{market_cap:.0f}亿<30亿，流动性风险'],
                position_status='市值不符',
            )
        elif market_cap > 2000:
            _large_cap_penalty = 0.50
            risk_flags_early.append(f'市值{market_cap:.0f}亿>2000亿，翻倍极难×0.50')
        elif market_cap > 1000:
            _large_cap_penalty = 0.60
            risk_flags_early.append(f'市值{market_cap:.0f}亿>1000亿，翻倍难度大×0.60')
        elif market_cap >= 500:
            _large_cap_penalty = 0.75
            risk_flags_early.append(f'市值{market_cap:.0f}亿(500-1000亿)，默认打折×0.75')
    
    # 1. 行业热度（含动态修正：用变化率而非绝对涨幅）
    matched_sectors, heat = _match_hot_sectors(
        name, sector, news_titles,
        change_20d=change_20d, news_count=news_count,
    )
    sector_heat = heat
    
    # 2. 资金强度
    capital_intensity = _score_capital_intensity(
        volume_ratio, change_5d, change_20d, buy_count, fund_flow_signal, trend
    )
    
    # 3. 催化密度
    catalyst_density, catalysts = _score_catalyst_density(
        earnings_growth, news_sentiment, news_count,
        has_earnings_surprise, catalyst_keywords
    )
    
    # 4. 预期差
    expectation_diff = _score_expectation_diff(
        pe_ttm, pe_quantile, pb_quantile, earnings_growth,
        sector_heat, change_60d
    )
    
    # 5. 筹码集中度
    chip_concentration = _score_chip_concentration(
        market_cap, volume_ratio, change_5d, change_20d, dist_high, trend
    )
    
    # 位置评估
    position_status, risk_flags = _assess_position(
        change_5d, change_20d, change_60d, dist_high, dist_low, trend
    )
    
    # 综合评分
    raw_score = (
        W_HEAT * sector_heat +
        W_FUND * capital_intensity +
        W_CATA * catalyst_density +
        W_EXPD * expectation_diff +
        W_CHIP * chip_concentration
    ) * 100
    
    # 惩罚项
    if sell_count >= 3:
        raw_score *= 0.80
        risk_flags.append(f"多策略看空({sell_count}个卖出信号)")
    elif sell_count >= 2:
        raw_score *= 0.90
    
    if change_60d > 100:
        raw_score *= 0.70
        risk_flags.append("60日已翻倍，短期继续翻倍概率低")
    elif change_60d > 60:
        raw_score *= 0.85

    # 大市值软惩罚（500-1000亿）：龙头属性强可恢复到×0.90，但不完全恢复
    if _large_cap_penalty < 1.0:
        large_cap_bonus = sector_heat * 0.25 + min(capital_intensity, 0.25) + min(catalyst_density, 0.2)
        if large_cap_bonus > 0.55:
            _large_cap_penalty = 0.90
            risk_flags_early[-1] = f'市值{market_cap:.0f}亿，龙头属性强恢复至×0.90'
        raw_score *= _large_cap_penalty
        risk_flags = risk_flags_early + risk_flags

    final_score = float(np.clip(raw_score, 0.0, 100.0))
    
    # 评级
    if final_score >= 70:
        grade = 'S'
    elif final_score >= 55:
        grade = 'A'
    elif final_score >= 40:
        grade = 'B'
    elif final_score >= 25:
        grade = 'C'
    else:
        grade = 'D'
    
    return DoublerResult(
        code=code,
        name=name,
        doubler_score=round(final_score, 1),
        doubler_grade=grade,
        sector_heat=round(sector_heat, 3),
        capital_intensity=round(capital_intensity, 3),
        catalyst_density=round(catalyst_density, 3),
        expectation_diff=round(expectation_diff, 3),
        chip_concentration=round(chip_concentration, 3),
        matched_sectors=matched_sectors,
        catalysts=catalysts,
        risk_flags=risk_flags,
        position_status=position_status,
        details={
            'heat_contrib': round(W_HEAT * sector_heat * 100, 1),
            'capital_contrib': round(W_FUND * capital_intensity * 100, 1),
            'catalyst_contrib': round(W_CATA * catalyst_density * 100, 1),
            'expect_contrib': round(W_EXPD * expectation_diff * 100, 1),
            'chip_contrib': round(W_CHIP * chip_concentration * 100, 1),
        },
    )


def batch_evaluate_doubler(
    stock_results: List[dict],
    top_n: int = 10,
) -> List[DoublerResult]:
    """
    批量评估翻倍潜力，返回按得分排序的TOP N列表。
    
    stock_results: recommend_today 输出的 all_results 列表
    """
    results = []
    for r in stock_results:
        # 估算市值 (price * 流通股)，如无则跳过市值检查
        market_cap = r.get('market_cap')
        
        # 提取催化关键词 (从 signals 或 reason 中)
        catalyst_kws = []
        for sig in r.get('signals', []):
            if len(sig) > 3:
                reason_text = sig[3]
                for kw in ['定增', '重组', '大客户', '新订单', '产能', '扩产',
                           '中标', '政策', '出海', '涨价', '进口替代', '集采']:
                    if kw in reason_text:
                        catalyst_kws.append(reason_text[:30])
                        break
        
        # 提取业绩增速
        earnings_g = r.get('earnings_growth')
        if earnings_g is None:
            for sig in r.get('signals', []):
                if sig[0] == 'EARNINGS_GROWTH' and sig[1] == 'BUY':
                    reason = sig[3] if len(sig) > 3 else ''
                    import re
                    m = re.search(r'(\d+\.?\d*)%', reason)
                    if m:
                        earnings_g = float(m.group(1))
                    break
        
        # 新闻情绪
        news_sent = 0.0
        news_cnt = 0
        for sig in r.get('signals', []):
            if sig[0] == 'NEWS':
                if sig[1] == 'BUY':
                    news_sent = 0.5
                    news_cnt = 3
                elif sig[1] == 'SELL':
                    news_sent = -0.3
                    news_cnt = 2
                break
        
        dr = evaluate_doubler(
            code=r['code'],
            name=r.get('name', ''),
            sector=r.get('sector', ''),
            price=r.get('price', 0),
            market_cap=market_cap,
            pe_ttm=r.get('pe_ttm'),
            pe_quantile=r.get('pe_quantile'),
            pb_quantile=r.get('pb_quantile'),
            change_5d=r.get('change_5d', 0),
            change_20d=r.get('change_20d', 0),
            change_60d=r.get('change_60d', 0),
            dist_high=r.get('dist_high', 0),
            dist_low=r.get('dist_low', 0),
            volume_ratio=r.get('volume_ratio', 1.0),
            trend=r.get('trend', ''),
            buy_count=r.get('buy_count', 0),
            sell_count=r.get('sell_count', 0),
            fund_flow_signal=r.get('fund_flow_signal', 'neutral'),
            earnings_growth=earnings_g,
            news_sentiment=news_sent,
            news_count=news_cnt,
            catalyst_keywords=catalyst_kws,
        )
        results.append(dr)
    
    results.sort(key=lambda x: x.doubler_score, reverse=True)
    return results[:top_n]


def render_doubler_section(doubler_results: List[DoublerResult]) -> str:
    """生成翻倍股报告章节"""
    lines = []
    lines.append("### 🚀 短周期翻倍股模型 (3-6个月)\n")
    lines.append("> **翻倍概率公式**: 行业热度×25% + 资金强度×25% + 催化密度×20% + 预期差×15% + 筹码集中度×15%\n")
    lines.append("> 与十倍股模型互补：十倍股重利润，翻倍股重资金与催化。最佳机会 = 长期十倍逻辑 + 短期资金启动。\n")
    
    lines.append("| 排名 | 代码 | 名称 | 评分 | 评级 | 行业热度 | 资金强度 | 催化密度 | 预期差 | 筹码 | 赛道 | 催化 | 位置 |")
    lines.append("|------|------|------|------|------|----------|----------|----------|--------|------|------|------|------|")
    
    for i, dr in enumerate(doubler_results, 1):
        sectors_str = '/'.join(dr.matched_sectors[:2]) if dr.matched_sectors else '-'
        catalysts_str = '、'.join(dr.catalysts[:2]) if dr.catalysts else '-'
        lines.append(
            f"| {i} | {dr.code} | {dr.name} | **{dr.doubler_score:.0f}** | "
            f"{'⭐' if dr.doubler_grade in ('S','A') else ''}{dr.doubler_grade} | "
            f"{dr.sector_heat:.0%} | {dr.capital_intensity:.0%} | "
            f"{dr.catalyst_density:.0%} | {dr.expectation_diff:.0%} | "
            f"{dr.chip_concentration:.0%} | {sectors_str} | {catalysts_str} | "
            f"{dr.position_status} |"
        )
    
    lines.append("")
    
    # 详细分析TOP3
    for i, dr in enumerate(doubler_results[:3], 1):
        lines.append(f"\n#### {'🥇' if i==1 else '🥈' if i==2 else '🥉'} {dr.name}({dr.code}) — 翻倍评分 {dr.doubler_score:.0f}")
        lines.append("")
        lines.append(f"- **赛道**: {'/'.join(dr.matched_sectors) if dr.matched_sectors else '未匹配热门赛道'} (热度{dr.sector_heat:.0%})")
        
        contrib = dr.details
        lines.append(f"- **五维贡献**: 热度{contrib.get('heat_contrib',0):.0f} + "
                     f"资金{contrib.get('capital_contrib',0):.0f} + "
                     f"催化{contrib.get('catalyst_contrib',0):.0f} + "
                     f"预期差{contrib.get('expect_contrib',0):.0f} + "
                     f"筹码{contrib.get('chip_contrib',0):.0f} = {dr.doubler_score:.0f}")
        
        if dr.catalysts:
            lines.append(f"- **催化剂**: {'、'.join(dr.catalysts)}")
        if dr.risk_flags:
            lines.append(f"- **⚠ 风险**: {'、'.join(dr.risk_flags)}")
        lines.append("")
    
    return "\n".join(lines)


def find_golden_cross(
    doubler_results: List[DoublerResult],
    tenbagger_scores: Dict[str, float],
) -> List[Tuple[str, str, float, float]]:
    """
    找到"长期十倍逻辑 + 短期资金启动"的黄金交叉股。
    
    返回: [(code, name, doubler_score, tenbagger_score), ...]
    """
    golden = []
    for dr in doubler_results:
        tb_score = tenbagger_scores.get(dr.code, 0)
        if dr.doubler_score >= 50 and tb_score >= 50:
            golden.append((dr.code, dr.name, dr.doubler_score, tb_score))
    
    golden.sort(key=lambda x: x[2] + x[3], reverse=True)
    return golden
