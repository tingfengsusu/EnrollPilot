"""登记入库：幂等合并、变更日志、存疑透传、无法建键的诚实回退。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.demo_store import DemoStore
from enroll.intake import intake_text

ID_MALE = "410102199001010012"
TEXT_FULL = ("姓名：测试员\n性别：男\n民族：汉\n出生：1990年1月1日\n"
             "住址：北京市海淀区清华园1号\n公民身份号码：" + ID_MALE)
TEXT_SPARSE = ("姓名：测试员\n性别：男\n出生：1990年1月1日\n"
               "公民身份号码：" + ID_MALE)          # 少了民族和住址


def test_new_record():
    store = DemoStore().seed()
    reply = intake_text(store, TEXT_FULL, operator="前台", source="剪贴板")
    assert "已登记" in reply and "待确认" in reply
    rec = store.find_record("测试员")
    assert rec["身份证号"] == ID_MALE and rec["登记渠道"] == "剪贴板"
    assert rec["报名状态"] == "待确认" and rec["缴费状态"] == "未收"
    assert store.timeline("测试员")[0]["变更类型"] == "新增"


def test_idempotent_second_pass():
    store = DemoStore().seed()
    intake_text(store, TEXT_FULL)
    reply = intake_text(store, TEXT_FULL, operator="前台")
    assert "无新增信息" in reply
    assert len(store.records()) == 3               # 种子 2 条 + 首次登记 1 条，未再增


def test_merge_fills_empty_only():
    store = DemoStore().seed()
    intake_text(store, TEXT_SPARSE)
    reply = intake_text(store, TEXT_FULL, operator="前台")
    assert "补全 2 项" in reply and "民族" in reply and "住址" in reply
    rec = store.find_record("测试员")
    assert rec["民族"] == "汉" and rec["性别"] == "男"     # 已有值不被覆盖
    assert store.timeline("测试员")[0]["变更类型"] == "字段补全"


def test_warnings_pass_through():
    store = DemoStore().seed()
    bad = f"姓名：测试员\n出生：1991年1月1日\n公民身份号码：{ID_MALE}"
    reply = intake_text(store, bad)
    assert "存疑" in reply and "不一致" in reply
    assert "测试员" in reply                        # 登记照做，疑点不吞


def test_unparseable_and_no_key():
    store = DemoStore().seed()
    assert "没有识别出" in intake_text(store, "今天天气不错")
    assert "幂等键" in intake_text(store, "姓名：李四")   # 只有姓名，无法建键


if __name__ == "__main__":
    test_new_record()
    test_idempotent_second_pass()
    test_merge_fills_empty_only()
    test_warnings_pass_through()
    test_unparseable_and_no_key()
    print("ok: test_intake")
