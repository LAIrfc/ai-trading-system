"""
L2层权重调整规则配置

定义市场状态和情绪状态下的权重调整系数及其叠加规则。

设计原则：
1. 单因子调整系数不超过 1.3x（避免过度调整）
2. 多因子叠加总系数不超过 1.5x（避免系数爆炸）
3. 优先调整仓位系数，其次调整策略权重
4. 系数需经过历史回测验证，不使用"拍脑袋"经验值

版本历史：
- v1.0 (2026-03-24): 初始版本，定义基础规则框架
"""

from typing import Dict, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# 配置常量
# ============================================================================

# 系数上限
MAX_SINGLE_FACTOR_MULTIPLIER = 1.3  # 单因子最大调整系数
MAX_COMBINED_MULTIPLIER = 1.5       # 组合后最大总系数
MIN_MULTIPLIER = 0.7                # 最小系数（避免过度降权）

# 默认调整系数（待优化脚本确定最优值）
# ⚠️ 这些是初始值，需要通过 optimize_regime_weights.py 优化后更新
DEFAULT_REGIME_MULTIPLIERS = {
    'bull': {
        'trend_following': 1.0,  # 牛市：趋势跟踪策略（MA, MACD, DUAL）
        'mean_reversion': 1.0,   # 牛市：均值回归策略（RSI, BOLL, KDJ）
        'fundamental': 1.0,      # 牛市：基本面策略（PE, PB, PEPB）
        'momentum': 1.0,         # 牛市：动量策略
        'position': 1.0,         # 牛市：仓位系数
    },
    'bear': {
        'trend_following': 1.0,
        'mean_reversion': 1.0,
        'fundamental': 1.0,
        'momentum': 1.0,
        'position': 1.0,
    },
    'sideways': {
        'trend_following': 1.0,
        'mean_reversion': 1.0,
        'fundamental': 1.0,
        'momentum': 1.0,
        'position': 1.0,
    }
}

DEFAULT_SENTIMENT_MULTIPLIERS = {
    'panic': {      # 恐慌（S < S_low）
        'contrarian': 1.0,   # 反向策略加权
        'position': 1.0,     # 仓位系数
    },
    'greed': {      # 贪婪（S > S_high）
        'contrarian': 1.0,
        'position': 1.0,
    },
    'neutral': {    # 中性
        'contrarian': 1.0,
        'position': 1.0,
    }
}

# 策略分类映射
STRATEGY_CATEGORY_MAP = {
    'MA': 'trend_following',
    'MACD': 'trend_following',
    'DUAL': 'trend_following',
    'RSI': 'mean_reversion',
    'BOLL': 'mean_reversion',
    'KDJ': 'mean_reversion',
    'PE': 'fundamental',
    'PB': 'fundamental',
    'PEPB': 'fundamental',
    'MONEY_FLOW': 'momentum',
    'NEWS': 'momentum',
}


@dataclass
class AdjustmentResult:
    """权重调整结果"""
    adjusted_weights: Dict[str, float]      # 调整后的策略权重
    position_multiplier: float              # 仓位系数
    regime: str                             # 市场状态
    sentiment: str                          # 情绪状态
    applied_multipliers: Dict[str, float]   # 实际应用的系数
    capped: bool                            # 是否触发上限约束
    explanation: str                        # 调整说明


