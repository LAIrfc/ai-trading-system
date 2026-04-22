"""
行业趋势前瞻策略（IndustryTrend）

核心能力：识别个股所处行业是否正在经历爆发式增长，捕捉"赛道逻辑"带来的估值重构机会。

数据来源：
1. 个股新闻中提取的行业关键词（从 NEWS 策略缓存获取 event_driven.sector_trend）
2. 东财/妙想搜索行业热点新闻
3. LLM 行业趋势判断（行业渗透率、增速、政策支持度、国产替代空间）

信号逻辑：
- 高景气赛道（LLM判定景气度≥0.7）+ 个股有实质业务切入 → BUY
- 行业进入下行周期（景气度≤0.3）→ SELL
- 其他 → HOLD

置信度 = 行业景气度 × 个股切入深度（有产品/订单 > 有布局 > 仅概念）
"""

import json
import logging
import re
from typing import Dict, Optional

import pandas as pd

from .base import Strategy, StrategySignal

logger = logging.getLogger(__name__)

_TREND_CACHE: Dict[str, dict] = {}

_SECTOR_KEYWORDS = {
    "AI数据中心": ["AI数据中心", "算力", "智算中心", "GPU服务器", "液冷", "AI芯片"],
    "光通信/OCS": ["OCS", "光交叉", "光开关", "光模块", "CPO", "硅光", "800G", "1.6T", "光互联"],
    "MEMS": ["MEMS", "微机电", "微镜", "惯性传感"],
    "商业航天": ["商业航天", "卫星", "火箭", "低轨", "星座", "卫星互联网", "北斗"],
    "新能源车": ["新能源车", "电动车", "动力电池", "固态电池", "充电桩", "智能驾驶"],
    "半导体": ["半导体", "芯片", "晶圆", "封装", "EDA", "光刻", "国产替代"],
    "人形机器人": ["人形机器人", "机器人", "减速器", "伺服", "丝杠", "灵巧手"],
    "低空经济": ["低空经济", "eVTOL", "飞行汽车", "无人机", "空中交通"],
}

_LLM_TREND_SYSTEM = (
    "你是A股行业趋势分析师，擅长识别处于爆发期的新兴行业赛道。"
    "只输出 JSON，不要任何其他文字。"
)

_LLM_TREND_PROMPT = """请分析以下行业/赛道的当前景气度和趋势：

行业赛道: {sector}
相关个股: {name}({symbol})
个股与赛道关系: {relation}

最新行业动态:
{news_summary}

请从以下维度评估，输出 JSON：
{{
  "prosperity": <0.0到1.0，行业景气度，0衰退/1极度景气>,
  "growth_stage": "<导入期|成长期|爆发期|成熟期|衰退期>",
  "penetration": "<低(<10%)|中(10-40%)|高(>40%)，行业渗透率>",
  "policy_support": <0.0到1.0，政策支持力度>,
  "domestic_substitute": <true/false，是否有国产替代逻辑>,
  "stock_depth": "<概念|布局|产品|订单|量产，个股切入深度>",
  "key_drivers": ["<驱动因素1>", "<驱动因素2>"],
  "risks": ["<风险1>"],
  "reason": "<80字以内的行业趋势判断>"
}}"""


