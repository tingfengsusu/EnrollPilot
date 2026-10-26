"""腾讯云 OCR：签名头、字段转文本、错误处理（假 Session，离线）。"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from enroll.ocr import (build_headers, idcard_fields_to_text, make_ocr,
                        recognize_idcard)

FIELDS = {"Name": "测试人", "Sex": "女", "Birth": "1992-01-18",
          "Address": "北京市海淀区测试路1号",
          "IdNum": "110101199201180019"}


class FakeResp:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.response


def test_build_headers_signing():
    h = build_headers("AKIDTEST", "KEYTEST", '{"ImageBase64":"x"}',
                      "ap-guangzhou", timestamp=1700000000)
    assert h["X-TC-Action"] == "IDCardOCR"
    assert h["X-TC-Version"] == "2018-11-19"
    assert h["X-TC-Timestamp"] == "1700000000"
    assert h["Authorization"].startswith("TC3-HMAC-SHA256 Credential=AKIDTEST/2023-11-14/ocr/tc3_request")
    assert "SignedHeaders=content-type;host" in h["Authorization"]
    assert "Signature=" in h["Authorization"]


def test_fields_to_text():
    text = idcard_fields_to_text(FIELDS)
    assert "姓名：测试人" in text and "公民身份号码：110101199201180019" in text
    # 抽取管道能消费这段文本
    from enroll.extract import parse_id_text
    r = parse_id_text(text)
    assert r.fields["姓名"] == "测试人" and r.fields["出生日期"] == "1992-01-18"


def test_slash_birth_from_tencent():
    """腾讯云实测返回 1992/1/18（斜杠格式），必须能解析。"""
    text = ("姓名：测试人\n性别：女\n出生：1992/1/18\n"
            "住址：北京市海淀区测试路1号\n公民身份号码：110101199201180019")
    from enroll.extract import parse_id_text
    r = parse_id_text(text)
    assert r.fields["出生日期"] == "1992-01-18"
    assert r.fields["姓名"] == "测试人"


def test_recognize_success():
    session = FakeSession(FakeResp({"Response": dict(FIELDS)}))
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ocr.jpg")
    with open(tmp, "wb") as f:
        f.write(b"\xff\xd8jpeg")
    try:
        text = recognize_idcard(tmp, "id", "key", session=session)
        assert "测试人" in text
        url, kw = session.calls[0]
        assert url == "https://ocr.tencentcloudapi.com"
        body = json.loads(kw["data"])
        assert "ImageBase64" in body
    finally:
        os.unlink(tmp)


def test_recognize_errors():
    session = FakeSession(FakeResp({"Response": {"Error": {"Code": "AuthFailure", "Message": "bad key"}}}))
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ocr2.jpg")
    with open(tmp, "wb") as f:
        f.write(b"x")
    try:
        with pytest.raises(RuntimeError):
            recognize_idcard(tmp, "id", "wrong", session=session)
    finally:
        os.unlink(tmp)
    with pytest.raises(RuntimeError):
        recognize_idcard(tmp, "", "", session=session)


def test_make_ocr_config_gate():
    assert make_ocr({}) is None
    assert make_ocr({"ocr": {"provider": "none"}}) is None
    assert make_ocr({"ocr": {"provider": "tencent"}}) is None       # 缺密钥
    fn = make_ocr({"ocr": {"provider": "tencent", "secret_id": "i", "secret_key": "k"}})
    assert callable(fn)


if __name__ == "__main__":
    test_build_headers_signing()
    test_fields_to_text()
    test_slash_birth_from_tencent()
    test_recognize_success()
    test_recognize_errors()
    test_make_ocr_config_gate()
    print("ok: test_ocr")
