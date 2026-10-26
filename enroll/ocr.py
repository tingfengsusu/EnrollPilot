"""腾讯云身份证 OCR（自包含实现，无 tencentcloud SDK 依赖）。

用官方 TC3-HMAC-SHA256 签名直接调 ``ocr.tencentcloudapi.com``，返回文本时
拼成抽取管道认识的「标签：值」多行格式——图片模式与文本模式走同一条解析链路。

凭证放 ``config/enroll.yaml`` 的 ``ocr`` 段；未配置时 :func:`make_ocr` 返回 None，
runner 会提示"复制图片内容"的人肉兜底。

测试注入 ``session``（duck-type requests.Session），见 tests/test_ocr.py。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

_HOST = "ocr.tencentcloudapi.com"
_SERVICE = "ocr"
_ACTION = "IDCardOCR"
_VERSION = "2018-11-19"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def build_headers(secret_id: str, secret_key: str, payload: str,
                  region: str, timestamp: Optional[int] = None) -> Dict[str, str]:
    """构造 TC3-HMAC-SHA256 请求头（纯函数，便于测试）。"""
    ts = timestamp or int(time.time())
    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    content_type = "application/json; charset=utf-8"

    canonical_request = "\n".join([
        "POST", "/", "",
        f"content-type:{content_type}",
        f"host:{_HOST}",
        "", "content-type;host", _sha256_hex(payload.encode("utf-8"))])

    scope = f"{date}/{_SERVICE}/tc3_request"
    string_to_sign = "\n".join([
        "TC3-HMAC-SHA256", str(ts), scope,
        _sha256_hex(canonical_request.encode("utf-8"))])

    secret_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac(secret_date, _SERVICE)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()

    return {
        "Authorization": (f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, "
                          f"SignedHeaders=content-type;host, Signature={signature}"),
        "Content-Type": content_type,
        "Host": _HOST,
        "X-TC-Action": _ACTION,
        "X-TC-Version": _VERSION,
        "X-TC-Timestamp": str(ts),
        "X-TC-Region": region,
    }


def idcard_fields_to_text(fields: Dict[str, Any]) -> str:
    """腾讯云返回字段 → 「标签：值」文本（抽取管道可解析的格式）。"""
    lines = []
    for label, key in (("姓名", "Name"), ("性别", "Sex"), ("出生", "Birth"),
                       ("住址", "Address"), ("公民身份号码", "IdNum")):
        value = str(fields.get(key) or "").strip()
        if value:
            lines.append(f"{label}：{value}")
    return "\n".join(lines)


def recognize_idcard(image_path: str, secret_id: str, secret_key: str,
                     region: str = "ap-guangzhou",
                     session: Optional[requests.Session] = None) -> str:
    """识别身份证图片，返回「标签：值」多行文本。失败抛 RuntimeError。"""
    if not secret_id or not secret_key:
        raise RuntimeError("未配置腾讯云 OCR 密钥（config/enroll.yaml → ocr）")
    with open(image_path, "rb") as fh:
        image_b64 = base64.b64encode(fh.read()).decode("ascii")
    payload = json.dumps({"ImageBase64": image_b64})
    headers = build_headers(secret_id, secret_key, payload, region)
    resp = (session or requests).post(f"https://{_HOST}", headers=headers,
                                      data=payload, timeout=20)
    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"OCR 返回非 JSON（HTTP {resp.status_code}）") from exc
    response = body.get("Response") or {}
    if response.get("Error"):
        err = response["Error"]
        raise RuntimeError(f"OCR 失败：{err.get('Code')} {err.get('Message')}")
    text = idcard_fields_to_text(response)
    if not text:
        raise RuntimeError("OCR 成功但未识别出字段")
    return text


def make_ocr(cfg: Dict[str, Any]):
    """按配置构造 runner 需要的 ocr 回调；未配置返回 None。"""
    ocr_cfg = (cfg or {}).get("ocr") or {}
    if ocr_cfg.get("provider") != "tencent":
        return None
    secret_id = ocr_cfg.get("secret_id") or ""
    secret_key = ocr_cfg.get("secret_key") or ""
    region = ocr_cfg.get("region") or "ap-guangzhou"
    if not secret_id or not secret_key:
        return None

    def _ocr(image_path: str) -> str:
        return recognize_idcard(image_path, secret_id, secret_key, region)

    return _ocr
