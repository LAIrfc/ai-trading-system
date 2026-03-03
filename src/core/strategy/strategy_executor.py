"""
策略执行器
严格按照策略文档执行交易，包含审计追踪功能
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
import json
from pathlib import Path
from loguru import logger

from .strategy_rule_engine import StrategyRuleEngine, RuleViolation
from .strategy_document import StrategyDocument
from ..risk.risk_manager import RiskManager


class ExecutionStatus(Enum):
    """执行状态"""
    PENDING = "pending"  # 等待执行
    APPROVED = "approved"  # 已批准
    REJECTED = "rejected"  # 已拒绝
    EXECUTED = "executed"  # 已执行
    FAILED = "failed"  # 执行失败
    CANCELLED = "cancelled"  # 已取消


@dataclass
class TradeOrder:
    """交易订单"""
    order_id: str
    strategy_name: str
    strategy_version: str
    stock_code: str
    action: str  # buy / sell
    target_position: float
    target_price: Optional[float]
    quantity: int
    signal: Dict
    create_time: str
    status: ExecutionStatus
    
    # 审计信息
    rule_check_passed: bool
    rule_violations: List[Dict]
    risk_check_passed: bool
    risk_check_result: Optional[Dict]
    
    # 执行信息
    executed_time: Optional[str] = None
    executed_price: Optional[float] = None
    executed_quantity: Optional[int] = None
    commission: Optional[float] = None
    
    # 审批信息
    approved_by: Optional[str] = None
    approved_time: Optional[str] = None
    reject_reason: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        data = asdict(self)
        data['status'] = self.status.value
        return data


@dataclass
class ExecutionAuditLog:
    """执行审计日志"""
    log_id: str
    timestamp: str
    strategy_name: str
    order_id: str
    event_type: str  # signal_generated / rule_check / risk_check / approved / executed / rejected
    details: Dict
    operator: Optional[str] = None


class StrategyExecutor:
    """策略执行器"""
    
    def __init__(self, 
                 strategy_name: str,
                 strategy_document: StrategyDocument,
                 rule_engine: StrategyRuleEngine,
                 risk_manager: RiskManager,
                 audit_dir: str = "mydate/audit"):
        """
        初始化策略执行器
        
        Args:
            strategy_name: 策略名称
            strategy_document: 策略文档
            rule_engine: 规则引擎
            risk_manager: 风险管理器
            audit_dir: 审计日志目录
        """
        self.strategy_name = strategy_name
        self.strategy_doc = strategy_document
        self.rule_engine = rule_engine
        self.risk_manager = risk_manager
        
        # 审计目录
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        
        # 订单管理
        self.pending_orders: Dict[str, TradeOrder] = {}
        self.executed_orders: Dict[str, TradeOrder] = {}
        self.audit_logs: List[ExecutionAuditLog] = []
        
        # 配置
        self.auto_approve = False  # 是否自动批准
        self.require_manual_approval = True  # 是否需要人工审批
        
        logger.info(f"策略执行器初始化: {strategy_name}")
        
    def process_signal(self, signal: Dict, market_data: Dict) -> Optional[TradeOrder]:
        """
        处理交易信号
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            交易订单或None
        """
        order_id = self._generate_order_id()
        
        # 记录信号生成
        self._log_audit(
            order_id=order_id,
            event_type="signal_generated",
            details={'signal': signal}
        )
        
        logger.info(f"📝 处理交易信号: {signal.get('stock_code')} - {signal.get('action')}")
        
        # 1. 规则检查
        rule_passed, rule_violations = self.rule_engine.validate_signal(signal, market_data)
        
        self._log_audit(
            order_id=order_id,
            event_type="rule_check",
            details={
                'passed': rule_passed,
                'violations': [v.__dict__ for v in rule_violations]
            }
        )
        
        if not rule_passed:
            logger.error(f"❌ 规则检查未通过: {signal.get('stock_code')}")
            for v in rule_violations:
                if v.severity == "error":
                    logger.error(f"  - {v.rule_name}: {v.reason}")
            return None
        
        # 2. 风控检查
        risk_passed, risk_result = self._check_risk(signal, market_data)
        
        self._log_audit(
            order_id=order_id,
            event_type="risk_check",
            details={
                'passed': risk_passed,
                'result': risk_result
            }
        )
        
        if not risk_passed:
            logger.error(f"❌ 风控检查未通过: {signal.get('stock_code')}")
            logger.error(f"  原因: {risk_result.get('reason')}")
            return None
        
        # 3. 创建订单
        order = self._create_order(
            order_id=order_id,
            signal=signal,
            market_data=market_data,
            rule_passed=rule_passed,
            rule_violations=rule_violations,
            risk_passed=risk_passed,
            risk_result=risk_result
        )
        
        self.pending_orders[order_id] = order
        
        # 4. 审批流程
        if self.auto_approve or not self.require_manual_approval:
            self.approve_order(order_id, "system")
        else:
            logger.info(f"⏳ 订单等待审批: {order_id}")
        
        return order
    
    def approve_order(self, order_id: str, approver: str) -> bool:
        """
        批准订单
        
        Args:
            order_id: 订单ID
            approver: 批准人
            
        Returns:
            是否成功
        """
        if order_id not in self.pending_orders:
            logger.error(f"订单不存在: {order_id}")
            return False
        
        order = self.pending_orders[order_id]
        order.status = ExecutionStatus.APPROVED
        order.approved_by = approver
        order.approved_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        self._log_audit(
            order_id=order_id,
            event_type="approved",
            details={'approver': approver},
            operator=approver
        )
        
        logger.info(f"✅ 订单已批准: {order_id} by {approver}")
        
        # 执行订单
        return self.execute_order(order_id)
    
    def reject_order(self, order_id: str, reason: str, operator: str) -> bool:
        """
        拒绝订单
        
        Args:
            order_id: 订单ID
            reason: 拒绝原因
            operator: 操作人
            
        Returns:
            是否成功
        """
        if order_id not in self.pending_orders:
            logger.error(f"订单不存在: {order_id}")
            return False
        
        order = self.pending_orders[order_id]
        order.status = ExecutionStatus.REJECTED
        order.reject_reason = reason
        
        self._log_audit(
            order_id=order_id,
            event_type="rejected",
            details={'reason': reason},
            operator=operator
        )
        
        # 移出待处理列表
        del self.pending_orders[order_id]
        
        logger.warning(f"🚫 订单已拒绝: {order_id} - {reason}")
        return True
    
    def execute_order(self, order_id: str) -> bool:
        """
        执行订单
        
        Args:
            order_id: 订单ID
            
        Returns:
            是否成功
        """
        if order_id not in self.pending_orders:
            logger.error(f"订单不存在: {order_id}")
            return False
        
        order = self.pending_orders[order_id]
        
        if order.status != ExecutionStatus.APPROVED:
            logger.error(f"订单未批准，无法执行: {order_id}")
            return False
        
        try:
            # TODO: 实际的订单执行逻辑（调用券商API）
            # 这里是模拟执行
            execution_result = self._simulate_execution(order)
            
            order.status = ExecutionStatus.EXECUTED
            order.executed_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            order.executed_price = execution_result['price']
            order.executed_quantity = execution_result['quantity']
            order.commission = execution_result['commission']
            
            self._log_audit(
                order_id=order_id,
                event_type="executed",
                details=execution_result
            )
            
            # 移到已执行列表
            self.executed_orders[order_id] = order
            del self.pending_orders[order_id]
            
            logger.success(f"✅ 订单已执行: {order_id} - {order.stock_code} {order.action} {order.executed_quantity}股 @ {order.executed_price}")
            
            return True
            
        except Exception as e:
            order.status = ExecutionStatus.FAILED
            
            self._log_audit(
                order_id=order_id,
                event_type="failed",
                details={'error': str(e)}
            )
            
            logger.error(f"❌ 订单执行失败: {order_id} - {e}")
            return False
    
    def _check_risk(self, signal: Dict, market_data: Dict) -> Tuple[bool, Dict]:
        """
        风控检查
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            (是否通过, 检查结果)
        """
        # TODO: 调用风控管理器进行检查
        # 这里是简化版本
        
        stock_code = signal.get('stock_code')
        action = signal.get('action')
        
        # 示例检查
        if action == 'buy':
            # 检查资金
            # 检查仓位限制
            # 检查交易频率
            pass
        elif action == 'sell':
            # 检查持仓
            # 检查最小持仓期
            pass
        
        return True, {'reason': '风控检查通过'}
    
    def _create_order(self, 
                     order_id: str,
                     signal: Dict,
                     market_data: Dict,
                     rule_passed: bool,
                     rule_violations: List[RuleViolation],
                     risk_passed: bool,
                     risk_result: Dict) -> TradeOrder:
        """创建订单"""
        
        stock_code = signal.get('stock_code')
        current_price = market_data.get(stock_code, {}).get('price', 0)
        target_position = signal.get('target_position', 0)
        
        # 计算数量（简化版）
        quantity = 100  # TODO: 根据资金和目标仓位计算
        
        # 获取当前策略版本
        current_version = self.strategy_doc.metadata.get('current_version', 'unknown')
        
        return TradeOrder(
            order_id=order_id,
            strategy_name=self.strategy_name,
            strategy_version=current_version,
            stock_code=stock_code,
            action=signal.get('action'),
            target_position=target_position,
            target_price=current_price,
            quantity=quantity,
            signal=signal,
            create_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            status=ExecutionStatus.PENDING,
            rule_check_passed=rule_passed,
            rule_violations=[v.__dict__ for v in rule_violations],
            risk_check_passed=risk_passed,
            risk_check_result=risk_result,
        )
    
    def _simulate_execution(self, order: TradeOrder) -> Dict:
        """模拟订单执行"""
        # 实际应该调用券商API
        return {
            'price': order.target_price,
            'quantity': order.quantity,
            'commission': order.target_price * order.quantity * 0.0003,  # 0.03%手续费
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    
    def _generate_order_id(self) -> str:
        """生成订单ID"""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
        return f"{self.strategy_name}_{timestamp}"
    
    def _log_audit(self, order_id: str, event_type: str, details: Dict, operator: Optional[str] = None):
        """记录审计日志"""
        log_id = f"{order_id}_{len(self.audit_logs)}"
        
        audit_log = ExecutionAuditLog(
            log_id=log_id,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'),
            strategy_name=self.strategy_name,
            order_id=order_id,
            event_type=event_type,
            details=details,
            operator=operator
        )
        
        self.audit_logs.append(audit_log)
        
        # 实时写入审计日志文件
        self._write_audit_log(audit_log)
    
    def _write_audit_log(self, audit_log: ExecutionAuditLog):
        """写入审计日志到文件"""
        date_str = datetime.now().strftime('%Y-%m-%d')
        log_file = self.audit_dir / f"{self.strategy_name}_{date_str}.jsonl"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(audit_log), ensure_ascii=False) + '\n')
    
    def get_pending_orders(self) -> List[TradeOrder]:
        """获取待处理订单"""
        return list(self.pending_orders.values())
    
    def get_executed_orders(self, since: Optional[str] = None) -> List[TradeOrder]:
        """获取已执行订单"""
        orders = list(self.executed_orders.values())
        
        if since:
            orders = [o for o in orders if o.executed_time and o.executed_time >= since]
        
        return orders
    
    def get_audit_logs(self, order_id: Optional[str] = None) -> List[ExecutionAuditLog]:
        """获取审计日志"""
        if order_id:
            return [log for log in self.audit_logs if log.order_id == order_id]
        return self.audit_logs
    
    def generate_execution_report(self, output_file: Optional[str] = None) -> str:
        """
        生成执行报告
        
        Args:
            output_file: 输出文件路径
            
        Returns:
            报告内容
        """
        report = []
        report.append(f"# 策略执行报告：{self.strategy_name}\n")
        report.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # 统计信息
        total_orders = len(self.pending_orders) + len(self.executed_orders)
        executed_count = len(self.executed_orders)
        pending_count = len(self.pending_orders)
        
        report.append("## 执行统计\n")
        report.append(f"- 总订单数：{total_orders}")
        report.append(f"- 已执行：{executed_count}")
        report.append(f"- 待处理：{pending_count}")
        report.append(f"- 审计日志：{len(self.audit_logs)}\n")
        
        # 待处理订单
        if self.pending_orders:
            report.append("## 待处理订单\n")
            report.append("| 订单ID | 股票代码 | 动作 | 状态 | 创建时间 |")
            report.append("|--------|----------|------|------|----------|")
            
            for order in self.pending_orders.values():
                report.append(
                    f"| {order.order_id} | {order.stock_code} | {order.action} | "
                    f"{order.status.value} | {order.create_time} |"
                )
            
            report.append("")
        
        # 已执行订单
        if self.executed_orders:
            report.append("## 已执行订单\n")
            report.append("| 订单ID | 股票代码 | 动作 | 数量 | 价格 | 执行时间 |")
            report.append("|--------|----------|------|------|------|----------|")
            
            for order in self.executed_orders.values():
                report.append(
                    f"| {order.order_id} | {order.stock_code} | {order.action} | "
                    f"{order.executed_quantity} | {order.executed_price} | {order.executed_time} |"
                )
            
            report.append("")
        
        # 规则违反统计
        all_violations = self.rule_engine.get_violations()
        if all_violations:
            report.append("## 规则违反记录\n")
            report.append(f"总计：{len(all_violations)}次\n")
            
            # 按规则分组统计
            by_rule = {}
            for v in all_violations:
                by_rule[v.rule_name] = by_rule.get(v.rule_name, 0) + 1
            
            report.append("| 规则名称 | 违反次数 |")
            report.append("|----------|----------|")
            for rule_name, count in sorted(by_rule.items(), key=lambda x: x[1], reverse=True):
                report.append(f"| {rule_name} | {count} |")
            
            report.append("")
        
        report_content = '\n'.join(report)
        
        # 保存到文件
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report_content)
            logger.info(f"执行报告已保存: {output_file}")
        
        return report_content


# 使用示例
if __name__ == '__main__':
    from .strategy_document import StrategyDocument
    from .strategy_rule_engine import StrategyRuleEngine, StrategyRule, RuleType
    from ..risk.risk_manager import RiskManager
    
    # 初始化组件
    strategy_doc = StrategyDocument("test_strategy")
    rule_engine = StrategyRuleEngine("test_strategy")
    risk_manager = RiskManager({'account_risk': {}, 'stock_risk': {}})
    
    # 添加规则
    rule = StrategyRule(
        rule_id="test_001",
        rule_type=RuleType.ENTRY,
        name="价格范围",
        description="价格在5-100元",
        condition={'type': 'price_range', 'min_price': 5.0, 'max_price': 100.0},
        action="reject",
        mandatory=True
    )
    rule_engine.add_rule(rule)
    
    # 创建执行器
    executor = StrategyExecutor(
        strategy_name="test_strategy",
        strategy_document=strategy_doc,
        rule_engine=rule_engine,
        risk_manager=risk_manager
    )
    
    # 处理信号
    signal = {
        'stock_code': '000001',
        'action': 'buy',
        'target_position': 0.10,
        'reason': '测试信号',
    }
    
    market_data = {
        '000001': {
            'price': 50.0,
            'volume': 10000000,
        }
    }
    
    order = executor.process_signal(signal, market_data)
    
    if order:
        print(f"订单创建成功: {order.order_id}")
        
        # 生成报告
        report = executor.generate_execution_report()
        print(report)
