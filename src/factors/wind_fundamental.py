"""
Wind 基本面因子接入框架

支持两种数据源模式：
1. Wind API 直连（需要安装 WindPy 并拥有有效的 Wind 金融终端账号）
2. CSV 缓存模式（从 Wind 导出后离线使用）

因子维度（机构级）：
- 质量因子：ROE_TTM, ROIC, 经营现金流/净利润, 应计利润
- 预期因子：一致预期EPS增长率, 分析师评级变化, 目标价/现价
- 事件因子：业绩预告方向, 大股东增持/减持, 回购金额
- 风格因子：市值, Beta, 动量, 波动率（用于 Barra 风险模型）

使用方式：
    from src.factors.wind_fundamental import WindFactorProvider
    provider = WindFactorProvider(mode='csv', cache_dir='mydate/wind_cache')
    factors_df = provider.get_factors(['600519', '000858'], '2026-03-28')
"""

import pandas as pd
import numpy as np
import logging
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

QUALITY_FACTORS = ['roe_ttm', 'roic', 'ocf_to_profit', 'accrual_ratio', 'gross_margin_stability']
EXPECTATION_FACTORS = ['est_eps_growth_1y', 'analyst_upgrade_ratio', 'target_price_ratio']
EVENT_FACTORS = ['earnings_surprise', 'buyback_amount', 'insider_net_buy']
STYLE_FACTORS = ['ln_market_cap', 'beta_252d', 'momentum_60d', 'volatility_20d']

ALL_FACTORS = QUALITY_FACTORS + EXPECTATION_FACTORS + EVENT_FACTORS + STYLE_FACTORS


@dataclass
class FactorConfig:
    """因子配置"""
    mode: str = 'csv'
    cache_dir: str = 'mydate/wind_cache'
    wind_timeout: int = 30


