"""
混合策略选择器（v5.2 vs v6.1 动态切换）

根据实时IC自动选择最优版本
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


class HybridVersionSelector:
    """
    混合版本选择器
    
    根据实时IC决定使用v5.2还是v6.1
    """
    
    def __init__(self, 
                 ic_threshold_base=0.20,
                 ic_threshold_rs=0.15,
                 ic_cache_file='results/factor_ic_monitoring.json',
                 ic_cache_max_age_hours=24):
        """
        Args:
            ic_threshold_base: base_trend IC阈值
            ic_threshold_rs: relative_strength IC阈值
            ic_cache_file: IC监控缓存文件
            ic_cache_max_age_hours: IC缓存最大有效期（小时）
        """
        self.ic_threshold_base = ic_threshold_base
        self.ic_threshold_rs = ic_threshold_rs
        self.ic_cache_file = ic_cache_file
        self.ic_cache_max_age_hours = ic_cache_max_age_hours
    
    def _load_latest_ic(self):
        """加载最新IC监控结果"""
        if not os.path.exists(self.ic_cache_file):
            return None
        
        try:
            with open(self.ic_cache_file, 'r') as f:
                data = json.load(f)
            
            # 检查时效性
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
        
        Args:
            force_version: 强制版本（'v5.2' 或 'v6.1'），None则自动选择
        
        Returns:
            dict: {
                'version': 'v5.2' or 'v6.1',
                'weights': [w1, w2, w3, w4],
                'reason': str,
                'ic_status': dict
            }
        """
        if force_version:
            if force_version == 'v5.2':
                return {
                    'version': 'v5.2',
                    'weights': [0.40, 0.30, 0.10, 0.20],
                    'reason': '用户强制指定v5.2',
                    'ic_status': None
                }
            elif force_version == 'v6.1':
                return {
                    'version': 'v6.1',
                    'weights': [0.42, 0.20, 0.30, 0.08],
                    'reason': '用户强制指定v6.1',
                    'ic_status': None
                }
        
        # 加载IC
        ic_results = self._load_latest_ic()
        
        if ic_results is None:
            # 无IC数据，默认使用v6.1（长期回测更优）
            return {
                'version': 'v6.1',
                'weights': [0.42, 0.20, 0.30, 0.08],
                'reason': 'IC数据不可用，使用v6.1（长期回测更优）',
                'ic_status': None
            }
        
        # 提取IC
        ic_base = ic_results.get('base_trend', {}).get('ic_spearman', 0)
        ic_rs = ic_results.get('relative_strength', {}).get('ic_spearman', 0)
        
        ic_status = {
            'base_trend_ic': ic_base,
            'relative_strength_ic': ic_rs,
            'cache_file': self.ic_cache_file
        }
        
        # 判断逻辑
        if ic_base >= self.ic_threshold_base and ic_rs >= self.ic_threshold_rs:
            # IC高，使用v6.1
            return {
                'version': 'v6.1',
                'weights': [0.42, 0.20, 0.30, 0.08],
                'reason': f'IC高（base={ic_base:.3f}, rs={ic_rs:.3f}），使用v6.1',
                'ic_status': ic_status
            }
        else:
            # IC低，使用v5.2
            return {
                'version': 'v5.2',
                'weights': [0.40, 0.30, 0.10, 0.20],
                'reason': f'IC低（base={ic_base:.3f}, rs={ic_rs:.3f}），使用v5.2',
                'ic_status': ic_status
            }
    
    def get_version_config(self, version='v6.1'):
        """
        获取版本配置
        
        Args:
            version: 'v5.2' or 'v6.1'
        
        Returns:
            dict: 版本配置
        """
        configs = {
            'v5.2': {
                'use_orthogonalization': False,
                'use_rank_normalization': False,
                'use_soft_regime': False,
                'use_volatility_scaling': False,
                'weights': [0.40, 0.30, 0.10, 0.20],
                'description': '固定权重，无正交化'
            },
            'v6.1': {
                'use_orthogonalization': True,
                'use_rank_normalization': True,
                'use_soft_regime': True,
                'use_volatility_scaling': True,
                'weights': [0.42, 0.20, 0.30, 0.08],
                'description': '正交化+Rank Norm+Soft Regime+Risk Parity'
            }
        }
        
        return configs.get(version, configs['v6.1'])
    
    def log_decision(self, decision, log_file='logs/hybrid_selector.log'):
        """记录决策日志"""
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
    """工厂函数"""
    return HybridVersionSelector(**kwargs)
