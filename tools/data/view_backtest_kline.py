#!/usr/bin/env python3
"""
查看本地回测 K 线：按股票代码显示历史价格（日期、开高低收、成交量），可导出 CSV。

用法:
  python3 tools/data/view_backtest_kline.py 000425
  python3 tools/data/view_backtest_kline.py 600519 --out-dir mydate/backtest_kline
  python3 tools/data/view_backtest_kline.py 000425 --csv          # 导出为 000425.csv
  python3 tools/data/view_backtest_kline.py --list-failed         # 列出未拉取成功的股票代码
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pandas as pd


def get_out_dir(args, base_dir: str) -> str:
    out = getattr(args, "out_dir", None) or "mydate/backtest_kline"
    return os.path.join(base_dir, out) if not os.path.isabs(out) else out


def view_one(code: str, out_dir: str, export_csv: bool = False, base_dir: str = "") -> int:
    path = os.path.join(out_dir, f"{code}.parquet")
    if not os.path.isfile(path):
        print(f"未找到本地数据: {path}")
        return 1
    try:
        df = pd.read_parquet(path)
        if df is None or df.empty:
            print(f"{code}: 文件为空")
            return 1
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        print(f"股票代码: {code}  共 {len(df)} 条")
        print("列:", list(df.columns))
        print("\n最近 20 条:")
        print(df.tail(20).to_string(index=False))
        print("\n最早 5 条:")
        print(df.head(5).to_string(index=False))
        if export_csv:
            csv_path = os.path.join(base_dir or out_dir, f"{code}.csv")
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            print(f"\n已导出: {csv_path}")
    except Exception as e:
        print(f"读取失败: {e}")
        return 1
    return 0


def list_failed(out_dir: str) -> int:
    manifest_path = os.path.join(out_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"未找到 {manifest_path}，请先运行预取/更新。")
        return 1
    with open(manifest_path, "r", encoding="utf-8") as f:
        m = json.load(f)
    codes = set(m.get("codes", []))
    have = set()
    for f in os.listdir(out_dir):
        if f.endswith(".parquet"):
            have.add(f.replace(".parquet", ""))
    failed = sorted(codes - have)
    # 若 manifest 里已记录 failed_codes 则优先用
    if "failed_codes" in m and m["failed_codes"]:
        failed = m["failed_codes"]
    print(f"未拉取成功的股票代码，共 {len(failed)} 只：")
    print(failed)
    return 0


def main():
    parser = argparse.ArgumentParser(description="查看回测 K 线（哪只股票、历史价格）或列出未成功标的")
    parser.add_argument("code", nargs="?", help="股票代码，如 000425")
    parser.add_argument("--out-dir", default="mydate/backtest_kline", help="回测 K 线目录")
    parser.add_argument("--csv", action="store_true", help="导出该只股票为 CSV（可 Excel 打开）")
    parser.add_argument("--list-failed", action="store_true", help="列出未拉取成功的股票代码")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out_dir = get_out_dir(args, base_dir)

    if getattr(args, "list_failed", False):
        return list_failed(out_dir)

    if not getattr(args, "code", None):
        parser.print_help()
        print("\n示例: python3 tools/data/view_backtest_kline.py 000425 或 --list-failed")
        return 0

    return view_one(args.code, out_dir, export_csv=args.csv, base_dir=base_dir)


if __name__ == "__main__":
    sys.exit(main())
