"""登记入库：抽取结果 → 幂等合并 → 写变更日志 → 回执文案。

入口 A（群消息）与入口 B（剪贴板）共用本模块——「双入口一个库」在这里汇合。
原则：只补空不覆盖（records.merge_into）；状态字段机器碰不到；
OCR 不确定的不猜，存疑清单原样回给发消息的人。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from enroll.extract import parse_id_text
from enroll.records import id_key, merge_into, normalize_record, validate


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def intake_text(store, text: str, operator: str = "系统",
                source: str = "群消息", today: Optional[str] = None) -> str:
    """把一段身份证识别文本（微信复制/OCR）登记进库，返回回群文案。"""
    result = parse_id_text(text)
    normalized = normalize_record(result.fields)
    if not normalized:
        return "没有识别出可登记的信息。临时办法：在微信里对图片点「复制图片内容」，把文字直接粘贴发我。"
    key = id_key(normalized)
    if not key:
        return "缺身份证号（或姓名+手机号），无法建幂等键，请人工登记。"

    existing = store.find_by_key(key)
    warnings = list(result.warnings)
    issues = validate(normalized)
    today = today or _today()

    if existing:
        merged, changed = merge_into(existing, normalized)
        if not changed:
            reply = f"{existing.get('姓名')}：无新增信息（已有记录）"
        else:
            store.update_fields(existing, {k: new for k, (_, new) in changed.items()})
            for field_name, (old, new) in changed.items():
                store.log(existing.get("姓名", ""), "字段补全", field_name,
                          old, new, operator, source)
            names = "、".join(changed)
            reply = f"{existing.get('姓名')}：补全 {len(changed)} 项（{names}）"
    else:
        rec = store.create({**normalized, "登记日期": today, "登记渠道": source,
                            "报名状态": "待确认", "缴费状态": "未收", "开票状态": "未开"})
        store.log(rec.get("姓名", ""), "新增", "报名记录", None,
                  "待确认", operator, source)
        reply = f"{rec.get('姓名')}：已登记 ✓（待确认）"

    if warnings:
        reply += "\n存疑（请人工核对）：\n  " + "\n  ".join(warnings)
    if issues:
        reply += "\n校验问题：\n  " + "\n  ".join(issues)
    return reply
