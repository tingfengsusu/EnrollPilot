"""证书规则（纯逻辑）：复审到期日期的推算。

安全培训证书按复审周期滚动（默认 3 年，可在 config 里改）。已有
「复审到期日期」的以表内为准；缺失时按 参加/考试日期 + 周期 推算。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from enroll.reminders import to_date

DEFAULT_REVIEW_YEARS = 3


def review_due(attend, years: int = DEFAULT_REVIEW_YEARS,
               existing=None) -> Optional[date]:
    """复审到期日：已有值优先；否则 参加日期 + years 年（2 月 29 日回退到 28 日）。"""
    current = to_date(existing)
    if current is not None:
        return current
    start = to_date(attend)
    if start is None:
        return None
    try:
        return start.replace(year=start.year + years)
    except ValueError:              # 2 月 29 日遇到平年
        return start.replace(year=start.year + years, day=28)
