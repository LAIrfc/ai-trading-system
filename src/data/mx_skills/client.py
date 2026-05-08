"""
统一的妙想 API 客户端 — 封装所有 5 个 skill 的 HTTP 调用。

各 skill 有独立配额，由 RateLimiter 按 skill 分别管控。
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from .rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

_BASE = "https://mkapi2.dfcfs.com/finskillshub"

_PATH_TO_SKILL = {
    "/api/claw/query": "mx-data",
    "/api/claw/news-search": "mx-search",
    "/api/claw/stock-screen": "mx-xuangu",
    "/api/claw/self-select/get": "mx-zixuan",
    "/api/claw/self-select/manage": "mx-zixuan",
    "/api/claw/mockTrading/positions": "mx-moni",
    "/api/claw/mockTrading/balance": "mx-moni",
    "/api/claw/mockTrading/orders": "mx-moni",
    "/api/claw/mockTrading/trade": "mx-moni",
    "/api/claw/mockTrading/cancel": "mx-moni",
}


def _resolve_skill(path: str) -> str:
    normalized = path if path.startswith("/") else f"/{path}"
    return _PATH_TO_SKILL.get(normalized, "mx-data")


class MXQuotaExhausted(Exception):
    """当日某 skill API 调用次数已用尽"""


class MXClient:
    """东方财富妙想 API 统一客户端"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("MX_APIKEY", "")
        if not self.api_key:
            raise ValueError(
                "MX_APIKEY 未设置。请 export MX_APIKEY=your_key 或传入 api_key 参数"
            )
        self._limiter = get_rate_limiter()
        self._server_exhausted: Dict[str, bool] = {}

    # ─── internal ────────────────────────────────────────────────────

    def _post(self, path: str, body: dict, timeout: int = 30) -> dict:
        skill = _resolve_skill(path)
        if self._server_exhausted.get(skill):
            raise MXQuotaExhausted(
                f"妙想 {skill} 今日服务端配额已耗尽"
            )
        self._limiter.force_consume(1, skill=skill)
        headers = {"Content-Type": "application/json", "apikey": self.api_key}
        url = f"{_BASE}{path}" if path.startswith("/") else f"{_BASE}/{path}"
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != 0:
                msg = str(data.get("message", ""))
                if any(kw in msg for kw in ("配额", "限额", "次数", "quota", "limit", "exceed")):
                    self._server_exhausted[skill] = True
                    logger.warning("妙想 %s 服务端配额耗尽: %s", skill, msg)
                    raise MXQuotaExhausted(f"妙想 {skill} 服务端配额耗尽: {msg}")
            return data
        except MXQuotaExhausted:
            raise
        except Exception:
            logger.exception("MX API 请求失败: %s (skill=%s)", path, skill)
            raise

    # ─── mx-data (金融数据) ──────────────────────────────────────────

    def query_data(self, question: str) -> dict:
        """自然语言查询金融数据（行情/财务/关系）"""
        return self._post("/api/claw/query", {"toolQuery": question})

    def query_data_df(self, question: str) -> pd.DataFrame:
        """查询金融数据并转换为 DataFrame（取第一个表）"""
        raw = self.query_data(question)
        return _data_to_df(raw)

    # ─── mx-search (资讯搜索) ────────────────────────────────────────

    def search_news(self, query: str) -> dict:
        """搜索金融资讯（研报/新闻/公告）"""
        return self._post("/api/claw/news-search", {"query": query})

    def search_news_items(self, query: str) -> List[Dict[str, Any]]:
        """搜索资讯并返回结构化列表: [{title, content, date, source, type}, ...]"""
        raw = self.search_news(query)
        return _extract_news_items(raw)

    # ─── mx-xuangu (智能选股) ────────────────────────────────────────

    def screen_stocks(self, condition: str) -> dict:
        """按自然语言条件筛选股票"""
        return self._post("/api/claw/stock-screen", {"keyword": condition})

    def screen_stocks_df(self, condition: str) -> pd.DataFrame:
        """选股并返回 DataFrame"""
        raw = self.screen_stocks(condition)
        return _xuangu_to_df(raw)

    # ─── mx-zixuan (自选股) ──────────────────────────────────────────

    def get_watchlist(self) -> dict:
        return self._post("/api/claw/self-select/get", {})

    def manage_watchlist(self, instruction: str) -> dict:
        return self._post("/api/claw/self-select/manage", {"query": instruction})

    def get_watchlist_df(self) -> pd.DataFrame:
        """获取自选股列表，返回 DataFrame"""
        raw = self.get_watchlist()
        return _zixuan_to_df(raw)

    # ─── mx-moni (模拟交易) ──────────────────────────────────────────

    def moni_positions(self) -> dict:
        return self._post("/api/claw/mockTrading/positions", {"moneyUnit": 1})

    def moni_balance(self) -> dict:
        return self._post("/api/claw/mockTrading/balance", {"moneyUnit": 1})

    def moni_orders(self) -> dict:
        return self._post(
            "/api/claw/mockTrading/orders",
            {"fltOrderDrt": 0, "fltOrderStatus": 0},
        )

    def moni_buy(
        self,
        stock_code: str,
        quantity: int,
        price: Optional[float] = None,
        market_price: bool = False,
    ) -> dict:
        body: Dict[str, Any] = {
            "type": "buy",
            "stockCode": stock_code,
            "quantity": quantity,
            "useMarketPrice": market_price,
        }
        if not market_price and price is not None:
            body["price"] = price
        return self._post("/api/claw/mockTrading/trade", body)

    def moni_sell(
        self,
        stock_code: str,
        quantity: int,
        price: Optional[float] = None,
        market_price: bool = False,
    ) -> dict:
        body: Dict[str, Any] = {
            "type": "sell",
            "stockCode": stock_code,
            "quantity": quantity,
            "useMarketPrice": market_price,
        }
        if not market_price and price is not None:
            body["price"] = price
        return self._post("/api/claw/mockTrading/trade", body)

    def moni_cancel(self, order_id: Optional[str] = None) -> dict:
        body: Dict[str, Any] = (
            {"type": "order", "orderId": order_id}
            if order_id
            else {"type": "all"}
        )
        return self._post("/api/claw/mockTrading/cancel", body)

    # ─── 便捷方法 ───────────────────────────────────────────────────

    @property
    def quota_status(self) -> dict:
        return self._limiter.status()


