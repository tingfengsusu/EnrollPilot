"""结算核对与日报渲染（纯逻辑；字段名 = bitable 中文业务名）。

核心等式（设计文档 5.1，来自真实样表）：**缴费 = 公司收费 + 返还**；
公司应留存 = Σ实收 − Σ已实收部分的返还。样例：缴费 700 = 公司收费 400 + 返还 300。

口径说明：
- 总缴费只认**收款流水**（一笔一条，真连时是收款表），不双计记录上的「缴费」字段；
- 「公司收费 / 返还」只对**已实收**的记录计（没收到钱的返还不是应付款）；
- 没有收款流水的已填「缴费」记录进**待收**名单，不进合计。

这是「结算核对」不是财务意义的对账——每条单据自洽校验 + 分组汇总出结算单，
差异当天暴露（红灯），不做银行流水比对。
"""
from __future__ import annotations

from typing import Dict, List


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def check_record(rec: Dict, payments: List[Dict]) -> List[str]:
    """单条报名记录的自洽校验，返回问题清单（空 = 通过）。"""
    issues: List[str] = []
    paid = sum(_num(p.get("金额")) for p in (payments or []))
    缴费 = rec.get("缴费")
    公司收费 = rec.get("公司收费")
    返还 = rec.get("返还")

    if 缴费 is None and paid > 0:
        issues.append(f"有收款 {paid:g} 元但未填缴费")
    if 缴费 is not None and paid > _num(缴费):
        issues.append(f"超收：实收 {paid:g} > 缴费 {_num(缴费):g}")
    if None not in (缴费, 公司收费, 返还):
        if _num(缴费) != _num(公司收费) + _num(返还):
            issues.append(f"拆分不平：缴费 {_num(缴费):g} ≠ "
                          f"公司收费 {_num(公司收费):g} + 返还 {_num(返还):g}")
    if rec.get("缴费状态") == "已退" and paid > 0:
        issues.append("已退但存在正向收款")
    return issues


def summarize(records: List[Dict], payments_by_key: Dict[str, List[Dict]],
              date: str = "") -> Dict:
    """按结算口径汇总。``date`` 非空时只统计 ``登记日期`` 匹配的记录。

    返回 {新增人数, 收款笔数, 总缴费, 总公司收费, 总返还, 公司应留存,
    待收: [(姓名, 缴费)], 差异: [(姓名, 问题)]}。
    """
    rows = [r for r in records if not date or r.get("登记日期", "") == date]
    total = {"新增人数": len(rows), "收款笔数": 0, "总缴费": 0.0,
             "总公司收费": 0.0, "总返还": 0.0, "待收": [], "差异": []}
    for rec in rows:
        name = rec.get("姓名", "")
        payments = payments_by_key.get(name, [])
        paid = sum(_num(p.get("金额")) for p in payments)
        total["收款笔数"] += len(payments)
        total["总缴费"] += paid
        if paid > 0:
            total["总公司收费"] += _num(rec.get("公司收费"))
            total["总返还"] += _num(rec.get("返还"))
        elif rec.get("缴费") is not None:
            total["待收"].append((name, rec.get("缴费")))
        for msg in check_record(rec, payments):
            total["差异"].append((name, msg))
    total["公司应留存"] = round(total["总缴费"] - total["总返还"], 2)
    return total


def render_daily(records: List[Dict], payments_by_key: Dict[str, List[Dict]],
                 date: str = "今天") -> str:
    """渲染文本结算日报（发群格式）。"""
    s = summarize(records, payments_by_key, date if date != "今天" else "")
    lines = [f"【结算日报 {date}】",
             f"新增报名 {s['新增人数']} 人 / 收款 {s['收款笔数']} 笔共 {s['总缴费']:g} 元",
             f"公司应留存 {s['公司应留存']:g} 元（公司收费 {s['总公司收费']:g} − "
             f"返还 {s['总返还']:g}）"]
    if s["待收"]:
        lines.append("待收：" + "、".join(f"{n} {_num(v):g}元" for n, v in s["待收"]))
    if s["差异"]:
        lines.append("差异（需人工处理）：")
        lines += [f"  ⚠ {name}：{msg}" for name, msg in s["差异"]]
    else:
        lines.append("差异：无 ✓")
    return "\n".join(lines)
