"""飞书多维表格客户端（bitable REST 薄封装）。

只用得到记录查询/增改、附件上传、tenant_access_token 几个端点，所以用
``requests`` 直接打官方 REST 而不走 SDK 的 bitable 封装——薄、可测
（测试注入假 Session）、不随 SDK 版本漂移。事件侧长连接仍由 ``gateway/feishu.py``
走 ``lark-oapi``，两栈各管各的。

鉴权：企业自建应用 ``tenant_access_token``，缓存到过期前 300 秒。
``app_token`` 是多维表格网址里 ``base/`` 后面那一串。

测试可注入 ``session``（duck-type requests.Session），见 tests/test_bitable.py。
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterator, List, Optional

import requests

_BASE = "https://open.feishu.cn/open-apis"
#: batch_create 单批上限（官方允许 1000，留余量）
_BATCH_SIZE = 500


class BitableError(RuntimeError):
    """飞书返回非 0 code 或 HTTP 非 200。"""


def _unwrap(resp: requests.Response) -> Dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError as exc:
        raise BitableError(f"非 JSON 响应 HTTP {resp.status_code}") from exc
    if resp.status_code != 200 or payload.get("code") not in (0, None):
        raise BitableError(f"HTTP {resp.status_code} code={payload.get('code')} "
                           f"msg={payload.get('msg')}")
    return payload


class BitableClient:
    """一个 client 绑定一张多维表格（app_token），表级操作再传 table_id。"""

    def __init__(self, app_id: str, app_secret: str, app_token: str,
                 session: Optional[requests.Session] = None,
                 base_url: str = _BASE):
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_token = app_token
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self._token = ""
        self._token_expire_at = 0.0

    # ------------------------------------------------------------------
    # 鉴权
    # ------------------------------------------------------------------
    def get_token(self) -> str:
        if self._token and time.time() < self._token_expire_at:
            return self._token
        payload = _unwrap(self.session.post(
            f"{self.base_url}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret}))
        token = payload.get("tenant_access_token", "")
        expire = int(payload.get("expire", 0))
        if not token:
            raise BitableError(f"拿不到 tenant_access_token：{payload.get('msg')}")
        self._token = token
        self._token_expire_at = time.time() + max(expire - 300, 60)
        return token

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.get_token()}",
                "Content-Type": "application/json; charset=utf-8"}

    def _records_url(self, table_id: str, suffix: str = "") -> str:
        return (f"{self.base_url}/bitable/v1/apps/{self.app_token}"
                f"/tables/{table_id}/records{suffix}")

    # ------------------------------------------------------------------
    # 记录
    # ------------------------------------------------------------------
    def list_records(self, table_id: str, filter: Optional[Dict] = None
                     ) -> Iterator[Dict]:
        """拉全部记录（自动翻页）。每条 yield {record_id, fields}。

        ``filter`` 为官方 search 条件（{"conjunction":"and","conditions":[...]}），
        走 POST records/search；不传则走 GET records 列表端点。
        """
        page_token = ""
        while True:
            if filter is None:
                params: Dict[str, Any] = {"page_size": _BATCH_SIZE}
                if page_token:
                    params["page_token"] = page_token
                payload = _unwrap(self.session.get(
                    self._records_url(table_id), headers=self._headers(),
                    params=params))
            else:
                body: Dict[str, Any] = {"filter": filter, "page_size": _BATCH_SIZE}
                if page_token:
                    body["page_token"] = page_token
                payload = _unwrap(self.session.post(
                    self._records_url(table_id, "/search"),
                    headers=self._headers(), json=body))
            data = payload.get("data", {})
            for item in data.get("items") or []:
                yield {"record_id": item.get("record_id"),
                       "fields": item.get("fields") or {}}
            if not data.get("has_more"):
                return
            page_token = data.get("page_token", "")

    def create_record(self, table_id: str, fields: Dict) -> str:
        """新建记录，返回 record_id。"""
        payload = _unwrap(self.session.post(
            self._records_url(table_id), headers=self._headers(),
            json={"fields": fields}))
        return payload["data"]["record"]["record_id"]

    def update_record(self, table_id: str, record_id: str, fields: Dict) -> None:
        _unwrap(self.session.put(
            self._records_url(table_id, f"/{record_id}"),
            headers=self._headers(), json={"fields": fields}))

    def batch_create(self, table_id: str, records: List[Dict]) -> int:
        """批量新建（自动分批），返回总条数。"""
        done = 0
        for i in range(0, len(records), _BATCH_SIZE):
            chunk = records[i:i + _BATCH_SIZE]
            _unwrap(self.session.post(
                self._records_url(table_id, "/batch_create"),
                headers=self._headers(), json={"records": chunk}))
            done += len(chunk)
        return done

    # ------------------------------------------------------------------
    # 附件（替代旧表 DISPIMG 内嵌：身份证正/一寸照/缴费凭证全部走这里）
    # ------------------------------------------------------------------
    def upload_media(self, file_path: str,
                     parent_type: str = "bitable_image") -> str:
        """上传附件，返回 file_token（再写入附件字段）。图片用默认类型，文件传
        ``bitable_file``。"""
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        with open(file_path, "rb") as fh:   # 用完即关，Windows 下不锁文件
            payload = _unwrap(self.session.post(
                f"{self.base_url}/drive/v1/medias/upload_all",
                headers={"Authorization": f"Bearer {self.get_token()}"},
                data={"file_name": file_name, "parent_type": parent_type,
                      "size": file_size, "parent_node": self.app_token},
                files={"file": (file_name, fh)}))
        token = payload.get("data", {}).get("file_token", "")
        if not token:
            raise BitableError(f"上传成功但拿不到 file_token：{payload}")
        return token

    def write_attachment(self, table_id: str, record_id: str, field: str,
                         file_token: str) -> None:
        """把上传好的附件挂到记录的附件字段上。"""
        self.update_record(table_id, record_id,
                           {field: [{"file_token": file_token}]})
