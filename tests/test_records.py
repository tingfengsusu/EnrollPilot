"""报名记录：归一化、幂等键、只补空合并、状态字段保护、校验。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.records import (HUMAN_ONLY_FIELDS, id_key, merge_into,
                            normalize_record, validate)


def test_normalize():
    rec = normalize_record({"姓名": " 李蕾 ", "身份证号": " 41120219911011502x ",
                            "手机号": "188-0000 0000"})
    assert rec["姓名"] == "李蕾"
    assert rec["身份证号"].endswith("X") and len(rec["身份证号"]) == 18
    assert rec["手机号"] == "18800000000"
    assert normalize_record({"身份证号": None}) == {}


def test_id_key():
    assert id_key({"身份证号": "410102199001010004"}) == "id:410102199001010004"
    assert id_key({"姓名": "李蕾", "手机号": "18800000000"}) == "np:李蕾|18800000000"
    assert id_key({"姓名": "李蕾"}) is None            # 只有姓名，无法建键
    assert id_key({}) is None


def test_merge_only_fills_empty_and_protects_status():
    existing = {"姓名": "李蕾", "工种": "危化经营主要负责人", "缴费状态": "已缴费"}
    incoming = {"工种": "叉车", "身份证号": "410102199001010004",
                "缴费状态": "已退", "报名状态": "已参加"}   # 状态字段必须被无视
    merged, changed = merge_into(existing, incoming)
    assert merged["工种"] == "危化经营主要负责人"      # 已有值不被覆盖
    assert merged["身份证号"] == "410102199001010004"  # 空值被补上
    for f in HUMAN_ONLY_FIELDS:
        assert f not in changed and merged.get(f) == existing.get(f)
    assert set(changed) == {"身份证号"}


def test_validate():
    good = {"姓名": "李蕾", "身份证号": "410102199001010004", "手机号": "18800000000"}
    assert validate(good) == []
    assert any("身份证" in s for s in validate({"姓名": "李蕾", "身份证号": "410102199001010005"}))
    assert any("幂等键" in s for s in validate({"姓名": "李蕾"}))
    assert any("手机号" in s for s in validate({"姓名": "李蕾", "手机号": "12345"}))


if __name__ == "__main__":
    test_normalize()
    test_id_key()
    test_merge_only_fills_empty_and_protects_status()
    test_validate()
    print("ok: test_records")
