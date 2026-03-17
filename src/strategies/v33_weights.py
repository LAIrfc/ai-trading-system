"""
V3.3 组合动态权重（Phase 5.2–5.4，已同步至 11 策略 Ensemble）

- 基准权重 1/N；市场状态（沪深300 ADX(14)、HV20）判定震荡/趋势，乘数表调节。
- 归一化两步法：先乘乘数再归一化，截断 [0.5%, 30%]，多出/不足按比例再分配。
- 调整触发与冷却：状态变化或 ADX/HV20 日环比连续 3 日超阈值则调整，调整后 7 日冷却。

策略名与 EnsembleStrategy 保持一致（11 策略）：
  技术面: MA MACD RSI BOLL KDJ DUAL
  基本面: PE PB PEPB
  消息面: NEWS
  资金面: MONEY_FLOW
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 进程级沪深300指数缓存：{ symbol -> (fetch_date_str, DataFrame) }
_INDEX_CACHE: Dict[str, tuple] = {}

# 市场状态判定：趋势市 ADX>25 且 HV20<30%
ADX_TREND_THRESHOLD = 25
HV20_TREND_MAX = 0.30  # 30%
# 日环比触发：连续 3 日 ADX 或 HV20 日环比变化超过此值则允许触发调整（与昨日差）
DAY_CHANGE_ADX = 1.0
DAY_CHANGE_HV20 = 0.02  # 2%
COOLDOWN_DAYS = 7

# 策略名列表（与 EnsembleStrategy 保持一致，11 策略）
V33_STRATEGY_NAMES = [
    "MA", "MACD", "RSI", "BOLL", "KDJ", "DUAL",  # 技术面
    "PE", "PB", "PEPB",                            # 基本面
    "NEWS", "MONEY_FLOW",                          # 消息面 + 资金面
]
TECH_NAMES = {"MA", "MACD", "RSI", "BOLL", "KDJ", "DUAL"}
FUNDAMENTAL_NAMES = {"PE", "PB", "PEPB"}
ALT_DATA_NAMES = {"NEWS", "MONEY_FLOW"}

# 乘数表
# 震荡市（range）：技术指标噪音大，降权 0.8；消息/资金面更有效，升权 1.2；基本面中性
# 趋势市（trend）：技术指标有效，恢复 1.0；消息面顺势加权 1.2；资金面龙虎榜更活跃 1.2；基本面中性
MULTIPLIER_RANGE: dict = {}
MULTIPLIER_TREND: dict = {}
for _s in V33_STRATEGY_NAMES:
    if _s in TECH_NAMES:
        MULTIPLIER_RANGE[_s] = 0.8   # 震荡市技术面降权
        MULTIPLIER_TREND[_s] = 1.0   # 趋势市技术面恢复
    elif _s in FUNDAMENTAL_NAMES:
        MULTIPLIER_RANGE[_s] = 1.1   # 震荡市基本面略升（价值回归）
        MULTIPLIER_TREND[_s] = 0.9   # 趋势市基本面略降（动量主导）
    elif _s == "NEWS":
        MULTIPLIER_RANGE[_s] = 1.2   # 震荡市消息面更有效
        MULTIPLIER_TREND[_s] = 1.2   # 趋势市消息面顺势加分
    elif _s == "MONEY_FLOW":
        MULTIPLIER_RANGE[_s] = 1.0   # 震荡市资金面中性
        MULTIPLIER_TREND[_s] = 1.2   # 趋势市龙虎榜更活跃
    else:
        MULTIPLIER_RANGE[_s] = 1.0
        MULTIPLIER_TREND[_s] = 1.0

MIN_WEIGHT_PCT = 0.005
MAX_WEIGHT_PCT = 0.30


def _adx_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ADX(period) 序列。"""
    if len(close) < period + 10:
        return pd.Series(dtype=float)
    tr = pd.Series(index=close.index, dtype=float)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    for i in range(1, len(close)):
        tr.iloc[i] = max(
            high.iloc[i] - low.iloc[i],
            abs(high.iloc[i] - close.iloc[i - 1]),
            abs(low.iloc[i] - close.iloc[i - 1]),
        )
    plus_dm = pd.Series(0.0, index=close.index)
    minus_dm = pd.Series(0.0, index=close.index)
    for i in range(1, len(close)):
        up = high.iloc[i] - high.iloc[i - 1]
        down = low.iloc[i - 1] - low.iloc[i]
        if up > down and up > 0:
            plus_dm.iloc[i] = up
        if down > up and down > 0:
            minus_dm.iloc[i] = down
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * (plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan))
    minus_di = 100.0 * (minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan))
    dx = 100.0 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan))
    return dx.ewm(alpha=alpha, adjust=False).mean()


def _hv20_series(close: pd.Series, window: int = 20) -> pd.Series:
    """20 日收益年化波动率（小数）。"""
    ret = close.pct_change()
    return ret.rolling(window, min_periods=5).std() * np.sqrt(252)


