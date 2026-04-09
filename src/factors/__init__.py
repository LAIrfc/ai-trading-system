"""
因子处理模块
包含因子正交化、标准化、Wind基本面因子接入等功能
"""

from .orthogonalization import FactorOrthogonalizer
from .normalization import RankNormalizer
from .wind_fundamental import WindFactorProvider

__all__ = ['FactorOrthogonalizer', 'RankNormalizer', 'WindFactorProvider']
