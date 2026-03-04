"""
政策关键词库（V3.3）

利好/利空/中性偏多/中性偏空 + 影响力等级；重大利空关键词单独判定。
"""

import re
from typing import Tuple

# 利好
POLICY_POSITIVE = [
    "降准", "降息", "定向降准", "减税", "减费", "降费", "稳增长", "扩内需", "促消费",
    "产业规划", "扶持", "补贴", "放宽", "改革", "新基建", "科技创新", "支持", "鼓励",
    "稳就业", "稳经济", "流动性", "宽松", "逆周期", "托底", "利好", "政策利好",
]

# 利空
POLICY_NEGATIVE = [
    "加息", "收紧", "调控", "监管加强", "去杠杆", "处罚", "立案", "规范整治",
    "限产", "收紧信贷", "严监管", "窗口指导", "叫停", "风险提示", "利空", "政策收紧",
]

# 中性偏多 / 中性偏空（V3.3 影响力 0.9 / 0.7）
POLICY_NEUTRAL_POSITIVE = ["稳增长", "逆周期调节", "技术突破", "出口增长", "创新药突破", "临床数据积极"]
POLICY_NEUTRAL_NEGATIVE = ["流动性边际收紧", "补贴退坡", "产能过剩预警", "集采预期", "医保谈判预警", "技术壁垒", "研发不及预期"]

# 重大利空：影响力≥1.0 且命中以下关键词时无条件卖出（V3.3）
MAJOR_NEGATIVE_KEYWORDS = ["监管加强", "反垄断", "集采降价", "出口管制"]

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
