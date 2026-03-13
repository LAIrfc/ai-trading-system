"""
政策关键词库（V3.3）

利好/利空/中性偏多/中性偏空 + 影响力等级；重大利空关键词单独判定。
"""

import re
from typing import Tuple

# 利好
POLICY_POSITIVE = [
    # 货币政策宽松
    "降准", "降息", "定向降准", "全面降准", "LPR下调", "再贷款", "再贴现",
    "流动性宽松", "宽松货币", "货币宽松", "量化宽松",
    # 财政刺激
    "减税", "减费", "降费", "退税", "财政补贴", "专项债", "超长期国债",
    "财政扩张", "积极财政", "财政刺激",
    # 产业政策利好
    "产业规划", "扶持", "补贴", "放宽", "改革", "新基建", "科技创新",
    "支持", "鼓励", "推动", "加快发展", "重点支持", "战略性新兴产业",
    "产业升级", "数字经济", "绿色发展", "碳中和支持",
    # 宏观稳增长
    "稳增长", "扩内需", "促消费", "稳就业", "稳经济", "稳市场",
    "逆周期", "托底", "兜底", "保增长", "经济复苏",
    # 资本市场利好
    "利好", "政策利好", "市场化改革", "注册制", "扩大开放",
    "外资流入", "北向资金", "险资入市", "长期资金入市",
    "回购增持", "分红", "市值管理",
]

# 利空
POLICY_NEGATIVE = [
    # 货币政策收紧
    "加息", "收紧", "货币收紧", "流动性收紧", "缩表", "提准",
    # 监管收紧
    "调控", "监管加强", "严监管", "整治", "规范整治", "专项整治",
    "窗口指导", "叫停", "暂停", "禁止", "限制",
    # 去杠杆/风险
    "去杠杆", "降杠杆", "化解风险", "风险提示", "风险警示",
    "处罚", "立案", "调查", "违规", "罚款",
    # 产业限制
    "限产", "收紧信贷", "压降", "退出", "淘汰", "产能过剩",
    # 贸易/地缘
    "贸易战", "关税加征", "制裁", "脱钩", "断供",
    # 市场利空
    "利空", "政策收紧", "减持", "解禁", "大股东减持",
]

# 中性偏多 / 中性偏空（V3.3 影响力 0.9 / 0.7）
POLICY_NEUTRAL_POSITIVE = [
    "稳增长", "逆周期调节", "技术突破", "出口增长", "创新药突破", "临床数据积极",
    "经济数据好于预期", "PMI回升", "CPI温和", "就业改善",
]
POLICY_NEUTRAL_NEGATIVE = [
    "流动性边际收紧", "补贴退坡", "产能过剩预警", "集采预期",
    "医保谈判预警", "技术壁垒", "研发不及预期",
    "经济数据低于预期", "PMI下滑", "通胀压力",
]

# 重大利空：影响力≥1.0 且命中以下关键词时无条件卖出（V3.3）
MAJOR_NEGATIVE_KEYWORDS = [
    "监管加强", "反垄断", "集采降价", "出口管制",
    "强制退市", "暂停上市", "立案调查", "重大处罚",
    "贸易制裁", "技术封锁",
]

# 影响力来源关键词：国家级 1.2 / 部委级 1.0 / 地方 0.8
INFLUENCE_NATIONAL = ["国务院", "央行", "发改委", "财政部", "工信部", "国常会", "中央"]
INFLUENCE_MINISTRY = ["部委", "证监会", "银保监会", "住建部", "商务部", "卫健委"]
INFLUENCE_LOCAL = ["省", "市", "区", "地方", "省政府", "市政府"]


def _influence_from_text(text: str) -> float:
    """从正文/标题推断影响力：国家级 1.2，部委级 1.0，地方 0.8，默认 1.0。"""
    if not text:
        return 1.0
    t = str(text)
    for k in INFLUENCE_NATIONAL:
        if k in t:
            return 1.2
    for k in INFLUENCE_MINISTRY:
        if k in t:
            return 1.0
    for k in INFLUENCE_LOCAL:
        if k in t:
            return 0.8
    return 1.0


def score_policy_text(text: str) -> Tuple[float, float]:
    """
    对单段政策相关文本打分并返回影响力。

    Returns
    -------
    (score, influence): score 在 [-1, 1]；influence 为 0.8/0.9/1.0/1.2 等（V3.3）。
    """
    if not text or not isinstance(text, str):
        return 0.0, 0.8
    text = re.sub(r"\s+", " ", text)
    pos = sum(1 for k in POLICY_POSITIVE if k in text)
    neg = sum(1 for k in POLICY_NEGATIVE if k in text)
    neu_pos = sum(1 for k in POLICY_NEUTRAL_POSITIVE if k in text)
    neu_neg = sum(1 for k in POLICY_NEUTRAL_NEGATIVE if k in text)
    raw = pos * 0.2 - neg * 0.2 + neu_pos * 0.1 - neu_neg * 0.1
    score = max(-1.0, min(1.0, raw))
    influence = _influence_from_text(text)
    if neu_pos and not pos and not neg:
        influence = 0.9
    if neu_neg and not pos and not neg:
        influence = 0.7
    return score, influence


def has_major_negative(text: str) -> bool:
    """是否命中重大利空关键词（监管加强、反垄断、集采降价、出口管制）。"""
    if not text or not isinstance(text, str):
        return False
    t = str(text)
    return any(k in t for k in MAJOR_NEGATIVE_KEYWORDS)
