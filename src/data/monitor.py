"""
数据层监控与告警（文档 3.4）：成功率、耗时、备用触发占比、缓存命中率；
关键接口连续失败邮件/钉钉告警。
"""

import logging
import os
import time
from collections import defaultdict
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# 指标：接口名 -> list of (success: bool, elapsed: float, used_backup: bool)
_metrics: dict = defaultdict(list)
# 最近 N 条保留
MAX_RECORDS_PER_SOURCE = 200
# 连续失败阈值触发告警
ALERT_FAIL_THRESHOLD = 3
# 告警回调：参数 (message: str, source: str, fail_count: int)
ALERT_CALLBACK: Optional[Callable[[str, str, int], None]] = None


def record_fetch(
    source: str,
    success: bool,
    elapsed_seconds: float = 0.0,
    used_backup: bool = False,
) -> None:
    """记录一次拉取结果。"""
    _metrics[source].append((success, elapsed_seconds, used_backup))
    if len(_metrics[source]) > MAX_RECORDS_PER_SOURCE:
        _metrics[source] = _metrics[source][-MAX_RECORDS_PER_SOURCE:]
    if not success:
        _check_alert(source)


def _check_alert(source: str) -> None:
    """若该 source 连续失败次数 >= 阈值则触发告警。"""
    recs = _metrics.get(source, [])
    n = 0
    for success, _, _ in reversed(recs):
        if success:
            break
        n += 1
    if n >= ALERT_FAIL_THRESHOLD and ALERT_CALLBACK:
        try:
            ALERT_CALLBACK(
                f"数据源 {source} 连续失败 {n} 次，请检查接口或网络。",
                source,
                n,
            )
        except Exception as e:
            logger.debug("告警回调异常: %s", e)


def get_stats(source: Optional[str] = None) -> dict:
    """
    返回统计：成功率、平均耗时、备用触发占比。
    若 source 为 None 则返回所有 source 的汇总。
    """
    if source:
        recs = _metrics.get(source, [])
    else:
        recs = []
        for v in _metrics.values():
            recs.extend(v)
    if not recs:
        return {"success_rate": 0.0, "avg_elapsed": 0.0, "backup_ratio": 0.0, "count": 0}
    total = len(recs)
    success = sum(1 for s, _, _ in recs if s)
    elapsed = [e for _, e, _ in recs if e and e > 0]
    backup = sum(1 for _, _, b in recs if b)
    return {
        "success_rate": success / total if total else 0.0,
        "avg_elapsed": sum(elapsed) / len(elapsed) if elapsed else 0.0,
        "backup_ratio": backup / total if total else 0.0,
        "count": total,
    }


def set_alert_callback(callback: Callable[[str, str, int], None]) -> None:
    """设置告警回调（如发邮件/钉钉）。"""
    global ALERT_CALLBACK
    ALERT_CALLBACK = callback


def send_alert_dingding(webhook_url: str, msg: str, source: str, fail_count: int) -> None:
    """
    钉钉机器人 webhook 发送告警。需设置 DINGDING_WEBHOOK 或传入 webhook_url。
    """
    url = webhook_url or os.environ.get("DINGDING_WEBHOOK", "").strip()
    if not url:
        logger.warning("未配置 DINGDING_WEBHOOK，跳过钉钉告警")
        return
    try:
        import requests
        body = {"msgtype": "text", "text": {"content": f"[数据告警] {msg}\n来源: {source}\n连续失败: {fail_count}"}}
        requests.post(url, json=body, timeout=5)
    except Exception as e:
        logger.debug("钉钉告警发送失败: %s", e)


def send_alert_email(to_addrs: str, msg: str, source: str, fail_count: int) -> None:
    """
    邮件告警（需 smtplib 配置）。环境变量 SMTP_* 或传入 to_addrs。
    """
    to_addrs = to_addrs or os.environ.get("ALERT_EMAIL_TO", "").strip()
    if not to_addrs:
        logger.warning("未配置 ALERT_EMAIL_TO，跳过邮件告警")
        return
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.utils import formatdate
        msg_obj = MIMEText(f"{msg}\n来源: {source}\n连续失败: {fail_count}", "plain", "utf-8")
        msg_obj["Subject"] = "[数据告警] " + source
        msg_obj["Date"] = formatdate(localtime=True)
        host = os.environ.get("SMTP_HOST", "localhost")
        port = int(os.environ.get("SMTP_PORT", "25"))
        user = os.environ.get("SMTP_USER", "")
        password = os.environ.get("SMTP_PASSWORD", "")
        with smtplib.SMTP(host, port) as s:
            if user and password:
                s.login(user, password)
            s.sendmail(os.environ.get("SMTP_FROM", "alerts@local"), to_addrs.split(","), msg_obj.as_string())
    except Exception as e:
        logger.debug("邮件告警发送失败: %s", e)
