"""文本抽取：微信交错文本、标签值形式、交叉核对只报警不猜。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.extract import parse_id_text, looks_like_id_text

#: 合成证件号（结构合法，非真人）：1990-01-01 生，男
ID_MALE = "410102199001010012"
#: 合成证件号：1990-01-01 生，女
ID_FEMALE = "410102199001010004"

#: 模拟微信「复制图片内容」的真实交错形态（字段行在前、值乱序、民族插行、住址粘邮编）
WECHAT_TEXT = (
    "姓名\n性别\n出生\n住址\n测试员\n男\n1990\n民族汉\n年1月1日\n"
    "北京市海淀区清华园1号100084\n公民身份号码\n" + ID_MALE
)


def test_wechat_interleaved_text():
    r = parse_id_text(WECHAT_TEXT)
    assert r.fields["姓名"] == "测试员"
    assert r.fields["性别"] == "男"
    assert r.fields["民族"] == "汉"
    assert r.fields["出生日期"] == "1990-01-01"
    assert r.fields["身份证号"] == ID_MALE
    assert "清华园" in r.fields["住址"]
    assert any("邮编" in w for w in r.warnings)      # 末尾 6 位数字只提醒不猜
    # 交叉核对全部一致 → 不应有出生/性别/校验位告警
    assert not any("不一致" in w or "校验不过" in w for w in r.warnings)


def test_label_colon_form_clean():
    text = ("姓名：测试员\n性别：男\n民族：汉\n出生：1990年1月1日\n"
            "住址：北京市海淀区清华园1号\n公民身份号码：" + ID_MALE)
    r = parse_id_text(text)
    assert r.fields == {"姓名": "测试员", "性别": "男", "民族": "汉",
                        "出生日期": "1990-01-01", "住址": "北京市海淀区清华园1号",
                        "身份证号": ID_MALE}
    assert r.warnings == []


def test_cross_check_reports_only():
    text = f"姓名：测试员\n性别：男\n出生：1991年1月1日\n公民身份号码：{ID_MALE}"
    r = parse_id_text(text)
    assert any("出生日期文本(1991-01-01)" in w for w in r.warnings)

    text2 = f"姓名：测试员\n性别：男\n公民身份号码：{ID_FEMALE}"
    r2 = parse_id_text(text2)
    assert any("性别文本(男)与身份证号内嵌(女)不一致" in w for w in r2.warnings)

    r3 = parse_id_text(f"姓名：测试员\n公民身份号码：410102199001010013")
    assert any("校验不过" in w for w in r3.warnings)   # 改动末位 → 校验位错


def test_missing_fields_warn():
    r = parse_id_text("姓名：李四")
    assert any("未识别出" in w for w in r.warnings)
    assert r.fields["姓名"] == "李四"


def test_looks_like_id_text():
    assert looks_like_id_text(WECHAT_TEXT)
    assert looks_like_id_text("身份证号：410102199001010012")
    assert not looks_like_id_text("状态")
    assert not looks_like_id_text("张莹 已缴费 700")


if __name__ == "__main__":
    test_wechat_interleaved_text()
    test_label_colon_form_clean()
    test_cross_check_reports_only()
    test_missing_fields_warn()
    test_looks_like_id_text()
    print("ok: test_extract")
