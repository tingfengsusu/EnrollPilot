"""指令解析：白名单动词、金额参数、未知不猜。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.instructions import USAGE, parse


def test_set_status_with_qualifier():
    """重名限定词：身份证后4位或登记日期（6.23 / 6.23期）。"""
    cmd = parse("朱军亮 6417 已缴费 700")
    assert (cmd.name, cmd.qual, cmd.verb, cmd.amount) == ("朱军亮", "6417", "已缴费", 700.0)
    assert parse("朱军亮 6.23 已开票").qual == "6.23"
    assert parse("朱军亮 6.23期 已开票").qual == "6.23"
    assert parse("朱军亮已开票").qual == ""          # 不带限定词仍可用


def test_simple_commands():
    assert parse("状态").action == "status"
    cmd = parse("结算 6.24")
    assert cmd.action == "settle" and cmd.date == "6.24"
    assert parse("结算").action == "settle" and parse("结算").date == ""
    assert parse("记录 张莹").action == "records" and parse("记录 张莹").name == "张莹"
    assert parse("查 某集团").action == "query" and parse("查 某集团").keyword == "某集团"
    assert parse("导出 名单 某集团").action == "export"
    assert parse("导出 名单 某集团").keyword == "名单 某集团"


def test_set_status():
    cmd = parse("张莹 已缴费 700")
    assert (cmd.action, cmd.name, cmd.verb, cmd.field) == \
        ("set_status", "张莹", "已缴费", "缴费状态")
    assert cmd.amount == 700.0
    assert parse("李蕾 已确认").field == "报名状态"
    assert parse("王五 未参加").field == "报名状态"
    assert parse("李蕾 已开票").field == "开票状态"
    assert parse("李蕾 已退").verb == "已退"
    # 不带金额的已缴费也允许（金额后补）
    assert parse("李蕾 已缴费").amount is None


def test_sales_command():
    assert parse("业务员账").action == "sales"
    assert parse("业务员对账").action == "sales"


def test_unknown_returns_none():
    assert parse("") is None
    assert parse(None) is None
    assert parse("随便聊聊") is None
    assert parse("已缴费") is None            # 缺姓名，不猜
    assert parse("记录") is None              # 缺姓名，不猜
    assert parse("查") is None
    assert parse("张三 已涨价") is None        # 白名单外动词
    assert USAGE and "已缴费" in USAGE        # 用法提示存在


def test_two_char_and_four_char_names():
    assert parse("李蕾 已缴费").name == "李蕾"
    assert parse("欧阳文雪 已缴费").name == "欧阳文雪"


if __name__ == "__main__":
    test_simple_commands()
    test_set_status()
    test_set_status_with_qualifier()
    test_sales_command()
    test_unknown_returns_none()
    test_two_char_and_four_char_names()
    print("ok: test_instructions")
