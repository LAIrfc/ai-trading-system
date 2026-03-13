"""
新闻情感打分（关键词规则版）

对标题+摘要/正文做简单情感打分，范围 -1（利空）～ 1（利好）。
后续可替换为预训练 NLP 模型。
"""

import re
from typing import Union

import pandas as pd


# ──────────────────────────────────────────────
# 利好关键词（出现则正向加分）
# ──────────────────────────────────────────────
POSITIVE_KEYWORDS = [
    # 行情/技术面
    "利好", "大涨", "涨停", "涨幅", "突破", "创新高", "历史新高", "强势",
    "放量", "主力买入", "北向加仓",
    # 业绩/财务
    "业绩预增", "业绩大增", "净利润增", "营收增", "扭亏为盈", "扭亏",
    "超预期", "超市场预期", "盈利", "盈利能力", "毛利率提升", "净利率提升",
    "现金流改善", "派息", "分红", "特别股息", "高送转",
    # 事件/催化剂
    "中标", "签约", "大单", "订单", "战略合作", "合作协议", "入围",
    "获批", "批准", "通过审批", "注册成功", "上市获批", "纳入", "入选",
    "回购", "增持", "大股东增持", "管理层增持", "股权激励",
    "扩产", "投产", "量产", "新产能", "产能释放", "产能爬坡",
    "并购", "收购", "重组", "资产注入", "借壳", "整合",
    "定增", "配股", "融资成功",
    # 行业/政策
    "景气", "景气度提升", "行业复苏", "需求回暖", "供需改善",
    "政策支持", "政策利好", "补贴", "减税", "降费", "专项资金",
    "纳入指数", "入选标普", "入选MSCI", "入选沪深300",
    # 技术/产品
    "研发突破", "技术突破", "专利获批", "核心技术", "自主研发",
    "新产品", "新业务", "新赛道", "市占率提升",
]

# ──────────────────────────────────────────────
# 利空关键词（出现则负向加分）
# ──────────────────────────────────────────────
NEGATIVE_KEYWORDS = [
    # 行情/技术面
    "利空", "大跌", "跌停", "跌幅", "破位", "创新低", "历史新低",
    "放量下跌", "主力出逃", "北向减仓",
    # 业绩/财务
    "亏损", "净亏损", "巨亏", "业绩变脸", "业绩下滑", "业绩不及预期",
    "营收下滑", "毛利率下降", "净利率下降", "现金流恶化",
    "商誉减值", "资产减值", "计提减值", "坏账", "存货减值",
    "债务违约", "违约", "爆仓", "流动性危机", "资金链断裂",
    # 事件/风险
    "暴雷", "雷", "爆雷", "减持", "大股东减持", "清仓式减持",
    "立案", "调查", "被查", "稽查", "处罚", "罚款", "行政处罚",
    "违规", "违法", "欺诈", "造假", "财务造假",
    "诉讼", "仲裁", "被起诉", "索赔",
    "停产", "停工", "停产整顿", "关停", "产能削减",
    "退市", "退市风险", "ST", "*ST", "摘牌",
    "质押爆仓", "股权质押", "强制平仓",
    # 行业/政策
    "行业整顿", "行业监管", "行业寒冬", "需求萎缩", "供给过剩",
    "政策收紧", "限价", "限产", "反垄断", "反倾销",
    "贸易摩擦", "关税", "制裁", "出口限制",
    # 宏观
    "加息", "缩表", "流动性收紧", "信用收缩",
]

# ──────────────────────────────────────────────
# 否定词（出现在利空词前时，可翻转语义）
# ──────────────────────────────────────────────
NEGATION_WORDS = [
    "不", "无", "没有", "未", "否认", "排除", "澄清", "不存在", "不涉及",
    "不构成", "不影响", "已解除", "已撤销", "已和解",
]


def _has_negation_before(text: str, keyword: str, window: int = 5) -> bool:
    """
    检查 keyword 在 text 中出现时，其前 window 个字符内是否有否定词。
    用于处理"不存在暴雷风险"等语义翻转场景。
    """
    idx = text.find(keyword)
    while idx != -1:
        prefix = text[max(0, idx - window): idx]
        if any(neg in prefix for neg in NEGATION_WORDS):
            return True
        idx = text.find(keyword, idx + 1)
    return False


def _score_text(text: str) -> float:
    """
    对单段文本打分：正词 +0.15，负词 -0.15，归一化到 [-1, 1]。
    支持否定词窗口翻转（如"不存在暴雷风险" → 正向）。
    """
    if not text or not isinstance(text, str):
        return 0.0
    text = re.sub(r"\s+", " ", text)
    pos_score = 0.0
    neg_score = 0.0
    for k in POSITIVE_KEYWORDS:
        if k in text:
            if _has_negation_before(text, k):
                neg_score += 0.1  # 否定利好 → 轻微利空
            else:
                pos_score += 0.15
    for k in NEGATIVE_KEYWORDS:
        if k in text:
            if _has_negation_before(text, k):
                pos_score += 0.1  # 否定利空 → 轻微利好
            else:
                neg_score += 0.15
    raw = pos_score - neg_score
    return max(-1.0, min(1.0, raw))


def score_news_sentiment(df: pd.DataFrame) -> pd.Series:
    """
    对新闻 DataFrame 每行计算情感分数。

    Parameters
    ----------
    df : pd.DataFrame
        需含列 title，可选 content（若无可仅用 title）

    Returns
    -------
    pd.Series
        与 df 同索引，取值为 [-1, 1]。
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)
    scores = []
    for _, row in df.iterrows():
        title = row.get("title") or row.get("新闻标题") or ""
        content = row.get("content") or row.get("新闻内容") or ""
        combined = str(title) + " " + str(content)
        scores.append(_score_text(combined))
    return pd.Series(scores, index=df.index)


def aggregate_sentiment(scores: pd.Series, method: str = "mean") -> float:
    """
    对多篇新闻的情感分数聚合。

    Parameters
    ----------
    scores : pd.Series
        每篇新闻的 score
    method : str
        "mean" | "median" | "max_abs"（取绝对值最大的方向）

    Returns
    -------
    float
        聚合值，范围 [-1, 1]
    """
    if scores is None or len(scores) == 0:
        return 0.0
    s = scores.astype(float).dropna()
    if len(s) == 0:
        return 0.0
    if method == "mean":
        return float(max(-1.0, min(1.0, s.mean())))
    if method == "median":
        return float(max(-1.0, min(1.0, s.median())))
    if method == "max_abs":
        idx = s.abs().idxmax()
        return float(s.loc[idx])
    return float(max(-1.0, min(1.0, s.mean())))
