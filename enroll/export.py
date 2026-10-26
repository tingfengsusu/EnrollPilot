"""Excel 导出（M4）：旧表三张手工衍生表 → 系统自动产物。

- :func:`export_settlement` 替代「6.24结算」手工表：按期结算单（含拆分与差异列）；
- :func:`export_roster` 替代「某集团报名人员名单」手工表：按集团/状态筛选的名单，
  集团维度经公司表 lookup 带出（Excel 单表做不到的那一步）。

导出是**读侧**产物：只读 store，不写任何表。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Font

from core.dictionaries import normalize as _norm
from enroll.records import HUMAN_ONLY_FIELDS
from enroll.settlement import check_record

_HEADER_FONT = Font(bold=True)


def _company_group_map(companies: List[Dict]) -> Dict[str, str]:
    """公司全名/简称（归一化）→ 所属集团。"""
    mapping: Dict[str, str] = {}
    for c in companies or []:
        group = c.get("所属集团", "")
        for key in (c.get("公司全名"), c.get("简称"), c.get("公司名")):
            if key:
                mapping[_norm(key)] = group
    return mapping


def _write_sheet(ws, headers: List[str], rows: List[List],
                 totals: Optional[List] = None) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT
    for row in rows:
        ws.append(row)
    if totals is not None:
        ws.append(totals)
        for cell in ws[ws.max_row]:
            cell.font = _HEADER_FONT


def _save(wb: Workbook, out_path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    wb.save(out_path)
    return out_path


def export_settlement(store, out_path: str, date: str = "") -> str:
    """按期结算单：一行一人，末尾合计。``date`` 非空时只导该登记日期。"""
    from enroll.settlement import pricing_map
    if hasattr(store, "payments_by_record"):      # 真连：按记录 ID 归组（重名安全）
        payments = store.payments_by_record()
        key_of = lambda rec: rec.get("_record_id", "")   # noqa: E731
    else:
        payments = store.payments_by_key()
        key_of = lambda rec: rec.get("姓名", "")          # noqa: E731
    try:
        pricing = pricing_map(store.pricing()) if hasattr(store, "pricing") else {}
    except Exception:  # noqa: BLE001
        pricing = {}
    rows: List[List] = []
    totals = [0.0, 0.0, 0.0]
    idx = 0
    for rec in store.records():
        if date and rec.get("登记日期", "") != date:
            continue
        idx += 1
        issues = check_record(rec, payments.get(key_of(rec), []), pricing)
        rows.append([idx, rec.get("姓名"), rec.get("公司"), rec.get("人员类别"),
                     rec.get("工种"), rec.get("培训类型"), rec.get("缴费"),
                     rec.get("公司收费"), rec.get("返还"), rec.get("缴费状态"),
                     rec.get("开票状态"), "；".join(issues)])
        for i, key in enumerate(("缴费", "公司收费", "返还")):
            value = rec.get(key)
            if isinstance(value, (int, float)):
                totals[i] += value
    wb = Workbook()
    ws = wb.active
    ws.title = "结算单"
    _write_sheet(ws, ["序号", "姓名", "公司", "人员类别", "工种", "培训类型",
                      "缴费", "公司收费", "返还", "缴费状态", "开票状态", "差异"],
                 rows, totals=["合计", "", "", "", "", "",
                               totals[0], totals[1], totals[2], "", "", ""])
    return _save(wb, out_path)


def export_for_command(store, keyword: str, out_dir: str) -> str:
    """群指令「导出 …」→ 生成对应 Excel，返回文件路径。

    - ``导出 名单 [集团]`` → 报名名单（可按集团筛选）
    - ``导出 结算 [日期]`` → 按期结算单
    """
    parts = (keyword or "").split()
    os.makedirs(out_dir, exist_ok=True)
    if parts and parts[0] == "结算":
        date = parts[1] if len(parts) > 1 else ""
        name = f"结算单_{date or '全量'}.xlsx"
        return export_settlement(store, os.path.join(out_dir, name), date=date)
    group = parts[1] if len(parts) > 1 and parts[0] == "名单" else (
        parts[0] if parts and parts[0] != "名单" else "")
    name = f"报名名单_{group or '全部'}.xlsx"
    return export_roster(store, os.path.join(out_dir, name), group=group)


def export_roster(store, out_path: str, group: str = "", period: str = "",
                  status_field: str = "", status_value: str = "") -> str:
    """名单导出：按集团（经公司表）/ 登记日期 / 任一状态字段筛选。

    ``status_field`` 必须是三个状态字段之一，防止随手筛出未知列。
    """
    if status_field and status_field not in HUMAN_ONLY_FIELDS:
        raise ValueError(f"status_field 只允许 {HUMAN_ONLY_FIELDS}，收到 {status_field!r}")
    group_map = _company_group_map(store.companies())
    rows: List[List] = []
    idx = 0
    for rec in store.records():
        if group and group_map.get(_norm(rec.get("公司", ""))) != group:
            continue
        if period and rec.get("登记日期", "") != period:
            continue
        if status_field and rec.get(status_field, "") != status_value:
            continue
        idx += 1
        rows.append([idx, rec.get("姓名"), rec.get("身份证号"), rec.get("手机号"),
                     rec.get("公司"), group_map.get(_norm(rec.get("公司", "")), ""),
                     rec.get("人员类别"), rec.get("工种"), rec.get("培训类型"),
                     rec.get("登记日期"), rec.get("报名状态"), rec.get("缴费状态"),
                     rec.get("开票状态")])
    wb = Workbook()
    ws = wb.active
    ws.title = "报名名单"
    _write_sheet(ws, ["序号", "姓名", "身份证号", "手机号", "公司", "集团",
                      "人员类别", "工种", "培训类型", "登记日期",
                      "报名状态", "缴费状态", "开票状态"], rows)
    return _save(wb, out_path)