def fetch_index_for_state(symbol: str = "000300", days: int = 60) -> Optional[pd.DataFrame]:
    """获取沪深300近期日线用于 ADX/HV20。列需含 date, high, low, close。当天内结果缓存复用。"""
    today = datetime.now().strftime("%Y%m%d")
    cache_key = f"{symbol}_{days}"
    cached = _INDEX_CACHE.get(cache_key)
    if cached and cached[0] == today:
        return cached[1]
    try:
        import akshare as ak
        end = today
        start = (datetime.now() - timedelta(days=days + 20)).strftime("%Y%m%d")
        df = ak.stock_zh_index_hist_csindex(symbol=symbol, start_date=start, end_date=end)
        if df is None or len(df) < 30:
            return None
        df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low"})
        df["date"] = pd.to_datetime(df["date"])
        for c in ["high", "low", "close"]:
            if c not in df.columns:
                df[c] = df["close"]
        df["high"] = pd.to_numeric(df["high"], errors="coerce").fillna(df["close"])
        df["low"] = pd.to_numeric(df["low"], errors="coerce").fillna(df["close"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        result = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        _INDEX_CACHE[cache_key] = (today, result)
        return result
    except Exception as e:
        logger.debug("fetch_index_for_state 失败: %s", e)
        return None


def get_market_state(index_df: pd.DataFrame) -> str:
    """
    根据 ADX(14) 与 HV20 判定：趋势市 ADX>25 且 HV20<30% 为 'trend'，否则 'range'。
    """
    if index_df is None or len(index_df) < 30:
        return "range"
    close = index_df["close"].astype(float)
    high = index_df["high"].astype(float) if "high" in index_df.columns else close
    low = index_df["low"].astype(float) if "low" in index_df.columns else close
    adx = _adx_series(high, low, close, 14)
    hv = _hv20_series(close, 20)
    if len(adx) < 1 or len(hv) < 1 or pd.isna(adx.iloc[-1]) or pd.isna(hv.iloc[-1]):
        return "range"
    a, h = float(adx.iloc[-1]), float(hv.iloc[-1])
    if a > ADX_TREND_THRESHOLD and h < HV20_TREND_MAX:
        return "trend"
    return "range"


def should_trigger_adjustment(
    index_df: pd.DataFrame,
    last_state: Optional[str] = None,
) -> bool:
    """
    是否触发调整：状态与上次不同，或 ADX/HV20 日环比连续 3 日超阈值。
    若 last_state 为 None 或 index_df 不足则返回 True（首次或默认调整）。
    """
    if index_df is None or len(index_df) < 25:
        return last_state is None
    current = get_market_state(index_df)
    if last_state is not None and current != last_state:
        return True
    close = index_df["close"].astype(float)
    high = index_df["high"].astype(float) if "high" in index_df.columns else close
    low = index_df["low"].astype(float) if "low" in index_df.columns else close
    adx = _adx_series(high, low, close, 14)
    hv = _hv20_series(close, 20)
    if len(adx) < 4 or len(hv) < 4:
        return last_state is None
    adx_d = adx.diff().abs()
    hv_d = hv.diff().abs()
    for i in range(-3, 0):
        if adx_d.iloc[i] >= DAY_CHANGE_ADX or hv_d.iloc[i] >= DAY_CHANGE_HV20:
            continue
        return last_state is None
    return True


def base_weights() -> Dict[str, float]:
    """
    基准权重（基于 v3 回测结果，与 EnsembleStrategy 默认权重一致）。
    动态权重模块在此基础上乘以市场状态乘数，再归一化。
    """
    raw = {
        "BOLL":       1.5,
        "MACD":       1.3,
        "KDJ":        1.1,
        "MA":         1.0,
        "DUAL":       0.9,
        "RSI":        0.8,
        "PEPB":       0.8,
        "PE":         0.6,
        "PB":         0.6,
        "NEWS":       0.5,
        "MONEY_FLOW": 0.4,
    }
    total = sum(raw.values())
    return {s: raw[s] / total for s in V33_STRATEGY_NAMES}


def apply_multipliers(weights: Dict[str, float], state: str) -> Dict[str, float]:
    """乘数表：state in ('trend','range')。"""
    mult = MULTIPLIER_TREND if state == "trend" else MULTIPLIER_RANGE
    return {s: weights.get(s, 1.0 / len(V33_STRATEGY_NAMES)) * mult.get(s, 1.0) for s in V33_STRATEGY_NAMES}


def normalize_two_step(
    weights: Dict[str, float],
    min_pct: float = MIN_WEIGHT_PCT,
    max_pct: float = MAX_WEIGHT_PCT,
) -> Tuple[Dict[str, float], bool]:
    """
    归一化两步法：先归一化到和为 1，再截断 [min_pct, max_pct]，再按比例分配使和为 1。
    Returns (weights, was_truncated).
    """
    total = sum(weights.values())
    if total <= 0:
        n = len(weights)
        return {s: 1.0 / n for s in weights}, False
    w = {s: weights[s] / total for s in weights}
    truncated = {}
    for s in w:
        truncated[s] = max(min_pct, min(max_pct, w[s]))
    was_truncated = any(truncated[s] != w[s] for s in w)
    s_sum = sum(truncated.values())
    if s_sum <= 0:
        return w, was_truncated
    if abs(s_sum - 1.0) > 1e-6:
        for s in truncated:
            truncated[s] = truncated[s] / s_sum
        if was_truncated:
            logger.info("V33 权重归一化两步法：截断后再分配，和=%.4f", sum(truncated.values()))
    return truncated, was_truncated


def compute_v33_weights(
    index_df: Optional[pd.DataFrame] = None,
    last_state: Optional[str] = None,
    last_adjustment_date: Optional[datetime] = None,
    as_of_date: Optional[datetime] = None,
) -> Tuple[Dict[str, float], str, Optional[datetime]]:
    """
    计算 V33 动态权重（含市场状态与两步法归一化）。
    Returns (weights_dict, current_state, adjustment_date_if_done).
    """
    as_of = as_of_date or datetime.now()
    state = "range"
    if index_df is not None and len(index_df) >= 25:
        state = get_market_state(index_df)
    base = base_weights()
    w = apply_multipliers(base, state)
    w, _ = normalize_two_step(w)
    return w, state, as_of
