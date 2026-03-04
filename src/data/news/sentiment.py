"""
新闻情感打分（关键词规则版）

对标题+摘要/正文做简单情感打分，范围 -1（利空）～ 1（利好）。
后续可替换为预训练 NLP 模型。
"""

import re
from typing import Union

import pandas as pd


# 利好相关词（出现则正向加分）
POSITIVE_KEYWORDS = [
    "利好", "大涨", "涨停", "突破", "创新高", "业绩预增", "扭亏", "中标", "签约",
    "回购", "增持", "分红", "扩产", "投产", "获批", "通过", "合作", "战略合作",
    "订单", "超预期", "增长", "净利润增", "营收增", "产能", "景气",
]

# 利空相关词（出现则负向加分）
NEGATIVE_KEYWORDS = [
    "利空", "大跌", "跌停", "亏损", "暴雷", "减持", "违规", "立案", "调查",
    "处罚", "风险", "预警", "下滑", "不及预期", "爆仓", "违约", "诉讼",
    "停产", "停产整顿", "退市", "ST", "商誉减值", "业绩变脸",
]


def _score_text(text: str) -> float:
    """
    对单段文本打分：正词 +1/词数，负词 -1/词数，归一化到 [-1, 1]。
    若正负都有，按加权差再 clip。
    """
    if not text or not isinstance(text, str):
        return 0.0
    text = re.sub(r"\s+", " ", text)
    pos_count = sum(1 for k in POSITIVE_KEYWORDS if k in text)
    neg_count = sum(1 for k in NEGATIVE_KEYWORDS if k in text)
    # 简单线性：每词 ±0.15，上限 ±1
    raw = pos_count * 0.15 - neg_count * 0.15
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