class RegimeAdjustmentEngine:
    """
    L2层权重调整引擎
    
    功能：
    1. 根据市场状态（bull/bear/sideways）调整策略权重
    2. 根据情绪状态（panic/greed/neutral）调整策略权重
    3. 应用系数上限和叠加规则
    4. 生成调整说明
    
    用法：
        engine = RegimeAdjustmentEngine()
        result = engine.adjust_weights(
            base_weights={'MA': 1.0, 'MACD': 1.3, ...},
            regime='bear',
            sentiment='panic'
        )
        adjusted_weights = result.adjusted_weights
        position_mult = result.position_multiplier
    """
    
    def __init__(self,
                 regime_multipliers: Optional[Dict] = None,
                 sentiment_multipliers: Optional[Dict] = None,
                 max_single_multiplier: float = MAX_SINGLE_FACTOR_MULTIPLIER,
                 max_combined_multiplier: float = MAX_COMBINED_MULTIPLIER,
                 min_multiplier: float = MIN_MULTIPLIER):
        """
        Parameters:
            regime_multipliers: 市场状态调整系数（如果为None，使用默认值）
            sentiment_multipliers: 情绪状态调整系数（如果为None，使用默认值）
            max_single_multiplier: 单因子最大系数
            max_combined_multiplier: 组合最大系数
            min_multiplier: 最小系数
        """
        self.regime_multipliers = regime_multipliers or DEFAULT_REGIME_MULTIPLIERS
        self.sentiment_multipliers = sentiment_multipliers or DEFAULT_SENTIMENT_MULTIPLIERS
        self.max_single = max_single_multiplier
        self.max_combined = max_combined_multiplier
        self.min_mult = min_multiplier
    
    def load_optimized_multipliers(self, filepath: str) -> bool:
        """
        从优化结果文件加载最优系数
        
        Parameters:
            filepath: 优化结果JSON文件路径
        
        Returns:
            是否加载成功
        """
        try:
            import json
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'regime_multipliers' in data:
                self.regime_multipliers = data['regime_multipliers']
                logger.info(f"✅ 加载市场状态系数: {filepath}")
            
            if 'sentiment_multipliers' in data:
                self.sentiment_multipliers = data['sentiment_multipliers']
                logger.info(f"✅ 加载情绪状态系数: {filepath}")
            
            return True
        except Exception as e:
            logger.warning(f"⚠️ 加载优化系数失败: {e}，使用默认值")
            return False
    
    def _apply_cap(self, multiplier: float) -> Tuple[float, bool]:
        """
        应用系数上限约束
        
        Returns:
            (调整后的系数, 是否触发上限)
        """
        capped = False
        if multiplier > self.max_single:
            multiplier = self.max_single
            capped = True
        elif multiplier < self.min_mult:
            multiplier = self.min_mult
            capped = True
        return multiplier, capped
    
    def _combine_multipliers(self, regime_mult: float, sentiment_mult: float) -> Tuple[float, bool]:
        """
        组合多个系数，应用上限约束
        
        叠加规则：
        1. 简单相乘：combined = regime_mult * sentiment_mult
        2. 应用上限：min(combined, max_combined_multiplier)
        
        Returns:
            (组合后的系数, 是否触发上限)
        """
        combined = regime_mult * sentiment_mult
        capped = False
        
        if combined > self.max_combined:
            combined = self.max_combined
            capped = True
        elif combined < self.min_mult:
            combined = self.min_mult
            capped = True
        
        return combined, capped
    
    def adjust_weights(self,
                      base_weights: Dict[str, float],
                      regime: str = 'sideways',
                      sentiment: str = 'neutral') -> AdjustmentResult:
        """
        调整策略权重
        
        Parameters:
            base_weights: 基础权重字典 {'MA': 1.0, 'MACD': 1.3, ...}
            regime: 市场状态 ('bull', 'bear', 'sideways')
            sentiment: 情绪状态 ('panic', 'greed', 'neutral')
        
        Returns:
            AdjustmentResult: 调整结果
        """
        # 验证输入
        if regime not in self.regime_multipliers:
            logger.warning(f"未知市场状态: {regime}，使用 sideways")
            regime = 'sideways'
        
        if sentiment not in self.sentiment_multipliers:
            logger.warning(f"未知情绪状态: {sentiment}，使用 neutral")
            sentiment = 'neutral'
        
        regime_config = self.regime_multipliers[regime]
        sentiment_config = self.sentiment_multipliers[sentiment]
        
        adjusted_weights = {}
        applied_multipliers = {}
        any_capped = False
        
        # 对每个策略应用调整系数
        for strategy_name, base_weight in base_weights.items():
            # 1. 获取策略类别
            category = STRATEGY_CATEGORY_MAP.get(strategy_name, 'trend_following')
            
            # 2. 获取市场状态系数
            regime_mult = regime_config.get(category, 1.0)
            regime_mult, capped1 = self._apply_cap(regime_mult)
            
            # 3. 获取情绪状态系数（仅对反向策略生效）
            sentiment_mult = 1.0
            if category in ['mean_reversion', 'fundamental']:
                sentiment_mult = sentiment_config.get('contrarian', 1.0)
                sentiment_mult, capped2 = self._apply_cap(sentiment_mult)
            else:
                capped2 = False
            
            # 4. 组合系数
            combined_mult, capped3 = self._combine_multipliers(regime_mult, sentiment_mult)
            
            # 5. 应用到权重
            adjusted_weights[strategy_name] = base_weight * combined_mult
            applied_multipliers[strategy_name] = combined_mult
            
            if capped1 or capped2 or capped3:
                any_capped = True
        
        # 仓位系数
        position_mult_regime = regime_config.get('position', 1.0)
        position_mult_sentiment = sentiment_config.get('position', 1.0)
        position_mult, pos_capped = self._combine_multipliers(
            position_mult_regime, position_mult_sentiment
        )
        
        if pos_capped:
            any_capped = True
        
        # 生成说明
        explanation = self._generate_explanation(
            regime, sentiment, applied_multipliers, position_mult, any_capped
        )
        
        return AdjustmentResult(
            adjusted_weights=adjusted_weights,
            position_multiplier=position_mult,
            regime=regime,
            sentiment=sentiment,
            applied_multipliers=applied_multipliers,
            capped=any_capped,
            explanation=explanation
        )
    
    def _generate_explanation(self,
                             regime: str,
                             sentiment: str,
                             multipliers: Dict[str, float],
                             position_mult: float,
                             capped: bool) -> str:
        """生成调整说明"""
        parts = []
        
        # 市场状态
        regime_desc = {
            'bull': '牛市',
            'bear': '熊市',
            'sideways': '震荡市'
        }
        parts.append(f"市场: {regime_desc.get(regime, regime)}")
        
        # 情绪状态
        sentiment_desc = {
            'panic': '恐慌',
            'greed': '贪婪',
            'neutral': '中性'
        }
        parts.append(f"情绪: {sentiment_desc.get(sentiment, sentiment)}")
        
        # 权重调整
        non_one_mults = {k: v for k, v in multipliers.items() if abs(v - 1.0) > 0.01}
        if non_one_mults:
            mult_str = ', '.join([f"{k}:{v:.2f}x" for k, v in list(non_one_mults.items())[:3]])
            parts.append(f"权重调整: {mult_str}")
        
        # 仓位调整
        if abs(position_mult - 1.0) > 0.01:
            parts.append(f"仓位: {position_mult:.2f}x")
        
        # 上限约束
        if capped:
            parts.append(f"(已限制在{self.max_combined:.1f}x内)")
        
        return " | ".join(parts)


