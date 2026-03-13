"""
基本面数据获取模块

功能:
1. 获取ROE等季频财务指标（akshare优先 → baostock备用）
2. 获取行业分类（baostock query_stock_industry）
3. 获取日频基本面（PE/PB/市值/换手率，baostock日K线）
4. 聚合同行业所有股票的PE/PB数据（用于分行业分位数计算）
5. 将季频数据按发布日期对齐到日频（避免未来函数）

数据源:
- akshare (免费): ROE/财务指标（stock_financial_analysis_indicator，数据更全）
- baostock (免费): ROE备用、行业分类、日频PE/PB
- 东方财富实时接口: 在部分服务器上被封，不作为主力

当前状态:
- get_financial_indicators: ✅ 已实现（akshare优先 + baostock备用）
- get_industry_classification: ✅ 已实现（baostock）
- get_industry_pe_pb_data: ✅ 已实现（聚合同行业PE/PB）
- get_daily_basic: ✅ 已实现（baostock日K线）
- get_industry_pe_cninfo: ✅ 新增（巨潮行业PE，直接获取，快100倍）
- get_pe_pb_baidu: ✅ 新增（百度PE/PB历史，非东财源不被封）
- get_fund_flow_signal: ✅ 新增（个股资金流信号）
- get_index_components_akshare: ✅ 新增（中证指数成分股实时获取）
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
import time
import json
import os

logger = logging.getLogger(__name__)


class FundamentalFetcher:
    """基本面数据获取器（akshare + baostock）"""
    
    # 缓存目录（使用 mycache 目录）
    _CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'mycache', 'fundamental')
    
    def __init__(self, source: str = 'baostock'):
        """
        Args:
            source: 数据源 ('baostock')
        """
        self.source = source
        self._bs_logged_in = False
        self._akshare_available = None  # None=未检测
        # 行业分类缓存（内存 + 磁盘）
        self._industry_cache: Dict[str, Optional[str]] = {}
        # 全市场行业缓存（code -> industry）
        self._all_industry_cache: Dict[str, str] = {}
        # 确保缓存目录存在
        os.makedirs(self._CACHE_DIR, exist_ok=True)
    
    def _check_akshare(self) -> bool:
        """检查akshare是否可用"""
        if self._akshare_available is None:
            try:
                import akshare
                self._akshare_available = True
            except ImportError:
                self._akshare_available = False
        return self._akshare_available
    
    def _ensure_bs_login(self):
        """确保baostock已登录"""
        if not self._bs_logged_in:
            import baostock as bs
            lg = bs.login()
            if lg.error_code == '0':
                self._bs_logged_in = True
            else:
                logger.error(f"baostock登录失败: {lg.error_msg}")
                raise RuntimeError(f"baostock登录失败: {lg.error_msg}")
    
    def _bs_logout(self):
        """登出baostock"""
        if self._bs_logged_in:
            import baostock as bs
            bs.logout()
            self._bs_logged_in = False
    
    def _code_to_bs(self, code: str) -> str:
        """股票代码转baostock格式: '600030' -> 'sh.600030'"""
        prefix = 'sh' if code.startswith(('5', '6', '9')) else 'sz'
        return f'{prefix}.{code}'
    
    # ============================================================
    # 1. ROE及财务指标获取（季频）
    # ============================================================
    
    def get_financial_indicators(self, code: str, 
                                 start_year: int = None,
                                 end_year: int = None) -> pd.DataFrame:
        """
        获取财务指标（ROE、净利润率、毛利率等，季频）
        
        优先使用akshare（数据更全、直接给百分比），
        失败时回退到baostock。
        
        返回数据以财报发布日期(pub_date)为准，避免未来函数。
        
        Args:
            code: 股票代码（如 '600030'）
            start_year: 开始年份（默认3年前）
            end_year: 结束年份（默认今年）
        
        Returns:
            DataFrame with columns: 
                pub_date (发布日期/统计截止日期), stat_date (统计截止日期),
                roe (ROE%), roe_weighted (加权ROE%),
                np_margin (净利润率%), gp_margin (毛利率%),
                net_profit (净利润), eps_ttm (每股收益TTM)
        """
        if start_year is None:
            start_year = datetime.now().year - 3
        if end_year is None:
            end_year = datetime.now().year
        
        # 先检查缓存
        cache_file = os.path.join(self._CACHE_DIR, f'roe_{code}.csv')
        if os.path.exists(cache_file):
            cache_mtime = os.path.getmtime(cache_file)
            if time.time() - cache_mtime < 7 * 86400:  # 7天有效
                try:
                    df = pd.read_csv(cache_file)
                    df['pub_date'] = pd.to_datetime(df['pub_date'])
                    df['stat_date'] = pd.to_datetime(df['stat_date'])
                    df = df[df['stat_date'].dt.year >= start_year]
                    df = df[df['stat_date'].dt.year <= end_year]
                    if not df.empty:
                        logger.debug(f"[{code}] ROE缓存命中, {len(df)}条")
                        return df
                except Exception:
                    pass
        
        # 优先用akshare
        df = pd.DataFrame()
        if self._check_akshare():
            df = self._get_fina_akshare(code, start_year, end_year)
        
        # akshare失败时回退到baostock
        if df.empty:
            df = self._get_fina_baostock(code, start_year, end_year)
        
        if df.empty:
            logger.warning(f"[{code}] 无财务指标数据")
            return df
        
        # 保存缓存
        try:
            df.to_csv(cache_file, index=False)
        except Exception:
            pass
        
        logger.info(f"[{code}] 获取ROE数据 {len(df)}条 ({start_year}-{end_year})")
        return df
    
    def _get_fina_akshare(self, code: str, start_year: int, end_year: int) -> pd.DataFrame:
        """使用akshare获取财务指标（数据更全、直接给百分比）"""
        try:
            import akshare as ak
            
            df = ak.stock_financial_analysis_indicator(symbol=code, start_year=str(start_year))
            
            if df.empty:
                return pd.DataFrame()
            
            # 标准化列名
            # akshare返回列：日期, 净资产收益率(%), 加权净资产收益率(%), 主营业务利润率(%), ...
            result = pd.DataFrame()
            
            # 日期列（既作为pub_date也作为stat_date）
            if '日期' in df.columns:
                result['stat_date'] = pd.to_datetime(df['日期'])
                result['pub_date'] = result['stat_date']  # akshare没有单独的发布日期
            else:
                return pd.DataFrame()
            
            # ROE
            if '净资产收益率(%)' in df.columns:
                result['roe'] = pd.to_numeric(df['净资产收益率(%)'], errors='coerce')
            if '加权净资产收益率(%)' in df.columns:
                result['roe_weighted'] = pd.to_numeric(df['加权净资产收益率(%)'], errors='coerce')
            
            # 利润率
            if '主营业务利润率(%)' in df.columns:
                result['gp_margin'] = pd.to_numeric(df['主营业务利润率(%)'], errors='coerce')
            
            # 每股收益
            if '摊薄每股收益(元)' in df.columns:
                result['eps_ttm'] = pd.to_numeric(df['摊薄每股收益(元)'], errors='coerce')
            
            # 每股净资产
            if '每股净资产_调整前(元)' in df.columns:
                result['bps'] = pd.to_numeric(df['每股净资产_调整前(元)'], errors='coerce')
            
            # 过滤年份
            result = result[result['stat_date'].dt.year >= start_year]
            result = result[result['stat_date'].dt.year <= end_year]
            
            result = result.sort_values('stat_date').reset_index(drop=True)
            
            if not result.empty:
                logger.info(f"[{code}] akshare ROE获取成功 {len(result)}条")
            
            return result
            
        except Exception as e:
            logger.debug(f"[{code}] akshare获取失败: {e}")
            return pd.DataFrame()
    
    def _get_fina_baostock(self, code: str, start_year: int, end_year: int) -> pd.DataFrame:
        """使用baostock获取财务指标（备用）"""
        self._ensure_bs_login()
        import baostock as bs
        
        records = []
        bs_code = self._code_to_bs(code)
        
        for year in range(start_year, end_year + 1):
            for quarter in range(1, 5):
                try:
                    rs = bs.query_profit_data(code=bs_code, year=year, quarter=quarter)
                    if rs.error_code == '0' and rs.next():
                        row = rs.get_row_data()
                        if len(row) >= 8 and row[1]:
                            record = {
                                'pub_date': row[1],
                                'stat_date': row[2],
                                'roe': self._safe_float(row[3]),
                                'np_margin': self._safe_float(row[4]),
                                'gp_margin': self._safe_float(row[5]),
                                'net_profit': self._safe_float(row[6]),
                                'eps_ttm': self._safe_float(row[7]),
                            }
                            records.append(record)
                except Exception as e:
                    logger.debug(f"[{code}] {year}Q{quarter} 获取失败: {e}")
        
        if not records:
            return pd.DataFrame()
        
        df = pd.DataFrame(records)
        df['pub_date'] = pd.to_datetime(df['pub_date'])
        df['stat_date'] = pd.to_datetime(df['stat_date'])
        
        # baostock返回小数，转百分比
        if 'roe' in df.columns:
            df['roe'] = df['roe'] * 100
        
        df = df.sort_values('pub_date').reset_index(drop=True)
        return df
    
    def get_roe_for_filter(self, code: str, min_years: int = 3) -> Tuple[bool, float, str]:
        """
        获取ROE用于PB策略过滤（实盘标准：连续3年ROE>8%）
        
        Args:
            code: 股票代码
            min_years: 最少需要多少年数据
        
        Returns:
            (passes_filter, latest_annual_roe, reason)
            - passes_filter: 是否通过过滤
            - latest_annual_roe: 最近年度ROE
            - reason: 原因说明
        """
        try:
            fina_df = self.get_financial_indicators(code, 
                                                     start_year=datetime.now().year - min_years - 2,
                                                     end_year=datetime.now().year)
            if fina_df.empty:
                return True, 0.0, '无ROE数据，暂不过滤'
            
            # 优先用加权ROE（更权威），没有则用普通ROE
            roe_col = 'roe_weighted' if 'roe_weighted' in fina_df.columns and fina_df['roe_weighted'].notna().any() else 'roe'
            
            # 取年报数据（Q4，即stat_date为12月31日的）
            annual = fina_df[fina_df['stat_date'].dt.month == 12].copy()
            
            if len(annual) < min_years:
                # 数据不足，看季度数据
                if len(fina_df) >= 4:
                    latest_roe = fina_df[roe_col].iloc[-1] if roe_col in fina_df.columns else 0.0
                    return True, latest_roe, f'年报数据不足({len(annual)}年)，暂不过滤'
                return True, 0.0, f'ROE数据不足，暂不过滤'
            
            # 最近N年的年度ROE
            recent_annual = annual.tail(min_years)
            latest_roe = recent_annual[roe_col].iloc[-1] if roe_col in recent_annual.columns else 0.0
            
            # 检查是否连续3年>8%
            roe_values = recent_annual[roe_col] if roe_col in recent_annual.columns else recent_annual['roe']
            all_above_8 = (roe_values > 8.0).all()
            
            if all_above_8:
                avg_roe = roe_values.mean()
                return True, latest_roe, f'连续{min_years}年ROE>{8}%（均值{avg_roe:.1f}%）'
            else:
                failed_years = recent_annual[roe_values <= 8.0]
                return False, latest_roe, (
                    f'ROE未连续{min_years}年>8%，'
                    f'有{len(failed_years)}年不达标，可能是价值陷阱'
                )
            
        except Exception as e:
            logger.warning(f"[{code}] ROE过滤检查失败: {e}")
            return True, 0.0, f'ROE检查异常({e})，暂不过滤'
    
    def align_roe_to_daily(self, daily_df: pd.DataFrame, 
                           fina_df: pd.DataFrame) -> pd.DataFrame:
        """
        将季频ROE数据按发布日期对齐到日频（避免未来函数）
        
        原理：在财报发布日(pub_date)之前，使用上一期的ROE数据
        
        Args:
            daily_df: 日线数据（必须有'date'列）
            fina_df: 财务指标数据（必须有'pub_date'和'roe'列）
        
        Returns:
            daily_df加上'roe'列
        """
        if fina_df.empty or 'roe' not in fina_df.columns:
            result = daily_df.copy()
            result['roe'] = np.nan
            return result
        
        result = daily_df.copy()
        result['roe'] = np.nan
        
        # 按发布日期排序
        fina_sorted = fina_df.sort_values('pub_date').reset_index(drop=True)
        
        for _, row in fina_sorted.iterrows():
            pub_date = row['pub_date']
            roe_val = row['roe']
            # 在发布日期及之后，使用此ROE值
            mask = result['date'] >= pub_date
            result.loc[mask, 'roe'] = roe_val
        
        return result
    
    # ============================================================
    # 2. 行业分类获取
    # ============================================================
    
    def get_industry_classification(self, code: str, use_cache: bool = True) -> Optional[str]:
        """
        获取股票所属行业分类（证监会行业分类）
        
        使用baostock query_stock_industry，免费无限制
        
        Args:
            code: 股票代码（如 '600030'）
            use_cache: 是否使用缓存
        
        Returns:
            行业名称，如 'J67资本市场服务', 'C36汽车制造业' 等
            如果获取失败，返回 None
        """
        if use_cache and code in self._industry_cache:
            return self._industry_cache[code]
        
        # 尝试磁盘缓存
        cache_file = os.path.join(self._CACHE_DIR, 'industry_all.json')
        if use_cache and not self._all_industry_cache and os.path.exists(cache_file):
            try:
                cache_mtime = os.path.getmtime(cache_file)
                if time.time() - cache_mtime < 30 * 86400:  # 30天有效
                    with open(cache_file, 'r') as f:
                        self._all_industry_cache = json.load(f)
                    logger.debug(f"行业缓存加载: {len(self._all_industry_cache)}只")
            except Exception:
                pass
        
        if code in self._all_industry_cache:
            industry = self._all_industry_cache[code]
            self._industry_cache[code] = industry
            return industry
        
        # 实时查询
        self._ensure_bs_login()
        import baostock as bs
        
        bs_code = self._code_to_bs(code)
        try:
            rs = bs.query_stock_industry(code=bs_code)
            if rs.error_code == '0' and rs.next():
                row = rs.get_row_data()
                # fields: updateDate, code, code_name, industry, industryClassification
                if len(row) >= 4 and row[3]:
                    industry = row[3]
                    self._industry_cache[code] = industry
                    self._all_industry_cache[code] = industry
                    return industry
        except Exception as e:
            logger.error(f"[{code}] 行业分类获取失败: {e}")
        
        self._industry_cache[code] = None
        return None
    
    def get_industry_for_batch(self, codes: List[str]) -> Dict[str, str]:
        """
        批量获取行业分类（带缓存）
        
        Args:
            codes: 股票代码列表
        
        Returns:
            {code: industry} 字典
        """
        # 先加载磁盘缓存
        cache_file = os.path.join(self._CACHE_DIR, 'industry_all.json')
        if not self._all_industry_cache and os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    self._all_industry_cache = json.load(f)
            except Exception:
                pass
        
        result = {}
        missing = []
        
        for code in codes:
            if code in self._all_industry_cache:
                result[code] = self._all_industry_cache[code]
            else:
                missing.append(code)
        
        if missing:
            logger.info(f"批量获取行业分类: {len(missing)}只未缓存")
            self._ensure_bs_login()
            import baostock as bs
            
            for i, code in enumerate(missing):
                bs_code = self._code_to_bs(code)
                try:
                    rs = bs.query_stock_industry(code=bs_code)
                    if rs.error_code == '0' and rs.next():
                        row = rs.get_row_data()
                        if len(row) >= 4 and row[3]:
                            result[code] = row[3]
                            self._all_industry_cache[code] = row[3]
                except Exception:
                    pass
                
                # 每50只暂停一下
                if (i + 1) % 50 == 0:
                    time.sleep(0.5)
            
            # 保存缓存
            try:
                with open(cache_file, 'w') as f:
                    json.dump(self._all_industry_cache, f, ensure_ascii=False)
                logger.info(f"行业缓存已保存: {len(self._all_industry_cache)}只")
            except Exception:
                pass
        
        return result
    
    def get_stocks_by_industry(self, industry: str, 
                                stock_pool: List[str] = None) -> List[str]:
        """
        获取同行业的所有股票代码
        
        Args:
            industry: 行业名称（如 'J67资本市场服务'）
            stock_pool: 股票池（如果提供，只在池内筛选）
        
        Returns:
            同行业股票代码列表
        """
        if stock_pool:
            industry_map = self.get_industry_for_batch(stock_pool)
        elif self._all_industry_cache:
            industry_map = self._all_industry_cache
        else:
            logger.warning("无行业数据，请先调用 get_industry_for_batch")
            return []
        
        return [code for code, ind in industry_map.items() if ind == industry]
    
    # ============================================================
    # 3. 行业PE/PB数据聚合
    # ============================================================
    
    def get_industry_pe_pb_data(self, code: str, 
                                 stock_pool: List[str] = None,
                                 datalen: int = 800) -> Dict[str, pd.Series]:
        """
        聚合同行业所有股票的PE/PB数据（用于分行业分位数计算）
        
        流程：
        1. 获取目标股票的行业
        2. 找到同行业的所有股票
        3. 从缓存或实时获取所有同行业股票的PE/PB
        4. 拼接为一个大Series返回
        
        Args:
            code: 目标股票代码
            stock_pool: 可选股票池（限制同行业范围）
            datalen: 每只股票的K线数据量
        
        Returns:
            {'industry': 行业名, 'industry_pe': pd.Series, 'industry_pb': pd.Series,
             'same_industry_count': 同行业股票数}
        """
        # 1. 获取行业
        industry = self.get_industry_classification(code)
        if not industry:
            logger.warning(f"[{code}] 无法获取行业，使用个股数据")
            return {'industry': None, 'industry_pe': pd.Series(dtype=float), 
                    'industry_pb': pd.Series(dtype=float), 'same_industry_count': 0}
        
        # 2. 找同行业股票
        same_industry = self.get_stocks_by_industry(industry, stock_pool)
        if len(same_industry) < 3:
            logger.warning(f"[{code}] 行业'{industry}'股票过少({len(same_industry)}只)")
            return {'industry': industry, 'industry_pe': pd.Series(dtype=float),
                    'industry_pb': pd.Series(dtype=float), 'same_industry_count': len(same_industry)}
        
        logger.info(f"[{code}] 行业'{industry}' 共{len(same_industry)}只同行业股票")
        
        # 3. 尝试从缓存加载行业PE/PB数据
        cache_key = industry.replace('/', '_').replace(' ', '_')
        pe_cache = os.path.join(self._CACHE_DIR, f'industry_pe_{cache_key}.csv')
        pb_cache = os.path.join(self._CACHE_DIR, f'industry_pb_{cache_key}.csv')
        
        all_pe = []
        all_pb = []
        
        # 检查缓存
        if os.path.exists(pe_cache) and os.path.exists(pb_cache):
            cache_mtime = os.path.getmtime(pe_cache)
            if time.time() - cache_mtime < 3 * 86400:  # 3天有效
                try:
                    pe_df = pd.read_csv(pe_cache)
                    pb_df = pd.read_csv(pb_cache)
                    pe_series = pe_df['pe_ttm'].dropna()
                    pb_series = pb_df['pb'].dropna()
                    if len(pe_series) > 100:
                        logger.debug(f"行业'{industry}' PE/PB缓存命中")
                        return {
                            'industry': industry,
                            'industry_pe': pe_series,
                            'industry_pb': pb_series,
                            'same_industry_count': len(same_industry),
                        }
                except Exception:
                    pass
        
        # 4. 从baostock批量获取日频数据（PE/PB需要从行情计算或外部获取）
        # baostock的 query_history_k_data_plus 可以获取 peTTM, pbMRQ
        self._ensure_bs_login()
        import baostock as bs
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=datalen * 1.5)).strftime('%Y-%m-%d')
        
        fetched = 0
        for i, s_code in enumerate(same_industry[:50]):  # 最多50只，避免太慢
            bs_code = self._code_to_bs(s_code)
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,peTTM,pbMRQ",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="3"
                )
                rows = []
                while rs.error_code == '0' and rs.next():
                    rows.append(rs.get_row_data())
                
                if rows:
                    for r in rows:
                        pe_val = self._safe_float(r[1])
                        pb_val = self._safe_float(r[2])
                        if pe_val and pe_val > 0 and pe_val <= 100:
                            all_pe.append(pe_val)
                        if pb_val and pb_val > 0 and pb_val <= 20:
                            all_pb.append(pb_val)
                    fetched += 1
            except Exception as e:
                logger.debug(f"[{s_code}] 获取失败: {e}")
            
            # 限速
            if (i + 1) % 20 == 0:
                time.sleep(1)
        
        logger.info(f"行业'{industry}' 成功获取{fetched}/{len(same_industry[:50])}只, "
                     f"PE数据{len(all_pe)}条, PB数据{len(all_pb)}条")
        
        pe_series = pd.Series(all_pe, dtype=float)
        pb_series = pd.Series(all_pb, dtype=float)
        
        # 保存缓存
        try:
            pd.DataFrame({'pe_ttm': all_pe}).to_csv(pe_cache, index=False)
            pd.DataFrame({'pb': all_pb}).to_csv(pb_cache, index=False)
        except Exception:
            pass
        
        return {
            'industry': industry,
            'industry_pe': pe_series,
            'industry_pb': pb_series,
            'same_industry_count': len(same_industry),
        }
    
    # ============================================================
    # 4. 日频基本面数据（兼容旧接口）
    # ============================================================
    
    def get_daily_basic(self, code: str, start_date: str = None,
                       end_date: str = None) -> pd.DataFrame:
        """
        获取日频基本面数据（PE、PB、市值等）
        
        多数据源降级逻辑：
        1. Baostock（主力，包含peTTM和pbMRQ字段）
        2. AKShare实时行情（备用，只能获取单日数据）
        
        Args:
            code: 股票代码（如 '600030'）
            start_date: 开始日期 'YYYYMMDD' 或 'YYYY-MM-DD'
            end_date: 结束日期 'YYYYMMDD' 或 'YYYY-MM-DD'
        
        Returns:
            DataFrame with columns: date, name, pe_ttm, pb, turnover_rate, market_cap
        """
        # 转换日期格式 YYYYMMDD -> YYYY-MM-DD
        if start_date and len(start_date) == 8:
            start_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        if end_date and len(end_date) == 8:
            end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        
        if not start_date:
            start_date = (datetime.now() - timedelta(days=1200)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        # 方案1: Baostock（主力）
        try:
            self._ensure_bs_login()
            import baostock as bs
            
            bs_code = self._code_to_bs(code)
            
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,peTTM,pbMRQ,turn",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3"
            )
            
            rows = []
            while rs.error_code == '0' and rs.next():
                rows.append(rs.get_row_data())
            
            if rows:
                df = pd.DataFrame(rows, columns=['date', 'pe_ttm', 'pb', 'turnover_rate'])
                df['date'] = pd.to_datetime(df['date'])
                df['pe_ttm'] = pd.to_numeric(df['pe_ttm'], errors='coerce')
                df['pb'] = pd.to_numeric(df['pb'], errors='coerce')
                df['turnover_rate'] = pd.to_numeric(df['turnover_rate'], errors='coerce')
                df = df.sort_values('date').reset_index(drop=True)
                logger.info(f"✅ Baostock获取 {code} 日频基本面: {len(df)}条")
                return df
        except Exception as e:
            logger.warning(f"⚠️ Baostock获取 {code} 日频基本面失败: {e}")
        
        # 方案2: AKShare实时行情（只能获取单日数据）
        try:
            import akshare as ak
            df_spot = ak.stock_zh_a_spot_em()
            stock_row = df_spot[df_spot['代码'] == code]
            
            if not stock_row.empty:
                row = stock_row.iloc[0]
                # 构造单日数据
                today = datetime.now().strftime('%Y-%m-%d')
                df = pd.DataFrame([{
                    'date': pd.to_datetime(today),
                    'name': row['名称'] if '名称' in row else '',
                    'pe_ttm': float(row['市盈率-动态']) if '市盈率-动态' in row and pd.notna(row['市盈率-动态']) else None,
                    'pb': float(row['市净率']) if '市净率' in row and pd.notna(row['市净率']) else None,
                    'turnover_rate': float(row['换手率']) if '换手率' in row and pd.notna(row['换手率']) else None,
                    'market_cap': float(row['总市值']) if '总市值' in row and pd.notna(row['总市值']) else None,
                }])
                logger.info(f"✅ AKShare获取 {code} 实时基本面（单日）")
                return df
        except Exception as e:
            logger.warning(f"⚠️ AKShare获取 {code} 实时基本面失败: {e}")
        
        logger.error(f"❌ 所有数据源均失败: {code}")
        return pd.DataFrame()
    
    # ============================================================
    # 5. AkShare增强接口
    # ============================================================
    
    def get_industry_pe_cninfo(self, industry_name: str = None,
                                date: str = None) -> Dict:
        """
        通过巨潮接口直接获取行业PE数据（替代逐只聚合方案，快100倍）
        
        Args:
            industry_name: 行业名称（如"证券"、"银行"），为None返回全部
            date: 日期 'YYYYMMDD'，默认最近交易日
        
        Returns:
            {'industry_name': str, 'pe_weighted': float, 'pe_median': float,
             'pe_mean': float, 'company_count': int, 'total_market_cap': float}
            如果未找到行业返回 None
        """
        if not self._check_akshare():
            return None
        
        # 缓存key
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        cache_file = os.path.join(self._CACHE_DIR, f'industry_pe_cninfo_{date}.json')
        
        # 读缓存（1天有效）
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    all_data = json.load(f)
                if industry_name:
                    for item in all_data:
                        if industry_name in item.get('industry_name', ''):
                            return item
                    return None
                return all_data
            except Exception:
                pass
        
        try:
            import akshare as ak
            # 用国证行业分类（层级更细）
            df = ak.stock_industry_pe_ratio_cninfo(symbol="国证行业分类", date=date)
            
            if df.empty:
                # 回退到证监会分类
                df = ak.stock_industry_pe_ratio_cninfo(symbol="证监会行业分类", date=date)
            
            if df.empty:
                logger.warning(f"巨潮行业PE数据为空 ({date})")
                return None
            
            # 转换为标准格式
            all_data = []
            for _, row in df.iterrows():
                item = {
                    'industry_name': row.get('行业名称', ''),
                    'industry_code': row.get('行业编码', ''),
                    'industry_level': int(row.get('行业层级', 0)) if pd.notna(row.get('行业层级')) else 0,
                    'company_count': int(row.get('公司数量', 0)) if pd.notna(row.get('公司数量')) else 0,
                    'pe_weighted': float(row.get('静态市盈率-加权平均', 0)) if pd.notna(row.get('静态市盈率-加权平均')) else None,
                    'pe_median': float(row.get('静态市盈率-中位数', 0)) if pd.notna(row.get('静态市盈率-中位数')) else None,
                    'pe_mean': float(row.get('静态市盈率-算术平均', 0)) if pd.notna(row.get('静态市盈率-算术平均')) else None,
                    'total_market_cap': float(row.get('总市值-静态', 0)) if pd.notna(row.get('总市值-静态')) else None,
                }
                all_data.append(item)
            
            # 缓存
            try:
                with open(cache_file, 'w') as f:
                    json.dump(all_data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            
            logger.info(f"巨潮行业PE获取成功: {len(all_data)}个行业")
            
            if industry_name:
                # 模糊匹配行业名
                for item in all_data:
                    if industry_name in item.get('industry_name', ''):
                        return item
                # 再找一层
                for item in all_data:
                    if any(k in item.get('industry_name', '') for k in industry_name):
                        return item
                return None
            return all_data
            
        except Exception as e:
            logger.warning(f"巨潮行业PE获取失败: {e}")
            return None
    
    def get_valuation_baidu(self, code: str, indicator: str = "市盈率(TTM)",
                            period: str = "近一年") -> pd.DataFrame:
        """
        通过百度股市通获取个股估值历史数据（非东财源，不被封）
        
        Args:
            code: 股票代码（如 '600030'）
            indicator: 指标类型 "市盈率(TTM)" / "市净率" / "总市值" / "市销率(TTM)"
            period: "近一年" / "近三年" / "近五年" / "近十年" / "全部"
        
        Returns:
            DataFrame with columns: date, value
        """
        if not self._check_akshare():
            return pd.DataFrame()
        
        try:
            import akshare as ak
            df = ak.stock_zh_valuation_baidu(symbol=code, indicator=indicator, period=period)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                df['value'] = pd.to_numeric(df['value'], errors='coerce')
                logger.debug(f"[{code}] 百度估值({indicator}) {len(df)}条")
            return df
        except Exception as e:
            logger.debug(f"[{code}] 百度估值获取失败: {e}")
            return pd.DataFrame()
    
    def get_pe_pb_baidu(self, code: str, period: str = "近三年") -> pd.DataFrame:
        """
        通过百度获取PE+PB历史数据（合并）
        
        比baostock更稳定、数据更全。
        
        Returns:
            DataFrame with columns: date, pe_ttm, pb
        """
        pe_df = self.get_valuation_baidu(code, "市盈率(TTM)", period)
        pb_df = self.get_valuation_baidu(code, "市净率", period)
        
        if pe_df.empty and pb_df.empty:
            return pd.DataFrame()
        
        result = pd.DataFrame()
        if not pe_df.empty:
            result = pe_df.rename(columns={'value': 'pe_ttm'})
        if not pb_df.empty:
            if result.empty:
                result = pb_df.rename(columns={'value': 'pb'})
            else:
                result = pd.merge(result, pb_df.rename(columns={'value': 'pb'}),
                                  on='date', how='outer')
        
        result = result.sort_values('date').reset_index(drop=True)
        logger.info(f"[{code}] 百度PE/PB {len(result)}条")
        return result
    
    def get_fund_flow(self, code: str) -> pd.DataFrame:
        """
        获取个股资金流向数据（主力/超大/大/中/小单）
        
        Args:
            code: 股票代码
        
        Returns:
            DataFrame with columns:
                日期, 收盘价, 涨跌幅, 
                主力净流入-净额, 主力净流入-净占比,
                超大单净流入-净额, 超大单净流入-净占比, ...
        """
        if not self._check_akshare():
            return pd.DataFrame()
        
        try:
            import akshare as ak
            market = 'sh' if code.startswith(('5', '6', '9')) else 'sz'
            df = ak.stock_individual_fund_flow(stock=code, market=market)
            if not df.empty:
                logger.debug(f"[{code}] 资金流 {len(df)}条")
            return df
        except Exception as e:
            logger.debug(f"[{code}] 资金流获取失败: {e}")
            return pd.DataFrame()
    
    def get_fund_flow_signal(self, code: str) -> Dict:
        """
        根据资金流向给出辅助信号
        
        Returns:
            {'signal': 'bullish'/'bearish'/'neutral',
             'main_net_inflow_5d': float,  # 近5日主力净流入
             'main_net_ratio_today': float,  # 今日主力净占比
             'big_order_trend': str,  # 大单趋势
             'reason': str}
        """
        df = self.get_fund_flow(code)
        if df.empty or len(df) < 5:
            return {'signal': 'neutral', 'main_net_inflow_5d': 0,
                    'main_net_ratio_today': 0, 'big_order_trend': 'unknown',
                    'reason': '资金流数据不足'}
        
        # 近5日主力净流入
        recent = df.tail(5)
        main_col = '主力净流入-净额'
        ratio_col = '主力净流入-净占比'
        
        if main_col not in df.columns:
            return {'signal': 'neutral', 'main_net_inflow_5d': 0,
                    'main_net_ratio_today': 0, 'big_order_trend': 'unknown',
                    'reason': '资金流列名不匹配'}
        
        net_5d = recent[main_col].sum()
        ratio_today = df[ratio_col].iloc[-1] if ratio_col in df.columns else 0
        
        # 连续流入/流出天数
        signs = (df[main_col].tail(10) > 0).tolist()
        
        consecutive_in = 0
        for s in reversed(signs):
            if s:
                consecutive_in += 1
            else:
                break
        
        consecutive_out = 0
        for s in reversed(signs):
            if not s:
                consecutive_out += 1
            else:
                break
        
        # 判断信号
        signal = 'neutral'
        reason_parts = []
        
        if net_5d > 0 and consecutive_in >= 3:
            signal = 'bullish'
            reason_parts.append(f'主力连续{consecutive_in}日净流入')
        elif net_5d < 0 and consecutive_out >= 3:
            signal = 'bearish'
            reason_parts.append(f'主力连续{consecutive_out}日净流出')
        elif ratio_today > 5:
            signal = 'bullish'
            reason_parts.append(f'今日主力净占比{ratio_today:.1f}%')
        elif ratio_today < -5:
            signal = 'bearish'
            reason_parts.append(f'今日主力净占比{ratio_today:.1f}%')
        
        reason_parts.append(f'5日主力净流入{net_5d/1e8:.1f}亿')
        
        return {
            'signal': signal,
            'main_net_inflow_5d': net_5d,
            'main_net_ratio_today': ratio_today,
            'big_order_trend': f'连续流入{consecutive_in}日' if consecutive_in > 0 else f'连续流出{consecutive_out}日',
            'reason': '; '.join(reason_parts),
        }
    
    def get_index_components_akshare(self, index_code: str = "000300") -> List[str]:
        """
        通过中证指数网获取指数成分股（实时最新，替代手动维护）
        
        Args:
            index_code: "000300"(沪深300) / "000905"(中证500) / "000852"(中证1000)
        
        Returns:
            股票代码列表 ['000001', '000002', ...]
        """
        if not self._check_akshare():
            return []
        
        cache_file = os.path.join(self._CACHE_DIR, f'index_components_{index_code}.json')
        # 30天缓存
        if os.path.exists(cache_file):
            if time.time() - os.path.getmtime(cache_file) < 30 * 86400:
                try:
                    with open(cache_file, 'r') as f:
                        return json.load(f)
                except Exception:
                    pass
        
        try:
            import akshare as ak
            df = ak.index_stock_cons_csindex(symbol=index_code)
            if df.empty:
                return []
            
            codes = df['成分券代码'].tolist()
            
            # 缓存
            try:
                with open(cache_file, 'w') as f:
                    json.dump(codes, f)
            except Exception:
                pass
            
            logger.info(f"指数{index_code}成分股: {len(codes)}只")
            return codes
            
        except Exception as e:
            logger.warning(f"获取指数{index_code}成分股失败: {e}")
            return []
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def merge_to_daily(self, daily_df: pd.DataFrame,
                       fundamental_df: pd.DataFrame,
                       fill_method: str = 'ffill') -> pd.DataFrame:
        """
        将基本面数据合并到日线数据，并填充缺失值
        
        Args:
            daily_df: 日线数据（date, open, high, low, close, volume）
            fundamental_df: 基本面数据（date, pe_ttm, pb, ...）
            fill_method: 填充方法 ('ffill' 前向填充)
        
        Returns:
            合并后的 DataFrame
        """
        if fundamental_df.empty:
            return daily_df.copy()
        
        daily_df = daily_df.copy()
        daily_df['date'] = pd.to_datetime(daily_df['date'])
        fundamental_df = fundamental_df.copy()
        fundamental_df['date'] = pd.to_datetime(fundamental_df['date'])
        
        merged = pd.merge(
            daily_df, fundamental_df,
            on='date', how='left',
            suffixes=('', '_fund')
        )
        
        merged = merged.sort_values('date').reset_index(drop=True)
        
        fundamental_cols = [c for c in fundamental_df.columns if c != 'date']
        for col in fundamental_cols:
            if col in merged.columns:
                merged[col] = merged[col].fillna(method=fill_method)
                # 头部NaN用后向填充
                if pd.isna(merged[col].iloc[0]):
                    merged[col] = merged[col].fillna(method='bfill')
        
        return merged
    
    @staticmethod
    def _safe_float(val) -> Optional[float]:
        """安全转换为float"""
        try:
            if val == '' or val is None:
                return None
            return float(val)
        except (ValueError, TypeError):
            return None


# ============================================================
# 便捷函数
# ============================================================

def create_mock_fundamental_data(daily_df: pd.DataFrame,
                                 pe_range: tuple = (5, 50),
                                 pb_range: tuple = (0.5, 5.0),
                                 random_seed: int = 42) -> pd.DataFrame:
    """
    创建模拟基本面数据（仅用于测试流程，不可用于真实回测）
    
    ⚠️ 警告: 此函数基于整个DataFrame的价格生成PE/PB，隐含未来信息。
    """
    rng = np.random.RandomState(random_seed)
    df = daily_df.copy()
    
    price_normalized = (df['close'] - df['close'].min()) / (df['close'].max() - df['close'].min() + 1e-6)
    pe_base = pe_range[0] + price_normalized * (pe_range[1] - pe_range[0])
    noise = rng.normal(0, (pe_range[1] - pe_range[0]) * 0.1, len(df))
    df['pe_ttm'] = np.clip(pe_base + noise, pe_range[0], pe_range[1])
    
    pb_base = pb_range[0] + price_normalized * (pb_range[1] - pb_range[0])
    noise = rng.normal(0, (pb_range[1] - pb_range[0]) * 0.1, len(df))
    df['pb'] = np.clip(pb_base + noise, pb_range[0], pb_range[1])
    
    return df[['date', 'pe_ttm', 'pb']]