# ═══════════════════════════════════════════════════════════════════
# 结果解析辅助函数
# ═══════════════════════════════════════════════════════════════════


def _safe_filename(s: str, max_len: int = 80) -> str:
    s = re.sub(r'[<>:"/\\|?*\[\]]', "_", s)
    return s.strip().replace(" ", "_")[:max_len] or "query"


def _data_to_df(raw: dict) -> pd.DataFrame:
    """把 mx-data API 返回转成 DataFrame（取第一个 dataTable）"""
    if not isinstance(raw, dict) or raw.get("status") != 0:
        return pd.DataFrame()
    _d1 = raw.get("data")
    if not isinstance(_d1, dict):
        return pd.DataFrame()
    _d2 = _d1.get("data")
    if not isinstance(_d2, dict):
        return pd.DataFrame()
    _d3 = _d2.get("searchDataResultDTO")
    if not isinstance(_d3, dict):
        return pd.DataFrame()
    dto_list = _d3.get("dataTableDTOList", [])
    if not dto_list:
        return pd.DataFrame()
    dto = dto_list[0]
    table = dto.get("table", {})
    name_map = dto.get("nameMap", {})
    if not isinstance(table, dict):
        return pd.DataFrame()
    headers = table.get("headName", [])
    if not headers:
        return pd.DataFrame()
    indicator_keys = [k for k in table if k != "headName"]
    records = []
    for i, h in enumerate(headers):
        row = {"date": h}
        for k in indicator_keys:
            vals = table.get(k, [])
            label = name_map.get(k, k) if isinstance(name_map, dict) else k
            row[str(label)] = vals[i] if i < len(vals) else None
        records.append(row)
    return pd.DataFrame(records)


def _extract_news_items(raw: dict) -> List[Dict[str, Any]]:
    """从 mx-search 结果提取结构化新闻列表"""
    if raw.get("status") != 0:
        return []
    items = (
        (raw.get("data") or {})
        .get("data") or {}
    )
    items = (items.get("llmSearchResponse") or {}).get("data", [])
    result = []
    for it in items or []:
        result.append(
            {
                "title": it.get("title", ""),
                "content": it.get("content", ""),
                "date": it.get("date", ""),
                "source": it.get("insName", "东方财富"),
                "type": it.get("informationType", ""),
            }
        )
    return result


def _xuangu_to_df(raw: dict) -> pd.DataFrame:
    """把 mx-xuangu API 返回转为 DataFrame"""
    if raw.get("status") != 0:
        return pd.DataFrame()
    data = raw.get("data", {}).get("data", {})
    data_list = data.get("allResults", {}).get("result", {}).get("dataList", [])
    columns = data.get("allResults", {}).get("result", {}).get("columns", [])
    if not data_list:
        return pd.DataFrame()
    col_map = {}
    for c in columns or []:
        key = c.get("field") or c.get("name") or c.get("key", "")
        title = c.get("displayName") or c.get("title") or c.get("label", key)
        if key:
            col_map[key] = title
    rows = []
    for item in data_list:
        row = {}
        for k, v in item.items():
            row[col_map.get(k, k)] = v
        rows.append(row)
    return pd.DataFrame(rows)


def _zixuan_to_df(raw: dict) -> pd.DataFrame:
    """把 mx-zixuan API 返回转为 DataFrame"""
    data_list = (
        raw.get("data", {})
        .get("allResults", {})
        .get("result", {})
        .get("dataList", [])
    )
    if not data_list:
        return pd.DataFrame()
    return pd.DataFrame(data_list)


# ─── 全局单例 ────────────────────────────────────────────────────

_global_client: Optional[MXClient] = None


def get_mx_client() -> MXClient:
    global _global_client
    if _global_client is None:
        _global_client = MXClient()
    return _global_client
