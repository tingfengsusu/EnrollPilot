"""规则问答：欠款/人数/收款/状态，未命中返回 None 不硬答。"""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.demo_store import DemoStore
from enroll.qa import answer

TODAY = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _store():
    store = DemoStore().seed()
    # 李蕾：缴费700、已收700；张莹：缴费700、已收400（部分）
    store.tables["收款"].append({"姓名": "张莹", "金额": 400, "时间": TODAY})
    return store


def test_debt_answer():
    text = answer("某集团集团还欠多少", _store())
    assert "待收" in text and "300" in text          # 张莹还欠 300
    assert "张莹" in text


def test_debt_by_session():
    assert answer("还欠多少", _store()) is not None


def test_count_answer():
    text = answer("某集团集团名单", _store())
    assert "2 人" in text and "李蕾" in text


def test_payment_answer_today():
    text = answer("今天收款多少", _store())
    assert "1 笔" in text and "400" in text


def test_status_answer():
    text = answer("李蕾什么状态", _store())
    assert "缴费" in text and "实收" in text


def test_unknown_returns_none():
    assert answer("今天天气怎么样", _store()) is None
    assert answer("", _store()) is None


if __name__ == "__main__":
    test_debt_answer()
    test_debt_by_session()
    test_count_answer()
    test_payment_answer_today()
    test_status_answer()
    test_unknown_returns_none()
    print("ok: test_qa")
