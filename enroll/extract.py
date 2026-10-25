"""文本抽取管道（纯逻辑，离线可测）。

两个入口：

- 微信「复制图片内容」的文本——实测字段交错错位（"出生 1992 / 民族汉 / 年1月18日"、
  住址被折行粘进户籍码），见设计文档 2.0；
- 任意 OCR 引擎吐出的身份证文本（标签行 + 值行，或「标签：值」行）。

输出 :class:`ExtractResult`：``fields`` 是抽取出的原始字段；身份证号做校验位检查，
出生/性别与身份证号内嵌信息**交叉核对**——不一致只报警不猜（FormPilot 原则）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

from core import id_card as ic

#: 标签词（兼容「姓名」独立行与「姓名：张三」同行两种形态）
_LABEL_RE = re.compile(
    r"^(姓名|性别|出生|住址|民族|公民身份[号码]+|身份证号[码]?)\s*[：:]?\s*(.*)$")
_ID_SEARCH_RE = re.compile(r"\d{17}[\dXx]")
_GENDER_RE = re.compile(r"^(男|女)$")
_NATION_RE = re.compile(r"^民族([\u4e00-\u9fa5]{1,3})$")
_NAME_RE = re.compile(r"^[\u4e00-\u9fa5]{2,4}$")
_BIRTH_FULL_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_YEAR_RE = re.compile(r"^\d{4}$")
_ADDR_HINT_RE = re.compile(
    r"(省|市|自治区|区|县|镇|乡|村|街|路|巷|道|号楼|栋|单元|号院|号)")

#: 短中文行里不算姓名的词（OCR 常见的标签残留/单字）
_NON_NAME = {"姓名", "性别", "出生", "住址", "民族", "汉族", "公民"}


@dataclass
class ExtractResult:
    fields: Dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


_ID_TEXT_HINT_RE = re.compile(r"公民身份|身份证号|\d{17}[\dXx]")


def looks_like_id_text(text: str) -> bool:
    """一段文本像不像身份证识别结果（先于指令判断：身份证文本里也可能含「状态」等词）。"""
    return bool(text) and bool(_ID_TEXT_HINT_RE.search(text))


def _birth_to_iso(year: str, month: str, day: str) -> str:
    return f"{year}-{int(month):02d}-{int(day):02d}"


def parse_id_text(text: str) -> ExtractResult:
    """把身份证识别文本解析成结构化字段 + 存疑清单。"""
    result = ExtractResult()
    fields, warnings = result.fields, result.warnings
    addr_parts: List[str] = []
    birth_frags: List[str] = []
    birth_iso = ""
    current = ""

    def take_birth(value: str) -> bool:
        m = _BIRTH_FULL_RE.search(value)
        if m:
            nonlocal birth_iso
            birth_iso = _birth_to_iso(m.group(1), m.group(2), m.group(3))
            return True
        return False

    def handle_value(value: str) -> None:
        nonlocal birth_iso
        if not value:
            return
        m = _ID_SEARCH_RE.search(value)
        if m:                                   # 18 位证件号永远优先
            fields["身份证号"] = ic.normalize(m.group(0))
            return
        if _GENDER_RE.match(value):
            fields["性别"] = value
            return
        n = _NATION_RE.match(value)
        if n:
            fields["民族"] = n.group(1)
            return
        if take_birth(value):
            return
        if (_YEAR_RE.match(value)
                or ("年" in value and "月" in value and "日" in value
                    and re.search(r"\d", value))):
            birth_frags.append(value)           # 「1992」+「年1月18日」被拆行；拼回来再解析
            return
        if current == "出生" and re.fullmatch(r"\d{1,4}", value):
            birth_frags.append(value)
            return
        if current == "民族" and re.fullmatch(r"[\u4e00-\u9fa5]{1,3}", value):
            fields["民族"] = value
            return
        if (_NAME_RE.match(value) and value not in _NON_NAME
                and "姓名" not in fields and not addr_parts):
            fields["姓名"] = value              # 首个短中文行当姓名（见上，模式优先）
            return
        if _ADDR_HINT_RE.search(value) or current == "住址":
            addr_parts.append(value)
            return
        if current == "出生":
            birth_frags.append(value)
            return
        warnings.append(f"未归类行「{value[:20]}」，请人工核对")

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LABEL_RE.match(line)
        if m:
            current = m.group(1)
            handle_value(m.group(2).strip())
            continue
        handle_value(line)

    # —— 组装 ——
    if not birth_iso and birth_frags:
        take_birth("".join(birth_frags))
    if birth_iso:
        fields["出生日期"] = birth_iso
    if addr_parts:
        address = "".join(addr_parts)
        fields["住址"] = address
        if re.search(r"\d{6}$", address):
            warnings.append(f"住址末尾 6 位数字疑似邮编混入（{address[-6:]}），请人工核对")

    # —— 交叉核对：只报警，不猜 ——
    id_no = fields.get("身份证号")
    if id_no:
        check = ic.validate_structure(id_no)
        if not check.ok:
            warnings.append(f"身份证校验不过：{check.detail}")
        birth_in_id = ic.parse_birthdate(id_no)
        if birth_iso and birth_in_id:
            want = birth_in_id.isoformat()
            if want != birth_iso:
                warnings.append(f"出生日期文本({birth_iso})与身份证号内嵌({want})不一致，以人工确认为准")
        gender_in_id = ic.gender_of(id_no)
        if fields.get("性别") and gender_in_id and fields["性别"] != gender_in_id:
            warnings.append(f"性别文本({fields['性别']})与身份证号内嵌({gender_in_id})不一致")
    if "姓名" not in fields:
        warnings.append("未识别出姓名")
    if not id_no:
        warnings.append("未识别出 18 位身份证号")
    return result
