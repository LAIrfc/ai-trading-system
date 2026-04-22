"""
利润质量因子模块

区分"真实业绩拐点"和"一次性财技利润"：
  - 归母净利润 vs 扣非净利润
  - 经营现金流 vs 利润
  - 毛利率变化 vs 收入变化
  - 一次性收益占比
  - 主营收入增速 vs 投资收益增速

评分公式：
  利润质量 = 0.4×扣非净利增速得分
           + 0.2×经营现金流覆盖率得分
           + 0.2×毛利率变化得分
           + 0.1×ROE变化得分
           - 0.1×一次性收益占比惩罚

返回 ProfitQualityResult，包含得分(0-1)、评级(A/B/C/D)、各维度详情。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ProfitQualityResult:
    score: float  # 0.0 ~ 1.0
    grade: str  # A/B/C/D
    deducted_growth: Optional[float] = None  # 扣非净利增速%
    net_growth: Optional[float] = None  # 归母净利增速%
    revenue_growth: Optional[float] = None  # 营收增速%
    ocf_coverage: Optional[float] = None  # 经营现金流/净利润
    gross_margin_delta: Optional[float] = None  # 毛利率变化(pct)
    roe_delta: Optional[float] = None  # ROE变化(pct)
    nonrecurring_ratio: Optional[float] = None  # 一次性收益占净利润比例
    warnings: list = field(default_factory=list)
    details: Dict[str, float] = field(default_factory=dict)

    @property
    def is_reliable(self) -> bool:
        return self.grade in ("A", "B")


def _safe_growth(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None:
        return None
    if previous == 0:
        return None if current == 0 else (100.0 if current > 0 else -100.0)
    return (current - previous) / abs(previous) * 100.0


def _score_growth(growth: Optional[float]) -> float:
    if growth is None:
        return 0.5
    return float(np.clip(np.tanh(growth / 100.0) * 0.5 + 0.5, 0.0, 1.0))


def _score_ocf_coverage(ratio: Optional[float]) -> float:
    if ratio is None:
        return 0.5
    if ratio >= 1.0:
        return min(1.0, 0.7 + 0.3 * min(ratio, 3.0) / 3.0)
    if ratio >= 0.5:
        return 0.5 + 0.2 * (ratio - 0.5) / 0.5
    if ratio >= 0:
        return 0.3 + 0.2 * ratio / 0.5
    return max(0.0, 0.3 + 0.3 * ratio)


def _score_gm_delta(delta: Optional[float]) -> float:
    if delta is None:
        return 0.5
    return float(np.clip(0.5 + delta / 20.0, 0.0, 1.0))


def _score_roe_delta(delta: Optional[float]) -> float:
    if delta is None:
        return 0.5
    return float(np.clip(0.5 + delta / 10.0, 0.0, 1.0))


def _penalize_nonrecurring(ratio: Optional[float]) -> float:
    if ratio is None:
        return 0.0
    ratio_abs = abs(ratio)
    if ratio_abs <= 0.2:
        return 0.0
    if ratio_abs <= 0.5:
        return (ratio_abs - 0.2) / 0.3 * 0.3
    return min(1.0, 0.3 + (ratio_abs - 0.5) * 1.4)


def compute_profit_quality(
    net_profit: Optional[float] = None,
    net_profit_prev: Optional[float] = None,
    deducted_profit: Optional[float] = None,
    deducted_profit_prev: Optional[float] = None,
    revenue: Optional[float] = None,
    revenue_prev: Optional[float] = None,
    operating_cashflow: Optional[float] = None,
    gross_margin: Optional[float] = None,
    gross_margin_prev: Optional[float] = None,
    roe: Optional[float] = None,
    roe_prev: Optional[float] = None,
    nonrecurring_income: Optional[float] = None,
) -> ProfitQualityResult:
    """
    计算利润质量综合评分。

    所有参数可选，缺失的维度取中性分(0.5)。

    Args:
        net_profit / net_profit_prev: 当期/上期归母净利润(元)
        deducted_profit / deducted_profit_prev: 当期/上期扣非净利润(元)
        revenue / revenue_prev: 当期/上期营业收入(元)
        operating_cashflow: 当期经营活动现金流净额(元)
        gross_margin / gross_margin_prev: 当期/上期毛利率(%)
        roe / roe_prev: 当期/上期ROE(%)
        nonrecurring_income: 非经常性损益(元)

    Returns:
        ProfitQualityResult
    """
    warnings = []

    net_growth = _safe_growth(net_profit, net_profit_prev)
    deducted_growth = _safe_growth(deducted_profit, deducted_profit_prev)
    revenue_growth = _safe_growth(revenue, revenue_prev)
    gm_delta = (gross_margin - gross_margin_prev) if (
        gross_margin is not None and gross_margin_prev is not None
    ) else None
    roe_delta = (roe - roe_prev) if (
        roe is not None and roe_prev is not None
    ) else None

    ocf_coverage = None
    if operating_cashflow is not None and net_profit is not None and net_profit != 0:
        ocf_coverage = operating_cashflow / abs(net_profit)

    nonrecurring_ratio = None
    if nonrecurring_income is not None and net_profit is not None and net_profit != 0:
        nonrecurring_ratio = nonrecurring_income / abs(net_profit)

    # ── 警告检测 ──
    if net_growth is not None and deducted_growth is not None:
        gap = net_growth - deducted_growth
        if gap > 50:
            warnings.append(
                f"⚠ 归母增速({net_growth:+.0f}%)远高于扣非增速({deducted_growth:+.0f}%)，"
                f"差距{gap:.0f}pct，可能含大额非经常性收益"
            )
    if deducted_profit is not None and deducted_profit < 0 and net_profit is not None and net_profit > 0:
        warnings.append("⚠ 扣非净利为负但归母为正，利润完全依赖非经常性损益")
    if net_growth is not None and revenue_growth is not None:
        if net_growth > 100 and revenue_growth < 10:
            warnings.append(
                f"⚠ 利润暴增({net_growth:+.0f}%)但营收几乎没增({revenue_growth:+.0f}%)，"
                "利润增长可能非主营驱动"
            )
    if ocf_coverage is not None and ocf_coverage < 0.3 and net_profit is not None and net_profit > 0:
        warnings.append(
            f"⚠ 经营现金流覆盖率仅{ocf_coverage:.1%}，利润含金量低"
        )
    if nonrecurring_ratio is not None and nonrecurring_ratio > 0.5:
        warnings.append(
            f"⚠ 一次性收益占净利润{nonrecurring_ratio:.0%}，利润不可持续"
        )

    # ── 评分 ──
    s_deducted = _score_growth(deducted_growth)
    s_ocf = _score_ocf_coverage(ocf_coverage)
    s_gm = _score_gm_delta(gm_delta)
    s_roe = _score_roe_delta(roe_delta)
    p_nr = _penalize_nonrecurring(nonrecurring_ratio)

    raw_score = (
        0.40 * s_deducted
        + 0.20 * s_ocf
        + 0.20 * s_gm
        + 0.10 * s_roe
        - 0.10 * p_nr
    )
    score = float(np.clip(raw_score, 0.0, 1.0))

    if score >= 0.7:
        grade = "A"
    elif score >= 0.5:
        grade = "B"
    elif score >= 0.3:
        grade = "C"
    else:
        grade = "D"

    return ProfitQualityResult(
        score=round(score, 4),
        grade=grade,
        deducted_growth=round(deducted_growth, 2) if deducted_growth is not None else None,
        net_growth=round(net_growth, 2) if net_growth is not None else None,
        revenue_growth=round(revenue_growth, 2) if revenue_growth is not None else None,
        ocf_coverage=round(ocf_coverage, 4) if ocf_coverage is not None else None,
        gross_margin_delta=round(gm_delta, 2) if gm_delta is not None else None,
        roe_delta=round(roe_delta, 2) if roe_delta is not None else None,
        nonrecurring_ratio=round(nonrecurring_ratio, 4) if nonrecurring_ratio is not None else None,
        warnings=warnings,
        details={
            "score_deducted_growth": round(s_deducted, 4),
            "score_ocf_coverage": round(s_ocf, 4),
            "score_gross_margin": round(s_gm, 4),
            "score_roe": round(s_roe, 4),
            "penalty_nonrecurring": round(p_nr, 4),
        },
    )
