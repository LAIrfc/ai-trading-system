"""
强势股回踩再启动策略 (Breakout Pullback)

独立选股工具，不参与 ensemble 投票。
三步模型：放量突破新高 → 缩量回踩 → 再次放量上攻

仅依赖 OHLCV 标准六列，零外部 API 调用。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.strategies.base import Strategy, StrategySignal

logger = logging.getLogger(__name__)

BREAKOUT_BUFFER = 0.003
RESTART_BUFFER = 0.003


@dataclass
class BreakoutDetail:
    """突破事件的详细快照"""
    idx: int
    date: str
    close: float
    high: float
    volume: float
    vol_ratio: float
    body_ratio: float
    close_high_ratio: float
    body_center: float


@dataclass
class ScanResult:
    """完整扫描结果，用于 scanner 脚本"""
    symbol: str = ""
    name: str = ""
    score: float = 0.0
    grade: str = ""
    stage: str = ""
    entry_type: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    breakout_date: str = ""
    breakout_price: float = 0.0
    pullback_days: int = 0
    vol_shrink_pct: float = 0.0
    gain_120d: float = 0.0
    liquidity_score: float = 0.0
    entry_triggered: bool = False
    breakout_buffer_pct: float = BREAKOUT_BUFFER
    restart_buffer_pct: float = RESTART_BUFFER
    vwap_pullback: float = 0.0
    risk_flags: List[str] = field(default_factory=list)
    score_detail: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class BreakoutPullbackStrategy(Strategy):

    name = "BREAKOUT_PULLBACK"
    description = "强势股回踩再启动：放量突破60日新高 + 缩量回踩1~3天 + 再次放量上攻"
    min_bars = 120

    def __init__(
        self,
        high_period: int = 60,
        lookback_breakout: int = 5,
        vol_breakout_ratio: float = 1.5,
        close_high_ratio: float = 0.7,
        pullback_days_min: int = 1,
        pullback_days_max: int = 3,
        pullback_vol_ratio: float = 0.7,
        pullback_price_tol: float = 0.03,
        restart_vol_ratio: float = 1.3,
        max_gain_120d_penalty: float = 1.0,
        max_breakout_count: int = 2,
        min_liquidity_yi: float = 1.0,
        body_ratio_min: float = 0.3,
        mode: str = "conservative",
    ):
        self.high_period = high_period
        self.lookback_breakout = lookback_breakout
        self.vol_breakout_ratio = vol_breakout_ratio
        self.close_high_ratio = close_high_ratio
        self.pullback_days_min = pullback_days_min
        self.pullback_days_max = pullback_days_max
        self.pullback_vol_ratio = pullback_vol_ratio
        self.pullback_price_tol = pullback_price_tol
        self.restart_vol_ratio = restart_vol_ratio
        self.max_gain_120d_penalty = max_gain_120d_penalty
        self.max_breakout_count = max_breakout_count
        self.min_liquidity_yi = min_liquidity_yi
        self.body_ratio_min = body_ratio_min
        self.mode = mode
        self.min_bars = max(self.high_period + 10, 30)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        """兼容 Strategy 基类的标准接口"""
        result = self.scan(df)
        if result is None:
            return StrategySignal("HOLD", 0.0, "未触发突破回踩条件")
        conf = min(result.score / 100.0, 1.0)
        return StrategySignal(
            action="BUY",
            confidence=conf,
            reason=f"{result.grade}级信号 | {result.stage} | score={result.score:.0f}",
            position=min(0.3 + conf * 0.4, 0.7),
            indicators=result.to_dict(),
        )

    def scan(self, df: pd.DataFrame, symbol: str = "", name: str = "") -> Optional[ScanResult]:
        """
        完整扫描，返回 ScanResult 或 None。
        scanner 脚本专用入口。
        """
        if len(df) < self.min_bars:
            return None

        df = df.copy().reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(subset=["open", "high", "low", "close", "volume"], inplace=True)
        if len(df) < self.min_bars:
            return None

        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        opn = df["open"].values
        volume = df["volume"].values

        liquidity = self._calc_liquidity(close, volume)
        if liquidity < self.min_liquidity_yi:
            return None

        bk = self._find_breakout(df)
        if bk is None:
            return None

        risk_flags: List[str] = []

        if bk.vol_ratio > 5.0:
            risk_flags.append("abnormal_volume")

        pb = self._check_pullback(df, bk, risk_flags)
        if pb is None:
            return None

        pb_days, pb_avg_vol, pb_low, pb_high, pb_vwap, pb_shrink = pb

        restart_triggered, restart_score = self._check_restart(df, bk, pb_high)

        gain_120d = (close[-1] / close[max(0, len(close) - 120)] - 1.0) if len(close) >= 120 else 0.0

        breakout_count = self._count_breakouts_120d(df)
        if breakout_count > self.max_breakout_count:
            risk_flags.append(f"multi_breakout_{breakout_count}")

        if self._has_long_upper_shadow_on_pullback(df, bk, pb_days):
            risk_flags.append("long_upper_shadow_pullback")

        bk_score = self._score_breakout(bk)
        pb_score = self._score_pullback(pb_shrink, close[-1], bk.close)
        risk_adj = self._score_risk(gain_120d, breakout_count)

        ma5 = pd.Series(close).rolling(5).mean().iloc[-1]
        ma10 = pd.Series(close).rolling(10).mean().iloc[-1]
        ma20 = pd.Series(close).rolling(20).mean().iloc[-1]
        trend_bonus = 5.0 if (ma5 > ma10 > ma20) else 0.0

        if "abnormal_volume" in risk_flags:
            bk_score = min(bk_score, 15.0)

        total = bk_score + pb_score + restart_score + risk_adj + trend_bonus
        total = max(0.0, min(105.0, total))

        if total < 25:
            return None

        if total >= 80:
            grade = "A"
        elif total >= 60:
            grade = "B"
        else:
            grade = "C"

        if restart_triggered:
            stage = "restart"
        elif pb_days >= self.pullback_days_min:
            stage = "ready"
        else:
            stage = "pullback"

        if self.mode == "aggressive":
            entry_type = "aggressive"
            entry_price = round(pb_vwap, 2) if pb_vwap > 0 else round(close[-1], 2)
            entry_triggered = (stage in ("ready", "restart"))
        else:
            entry_type = "conservative"
            entry_price = round(pb_high * (1 + RESTART_BUFFER), 2) if pb_high > 0 else round(close[-1], 2)
            entry_triggered = (stage == "restart")

        stop_loss = round(pb_low * 0.985, 2)

        bk_date = str(df.iloc[bk.idx].get("date", ""))

        return ScanResult(
            symbol=symbol,
            name=name,
            score=round(total, 1),
            grade=grade,
            stage=stage,
            entry_type=entry_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            breakout_date=bk_date,
            breakout_price=round(bk.close, 2),
            pullback_days=pb_days,
            vol_shrink_pct=round(pb_shrink, 4),
            gain_120d=round(gain_120d, 4),
            liquidity_score=round(liquidity, 2),
            entry_triggered=entry_triggered,
            breakout_buffer_pct=BREAKOUT_BUFFER,
            restart_buffer_pct=RESTART_BUFFER,
            vwap_pullback=round(pb_vwap, 2),
            risk_flags=risk_flags,
            score_detail={
                "breakout_quality": round(bk_score, 1),
                "pullback_quality": round(pb_score, 1),
                "restart_signal": round(restart_score, 1),
                "risk_adjust": round(risk_adj, 1),
                "trend_bonus": round(trend_bonus, 1),
            },
        )

    # ------------------------------------------------------------------
    # Step 1: 突破检测
    # ------------------------------------------------------------------

    def _find_breakout(self, df: pd.DataFrame) -> Optional[BreakoutDetail]:
        close = df["close"].values
        high = df["high"].values
        opn = df["open"].values
        volume = df["volume"].values
        low = df["low"].values
        n = len(df)

        vol_ma20 = pd.Series(volume).rolling(20, min_periods=10).mean().values
        vol_max5 = pd.Series(volume).rolling(5, min_periods=3).max().shift(1).values
        ma10_series = pd.Series(close).rolling(10, min_periods=5).mean().values

        prev_high_60 = pd.Series(close).rolling(self.high_period, min_periods=min(30, self.high_period)).max().shift(1).values

        search_start = max(0, n - self.lookback_breakout - self.pullback_days_max)
        search_end = n - 1

        best_bk = None
        for i in range(search_end, search_start - 1, -1):
            if np.isnan(prev_high_60[i]) or np.isnan(vol_ma20[i]):
                continue

            threshold = prev_high_60[i] * (1 + BREAKOUT_BUFFER)
            if close[i] <= threshold:
                continue

            if high[i] <= 0 or close[i] / high[i] < self.close_high_ratio:
                continue

            if vol_ma20[i] <= 0 or volume[i] < self.vol_breakout_ratio * vol_ma20[i]:
                continue

            if not np.isnan(vol_max5[i]) and vol_max5[i] > 0:
                if volume[i] < vol_max5[i]:
                    continue

            if volume[i] <= 0:
                continue

            # 前10日内不能跌破MA10
            pre10_start = max(0, i - 10)
            ma10_broken = False
            for k in range(pre10_start, i):
                if not np.isnan(ma10_series[k]) and close[k] < ma10_series[k]:
                    ma10_broken = True
                    break
            if ma10_broken:
                continue

            # 突破日量能必须比前10日内最大阴线量多2/3
            max_green_vol = 0.0
            for k in range(pre10_start, i):
                if close[k] < opn[k] and volume[k] > max_green_vol:
                    max_green_vol = volume[k]
            if max_green_vol > 0 and volume[i] < max_green_vol * (1 + 2.0 / 3.0):
                continue

            # 突破日及前2天（共3天窗口）内必须有一根涨幅>=8%的大阳线
            has_big_yang = False
            for k in range(max(0, i - 2), i + 1):
                prev_c = close[k - 1] if k > 0 else opn[k]
                if prev_c > 0 and (close[k] / prev_c - 1.0) >= 0.08:
                    has_big_yang = True
                    break
            if not has_big_yang:
                continue

            body = close[i] - opn[i]
            hl_range = high[i] - low[i]
            if body <= 0:
                continue
            body_ratio = body / (hl_range + 1e-9)
            if body_ratio < self.body_ratio_min:
                continue

            close_high_ratio = close[i] / high[i]
            body_center = (opn[i] + close[i]) / 2.0
            vol_ratio = volume[i] / vol_ma20[i] if vol_ma20[i] > 0 else 0

            bk = BreakoutDetail(
                idx=i, date="", close=close[i], high=high[i],
                volume=volume[i], vol_ratio=vol_ratio,
                body_ratio=body_ratio, close_high_ratio=close_high_ratio,
                body_center=body_center,
            )
            remaining = n - 1 - i
            if remaining >= self.pullback_days_min:
                best_bk = bk
                break

        return best_bk

    # ------------------------------------------------------------------
    # Step 2: 回踩检测
    # ------------------------------------------------------------------

    def _check_pullback(self, df: pd.DataFrame, bk: BreakoutDetail,
                        risk_flags: List[str]):
        close = df["close"].values
        opn = df["open"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values
        n = len(df)

        pb_start = bk.idx + 1
        pb_end = min(bk.idx + 1 + self.pullback_days_max, n)
        if pb_start >= n:
            return None

        actual_pb_days = 0
        pb_vol_sum = 0.0
        pb_low = float("inf")
        pb_high = -float("inf")
        pb_vwap_num = 0.0
        pb_vwap_den = 0.0
        has_down_day = False

        ma5_series = pd.Series(close).rolling(5, min_periods=3).mean().values

        for j in range(pb_start, pb_end):
            prev_close = close[j - 1]
            daily_change_pct = (close[j] / prev_close - 1.0) if prev_close > 0 else 0
            if abs(daily_change_pct) > 0.05:
                break

            if daily_change_pct < -0.095:
                return None

            if close[j] < opn[j] and volume[j] > bk.volume:
                return None

            if close[j] < bk.body_center:
                risk_flags.append("below_body_center")
                break

            if not np.isnan(ma5_series[j]) and close[j] < ma5_series[j]:
                return None

            if daily_change_pct < 0 or close[j] < opn[j]:
                has_down_day = True

            actual_pb_days += 1
            pb_vol_sum += volume[j]
            pb_low = min(pb_low, low[j])
            pb_high = max(pb_high, high[j])
            typical = (high[j] + low[j] + close[j]) / 3.0
            pb_vwap_num += typical * volume[j]
            pb_vwap_den += volume[j]

        if actual_pb_days < self.pullback_days_min:
            return None

        if not has_down_day:
            return None

        pb_last_close = close[pb_start + actual_pb_days - 1]
        if pb_last_close >= bk.close * 1.03:
            return None

        price_drop = (pb_last_close / bk.close - 1.0) if bk.close > 0 else 0
        if price_drop < -self.pullback_price_tol:
            return None

        pb_avg_vol = pb_vol_sum / actual_pb_days if actual_pb_days > 0 else 0
        pb_shrink = 1.0 - (pb_avg_vol / bk.volume) if bk.volume > 0 else 0

        if pb_avg_vol > bk.volume * self.pullback_vol_ratio:
            if pb_shrink < 0.1:
                return None

        pb_vwap = pb_vwap_num / pb_vwap_den if pb_vwap_den > 0 else 0
        if pb_vwap_den < bk.volume * 0.2:
            pb_vwap = close[pb_start + actual_pb_days - 1]

        return (actual_pb_days, pb_avg_vol, pb_low, pb_high, pb_vwap, pb_shrink)

    # ------------------------------------------------------------------
    # Step 3: 再启动检测
    # ------------------------------------------------------------------

    def _check_restart(self, df: pd.DataFrame, bk: BreakoutDetail,
                       pb_high: float) -> tuple:
        close = df["close"].values
        opn = df["open"].values
        volume = df["volume"].values
        n = len(df)

        vol_ma20 = pd.Series(volume).rolling(20, min_periods=10).mean().values

        last = n - 1
        is_bullish = close[last] > opn[last]

        vol_ok = False
        if not np.isnan(vol_ma20[last]) and vol_ma20[last] > 0:
            pb_start = bk.idx + 1
            pb_end = min(bk.idx + 1 + self.pullback_days_max, n - 1)
            pb_avg_vol = np.mean(volume[pb_start:pb_end]) if pb_end > pb_start else vol_ma20[last]
            threshold = max(
                self.restart_vol_ratio * pb_avg_vol,
                0.8 * bk.volume,
            )
            vol_ok = volume[last] >= threshold

        restart_threshold = pb_high * (1 + RESTART_BUFFER) if pb_high > 0 else 0
        price_ok = close[last] > restart_threshold

        if is_bullish and vol_ok and price_ok:
            return True, 20.0

        if is_bullish and (vol_ok or price_ok):
            return False, 10.0

        return False, 0.0

    # ------------------------------------------------------------------
    # 评分
    # ------------------------------------------------------------------

    def _score_breakout(self, bk: BreakoutDetail) -> float:
        vol_score = min(bk.vol_ratio / 3.0, 1.0) * 15.0
        body_score = min(bk.body_ratio / 0.6, 1.0) * 7.0
        pos_score = bk.close_high_ratio * 8.0
        return vol_score + body_score + pos_score

    def _score_pullback(self, shrink_pct: float, last_close: float,
                        bk_close: float) -> float:
        shrink_score = max(0.0, shrink_pct) * 15.0
        shrink_score = min(shrink_score, 15.0)

        drop_pct = (bk_close - last_close) / bk_close if bk_close > 0 else 0
        if drop_pct <= 0:
            price_score = 15.0
        elif drop_pct <= 0.03:
            price_score = 10.0
        elif drop_pct <= 0.05:
            price_score = 5.0
        else:
            price_score = 0.0

        return shrink_score + price_score

    def _score_risk(self, gain_120d: float, breakout_count: int) -> float:
        adj = 0.0
        if gain_120d <= 0.5:
            adj += 5.0
        elif gain_120d > self.max_gain_120d_penalty:
            adj -= 10.0

        if breakout_count > self.max_breakout_count:
            adj -= 10.0

        return adj

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _calc_liquidity(self, close: np.ndarray, volume: np.ndarray) -> float:
        if len(close) < 20:
            return 0.0
        amount_20 = (close[-20:] * volume[-20:]).mean()
        return amount_20 / 1e8

    def _count_breakouts_120d(self, df: pd.DataFrame) -> int:
        """统计独立突破事件数。要求两次突破之间有 >=3% 的回落，排除趋势延续误判。"""
        close = df["close"].values
        n = len(close)
        start = max(0, n - 120)
        segment = close[start:]
        if len(segment) < 30:
            return 0

        prev_high = pd.Series(segment).rolling(self.high_period, min_periods=min(20, self.high_period)).max().shift(1).values
        count = 0
        last_bk_high = 0.0
        had_pullback = True

        for i in range(len(segment)):
            if not np.isnan(prev_high[i]) and segment[i] > prev_high[i] * (1 + BREAKOUT_BUFFER):
                if had_pullback:
                    count += 1
                    last_bk_high = segment[i]
                    had_pullback = False
                else:
                    last_bk_high = max(last_bk_high, segment[i])
            elif last_bk_high > 0 and segment[i] < last_bk_high * 0.97:
                had_pullback = True

        return count

    def _has_long_upper_shadow_on_pullback(self, df: pd.DataFrame,
                                           bk: BreakoutDetail,
                                           pb_days: int) -> bool:
        high = df["high"].values
        close = df["close"].values
        opn = df["open"].values
        volume = df["volume"].values

        for j in range(bk.idx + 1, min(bk.idx + 1 + pb_days, len(df))):
            body_top = max(close[j], opn[j])
            body_bot = min(close[j], opn[j])
            body = body_top - body_bot
            upper_shadow = high[j] - body_top
            if body > 0 and upper_shadow / body > 1.5 and volume[j] > bk.volume * 0.8:
                return True
        return False
