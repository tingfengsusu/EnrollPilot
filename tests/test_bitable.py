"""bitable 客户端：token 缓存、请求拼装、翻页、错误码、附件上传（假 Session，离线）。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from enroll.bitable import BitableClient, BitableError

APP = {"app_id": "cli_test", "app_secret": "sec", "app_token": "bascnXXX"}


class FakeResp:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class FakeSession:
    """按脚本顺序返回响应；记录全部调用供断言。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _do(self, method, url, **kw):
        self.calls.append((method, url, kw))
        payload, status = self.responses.pop(0)
        return FakeResp(payload, status)

    def post(self, url, **kw):
        return self._do("POST", url, **kw)

    def get(self, url, **kw):
        return self._do("GET", url, **kw)

    def put(self, url, **kw):
        return self._do("PUT", url, **kw)


def _client(session):
    return BitableClient(session=session, base_url="https://fake", **APP)


def _token_ok():
    return ({"tenant_access_token": "t-1", "expire": 7200}, 200)


def test_token_cached():
    s = FakeSession([_token_ok()])
    c = _client(s)
    assert c.get_token() == "t-1"
    assert c.get_token() == "t-1"          # 第二次命中缓存
    assert len([x for x in s.calls if "/auth/" in x[1]]) == 1


def test_create_record_payload():
    s = FakeSession([_token_ok(),
                     ({"data": {"record": {"record_id": "rec123"}}}, 200)])
    rid = _client(s).create_record("tbl1", {"姓名": "李蕾"})
    assert rid == "rec123"
    method, url, kw = s.calls[-1]
    assert method == "POST" and url.endswith("/tables/tbl1/records")
    assert kw["json"] == {"fields": {"姓名": "李蕾"}}
    assert kw["headers"]["Authorization"] == "Bearer t-1"


def test_update_record_uses_put():
    s = FakeSession([_token_ok(), ({"data": {}}, 200)])
    _client(s).update_record("tbl1", "rec9", {"缴费状态": "已缴费"})
    method, url, kw = s.calls[-1]
    assert method == "PUT" and url.endswith("/records/rec9")
    assert kw["json"] == {"fields": {"缴费状态": "已缴费"}}


def test_list_records_pagination():
    page1 = ({"data": {"has_more": True, "page_token": "pt2",
                       "items": [{"record_id": "r1", "fields": {"姓名": "李蕾"}}]}}, 200)
    page2 = ({"data": {"has_more": False,
                       "items": [{"record_id": "r2", "fields": {"姓名": "张莹"}}]}}, 200)
    s = FakeSession([_token_ok(), page1, page2])
    rows = list(_client(s).list_records("tbl1"))
    assert [r["record_id"] for r in rows] == ["r1", "r2"]
    assert s.calls[2][2]["params"]["page_token"] == "pt2"


def test_error_raises():
    s = FakeSession([_token_ok(), ({"code": 1254302, "msg": "Permission denied"}, 200)])
    with pytest.raises(BitableError):
        list(_client(s).list_records("tbl1"))


def test_upload_media_and_attach():
    s = FakeSession([_token_ok(), ({"data": {"file_token": "fltX"}}, 200),
                     ({"data": {}}, 200)])
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.write(b"\xff\xd8jpeg")
    tmp.close()
    try:
        c = _client(s)
        token = c.upload_media(tmp.name)
        assert token == "fltX"
        method, url, kw = s.calls[1]
        assert "/drive/v1/medias/upload_all" in url
        assert kw["data"]["parent_type"] == "bitable_image"
        c.write_attachment("tbl1", "rec1", "身份证正", token)
        method, url, kw = s.calls[2]
        assert method == "PUT"
        assert kw["json"] == {"fields": {"身份证正": [{"file_token": "fltX"}]}}
    finally:
        os.unlink(tmp.name)


def test_batch_create_chunks():
    s = FakeSession([_token_ok()] + [({"data": {"records": []}}, 200)] * 3)
    n = _client(s).batch_create("tbl1", [{"姓名": f"u{i}"} for i in range(1001)])
    assert n == 1001
    posts = [x for x in s.calls if "batch_create" in x[1]]
    assert len(posts) == 3            # 500 + 500 + 1


if __name__ == "__main__":
    test_token_cached()
    test_create_record_payload()
    test_update_record_uses_put()
    test_list_records_pagination()
    test_error_raises()
    test_upload_media_and_attach()
    test_batch_create_chunks()
    print("ok: test_bitable")
