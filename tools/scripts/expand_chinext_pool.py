#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Expand stock_pool_all.json with ChiNext (创业板) stocks via AKShare."""

from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import akshare as ak

POOL_PATH = Path(__file__).resolve().parents[2] / "mydate" / "stock_pool_all.json"
# 百度股市通「总市值」曲线数值单位为亿元人民币（与同花顺/东方财富常见口径一致）
MIN_MC_YI = 50.0
MAX_WORKERS = 3  # 并发过高易触发东方财富封禁；百度接口亦保守限流
GEM_CODE_RE = re.compile(r"^30[012]\d{3}$")
BAIDU_PERIOD = "近一月"


def _is_st(name: str) -> bool:
    n = str(name).upper()
    return "ST" in n or "*ST" in n


def classify_sector(name: str) -> str:
    """Name-based keyword routing; first match wins."""
    if any(k in name for k in ("半导", "芯片", "微电子", "集成", "封测", "晶圆", "存储")):
        return "半导体"
    if any(k in name for k in ("光模块", "光通信", "光纤", "天线", "通信")):
        return "创业板_光通信"
    if any(k in name for k in ("算力", "云", "数字", "智能", "软件", "信息", "数据", "科技")):
        return "创业板_AI算力"
    if any(
        k in name
        for k in ("新能源", "光伏", "太阳能", "风电", "储能", "氢能", "风能", "电源")
    ):
        return "创业板_新能源"
    if any(k in name for k in ("电池", "锂", "钴", "电解")):
        return "创业板_锂电电池"
    if any(
        k in name
        for k in ("疫苗", "基因", "诊断", "器械", "医疗", "生物", "医药", "药业", "医院", "口腔")
    ):
        return "创业板_医药医疗"
    if "药" in name or "医" in name:
        return "创业板_医药医疗"
    if any(k in name for k in ("航天", "航空", "防务", "雷达", "军工", "军品")):
        return "创业板_军工航天"
    if "军" in name:
        return "创业板_军工航天"
    if any(
        k in name
        for k in ("机器人", "自动化", "伺服", "控制", "工控", "数控", "减速器", "谐波")
    ):
        return "创业板_机器人"
    if any(k in name for k in ("汽车", "动力", "零部件", "整车", "车联网", "轮胎", "充电")):
        return "创业板_汽车"
    if "车" in name:
        return "创业板_汽车"
    if any(k in name for k in ("PCB", "pcb", "传感", "元件", "面板", "激光", "精密", "光学", "电子")):
        return "创业板_电子PCB"
    if any(k in name for k in ("材料", "化工", "化学")):
        return "创业板_新材料"
    return "创业板_其他"


def fetch_mcap_yi_baidu(code: str) -> tuple[str, float | None]:
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            df = ak.stock_zh_valuation_baidu(
                symbol=code, indicator="总市值", period=BAIDU_PERIOD
            )
            v = float(df["value"].iloc[-1])
            if v != v:  # NaN
                return code, None
            return code, v
        except Exception as e:
            last_err = e
            time.sleep(0.4 * (attempt + 1))
    return code, None


def try_spot_cy_mcap_map() -> dict[str, float] | None:
    """若东方财富创业板列表可用，则一次性取总市值（元）→ 亿元。"""
    try:
        df = ak.stock_cy_a_spot_em()
    except Exception:
        return None
    col_code, col_mc = "代码", "总市值"
    if col_code not in df.columns or col_mc not in df.columns:
        return None
    out: dict[str, float] = {}
    for _, row in df.iterrows():
        raw = str(row[col_code]).strip()
        c = raw.zfill(6) if len(raw) <= 6 else raw
        mc_yuan = float(row[col_mc])
        if mc_yuan != mc_yuan:
            continue
        out[c] = mc_yuan / 1e8
    return out if out else None


