"""
每日 API 调用限制管理器 (跨所有 mx_skills 共享)

使用本地文件持久化当日计数，进程重启不丢失。
"""

import json
import os
import threading
from datetime import date
from pathlib import Path
from typing import Optional


class MXRateLimiter:
    DAILY_LIMIT = 300

    def __init__(self, state_dir: Optional[str] = None):
        if state_dir is None:
            project_root = Path(__file__).resolve().parents[4]
            state_dir = str(project_root / "mydate" / ".mx_state")
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._state_dir / "rate_limit.json"
        self._lock = threading.Lock()
        self._today: str = ""
        self._count: int = 0
        self._load()

    def _load(self):
        today_str = date.today().isoformat()
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                if data.get("date") == today_str:
                    self._count = data.get("count", 0)
                    self._today = today_str
                    return
            except (json.JSONDecodeError, OSError):
                pass
        self._today = today_str
        self._count = 0
        self._save()

    def _save(self):
        try:
            self._state_file.write_text(
                json.dumps({"date": self._today, "count": self._count}),
                encoding="utf-8",
            )
        except OSError:
            pass

    @property
    def remaining(self) -> int:
        with self._lock:
            self._maybe_reset()
            return max(0, self.DAILY_LIMIT - self._count)

    @property
    def used(self) -> int:
        with self._lock:
            self._maybe_reset()
            return self._count

    def _maybe_reset(self):
        today_str = date.today().isoformat()
        if self._today != today_str:
            self._today = today_str
            self._count = 0
            self._save()

    def acquire(self, n: int = 1) -> bool:
        """Try to acquire n API call slots. Returns False if would exceed limit."""
        with self._lock:
            self._maybe_reset()
            if self._count + n > self.DAILY_LIMIT:
                return False
            self._count += n
            self._save()
            return True

    def force_consume(self, n: int = 1):
        """Record n calls without checking limit (for post-hoc accounting)."""
        with self._lock:
            self._maybe_reset()
            self._count += n
            self._save()

    def status(self) -> dict:
        with self._lock:
            self._maybe_reset()
            return {
                "date": self._today,
                "used": self._count,
                "remaining": max(0, self.DAILY_LIMIT - self._count),
                "limit": self.DAILY_LIMIT,
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