def _detect_sector_from_news(symbol: str, stock_name: str) -> Optional[str]:
    """从 NEWS 策略缓存的 event_driven 或关键词匹配推断行业赛道。"""
    from .news_sentiment import _SESSION_NEWS_CACHE
    cached = _SESSION_NEWS_CACHE.get(symbol)
    if cached and len(cached) > 3 and cached[3]:
        event_driven = cached[3]
        sector_trend = event_driven.get("sector_trend", "")
        if sector_trend:
            return sector_trend

    try:
        from src.data.news import fetch_stock_news
    except ImportError:
        try:
            from data.news import fetch_stock_news
        except ImportError:
            return None

    # 尝试用股票代码和名称搜索新闻
    all_text = ""
    try:
        df = fetch_stock_news(symbol, max_items=15)
        if df is not None and not df.empty:
            all_text = " ".join(df["title"].dropna().tolist()[:15])
    except Exception as e:
        logger.debug("行业赛道检测 (代码搜索) 失败 %s: %s", symbol, e)

    # 如果股票名称搜索能获得更多结果，合并
    if stock_name:
        try:
            df2 = fetch_stock_news(stock_name, max_items=10)
            if df2 is not None and not df2.empty:
                all_text += " " + " ".join(df2["title"].dropna().tolist()[:10])
        except Exception:
            pass

    if all_text:
        for sector, keywords in _SECTOR_KEYWORDS.items():
            for kw in keywords:
                if kw in all_text:
                    return sector

    # 最后尝试 MX 搜索（消耗配额，但覆盖更广）
    if stock_name:
        try:
            import os
            if os.environ.get("MX_APIKEY"):
                from src.data.mx_skills.client import MXSkillsClient
                client = MXSkillsClient()
                result = client.search_news(f"{stock_name} 行业 赛道", max_results=5)
                if result and isinstance(result, list):
                    mx_text = " ".join(r.get("title", "") for r in result[:5])
                    for sector, keywords in _SECTOR_KEYWORDS.items():
                        for kw in keywords:
                            if kw in mx_text:
                                return sector
        except Exception as e:
            logger.debug("MX搜索行业赛道失败 %s: %s", stock_name, e)

    return None


def _fetch_sector_news(sector: str, max_items: int = 10) -> str:
    """获取行业相关新闻摘要。"""
    try:
        from src.data.news import fetch_stock_news
    except ImportError:
        try:
            from data.news import fetch_stock_news
        except ImportError:
            return ""

    try:
        from src.data.mx_skills.news_adapter import MXNewsFetcher
        fetcher = MXNewsFetcher()
        df = fetcher.search_news(sector, max_items=max_items)
        if df is not None and not df.empty:
            titles = df["title"].dropna().tolist()[:max_items]
            return "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    except Exception:
        pass

    try:
        import os
        if os.environ.get("MX_APIKEY"):
            from src.data.mx_skills.client import MXSkillsClient
            client = MXSkillsClient()
            result = client.search_news(sector, max_results=max_items)
            if result and isinstance(result, list):
                return "\n".join(f"{i+1}. {r.get('title', '')}" for i, r in enumerate(result[:max_items]))
    except Exception:
        pass

    return f"(无法获取{sector}行业最新新闻)"