class WindFactorProvider:
    """
    Wind 因子数据提供者

    mode='wind':  通过 WindPy API 实时获取（需要 Wind 终端在线）
    mode='csv':   从本地 CSV 缓存读取（离线可用）
    """

    def __init__(self, mode: str = 'csv', cache_dir: str = 'mydate/wind_cache'):
        self.mode = mode
        self.cache_dir = Path(cache_dir)
        self._wind_api = None

        if mode == 'wind':
            self._init_wind()

    def _init_wind(self):
        """初始化 WindPy 连接"""
        try:
            from WindPy import w
            w.start()
            if w.isconnected():
                self._wind_api = w
                logger.info("Wind API 连接成功")
            else:
                logger.warning("Wind API 未连接，降级为 CSV 模式")
                self.mode = 'csv'
        except ImportError:
            logger.warning("WindPy 未安装，降级为 CSV 模式。安装方法: pip install WindPy")
            self.mode = 'csv'

    def get_factors(self, codes: List[str], date: str,
                    factor_list: Optional[List[str]] = None) -> pd.DataFrame:
        """
        获取指定股票在指定日期的因子数据

        Args:
            codes: 股票代码列表（如 ['600519', '000858']）
            date: 日期字符串 'YYYY-MM-DD'
            factor_list: 指定因子列表，None 则获取全部

        Returns:
            DataFrame, index=code, columns=factor_names
        """
        factors = factor_list or ALL_FACTORS

        if self.mode == 'wind' and self._wind_api is not None:
            return self._fetch_from_wind(codes, date, factors)
        else:
            return self._fetch_from_csv(codes, date, factors)

    def _fetch_from_wind(self, codes: List[str], date: str,
                         factors: List[str]) -> pd.DataFrame:
        """通过 Wind API 获取因子"""
        w = self._wind_api
        wind_codes = [self._to_wind_code(c) for c in codes]

        wind_field_map = {
            'roe_ttm': 'roe_ttm2',
            'roic': 'roic_ttm',
            'ocf_to_profit': 'ocftoprofit_ttm',
            'gross_margin_stability': 'grossprofitmargin',
            'est_eps_growth_1y': 'est_epsfy1_yoy',
            'analyst_upgrade_ratio': 'est_change_rating',
            'target_price_ratio': 'est_avgprice_fy1',
            'ln_market_cap': 'val_lnmv',
            'beta_252d': 'beta_252d',
            'momentum_60d': 'pct_chg_per_60d',
            'volatility_20d': 'stdevr_20d',
        }

        rows = {}
        for code, wcode in zip(codes, wind_codes):
            row = {}
            for factor in factors:
                wind_field = wind_field_map.get(factor)
                if wind_field is None:
                    row[factor] = np.nan
                    continue
                try:
                    result = w.wss(wcode, wind_field, f"tradeDate={date}")
                    if result.ErrorCode == 0 and result.Data:
                        row[factor] = result.Data[0][0]
                    else:
                        row[factor] = np.nan
                except Exception:
                    row[factor] = np.nan
            rows[code] = row

        df = pd.DataFrame.from_dict(rows, orient='index')
        df.index.name = 'code'

        self._save_to_csv(df, date)
        return df

    def _fetch_from_csv(self, codes: List[str], date: str,
                        factors: List[str]) -> pd.DataFrame:
        """从本地 CSV 缓存读取"""
        date_str = date.replace('-', '')
        cache_file = self.cache_dir / f'wind_factors_{date_str}.csv'

        if not cache_file.exists():
            logger.debug("Wind 因子缓存不存在: %s", cache_file)
            return pd.DataFrame(columns=factors, index=pd.Index(codes, name='code'))

        try:
            df = pd.read_csv(cache_file, index_col='code', dtype={'code': str})
            df = df.reindex(codes)
            available = [f for f in factors if f in df.columns]
            missing = [f for f in factors if f not in df.columns]
            if missing:
                for f in missing:
                    df[f] = np.nan
            return df[factors]
        except Exception as e:
            logger.warning("读取 Wind 因子缓存失败: %s", e)
            return pd.DataFrame(columns=factors, index=pd.Index(codes, name='code'))

    def _save_to_csv(self, df: pd.DataFrame, date: str):
        """保存到 CSV 缓存"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        date_str = date.replace('-', '')
        cache_file = self.cache_dir / f'wind_factors_{date_str}.csv'
        try:
            df.to_csv(cache_file)
            logger.info("Wind 因子已缓存: %s", cache_file)
        except Exception as e:
            logger.warning("保存 Wind 因子缓存失败: %s", e)

    @staticmethod
    def _to_wind_code(code: str) -> str:
        """将纯数字代码转为 Wind 格式（600xxx.SH / 000xxx.SZ）"""
        if code.startswith('6') or code.startswith('9'):
            return f'{code}.SH'
        else:
            return f'{code}.SZ'

    def get_quality_score(self, code: str, date: str) -> float:
        """
        计算单只股票的质量因子综合得分 [0, 1]

        ROE_TTM 权重 30%, ROIC 权重 25%, OCF/Profit 权重 25%,
        毛利率稳定性权重 10%, 应计利润(反向) 权重 10%
        """
        df = self.get_factors([code], date, QUALITY_FACTORS)
        if df.empty or df.iloc[0].isna().all():
            return 0.5

        row = df.iloc[0]
        scores = []
        weights = [0.30, 0.25, 0.25, 0.10, 0.10]

        roe = row.get('roe_ttm', np.nan)
        if np.isfinite(roe):
            scores.append(np.clip(roe / 30.0, 0, 1))
        else:
            scores.append(0.5)

        roic = row.get('roic', np.nan)
        if np.isfinite(roic):
            scores.append(np.clip(roic / 25.0, 0, 1))
        else:
            scores.append(0.5)

        ocf = row.get('ocf_to_profit', np.nan)
        if np.isfinite(ocf):
            scores.append(np.clip(ocf / 1.5, 0, 1))
        else:
            scores.append(0.5)

        gm = row.get('gross_margin_stability', np.nan)
        if np.isfinite(gm):
            scores.append(np.clip(gm / 50.0, 0, 1))
        else:
            scores.append(0.5)

        accrual = row.get('accrual_ratio', np.nan)
        if np.isfinite(accrual):
            scores.append(np.clip(1.0 - abs(accrual) / 0.3, 0, 1))
        else:
            scores.append(0.5)

        return float(np.average(scores, weights=weights))

    def get_expectation_alpha(self, code: str, date: str) -> float:
        """
        计算预期因子 alpha [-1, 1]

        一致预期增长率变化、评级调整方向、目标价与现价之比
        """
        df = self.get_factors([code], date, EXPECTATION_FACTORS)
        if df.empty or df.iloc[0].isna().all():
            return 0.0

        row = df.iloc[0]

        eps_g = row.get('est_eps_growth_1y', np.nan)
        eps_score = np.clip(eps_g / 50.0, -1, 1) if np.isfinite(eps_g) else 0.0

        upgrade = row.get('analyst_upgrade_ratio', np.nan)
        upgrade_score = np.clip(upgrade, -1, 1) if np.isfinite(upgrade) else 0.0

        tp_ratio = row.get('target_price_ratio', np.nan)
        tp_score = np.clip((tp_ratio - 1.0) * 5.0, -1, 1) if np.isfinite(tp_ratio) else 0.0

        return float(0.4 * eps_score + 0.3 * upgrade_score + 0.3 * tp_score)
