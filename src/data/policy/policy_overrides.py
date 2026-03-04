"""
政策标签人工覆盖（V3.3 Phase 6.4）

从 config/policy_overrides.yaml 读取覆盖表；策略/数据层对单条政策先查覆盖再回退自动标注。
修正次日生效，不追溯历史；键为政策唯一标识（如 date_title_hash）。
"""

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_OVERRIDES: Dict[str, Dict[str, Any]] = {}
_LOADED = False


def policy_id_from_row(date_str: str, title: str) -> str:
    """生成政策唯一标识：日期 + 标题哈希前 8 位。"""
    raw = f"{date_str}_{title}"
    return f"{date_str}_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:8]}"


def _load_overrides() -> None:
    global _OVERRIDES, _LOADED
    if _LOADED:
        return
    try:
        import yaml
        for base in [Path(__file__).resolve().parents[2].parent / "config", Path("config")]:
            path = base / "policy_overrides.yaml"
            if path.exists():
                break
        else:
            _LOADED = True
            return
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _OVERRIDES = (data or {}).get("overrides") or {}
        _OVERRIDES = {str(k): v for k, v in _OVERRIDES.items() if v is not None}
        _LOADED = True
    except Exception as e:
        logger.debug("加载 policy_overrides 失败: %s", e)
        _LOADED = True


def get_policy_override(policy_id: str) -> Optional[Dict[str, Any]]:
    """
    按政策 ID 获取人工覆盖标签。返回 None 表示无覆盖，使用自动标注。
    返回 dict 时含 direction（利好/利空/中性）、influence（0.8~1.2）等。
    """
    _load_overrides()
    return _OVERRIDES.get(policy_id)


def score_from_override(override: Dict[str, Any]) -> float:
    """将 direction 转为情感分数 [-1, 1]。"""
    d = (override.get("direction") or "").strip()
    if "利好" in d or d == "利好":
        return 0.6
    if "利空" in d or d == "利空":
        return -0.6
    return 0.0


def influence_from_override(override: Dict[str, Any]) -> float:
    """从覆盖取 influence，缺省 1.0。"""
    return float(override.get("influence", 1.0))
