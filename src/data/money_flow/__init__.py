"""
资金流向数据（V3.4）：龙虎榜、大宗交易、实时主力资金流向

- 席位匹配与权重：normalize_seat_name, get_seat_weight
- 龙虎榜：fetch_stock_lhb, get_lhb_signal
- 大宗：fetch_stock_dzjy, get_dzjy_signal
- 实时资金流：fetch_realtime_fund_flow, get_realtime_flow_signal
"""

from .seat import normalize_seat_name, get_seat_weight
from .lhb import fetch_stock_lhb, get_lhb_signal, LHB_VALID_DAYS
from .dzjy import fetch_stock_dzjy, get_dzjy_signal, DZJY_VALID_DAYS
from .realtime_flow import fetch_realtime_fund_flow, get_realtime_flow_signal

__all__ = [
    "normalize_seat_name",
    "get_seat_weight",
    "fetch_stock_lhb",
    "get_lhb_signal",
    "LHB_VALID_DAYS",
    "fetch_stock_dzjy",
    "get_dzjy_signal",
    "DZJY_VALID_DAYS",
    "fetch_realtime_fund_flow",
    "get_realtime_flow_signal",
]
