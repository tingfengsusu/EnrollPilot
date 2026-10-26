"""bitable 后端：字段拍平、状态更新+日志、收款流水、幂等查找、时间线排序。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.bitable_store import BitableStore, _plain

TABLES = {"报名记录": "tA", "收款": "tB", "变更日志": "tC", "公司": "tD", "班期": "tE"}
ID_MALE = "410102199001010012"

#: 模拟表结构（字段名白名单）
FIELDS = {
    "tA": ["姓名", "身份证号", "手机号", "缴费状态", "报名状态", "开票状态",
           "登记日期", "登记渠道", "备注"],
    "tB": ["姓名", "金额", "收款方式", "收款人类型", "业务员", "时间"],
    "tC": ["姓名", "时间", "操作人", "变更类型", "字段", "旧值", "新值", "触发来源"],
}


class FakeClient:
    def __init__(self, rows_by_table):
        self.rows = rows_by_table
        self.created = []
        self.updated = []

    def list_records(self, table_id):
        for i, fields in enumerate(self.rows.get(table_id, [])):
            yield {"record_id": f"r{i}", "fields": fields}

    def list_fields(self, table_id):
        return [{"field_name": n} for n in FIELDS.get(table_id, [])]

    def create_record(self, table_id, fields):
        self.created.append((table_id, fields))
        return f"new{len(self.created)}"

    def update_record(self, table_id, record_id, fields):
        self.updated.append((table_id, record_id, fields))


def test_plain_flattens_bitable_shapes():
    assert _plain("李蕾") == "李蕾"
    assert _plain([{"text": "李蕾"}]) == "李蕾"
    assert _plain([{"file_token": "flt1"}]) == "flt1"
    assert _plain([]) == ""
    assert _plain(700) == 700


def _store(extra_tables=None):
    rows = {
        "tA": [{"姓名": "李蕾", "身份证号": ID_MALE, "缴费状态": "已缴费"}],
        "tB": [{"姓名": "李蕾", "金额": 700}],
        "tC": [{"姓名": "李蕾", "时间": "2026-10-26 10:00:00", "字段": "缴费状态",
                "旧值": "未收", "新值": "已缴费"}],
        "tD": [{"公司全名": "某集团（中小拖）", "所属集团": "某集团集团"}],
    }
    return BitableStore(FakeClient(rows), TABLES)


def test_records_keep_record_id():
    store = _store()
    recs = store.records()
    assert recs[0]["_record_id"] == "r0"
    assert recs[0]["缴费状态"] == "已缴费"
    assert store.counts()["报名记录"] == 1 and store.counts()["收款"] == 1


def test_set_status_updates_and_logs():
    store = _store()
    ok, reply = store.set_status("李蕾", "已退", "缴费状态", operator="业务员A")
    assert ok and "已缴费 → 已退" in reply
    client = store.client
    assert client.updated[0][:2] == ("tA", "r0")
    assert client.updated[0][2] == {"缴费状态": "已退"}
    log = client.created[-1]
    assert log[0] == "tC" and log[1]["新值"] == "已退"
    assert log[1]["操作人"] == "业务员A"


def test_add_payment_creates_flow():
    store = _store()
    ok, reply = store.add_payment("李蕾", 700, operator="业务员A")
    assert ok and "入流水" in reply
    client = store.client
    flow = [c for c in client.created if c[0] == "tB"][0]
    assert flow[1]["金额"] == 700 and flow[1]["业务员"] == "业务员A"


def test_find_by_key_and_record():
    store = _store()
    assert store.find_record("李蕾")["身份证号"] == ID_MALE
    assert store.find_by_key(f"id:{ID_MALE}")["_record_id"] == "r0"
    assert store.find_by_key("id:不存在") is None
    assert store.find_by_key("") is None


def test_filter_unknown_fields():
    """表里没有的字段被过滤（实测 1254045 FieldNameNotFound 会炸整条记录）。"""
    store = _store()
    store.create({"姓名": "王五", "住址": "北京市海淀区", "手机号": "18800000000"})
    sent = store.client.created[-1][1]
    assert sent == {"姓名": "王五", "手机号": "18800000000"}


def test_payments_by_record_groups_by_link():
    """收款按关联报名记录 ID 归组（重名场景唯一正确口径）。"""
    store = _store()
    store.client.rows["tB"] = [
        {"姓名": "李蕾", "金额": 700,
         "关联报名记录": [{"record_ids": ["r0"], "table_id": "tA", "type": "text"}]},
        {"姓名": "李蕾", "金额": 300,
         "关联报名记录": [{"record_ids": ["r9"], "table_id": "tA", "type": "text"}]},
    ]
    grouped = store.payments_by_record()
    assert [p["金额"] for p in grouped["r0"]] == [700]
    assert [p["金额"] for p in grouped["r9"]] == [300]


def test_timeline_sorted_desc():
    store = _store()
    store.client.rows["tC"] = [
        {"姓名": "李蕾", "时间": "2026-10-26 10:00:00", "新值": "a"},
        {"姓名": "李蕾", "时间": "2026-10-26 11:00:00", "新值": "b"},
        {"姓名": "张三", "时间": "2026-10-26 09:00:00", "新值": "c"},
    ]
    rows = store.timeline("李蕾")
    assert [r["新值"] for r in rows] == ["b", "a"]


if __name__ == "__main__":
    test_plain_flattens_bitable_shapes()
    test_records_keep_record_id()
    test_set_status_updates_and_logs()
    test_add_payment_creates_flow()
    test_find_by_key_and_record()
    test_filter_unknown_fields()
    test_payments_by_record_groups_by_link()
    test_timeline_sorted_desc()
    print("ok: test_bitable_store")