def main() -> int:
    with POOL_PATH.open(encoding="utf-8") as f:
        pool = json.load(f)

    existing: set[str] = set()
    for lst in pool["stocks"].values():
        for it in lst:
            existing.add(str(it["code"]).zfill(6))

    info = ak.stock_info_a_code_name()
    info["code"] = info["code"].astype(str).str.zfill(6)
    gem = info[info["code"].str.match(GEM_CODE_RE)].copy()
    gem = gem[~gem["name"].astype(str).map(_is_st)]

    candidates = gem[~gem["code"].isin(existing)]
    codes_to_fetch = candidates["code"].tolist()
    print(
        f"ChiNext (30/301/302) non-ST: {len(gem)} | not yet in pool: {len(codes_to_fetch)}",
        flush=True,
    )

    mcap_yi: dict[str, float] = {}
    spot = try_spot_cy_mcap_map()
    if spot:
        print(f"Using stock_cy_a_spot_em() for mcap: {len(spot)} rows", flush=True)
        for c in codes_to_fetch:
            v = spot.get(c)
            if v is not None:
                mcap_yi[c] = v
        missing = [c for c in codes_to_fetch if c not in mcap_yi]
        print(f"Baidu fill-in for {len(missing)} codes missing from spot", flush=True)
        codes_for_baidu = missing
    else:
        print("stock_cy_a_spot_em unavailable; using Baidu 总市值 only", flush=True)
        codes_for_baidu = codes_to_fetch

    failed = 0
    done = 0
    total_baidu = len(codes_for_baidu)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(fetch_mcap_yi_baidu, c) for c in codes_for_baidu]
        for fut in as_completed(futs):
            c, v = fut.result()
            done += 1
            if done % 200 == 0 or done == total_baidu:
                print(f"  mcap progress {done}/{total_baidu}", flush=True)
            if v is None:
                failed += 1
            else:
                mcap_yi[c] = v

    print(f"总市值(亿) 有效: {len(mcap_yi)} | 失败/缺省: {failed}", flush=True)

    added_by_sector: dict[str, int] = defaultdict(int)
    added = 0
    for _, row in candidates.iterrows():
        code = row["code"]
        name = str(row["name"])
        mc = mcap_yi.get(code)
        if mc is None or mc < MIN_MC_YI:
            continue
        sector = classify_sector(name)
        pool["stocks"].setdefault(sector, [])
        pool["stocks"][sector].append({"code": code, "name": name})
        added_by_sector[sector] += 1
        added += 1

    for lst in pool["stocks"].values():
        lst.sort(key=lambda x: str(x["code"]))

    total_stocks = sum(len(v) for v in pool["stocks"].values())
    pool.setdefault("stats", {})
    pool["stats"]["total_stocks"] = total_stocks
    etf_n = int(pool["stats"].get("total_etf", 0))
    pool["stats"]["total"] = total_stocks + etf_n

    base = "综合股票池（个股+ETF），含基本面过滤。"
    pool["description"] = (
        base
        + " 创业板扩充：AKShare 全市场代码表，剔除ST；总市值>50亿元"
        "（优先东方财富创业板列表；不可用时用百度股市通总市值曲线，单位亿元人民币）；"
        "按股票简称关键词归入「半导体」或创业板主题分桶。"
    )

    pool.setdefault("filter_rules", {})
    pool["filter_rules"]["chinext_expansion"] = (
        "非ST；总市值>50亿元；创业板30/301/302；名称关键词分类；市值数据源 Eastmoney 或 Baidu"
    )
    pool["created_at"] = date.today().isoformat()

    with POOL_PATH.open("w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("--- 各板块新增数量 ---", flush=True)
    for k in sorted(added_by_sector.keys(), key=lambda x: (-added_by_sector[x], x)):
        print(f"  {k}: {added_by_sector[k]}", flush=True)
    print(f"--- 新增合计: {added} ---", flush=True)
    print(f"--- 股票池 total_stocks: {total_stocks} ---", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
