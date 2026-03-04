"""
龙虎榜席位匹配与权重（V3.3）

- 同一席位：营业部全称去后缀后取前 10 字（或「证券」之后部分），并结合别名表标准化。
- 无标签席位默认权重 1.0；机构专用/基金/社保/养老金等可配置为 >1.2 以满足龙虎榜信号条件。
"""

import csv
import logging
import re
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 机构席位数值权重（>1.2 才满足龙虎榜“机构权重>1.2”条件）
INSTITUTION_KEYWORDS = ["机构专用", "基金", "社保", "养老金", "QFII", "北向"]
DEFAULT_WEIGHT = 1.0
INSTITUTION_WEIGHT = 1.2

_alias_to_standard: Dict[str, str] = {}
_standard_weights: Dict[str, float] = {}


def _load_seat_alias() -> None:
    global _alias_to_standard, _standard_weights
    if _standard_weights:
        return
    try:
        for base in [Path(__file__).resolve().parents[2].parent / "config", Path("config")]:
            path = base / "seat_alias.csv"
            if path.exists():
                break
        else:
            return
        with open(path, "r", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                standard = (row.get("标准席位名称") or "").strip()
                alias_str = (row.get("别名") or "").strip()
                if not standard:
                    continue
                _standard_weights[standard] = INSTITUTION_WEIGHT if any(k in standard for k in INSTITUTION_KEYWORDS) else 1.0
                for a in re.split(r"[,，、]", alias_str):
                    a = a.strip()
                    if a:
                        _alias_to_standard[a] = standard
    except Exception as e:
        logger.debug("加载席位别名失败: %s", e)


def normalize_seat_name(full_name: str) -> str:
    """
    营业部全称标准化：去「营业部」等后缀，取前 10 字；若含「证券」则取「证券」之后部分再取前 10 字。
    """
    if not full_name or not isinstance(full_name, str):
        return ""
    s = full_name.strip()
    for suffix in ["营业部", "证券营业部", "分公司"]:
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    if "证券" in s:
        idx = s.find("证券")
        s = s[idx + 2 :].strip()
    return s[:10] if len(s) > 10 else s


def get_seat_weight(seat_name: str) -> float:
    """
    席位权重。无标签或未在别名表中命中则返回 1.0；机构席返回 1.2；别名表可扩展为带权重的 CSV。
    """
    _load_seat_alias()
    if not seat_name or not isinstance(seat_name, str):
        return DEFAULT_WEIGHT
    s = seat_name.strip()
    key = normalize_seat_name(s)
    if any(k in s for k in INSTITUTION_KEYWORDS):
        return INSTITUTION_WEIGHT
    standard = _alias_to_standard.get(key) or _alias_to_standard.get(s)
    if standard:
        return _standard_weights.get(standard, DEFAULT_WEIGHT)
    return DEFAULT_WEIGHT
