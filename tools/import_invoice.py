"""导入开票明细（某集团培训剩余人员开票明细）→「开票明细」表。

用法::

    python tools/import_invoice.py --file "某集团培训26.10.22开票明细.xlsx" --reset

表头在第二行（第一行是标题）：序号/企业名称/姓名/复审到期日期/安全员负责人/工种/
培训类型/公司收费/备注。序号可能跳号，按行导入。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import yaml

from enroll.bitable import BitableClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--sheet", default="剩余人员开票明细")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(CONFIG, "enroll.yaml"), encoding="utf-8"))
    feishu, bitable = cfg["feishu"], cfg["bitable"]
    client = BitableClient(feishu["app_id"], feishu["app_secret"], bitable["app_token"])
    app, tid = bitable["app_token"], bitable["tables"]["开票明细"]

    wb = openpyxl.load_workbook(args.file, read_only=True, data_only=True)
    ws = wb[args.sheet]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    header = [str(c).strip() if c is not None else "" for c in rows[1]]
    idx = {}
    for i, name in enumerate(header):
        idx.setdefault(name, i)
    source = os.path.basename(args.file)

    def cell(row, *names):
        for name in names:
            i = idx.get(name)
            if i is not None and i < len(row):
                return row[i]
        return None

    records = []
    for row in rows[2:]:
        name = str(cell(row, "姓名") or "").strip()
        if not name:
            continue
        fee = cell(row, "公司收费")
        records.append({"fields": {
            "序号": cell(row, "序号") if isinstance(cell(row, "序号"), (int, float)) else None,
            "企业名称": str(cell(row, "企业名称") or "").strip(),
            "姓名": name,
            "复审到期日期": str(cell(row, "复审到期日期") or "").strip(),
            "安全员负责人": str(cell(row, "安全员/负责人", "安全员负责人") or "").strip(),
            "工种": str(cell(row, "工种") or "").strip(),
            "培训类型": str(cell(row, "培训类型") or "").strip(),
            "公司收费": float(fee) if isinstance(fee, (int, float)) else None,
            "备注": str(cell(row, "备注") or "").strip(),
            "来源文件": source,
        }})

    if args.reset:
        ids = [r["record_id"] for r in client.list_records(tid)]
        for start in range(0, len(ids), 500):
            client.session.post(
                f"{client.base_url}/bitable/v1/apps/{app}/tables/{tid}/records/batch_delete",
                headers=client._headers(), json={"records": ids[start:start + 500]})
        print(f"已清空开票明细 {len(ids)} 条")

    # 去掉 None 字段（数字字段传 None 可能报错）
    for rec in records:
        rec["fields"] = {k: v for k, v in rec["fields"].items() if v is not None}
    for start in range(0, len(records), 500):
        chunk = records[start:start + 500]
        resp = client.session.post(
            f"{client.base_url}/bitable/v1/apps/{app}/tables/{tid}/records/batch_create",
            headers=client._headers(), json={"records": chunk})
        payload = resp.json()
        if payload.get("code") != 0:
            raise SystemExit(f"导入失败：{payload.get('code')} {payload.get('msg')}")
    print(f"已导入开票明细 {len(records)} 条（来源：{source}）")


if __name__ == "__main__":
    main()
