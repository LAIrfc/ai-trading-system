"""
策略严格执行示例
展示如何使用规则引擎和策略执行器确保交易严格按照规则执行
"""

import sys
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime
from src.core.strategy.strategy_document import StrategyDocument, StrategyVersion, StrategyPerformance
from src.core.strategy.strategy_rule_engine import StrategyRuleEngine, StrategyRule, RuleType
from src.core.strategy.strategy_executor import StrategyExecutor
from src.core.risk.risk_manager import RiskManager


def create_demo_rules(rule_engine: StrategyRuleEngine):
    """创建示例规则"""
    
    print("\n📋 创建策略规则...")
    
    # 1. 交易时间窗口规则
    time_rule = StrategyRule(
        rule_id="entry_time",
        rule_type=RuleType.ENTRY,
        name="交易时间窗口",
        description="只在10:00-14:30之间交易",
        condition={
            'type': 'time_window',
            'start_time': '10:00:00',
            'end_time': '14:30:00',
        },
        action="reject",
        priority=10,
        enabled=True,
        mandatory=True
    )
    rule_engine.add_rule(time_rule)
    print(f"✅ 已添加规则: {time_rule.name}")
    
    # 2. 价格范围规则
    price_rule = StrategyRule(
        rule_id="entry_price",
        rule_type=RuleType.ENTRY,
        name="价格范围限制",
        description="只买5-100元的股票",
        condition={
            'type': 'price_range',
            'min_price': 5.0,
            'max_price': 100.0,
        },
        action="reject",
        priority=20,
        enabled=True,
        mandatory=True
    )
    rule_engine.add_rule(price_rule)
    print(f"✅ 已添加规则: {price_rule.name}")
    
    # 3. 单股仓位规则
    position_rule = StrategyRule(
        rule_id="pos_limit",
        rule_type=RuleType.POSITION_SIZE,
        name="单股仓位限制",
        description="单股仓位2%-15%",
        condition={
            'type': 'position_limit',
            'min_position': 0.02,
            'max_position': 0.15,
        },
        action="adjust",
        priority=30,
        enabled=True,
        mandatory=True
    )
    rule_engine.add_rule(position_rule)
    print(f"✅ 已添加规则: {position_rule.name}")
    
    # 4. 最小持仓期规则
    holding_rule = StrategyRule(
        rule_id="exit_holding",
        rule_type=RuleType.EXIT,
        name="最小持仓期",
        description="至少持仓1天",
        condition={
            'type': 'holding_period',
            'min_holding_days': 1,
        },
        action="reject",
        priority=10,
        enabled=True,
        mandatory=True
    )
    rule_engine.add_rule(holding_rule)
    print(f"✅ 已添加规则: {holding_rule.name}")
    
    # 5. 流动性规则
    liquidity_rule = StrategyRule(
        rule_id="entry_liquidity",
        rule_type=RuleType.FILTER,
        name="流动性要求",
        description="日成交量>1000万",
        condition={
            'type': 'liquidity',
            'min_volume': 10000000,
        },
        action="reject",
        priority=25,
        enabled=True,
        mandatory=False  # 非强制，仅警告
    )
    rule_engine.add_rule(liquidity_rule)
    print(f"✅ 已添加规则: {liquidity_rule.name} (建议规则)")


