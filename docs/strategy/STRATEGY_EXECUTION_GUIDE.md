# 策略严格执行指南

## 概述

本系统实现了**策略文档驱动的严格交易执行**机制，确保所有交易都完全遵循事先定义的策略规则，避免情绪化交易和随意性操作。

## 核心理念

### 1. 策略即规则（Strategy as Code）

- 所有交易逻辑必须以规则形式明确定义
- 规则存储在版本控制的文档中
- 规则变更需要经过审批和验证

### 2. 强制执行（Mandatory Enforcement）

- 交易信号必须通过规则检查
- 强制规则违反时自动拒绝交易
- 无法绕过规则系统

### 3. 完整审计（Full Audit Trail）

- 记录每个交易决策的完整过程
- 追踪规则检查、风控检查、审批流程
- 可追溯、可复盘

## 系统架构

```
交易信号
    ↓
规则引擎检查 ←── 策略规则文档
    ↓
风控系统检查 ←── 风控配置
    ↓
审批流程（可选）
    ↓
订单执行 → 券商API
    ↓
审计日志 ←── 完整记录
```

## 使用流程

### Step 1: 定义策略规则

创建或编辑策略规则配置文件 `config/strategy_rules.yaml`：

```yaml
strategy_name: "momentum_strategy"

entry_rules:
  - rule_id: "entry_001"
    name: "价格范围"
    description: "只买5-100元的股票"
    condition:
      type: "price_range"
      min_price: 5.0
      max_price: 100.0
    mandatory: true
    
exit_rules:
  - rule_id: "exit_001"
    name: "止损"
    description: "亏损8%止损"
    condition:
      type: "stop_loss"
      max_loss_pct: -0.08
    mandatory: true
```

### Step 2: 初始化策略执行系统

```python
from src.core.strategy import (
    StrategyDocument,
    StrategyRuleEngine,
    StrategyExecutor
)
from src.core.risk import RiskManager

# 1. 创建策略文档
strategy_doc = StrategyDocument("momentum_strategy")
strategy_doc.metadata['description'] = "动量策略"

# 2. 创建规则引擎并加载规则
rule_engine = StrategyRuleEngine("momentum_strategy")
rule_engine.import_rules("config/strategy_rules.json")

# 3. 创建风控管理器
risk_config = load_yaml("config/risk_config.yaml")
risk_manager = RiskManager(risk_config)

# 4. 创建策略执行器
executor = StrategyExecutor(
    strategy_name="momentum_strategy",
    strategy_document=strategy_doc,
    rule_engine=rule_engine,
    risk_manager=risk_manager,
    audit_dir="data/audit"
)

# 5. 配置审批模式
executor.require_manual_approval = False  # 自动执行
executor.auto_approve = True  # 规则通过后自动批准
```

### Step 3: 处理交易信号

```python
# 生成交易信号（来自策略算法）
signal = {
    'stock_code': '600519',
    'action': 'buy',
    'target_position': 0.10,
    'reason': '动量突破',
    'confidence': 0.85,
}

# 获取市场数据
market_data = {
    '600519': {
        'price': 1800.0,
        'volume': 50000000,
        'volatility': 0.02,
    }
}

# 处理信号（自动进行规则检查、风控检查）
order = executor.process_signal(signal, market_data)

if order:
    print(f"✅ 订单创建成功: {order.order_id}")
    print(f"状态: {order.status.value}")
else:
    print("❌ 信号被拒绝")
```

### Step 4: 审批流程（可选）

如果启用了人工审批：

```python
# 配置需要人工审批
executor.require_manual_approval = True
executor.auto_approve = False

# 处理信号
order = executor.process_signal(signal, market_data)

# 查看待审批订单
pending = executor.get_pending_orders()
for order in pending:
    print(f"订单 {order.order_id}: {order.stock_code} {order.action}")
    
    # 人工审批
    if user_approve:
        executor.approve_order(order.order_id, approver="张三")
    else:
        executor.reject_order(order.order_id, "不符合当前市场环境", "张三")
```

### Step 5: 查看审计日志

```python
# 查看特定订单的审计日志
logs = executor.get_audit_logs(order_id="momentum_strategy_20240224123456")

for log in logs:
    print(f"{log.timestamp} - {log.event_type}")
    print(f"  详情: {log.details}")

# 生成执行报告
report = executor.generate_execution_report(
    output_file="reports/execution_report.md"
)
print(report)
```

