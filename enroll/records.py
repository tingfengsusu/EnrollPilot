"""报名记录的归一化、幂等合并与校验（纯逻辑，离线可测）。

字段名 = bitable 中文业务名（docs/报名结算系统-设计.md 2.1）。

合并原则（设计文档 2.1）：幂等键 = 身份证号（缺则 姓名+手机号）；
**只补空、不覆盖**；三个状态字段（报名/缴费/开票）只允许人通过群指令
或面板修改，机器合并永远碰不到——这是"状态只许人改"的权限规则的实现点。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from core import id_card as ic
from core.dictionaries import normalize as _norm

#: 机器合并永远不许碰的字段（只能由人改）
HUMAN_ONLY_FIELDS = ("报名状态", "缴费状态", "开票状态")

_PHONE_RE = re.compile(r"^1\d{10}$")


def normalize_record(raw: Dict) -> Dict:
    """归一化一条原始抽取结果：去空白/全角转半角/身份证 X 大写/手机号纯数字。"""
    out: Dict = {}
    for key, value in (raw or {}).items():
        if value is None or value == "":
            continue
        text = str(value)
        if key in ("身份证号",):
            out[key] = ic.normalize(text)
        elif key in ("手机号", "联系电话", "联系方式"):
            digits = re.sub(r"\D", "", _norm(text))
            out[key] = digits
        elif key in HUMAN_ONLY_FIELDS:
            out[key] = text.strip()
        else:
            out[key] = _norm(text) if key not in ("备注", "触发来源") else text.strip()
    return out


def id_key(rec: Dict) -> Optional[str]:
    """幂等键：身份证号优先，缺则 姓名|手机号；两者都缺 → None（不可合并，须人工）。"""
    id_no = rec.get("身份证号")
    if id_no and len(str(id_no)) == 18:
        return f"id:{id_no}"
    name, phone = rec.get("姓名", ""), rec.get("手机号", "")
    if name and phone:
        return f"np:{name}|{phone}"
    return None


def merge_into(existing: Dict, incoming: Dict) -> Tuple[Dict, Dict[str, Tuple]]:
    """把 incoming 合并进 existing（不改动入参）：只补空字段，状态字段绝不碰。

    返回 (merged, changed)，changed = {字段: (旧值, 新值)}，供变更日志用。
    """
    merged = dict(existing)
    changed: Dict[str, Tuple] = {}
    for key, value in (incoming or {}).items():
        if key in HUMAN_ONLY_FIELDS:
            continue
        if value and not merged.get(key):
            changed[key] = (merged.get(key), value)
            merged[key] = value
    return merged, changed


def validate(rec: Dict) -> List[str]:
    """录入校验：必填 + 身份证校验位（复用 batch 基建）+ 手机号格式。只报问题，不猜。"""
    issues: List[str] = []
    if not rec.get("姓名"):
        issues.append("缺姓名")
    id_no = rec.get("身份证号")
    if id_no:
        check = ic.validate_structure(id_no)
        if not check.ok:
            issues.append(f"身份证异常：{check.detail}")
    elif not rec.get("手机号"):
        issues.append("身份证号与手机号都缺，无法建幂等键")
    phone = rec.get("手机号")
    if phone and not _PHONE_RE.match(str(phone)):
        issues.append(f"手机号格式异常：{phone}")
    return issues


def record_day(rec: Dict) -> str:
    """记录日期 → "M.D"（登记日期优先，毫秒时间戳/字符串都兼容）。"""
    from datetime import datetime
    value = rec.get("登记日期") or rec.get("参加日期")
    if value in (None, ""):
        return ""
    dt = None
    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value / 1000)
    else:
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            m = re.fullmatch(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
            if m:
                return f"{int(m.group(1))}.{int(m.group(2))}"
    return f"{dt.month}.{dt.day}" if dt else ""


def qualify(records: List[Dict], name: str, qual: str = "") -> List[Dict]:
    """按姓名筛记录，并用限定词收窄：qual=4位数字 → 身份证尾号；qual=M.D → 登记日期。"""
    hits = [r for r in records if r.get("姓名") == name]
    if qual and hits:
        q = qual.strip()
        if re.fullmatch(r"\d{4}", q):
            hits = [r for r in hits if str(r.get("身份证号", "")).endswith(q)]
        else:
            hits = [r for r in hits if record_day(r) == q]
    return hits


def describe_candidates(records: List[Dict]) -> str:
    """重名候选说明（尾号/日期/状态），让用户加限定词。"""
    lines = []
    for rec in records[:6]:
        id_no = str(rec.get("身份证号", ""))
        tail = id_no[-4:] if len(id_no) >= 4 else "????"
        day = record_day(rec) or "日期未知"
        lines.append(f"{rec.get('姓名')}（尾号 {tail}，{day}，"
                     f"报名{rec.get('报名状态', '')}/缴费{rec.get('缴费状态', '')}）")
    return "；\n".join(lines)
