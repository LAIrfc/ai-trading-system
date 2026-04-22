"""基本面数据模块：利润质量、财务健康度等。"""

from .profit_quality import compute_profit_quality, ProfitQualityResult

__all__ = ["compute_profit_quality", "ProfitQualityResult"]
