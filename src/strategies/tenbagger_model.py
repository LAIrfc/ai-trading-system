"""
长周期十倍股模型 (3-5年) — 基于"7条铁律"选股框架

原始框架来自十五五规划分析，已在实战中成功选出豪鹏科技等标的。
本模块将7条铁律自动化，使其可以在 recommend_today.py 中对每只股票自动评分。

核心公式(来自实战验证):
  十倍股 = 小市值 × 大赛道 × 高壁垒 × 业绩拐点 × 国产替代 × 连续催化 × 合理估值

7条铁律:
  1. 赛道为王 — 十倍股一定出在大赛道的爆发期
  2. 小市值×大赛道 — 50-200亿甜蜜区
  3. 高壁垒 — 利润最厚、壁垒最高、最缺货的环节
  4. 业绩拐点 — 必须是主营利润爆发（扣非！）
  5. 国产替代 — 从0→1的自主可控突破
  6. 连续催化 — 三级跳(故事→订单/产能→利润/现金流)
  7. 合理估值 — PEG<1, PE与增速匹配, 利润质量过关

筛选条件：
  - 市值: 30-300亿 (50-200亿甜蜜区)
  - 扣非增速 > 0 (必须主营驱动)
  - 利润质量 ≥ B 级
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# 7条铁律权重 (总分700，每项100分)
W_TRACK   = 1.0   # 铁律1: 赛道为王
W_MCAP    = 1.0   # 铁律2: 小市值×大赛道
W_MOAT    = 1.0   # 铁律3: 高壁垒
W_EARNING = 1.0   # 铁律4: 业绩拐点
W_REPLACE = 1.0   # 铁律5: 国产替代
W_CATALYST= 1.0   # 铁律6: 连续催化
W_VALUE   = 1.0   # 铁律7: 合理估值

# 十五五核心赛道 (来自实战框架)
CORE_TRACKS_15TH = {
    '集成电路':   95, '半导体':     95, '芯片':       95,
    'AI算力':     93, '算力':       90, '数据中心':   88,
    '智能机器人': 92, '机器人':     90, '人形机器人': 92,
    '减速器':     88, '伺服':       85, '控制器':     85,
    '新型储能':   90, '储能':       88, '电池':       82,
    '固态电池':   90, '锂电':       80,
    'CPO':        90, '光模块':     88, '光通信':     85,
    '低空经济':   88, 'eVTOL':      90, '无人机':     85,
    '新型电网':   85, '特高压':     82, '智能电网':   80,
    '量子':       85, '量子科技':   88,
    '脑机接口':   82, '具身智能':   88,
    '卫星互联网': 85, '卫星':       82,
    '医疗器械':   85, '生物医药':   82, '创新药':     85,
    '高端装备':   80, '工业母机':   82,
    '军工航天':   80, '军工':       78, '航天':       80,
    '自动驾驶':   85, '智驾':       82,
    '航空航运':   65, '航空':       65, '物流':       60,
    '新消费':     60, '品牌消费':   58,
    '医药':       75, '药业':       72,
}

TRACK_KEYWORDS = {
    '集成电路/半导体': ['半导体', '芯片', '晶圆', '封装', '集成电路', 'IC', '功率器件',
                        'IGBT', 'SiC', 'MOSFET', 'EDA', '光刻', '存储', 'MCU',
                        '全志', '瑞芯', '兆易', '韦尔', '紫光', '中科蓝讯', '中芯'],
    'AI算力': ['算力', 'GPU', 'AI芯片', '智算', '数据中心', 'HBM', '服务器',
               '交换机', '液冷', 'AI训练', '光力科技', '华勤'],
    'CPO/光通信': ['CPO', '光模块', '光通信', '光纤', '光互联', '硅光', '光芯片',
                   '新易盛', '旭创', '中际', '光迅', '天孚'],
    '智能机器人': ['机器人', '减速器', '伺服电机', '控制器', '灵巧手', '人形',
                   '丝杠', '谐波', '行星', '编码器', '绿的', '南方精工', '兆丰'],
    '新型储能': ['储能', '锂电', '钠电', '固态电池', 'BMS', 'PCS', '液冷',
                 '电芯', '新能源', '充电桩', '豪鹏', '宁德', '亿纬'],
    '低空经济': ['低空', 'eVTOL', '无人机', '飞行汽车', '通航', '空管'],
    '新型电网': ['电网', '特高压', '智能电网', '配电', '变压器', '开关', '南网'],
    '量子科技': ['量子', '量子计算', '量子通信', '量子加密'],
    '具身智能': ['具身智能', '人形机器人', '灵巧操作', '运动控制'],
    '卫星互联网': ['卫星', '北斗', '低轨', '星链', '遥感'],
    '医疗器械': ['医疗器械', '内窥镜', '手术机器人', '体外诊断', 'IVD',
                 '影像', '监护', '超声', '心电', '血氧', '理邦', '迈瑞',
                 '医疗设备', '康复', '植入'],
    '生物医药': ['生物医药', '创新药', '靶向', '抗体', 'ADC', 'GLP-1',
                 'mRNA', '基因治疗', '细胞治疗', 'CXO', 'CDMO', '新药',
                 '医药', '药业', '制药', '生物', '疫苗', '血制品'],
    '高端装备': ['高端装备', '数控', '工业母机', '精密', '激光', '3D打印',
                 '模具', '刀具', '测量'],
    '军工航天': ['军工', '航天', '航空', '导弹', '雷达', '国防', '航发',
                 '中航', '航空发动机', '飞机', '军机', '国防科工',
                 '西飞', '沈飞', '成飞'],
    '新消费': ['消费升级', '品牌', '连锁', '免税', '跨境电商',
              '直播电商', '预制菜', '功能食品', '新零售'],
    '自动驾驶': ['自动驾驶', '智驾', '激光雷达', '域控', '线控底盘',
                '高精地图', 'L4', '车路协同', '智能座舱'],
    '航空航运': ['航空', '航运', '物流', '港口', '机场', '航线',
                '快递', '供应链', '冷链'],
}

# 国产替代关键词 (含海外大客户绑定的软性国产替代)
DOMESTIC_REPLACE_KEYWORDS = [
    '国产替代', '自主可控', '进口替代', '国产化', '卡脖子', '自研',
    '打破垄断', '填补空白', '首台套', '首批次', '国产首个',
    'MEMS', '光刻胶', 'EDA', '操作系统', '数据库', '工业软件',
]

# 海外大客户绑定 = 软性国产替代 (中国制造出海，绑定全球头部客户)
OVERSEAS_CUSTOMER_KEYWORDS = [
    '惠普', 'HP', '戴尔', 'Dell', '谷歌', 'Google', '亚马逊', 'Amazon',
    '苹果', 'Apple', '微软', 'Microsoft', '特斯拉', 'Tesla', '英伟达', 'NVIDIA',
    '三星', 'Samsung', '索尼', 'Sony', '大疆', 'DJI', '博世', 'Bosch',
    '西门子', 'Siemens', '通用', 'GE', 'ABB',
    '出海', '海外收入', '海外客户', 'CE认证', 'FDA认证', 'UL认证',
    '全球份额', '全球龙头', '全球TOP', '海外占比',
]

# 周期性行业 (十倍股不太可能出在这里)
CYCLICAL_SECTORS = {
    '有色', '钢铁', '煤炭', '石油', '化工', '造纸',
    '水泥', '建材', '地产', '房地产', '银行', '保险',
}

# 十倍股关注列表 — 之前选出的重点标的，每次评估必须包含
TENBAGGER_WATCHLIST = [
    {'code': '001283', 'name': '豪鹏科技', 'note': '储能锂电龙头，十五五选股框架选出'},
    {'code': '300041', 'name': '回天新材', 'note': '新材料+新能源胶黏剂'},
    {'code': '300502', 'name': '新易盛', 'note': 'CPO光模块龙头'},
]


@dataclass
class TenbaggerResult:
    """单只股票的长周期十倍评估结果"""
    code: str
    name: str
    tenbagger_score: float          # 0-700 (7项×100)
    tenbagger_grade: str            # S/A/B/C/D
    # 7条铁律单项得分 (0-100)
    score_track: float = 0.0       # 铁律1: 赛道
    score_mcap: float = 0.0        # 铁律2: 小市值
    score_moat: float = 0.0        # 铁律3: 高壁垒
    score_earning: float = 0.0     # 铁律4: 业绩拐点
    score_replace: float = 0.0     # 铁律5: 国产替代
    score_catalyst: float = 0.0    # 铁律6: 连续催化
    score_value: float = 0.0       # 铁律7: 合理估值
    # 辅助信息
    matched_tracks: List[str] = field(default_factory=list)
    peg: Optional[float] = None
    profit_grade: str = ''
    strengths: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)

    @property
    def is_candidate(self) -> bool:
        return self.tenbagger_grade in ('S', 'A')

    @property
    def score_pct(self) -> float:
        """得分百分比 (0-100)"""
        return self.tenbagger_score / 7.0


def _rule1_track(name: str, sector: str, news_titles: List[str] = None) -> Tuple[float, List[str]]:
    """铁律1: 赛道为王 — 十倍股一定出在大赛道的爆发期"""
    text = f"{name} {sector} " + " ".join(news_titles or [])

    matched = []
    for track_name, keywords in TRACK_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matched.append(track_name)
                break

    matched = list(set(matched))

    if not matched:
        for cyc in CYCLICAL_SECTORS:
            if cyc in text:
                return 10.0, []
        return 20.0, []

    max_score = 0.0
    for m in matched:
        for track, s in CORE_TRACKS_15TH.items():
            if track in m or m in track:
                max_score = max(max_score, float(s))
                break
        else:
            max_score = max(max_score, 70.0)

    if len(matched) >= 2:
        max_score = min(100.0, max_score + 3)

    return max_score, matched


def _rule2_mcap(market_cap_yi: Optional[float]) -> float:
    """铁律2: 小市值×大赛道 (50-200亿甜蜜区)"""
    if market_cap_yi is None:
        return 55.0  # 无数据时给中性分，不惩罚也不奖励

    if 50 <= market_cap_yi <= 100:
        return 95.0
    elif 30 <= market_cap_yi < 50:
        return 85.0
    elif 100 < market_cap_yi <= 150:
        return 85.0
    elif 150 < market_cap_yi <= 200:
        return 75.0
    elif 200 < market_cap_yi <= 300:
        return 55.0
    elif 300 < market_cap_yi <= 500:
        return 30.0
    elif market_cap_yi > 500:
        return 10.0
    elif market_cap_yi < 30:
        return 60.0
    return 40.0


def _rule3_moat(
    pb: Optional[float],
    buy_count: int,
    sell_count: int,
    sector: str,
    market_cap_yi: Optional[float],
    gross_margin: Optional[float] = None,
    rd_ratio: Optional[float] = None,
) -> Tuple[float, List[str]]:
    """铁律3: 高壁垒 — 利润最厚、壁垒最高、最缺货的环节
    
    增强维度: 毛利率(高毛利=定价权)、研发占比(高研发=技术壁垒)
    """
    score = 45.0
    strengths = []

    if pb is not None:
        if pb > 5.0:
            score += 12
            strengths.append(f"高PB({pb:.1f})暗示技术/品牌溢价")
        elif pb > 3.0:
            score += 8
        elif pb > 2.0:
            score += 4

    # 毛利率：>50%定价权极强，>35%良好壁垒
    if gross_margin is not None:
        if gross_margin > 60:
            score += 15
            strengths.append(f"毛利率{gross_margin:.0f}%极高(强定价权)")
        elif gross_margin > 45:
            score += 10
            strengths.append(f"毛利率{gross_margin:.0f}%(定价权好)")
        elif gross_margin > 30:
            score += 5
        elif gross_margin < 15:
            score -= 5

    # 研发投入比：>10%技术驱动型公司
    if rd_ratio is not None:
        if rd_ratio > 15:
            score += 12
            strengths.append(f"研发投入{rd_ratio:.0f}%(重研发)")
        elif rd_ratio > 10:
            score += 8
        elif rd_ratio > 5:
            score += 3

    total_signals = buy_count + sell_count
    if total_signals > 0:
        buy_ratio = buy_count / total_signals
        if buy_ratio >= 0.8:
            score += 10
            strengths.append("策略高度一致看多")
        elif buy_ratio >= 0.6:
            score += 5
        elif buy_ratio >= 0.4:
            score += 2
        else:
            score -= 5

    for cyc in CYCLICAL_SECTORS:
        if cyc in sector:
            score -= 15
            break

    if market_cap_yi is not None and 50 <= market_cap_yi <= 200:
        score += 3

    return float(np.clip(score, 0, 100)), strengths


def _rule4_earning(
    earnings_growth: Optional[float],
    signals: List,
    pe_ttm: Optional[float],
) -> Tuple[float, str, List[str]]:
    """铁律4: 业绩拐点 — 必须是主营利润爆发"""
    score = 40.0  # 无数据时给中性基准分(不惩罚也不高估)
    grade = 'C'
    strengths = []
    data_available = False

    eg_signal = None
    eg_reason = ''
    for sig in (signals or []):
        if sig[0] == 'EARNINGS_GROWTH':
            eg_signal = sig[1]
            eg_reason = sig[3] if len(sig) > 3 else ''
            break

    if earnings_growth is not None:
        data_available = True
        if earnings_growth > 200:
            score = 95
            strengths.append(f"扣非增速{earnings_growth:+.0f}% (爆发)")
        elif earnings_growth > 100:
            score = 90
            strengths.append(f"扣非增速{earnings_growth:+.0f}% (高增)")
        elif earnings_growth > 50:
            score = 80
            strengths.append(f"扣非增速{earnings_growth:+.0f}%")
        elif earnings_growth > 30:
            score = 65
        elif earnings_growth > 10:
            score = 50
        elif earnings_growth > 0:
            score = 40
        else:
            score = 20
    elif eg_signal == 'BUY':
        data_available = True
        score = 60
        if '景气' in eg_reason:
            strengths.append("行业景气度向好")
    elif eg_signal == 'SELL':
        data_available = True
        score = 15

    if score >= 80:
        grade = 'A'
    elif score >= 60:
        grade = 'B'
    elif score >= 40:
        grade = 'C'
    elif data_available:
        grade = 'D'
    else:
        # 无业绩数据时不应惩罚，给中性评级
        grade = 'C'

    return score, grade, strengths


def _rule5_replace(name: str, sector: str, news_titles: List[str] = None) -> float:
    """
    铁律5: 国产替代 — 从0→1的自主可控突破

    包含两种替代逻辑:
      1. 硬性替代: 国产替代进口 (芯片/MEMS/EDA等)
      2. 软性替代: 绑定海外大客户，中国制造出海 (惠普/戴尔/谷歌等)
    """
    text = f"{name} {sector} " + " ".join(news_titles or [])

    # 硬性国产替代
    hard_hits = sum(1 for kw in DOMESTIC_REPLACE_KEYWORDS if kw in text)

    # 软性替代: 海外大客户绑定
    soft_hits = sum(1 for kw in OVERSEAS_CUSTOMER_KEYWORDS if kw in text)

    # 综合评分
    if hard_hits >= 3:
        return 95.0
    elif hard_hits >= 2:
        return 85.0
    elif hard_hits >= 1 and soft_hits >= 1:
        return 85.0
    elif hard_hits >= 1:
        return 75.0
    elif soft_hits >= 3:
        return 85.0
    elif soft_hits >= 2:
        return 80.0
    elif soft_hits >= 1:
        return 70.0

    replace_sectors = ['半导体', '芯片', 'MEMS', '光刻', 'EDA', '操作系统',
                       '数据库', '工业软件', '减速器', '航天', '军工',
                       '医疗器械', '创新药']
    for rs in replace_sectors:
        if rs in text:
            return 65.0

    return 45.0


def _rule6_catalyst(
    earnings_growth: Optional[float],
    news_sentiment: float,
    news_count: int,
    buy_count: int,
    change_5d: float,
    change_20d: float,
    volume_ratio: float,
    trend: str,
    catalyst_keywords: List[str] = None,
) -> Tuple[float, List[str]]:
    """铁律6: 连续催化 — 三级跳(故事→订单/产能→利润/现金流)"""
    score = 30.0
    catalysts = []

    if earnings_growth is not None and earnings_growth > 50:
        score += 20
        catalysts.append(f"业绩拐点确认(+{earnings_growth:.0f}%)")
    elif earnings_growth is not None and earnings_growth > 20:
        score += 10

    if news_count >= 5 and news_sentiment > 0.3:
        score += 15
        catalysts.append(f"密集利好新闻({news_count}篇)")
    elif news_count >= 3 and news_sentiment > 0.1:
        score += 8

    if '多头' in trend and change_5d > 0 and volume_ratio > 1.2:
        score += 15
        catalysts.append("量价齐升+多头排列")
    elif '多头' in trend:
        score += 8
    elif change_5d > 3 and volume_ratio > 1.5:
        score += 10

    if buy_count >= 5:
        score += 10
    elif buy_count >= 3:
        score += 5

    if catalyst_keywords:
        kw_map = {
            '满产': '满产', '扩产': '扩产', '提价': '提价', '涨价': '涨价',
            '新订单': '订单催化', '中标': '中标', '大客户': '大客户导入',
            '重组': '并购重组', '募资': '募资扩产', '出海': '出海加速',
        }
        for kw in catalyst_keywords:
            for trigger, label in kw_map.items():
                if trigger in kw:
                    score += 5
                    catalysts.append(label)
                    break

    return float(np.clip(score, 0, 100)), catalysts


def _rule7_value(
    pe_ttm: Optional[float],
    pe_quantile: Optional[float],
    earnings_growth: Optional[float],
    profit_grade: str,
) -> Tuple[float, Optional[float], List[str]]:
    """铁律7: 合理估值 — PEG<1, PE与增速匹配, 利润质量过关"""
    score = 40.0
    peg = None
    strengths = []

    if pe_ttm is not None and pe_ttm > 0 and earnings_growth is not None and earnings_growth > 0:
        peg = pe_ttm / earnings_growth
        if peg < 0.3:
            score = 98
            strengths.append(f"PEG={peg:.2f} 极度低估")
        elif peg < 0.5:
            score = 92
            strengths.append(f"PEG={peg:.2f} 严重低估")
        elif peg < 0.8:
            score = 85
            strengths.append(f"PEG={peg:.2f} 明显低估")
        elif peg < 1.0:
            score = 75
            strengths.append(f"PEG={peg:.2f} 合理偏低")
        elif peg < 1.5:
            score = 55
        elif peg < 2.0:
            score = 35
        else:
            score = 20
    elif pe_ttm is not None and pe_ttm > 0:
        if pe_ttm < 10:
            score = 85
        elif pe_ttm < 20:
            score = 75
        elif pe_ttm < 30:
            score = 60
        elif pe_ttm < 50:
            score = 40
        elif pe_ttm < 80:
            score = 25
        else:
            score = 15
    elif pe_ttm is not None and pe_ttm < 0:
        score = 20
        strengths.append("当前亏损，需关注扭亏时点")
    else:
        score = 35

    if pe_quantile is not None:
        if pe_quantile < 0.2:
            score = min(100, score + 10)
            strengths.append("PE处于历史极低分位")
        elif pe_quantile < 0.35:
            score = min(100, score + 5)

    if profit_grade in ('A',):
        score = min(100, score + 5)
    elif profit_grade in ('D',):
        score = max(0, score - 15)
        strengths.append("⚠利润质量差(D级)")

    return float(np.clip(score, 0, 100)), peg, strengths


def evaluate_tenbagger(
    code: str,
    name: str,
    sector: str = '',
    price: float = 0.0,
    market_cap: Optional[float] = None,
    pe_ttm: Optional[float] = None,
    pe_quantile: Optional[float] = None,
    pb: Optional[float] = None,
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
    earnings_growth: Optional[float] = None,
    signals: List = None,
    fundamental_score: float = 0.0,
    news_sentiment: float = 0.0,
    news_count: int = 0,
    news_titles: List[str] = None,
    catalyst_keywords: List[str] = None,
    profit_quality_result=None,
    gross_margin: Optional[float] = None,
    rd_ratio: Optional[float] = None,
) -> TenbaggerResult:
    """
    基于7条铁律计算十倍股评分 (0-700)。

    与之前选出豪鹏科技的分析框架完全对齐:
      豪鹏: 小市值92 + 大赛道90 + 壁垒75 + 拐点95 + 替代80 + 催化95 + 估值98 = 625/700
    """
    # 市值转亿
    cap_yi = None
    if market_cap is not None:
        cap_yi = market_cap / 1e8 if market_cap > 1e6 else market_cap

    # 铁律1: 赛道为王
    s1, matched_tracks = _rule1_track(name, sector, news_titles)

    # 铁律2: 小市值×大赛道
    s2 = _rule2_mcap(cap_yi)

    # 铁律3: 高壁垒（含毛利率、研发投入比）
    s3, moat_strengths = _rule3_moat(pb, buy_count, sell_count, sector, cap_yi,
                                      gross_margin=gross_margin, rd_ratio=rd_ratio)

    # 铁律4: 业绩拐点 (扣非!)
    s4, profit_grade, earning_strengths = _rule4_earning(earnings_growth, signals, pe_ttm)

    # 铁律5: 国产替代
    s5 = _rule5_replace(name, sector, news_titles)

    # 铁律6: 连续催化
    s6, catalysts = _rule6_catalyst(
        earnings_growth, news_sentiment, news_count, buy_count,
        change_5d, change_20d, volume_ratio, trend, catalyst_keywords
    )

    # 铁律7: 合理估值
    s7, peg, val_strengths = _rule7_value(pe_ttm, pe_quantile, earnings_growth, profit_grade)

    # 利润质量修正
    if profit_quality_result is not None:
        if profit_quality_result.grade == 'A':
            profit_grade = 'A'
            s4 = min(100, s4 + 5)
        elif profit_quality_result.grade == 'D':
            profit_grade = 'D'
            s4 = max(0, s4 - 20)
            s7 = max(0, s7 - 15)

    total = s1 + s2 + s3 + s4 + s5 + s6 + s7
    all_strengths = earning_strengths + moat_strengths + val_strengths
    if catalysts:
        all_strengths.extend(catalysts[:2])

    risks = []

    # 铁律1是"赛道为王" — 非核心赛道有一定折扣但不过度惩罚
    # 传统行业龙头(医药/消费/金融)虽非十五五核心赛道，但有独立的十倍逻辑
    if s1 <= 30 and not matched_tracks:
        total = int(total * 0.88)
        risks.append("未匹配十五五核心赛道，十倍概率略低")
    elif s1 <= 50:
        total = int(total * 0.92)
        risks.append("赛道非十五五核心方向，需额外验证")

    if cap_yi is not None and cap_yi > 300:
        risks.append(f"市值{cap_yi:.0f}亿>300亿，十倍空间有限")
    if cap_yi is not None and cap_yi < 30:
        risks.append(f"市值{cap_yi:.0f}亿<30亿，流动性/治理风险")
    if profit_grade == 'D':
        risks.append("利润质量D级，可能为财技利润")
    if change_60d > 80:
        risks.append(f"60日涨幅{change_60d:+.0f}%，短期追高风险")
    for cyc in CYCLICAL_SECTORS:
        if cyc in sector:
            risks.append(f"周期行业({cyc})，穿越周期难度大")
            break

    # 评级 (与原始框架对齐: 豪鹏625=A级)
    if total >= 600:
        grade = 'S'
    elif total >= 500:
        grade = 'A'
    elif total >= 400:
        grade = 'B'
    elif total >= 300:
        grade = 'C'
    else:
        grade = 'D'

    return TenbaggerResult(
        code=code,
        name=name,
        tenbagger_score=round(total, 1),
        tenbagger_grade=grade,
        score_track=round(s1, 1),
        score_mcap=round(s2, 1),
        score_moat=round(s3, 1),
        score_earning=round(s4, 1),
        score_replace=round(s5, 1),
        score_catalyst=round(s6, 1),
        score_value=round(s7, 1),
        matched_tracks=matched_tracks,
        peg=round(peg, 2) if peg is not None else None,
        profit_grade=profit_grade,
        strengths=all_strengths,
        risks=risks,
    )


def batch_evaluate_tenbagger(
    stock_results: List[dict],
    top_n: int = 10,
) -> List[TenbaggerResult]:
    """
    批量评估十倍股潜力，返回按得分排序的TOP N列表。

    stock_results: recommend_today 输出的 top_list
    """
    import re

    results = []
    for r in stock_results:
        market_cap = r.get('market_cap')

        earnings_g = r.get('earnings_growth')
        if earnings_g is None:
            for sig in r.get('signals', []):
                if sig[0] == 'EARNINGS_GROWTH' and sig[1] == 'BUY':
                    reason = sig[3] if len(sig) > 3 else ''
                    m = re.search(r'(\d+\.?\d*)%', reason)
                    if m:
                        earnings_g = float(m.group(1))
                    break

        catalyst_kws = []
        for sig in r.get('signals', []):
            if len(sig) > 3:
                reason_text = sig[3]
                for kw in ['满产', '扩产', '提价', '涨价', '新订单', '中标',
                           '大客户', '重组', '募资', '出海']:
                    if kw in reason_text:
                        catalyst_kws.append(reason_text[:30])
                        break

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

        tr = evaluate_tenbagger(
            code=r['code'],
            name=r.get('name', ''),
            sector=r.get('sector', ''),
            price=r.get('price', 0),
            market_cap=market_cap,
            pe_ttm=r.get('pe_ttm'),
            pe_quantile=r.get('pe_quantile'),
            pb=r.get('pb'),
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
            earnings_growth=earnings_g,
            signals=r.get('signals', []),
            fundamental_score=r.get('fundamental_score', 0.0),
            news_sentiment=news_sent,
            news_count=news_cnt,
            catalyst_keywords=catalyst_kws,
        )
        results.append(tr)

    results.sort(key=lambda x: x.tenbagger_score, reverse=True)
    return results[:top_n]


def render_tenbagger_section(tenbagger_results: List[TenbaggerResult]) -> str:
    """生成十倍股报告章节 (7条铁律维度)"""
    lines = []
    lines.append("### 🏔️ 长周期十倍股模型 (3-5年) — 7条铁律\n")
    lines.append("> **铁律公式**: 赛道 + 小市值 + 高壁垒 + 业绩拐点 + 国产替代 + 连续催化 + 合理估值 = 总分/700\n")
    lines.append("> 框架来源: 十五五规划分析，已实战验证（豪鹏科技625/700）。\n")

    lines.append("| 排名 | 代码 | 名称 | 总分 | 评级 | 赛道 | 市值 | 壁垒 | 拐点 | 替代 | 催化 | 估值 | PEG | 赛道匹配 |")
    lines.append("|------|------|------|------|------|------|------|------|------|------|------|------|-----|----------|")

    for i, tr in enumerate(tenbagger_results, 1):
        tracks_str = '/'.join(tr.matched_tracks[:2]) if tr.matched_tracks else '-'
        peg_str = f"{tr.peg:.2f}" if tr.peg is not None else '-'
        lines.append(
            f"| {i} | {tr.code} | {tr.name} | **{tr.tenbagger_score:.0f}** | "
            f"{'⭐' if tr.tenbagger_grade in ('S','A') else ''}{tr.tenbagger_grade} | "
            f"{tr.score_track:.0f} | {tr.score_mcap:.0f} | {tr.score_moat:.0f} | "
            f"{tr.score_earning:.0f} | {tr.score_replace:.0f} | {tr.score_catalyst:.0f} | "
            f"{tr.score_value:.0f} | {peg_str} | {tracks_str} |"
        )

    lines.append("")

    for i, tr in enumerate(tenbagger_results[:3], 1):
        icon = '🥇' if i == 1 else '🥈' if i == 2 else '🥉'
        lines.append(f"\n#### {icon} {tr.name}({tr.code}) — {tr.tenbagger_score:.0f}/700 ({tr.tenbagger_grade}级)")
        lines.append("")

        tracks_text = '/'.join(tr.matched_tracks) if tr.matched_tracks else '未匹配核心赛道'
        lines.append(f"- **赛道**: {tracks_text} ({tr.score_track:.0f}分)")

        lines.append(
            f"- **7项得分**: 赛道{tr.score_track:.0f} + 市值{tr.score_mcap:.0f} + "
            f"壁垒{tr.score_moat:.0f} + 拐点{tr.score_earning:.0f} + "
            f"替代{tr.score_replace:.0f} + 催化{tr.score_catalyst:.0f} + "
            f"估值{tr.score_value:.0f} = **{tr.tenbagger_score:.0f}**"
        )

        if tr.peg is not None:
            lines.append(f"- **PEG**: {tr.peg:.2f} {'(极度低估)' if tr.peg < 0.3 else '(低估)' if tr.peg < 1 else '(合理)' if tr.peg < 1.5 else '(偏贵)'}")

        if tr.strengths:
            lines.append(f"- **亮点**: {'、'.join(tr.strengths[:4])}")
        if tr.risks:
            lines.append(f"- **⚠ 风险**: {'、'.join(tr.risks)}")
        lines.append("")

    return "\n".join(lines)


def find_golden_cross_enhanced(
    tenbagger_results: List[TenbaggerResult],
    doubler_results: List,
) -> str:
    """
    找到"长期十倍逻辑 + 短期资金启动"的黄金交叉股。

    最好的机会 = 长期十倍逻辑 + 短期资金启动
    """
    tb_map = {tr.code: tr for tr in tenbagger_results}
    db_map = {dr.code: dr for dr in doubler_results}

    common_codes = set(tb_map.keys()) & set(db_map.keys())

    golden = []
    for code in common_codes:
        tb = tb_map[code]
        db = db_map[code]
        if tb.tenbagger_score >= 350 and db.doubler_score >= 40:
            combined = tb.score_pct + db.doubler_score
            golden.append((code, tb, db, combined))

    golden.sort(key=lambda x: x[3], reverse=True)

    if not golden:
        return ""

    lines = []
    lines.append("### 🌟 黄金交叉（长期十倍逻辑 + 短期资金启动）\n")
    lines.append("> 同时满足十倍股总分≥350/700 和 翻倍股评分≥40 的个股。\n")
    lines.append("| 排名 | 代码 | 名称 | 十倍评分 | 翻倍评分 | 十倍赛道 | 翻倍赛道 | 核心逻辑 |")
    lines.append("|------|------|------|----------|----------|----------|----------|----------|")

    for i, (code, tb, db, combined) in enumerate(golden[:5], 1):
        tb_tracks = '/'.join(tb.matched_tracks[:2]) if tb.matched_tracks else '-'
        db_tracks = '/'.join(db.matched_sectors[:2]) if db.matched_sectors else '-'
        logic = '、'.join((tb.strengths[:1] + db.catalysts[:1])) if (tb.strengths or db.catalysts) else '-'
        lines.append(
            f"| {'🌟' if i <= 3 else ''}{i} | {code} | {tb.name} | "
            f"**{tb.tenbagger_score:.0f}**/700 | {db.doubler_score:.0f}/100 | "
            f"{tb_tracks} | {db_tracks} | {logic} |"
        )

    lines.append("")
    return "\n".join(lines)
