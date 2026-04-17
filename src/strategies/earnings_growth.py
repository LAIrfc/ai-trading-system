"""
业绩增速策略

多源数据融合：
1. stock_yjyg_em  业绩预告（预增/扭亏等定性分类 + 业绩变动幅度）
2. stock_yjbb_em  业绩报表（一季报/半年报/三季报 实际净利润同比增速）

决策优先级：
- 最新季报实际数据 > 业绩预告 > 同行业景气度外推
- 4月看Q1实际 + 年报预告；7-8月看Q2实际 + 半年报预告；以此类推

同一报告期全市场数据在进程内按日期缓存，避免逐股重复请求。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from .base import Strategy, StrategySignal

logger = logging.getLogger(__name__)

# 报告期 YYYYMMDD -> {'forecast_df': DataFrame, 'timestamp': float}
_earnings_cache: Dict[str, Dict[str, Any]] = {}
# 业绩报表缓存（季报实际数据）
_report_cache: Dict[str, Dict[str, Any]] = {}


def _normalize_a_share_code(symbol: Optional[str]) -> str:
    if not symbol:
        return ""
    digits = "".join(c for c in str(symbol).strip() if c.isdigit())
    if not digits:
        return ""
    if len(digits) >= 6:
        return digits[-6:]
    return digits.zfill(6)


def _forecast_report_date(when: Optional[datetime] = None) -> str:
    """业绩预告(stock_yjyg_em)的报告期参数。"""
    dt = when or datetime.now()
    y, m = dt.year, dt.month
    if m <= 4:
        return f"{y - 1}1231"
    if m <= 8:
        return f"{y}0630"
    if m <= 10:
        return f"{y}0930"
    return f"{y}1231"


def _quarterly_report_date(when: Optional[datetime] = None) -> str:
    """
    最新季报(stock_yjbb_em)的报告期参数。
    4月看当年Q1(0331)；7-8月看当年Q2(0630)；10月看当年Q3(0930)；1-3月看上年Q3(0930)。
    """
    dt = when or datetime.now()
    y, m = dt.year, dt.month
    if 4 <= m <= 6:
        return f"{y}0331"
    if 7 <= m <= 9:
        return f"{y}0630"
    if 10 <= m <= 12:
        return f"{y}0930"
    return f"{y - 1}0930"


def _report_date_yyyymmdd(when: Optional[datetime] = None) -> str:
    """向后兼容：返回预告报告期。"""
    return _forecast_report_date(when)


def _fetch_forecast_df_cached(report_date: str) -> pd.DataFrame:
    """按报告期拉取全市场预告表，同日期只请求一次。"""
    entry = _earnings_cache.get(report_date)
    if entry is not None:
        return entry["forecast_df"]
    try:
        import akshare as ak  # type: ignore
    except ImportError as e:
        logger.warning("[业绩增速] 未安装 akshare: %s", e)
        empty = pd.DataFrame()
        _earnings_cache[report_date] = {"forecast_df": empty, "timestamp": time.time()}
        return empty
    try:
        raw = ak.stock_yjyg_em(date=report_date)
    except Exception as e:
        logger.warning("[业绩增速] stock_yjyg_em(%s) 失败: %s", report_date, e)
        raise
    if raw is None:
        raw = pd.DataFrame()
    _earnings_cache[report_date] = {"forecast_df": raw, "timestamp": time.time()}
    return raw


def _fetch_quarterly_df_cached(report_date: str) -> pd.DataFrame:
    """按报告期拉取全市场季报业绩报表，同日期只请求一次。"""
    entry = _report_cache.get(report_date)
    if entry is not None:
        return entry["report_df"]
    try:
        import akshare as ak  # type: ignore
    except ImportError as e:
        logger.warning("[业绩增速] 未安装 akshare: %s", e)
        empty = pd.DataFrame()
        _report_cache[report_date] = {"report_df": empty, "timestamp": time.time()}
        return empty
    try:
        raw = ak.stock_yjbb_em(date=report_date)
    except Exception as e:
        logger.warning("[业绩增速] stock_yjbb_em(%s) 失败: %s", report_date, e)
        raw = pd.DataFrame()
    if raw is None:
        raw = pd.DataFrame()
    _report_cache[report_date] = {"report_df": raw, "timestamp": time.time()}
    return raw


def _code_series(forecast_df: pd.DataFrame) -> pd.Series:
    col = "股票代码" if "股票代码" in forecast_df.columns else None
    if col is None:
        return pd.Series(dtype=str)
    return forecast_df[col].astype(str).str.replace(r"\D", "", regex=True).str[-6:].str.zfill(6)


def _pick_forecast_row(forecast_df: pd.DataFrame, code: str) -> Optional[pd.Series]:
    if forecast_df is None or forecast_df.empty or not code:
        return None
    try:
        codes = _code_series(forecast_df)
        m = codes == code
        if not m.any():
            return None
        sub = forecast_df.loc[m].copy()
        if "公告日期" in sub.columns:
            sub["_ad"] = pd.to_datetime(sub["公告日期"], errors="coerce")
            sub = sub.sort_values("_ad", ascending=False, na_position="last")
        return sub.iloc[0]
    except Exception as e:
        logger.warning("[业绩增速] 匹配行失败 code=%s: %s", code, e)
        return None


def _parse_change_pct(row: pd.Series) -> Optional[float]:
    if "业绩变动幅度" not in row.index:
        return None
    v = pd.to_numeric(row.get("业绩变动幅度"), errors="coerce")
    if pd.isna(v):
        return None
    return float(v)


def _build_reason(
    label: str,
    ftype: str,
    pct: Optional[float],
    code: str,
    stock_name: str,
    report_date: str,
) -> str:
    parts = [label]
    if stock_name:
        parts.append(f"{stock_name}({code})")
    else:
        parts.append(code)
    parts.append(f"预告类型:{ftype}")
    if pct is not None:
        parts.append(f"业绩变动幅度:{pct:.2f}%")
    parts.append(f"报告期:{report_date}")
    return "；".join(parts)


def _signal_from_row(
    row: pd.Series,
    code: str,
    stock_name: str,
    report_date: str,
) -> StrategySignal:
    ftype = str(row.get("预告类型", "") or "").strip()
    pct = _parse_change_pct(row)
    short_name = str(row.get("股票简称", "") or "").strip()

    def _ind(action: str, conf: float, pos: float, label: str) -> StrategySignal:
        display_name = stock_name or short_name
        return StrategySignal(
            action=action,
            confidence=round(conf, 2),
            reason=_build_reason(label, ftype, pct, code, display_name, report_date),
            position=round(pos, 2),
            indicators={
                "earnings_forecast_type": ftype,
                "earnings_change_pct": None if pct is None else round(pct, 4),
                "earnings_report_date": report_date,
                "symbol": code,
            },
        )

    if ftype == "预增":
        if pct is not None and pct > 100:
            return _ind("BUY", 0.9, 0.78, "预增高增速")
        if pct is not None and pct >= 50:
            return _ind("BUY", 0.7, 0.62, "预增中等增速")
        return _ind("BUY", 0.5, 0.55, "预增或增速未披露/低于50%")

    if ftype == "略增":
        return _ind("BUY", 0.5, 0.55, "略增")

    if ftype == "续盈":
        return StrategySignal(
            action="HOLD",
            confidence=0.35,
            reason=_build_reason("续盈观望", ftype, pct, code, stock_name or short_name, report_date),
            position=0.5,
            indicators={
                "earnings_forecast_type": ftype,
                "earnings_change_pct": None if pct is None else round(pct, 4),
                "earnings_report_date": report_date,
                "symbol": code,
            },
        )

    if ftype == "略减":
        return _ind("SELL", 0.4, 0.42, "略减")

    if ftype in ("预减", "首亏"):
        return _ind("SELL", 0.8, 0.22, "预减/首亏")

    if ftype == "扭亏":
        return _ind("BUY", 0.72, 0.65, "扭亏")
    if ftype == "减亏":
        return _ind("BUY", 0.5, 0.55, "减亏")
    if ftype == "增亏":
        return _ind("SELL", 0.75, 0.25, "增亏")
    if ftype == "续亏":
        return _ind("SELL", 0.65, 0.28, "续亏")
    if ftype == "不确定":
        return StrategySignal(
            action="HOLD",
            confidence=0.25,
            reason=_build_reason("预告不确定", ftype, pct, code, stock_name or short_name, report_date),
            position=0.5,
            indicators={
                "earnings_forecast_type": ftype,
                "earnings_change_pct": None if pct is None else round(pct, 4),
                "earnings_report_date": report_date,
                "symbol": code,
            },
        )

    logger.warning("[业绩增速] 未覆盖的预告类型: %s code=%s", ftype, code)
    return StrategySignal(
        action="HOLD",
        confidence=0.3,
        reason=_build_reason("未知预告类型", ftype or "—", pct, code, stock_name or short_name, report_date),
        position=0.5,
        indicators={
            "earnings_forecast_type": ftype,
            "earnings_change_pct": None if pct is None else round(pct, 4),
            "earnings_report_date": report_date,
            "symbol": code,
        },
    )


# ── 季报实际数据信号 ──────────────────────────────────────

def _pick_quarterly_row(report_df: pd.DataFrame, code: str) -> Optional[pd.Series]:
    """从业绩报表中按代码匹配行。"""
    if report_df is None or report_df.empty or not code:
        return None
    try:
        codes = _code_series(report_df)
        m = codes == code
        if not m.any():
            return None
        sub = report_df.loc[m].copy()
        if "最新公告日期" in sub.columns:
            sub["_ad"] = pd.to_datetime(sub["最新公告日期"], errors="coerce")
            sub = sub.sort_values("_ad", ascending=False, na_position="last")
        return sub.iloc[0]
    except Exception as e:
        logger.warning("[业绩增速] 季报匹配行失败 code=%s: %s", code, e)
        return None


def _signal_from_quarterly(
    row: pd.Series,
    code: str,
    stock_name: str,
    report_date: str,
) -> Optional[StrategySignal]:
    """从业绩报表实际数据生成信号。净利润同比增速为核心指标。"""
    growth_col = "净利润同比增长"
    if growth_col not in row.index:
        return None
    growth = pd.to_numeric(row.get(growth_col), errors="coerce")
    if pd.isna(growth):
        return None
    growth_pct = float(growth)

    short_name = str(row.get("股票简称", "") or "").strip()
    display_name = stock_name or short_name

    def _mk(action: str, conf: float, pos: float, label: str) -> StrategySignal:
        reason_parts = [label]
        if display_name:
            reason_parts.append(f"{display_name}({code})")
        else:
            reason_parts.append(code)
        reason_parts.append(f"净利润同比:{growth_pct:+.1f}%")
        reason_parts.append(f"报告期:{report_date}(季报实际)")
        return StrategySignal(
            action=action,
            confidence=round(conf, 2),
            reason="；".join(reason_parts),
            position=round(pos, 2),
            indicators={
                "earnings_data_source": "quarterly_report",
                "earnings_net_profit_yoy": round(growth_pct, 2),
                "earnings_report_date": report_date,
                "symbol": code,
            },
        )

    if growth_pct > 100:
        return _mk("BUY", 0.92, 0.80, "季报高增速")
    if growth_pct > 50:
        return _mk("BUY", 0.78, 0.68, "季报中等增速")
    if growth_pct > 20:
        return _mk("BUY", 0.60, 0.58, "季报稳健增长")
    if growth_pct > 0:
        return _mk("BUY", 0.45, 0.52, "季报正增长")
    if growth_pct > -20:
        return _mk("HOLD", 0.35, 0.48, "季报小幅下滑")
    if growth_pct > -50:
        return _mk("SELL", 0.55, 0.35, "季报显著下滑")
    return _mk("SELL", 0.80, 0.20, "季报大幅下滑")


# ── 行业景气度外推 ──────────────────────────────────────

def _compute_sector_q_prosperity(
    report_df: pd.DataFrame,
    sector_codes: set,
) -> Optional[float]:
    """
    基于同行业已披露季报的公司净利润同比，计算行业景气度得分 [-1, 1]。
    正值=同行普遍业绩向好；负值=同行普遍业绩下滑。
    返回 None 表示数据不足。
    """
    if report_df is None or report_df.empty or not sector_codes:
        return None
    codes = _code_series(report_df)
    report_df_copy = report_df.copy()
    report_df_copy["_norm_code"] = codes
    mask = report_df_copy["_norm_code"].isin(sector_codes)
    sec_rows = report_df_copy[mask]
    if len(sec_rows) < 3:
        return None

    growth_col = "净利润同比增长"
    if growth_col not in sec_rows.columns:
        return None
    growths = pd.to_numeric(sec_rows[growth_col], errors="coerce").dropna()
    if len(growths) < 3:
        return None

    import numpy as _np
    avg = float(growths.mean())
    positive_ratio = float((growths > 0).sum()) / len(growths)
    score = float(_np.clip(
        0.5 * _np.tanh(avg / 50.0) + 0.5 * (positive_ratio - 0.5),
        -1.0, 1.0
    ))
    return score


class EarningsGrowthStrategy(Strategy):
    """
    多源业绩增速评估策略。

    优先级：季报实际 > 业绩预告 > 同行业景气度外推。
    """

    name = "业绩增速"
    description = "多源业绩增速评估（季报实际+预告+行业景气外推）"
    min_bars = 1

    def __init__(self, symbol: Optional[str] = None, stock_name: str = "",
                 sector_codes: Optional[set] = None, **kwargs):
        self.symbol = symbol
        self.stock_name = stock_name
        self.sector_codes = sector_codes

    def analyze(self, df: pd.DataFrame, **kwargs) -> StrategySignal:
        from .base import _BACKTEST_ACTIVE

        _ = df
        symbol = kwargs.get("symbol", self.symbol)
        stock_name = str(kwargs.get("stock_name", self.stock_name) or "")

        code = _normalize_a_share_code(symbol if symbol is not None else None)
        if not code:
            return StrategySignal(
                action="HOLD",
                confidence=0.0,
                reason="未披露（缺少股票代码）",
                position=0.5,
                indicators={"earnings_change_pct": None, "symbol": None},
            )

        if _BACKTEST_ACTIVE:
            return StrategySignal(
                action="HOLD",
                confidence=0.0,
                reason="回测中跳过业绩预告拉取",
                position=0.5,
                indicators={"earnings_change_pct": None, "symbol": code},
            )

        # ── 优先级1: 尝试季报实际数据 ──
        q_date = _quarterly_report_date()
        q_signal = self._try_quarterly(code, stock_name, q_date)
        if q_signal is not None:
            return q_signal

        # ── 优先级2: 业绩预告 ──
        forecast_date = _forecast_report_date()
        forecast_signal = self._try_forecast(code, stock_name, forecast_date)
        if forecast_signal is not None:
            return forecast_signal

        # ── 优先级3: 同行业季报景气度外推 ──
        sector_codes = kwargs.get("sector_codes", self.sector_codes)
        if sector_codes:
            prosperity_signal = self._try_sector_prosperity(
                code, stock_name, q_date, sector_codes
            )
            if prosperity_signal is not None:
                return prosperity_signal

        return StrategySignal(
            action="HOLD",
            confidence=0.0,
            reason="未披露（本报告期预告及季报均无该股数据）",
            position=0.5,
            indicators={
                "earnings_change_pct": None,
                "symbol": code,
                "earnings_report_date": forecast_date,
            },
        )

    def _try_quarterly(self, code: str, stock_name: str,
                       q_date: str) -> Optional[StrategySignal]:
        try:
            report_df = _fetch_quarterly_df_cached(q_date)
        except Exception:
            return None
        if report_df is None or report_df.empty:
            return None
        row = _pick_quarterly_row(report_df, code)
        if row is None:
            return None
        return _signal_from_quarterly(row, code, stock_name, q_date)

    def _try_forecast(self, code: str, stock_name: str,
                      forecast_date: str) -> Optional[StrategySignal]:
        try:
            forecast_df = _fetch_forecast_df_cached(forecast_date)
        except Exception:
            logger.warning("[业绩增速] 获取预告数据失败 symbol=%s", code, exc_info=True)
            return None
        if forecast_df is None or forecast_df.empty:
            return None
        row = _pick_forecast_row(forecast_df, code)
        if row is None:
            return None
        return _signal_from_row(row, code, stock_name, forecast_date)

    def _try_sector_prosperity(self, code: str, stock_name: str,
                               q_date: str,
                               sector_codes: set) -> Optional[StrategySignal]:
        """同行业景气度外推：用已披露季报的同行数据推断未披露个股。"""
        try:
            report_df = _fetch_quarterly_df_cached(q_date)
        except Exception:
            return None
        prosperity = _compute_sector_q_prosperity(report_df, sector_codes)
        if prosperity is None:
            return None

        display_name = stock_name or code
        disclosed_count = 0
        if report_df is not None and not report_df.empty:
            codes = _code_series(report_df)
            report_copy = report_df.copy()
            report_copy["_norm_code"] = codes
            disclosed_count = int(report_copy["_norm_code"].isin(sector_codes).sum())

        if prosperity > 0.3:
            action, conf, pos, label = "BUY", 0.50, 0.55, "同行季报景气外推(看好)"
        elif prosperity > 0.1:
            action, conf, pos, label = "BUY", 0.35, 0.52, "同行季报景气外推(偏好)"
        elif prosperity > -0.1:
            action, conf, pos, label = "HOLD", 0.25, 0.50, "同行季报景气外推(中性)"
        elif prosperity > -0.3:
            action, conf, pos, label = "SELL", 0.35, 0.42, "同行季报景气外推(偏弱)"
        else:
            action, conf, pos, label = "SELL", 0.50, 0.30, "同行季报景气外推(看淡)"

        reason = (
            f"{label}；{display_name}({code})；"
            f"同行已披露{disclosed_count}/{len(sector_codes)}家；"
            f"景气度得分:{prosperity:+.2f}；报告期:{q_date}"
        )
        return StrategySignal(
            action=action,
            confidence=round(conf, 2),
            reason=reason,
            position=round(pos, 2),
            indicators={
                "earnings_data_source": "sector_prosperity_extrapolation",
                "sector_prosperity_score": round(prosperity, 4),
                "sector_disclosed_count": disclosed_count,
                "sector_total_count": len(sector_codes),
                "earnings_report_date": q_date,
                "symbol": code,
            },
        )


_industry_prosperity_cache: Dict[str, Dict[str, Any]] = {}


def get_industry_prosperity(sector_stocks: Dict[str, list]) -> Dict[str, dict]:
    """
    计算行业景气度：融合季报实际数据 + 业绩预告。

    季报实际净利润同比优先；预告作为补充。

    Args:
        sector_stocks: {sector_name: [{"code": "300xxx", "name": "..."}]}

    Returns:
        {sector_name: {
            "avg_growth_pct": float,
            "positive_ratio": float,
            "disclosed": int,
            "total": int,
            "prosperity_score": float (0-1),
            "data_sources": list[str],
        }}
    """
    import numpy as _np

    q_date = _quarterly_report_date()
    f_date = _forecast_report_date()
    cache_key = f"{q_date}_{f_date}"
    if cache_key in _industry_prosperity_cache:
        return _industry_prosperity_cache[cache_key]

    try:
        q_df = _fetch_quarterly_df_cached(q_date)
    except Exception:
        q_df = pd.DataFrame()
    try:
        f_df = _fetch_forecast_df_cached(f_date)
    except Exception:
        f_df = pd.DataFrame()

    q_codes = _code_series(q_df) if q_df is not None and not q_df.empty else pd.Series(dtype=str)
    f_codes = _code_series(f_df) if f_df is not None and not f_df.empty else pd.Series(dtype=str)

    if q_df is not None and not q_df.empty:
        q_df = q_df.copy()
        q_df["_norm_code"] = q_codes
    if f_df is not None and not f_df.empty:
        f_df = f_df.copy()
        f_df["_norm_code"] = f_codes

    good_types = {"预增", "略增", "扭亏", "续盈", "减亏"}

    result = {}
    for sec_name, stocks in sector_stocks.items():
        sec_codes = set()
        for s in stocks:
            c = s.get("code", "")
            if c:
                sec_codes.add(c.zfill(6))
        if not sec_codes:
            continue

        total = len(sec_codes)
        growths = []
        data_sources = []

        # 优先季报实际数据
        if q_df is not None and not q_df.empty:
            mask = q_df["_norm_code"].isin(sec_codes)
            sec_q = q_df[mask]
            if len(sec_q) > 0 and "净利润同比增长" in sec_q.columns:
                g = pd.to_numeric(sec_q["净利润同比增长"], errors="coerce").dropna()
                growths.extend(g.tolist())
                if len(g) > 0:
                    data_sources.append("quarterly_report")

        # 补充预告数据（仅覆盖季报中未出现的股票）
        if f_df is not None and not f_df.empty:
            covered = set()
            if q_df is not None and not q_df.empty:
                covered = set(q_df.loc[q_df["_norm_code"].isin(sec_codes), "_norm_code"])
            uncovered = sec_codes - covered
            if uncovered:
                mask = f_df["_norm_code"].isin(uncovered)
                sec_f = f_df[mask]
                if len(sec_f) > 0:
                    pcts = pd.to_numeric(
                        sec_f.get("业绩变动幅度", pd.Series(dtype=float)),
                        errors="coerce",
                    ).dropna()
                    growths.extend(pcts.tolist())
                    if len(pcts) > 0:
                        data_sources.append("forecast")

        disclosed = len(growths)
        if disclosed == 0:
            result[sec_name] = {
                "avg_growth_pct": 0.0, "positive_ratio": 0.0,
                "disclosed": 0, "total": total, "prosperity_score": 0.0,
                "data_sources": [],
            }
            continue

        arr = _np.array(growths)
        avg_pct = float(arr.mean())
        pos_ratio = float((arr > 0).sum()) / len(arr)
        score = float(_np.clip(
            0.4 * pos_ratio + 0.6 * _np.tanh(avg_pct / 100.0),
            0.0, 1.0,
        ))

        result[sec_name] = {
            "avg_growth_pct": round(avg_pct, 2),
            "positive_ratio": round(pos_ratio, 4),
            "disclosed": disclosed,
            "total": total,
            "prosperity_score": round(score, 4),
            "data_sources": data_sources,
        }

    _industry_prosperity_cache[cache_key] = result
    return result
