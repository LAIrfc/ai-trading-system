"""
通用缓存（文档 3.3）：键含 data_type、source、symbol、date_range、params_hash；
支持内存 + 可选本地文件；定期清理过期。
"""

import hashlib
import json
import logging
import os
import time
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 默认内存 TTL（秒）；日频至次日 0 点可在外层按日期判断
DEFAULT_TTL_SECONDS = 86400
# 文件缓存根目录，空则仅内存
CACHE_ROOT: Optional[str] = None
# 内存缓存: key_str -> (value, ts)
_memory: dict = {}
# 最大内存条数，超出时清理最旧
MAX_MEMORY_ENTRIES = 500


def _make_key(
    data_type: str,
    source: str,
    symbol: str = "",
    date_range: str = "",
    params: Optional[dict] = None,
) -> str:
    """生成缓存键；params 会做 hash。"""
    h = hashlib.sha256(
        json.dumps(params or {}, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    return f"{data_type}|{source}|{symbol}|{date_range}|{h}"


def get_cached(
    key: str,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    use_file: bool = True,
) -> Optional[Any]:
    """
    先查内存，再查文件（若 CACHE_ROOT 且 use_file）。
    返回 None 表示未命中或已过期。DataFrame 会从 parquet 还原。
    """
    now = time.time()
    if key in _memory:
        val, ts = _memory[key]
        if now - ts <= ttl_seconds:
            return val
        del _memory[key]
    if use_file and CACHE_ROOT:
        path = os.path.join(CACHE_ROOT, key.replace("|", "_") + ".parquet")
        if os.path.isfile(path):
            try:
                if os.path.getmtime(path) + ttl_seconds >= now:
                    df = pd.read_parquet(path)
                    _memory[key] = (df, now)
                    _trim_memory()
                    return df
            except Exception as e:
                logger.debug("缓存读文件失败 %s: %s", key, e)
    return None


def set_cached(
    key: str,
    value: Any,
    use_file: bool = True,
) -> None:
    """写入内存；若 value 为 DataFrame 且 CACHE_ROOT 且 use_file 则落盘。"""
    now = time.time()
    _memory[key] = (value, now)
    _trim_memory()
    if use_file and CACHE_ROOT and isinstance(value, pd.DataFrame):
        path = os.path.join(CACHE_ROOT, key.replace("|", "_") + ".parquet")
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            value.to_parquet(path, index=False)
        except Exception as e:
            logger.debug("缓存写文件失败 %s: %s", key, e)


def _trim_memory() -> None:
    """保留最近 MAX_MEMORY_ENTRIES 条。"""
    global _memory
    if len(_memory) <= MAX_MEMORY_ENTRIES:
        return
    by_ts = sorted(_memory.items(), key=lambda x: x[1][1])
    for k, _ in by_ts[: len(_memory) - MAX_MEMORY_ENTRIES]:
        del _memory[k]


def clear_expired_file_cache(max_age_seconds: float = 86400 * 7) -> int:
    """
    清理过期文件缓存（按 mtime）。返回删除文件数。
    """
    if not CACHE_ROOT or not os.path.isdir(CACHE_ROOT):
        return 0
    now = time.time()
    removed = 0
    for f in os.listdir(CACHE_ROOT):
        if not f.endswith(".parquet"):
            continue
        path = os.path.join(CACHE_ROOT, f)
        if os.path.isfile(path) and (now - os.path.getmtime(path)) > max_age_seconds:
            try:
                os.remove(path)
                removed += 1
            except Exception as e:
                logger.debug("清理缓存文件失败 %s: %s", path, e)
    return removed


def set_cache_root(root: Optional[str]) -> None:
    """设置文件缓存根目录；None 表示仅内存。"""
    global CACHE_ROOT
    CACHE_ROOT = root
