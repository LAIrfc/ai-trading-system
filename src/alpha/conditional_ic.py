"""
Conditional IC Learning（按市场状态分桶IC）

IC不再是标量：按regime分桶计算，置信区间加权，EWMA衰减平滑，防塌陷clip。
用于动态调整因子预期收益率的权重。
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, List, Tuple


class ConditionalICUpdater:
    """
    按市场状态分桶的 IC 学习器

    三个桶（bear/mid/bull）各自独立维护 IC，
    根据当前 regime_prob 插值得到最终 IC。
    """

    REGIME_BOUNDS = {'bear': (0.0, 0.3), 'mid': (0.3, 0.7), 'bull': (0.7, 1.0)}
    BUCKET_NAMES = list(REGIME_BOUNDS.keys())

    def __init__(self, half_life: int = 20, max_history: int = 200,
                 min_samples: int = 10, ic_floor: float = 0.05,
                 ic_cap: float = 0.30, default_ic: float = 0.15,
                 persist_path: Optional[str] = None):
        self.decay = 0.5 ** (1.0 / half_life)
        self.max_history = max_history
        self.min_samples = min_samples
        self.ic_floor = ic_floor
        self.ic_cap = ic_cap
        self.default_ic = default_ic
        self.persist_path = persist_path

        self.buckets: Dict[str, List[Tuple[float, float]]] = {
            b: [] for b in self.BUCKET_NAMES
        }
        self.ic_ewma: Dict[str, Optional[float]] = {
            b: None for b in self.BUCKET_NAMES
        }

        if persist_path and os.path.exists(persist_path):
            self._load(persist_path)

    def _regime_to_bucket(self, regime_prob: float) -> str:
        for bucket, (lo, hi) in self.REGIME_BOUNDS.items():
            if lo <= regime_prob < hi:
                return bucket
        return 'bull'

    def add_observation(self, signal: float, future_return: float,
                        regime_prob: float) -> None:
        bucket = self._regime_to_bucket(regime_prob)
        self.buckets[bucket].append((signal, future_return))
        if len(self.buckets[bucket]) > self.max_history:
            self.buckets[bucket] = self.buckets[bucket][-self.max_history:]

    def add_batch(self, signals: np.ndarray, returns: np.ndarray,
                  regime_prob: float) -> None:
        bucket = self._regime_to_bucket(regime_prob)
        for s, r in zip(signals, returns):
            if np.isfinite(s) and np.isfinite(r):
                self.buckets[bucket].append((float(s), float(r)))
        if len(self.buckets[bucket]) > self.max_history:
            self.buckets[bucket] = self.buckets[bucket][-self.max_history:]

    def _update_bucket_ic(self, bucket: str) -> None:
        obs = self.buckets[bucket]
        if len(obs) < self.min_samples:
            return
        signals = np.array([s for s, _ in obs])
        rets = np.array([r for _, r in obs])
        if signals.std() < 1e-10 or rets.std() < 1e-10:
            return

        ic_instant = np.corrcoef(signals, rets)[0, 1]
        if not np.isfinite(ic_instant):
            return

        if self.ic_ewma[bucket] is None:
            self.ic_ewma[bucket] = ic_instant
        else:
            self.ic_ewma[bucket] = (self.decay * self.ic_ewma[bucket]
                                    + (1 - self.decay) * ic_instant)

        confidence = min(1.0, len(obs) / 100.0)
        blended = self.ic_ewma[bucket] * confidence + self.default_ic * (1 - confidence)
        self.ic_ewma[bucket] = np.clip(blended, self.ic_floor, self.ic_cap)

    def update_all(self) -> None:
        for bucket in self.BUCKET_NAMES:
            self._update_bucket_ic(bucket)

    def get_ic(self, regime_prob: float) -> float:
        """根据当前 regime_prob 插值获取 IC"""
        regime_prob = np.clip(regime_prob, 0.0, 1.0)

        if regime_prob <= 0.3:
            t = regime_prob / 0.3
            weights = {'bear': 1 - t, 'mid': t, 'bull': 0.0}
        elif regime_prob <= 0.7:
            t = (regime_prob - 0.3) / 0.4
            weights = {'bear': 0.0, 'mid': 1 - t, 'bull': t}
        else:
            weights = {'bear': 0.0, 'mid': 0.0, 'bull': 1.0}

        ic = sum(
            weights[b] * (self.ic_ewma[b] if self.ic_ewma[b] is not None else self.default_ic)
            for b in self.BUCKET_NAMES
        )
        return np.clip(ic, self.ic_floor, self.ic_cap)

    def get_bucket_status(self) -> Dict[str, dict]:
        status = {}
        for b in self.BUCKET_NAMES:
            status[b] = {
                'samples': len(self.buckets[b]),
                'ic_ewma': self.ic_ewma[b],
                'confidence': min(1.0, len(self.buckets[b]) / 100.0)
            }
        return status

    def save(self, path: Optional[str] = None) -> None:
        path = path or self.persist_path
        if path is None:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            'timestamp': datetime.now().isoformat(),
            'ic_ewma': {k: v for k, v in self.ic_ewma.items()},
            'bucket_sizes': {b: len(self.buckets[b]) for b in self.BUCKET_NAMES},
            'buckets': {b: obs[-50:] for b, obs in self.buckets.items()}
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def _load(self, path: str) -> None:
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            for b in self.BUCKET_NAMES:
                if b in data.get('ic_ewma', {}):
                    self.ic_ewma[b] = data['ic_ewma'][b]
                if b in data.get('buckets', {}):
                    self.buckets[b] = [(s, r) for s, r in data['buckets'][b]]
        except Exception:
            pass


def regime_prob_from_score(regime_score: float) -> float:
    """将 regime_score ∈ [-1, 1] 映射为 regime_prob ∈ [0, 1]"""
    return (regime_score + 1.0) / 2.0
