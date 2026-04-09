"""
MX-Data 适配器 — 将妙想金融数据 API 接入现有 KlineAdapter 体系。

用途:
1. 作为 UnifiedDataProvider 的备用 K 线源 (AKShare 不稳定时自动降级)
2. 提供实时行情快照 (替代 stock_zh_a_spot_em)
3. 提供财务数据查询
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .client import MXClient, MXQuotaExhausted, get_mx_client

logger = logging.getLogger(__name__)

KLINE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class MXDataAdapter:
    """
    妙想金融数据适配器 — 通过自然语言查询获取行情/财务数据。

    注意: 妙想 API 按 *自然语言问句* 驱动，而非标准化参数。
    查询大范围历史数据会快速消耗每日配额，适合:
    - 实时/近期行情查询
    - 单只股票最新财务数据
    - 作为 AKShare 的最后降级手段
    """

    source_id = "mx_data"

    def __init__(self, client: Optional[MXClient] = None):
        self._client = client

    @property
    def client(self) -> MXClient:
        if self._client is None:
            self._client = get_mx_client()
        return self._client

    def get_realtime_quote(self, symbol: str) -> Optional[Dict]:
        """获取单只股票的实时行情快照"""
        try:
            df = self.client.query_data_df(f"{symbol} 最新价 涨跌幅 成交量 换手率")
            if df.empty:
                return None
            row = df.iloc[0].to_dict()
            row["symbol"] = symbol
            return row
        except MXQuotaExhausted:
            logger.warning("MX 配额用尽，跳过实时行情查询: %s", symbol)
            return None
        except Exception:
            logger.exception("MX 实时行情查询失败: %s", symbol)
            return None

    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        获取股票日 K 线数据。

        警告: 每次查询消耗 1 次配额，大范围数据查询应优先使用 AKShare。
        仅建议在 AKShare 故障时作为降级使用。
        """
        try:
            period_desc = ""
            if datalen and datalen <= 60:
                period_desc = f"近{datalen}个交易日"
            elif start_date and end_date:
                period_desc = f"从{start_date}到{end_date}"
            else:
                period_desc = "近30个交易日"

            query = f"{symbol} {period_desc} 每日开盘价收盘价最高价最低价成交量"
            df = self.client.query_data_df(query)
            if df.empty:
                return pd.DataFrame(columns=KLINE_COLUMNS)

            col_mapping = {}
            for col in df.columns:
                col_lower = col.lower()
                if "开盘" in col or "open" in col_lower:
                    col_mapping[col] = "open"
                elif "收盘" in col or "close" in col_lower:
                    col_mapping[col] = "close"
                elif "最高" in col or "high" in col_lower:
                    col_mapping[col] = "high"
                elif "最低" in col or "low" in col_lower:
                    col_mapping[col] = "low"
                elif "成交量" in col or "volume" in col_lower:
                    col_mapping[col] = "volume"
                elif "日期" in col or "date" in col_lower:
                    col_mapping[col] = "date"

            df = df.rename(columns=col_mapping)
            for c in KLINE_COLUMNS:
                if c not in df.columns:
                    df[c] = np.nan
            df = df[KLINE_COLUMNS]
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df
        except MXQuotaExhausted:
            logger.warning("MX 配额用尽，跳过 K 线查询: %s", symbol)
            return pd.DataFrame(columns=KLINE_COLUMNS)
        except Exception:
            logger.exception("MX K 线查询失败: %s", symbol)
            return pd.DataFrame(columns=KLINE_COLUMNS)

    def get_financials(self, symbol: str, metrics: str = "净利润 营业收入 净资产收益率") -> pd.DataFrame:
        """获取财务指标"""
        try:
            return self.client.query_data_df(f"{symbol} {metrics} 近三年")
        except (MXQuotaExhausted, Exception) as e:
            logger.warning("MX 财务查询失败 %s: %s", symbol, e)
            return pd.DataFrame()

    def get_index_quote(self, index_name: str = "上证指数") -> Optional[Dict]:
        """获取指数实时行情"""
        try:
            df = self.client.query_data_df(f"{index_name} 最新点位 涨跌幅")
            if df.empty:
                return None
            return df.iloc[0].to_dict()
        except Exception:
            logger.exception("MX 指数查询失败: %s", index_name)
            return None

    def get_fund_flow(self, symbol: str) -> Optional[Dict]:
        """获取主力资金流向"""
        try:
            df = self.client.query_data_df(f"{symbol} 主力资金流向")
            if df.empty:
                return None
            return df.iloc[0].to_dict()
        except Exception:
            logger.warning("MX 资金流向查询失败: %s", symbol)
            return None
