"""
每日 API 调用限制管理器 — 按 skill 独立计数。

妙想各 skill 有独立配额：
  - mx-search (资讯搜索):  300 次/天
  - mx-data   (金融数据):  300 次/天
  - mx-xuangu (智能选股):  300 次/天
  - mx-moni   (模拟组合):  3000 次/天
  - mx-zixuan (自选股):    500 次/天

使用本地文件持久化当日计数，进程重启不丢失。
"""

import json
import os
import threading
from datetime import date
from pathlib import Path
from typing import Dict, Optional


SKILL_LIMITS: Dict[str, int] = {
    "mx-search": 300,
    "mx-data": 300,
    "mx-xuangu": 300,
    "mx-moni": 3000,
    "mx-zixuan": 500,
}

DEFAULT_SKILL = "mx-data"


class MXRateLimiter:
    DAILY_LIMIT = 300  # legacy fallback

    def __init__(self, state_dir: Optional[str] = None):
        if state_dir is None:
            project_root = Path(__file__).resolve().parents[4]
            state_dir = str(project_root / "mydate" / ".mx_state")
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._state_dir / "rate_limit.json"
        self._lock = threading.Lock()
        self._today: str = ""
        self._counts: Dict[str, int] = {}
        self._load()

    def _load(self):
        today_str = date.today().isoformat()
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                if data.get("date") == today_str:
                    raw = data.get("counts", {})
                    if isinstance(raw, dict):
                        self._counts = {k: int(v) for k, v in raw.items()}
                    elif isinstance(data.get("count"), int):
                        self._counts = {DEFAULT_SKILL: data["count"]}
                    else:
                        self._counts = {}
                    self._today = today_str
                    return
            except (json.JSONDecodeError, OSError):
                pass
        self._today = today_str
        self._counts = {}
        self._save()

    def _save(self):
        total = sum(self._counts.values())
        try:
            self._state_file.write_text(
                json.dumps({
                    "date": self._today,
                    "counts": self._counts,
                    "count": total,
                }),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _maybe_reset(self):
        today_str = date.today().isoformat()
        if self._today != today_str:
            self._today = today_str
            self._counts = {}
            self._save()

    def _get_limit(self, skill: str) -> int:
        return SKILL_LIMITS.get(skill, self.DAILY_LIMIT)

    def _get_count(self, skill: str) -> int:
        return self._counts.get(skill, 0)

    @property
    def remaining(self) -> int:
        """Legacy: returns remaining for DEFAULT_SKILL."""
        return self.remaining_for(DEFAULT_SKILL)

    @property
    def used(self) -> int:
        """Legacy: returns total used across all skills."""
        with self._lock:
            self._maybe_reset()
            return sum(self._counts.values())

    def remaining_for(self, skill: str) -> int:
        with self._lock:
            self._maybe_reset()
            limit = self._get_limit(skill)
            used = self._get_count(skill)
            return max(0, limit - used)

    def acquire(self, n: int = 1, skill: str = DEFAULT_SKILL) -> bool:
        with self._lock:
            self._maybe_reset()
            limit = self._get_limit(skill)
            used = self._get_count(skill)
            if used + n > limit:
                return False
            self._counts[skill] = used + n
            self._save()
            return True

    def force_consume(self, n: int = 1, skill: str = DEFAULT_SKILL):
        with self._lock:
            self._maybe_reset()
            self._counts[skill] = self._get_count(skill) + n
            self._save()

    def status(self) -> dict:
        with self._lock:
            self._maybe_reset()
            total_used = sum(self._counts.values())
            total_limit = sum(SKILL_LIMITS.values())
            per_skill = {}
            for sk, lim in SKILL_LIMITS.items():
                u = self._get_count(sk)
                per_skill[sk] = {"used": u, "limit": lim, "remaining": max(0, lim - u)}
            return {
                "date": self._today,
                "used": total_used,
                "remaining": max(0, total_limit - total_used),
                "limit": total_limit,
                "skills": per_skill,
            }


_global_limiter: Optional[MXRateLimiter] = None
_init_lock = threading.Lock()


def get_rate_limiter() -> MXRateLimiter:
    global _global_limiter
    if _global_limiter is None:
        with _init_lock:
            if _global_limiter is None:
                _global_limiter = MXRateLimiter()
    return _global_limiter
