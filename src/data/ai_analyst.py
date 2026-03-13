"""
AI 大模型综合分析模块

使用 OpenAI 兼容接口调用 LLM 生成投资分析结论。
支持 DeepSeek / 通义千问 / Minimax / OpenAI 等任何兼容 API。

配置方式（优先级从高到低）：
1. 函数参数直接传入
2. 环境变量 AI_API_KEY, AI_BASE_URL, AI_MODEL
3. 配置文件 mydate/ai_config.json

使用示例::

    from src.data.ai_analyst import generate_ai_analysis

    conclusion = generate_ai_analysis(
        market_context="上证指数3280点，两市缩量...",
        stock_context="贵州茅台: PE 28x, 近5日涨3%...",
    )
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 预设的 API 端点
KNOWN_PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "minimax": {
        "base_url": "https://api.minimaxi.chat/v1",
        "model": "MiniMax-M2.1",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "silicon": {
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
    },
}

CONFIG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "mydate", "ai_config.json"
)

SYSTEM_PROMPT = (
    "你是专业的A股投资分析师，擅长技术面、基本面、资金面和情绪面分析。"
    "请基于提供的真实市场数据，给出简洁、专业、可操作的投资分析和建议。"
    "所有分析必须基于数据，不要编造数据。"
    "如果数据不足以做出判断，请如实说明。"
)


def _load_config() -> Dict[str, str]:
    """从配置文件读取 AI API 设置。"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _resolve_config(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, str]:
    """
    按优先级解析 API 配置：函数参数 > 环境变量 > 配置文件 > 默认 deepseek。
    """
    file_cfg = _load_config()

    resolved_provider = (
        provider
        or os.environ.get("AI_PROVIDER", "").strip()
        or file_cfg.get("provider", "")
    ).lower()

    preset = KNOWN_PROVIDERS.get(resolved_provider, {})

    resolved = {
        "api_key": (
            api_key
            or os.environ.get("AI_API_KEY", "").strip()
            or file_cfg.get("api_key", "")
        ),
        "base_url": (
            base_url
            or os.environ.get("AI_BASE_URL", "").strip()
            or file_cfg.get("base_url", "")
            or preset.get("base_url", "")
        ),
        "model": (
            model
            or os.environ.get("AI_MODEL", "").strip()
            or file_cfg.get("model", "")
            or preset.get("model", "deepseek-chat")
        ),
        "provider": resolved_provider or "deepseek",
    }

    return resolved


def call_llm(
    prompt: str,
    system_prompt: str = SYSTEM_PROMPT,
    max_tokens: int = 2000,
    temperature: float = 0.3,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    timeout: int = 60,
) -> Optional[str]:
    """
    调用 LLM（OpenAI 兼容接口）。

    Parameters
    ----------
    prompt : str
        用户输入（市场数据摘要等）
    system_prompt : str
        系统提示词
    max_tokens : int
        最大输出 token
    temperature : float
        生成温度
    api_key / base_url / model / provider : str
        API 配置，未提供时自动从环境变量或配置文件读取

    Returns
    -------
    str or None
        LLM 返回的文本，失败返回 None
    """
    cfg = _resolve_config(api_key, base_url, model, provider)

    if not cfg["api_key"]:
        logger.warning(
            "AI API Key 未配置。请设置环境变量 AI_API_KEY 或创建 %s",
            CONFIG_FILE,
        )
        return None

    if not cfg["base_url"]:
        logger.warning("AI Base URL 未配置")
        return None

    try:
        import requests

        url = cfg["base_url"].rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        logger.info(
            "调用 AI 分析 [%s/%s] prompt=%d chars",
            cfg["provider"],
            cfg["model"],
            len(prompt),
        )

        r = requests.post(url, json=payload, headers=headers, timeout=timeout)

        if r.status_code != 200:
            logger.error("AI API 返回 %d: %s", r.status_code, r.text[:500])
            return None

        result = r.json()
        if "choices" in result and result["choices"]:
            content = result["choices"][0]["message"]["content"]
            logger.info("AI 分析成功，返回 %d 字符", len(content))
            return content

        logger.warning("AI 返回结构异常: %s", str(result)[:300])
        return None

    except Exception as e:
        logger.error("AI API 调用异常: %s", e)
        return None


# ============================================================
# 高级分析接口
# ============================================================