### Step 6: 监控和复盘

```python
# 查看规则违反记录
violations = rule_engine.get_violations()

print(f"总违反次数: {len(violations)}")

# 统计最常违反的规则
violation_stats = {}
for v in violations:
    violation_stats[v.rule_name] = violation_stats.get(v.rule_name, 0) + 1

for rule_name, count in sorted(violation_stats.items(), key=lambda x: x[1], reverse=True):
    print(f"{rule_name}: {count}次")
```

## 规则类型详解

### 1. 入场规则 (Entry Rules)

控制何时可以买入：

```python
entry_rule = StrategyRule(
    rule_id="entry_001",
    rule_type=RuleType.ENTRY,
    name="交易时间窗口",
    description="只在10:00-14:30交易",
    condition={
        'type': 'time_window',
        'start_time': '10:00:00',
        'end_time': '14:30:00',
    },
    action="reject",
    mandatory=True
)
```

### 2. 出场规则 (Exit Rules)

控制何时必须或应该卖出：

```python
exit_rule = StrategyRule(
    rule_id="exit_001",
    rule_type=RuleType.EXIT,
    name="强制止损",
    description="亏损8%强制止损",
    condition={
        'type': 'stop_loss',
        'max_loss_pct': -0.08,
    },
    action="force_sell",
    mandatory=True
)
```

### 3. 仓位规则 (Position Rules)

控制仓位大小：

```python
position_rule = StrategyRule(
    rule_id="pos_001",
    rule_type=RuleType.POSITION_SIZE,
    name="单股仓位限制",
    description="单股最多15%",
    condition={
        'type': 'position_limit',
        'max_position': 0.15,
    },
    action="adjust",
    mandatory=True
)
```

### 4. 风险规则 (Risk Rules)

账户级风控：

```python
risk_rule = StrategyRule(
    rule_id="risk_001",
    rule_type=RuleType.RISK,
    name="最大回撤限制",
    description="回撤20%停止交易",
    condition={
        'type': 'max_drawdown',
        'threshold': 0.20,
    },
    action="halt_trading",
    mandatory=True
)
```

### 5. 过滤规则 (Filter Rules)

股票池过滤：

```python
filter_rule = StrategyRule(
    rule_id="filter_001",
    rule_type=RuleType.FILTER,
    name="排除ST",
    description="不交易ST股票",
    condition={
        'type': 'stock_filter',
        'exclude_st': True,
    },
    action="reject",
    mandatory=True
)
```

## 规则优先级

规则按优先级（priority）执行，数字越小优先级越高：

- **1-10**: 最高优先级（风控、熔断）
- **11-30**: 高优先级（合规、重要业务规则）
- **31-50**: 中等优先级（一般业务规则）
- **51+**: 低优先级（监控、提示）

示例：

```python
# 高优先级：止损规则
stop_loss_rule = StrategyRule(
    rule_id="exit_stop_loss",
    priority=5,  # 最高优先级
    mandatory=True
)

# 低优先级：建议规则
suggestion_rule = StrategyRule(
    rule_id="suggest_001",
    priority=60,  # 低优先级
    mandatory=False  # 仅提示
)
```

## 审批工作流

### 自动执行模式

```python
executor.require_manual_approval = False
executor.auto_approve = True

# 规则通过 → 自动批准 → 立即执行
order = executor.process_signal(signal, market_data)
```

### 人工审批模式

```python
executor.require_manual_approval = True
executor.auto_approve = False

# 规则通过 → 等待审批 → 人工批准 → 执行
order = executor.process_signal(signal, market_data)

# 稍后批准
executor.approve_order(order.order_id, approver="风控经理")
```

### 半自动模式

```python
# 小额订单自动，大额订单人工审批
def should_require_approval(order):
    return order.target_price * order.quantity > 500000

if should_require_approval(order):
    # 等待审批
    pass
else:
    executor.approve_order(order.order_id, approver="system")
```

## 审计和报告

### 审计日志格式

每个交易动作都会生成审计日志：

