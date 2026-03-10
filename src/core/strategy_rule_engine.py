"""
策略规则引擎
确保所有交易严格按照策略文档定义的规则执行
"""

from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
import json
from loguru import logger


class RuleType(Enum):
    """规则类型"""
    ENTRY = "entry"  # 入场规则
    EXIT = "exit"  # 出场规则
    POSITION_SIZE = "position_size"  # 仓位规则
    RISK = "risk"  # 风险规则
    TIMING = "timing"  # 时机规则
    FILTER = "filter"  # 过滤规则


class RuleOperator(Enum):
    """规则运算符"""
    GREATER = ">"
    LESS = "<"
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    EQUAL = "=="
    NOT_EQUAL = "!="
    IN = "in"
    NOT_IN = "not_in"
    BETWEEN = "between"


@dataclass
class StrategyRule:
    """策略规则定义"""
    rule_id: str
    rule_type: RuleType
    name: str
    description: str
    condition: Dict  # 规则条件
    action: str  # 规则触发的动作
    priority: int = 100  # 优先级，数字越小优先级越高
    enabled: bool = True
    mandatory: bool = True  # 是否强制执行
    created_time: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'rule_id': self.rule_id,
            'rule_type': self.rule_type.value,
            'name': self.name,
            'description': self.description,
            'condition': self.condition,
            'action': self.action,
            'priority': self.priority,
            'enabled': self.enabled,
            'mandatory': self.mandatory,
            'created_time': self.created_time,
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'StrategyRule':
        """从字典创建"""
        data['rule_type'] = RuleType(data['rule_type'])
        return StrategyRule(**data)


@dataclass
class RuleViolation:
    """规则违反记录"""
    rule_id: str
    rule_name: str
    violation_time: str
    signal: Dict
    reason: str
    severity: str  # "error" / "warning"


