"""指令执行闭环（DemoStore + service）：状态/日志/流水/结算/落盘重载。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.demo_store import DemoStore
from enroll.instructions import parse
from enroll.service import execute


def _store() -> DemoStore:
    return DemoStore().seed()


def test_status_and_counts():
    reply = execute(_store(), parse("状态"))
    assert "报名记录 2" in reply and "收款 1" in reply and "公司 2" in reply


def test_set_status_with_payment_flow():
    store = _store()
    reply = execute(store, parse("张莹 已缴费 700"), operator="业务员A")
    assert "未收 → 已缴费" in reply and "700" in reply
    assert store.find_record("张莹")["缴费状态"] == "已缴费"
    assert len(store.payments_by_key()["张莹"]) == 1
    log = store.timeline("张莹")[0]
    assert log["操作人"] == "业务员A" and log["触发来源"].startswith("群指令")
    assert log["旧值"] == "未收" and log["新值"] == "已缴费"


def test_status_change_only():
    store = _store()
    reply = execute(store, parse("李蕾 已退"), operator="业务员A")
    assert "已缴费 → 已退" in reply
    # 已退不自动动流水——结算红灯会指出「已退但存在正向收款」
    assert len(store.payments_by_key()["李蕾"]) == 1


def test_timeline_query_settle():
    store = _store()
    execute(store, parse("张莹 已缴费 700"), operator="业务员A")
    execute(store, parse("李蕾 已退"), operator="业务员A")
    assert "变更时间线" in execute(store, parse("记录 张莹"))
    assert "某集团" in execute(store, parse("查 某集团"))
    daily = execute(store, parse("结算"))
    assert "结算日报 今天" in daily
    assert "已退但存在正向收款" in daily          # 李蕾 的红灯
    assert "待收" not in daily                    # 张莹 已缴，无待收


def test_export_and_unknown():
    store = _store()
    assert "M4" in execute(store, parse("导出 名单 某集团"))
    assert parse("随便聊聊") is None


def test_not_found_is_honest():
    store = _store()
    reply = execute(store, parse("赵六 已缴费 100"), operator="业务员A")
    assert "没有找到" in reply


def test_store_roundtrip():
    tmp = os.path.join(tempfile.mkdtemp(), "demo.json")
    store = DemoStore(tmp).seed()
    execute(store, parse("张莹 已缴费 700"), operator="业务员A")
    store.save()
    reloaded = DemoStore(tmp)
    assert len(reloaded.records()) == 2
    assert reloaded.find_record("张莹")["缴费状态"] == "已缴费"
    assert len(reloaded.timeline("张莹")) == 1


def test_duplicate_name_requires_qualifier():
    """真实数据里有重名：不加限定词不猜，加尾号/日期才更新。"""
    store = _store()
    store.records().append({           # 第二个李蕾（不同尾号/日期）
        "姓名": "李蕾", "身份证号": "410102199001010012", "登记日期": "6月22日",
        "报名状态": "已确认", "缴费状态": "未收", "开票状态": "未开"})
    reply = execute(store, parse("李蕾 已开票"), operator="测试")
    assert "2 条记录" in reply and "0004" in reply and "0012" in reply

    reply2 = execute(store, parse("李蕾 0012 已开票"), operator="测试")
    assert "未开 → 已开票" in reply2
    second = [r for r in store.records()
              if r.get("身份证号", "").endswith("0012")][0]
    first = [r for r in store.records()
             if r.get("身份证号", "").endswith("0004")][0]
    assert second["开票状态"] == "已开票"
    assert first["开票状态"] == "已开"          # 原记录未被误改

    # 用登记日期限定同样能定位
    execute(store, parse("李蕾 6.22 已确认"), operator="测试")
    assert second["报名状态"] == "已确认"


if __name__ == "__main__":
    test_status_and_counts()
    test_set_status_with_payment_flow()
    test_status_change_only()
    test_timeline_query_settle()
    test_export_and_unknown()
    test_not_found_is_honest()
    test_store_roundtrip()
    test_duplicate_name_requires_qualifier()
    print("ok: test_service")