```json
{
  "log_id": "order_001_0",
  "timestamp": "2024-02-24 10:30:15.123456",
  "strategy_name": "momentum_strategy",
  "order_id": "order_001",
  "event_type": "signal_generated",
  "details": {
    "signal": {
      "stock_code": "600519",
      "action": "buy"
    }
  },
  "operator": null
}
```

### 生成执行报告

```python
# 生成Markdown格式报告
report = executor.generate_execution_report(
    output_file="reports/daily_execution_2024-02-24.md"
)

# 报告内容包括：
# - 执行统计
# - 待处理订单列表
# - 已执行订单列表
# - 规则违反统计
# - 审计日志摘要
```

## 最佳实践

### 1. 规则设计原则

✅ **明确性**: 规则条件清晰明确，无歧义
✅ **可测试**: 规则可以用历史数据验证
✅ **分层**: 按重要性分层（强制/建议）
✅ **文档化**: 每条规则都有详细说明

❌ **避免**: 
- 规则过于复杂
- 规则相互冲突
- 规则过于宽松或过于严格

### 2. 版本管理

```python
# 每次修改规则后创建新版本
from src.core.strategy import StrategyVersion

version = StrategyVersion(
    version="1.1.0",
    create_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    author="策略团队",
    description="新增波动率过滤规则",
    parameters={'rule_count': 15},
    changes=[
        "新增entry_volatility规则",
        "调整止损阈值从-10%到-8%"
    ],
    status="testing"
)

strategy_doc.create_version(version)
```

### 3. 规则测试

上线前用历史数据测试规则：

```python
# 回测规则有效性
def backtest_rules(rule_engine, historical_signals):
    blocked_count = 0
    passed_count = 0
    
    for signal in historical_signals:
        is_valid, violations = rule_engine.validate_signal(
            signal, 
            historical_market_data
        )
        
        if is_valid:
            passed_count += 1
        else:
            blocked_count += 1
    
    print(f"通过: {passed_count}, 拒绝: {blocked_count}")
    print(f"拒绝率: {blocked_count / len(historical_signals):.2%}")
```

### 4. 定期复盘

每周/每月复盘规则执行情况：

```python
# 分析规则有效性
violations = rule_engine.get_violations(since="2024-02-01")

# 哪些规则最常被触发？
# 被拒绝的信号中，后来表现如何？
# 规则是否需要调整？
```

### 5. 应急机制

系统故障时的应急预案：

```python
# 紧急暂停所有交易
executor.trading_halted = True

# 紧急平仓
for position in current_positions:
    emergency_exit_order = create_exit_signal(position)
    # 绕过某些非关键规则
    rule_engine.disable_rule("non_critical_rule")
    executor.process_signal(emergency_exit_order, market_data)
```

## 常见问题

### Q1: 如何处理规则冲突？

A: 规则按priority执行，优先级高的先检查。如果高优先级规则已拒绝，不会继续检查低优先级规则。

### Q2: 如何临时禁用某个规则？

```python
# 临时禁用（需要有充分理由并记录）
rule_engine.disable_rule("rule_id")

# 记录原因
audit_log("禁用规则: rule_id, 原因: 特殊市场情况")

# 记得恢复
rule_engine.enable_rule("rule_id")
```

### Q3: 强制规则 vs 建议规则？

- **强制规则** (mandatory=True): 违反时拒绝交易，无例外
- **建议规则** (mandatory=False): 违反时仅警告，交易可继续

### Q4: 如何验证策略在实际执行中确实遵循了规则？

查看审计日志，每笔交易都记录了：
- 触发的规则
- 规则检查结果
- 违反的规则（如有）
- 最终执行决策

```python
# 验证合规性
for order in executor.get_executed_orders():
    assert order.rule_check_passed, f"订单{order.order_id}规则检查未通过却被执行"
    assert order.risk_check_passed, f"订单{order.order_id}风控检查未通过却被执行"
```

## 总结

严格的策略执行系统确保：

✅ **纪律性**: 交易完全遵循预定规则，避免情绪化
✅ **可追溯**: 每个决策都有完整记录
✅ **可优化**: 通过数据分析持续改进规则
✅ **风险可控**: 多层风控自动执行
✅ **合规性**: 满足监管和内部要求

记住：**策略的价值在于坚持执行，而非频繁调整。**
