"""
统一数据接入层：DataProvider + 适配器，屏蔽底层接口差异。

- 策略/回测/采集器仅调用 get_kline(symbol, start_date, end_date) 或 get_kline(symbol, datalen=...)。
- 主备顺序由 config/data_sources.yaml 的 kline.sources 或 config/trading_config.yaml 的 data.kline_sources 决定。
- 更换数据源或调整优先级只需改配置，无需改策略代码。
"""

from .base import KlineAdapter, KLINE_COLUMNS
from .adapters import (
    KLINE_ADAPTER_REGISTRY,
    SinaKlineAdapter,
    EastMoneyKlineAdapter,
    TencentKlineAdapter,
    TushareKlineAdapter,
)
from .data_provider import (
    UnifiedDataProvider,
    get_default_kline_provider,
    reset_default_kline_provider,
    DEFAULT_KLINE_SOURCES,
)

__all__ = [
    "KlineAdapter",
    "KLINE_COLUMNS",
    "KLINE_ADAPTER_REGISTRY",
    "SinaKlineAdapter",
    "EastMoneyKlineAdapter",
    "TencentKlineAdapter",
    "TushareKlineAdapter",
    "UnifiedDataProvider",
    "get_default_kline_provider",
    "reset_default_kline_provider",
    "DEFAULT_KLINE_SOURCES",
]
