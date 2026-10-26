"""班期提醒：缴费逾期、开班前一天、日期格式双兼容。"""
from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.reminders import due_reminders, render_reminders, to_date


def test_to_date_formats():
    assert to_date("2026-06-24") == date(2026, 6, 24)
    assert to_date("2026-06-24 10:30:00") == date(2026, 6, 24)
    assert to_date(1792977959000) is not None      # 毫秒时间戳
    assert to_date("") is None and to_date(None) is None


def test_unpaid_reminder():
    today = date(2026, 7, 1)
    records = [
        {"姓名": "李蕾", "缴费状态": "未收", "登记日期": "2026-06-27", "缴费": 700},
        {"姓名": "张莹", "缴费状态": "已缴费", "登记日期": "2026-06-01", "缴费": 700},
        {"姓名": "王五", "缴费状态": "部分收款", "登记日期": "2026-06-28", "缴费": 700},
    ]
    items = due_reminders(records, [], today, unpaid_days=3)
    assert any("李蕾" in i and "4 天" in i for i in items)
    assert not any("张莹" in i for i in items)     # 已缴不提醒
    assert any("王五" in i and "3 天" in i for i in items)   # 达到阈值 3 天


def test_session_reminder_one_day_before():
    today = date(2026, 7, 1)
    sessions = [{"班期名称": "26.7.2 期", "起始日期": "2026-07-02"},
                {"班期名称": "26.8.1 期", "起始日期": "2026-08-01"}]
    records = [{"姓名": "李蕾", "班期": "26.7.2 期"},
               {"姓名": "张莹", "班期": "26.7.2 期"}]
    items = due_reminders(records, sessions, today)
    assert any("26.7.2 期" in i and "2 人" in i for i in items)
    assert not any("26.8.1 期" in i for i in items)


def test_render():
    assert "没有到期" in render_reminders([])
    assert "⚠" in render_reminders(["缴费提醒：李蕾"])


if __name__ == "__main__":
    test_to_date_formats()
    test_unpaid_reminder()
    test_session_reminder_one_day_before()
    test_render()
    print("ok: test_reminders")