def _llm_analyze_trend(
    sector: str, symbol: str, stock_name: str,
    relation: str, news_summary: str,
) -> Optional[dict]:
    """用 LLM 分析行业趋势。"""
    try:
        from src.data.ai_analyst import call_llm
    except ImportError:
        try:
            import sys, os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
            from src.data.ai_analyst import call_llm
        except ImportError:
            return None

    prompt = _LLM_TREND_PROMPT.format(
        sector=sector, name=stock_name or symbol, symbol=symbol,
        relation=relation, news_summary=news_summary or "(无)",
    )

    try:
        result = call_llm(prompt=prompt, system_prompt=_LLM_TREND_SYSTEM,
                          max_tokens=300, temperature=0.1)
        if not result:
            return None
        m = re.search(r'\{.*\}', result, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        return data
    except Exception as e:
        logger.debug("LLM 行业趋势分析失败 %s: %s", sector, e)
        return None


_DEPTH_SCORE = {
    "量产": 1.0, "订单": 0.85, "产品": 0.7, "布局": 0.5, "概念": 0.25,
}


class IndustryTrendStrategy(Strategy):
    """行业趋势前瞻策略：识别个股所在赛道的景气度和爆发信号。"""

    name = "IndustryTrend"
    description = "行业趋势前瞻：赛道景气度+个股切入深度→事件驱动买入/卖出信号"

    min_bars = 0

    def __init__(self, symbol: Optional[str] = None, stock_name: str = "", **kwargs):
        self.symbol = symbol
        self.stock_name = stock_name

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        from .base import _BACKTEST_ACTIVE
        symbol = self.symbol
        if not symbol:
            return StrategySignal("HOLD", 0.0, "未指定标的", 0.5, {})

        if _BACKTEST_ACTIVE:
            return StrategySignal("HOLD", 0.0, "回测中不执行行业趋势分析", 0.5, {})

        if symbol in _TREND_CACHE:
            return _TREND_CACHE[symbol]

        try:
            result = self._analyze_impl(symbol)
            _TREND_CACHE[symbol] = result
            return result
        except Exception as e:
            logger.warning("[IndustryTrend] %s 分析异常: %s", symbol, e)
            return StrategySignal("HOLD", 0.0, f"行业趋势分析异常: {e}", 0.5, {})

    def _analyze_impl(self, symbol: str) -> StrategySignal:
        sector = _detect_sector_from_news(symbol, self.stock_name)
        if not sector:
            return StrategySignal(
                "HOLD", 0.0, "未检测到明确行业赛道标签",
                0.5, {"sector": None},
            )

        news_summary = _fetch_sector_news(sector, max_items=8)

        from .news_sentiment import _SESSION_NEWS_CACHE
        cached = _SESSION_NEWS_CACHE.get(symbol)
        relation = "未知"
        if cached and len(cached) > 3 and cached[3]:
            cat_type = cached[3].get("catalyst_type", "")
            if cat_type:
                relation = cat_type

        trend = _llm_analyze_trend(sector, symbol, self.stock_name, relation, news_summary)
        if not trend:
            return StrategySignal(
                "HOLD", 0.0, f"赛道{sector}的LLM趋势分析不可用",
                0.5, {"sector": sector},
            )

        prosperity = float(trend.get("prosperity", 0.5))
        prosperity = max(0.0, min(1.0, prosperity))
        growth_stage = trend.get("growth_stage", "成熟期")
        stock_depth = trend.get("stock_depth", "概念")
        depth_score = _DEPTH_SCORE.get(stock_depth, 0.25)
        policy_support = float(trend.get("policy_support", 0.5))
        domestic_sub = trend.get("domestic_substitute", False)
        reason_text = trend.get("reason", "")

        indicators = {
            "sector": sector,
            "prosperity": round(prosperity, 2),
            "growth_stage": growth_stage,
            "stock_depth": stock_depth,
            "depth_score": round(depth_score, 2),
            "policy_support": round(policy_support, 2),
            "domestic_substitute": domestic_sub,
            "key_drivers": trend.get("key_drivers", []),
            "risks": trend.get("risks", []),
        }

        confidence = prosperity * depth_score
        if domestic_sub:
            confidence = min(1.0, confidence * 1.15)
        if policy_support > 0.7:
            confidence = min(1.0, confidence * 1.1)
        confidence = min(1.0, confidence)

        if prosperity >= 0.7 and depth_score >= 0.5:
            pos = min(0.85, 0.5 + 0.35 * min(prosperity, 1.0) * depth_score)
            stage_label = f"({growth_stage})" if growth_stage in ("爆发期", "成长期") else ""
            return StrategySignal(
                action="BUY",
                confidence=round(confidence, 2),
                position=round(pos, 2),
                reason=f"赛道{sector}{stage_label}景气度{prosperity:.0%}+切入深度{stock_depth}|{reason_text}",
                indicators=indicators,
            )

        if prosperity <= 0.3:
            return StrategySignal(
                action="SELL",
                confidence=round(min(0.8, (1 - prosperity) * depth_score), 2),
                position=0.2,
                reason=f"赛道{sector}景气度低({prosperity:.0%})|{reason_text}",
                indicators=indicators,
            )

        return StrategySignal(
            action="HOLD",
            confidence=0.5,
            position=0.5,
            reason=f"赛道{sector}景气度{prosperity:.0%}切入{stock_depth}，暂观望|{reason_text}",
            indicators=indicators,
        )