def demo_signal_processing(executor: StrategyExecutor):
    """演示信号处理流程"""
    
    print("\n\n" + "="*60)
    print("📊 测试场景1: 正常信号（应该通过）")
    print("="*60)
    
    # 正常信号
    normal_signal = {
        'stock_code': '600519',
        'action': 'buy',
        'target_position': 0.10,
        'reason': '动量突破',
        'confidence': 0.85,
    }
    
    normal_market_data = {
        '600519': {
            'price': 50.0,  # 在5-100范围内
            'volume': 50000000,  # 超过1000万
            'volatility': 0.02,
        }
    }
    
    print(f"\n信号: {normal_signal['stock_code']} - {normal_signal['action']}")
    print(f"价格: {normal_market_data['600519']['price']}元")
    print(f"成交量: {normal_market_data['600519']['volume']:,}")
    
    order = executor.process_signal(normal_signal, normal_market_data)
    
    if order:
        print(f"\n✅ 订单创建成功!")
        print(f"   订单ID: {order.order_id}")
        print(f"   状态: {order.status.value}")
        print(f"   规则检查: {'通过' if order.rule_check_passed else '未通过'}")
        print(f"   风控检查: {'通过' if order.risk_check_passed else '未通过'}")
    else:
        print("\n❌ 订单被拒绝")
    
    # 场景2: 价格超限
    print("\n\n" + "="*60)
    print("📊 测试场景2: 价格超限（应该被拒绝）")
    print("="*60)
    
    overpriced_signal = {
        'stock_code': '600519',
        'action': 'buy',
        'target_position': 0.10,
        'reason': '动量突破',
    }
    
    overpriced_market_data = {
        '600519': {
            'price': 150.0,  # 超过100元上限
            'volume': 50000000,
            'volatility': 0.02,
        }
    }
    
    print(f"\n信号: {overpriced_signal['stock_code']} - {overpriced_signal['action']}")
    print(f"价格: {overpriced_market_data['600519']['price']}元 (超过上限100元)")
    
    order = executor.process_signal(overpriced_signal, overpriced_market_data)
    
    if order:
        print(f"\n✅ 订单创建成功 (不应该发生!)")
    else:
        print("\n❌ 订单被拒绝 (符合预期)")
        print("   原因: 价格超出允许范围")
    
    # 场景3: 仓位超限
    print("\n\n" + "="*60)
    print("📊 测试场景3: 仓位超限（应该被拒绝）")
    print("="*60)
    
    overlarge_signal = {
        'stock_code': '600519',
        'action': 'buy',
        'target_position': 0.25,  # 超过15%上限
        'reason': '强势信号',
    }
    
    print(f"\n信号: {overlarge_signal['stock_code']} - {overlarge_signal['action']}")
    print(f"目标仓位: {overlarge_signal['target_position']:.0%} (超过上限15%)")
    
    order = executor.process_signal(overlarge_signal, normal_market_data)
    
    if order:
        print(f"\n✅ 订单创建成功 (不应该发生!)")
    else:
        print("\n❌ 订单被拒绝 (符合预期)")
        print("   原因: 仓位超出允许范围")
    
    # 场景4: 流动性不足（建议规则，应该通过但有警告）
    print("\n\n" + "="*60)
    print("📊 测试场景4: 流动性不足（建议规则，应通过但警告）")
    print("="*60)
    
    low_liquidity_signal = {
        'stock_code': '000001',
        'action': 'buy',
        'target_position': 0.10,
        'reason': '技术信号',
    }
    
    low_liquidity_market_data = {
        '000001': {
            'price': 30.0,
            'volume': 5000000,  # 低于1000万
            'volatility': 0.02,
        }
    }
    
    print(f"\n信号: {low_liquidity_signal['stock_code']} - {low_liquidity_signal['action']}")
    print(f"成交量: {low_liquidity_market_data['000001']['volume']:,} (低于1000万)")
    
    order = executor.process_signal(low_liquidity_signal, low_liquidity_market_data)
    
    if order:
        print(f"\n✅ 订单创建成功 (建议规则，可以通过)")
        print(f"   ⚠️  警告: 流动性不足")
        if order.rule_violations:
            for v in order.rule_violations:
                if v['severity'] == 'warning':
                    print(f"   - {v['rule_name']}: {v['reason']}")
    else:
        print("\n❌ 订单被拒绝")


def demo_audit_trail(executor: StrategyExecutor):
    """演示审计追踪"""
    
    print("\n\n" + "="*60)
    print("📝 审计日志")
    print("="*60)
    
    # 获取所有审计日志
    logs = executor.get_audit_logs()
    
    print(f"\n总计: {len(logs)}条审计记录\n")
    
    # 按订单分组显示
    orders = {}
    for log in logs:
        if log.order_id not in orders:
            orders[log.order_id] = []
        orders[log.order_id].append(log)
    
    for order_id, order_logs in orders.items():
        print(f"\n订单 {order_id}:")
        for log in order_logs:
            print(f"  [{log.timestamp}] {log.event_type}")
            if log.event_type == 'rule_check':
                passed = log.details.get('passed')
                print(f"    → 规则检查: {'✅ 通过' if passed else '❌ 未通过'}")
                violations = log.details.get('violations', [])
                if violations:
                    for v in violations:
                        severity = v.get('severity', 'error')
                        icon = '⚠️ ' if severity == 'warning' else '❌'
                        print(f"      {icon} {v.get('rule_name')}: {v.get('reason')}")


def demo_execution_report(executor: StrategyExecutor):
    """演示执行报告"""
    
    print("\n\n" + "="*60)
    print("📊 执行报告")
    print("="*60)
    
    report = executor.generate_execution_report()
    print(report)


