"""
大宗交易数据（V3.3）

主 akshare；备 东方财富 HTTP（文档 1.3.2）。列: date, discount_pct, amount, buyer, seller。
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

DZJY_BUY_DISCOUNT_MAX = 0.03
DZJY_BUY_AMT_MIN = 1e8
DZJY_SELL_DISCOUNT_MIN = 0.05
DZJY_SELL_AMT_MIN = 0.5e8
LONG_TERM_BUYER_KEYWORDS = ["机构专用", "基金", "社保", "养老金", "公募"]
SELLER_RISK_KEYWORDS = ["控股股东", "董监高", "实际控制人", "减持"]
DZJY_VALID_DAYS = 5


def _fetch_dzjy_eastmoney(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    文档 1.3.2：东方财富大宗交易 HTTP 备用。push2.eastmoney 大宗列表，按标的过滤。
    返回列 date, discount_pct, amount, buyer, seller。
    """
    try:
        import requests
        code = symbol[-6:] if len(symbol) >= 6 else symbol.zfill(6)
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "fid": "f124", "po": "1", "pz": "100", "pn": "1", "np": "1",
            "fltt": "2", "invt": "2",
            "fields": "f12,f14,f2,f15,f16,f17,f18",
        }
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
        r = requests.get(url, params=params, headers=headers, timeout=12)
        if r.status_code != 200 or not r.text:
            return pd.DataFrame()
        data = r.json()
        diff = (data.get("data") or {}).get("diff") or []
        out = []
        for row in diff:
            if str(row.get("f12", "")) != code:
                continue
            out.append({
                "date": row.get("f17") or row.get("f18"),
                "discount_pct": float(row.get("f15", 0) or 0) / 100.0,
                "amount": float(row.get("f16", 0) or 0),
                "buyer": str(row.get("f18", "")),
                "seller": str(row.get("f19", "")),
            })
        if not out:
            return pd.DataFrame()
        df = pd.DataFrame(out)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["discount_pct"] = pd.to_numeric(df["discount_pct"], errors="coerce").fillna(0)
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
        return df.dropna(subset=["date"]).sort_values("date", ascending=False).reset_index(drop=True)
    except Exception as e:
        logger.debug("东方财富大宗 %s 失败: %s", symbol, e)
        return pd.DataFrame()


def _normalize_dzjy_df(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名与类型。"""
    df = df.rename(columns={
        "交易日期": "date", "折溢率": "discount_pct", "成交额": "amount",
        "买方营业部": "buyer", "卖方营业部": "seller",
    })
    for c in ["date", "amount"]:
        if c not in df.columns:
            return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    disc = df.get("discount_pct")
    if disc is not None:
        if disc.dtype == object:
            df["discount_pct"] = disc.astype(str).str.replace("%", "").map(lambda x: float(x) / 100.0 if x and x != "" else 0.0)
        else:
            df["discount_pct"] = pd.to_numeric(disc, errors="coerce").fillna(0) / 100.0
    else:
        df["discount_pct"] = 0.0
    df["buyer"] = df.get("buyer", pd.Series(dtype=object)).fillna("")
    df["seller"] = df.get("seller", pd.Series(dtype=object)).fillna("")
    return df.dropna(subset=["date"]).sort_values("date", ascending=False).reset_index(drop=True)


def fetch_stock_dzjy(symbol: str, trade_date: Optional[str] = None, days_back: int = 10) -> pd.DataFrame:
    """
    获取个股近期大宗交易。

    Returns
    -------
    pd.DataFrame
        列: date, discount_pct, amount, buyer, seller
    """
    end = trade_date or datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days_back + 5)).strftime("%Y%m%d")
    try:
        import akshare as ak
        df = ak.stock_dzjy_sctj(symbol=symbol, start_date=start, end_date=end)
        if df is not None and not df.empty:
            return _normalize_dzjy_df(df.copy())
        df_backup = _fetch_dzjy_eastmoney(symbol, start, end)
        if df_backup is not None and not df_backup.empty:
            logger.info("[dzjy] 标的=%s akshare 无数据，已用东方财富备用", symbol)
            return df_backup
        return pd.DataFrame()
    except Exception as e:
        logger.debug("fetch_stock_dzjy 失败 %s: %s", symbol, e)
        df_backup = _fetch_dzjy_eastmoney(symbol, start, end)
        if df_backup is not None and not df_backup.empty:
            logger.info("[dzjy] 标的=%s akshare 异常，已用东方财富备用", symbol)
            return df_backup
        return pd.DataFrame()


def get_dzjy_signal(symbol: str, trade_date: Optional[str] = None) -> Optional[Tuple[str, float, float]]:
    """
    大宗信号。

    Returns
    -------
    ("BUY"|"SELL", confidence, position) 或 None
    """
    df = fetch_stock_dzjy(symbol, trade_date=trade_date, days_back=DZJY_VALID_DAYS + 2)
    if df is None or df.empty:
        return None
    for _, row in df.iterrows():
        discount = float(row.get("discount_pct", 0) or 0)
        amount = float(row.get("amount", 0) or 0)
        buyer = str(row.get("buyer", "") or "")
        seller = str(row.get("seller", "") or "")
        if discount < DZJY_BUY_DISCOUNT_MAX and amount >= DZJY_BUY_AMT_MIN:
            if any(k in buyer for k in LONG_TERM_BUYER_KEYWORDS):
                return ("BUY", 0.5, 0.6)
        if discount > DZJY_SELL_DISCOUNT_MIN and amount >= DZJY_SELL_AMT_MIN:
            if any(k in seller for k in SELLER_RISK_KEYWORDS):
                return ("SELL", 0.8, 0.15)
    return None
