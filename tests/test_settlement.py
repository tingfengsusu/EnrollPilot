"""结算核对：拆分等式、超收、退款红灯、汇总口径、日报渲染。

金额结构取自真实样表：缴费 700 = 公司收费 400 + 返还 300。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.settlement import check_record, render_daily, summarize


def _rec(**kw):
    base = {"姓名": "李蕾", "缴费": 700, "公司收费": 400, "返还": 300,
            "报名状态": "已确认", "登记日期": "6月21日"}
    base.update(kw)
    return base


def test_check_record_ok():
    assert check_record(_rec(), [{"金额": 700}]) == []
    assert check_record(_rec(), []) == []          # 没收款不算错，进待收


def test_check_record_issues():
    assert any("拆分不平" in s for s in
               check_record(_rec(返还=350), [{"金额": 700}]))
    assert any("超收" in s for s in
               check_record(_rec(), [{"金额": 700}, {"金额": 500}]))
    assert any("已退" in s for s in
               check_record(_rec(缴费状态="已退"), [{"金额": 700}]))
    assert any("未填缴费" in s for s in
               check_record({"姓名": "李蕾"}, [{"金额": 700}]))


def test_summarize_only_counts_paid():
    records = [_rec(), _rec(姓名="张莹", 登记日期="6月21日")]   # 张莹无流水 → 待收
    flows = {"李蕾": [{"金额": 700}]}
    s = summarize(records, flows)
    assert s["新增人数"] == 2 and s["收款笔数"] == 1
    assert s["总缴费"] == 700
    assert s["总公司收费"] == 400 and s["总返还"] == 300
    assert s["公司应留存"] == 400                   # 实收700 − 返还300
    assert s["待收"] == [("张莹", 700)]
    assert s["差异"] == []


def test_summarize_filters_by_date():
    records = [_rec(), _rec(姓名="张莹", 登记日期="6月22日")]
    s = summarize(records, {"李蕾": [{"金额": 700}]}, date="6月21日")
    assert s["新增人数"] == 1 and s["待收"] == []


def test_price_deviation():
    """统一标准价：公司收费偏离「工种×培训类型」标准价 → 红灯。"""
    std = {("危化经营主要负责人", "新办"): 450.0}
    rec = _rec(工种="危化经营主要负责人", 培训类型="新办")
    assert any("偏离标准价" in s for s in check_record(rec, [], pricing=std))
    ok = _rec(公司收费=450, 返还=250, 工种="危化经营主要负责人", 培训类型="新办")
    assert not any("偏离标准价" in s for s in check_record(ok, [], pricing=std))
    # 没有标准价 / 有标准价但工种对不上 → 不报
    assert not any("偏离标准价" in s for s in check_record(rec, [], pricing=None))


def test_render_daily():
    records = [_rec(), _rec(姓名="张莹")]
    text = render_daily(records, {"李蕾": [{"金额": 700}]}, date="6月21日")
    assert "结算日报 6月21日" in text and "待收：张莹 700元" in text
    assert "公司应留存 400" in text
    bad = _rec(返还=350)
    text2 = render_daily([bad], {"李蕾": [{"金额": 700}]}, date="6月21日")
    assert "拆分不平" in text2 and "⚠" in text2


if __name__ == "__main__":
    test_check_record_ok()
    test_check_record_issues()
    test_summarize_only_counts_paid()
    test_summarize_filters_by_date()
    test_price_deviation()
    test_render_daily()
    print("ok: test_settlement")
