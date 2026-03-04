"""
新闻源权重（V3.3）

从 config/news_source_weights.yaml 加载；匹配逻辑：来源字符串与 names 中任一匹配（包含或相等）取对应 weight，否则 default。
"""

import logging
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

_DEFAULT_WEIGHT = 1.0
_LOADED: Dict[str, float] = {}  # name_lower_or_substr -> weight
_LOADED_DEFAULT = _DEFAULT_WEIGHT


def _load_config() -> None:
    global _LOADED, _LOADED_DEFAULT
    if _LOADED:
        return
    try:
        import yaml
        config_dir = Path(__file__).resolve().parents[2].parent / "config"
        path = config_dir / "news_source_weights.yaml"
        if not path.exists():
            path = Path("config/news_source_weights.yaml")
        if not path.exists():
            _LOADED_DEFAULT = _DEFAULT_WEIGHT
            return
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            return
        _LOADED_DEFAULT = float(data.get("default", _DEFAULT_WEIGHT))
        for item in data.get("sources") or []:
            w = float(item.get("weight", 1.0))
            for name in item.get("names") or []:
                if name:
                    _LOADED[name.strip()] = w
    except Exception as e:
        logger.debug("加载新闻源权重失败: %s", e)
        _LOADED_DEFAULT = _DEFAULT_WEIGHT


def get_source_weight(source_name: str) -> float:
    """
    根据来源名称返回权重。匹配规则：source_name 包含某 names 项或与之相等即命中。
    """
    _load_config()
    if not source_name or not isinstance(source_name, str):
        return _LOADED_DEFAULT
    s = str(source_name).strip()
    for name, w in _LOADED.items():
        if name in s or s in name:
            return w
    return _LOADED_DEFAULT
