"""开票对账：匹配/缺失/缺价/金额不一致/重名不猜。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.invoice import reconcile, render_reconcile

INV = [
    {"姓名": "卜春雷", "企业名称": "技术中心", "工种": "危险化学品经营单位", "公司收费": 449.45},
    {"姓名": "纪荣林", "企业名称": "铸锻", "工种": "危险化学品经营单位", "公司收费": 449.45},
    {"姓名": "张晓宇", "企业名称": "特专车", "工种": "危险化学品经营单位", "公司收费": 181.8},
    {"姓名": "库里没有", "企业名称": "X", "工种": "叉车", "公司收费": 300},
]
RECORDS = [
    {"姓名": "卜春雷", "工种": "危险化学品经营单位", "公司收费": 449.45},   # 一致
    {"姓名": "纪荣林", "工种": "危险化学品经营单位", "公司收费": None},       # 记录缺价格
    {"姓名": "张晓宇", "工种": "危险化学品经营单位", "公司收费": 200},        # 金额不一致
]


def test_reconcile():
    r = reconcile(INV, RECORDS)
    assert r["明细条数"] == 4 and r["开票金额"] == 1380.7
    assert len(r["已匹配"]) == 3
    assert [x["姓名"] for x in r["名单缺失"]] == ["库里没有"]
    assert [i["姓名"] for i, _ in r["记录缺价格"]] == ["纪荣林"]
    assert [i["姓名"] for i, _ in r["金额不一致"]] == ["张晓宇"]


def test_ambiguous_not_guessed():
    inv = [{"姓名": "李蕾", "工种": "新办", "公司收费": 100}]
    recs = [{"姓名": "李蕾", "工种": "新办", "公司收费": 100},
            {"姓名": "李蕾", "工种": "新办", "公司收费": 100}]
    r = reconcile(inv, recs)
    assert len(r["重名待确认"]) == 1 and not r["已匹配"]


def test_render():
    text = render_reconcile(reconcile(INV, RECORDS))
    assert "开票对账" in text and "名单缺失 1 条" in text
    assert "记录未填价格 1 条" in text and "金额不一致 1 条" in text


if __name__ == "__main__":
    test_reconcile()
    test_ambiguous_not_guessed()
    test_render()
    print("ok: test_invoice")