# ============================================================================
# 便捷函数
# ============================================================================

def create_adjustment_engine(optimized_config_path: Optional[str] = None) -> RegimeAdjustmentEngine:
    """
    创建权重调整引擎
    
    Parameters:
        optimized_config_path: 优化配置文件路径（如果为None，使用默认值）
    
    Returns:
        RegimeAdjustmentEngine实例
    """
    engine = RegimeAdjustmentEngine()
    
    if optimized_config_path:
        engine.load_optimized_multipliers(optimized_config_path)
    
    return engine


if __name__ == '__main__':
    # 测试代码
    engine = RegimeAdjustmentEngine()
    
    base_weights = {
        'MA': 1.0,
        'MACD': 1.3,
        'RSI': 0.8,
        'BOLL': 1.5,
        'KDJ': 1.1,
        'DUAL': 0.9,
        'PE': 0.6,
        'PB': 0.6,
        'PEPB': 0.8,
    }
    
    print("="*60)
    print("L2层权重调整规则测试")
    print("="*60)
    
    # 测试不同组合
    test_cases = [
        ('bull', 'neutral'),
        ('bear', 'panic'),
        ('sideways', 'greed'),
    ]
    
    for regime, sentiment in test_cases:
        result = engine.adjust_weights(base_weights, regime, sentiment)
        print(f"\n{result.explanation}")
        print(f"仓位系数: {result.position_multiplier:.2f}x")
        if result.capped:
            print("⚠️ 触发上限约束")
