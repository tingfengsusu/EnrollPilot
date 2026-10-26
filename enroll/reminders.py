"""班期驱动的消息提醒（P2，纯逻辑，离线可测）。

两类提醒（设计文档 六）：

1. **缴费逾期**：报名后 N 天仍是「未收/部分收款」→ 提醒业务员；
2. **开班提醒**：班期开始前一天 → 发该班期报名名单提醒。

日期兼容两种来源：DemoStore 的字符串（"2026-06-24"）与 bitable 的毫秒时间戳。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

_UNPAID_STATES = ("未收", "部分收款")


def to_date(value) -> Optional[date]:
    """字符串 / 毫秒时间戳 → date；解析不了返回 None。"""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000).date()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def due_reminders(records: List[Dict], sessions: List[Dict], today: date,
                  unpaid_days: int = 3) -> List[str]:
    """返回今天应发的提醒文案（空列表 = 无提醒）。"""
    out: List[str] = []

    for rec in records or []:
        name = rec.get("姓名", "")
        if rec.get("缴费状态") not in _UNPAID_STATES:
            continue
        start = to_date(rec.get("登记日期"))
        if start is None:
            continue
        days = (today - start).days
        if days >= unpaid_days:
            amount = rec.get("缴费")
            tail = f"（{amount} 元）" if amount not in (None, "") else ""
            out.append(f"缴费提醒：{name} 报名已 {days} 天未缴费{tail}")

    for session in sessions or []:
        # 班期以「考试时间」为衡量标准：优先考试日期，兼容旧的起始日期
        exam = to_date(session.get("考试日期")) or to_date(session.get("起始日期"))
        if exam is None or exam - today != timedelta(days=1):
            continue
        title = session.get("班期名称", "")
        members = [r.get("姓名", "") for r in records or []
                   if r.get("班期") and (r.get("班期") == title
                                         or str(r.get("班期")).find(title) >= 0)]
        if members:
            out.append(f"考试提醒：{title} 明天考试，共 {len(members)} 人"
                       f"（{'、'.join(members[:10])}{'…' if len(members) > 10 else ''}）")
        else:
            out.append(f"考试提醒：{title} 明天考试，暂无关联报名")
    return out


def render_reminders(items: List[str]) -> str:
    if not items:
        return "提醒：今天没有到期的提醒 ✓"
    lines = [f"  ⚠ {line}" for line in items[:12]]
    if len(items) > 12:
        lines.append(f"  …其余 {len(items) - 12} 条见明细")
    return "【提醒】\n" + "\n".join(lines)
