"""
东方财富妙想Skills集成模块

提供以下能力:
- mx_data:   金融行情/财务数据查询 (替代/补充 AKShare)
- mx_search: 金融资讯搜索 (增强 NEWS/SENTIMENT 策略)
- mx_xuangu: 智能选股 (预筛选层)
- mx_zixuan: 自选股管理
- mx_moni:   模拟组合管理

全局共享每日 300 次 API 调用限制。
"""

from .rate_limiter import MXRateLimiter, get_rate_limiter
from .client import MXClient, get_mx_client

__all__ = [
    "MXRateLimiter",
    "get_rate_limiter",
    "MXClient",
    "get_mx_client",
]
