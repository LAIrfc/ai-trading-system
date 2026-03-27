"""
因子处理模块
包含因子正交化、标准化等功能
"""

from .orthogonalization import FactorOrthogonalizer
from .normalization import RankNormalizer

__all__ = ['FactorOrthogonalizer', 'RankNormalizer']