def demo_rule_summary(rule_engine: StrategyRuleEngine):
    """演示规则摘要"""
    
    print("\n\n" + "="*60)
    print("📋 规则摘要")
    print("="*60)
    
    summary = rule_engine.get_rule_summary()
    
    print(f"\n策略名称: {summary['strategy_name']}")
    print(f"总规则数: {summary['total_rules']}")
    print(f"已启用: {summary['enabled_rules']}")
    print(f"强制规则: {summary['mandatory_rules']}")
    print(f"规则违反: {summary['total_violations']}次")
    
    print("\n按类型统计:")
    for rule_type, count in summary['by_type'].items():
        print(f"  - {rule_type}: {count}条")


def main():
    """主函数"""
    
    print("="*60)
    print("🚀 策略严格执行系统演示")
    print("="*60)
    print("\n本演示展示如何使用规则引擎确保交易严格按照预定规则执行")
    
    # 1. 创建策略文档
    print("\n📄 Step 1: 初始化策略文档")
    strategy_doc = StrategyDocument("demo_strategy", doc_dir="docs/strategies")
    strategy_doc.metadata['description'] = "演示策略 - 展示规则强制执行"
    strategy_doc.metadata['category'] = "示例"
    strategy_doc.metadata['tags'] = ['demo', 'rule_based']
    
    # 创建版本
    version = StrategyVersion(
        version="1.0.0",
        create_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        author="Demo Team",
        description="初始版本，包含5条基础规则",
        parameters={
            'price_range': [5, 100],
            'position_limit': [0.02, 0.15],
            'min_holding_days': 1,
        },
        changes=[
            "添加交易时间窗口限制",
            "添加价格范围限制",
            "添加仓位限制",
            "添加最小持仓期限制",
            "添加流动性建议规则"
        ],
        status="testing"
    )
    strategy_doc.create_version(version)
    print("✅ 策略文档已创建")
    
    # 2. 创建规则引擎
    print("\n🔧 Step 2: 初始化规则引擎")
    rule_engine = StrategyRuleEngine("demo_strategy")
    create_demo_rules(rule_engine)
    
    # 3. 创建风控管理器
    print("\n🛡️  Step 3: 初始化风控管理器")
    risk_config = {
        'account_risk': {
            'max_drawdown': 0.20,
            'daily_loss_limit': 0.05,
        },
        'stock_risk': {
            'stop_loss': -0.08,
            'stop_profit': 0.20,
        },
    }
    risk_manager = RiskManager(risk_config)
    print("✅ 风控管理器已创建")
    
    # 4. 创建策略执行器
    print("\n⚙️  Step 4: 初始化策略执行器")
    executor = StrategyExecutor(
        strategy_name="demo_strategy",
        strategy_document=strategy_doc,
        rule_engine=rule_engine,
        risk_manager=risk_manager,
        audit_dir="data/audit"
    )
    executor.require_manual_approval = False
    executor.auto_approve = True
    print("✅ 策略执行器已创建")
    print("   - 自动批准模式: ON")
    print("   - 规则强制执行: ON")
    
    # 5. 演示信号处理
    demo_signal_processing(executor)
    
    # 6. 查看审计日志
    demo_audit_trail(executor)
    
    # 7. 生成执行报告
    demo_execution_report(executor)
    
    # 8. 规则摘要
    demo_rule_summary(rule_engine)
    
    # 9. 导出规则
    print("\n\n" + "="*60)
    print("💾 导出规则和文档")
    print("="*60)
    
    rule_engine.export_rules("data/demo_strategy_rules.json")
    print("✅ 规则已导出到: data/demo_strategy_rules.json")
    
    strategy_doc.export_report("docs/strategies/demo_strategy_report.md")
    print("✅ 策略报告已导出到: docs/strategies/demo_strategy_report.md")
    
    print("\n\n" + "="*60)
    print("🎉 演示完成!")
    print("="*60)
    print("\n关键要点:")
    print("1. 所有交易必须通过规则检查")
    print("2. 强制规则违反会自动拒绝交易")
    print("3. 建议规则违反会给出警告但允许交易")
    print("4. 每个决策都有完整的审计追踪")
    print("5. 规则和文档可以版本控制")
    print("\n📚 查看详细文档: docs/STRATEGY_EXECUTION_GUIDE.md")


if __name__ == '__main__':
    main()