def generate_market_analysis(
    panorama_text: str,
    stock_details: str = "",
    portfolio_text: str = "",
    extra_context: str = "",
    **llm_kwargs,
) -> str:
    """
    生成市场综合分析报告。

    Parameters
    ----------
    panorama_text : str
        市场全景数据（由 format_panorama_for_prompt 生成）
    stock_details : str
        重点个股的技术/基本面数据
    portfolio_text : str
        持仓信息（可选）
    extra_context : str
        其他上下文（新闻摘要、政策等）

    Returns
    -------
    str
        AI 分析报告文本；LLM 不可用时返回规则版分析
    """
    prompt_parts = []

    prompt_parts.append("请基于以下真实市场数据，给出今日投资分析：\n")

    if panorama_text:
        prompt_parts.append(panorama_text)

    if stock_details:
        prompt_parts.append(f"\n【重点个股数据】\n{stock_details}")

    if portfolio_text:
        prompt_parts.append(f"\n【当前持仓】\n{portfolio_text}")

    if extra_context:
        prompt_parts.append(f"\n【其他信息】\n{extra_context}")

    prompt_parts.append(
        "\n请输出以下内容：\n"
        "1. 【核心结论】一句话总结今日市场状态和操作建议\n"
        "2. 【市场环境】从技术面、资金面、情绪面三个维度分析\n"
        "3. 【板块机会】今日最值得关注的2-3个板块及原因\n"
        "4. 【风险提示】需要警惕的风险信号\n"
    )

    if portfolio_text:
        prompt_parts.append("5. 【持仓建议】针对持仓股给出具体操作建议\n")

    prompt_parts.append(
        "\n要求：\n"
        "- 结论具体、可操作，不说空话\n"
        "- 必须引用具体数据支撑观点\n"
        "- 总字数控制在600字以内\n"
        "- 使用中文，语气专业但易懂\n"
    )

    prompt = "\n".join(prompt_parts)

    ai_result = call_llm(prompt, **llm_kwargs)
    if ai_result:
        return ai_result

    logger.info("AI 不可用，使用规则版分析")
    return _generate_rule_based_analysis(panorama_text)


def generate_stock_analysis(
    code: str,
    name: str,
    price_data: str,
    fundamental_data: str = "",
    news_summary: str = "",
    **llm_kwargs,
) -> str:
    """
    生成单个股票的 AI 深度分析。

    Parameters
    ----------
    code : str
        股票代码
    name : str
        股票名称
    price_data : str
        价格和技术指标数据
    fundamental_data : str
        基本面数据
    news_summary : str
        近期新闻摘要

    Returns
    -------
    str
        AI 个股分析
    """
    prompt = (
        f"请对 {name}({code}) 进行深度分析：\n\n"
        f"【行情数据】\n{price_data}\n"
    )
    if fundamental_data:
        prompt += f"\n【基本面】\n{fundamental_data}\n"
    if news_summary:
        prompt += f"\n【近期新闻】\n{news_summary}\n"

    prompt += (
        "\n请输出：\n"
        "1. 技术面分析（趋势、支撑位、压力位、量价关系）\n"
        "2. 基本面评价（估值水平、行业对比）\n"
        "3. 操作建议（买入/持有/卖出，目标价位，止损位）\n"
        "4. 风险提示\n"
        "\n要求简洁专业，300字以内。\n"
    )

    ai_result = call_llm(prompt, **llm_kwargs)
    if ai_result:
        return ai_result

    return f"[{name}({code})] AI 分析暂不可用，请配置 AI API Key。"


# ============================================================
# 规则版备用分析（无需 API）
# ============================================================

def _generate_rule_based_analysis(panorama_text: str) -> str:
    """
    参考 stock-sentiment-cn 的规则版分析，基于市场数据生成简单结论。
    当 AI API 不可用时作为降级方案。
    """
    lines = []
    lines.append("【规则版市场分析（AI暂不可用）】\n")
    lines.append("由于 AI API 未配置，以下为基于规则的简要分析：\n")

    if not panorama_text:
        lines.append("市场数据未获取，无法分析。\n")
        lines.append("请配置 AI API Key 以启用智能分析。\n")
        lines.append("配置方式：\n")
        lines.append("  export AI_API_KEY=你的API密钥\n")
        lines.append("  export AI_PROVIDER=deepseek  # 或 qwen/minimax/openai\n")
        return "\n".join(lines)

    lines.append("已获取的市场数据：\n")
    lines.append(panorama_text)
    lines.append("\n---\n")
    lines.append("如需 AI 智能分析，请配置以下环境变量：\n")
    lines.append("  export AI_API_KEY=你的API密钥\n")
    lines.append("  export AI_PROVIDER=deepseek\n")
    lines.append("DeepSeek 新用户注册即送免费额度：https://platform.deepseek.com\n")

    return "\n".join(lines)


# ============================================================
# 配置辅助
# ============================================================

def save_ai_config(
    api_key: str,
    provider: str = "deepseek",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """
    保存 AI 配置到 mydate/ai_config.json。

    Returns
    -------
    str
        配置文件路径
    """
    preset = KNOWN_PROVIDERS.get(provider.lower(), {})
    config = {
        "provider": provider.lower(),
        "api_key": api_key,
        "base_url": base_url or preset.get("base_url", ""),
        "model": model or preset.get("model", ""),
    }
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    logger.info("AI 配置已保存到 %s", CONFIG_FILE)
    return CONFIG_FILE


def check_ai_config() -> Dict[str, Any]:
    """
    检查当前 AI 配置状态。

    Returns
    -------
    dict
        provider, model, has_key, base_url
    """
    cfg = _resolve_config()
    return {
        "provider": cfg["provider"],
        "model": cfg["model"],
        "has_key": bool(cfg["api_key"]),
        "base_url": cfg["base_url"],
        "config_file": CONFIG_FILE,
        "env_vars": {
            "AI_API_KEY": "***" if os.environ.get("AI_API_KEY") else "(未设置)",
            "AI_PROVIDER": os.environ.get("AI_PROVIDER", "(未设置)"),
            "AI_BASE_URL": os.environ.get("AI_BASE_URL", "(未设置)"),
            "AI_MODEL": os.environ.get("AI_MODEL", "(未设置)"),
        },
    }
