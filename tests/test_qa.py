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


def test_exam_time_answer():
    text = answer("26.6.24期 考试时间", _store())
    assert text and "2026-06-24" in text
    person = answer("李蕾 什么时候考试", _store())
    assert person and "2026-06-24" in person
    # 有批次但未录考试日期 → 明确说明"未录入"，而不是瞎报批次日期
    store = _store()
    store.tables["班期"][0].pop("考试日期", None)
    note = answer("26.6.24期 考试时间", store)
    assert note and "考试日期未录入" in note and "2026-06-24" in note
    # 有记录但缺班期/日期 → 明确说明
    store2 = _store()
    store2.find_record("张莹")["班期"] = ""
    store2.find_record("张莹")["登记日期"] = ""
    note2 = answer("张莹 考试时间", store2)
    assert note2 and "暂无班期/考试日期信息" in note2


def test_invoice_answer():
    store = _store()
    store.tables["开票明细"] = [
        {"姓名": "卜春雷", "企业名称": "技术中心", "公司收费": 449.45},
        {"姓名": "纪荣林", "企业名称": "铸锻", "公司收费": 181.8},
    ]
    text = answer("开票明细多少", store)
    assert "2 条" in text and "631.25" in text
    one = answer("卜春雷 开票明细", store)
    assert "卜春雷" in one and "449.45" in one


def test_month_stats():
    from datetime import date
    store = _store()
    store.records().append({"姓名": "本月新人", "登记日期": date.today().isoformat()})
    text = answer("本月新增报名多少", store)
    assert "本月新增报名 1 人" in text
    pay = answer("本月收款多少", store)
    assert "本月收款 1 笔" in pay and "400" in pay


def test_unknown_returns_none():
    assert answer("今天天气怎么样", _store()) is None
    assert answer("", _store()) is None


if __name__ == "__main__":
    test_debt_answer()
    test_debt_by_session()
    test_count_answer()
    test_payment_answer_today()
    test_status_answer()
    test_exam_time_answer()
    test_invoice_answer()
    test_month_stats()
    test_unknown_returns_none()
    print("ok: test_qa")
