"""
混合策略选择器（v5.2 / v6.1 / v6.4 动态切换）

根据实时IC自动选择最优版本
v6.4: 生产级组合决策引擎（Conditional IC + CVaR + 统一优化器 + 执行反馈）
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


VERSIONS = {
    'v5.2': {
        'use_orthogonalization': False,
        'use_rank_normalization': False,
        'use_soft_regime': False,
        'use_volatility_scaling': False,
        'use_unified_optimizer': False,
        'use_conditional_ic': False,
        'use_alpha_penalty': False,
        'use_execution_feedback': False,
        'weights': [0.40, 0.30, 0.10, 0.20],
        'description': '固定权重，无正交化'
    },
    'v6.1': {
        'use_orthogonalization': True,
        'use_rank_normalization': True,
        'use_soft_regime': True,
        'use_volatility_scaling': True,
        'use_unified_optimizer': False,
        'use_conditional_ic': False,
        'use_alpha_penalty': False,
        'use_execution_feedback': False,
        'weights': [0.42, 0.20, 0.30, 0.08],
        'description': '正交化+Rank Norm+Soft Regime+Risk Parity'
    },
    'v6.4': {
        'use_orthogonalization': True,
        'use_rank_normalization': True,
        'use_soft_regime': True,
        'use_volatility_scaling': True,
        'use_unified_optimizer': True,
        'use_conditional_ic': True,
        'use_alpha_penalty': True,
        'use_execution_feedback': True,
        'weights': [0.42, 0.20, 0.30, 0.08],
        'description': '生产级组合决策引擎(Conditional IC + CVaR + 统一优化 + 执行反馈)'
    }
}


class HybridVersionSelector:
    """
    混合版本选择器

    根据实时IC决定使用v5.2/v6.1/v6.4
    """

    def __init__(self,
                 ic_threshold_base=0.20,
                 ic_threshold_rs=0.15,
                 ic_cache_file='results/factor_ic_monitoring.json',
                 ic_cache_max_age_hours=24):
        self.ic_threshold_base = ic_threshold_base
        self.ic_threshold_rs = ic_threshold_rs
        self.ic_cache_file = ic_cache_file
        self.ic_cache_max_age_hours = ic_cache_max_age_hours

    def _load_latest_ic(self):
        if not os.path.exists(self.ic_cache_file):
            return None
        try:
            with open(self.ic_cache_file, 'r') as f:
                data = json.load(f)
            cache_time = datetime.strptime(data['date'], '%Y-%m-%d %H:%M:%S')
            age_hours = (datetime.now() - cache_time).total_seconds() / 3600
            if age_hours > self.ic_cache_max_age_hours:
                return None
            return data['ic_results']
        except Exception:
            return None

    def select_version(self, force_version=None):
        """
        选择版本

        Returns:
            dict: {version, weights, reason, ic_status}
        """
        if force_version and force_version in VERSIONS:
            cfg = VERSIONS[force_version]
            return {
                'version': force_version,
                'weights': cfg['weights'],
                'reason': f'用户强制指定{force_version}',
                'ic_status': None
            }

        ic_results = self._load_latest_ic()

        if ic_results is None:
            return {
                'version': 'v6.4',
                'weights': VERSIONS['v6.4']['weights'],
                'reason': 'IC数据不可用，使用v6.4（最新生产级引擎）',
                'ic_status': None
            }

        ic_base = ic_results.get('base_trend', {}).get('ic_spearman', 0)
        ic_rs = ic_results.get('relative_strength', {}).get('ic_spearman', 0)

        ic_status = {
            'base_trend_ic': ic_base,
            'relative_strength_ic': ic_rs,
            'cache_file': self.ic_cache_file
        }

        if ic_base >= self.ic_threshold_base and ic_rs >= self.ic_threshold_rs:
            return {
                'version': 'v6.4',
                'weights': VERSIONS['v6.4']['weights'],
                'reason': f'IC高（base={ic_base:.3f}, rs={ic_rs:.3f}），使用v6.4',
                'ic_status': ic_status
            }
        elif ic_base >= self.ic_threshold_base * 0.8:
            return {
                'version': 'v6.1',
                'weights': VERSIONS['v6.1']['weights'],
                'reason': f'IC中（base={ic_base:.3f}, rs={ic_rs:.3f}），使用v6.1',
                'ic_status': ic_status
            }
        else:
            return {
                'version': 'v5.2',
                'weights': VERSIONS['v5.2']['weights'],
                'reason': f'IC低（base={ic_base:.3f}, rs={ic_rs:.3f}），使用v5.2',
                'ic_status': ic_status
            }

    def get_version_config(self, version='v6.4'):
        return VERSIONS.get(version, VERSIONS['v6.4'])

    def log_decision(self, decision, log_file='logs/hybrid_selector.log'):
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        log_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'version': decision['version'],
            'reason': decision['reason'],
            'ic_status': decision['ic_status']
        }
        try:
            with open(log_file, 'a') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception:
            pass


def create_hybrid_selector(**kwargs):
    return HybridVersionSelector(**kwargs)
