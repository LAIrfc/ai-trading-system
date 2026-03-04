"""
龙虎榜数据（V3.3）

个股龙虎榜明细：交易日期、营业部、买入/卖出/净额、占流通市值比等。
数据源：主 akshare 东方财富个股龙虎榜；备 同花顺 HTML（需 10JQKA_COOKIE），文档 1.3.2。
"""

import os
import re
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# 连续 2 日同席位、占比 > 0.1%、机构权重 > 1.2
LHB_RATIO_THRESHOLD = 0.001
LHB_SEAT_WEIGHT_THRESHOLD = 1.2
LHB_VALID_DAYS = 3


def _fetch_lhb_10jqka(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    文档 1.3.2 备1：同花顺龙虎榜 data.10jqka.com.cn/lhb/ggcx/，GET，需 10JQKA_COOKIE。
    解析 HTML 表格，返回列 date, seat_name, buy_amt, sell_amt, net_amt, ratio_pct。
    """
    cookie = os.environ.get("10JQKA_COOKIE", "").strip()
    if not cookie:
        return pd.DataFrame()
    try:
        import requests
        from bs4 import BeautifulSoup
        code = symbol[-6:] if len(symbol) >= 6 else symbol.zfill(6)
        out = []
        start_d = datetime.strptime(start[:8], "%Y%m%d")
        end_d = datetime.strptime(end[:8], "%Y%m%d")
        for d in pd.date_range(start_d, end_d, freq="D"):
            date_str = d.strftime("%Y-%m-%d")
            url = "https://data.10jqka.com.cn/lhb/ggcx/"
            params = {"date": date_str, "page": 1}
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Cookie": cookie}
            r = requests.get(url, params=params, headers=headers, timeout=12)
            if r.status_code != 200 or not r.text:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            tables = soup.find_all("table")
            for tbl in tables:
                rows = tbl.find_all("tr")
                for tr in rows[1:]:
                    tds = tr.find_all(["td", "th"])
                    if len(tds) < 4:
                        continue
                    texts = [t.get_text(strip=True) for t in tds]
                    if code and code not in "".join(texts):
                        continue
                    seat_name = texts[1] if len(texts) > 1 else ""
                    nums = re.findall(r"[-\d.]+", " ".join(texts[2:]))
                    buy_amt = float(nums[0]) * 1e4 if len(nums) > 0 else 0.0
                    sell_amt = float(nums[1]) * 1e4 if len(nums) > 1 else 0.0
                    net_amt = buy_amt - sell_amt
                    ratio_pct = float(nums[2]) / 100.0 if len(nums) > 2 and "." in str(nums[2]) else 0.0
                    out.append({"date": date_str, "seat_name": seat_name, "buy_amt": buy_amt, "sell_amt": sell_amt, "net_amt": net_amt, "ratio_pct": ratio_pct})
        if not out:
            return pd.DataFrame()
        df = pd.DataFrame(out)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    except Exception as e:
        logger.debug("同花顺龙虎榜 %s 失败: %s", symbol, e)
        return pd.DataFrame()


def fetch_stock_lhb(
    symbol: str,
    trade_date: Optional[str] = None,
    days_back: int = 5,
) -> pd.DataFrame:
    """
    获取个股近期龙虎榜明细。

    Returns
    -------
    pd.DataFrame
        列: date, seat_name, buy_amt, sell_amt, net_amt, ratio_pct（占流通市值比例，若可得）
        无数据或失败返回空 DataFrame。
    """
    end = trade_date or datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days_back + 5)).strftime("%Y%m%d")
    prefetch_dir = os.environ.get("BACKTEST_PREFETCH_DIR", "").strip()
    if prefetch_dir:
        path = os.path.join(prefetch_dir, "lhb", f"{symbol}.parquet")
        if os.path.isfile(path):
            try:
                return pd.read_parquet(path)
            except Exception as e:
                logger.debug("回测预取龙虎榜 %s 读本地失败: %s", symbol, e)
    try:
        import akshare as ak
        # 东方财富个股龙虎榜：按日、买入/卖出分别接口
        out = []
        for flag in ["买入", "卖出"]:
            try:
                df = ak.stock_lhb_stock_detail_em(symbol=symbol, start_date=start, end_date=end, flag=flag)
                if df is None or df.empty:
                    continue
                # 列名兼容：akshare 版本可能不同
                col_map = {
                    "交易日期": "date", "日期": "date",
                    "营业部名称": "seat_name", "营业部": "seat_name",
                    "买入金额": "buy_amt", "买入": "buy_amt",
                    "卖出金额": "sell_amt", "卖出": "sell_amt",
                    "净额": "net_amt", "净买入": "net_amt", "净买": "net_amt",
                }
                df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
                if "date" not in df.columns or "seat_name" not in df.columns:
                    continue
                df["buy_amt"] = pd.to_numeric(df.get("buy_amt", 0), errors="coerce").fillna(0)
                df["sell_amt"] = pd.to_numeric(df.get("sell_amt", 0), errors="coerce").fillna(0)
                df["net_amt"] = pd.to_numeric(df.get("net_amt", 0), errors="coerce").fillna(0)
                ratio_col = [c for c in df.columns if "比例" in str(c) or "占比" in str(c)]
                df["ratio_pct"] = pd.to_numeric(df.get(ratio_col[0] if ratio_col else "ratio_pct", 0), errors="coerce").fillna(0)
                if "ratio_pct" in df.columns and df["ratio_pct"].max() > 1:
                    df["ratio_pct"] = df["ratio_pct"] / 100.0
                out.append(df)
            except Exception as e:
                logger.debug("龙虎榜 %s %s 失败: %s", symbol, flag, e)
        if not out:
            df_backup = _fetch_lhb_10jqka(symbol, start, end)
            if df_backup is not None and not df_backup.empty:
                logger.info("[lhb] 标的=%s akshare 无数据，已用同花顺备用", symbol)
                return df_backup
            return pd.DataFrame()
        merged = pd.concat(out, ignore_index=True)
        merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
        return merged.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    except Exception as e:
        logger.debug("fetch_stock_lhb 失败 %s: %s", symbol, e)
        df_backup = _fetch_lhb_10jqka(symbol, start, end)
        if df_backup is not None and not df_backup.empty:
            logger.info("[lhb] 标的=%s akshare 异常，已用同花顺备用", symbol)
            return df_backup
        return pd.DataFrame()


def get_lhb_signal(
    symbol: str,
    trade_date: Optional[str] = None,
) -> Optional[Tuple[str, float, float]]:
    """
    龙虎榜信号：连续 2 日同席位净买/卖、占比>0.1%、机构权重>1.2。

    Returns
    -------
    ("BUY"|"SELL", confidence, position) 或 None
        confidence = min(累计占比/0.2%, 1) × 席位权重均值
    """
    from .seat import normalize_seat_name, get_seat_weight
    df = fetch_stock_lhb(symbol, trade_date=trade_date, days_back=10)
    if df is None or len(df) < 2:
        return None
    df = df.copy()
    df["seat_key"] = df["seat_name"].map(normalize_seat_name)
    df["weight"] = df["seat_name"].map(get_seat_weight)
    # 按日期分组，找连续两日同一 seat_key 同向净买或净卖
    dates = sorted(df["date"].dropna().unique())
    if len(dates) < 2:
        return None
    for i in range(len(dates) - 1):
        d1, d2 = dates[i], dates[i + 1]
        g1 = df[df["date"] == d1]
        g2 = df[df["date"] == d2]
        for _, r1 in g1.iterrows():
            key = r1["seat_key"]
            w1 = r1["weight"]
            if w1 <= LHB_SEAT_WEIGHT_THRESHOLD:
                continue
            net1 = float(r1.get("net_amt", 0) or 0)
            ratio1 = float(r1.get("ratio_pct", 0) or 0)
            match = g2[g2["seat_key"] == key]
            if match.empty:
                continue
            for _, r2 in match.iterrows():
                w2 = r2["weight"]
                if w2 <= LHB_SEAT_WEIGHT_THRESHOLD:
                    continue
                net2 = float(r2.get("net_amt", 0) or 0)
                ratio2 = float(r2.get("ratio_pct", 0) or 0)
                total_ratio = ratio1 + ratio2
                if total_ratio <= LHB_RATIO_THRESHOLD:
                    continue
                mean_w = (w1 + w2) / 2
                conf = min(1.0, total_ratio / 0.002) * mean_w
                conf = min(1.0, conf)
                if net1 > 0 and net2 > 0:
                    return ("BUY", conf, 0.7)
                if net1 < 0 and net2 < 0:
                    return ("SELL", conf, 0.2)
    return None
