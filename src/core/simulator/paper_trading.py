"""
模拟交易系统（纸面交易）
用于测试策略，无真实资金风险
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from loguru import logger


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"      # 待成交
    FILLED = "filled"        # 已成交
    CANCELLED = "cancelled"  # 已取消
    REJECTED = "rejected"    # 已拒绝


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    """订单"""
    order_id: str
    stock_code: str
    side: OrderSide
    price: float
    quantity: int
    status: OrderStatus = OrderStatus.PENDING
    filled_price: float = 0.0
    filled_quantity: int = 0
    filled_time: Optional[datetime] = None
    create_time: datetime = field(default_factory=datetime.now)
    commission: float = 0.0  # 手续费
    
    def to_dict(self):
        return {
            'order_id': self.order_id,
            'stock_code': self.stock_code,
            'side': self.side.value,
            'price': self.price,
            'quantity': self.quantity,
            'status': self.status.value,
            'filled_price': self.filled_price,
            'filled_quantity': self.filled_quantity,
            'filled_time': self.filled_time.isoformat() if self.filled_time else None,
            'create_time': self.create_time.isoformat(),
            'commission': self.commission,
        }


@dataclass
class Position:
    """持仓"""
    stock_code: str
    quantity: int
    cost_price: float  # 成本价
    current_price: float = 0.0  # 当前价
    
    @property
    def market_value(self) -> float:
        """市值"""
        return self.quantity * self.current_price
    
    @property
    def cost_value(self) -> float:
        """成本"""
        return self.quantity * self.cost_price
    
    @property
    def profit(self) -> float:
        """浮动盈亏"""
        return self.market_value - self.cost_value
    
    @property
    def profit_pct(self) -> float:
        """盈亏比例"""
        if self.cost_value == 0:
            return 0.0
        return (self.profit / self.cost_value) * 100
    
    def to_dict(self):
        return {
            'stock_code': self.stock_code,
            'quantity': self.quantity,
            'cost_price': self.cost_price,
            'current_price': self.current_price,
            'market_value': self.market_value,
            'profit': self.profit,
            'profit_pct': self.profit_pct,
        }


@dataclass
class Trade:
    """成交记录"""
    trade_id: str
    order_id: str
    stock_code: str
    side: OrderSide
    price: float
    quantity: int
    amount: float  # 成交金额
    commission: float  # 手续费
    trade_time: datetime = field(default_factory=datetime.now)
    
    def to_dict(self):
        return {
            'trade_id': self.trade_id,
            'order_id': self.order_id,
            'stock_code': self.stock_code,
            'side': self.side.value,
            'price': self.price,
            'quantity': self.quantity,
            'amount': self.amount,
            'commission': self.commission,
            'trade_time': self.trade_time.isoformat(),
        }


class PaperTradingAccount:
    """模拟交易账户"""
    
    def __init__(self, initial_capital: float = 100000.0, 
                 commission_rate: float = 0.0003):
        """
        初始化模拟账户
        
        Args:
            initial_capital: 初始资金（默认10万）
            commission_rate: 手续费率（默认万三）
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital  # 可用资金
        self.commission_rate = commission_rate
        
        self.positions: Dict[str, Position] = {}  # 持仓
        self.orders: Dict[str, Order] = {}  # 订单
        self.trades: List[Trade] = []  # 成交记录
        
        self.order_counter = 0
        self.trade_counter = 0
        
        logger.info(f"模拟账户已创建，初始资金: {initial_capital:,.2f}元")
    
    def _generate_order_id(self) -> str:
        """生成订单ID"""
        self.order_counter += 1
        return f"ORDER_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.order_counter:04d}"
    
    def _generate_trade_id(self) -> str:
        """生成成交ID"""
        self.trade_counter += 1
        return f"TRADE_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.trade_counter:04d}"
    
    def _calculate_commission(self, amount: float) -> float:
        """计算手续费"""
        commission = amount * self.commission_rate
        # 最低5元
        return max(5.0, commission)
    
    def buy(self, stock_code: str, price: float, quantity: int) -> Tuple[bool, str]:
        """
        买入股票
        
        Args:
            stock_code: 股票代码
            price: 价格
            quantity: 数量（必须是100的倍数）
            
        Returns:
            (成功与否, 订单ID或错误信息)
        """
        # 检查数量
        if quantity <= 0 or quantity % 100 != 0:
            return False, "数量必须是100的正整数倍"
        
        # 计算所需资金
        amount = price * quantity
        commission = self._calculate_commission(amount)
        total_cost = amount + commission
        
        # 检查资金
        if self.cash < total_cost:
            return False, f"资金不足，需要{total_cost:.2f}元，可用{self.cash:.2f}元"
        
        # 创建订单
        order = Order(
            order_id=self._generate_order_id(),
            stock_code=stock_code,
            side=OrderSide.BUY,
            price=price,
            quantity=quantity,
            status=OrderStatus.PENDING,
        )
        
        # 立即成交（模拟）
        self._fill_order(order, price, quantity, commission)
        
        logger.info(f"买入成交: {stock_code} {quantity}股 @ {price:.2f}元")
        
        return True, order.order_id
    
    def sell(self, stock_code: str, price: float, quantity: int) -> Tuple[bool, str]:
        """
        卖出股票
        
        Args:
            stock_code: 股票代码
            price: 价格
            quantity: 数量
            
        Returns:
            (成功与否, 订单ID或错误信息)
        """
        # 检查持仓
        if stock_code not in self.positions:
            return False, f"没有持仓 {stock_code}"
        
        position = self.positions[stock_code]
        if position.quantity < quantity:
            return False, f"持仓不足，持有{position.quantity}股，卖出{quantity}股"
        
        # 创建订单
        order = Order(
            order_id=self._generate_order_id(),
            stock_code=stock_code,
            side=OrderSide.SELL,
            price=price,
            quantity=quantity,
            status=OrderStatus.PENDING,
        )
        
        # 计算手续费和印花税
        amount = price * quantity
        commission = self._calculate_commission(amount)
        stamp_tax = amount * 0.001  # 印花税千分之一
        total_commission = commission + stamp_tax
        
        # 立即成交
        self._fill_order(order, price, quantity, total_commission)
        
        logger.info(f"卖出成交: {stock_code} {quantity}股 @ {price:.2f}元")
        
        return True, order.order_id
    
    def _fill_order(self, order: Order, price: float, quantity: int, commission: float):
        """成交订单"""
        order.status = OrderStatus.FILLED
        order.filled_price = price
        order.filled_quantity = quantity
        order.filled_time = datetime.now()
        order.commission = commission
        
        # 保存订单
        self.orders[order.order_id] = order
        
        # 创建成交记录
        amount = price * quantity
        trade = Trade(
            trade_id=self._generate_trade_id(),
            order_id=order.order_id,
            stock_code=order.stock_code,
            side=order.side,
            price=price,
            quantity=quantity,
            amount=amount,
            commission=commission,
        )
        self.trades.append(trade)
        
        # 更新持仓和资金
        if order.side == OrderSide.BUY:
            self._update_position_buy(order.stock_code, price, quantity)
            self.cash -= (amount + commission)
        else:
            self._update_position_sell(order.stock_code, quantity)
            self.cash += (amount - commission)
    
    def _update_position_buy(self, stock_code: str, price: float, quantity: int):
        """更新持仓（买入）"""
        if stock_code in self.positions:
            # 已有持仓，更新成本价
            pos = self.positions[stock_code]
            total_cost = pos.cost_price * pos.quantity + price * quantity
            total_quantity = pos.quantity + quantity
            pos.cost_price = total_cost / total_quantity
            pos.quantity = total_quantity
        else:
            # 新建持仓
            self.positions[stock_code] = Position(
                stock_code=stock_code,
                quantity=quantity,
                cost_price=price,
                current_price=price,
            )
    
    def _update_position_sell(self, stock_code: str, quantity: int):
        """更新持仓（卖出）"""
        pos = self.positions[stock_code]
        pos.quantity -= quantity
        
        # 如果清仓，删除持仓
        if pos.quantity == 0:
            del self.positions[stock_code]
    
    def update_market_prices(self, prices: Dict[str, float]):
        """
        更新市场价格
        
        Args:
            prices: {股票代码: 当前价格}
        """
        for code, price in prices.items():
            if code in self.positions:
                self.positions[code].current_price = price
    
    @property
    def total_market_value(self) -> float:
        """持仓总市值"""
        return sum(pos.market_value for pos in self.positions.values())
    
    @property
    def total_assets(self) -> float:
        """总资产"""
        return self.cash + self.total_market_value
    
    @property
    def total_profit(self) -> float:
        """总盈亏"""
        return self.total_assets - self.initial_capital
    
    @property
    def total_profit_pct(self) -> float:
        """总盈亏比例"""
        return (self.total_profit / self.initial_capital) * 100
    
    def get_account_info(self) -> Dict:
        """获取账户信息"""
        return {
            'initial_capital': self.initial_capital,
            'cash': self.cash,
            'market_value': self.total_market_value,
            'total_assets': self.total_assets,
            'total_profit': self.total_profit,
            'total_profit_pct': self.total_profit_pct,
            'position_count': len(self.positions),
            'order_count': len(self.orders),
            'trade_count': len(self.trades),
        }
    
    def get_positions(self) -> List[Dict]:
        """获取持仓列表"""
        return [pos.to_dict() for pos in self.positions.values()]
    
    def get_orders(self, stock_code: Optional[str] = None) -> List[Dict]:
        """获取订单列表"""
        orders = self.orders.values()
        if stock_code:
            orders = [o for o in orders if o.stock_code == stock_code]
        return [o.to_dict() for o in orders]
    
    def get_trades(self, stock_code: Optional[str] = None) -> List[Dict]:
        """获取成交记录"""
        trades = self.trades
        if stock_code:
            trades = [t for t in trades if t.stock_code == stock_code]
        return [t.to_dict() for t in trades]
    
    def save_to_file(self, filename: str):
        """保存账户到文件"""
        data = {
            'account_info': self.get_account_info(),
            'positions': self.get_positions(),
            'orders': self.get_orders(),
            'trades': self.get_trades(),
            'saved_time': datetime.now().isoformat(),
        }
        
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"账户已保存到: {filename}")
    
    def print_summary(self):
        """打印账户摘要"""
        print("\n" + "="*60)
        print("  模拟账户摘要")
        print("="*60)
        
        info = self.get_account_info()
        
        print(f"\n💰 资金情况:")
        print(f"   初始资金: {info['initial_capital']:,.2f}元")
        print(f"   可用资金: {info['cash']:,.2f}元")
        print(f"   持仓市值: {info['market_value']:,.2f}元")
        print(f"   总资产:   {info['total_assets']:,.2f}元")
        
        profit_emoji = "📈" if info['total_profit'] >= 0 else "📉"
        print(f"\n{profit_emoji} 盈亏:")
        print(f"   盈亏金额: {info['total_profit']:+,.2f}元")
        print(f"   盈亏比例: {info['total_profit_pct']:+.2f}%")
        
        print(f"\n📊 持仓 ({info['position_count']}只):")
        if self.positions:
            for pos in self.positions.values():
                profit_emoji = "📈" if pos.profit >= 0 else "📉"
                print(f"   {profit_emoji} {pos.stock_code}")
                print(f"      数量: {pos.quantity}股")
                print(f"      成本: {pos.cost_price:.2f}元")
                print(f"      现价: {pos.current_price:.2f}元")
                print(f"      盈亏: {pos.profit:+,.2f}元 ({pos.profit_pct:+.2f}%)")
        else:
            print("   暂无持仓")
        
        print(f"\n📝 统计:")
        print(f"   订单数: {info['order_count']}")
        print(f"   成交数: {info['trade_count']}")
        
        print("\n" + "="*60)
