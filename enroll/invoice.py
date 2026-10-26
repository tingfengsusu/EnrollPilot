"""开票对账（纯逻辑）：开票明细 vs 报名记录。

输入来自 `tools/import_invoice.py` 导入的「开票明细」表（某集团培训剩余人员开票明细）：
序号/企业名称/姓名/复审到期日期/安全员负责人/工种/培训类型/公司收费/备注。
对账输出：已匹配 / 名单缺失（开票有、库里没有）/ 金额不一致 / 名字重名待确认。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from core.dictionaries import normalize as _norm


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def reconcile(invoice_rows: List[Dict], records: List[Dict]) -> Dict:
    by_name: Dict[str, List[Dict]] = {}
    for rec in records or []:
        by_name.setdefault(_norm(str(rec.get("姓名") or "")), []).append(rec)

    matched: List[Tuple[Dict, Dict]] = []
    missing: List[Dict] = []
    amount_diff: List[Tuple[Dict, Dict]] = []
    no_price: List[Tuple[Dict, Dict]] = []
    ambiguous: List[Dict] = []
    total = 0.0

    for inv in invoice_rows or []:
        name = _norm(str(inv.get("姓名") or ""))
        total += _num(inv.get("公司收费"))
        hits = by_name.get(name) or []
        if not hits:
            missing.append(inv)
            continue
        job = _norm(str(inv.get("工种") or ""))
        narrowed = [h for h in hits
                    if job and _norm(str(h.get("工种") or "")) == job] or hits
        if len(narrowed) > 1:
            ambiguous.append(inv)          # 重名同工种，不猜
            continue
        rec = narrowed[0]
        matched.append((inv, rec))
        rec_fee = rec.get("公司收费")
        if rec_fee in (None, ""):
            no_price.append((inv, rec))    # 记录还没填价格（未收/未定价）
        elif abs(_num(inv.get("公司收费")) - _num(rec_fee)) > 0.01:
            amount_diff.append((inv, rec))

    return {"明细条数": len(invoice_rows or []), "开票金额": round(total, 2),
            "已匹配": matched, "名单缺失": missing,
            "记录缺价格": no_price, "金额不一致": amount_diff,
            "重名待确认": ambiguous}


def render_reconcile(result: Dict) -> str:
    lines = [f"【开票对账】明细 {result['明细条数']} 条 / 开票金额 {result['开票金额']:g} 元",
             f"已匹配 {len(result['已匹配'])} 条"]
    if result["名单缺失"]:
        names = "、".join(str(x.get("姓名")) for x in result["名单缺失"][:8])
        lines.append(f"名单缺失 {len(result['名单缺失'])} 条：{names}")
    if result["记录缺价格"]:
        names = "、".join(str(inv.get("姓名")) for inv, _ in result["记录缺价格"][:10])
        lines.append(f"记录未填价格 {len(result['记录缺价格'])} 条：{names}")
    if result["金额不一致"]:
        lines.append(f"金额不一致 {len(result['金额不一致'])} 条：")
        for inv, rec in result["金额不一致"][:8]:
            lines.append(f"  ⚠ {inv.get('姓名')}：开票 {_num(inv.get('公司收费')):g} / "
                         f"记录 {_num(rec.get('公司收费')):g}")
    if result["重名待确认"]:
        names = "、".join(str(x.get("姓名")) for x in result["重名待确认"][:8])
        lines.append(f"重名待确认 {len(result['重名待确认'])} 条：{names}")
    if not (result["名单缺失"] or result["金额不一致"]
            or result["记录缺价格"] or result["重名待确认"]):
        lines.append("差异：无 ✓")
    return "\n".join(lines)
