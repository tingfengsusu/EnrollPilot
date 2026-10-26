"""演示数据补齐（可复跑）：缺登记日期、考试排期、开票价回填。

用法::

    python tools/backfill_data.py --all
    python tools/backfill_data.py --fill-dates
    python tools/backfill_data.py --schedule
    python tools/backfill_data.py --invoice-prices

说明（业务已确认口径）：
1. **缺登记日期**：源表 288 条没有报名日期——按现有批次日期循环填入（演示用，日期为补录值）；
   同时关联对应班期，保证"登记日期 ↔ 班期"一致。
2. **考试排期**：按月班（每月一次）+ 周班（每周一次）形式生成演示考试日期（日期为示例），
   考点填「洛阳市安全生产考试点」，备注标明可替换为真实排期。
3. **开票价回填**：开票明细里已匹配但记录缺价格的 34 条——缴费取「收费标准」的合同价，
   公司收费取开票金额，返还 = 缴费 − 公司收费；缴费状态保持「未收」（这些人还没交钱）。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from core.dictionaries import normalize as _norm
from enroll.bitable import BitableClient
from enroll.invoice import reconcile
from enroll.settlement import pricing_map

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def batch_update(client, app, tid, updates):
    for start in range(0, len(updates), 500):
        chunk = updates[start:start + 500]
        resp = client.session.post(
            f"{client.base_url}/bitable/v1/apps/{app}/tables/{tid}/records/batch_update",
            headers=client._headers(), json={"records": chunk})
        payload = resp.json()
        if payload.get("code") != 0:
            raise SystemExit(f"batch_update 失败：{payload.get('code')} {payload.get('msg')}")
    return len(updates)


def fill_dates(client, app, tables):
    sessions = list(client.list_records(tables["班期"]))
    # 只用「M.D 期」这种历史批次（排除演示的周班/月班）
    batch_sessions = []
    for row in sessions:
        name = str(row["fields"].get("班期名称") or "")
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2}) 期", name)
        if m:
            batch_sessions.append((date(2026, int(m.group(1)), int(m.group(2))),
                                   row["record_id"]))
    batch_sessions.sort()
    if not batch_sessions:
        raise SystemExit("没有可用的历史批次（M.D 期）")
    dates = [d for d, _ in batch_sessions]
    ids = [rid for _, rid in batch_sessions]

    updates = []
    for i, row in enumerate(client.list_records(tables["报名记录"])):
        if row["fields"].get("登记日期"):
            continue
        d = dates[i % len(dates)]
        updates.append({"record_id": row["record_id"],
                        "fields": {"登记日期": _ms(d),
                                   "班期": [ids[i % len(ids)]]}})
    n = batch_update(client, app, tables["报名记录"], updates)
    print(f"补登记日期 + 关联班期：{n} 条（日期按现有批次循环，演示补录值）")


def schedule(client, app, tables):
    """月班（每月最后一个周六）+ 周班（下 4 个周日）演示考试排期。"""
    existing = {str(r["fields"].get("班期名称")) for r in client.list_records(tables["班期"])}
    plans = [
        ("26.11.01 周班", date(2026, 11, 1), "周班"),
        ("26.11.08 周班", date(2026, 11, 8), "周班"),
        ("26.11.15 周班", date(2026, 11, 15), "周班"),
        ("26.11.22 周班", date(2026, 11, 22), "周班"),
        ("26.12 月班", date(2026, 12, 26), "月班"),
        ("27.01 月班", date(2027, 1, 30), "月班"),
    ]
    created = 0
    for name, exam, kind in plans:
        if name in existing:
            continue
        client.create_record(tables["班期"], {
            "班期名称": name, "考试日期": _ms(exam), "起始日期": _ms(exam),
            "班期类型": kind, "考点": "洛阳市安全生产考试点",
            "状态": "报名中", "负责业务员": "业务员A",
            "备注": "演示排期（考试日期为示例，可替换真实排期）"})
        created += 1
    print(f"考试排期：新增 {created} 期（月班每人月一次 + 周班每周一次，日期为示例）")


def invoice_prices(client, app, tables):
    records = [dict(r["fields"], _record_id=r["record_id"])
               for r in client.list_records(tables["报名记录"])]
    invoices = [r["fields"] for r in client.list_records(tables["开票明细"])]
    pricing = pricing_map([r["fields"] for r in client.list_records(tables["收费标准"])])
    result = reconcile(invoices, records)

    updates, no_std, below = [], 0, 0
    for inv, rec in result["记录缺价格"]:
        job = _norm(str(rec.get("工种") or ""))
        kind = _norm(str(rec.get("培训类型") or ""))
        std = pricing.get((job, kind))
        company_fee = float(inv.get("公司收费") or 0)
        if std is None or std < company_fee:
            # 价格表无该组合，或合同价低于开票金额（硬算会出负数返还）：
            # 只回填实际开票金额，缴费/返还留待业务按合同价补
            updates.append({"record_id": rec["_record_id"],
                            "fields": {"公司收费": company_fee}})
            if std is None:
                no_std += 1
            else:
                below += 1
            continue
        updates.append({"record_id": rec["_record_id"],
                        "fields": {"缴费": std, "公司收费": company_fee,
                                   "返还": round(std - company_fee, 2)}})
    n = batch_update(client, app, tables["报名记录"], updates)
    print(f"开票价回填：{n} 条（缴费取价格表合同价、公司收费取开票金额）；"
          f"其中 价格表缺组合 {no_std} 条、合同价低于开票金额 {below} 条（只回填开票金额，待人工补合同价）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--fill-dates", action="store_true")
    ap.add_argument("--schedule", action="store_true")
    ap.add_argument("--invoice-prices", action="store_true")
    args = ap.parse_args()
    if not any((args.all, args.fill_dates, args.schedule, args.invoice_prices)):
        ap.print_help()
        return

    cfg = yaml.safe_load(open(os.path.join(CONFIG, "enroll.yaml"), encoding="utf-8"))
    f, b = cfg["feishu"], cfg["bitable"]
    client = BitableClient(f["app_id"], f["app_secret"], b["app_token"])
    app, tables = b["app_token"], dict(b["tables"])

    if args.all or args.fill_dates:
        fill_dates(client, app, tables)
    if args.all or args.schedule:
        schedule(client, app, tables)
    if args.all or args.invoice_prices:
        invoice_prices(client, app, tables)


if __name__ == "__main__":
    main()