class StrategyRuleEngine:
    """策略规则引擎"""
    
    def __init__(self, strategy_name: str):
        """
        初始化规则引擎
        
        Args:
            strategy_name: 策略名称
        """
        self.strategy_name = strategy_name
        self.rules: Dict[str, StrategyRule] = {}
        self.violations: List[RuleViolation] = []
        
        # 规则验证函数
        self.validators: Dict[str, Callable] = {
            'price_range': self._validate_price_range,
            'time_window': self._validate_time_window,
            'position_limit': self._validate_position_limit,
            'holding_period': self._validate_holding_period,
            'sector_limit': self._validate_sector_limit,
            'correlation': self._validate_correlation,
            'volatility': self._validate_volatility,
            'liquidity': self._validate_liquidity,
        }
        
    def add_rule(self, rule: StrategyRule):
        """
        添加规则
        
        Args:
            rule: 策略规则
        """
        self.rules[rule.rule_id] = rule
        logger.info(f"规则已添加: {rule.rule_id} - {rule.name}")
        
    def remove_rule(self, rule_id: str):
        """
        移除规则
        
        Args:
            rule_id: 规则ID
        """
        if rule_id in self.rules:
            del self.rules[rule_id]
            logger.info(f"规则已移除: {rule_id}")
            
    def enable_rule(self, rule_id: str):
        """启用规则"""
        if rule_id in self.rules:
            self.rules[rule_id].enabled = True
            logger.info(f"规则已启用: {rule_id}")
            
    def disable_rule(self, rule_id: str):
        """禁用规则"""
        if rule_id in self.rules:
            self.rules[rule_id].enabled = False
            logger.info(f"规则已禁用: {rule_id}")
    
    def validate_signal(self, signal: Dict, market_data: Dict) -> Tuple[bool, List[RuleViolation]]:
        """
        验证交易信号是否符合策略规则
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            (是否通过, 违反的规则列表)
        """
        violations = []
        
        # 按优先级排序规则
        sorted_rules = sorted(
            [r for r in self.rules.values() if r.enabled],
            key=lambda x: x.priority
        )
        
        for rule in sorted_rules:
            # 检查规则类型是否匹配
            if rule.rule_type == RuleType.ENTRY and signal.get('action') != 'buy':
                continue
            if rule.rule_type == RuleType.EXIT and signal.get('action') != 'sell':
                continue
            
            # 执行规则验证
            is_valid, reason = self._evaluate_rule(rule, signal, market_data)
            
            if not is_valid:
                violation = RuleViolation(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    violation_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    signal=signal,
                    reason=reason,
                    severity="error" if rule.mandatory else "warning"
                )
                violations.append(violation)
                self.violations.append(violation)
                
                # 如果是强制规则，立即返回失败
                if rule.mandatory:
                    logger.error(f"❌ 强制规则违反: {rule.name} - {reason}")
                    return False, violations
                else:
                    logger.warning(f"⚠️ 规则警告: {rule.name} - {reason}")
        
        # 如果没有强制规则违反，则通过
        if not any(v.severity == "error" for v in violations):
            logger.info(f"✅ 信号验证通过: {signal.get('stock_code')}")
            return True, violations
        
        return False, violations
    
    def _evaluate_rule(self, rule: StrategyRule, signal: Dict, market_data: Dict) -> Tuple[bool, str]:
        """
        评估单条规则
        
        Args:
            rule: 规则
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            (是否通过, 原因)
        """
        condition = rule.condition
        validator_type = condition.get('type')
        
        if validator_type in self.validators:
            return self.validators[validator_type](condition, signal, market_data)
        else:
            logger.warning(f"未知的验证器类型: {validator_type}")
            return True, ""
    
    def _validate_price_range(self, condition: Dict, signal: Dict, market_data: Dict) -> Tuple[bool, str]:
        """验证价格范围"""
        stock_code = signal.get('stock_code')
        current_price = market_data.get(stock_code, {}).get('price', 0)
        
        min_price = condition.get('min_price', 0)
        max_price = condition.get('max_price', float('inf'))
        
        if min_price <= current_price <= max_price:
            return True, ""
        else:
            return False, f"价格{current_price}不在允许范围[{min_price}, {max_price}]内"
    
    def _validate_time_window(self, condition: Dict, signal: Dict, market_data: Dict) -> Tuple[bool, str]:
        """验证交易时间窗口"""
        now = datetime.now().time()
        
        start_time = time.fromisoformat(condition.get('start_time', '09:30:00'))
        end_time = time.fromisoformat(condition.get('end_time', '15:00:00'))
        
        if start_time <= now <= end_time:
            return True, ""
        else:
            return False, f"当前时间{now}不在允许的交易时间[{start_time}, {end_time}]内"
    
    def _validate_position_limit(self, condition: Dict, signal: Dict, market_data: Dict) -> Tuple[bool, str]:
        """验证仓位限制"""
        target_position = signal.get('target_position', 0)
        max_position = condition.get('max_position', 1.0)
        min_position = condition.get('min_position', 0.0)
        
        if min_position <= target_position <= max_position:
            return True, ""
        else:
            return False, f"目标仓位{target_position}不在允许范围[{min_position}, {max_position}]内"
    
    def _validate_holding_period(self, condition: Dict, signal: Dict, market_data: Dict) -> Tuple[bool, str]:
        """验证持仓时间"""
        entry_time = signal.get('entry_time')
        if not entry_time:
            return True, ""
        
        min_holding_days = condition.get('min_holding_days', 0)
        entry_date = datetime.fromisoformat(entry_time)
        holding_days = (datetime.now() - entry_date).days
        
        if holding_days >= min_holding_days:
            return True, ""
        else:
            return False, f"持仓时间{holding_days}天，未满足最小持仓期{min_holding_days}天"
    
    def _validate_sector_limit(self, condition: Dict, signal: Dict, market_data: Dict) -> Tuple[bool, str]:
        """验证行业集中度"""
        # TODO: 实现行业集中度检查
        return True, ""
    
    def _validate_correlation(self, condition: Dict, signal: Dict, market_data: Dict) -> Tuple[bool, str]:
        """验证相关性"""
        # TODO: 实现相关性检查
        return True, ""
    
    def _validate_volatility(self, condition: Dict, signal: Dict, market_data: Dict) -> Tuple[bool, str]:
        """验证波动率"""
        stock_code = signal.get('stock_code')
        volatility = market_data.get(stock_code, {}).get('volatility', 0)
        
        max_volatility = condition.get('max_volatility', float('inf'))
        
        if volatility <= max_volatility:
            return True, ""
        else:
            return False, f"波动率{volatility}超过上限{max_volatility}"
    
    def _validate_liquidity(self, condition: Dict, signal: Dict, market_data: Dict) -> Tuple[bool, str]:
        """验证流动性"""
        stock_code = signal.get('stock_code')
        volume = market_data.get(stock_code, {}).get('volume', 0)
        
        min_volume = condition.get('min_volume', 0)
        
        if volume >= min_volume:
            return True, ""
        else:
            return False, f"成交量{volume}低于最小要求{min_volume}"
    
    def get_violations(self, since: Optional[str] = None) -> List[RuleViolation]:
        """
        获取规则违反记录
        
        Args:
            since: 起始时间，格式 'YYYY-MM-DD HH:MM:SS'
            
        Returns:
            违反记录列表
        """
        if since:
            return [v for v in self.violations if v.violation_time >= since]
        return self.violations
    
    def clear_violations(self):
        """清除违反记录"""
        self.violations.clear()
        
    def export_rules(self, filepath: str):
        """
        导出规则到文件
        
        Args:
            filepath: 文件路径
        """
        rules_data = [rule.to_dict() for rule in self.rules.values()]
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(rules_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"规则已导出到: {filepath}")
    
    def import_rules(self, filepath: str):
        """
        从文件导入规则
        
        Args:
            filepath: 文件路径
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            rules_data = json.load(f)
        
        for rule_data in rules_data:
            rule = StrategyRule.from_dict(rule_data)
            self.add_rule(rule)
        
        logger.info(f"已从{filepath}导入{len(rules_data)}条规则")
    
    def get_rule_summary(self) -> Dict:
        """
        获取规则摘要
        
        Returns:
            规则摘要字典
        """
        enabled_rules = [r for r in self.rules.values() if r.enabled]
        mandatory_rules = [r for r in enabled_rules if r.mandatory]
        
        by_type = {}
        for rule in enabled_rules:
            rule_type = rule.rule_type.value
            by_type[rule_type] = by_type.get(rule_type, 0) + 1
        
        return {
            'strategy_name': self.strategy_name,
            'total_rules': len(self.rules),
            'enabled_rules': len(enabled_rules),
            'mandatory_rules': len(mandatory_rules),
            'by_type': by_type,
            'total_violations': len(self.violations),
        }


# 使用示例
if __name__ == '__main__':
    # 创建规则引擎
    engine = StrategyRuleEngine("my_strategy")
    
    # 定义入场规则
    entry_rule_1 = StrategyRule(
        rule_id="entry_001",
        rule_type=RuleType.ENTRY,
        name="交易时间限制",
        description="只在开盘后30分钟到收盘前30分钟交易",
        condition={
            'type': 'time_window',
            'start_time': '10:00:00',
            'end_time': '14:30:00',
        },
        action="reject",
        priority=10,
        mandatory=True
    )
    
    entry_rule_2 = StrategyRule(
        rule_id="entry_002",
        rule_type=RuleType.ENTRY,
        name="价格范围限制",
        description="只买入价格在5-100元之间的股票",
        condition={
            'type': 'price_range',
            'min_price': 5.0,
            'max_price': 100.0,
        },
        action="reject",
        priority=20,
        mandatory=True
    )
    
    position_rule = StrategyRule(
        rule_id="pos_001",
        rule_type=RuleType.POSITION_SIZE,
        name="单股仓位限制",
        description="单只股票仓位不超过15%",
        condition={
            'type': 'position_limit',
            'max_position': 0.15,
            'min_position': 0.02,
        },
        action="adjust",
        priority=30,
        mandatory=True
    )
    
    exit_rule = StrategyRule(
        rule_id="exit_001",
        rule_type=RuleType.EXIT,
        name="最小持仓期",
        description="持仓至少1个交易日",
        condition={
            'type': 'holding_period',
            'min_holding_days': 1,
        },
        action="reject",
        priority=10,
        mandatory=True
    )
    
    # 添加规则
    engine.add_rule(entry_rule_1)
    engine.add_rule(entry_rule_2)
    engine.add_rule(position_rule)
    engine.add_rule(exit_rule)
    
    # 导出规则
    engine.export_rules("strategy_rules.json")
    
    # 测试信号验证
    signal = {
        'stock_code': '000001',
        'action': 'buy',
        'target_position': 0.10,
        'reason': '动量信号',
    }
    
    market_data = {
        '000001': {
            'price': 50.0,
            'volume': 10000000,
            'volatility': 0.02,
        }
    }
    
    # 验证信号
    is_valid, violations = engine.validate_signal(signal, market_data)
    
    print(f"信号验证结果: {'通过' if is_valid else '拒绝'}")
    if violations:
        print("违反的规则:")
        for v in violations:
            print(f"  - {v.rule_name}: {v.reason}")
    
    # 查看规则摘要
    summary = engine.get_rule_summary()
    print("\n规则摘要:")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
