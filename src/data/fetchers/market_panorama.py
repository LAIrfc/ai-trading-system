"""
市场全景数据采集

提供三大板块的一站式采集：
1. 热点板块排行（概念/行业板块涨幅+资金流入 TOP）
2. 大盘指数行情（上证/深证/创业板/科创50/北证50）
3. 市场情绪快照（涨跌家数、涨跌停、两市成交额、北向资金）

数据源：akshare（免费、稳定），备用东方财富/腾讯接口。
"""

import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TypeVar

import pandas as pd

logger = logging.getLogger(__name__)

_AK = None
T = TypeVar("T")

_MAX_RETRIES = 2
_RETRY_DELAY = 1.5


def _get_ak():
    """延迟加载 akshare，避免 import 时开销。"""
    global _AK
    if _AK is None:
        import akshare as ak
        _AK = ak
    return _AK


def _retry_call(fn: Callable[[], T], label: str, retries: int = _MAX_RETRIES) -> T:
    """带重试的函数调用，应对 akshare 连接不稳定。"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < retries:
                logger.debug("%s 第 %d 次失败，%0.1fs 后重试: %s", label, attempt + 1, _RETRY_DELAY, e)
                time.sleep(_RETRY_DELAY)
    raise last_err  # type: ignore[misc]


# ============================================================
# 1. 热点板块排行 + 板块资金流向
# ============================================================

def get_hot_concept_sectors(top_n: int = 15) -> List[Dict[str, Any]]:
    """获取概念板块涨幅排行。优先新浪，备用 akshare。"""
    result = _fetch_board_rank_sina("concept", top_n)
    if result:
        return result

    try:
        ak = _get_ak()
        df = _retry_call(lambda: ak.stock_board_concept_name_em(), "概念板块排行")
        if df is None or df.empty:
            return []
        return _df_to_board_list(df, "concept", top_n)
    except Exception as e:
        logger.error("概念板块排行获取失败: %s", e)
        return []


def get_hot_industry_sectors(top_n: int = 15) -> List[Dict[str, Any]]:
    """获取行业板块涨幅排行。优先新浪，备用 akshare。"""
    result = _fetch_board_rank_sina("industry", top_n)
    if result:
        return result

    try:
        ak = _get_ak()
        df = _retry_call(lambda: ak.stock_board_industry_name_em(), "行业板块排行")
        if df is None or df.empty:
            return []
        return _df_to_board_list(df, "industry", top_n)
    except Exception as e:
        logger.error("行业板块排行获取失败: %s", e)
        return []


def _df_to_board_list(df: pd.DataFrame, board_type: str, top_n: int) -> List[Dict[str, Any]]:
    """将 akshare 板块 DataFrame 转为标准列表。"""
    df = df.sort_values("涨跌幅", ascending=False).head(top_n)
    result = []
    for _, row in df.iterrows():
        result.append({
            "name": row.get("板块名称", ""),
            "change_pct": _safe_float(row.get("涨跌幅")),
            "leader_stock": row.get("领涨股票", ""),
            "leader_change": _safe_float(row.get("领涨股票-涨跌幅")),
            "total_market_cap": _safe_float(row.get("总市值")),
            "turnover": _safe_float(row.get("换手率")),
            "type": board_type,
        })
    logger.info("%s板块排行获取成功 (akshare): %d 条", board_type, len(result))
    return result


def _fetch_board_rank_sina(board_type: str, top_n: int) -> List[Dict[str, Any]]:
    """
    通过新浪财经接口获取板块排行。
    - 行业板块: http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php
    - 概念板块: http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class

    返回格式: code, name, stock_count, avg_price, avg_change_pct, avg_change_amount,
              total_volume, total_amount, leader_code, leader_change_pct,
              leader_price, leader_change_amount, leader_name
    """
    import json
    import re

    try:
        import requests

        if board_type == "industry":
            url = "http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
        else:
            url = "http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class"

        r = requests.get(url, timeout=10, headers={
            "Referer": "http://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        })

        if r.status_code != 200 or not r.text.strip():
            return []

        m = re.search(r"var\s+\w+\s*=\s*(\{.*\})", r.text, re.DOTALL)
        if not m:
            return []

        data = json.loads(m.group(1))
        sectors = []
        for val in data.values():
            parts = val.split(",")
            if len(parts) < 10:
                continue
            try:
                sectors.append({
                    "name": parts[1],
                    "change_pct": float(parts[4]) if parts[4] else 0,
                    "leader_stock": parts[12] if len(parts) > 12 else "",
                    "leader_change": float(parts[9]) if parts[9] else 0,
                    "total_market_cap": None,
                    "turnover": None,
                    "stock_count": int(parts[2]) if parts[2] else 0,
                    "total_amount": float(parts[7]) if parts[7] else 0,
                    "type": board_type,
                })
            except (ValueError, IndexError):
                continue

        sectors.sort(key=lambda x: x["change_pct"], reverse=True)
        result = sectors[:top_n]

        if result:
            logger.info(
                "%s板块排行获取成功 (新浪): %d/%d 条",
                board_type, len(result), len(sectors),
            )
        return result

    except Exception as e:
        logger.debug("新浪 %s板块排行失败: %s", board_type, e)
        return []


def get_sector_fund_flow(sector_type: str = "concept", top_n: int = 10) -> List[Dict[str, Any]]:
    """
    获取板块资金流向排行。

    优先 akshare（东方财富数据），若被反爬拦截则用新浪板块成交额排序近似。

    Parameters
    ----------
    sector_type : str
        "concept" 概念板块 / "industry" 行业板块
    top_n : int
        返回 TOP N

    Returns
    -------
    list of dict
        name, change_pct, main_net_inflow (主力净流入，元), main_net_pct (主力净占比%)
    """
    try:
        ak = _get_ak()
        flow_type = "概念资金流" if sector_type == "concept" else "行业资金流"
        df = _retry_call(
            lambda: ak.stock_sector_fund_flow_rank(indicator="今日", sector_type=flow_type),
            f"板块资金流向({sector_type})",
        )

        if df is None or df.empty:
            logger.warning("板块资金流向数据为空 (%s)", sector_type)
            return _get_sector_fund_flow_fallback(sector_type, top_n)

        result = []
        for _, row in df.head(top_n).iterrows():
            result.append({
                "name": row.get("名称", ""),
                "change_pct": _safe_float(row.get("今日涨跌幅")),
                "main_net_inflow": _safe_float(row.get("主力净流入-净额")),
                "main_net_pct": _safe_float(row.get("主力净流入-净占比")),
                "type": sector_type,
            })
        logger.info("板块资金流向获取成功 (%s): %d 条", sector_type, len(result))
        return result
    except Exception as e:
        logger.debug("板块资金流向 akshare 失败 (%s): %s", sector_type, e)
        return _get_sector_fund_flow_fallback(sector_type, top_n)


def _get_sector_fund_flow_fallback(sector_type: str, top_n: int) -> List[Dict[str, Any]]:
    """
    备用方案：新浪板块数据按成交额排序（成交额越大近似资金关注度越高）。
    无法获取真实的主力净流入，用 None 标记。
    """
    try:
        if sector_type == "concept":
            sectors = get_hot_concept_sectors(top_n * 2)
        else:
            sectors = get_hot_industry_sectors(top_n * 2)

        for s in sectors:
            s["main_net_inflow"] = None
            s["main_net_pct"] = None

        # 按成交额降序排列（近似资金活跃度）
        sectors.sort(key=lambda x: x.get("total_amount") or 0, reverse=True)
        return sectors[:top_n]
    except Exception:
        return []


# ============================================================
# 2. 大盘指数行情
# ============================================================

INDEX_LIST = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
    ("sh000688", "科创50"),
    ("sh000016", "上证50"),
]


def get_index_quotes(indices: Optional[List[tuple]] = None) -> List[Dict[str, Any]]:
    """
    获取主要指数的实时行情。

    Parameters
    ----------
    indices : list of (code, name) or None
        默认 INDEX_LIST

    Returns
    -------
    list of dict
        code, name, price, change_pct, volume, amount
    """
    indices = indices or INDEX_LIST
    result = []

    # 优先腾讯接口（最快、最轻量）
    for code, name in indices:
        quote = _fetch_index_tencent(code, name)
        if quote:
            result.append(quote)

    if result:
        logger.info("指数行情获取成功 (腾讯): %d 条", len(result))
        return result

    # 备用 akshare
    try:
        ak = _get_ak()
        for code, name in indices:
            try:
                pure_code = code.replace("sh", "").replace("sz", "")
                df = ak.stock_zh_index_spot_em()
                if df is not None and not df.empty:
                    row = df[df["代码"] == pure_code]
                    if not row.empty:
                        r = row.iloc[0]
                        result.append({
                            "code": code,
                            "name": name,
                            "price": _safe_float(r.get("最新价")),
                            "change_pct": _safe_float(r.get("涨跌幅")),
                            "volume": _safe_float(r.get("成交量")),
                            "amount": _safe_float(r.get("成交额")),
                        })
            except Exception as e:
                logger.debug("akshare 指数 %s 获取失败: %s", name, e)
        if result:
            logger.info("指数行情获取成功 (akshare): %d 条", len(result))
    except Exception as e:
        logger.error("指数行情获取失败: %s", e)

    return result


def _fetch_index_tencent(code: str, name: str) -> Optional[Dict[str, Any]]:
    """通过腾讯财经 API 获取单个指数行情（同 stock-sentiment-cn 方案）。"""
    try:
        import requests
        url = f"http://qt.gtimg.cn/q={code}"
        r = requests.get(url, timeout=5, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        data = r.text.strip().split("~")
        if len(data) > 36:
            return {
                "code": code,
                "name": name,
                "price": float(data[3]),
                "change_pct": float(data[32]),
                "volume": int(data[36]) if data[36] else 0,
                "amount": float(data[37]) if len(data) > 37 and data[37] else 0,
            }
    except Exception as e:
        logger.debug("腾讯指数 %s 获取失败: %s", name, e)
    return None


# ============================================================
# 3. 市场情绪快照
# ============================================================

def get_market_snapshot() -> Dict[str, Any]:
    """
    获取市场全景快照（涨跌家数、涨跌停数、两市成交额、北向资金等）。

    优先直接请求东方财富 push2 接口（绕过 akshare），备用 akshare。

    Returns
    -------
    dict with keys:
        total_stocks, rising, falling, flat,
        limit_up, limit_down,
        avg_change_pct, total_amount (元),
        north_bound_net (北向净买入，亿元，可能为 None),
        timestamp
    """
    snapshot: Dict[str, Any] = {"timestamp": datetime.now().isoformat()}

    # 优先直接 HTTP 请求
    direct = _fetch_market_snapshot_direct()
    if direct:
        snapshot.update(direct)
        snapshot["north_bound_net"] = _get_north_bound_net()
        return snapshot

    # 备用 akshare
    try:
        ak = _get_ak()
        df = _retry_call(lambda: ak.stock_zh_a_spot_em(), "全市场 spot")
        if df is None or df.empty:
            logger.warning("全市场 spot 数据为空")
            snapshot["north_bound_net"] = _get_north_bound_net()
            return snapshot

        chg = pd.to_numeric(df["涨跌幅"], errors="coerce")
        amount = pd.to_numeric(df["成交额"], errors="coerce")

        snapshot.update({
            "total_stocks": len(df),
            "rising": int((chg > 0).sum()),
            "falling": int((chg < 0).sum()),
            "flat": int((chg == 0).sum()),
            "limit_up": int((chg >= 9.9).sum()),
            "limit_down": int((chg <= -9.9).sum()),
            "avg_change_pct": round(float(chg.mean()), 3),
            "total_amount": float(amount.sum()),
        })
    except Exception as e:
        logger.error("市场快照获取失败: %s", e)

    snapshot["north_bound_net"] = _get_north_bound_net()
    return snapshot


def _fetch_market_snapshot_direct() -> Optional[Dict[str, Any]]:
    """
    通过新浪板块数据汇总市场涨跌统计。
    新浪行业板块数据包含每个行业的股票数、平均涨跌幅、成交额，
    可以汇总得到全市场近似统计。

    同时用腾讯接口获取上证和深证的成交额作为补充。
    """
    import json
    import re

    try:
        import requests

        # 从新浪行业板块汇总
        r = requests.get(
            "http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
            timeout=10,
            headers={
                "Referer": "http://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            },
        )
        if r.status_code != 200:
            return None

        m = re.search(r"var\s+\w+\s*=\s*(\{.*\})", r.text, re.DOTALL)
        if not m:
            return None

        data = json.loads(m.group(1))

        total_stocks = 0
        total_amount = 0.0
        weighted_chg_sum = 0.0

        for val in data.values():
            parts = val.split(",")
            if len(parts) < 8:
                continue
            try:
                count = int(parts[2]) if parts[2] else 0
                chg = float(parts[4]) if parts[4] else 0
                amt = float(parts[7]) if parts[7] else 0
                total_stocks += count
                total_amount += amt
                weighted_chg_sum += chg * count
            except (ValueError, IndexError):
                continue

        if total_stocks == 0:
            return None

        avg_chg = weighted_chg_sum / total_stocks

        # 用板块平均涨幅方向 * 股票数来估算涨跌家数
        # 注意：一个板块内部涨跌参差，所以按平均涨幅方向归类整个板块的股票是粗略估算
        rising, falling, flat = 0, 0, 0
        limit_up, limit_down = 0, 0

        for val in data.values():
            parts = val.split(",")
            if len(parts) < 5:
                continue
            try:
                chg = float(parts[4]) if parts[4] else 0
                count = int(parts[2]) if parts[2] else 0
                if chg > 0:
                    rising += count
                elif chg < 0:
                    falling += count
                else:
                    flat += count
            except (ValueError, IndexError):
                continue

        result = {
            "total_stocks": total_stocks,
            "rising": rising,
            "falling": falling,
            "flat": flat if flat > 0 else max(0, total_stocks - rising - falling),
            "limit_up": limit_up,
            "limit_down": limit_down,
            "avg_change_pct": round(avg_chg, 3),
            "total_amount": total_amount,
        }
        logger.info(
            "市场快照获取成功 (新浪汇总): ~%d只, 涨~%d/跌~%d",
            total_stocks, rising, falling,
        )
        return result

    except Exception as e:
        logger.debug("新浪汇总市场快照失败: %s", e)
        return None


def _get_north_bound_net() -> Optional[float]:
    """获取今日北向资金净买入（亿元）。"""
    try:
        ak = _get_ak()
        df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            value = _safe_float(latest.get("当日净买入", latest.get("value")))
            if value is not None:
                return round(value / 1e8, 2) if abs(value) > 1e6 else round(value, 2)
    except Exception as e:
        logger.debug("北向资金获取失败: %s", e)
    return None


# ============================================================
# 4. 一键全景采集
# ============================================================

def get_full_market_panorama(
    concept_top: int = 10,
    industry_top: int = 10,
    fund_flow_top: int = 10,
) -> Dict[str, Any]:
    """
    顺序采集全部市场全景数据，返回结构化大字典。

    akshare 底层共享同一个 HTTP session，并发请求容易触发反爬 /
    连接重置。因此改为顺序执行，每步之间留短暂间隔。
    指数行情走腾讯接口（不受 akshare 反爬影响），可以先行获取。

    Returns
    -------
    dict with keys:
        indices, market_snapshot,
        hot_concepts, hot_industries,
        concept_fund_flow, industry_fund_flow,
        fetch_time_sec
    """
    start = time.time()
    result: Dict[str, Any] = {}

    # 指数行情（腾讯接口，不经过 akshare）
    result["indices"] = get_index_quotes()

    # akshare 系列接口顺序执行，每步间隔 0.5s 避免反爬
    steps = [
        ("market_snapshot", lambda: get_market_snapshot()),
        ("hot_concepts", lambda: get_hot_concept_sectors(concept_top)),
        ("hot_industries", lambda: get_hot_industry_sectors(industry_top)),
        ("concept_fund_flow", lambda: get_sector_fund_flow("concept", fund_flow_top)),
        ("industry_fund_flow", lambda: get_sector_fund_flow("industry", fund_flow_top)),
    ]

    for key, fn in steps:
        try:
            result[key] = fn()
        except Exception as e:
            logger.error("全景采集 %s 失败: %s", key, e)
            result[key] = [] if key != "market_snapshot" else {}
        time.sleep(0.5)

    result["fetch_time_sec"] = round(time.time() - start, 2)
    logger.info("全景数据采集完成，耗时 %.2fs", result["fetch_time_sec"])
    return result


# ============================================================
# 5. 格式化输出（供 AI Prompt 或终端打印）
# ============================================================

def format_panorama_for_prompt(panorama: Dict[str, Any]) -> str:
    """
    将全景数据格式化为适合喂给 LLM 的纯文本摘要。
    """
    lines = []

    # 指数
    indices = panorama.get("indices", [])
    if indices:
        lines.append("【大盘指数】")
        for idx in indices:
            arrow = "↑" if (idx.get("change_pct") or 0) > 0 else "↓"
            lines.append(
                f"  {idx['name']}: {idx.get('price', 'N/A')} "
                f"{arrow}{idx.get('change_pct', 0):+.2f}%"
            )

    # 市场快照
    snap = panorama.get("market_snapshot", {})
    if snap.get("total_stocks"):
        lines.append("")
        lines.append("【市场情绪】")
        lines.append(f"  上涨: {snap['rising']}只  下跌: {snap['falling']}只  平盘: {snap['flat']}只")
        lines.append(f"  涨停: {snap.get('limit_up', 'N/A')}只  跌停: {snap.get('limit_down', 'N/A')}只")
        total_amount_yi = snap.get("total_amount", 0) / 1e8
        lines.append(f"  两市成交额: {total_amount_yi:.0f}亿元")
        lines.append(f"  全A平均涨幅: {snap.get('avg_change_pct', 0):+.3f}%")
        if snap.get("north_bound_net") is not None:
            lines.append(f"  北向资金净买入: {snap['north_bound_net']:+.2f}亿元")

    # 热点概念
    concepts = panorama.get("hot_concepts", [])
    if concepts:
        lines.append("")
        lines.append("【热点概念板块 TOP10】")
        for i, s in enumerate(concepts[:10], 1):
            leader = f" (领涨: {s['leader_stock']})" if s.get("leader_stock") else ""
            lines.append(f"  {i}. {s['name']}: {s.get('change_pct', 0):+.2f}%{leader}")

    # 热点行业
    industries = panorama.get("hot_industries", [])
    if industries:
        lines.append("")
        lines.append("【热点行业板块 TOP10】")
        for i, s in enumerate(industries[:10], 1):
            leader = f" (领涨: {s['leader_stock']})" if s.get("leader_stock") else ""
            lines.append(f"  {i}. {s['name']}: {s.get('change_pct', 0):+.2f}%{leader}")

    # 资金流向
    cf = panorama.get("concept_fund_flow", [])
    if cf:
        lines.append("")
        lines.append("【概念板块资金流入 TOP5】")
        for i, s in enumerate(cf[:5], 1):
            inflow = s.get("main_net_inflow")
            inflow_str = f"{inflow / 1e8:+.2f}亿" if inflow else "N/A"
            lines.append(f"  {i}. {s['name']}: {s.get('change_pct', 0):+.2f}%, 主力净流入{inflow_str}")

    idf = panorama.get("industry_fund_flow", [])
    if idf:
        lines.append("")
        lines.append("【行业板块资金流入 TOP5】")
        for i, s in enumerate(idf[:5], 1):
            inflow = s.get("main_net_inflow")
            inflow_str = f"{inflow / 1e8:+.2f}亿" if inflow else "N/A"
            lines.append(f"  {i}. {s['name']}: {s.get('change_pct', 0):+.2f}%, 主力净流入{inflow_str}")

    return "\n".join(lines)


# ============================================================
# 辅助
# ============================================================

def _safe_float(val) -> Optional[float]:
    """安全浮点转换。"""
    try:
        if val is None or val == "":
            return None
        return float(val)
    except (ValueError, TypeError):
        return None
