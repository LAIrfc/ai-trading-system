"""
全局 Baostock 熔断器 — 进程级单例

任何使用 baostock 的模块应先调用 `is_fused()` 判断是否已熔断。
连接失败时调用 `record_fail()` 累计计数，连续 N 次失败后自动熔断，
后续所有调用方直接跳过，避免反复超时。
"""

import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_consecutive_fails = 0
_FUSE_THRESHOLD = 3
_fused = False


def is_fused() -> bool:
    return _fused


def record_fail(context: str = ""):
    global _consecutive_fails, _fused
    with _lock:
        _consecutive_fails += 1
        if _consecutive_fails >= _FUSE_THRESHOLD and not _fused:
            _fused = True
            logger.warning(
                "⚡ Baostock 全局熔断：连续 %d 次失败 (%s)，后续全部跳过",
                _consecutive_fails,
                context,
            )


def record_success():
    global _consecutive_fails, _fused
    with _lock:
        _consecutive_fails = 0
        _fused = False
