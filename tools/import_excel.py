"""把真实报名 Excel（总表）导入线上多维表格——公司/班期/报名记录/收款 四张表。

用法::

    python tools/import_excel.py --file "业务员A报名人员.xlsm" --year 2026 --reset
    python tools/import_excel.py --file ... --limit 20          # 先试 20 行

映射规则（见 docs/报名结算系统-设计.md 2.1）：
- 企业名称 → 公司表（集团：名称含「某集团」→ 某集团集团）
- 参加日期 → 班期表（考试日期=参加日期；班期名称「M.D 期」）
- 缴费/公司收费/返还 → 报名记录金额；缴费>0 → 另记一条收款流水（业务员代收）
- 复审到期日期：表里有就用，没有按参加日期 + 3 年推算（enroll/certificate.py）
- 字典值域：config/options_*.yaml（tools/build_dictionaries.py 生成），未命中归「其他」
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import yaml

from enroll.bitable import BitableClient
from enroll.certificate import review_due
from core.dictionaries import normalize as _norm
from core import id_card as ic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def _parse_date(value, year: int):
    """'6月23日' / datetime / '2026-06-23' → date。"""
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    import re
    m = re.fullmatch(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        return date(year, int(m.group(1)), int(m.group(2)))
    return None


#: 真实表值 → 权威值（与 tools/build_dictionaries.py 的映射保持一致）
NORMALIZE = {
    "培训类型": {"初训": "新办"},
    "人员类别": {"负责人": "主要负责人", "职业健康单位负责人": "主要负责人",
                "安全管理人员": "安全员", "职业健康管理人员": "安全员"},
    "学历": {"本科或同等学历": "本科", "专科或同等学历": "大专",
             "高中或同等学历": "高中", "中专或同等学历": "中专",
             "研究生及以上": "其他"},
}


def _load_options(name: str):
    path = os.path.join(CONFIG, f"options_{name}.yaml")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        values = yaml.safe_load(fh) or []
    return {_norm(v): v for v in values}


def _canon(options, raw, fallback="其他", misses=None, field=""):
    if raw is None or str(raw).strip() == "":
        return ""
    text = str(raw).strip()
    if text.startswith("="):                 # 嵌图公式（材料列）不是值域
        return ""
    text = NORMALIZE.get(field, {}).get(text, text)
    if options is None:
        return text
    hit = options.get(_norm(text))
    if hit:
        return hit
    if misses is not None:
        misses[(field, text)] += 1
    return fallback


def api(client, method, path, **kw):
    resp = client.session.request(method, f"{client.base_url}{path}",
                                  headers=client._headers(), timeout=30, **kw)
    payload = resp.json()
    if payload.get("code") != 0:
        raise SystemExit(f"{method} {path} 失败：{payload.get('code')} {payload.get('msg')}")
    return payload.get("data", {})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--limit", type=int, default=0, help="只导前 N 行（0=全部）")
    ap.add_argument("--reset", action="store_true", help="先清空五张业务表（危险）")
    ap.add_argument("--business", default="业务员A", help="收款业务员（默认取文件名）")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(CONFIG, "enroll.yaml"), encoding="utf-8"))
    feishu, bitable = cfg["feishu"], cfg["bitable"]
    client = BitableClient(feishu["app_id"], feishu["app_secret"], bitable["app_token"])
    tables = bitable["tables"]

    # —— 读 Excel ——
    wb = openpyxl.load_workbook(args.file, read_only=True, data_only=True)
    ws = wb["总表"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    # 同名列表头（两个「学历」）只取第一列——第二列是材料图片状态
    idx = {}
    for i, name in enumerate(header):
        idx.setdefault(name, i)
    data = rows[1:]
    if args.limit:
        data = data[: args.limit]
    print(f"读取 {len(data)} 行（表头 {len(header)} 列）")

    def cell(row, *names):
        for name in names:
            i = idx.get(name)
            if i is not None and i < len(row):
                return row[i]
        return None

    options = {name: _load_options(name)
               for name in ("工种", "培训类型", "人员类别", "学历")}
    misses: Counter = Counter()

    # —— 清空（可选）——
    if args.reset:
        total = 0
        for table in ("报名记录", "收款", "变更日志", "公司", "班期"):
            tid = tables[table]
            ids = [item["record_id"] for item in client.list_records(tid)]
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                api(client, "POST", f"/bitable/v1/apps/{bitable['app_token']}"
                                     f"/tables/{tid}/records/batch_delete",
                    json={"records": chunk})
                total += len(chunk)
        print(f"已清空 {total} 条旧记录")

    # —— 收集公司 / 班期 ——
    companies, sessions = {}, {}
    for row in data:
        name = str(cell(row, "企业名称") or "").strip()
        if name:
            companies.setdefault(name, None)
        # 「参加日期」列常为空：用报名日期兜底，两者都是"这一期"的日期
        exam_day = (_parse_date(cell(row, "参加日期"), args.year)
                    or _parse_date(cell(row, "报名日期"), args.year))
        if exam_day:
            title = f"{exam_day.month}.{exam_day.day} 期"
            sessions.setdefault(title, exam_day)
    print(f"公司 {len(companies)} 家 / 班期 {len(sessions)} 期")

    def batch_create(tid, rows_fields, key_field):
        """批量建记录并返回 key_field 值 → record_id 映射（失败回退逐条）。"""
        mapping = {}
        for start in range(0, len(rows_fields), 500):
            chunk = rows_fields[start:start + 500]
            try:
                data_ = api(client, "POST", f"/bitable/v1/apps/{bitable['app_token']}"
                                            f"/tables/{tid}/records/batch_create",
                            json={"records": [{"fields": f} for f in chunk]})
                for rec in data_.get("records", []):
                    key = (rec.get("fields") or {}).get(key_field)
                    if key:
                        mapping[key] = rec["record_id"]
            except SystemExit:
                mapping = {}      # 回退逐条
                break
        if len(mapping) != len(rows_fields):
            mapping = {}
            for fields in rows_fields:
                mapping[fields[key_field]] = client.create_record(tid, fields)
        return mapping

    company_rows = []
    for name in companies:
        payload = {"公司全名": name, "简称": name, "结算方式": "业务员代收"}
        if "某集团" in name:
            payload["所属集团"] = "某集团集团"
        company_rows.append(payload)
    company_ids = batch_create(tables["公司"], company_rows, "公司全名")
    session_rows = [{"班期名称": title, "考试日期": _ms(exam), "起始日期": _ms(exam),
                     "状态": "已结束", "负责业务员": args.business}
                    for title, exam in sessions.items()]
    session_ids = batch_create(tables["班期"], session_rows, "班期名称")
    print(f"公司/班期已建：{len(company_ids)} 家 / {len(session_ids)} 期")

    # —— 探测关联字段写入格式（不同租户/版本有差异）——
    probe_link = None
    any_company = next(iter(company_ids.values()), "")
    if any_company:
        for candidate in ([any_company], [{"record_id": any_company}]):
            try:
                rid = client.create_record(tables["报名记录"],
                                           {"姓名": "__link_probe__", "公司": candidate})
                api(client, "DELETE", f"/bitable/v1/apps/{bitable['app_token']}"
                                     f"/tables/{tables['报名记录']}/records/{rid}")
                probe_link = candidate
                break
            except SystemExit:
                continue
        if probe_link is None:
            raise SystemExit("关联字段写入格式探测失败（两种格式都被拒绝）")
        link_plain = not isinstance(probe_link[0], dict)
        print(f"关联字段格式：{'纯 id 列表' if link_plain else '{record_id} 对象列表'}")

    def link_value(record_ids):
        return list(record_ids) if link_plain else [{"record_id": r} for r in record_ids]

    # —— 组装报名记录 ——
    record_rows, row_meta = [], []
    invalid_ids = 0
    for n, row in enumerate(data, 1):
        name = str(cell(row, "姓名") or "").strip()
        if not name:
            continue
        id_no = ic.normalize(str(cell(row, "身份证") or ""))
        if id_no and not ic.validate_structure(id_no).ok:
            invalid_ids += 1
        attended = (_parse_date(cell(row, "参加日期"), args.year)
                    or _parse_date(cell(row, "报名日期"), args.year))
        registered = _parse_date(cell(row, "报名日期"), args.year) or attended
        company = str(cell(row, "企业名称") or "").strip()
        title = f"{attended.month}.{attended.day} 期" if attended else ""
        fee = cell(row, "缴费")
        fee = float(fee) if isinstance(fee, (int, float)) else None
        fields = {
            "姓名": name,
            "手机号": str(cell(row, "联系方式") or "").strip(),
            "身份证号": id_no,
            "学历": _canon(options["学历"], cell(row, "学历"), "其他", misses, "学历"),
            "人员类别": _canon(options["人员类别"], cell(row, "安全员/负责人", "负责人"),
                            "其他", misses, "人员类别"),
            "工种": _canon(options["工种"], cell(row, "工种"), "", misses, "工种"),
            "培训类型": _canon(options["培训类型"], cell(row, "培训类型"), "其他",
                            misses, "培训类型"),
            "报名状态": "已参加",
            "缴费状态": "已缴费" if fee else "未收",
            "开票状态": "未开",
            "登记渠道": "EXCEL导入",
            "备注": str(cell(row, "备注") or "").strip(),
        }
        # 日期字段：解析不到就不写（空字符串会触发 DatetimeFieldConvFail）
        if registered:
            fields["登记日期"] = _ms(registered)
        if attended:
            fields["参加日期"] = _ms(attended)
        if fee is not None:
            fields["缴费"] = fee
        for src, dst in (("公司收费", "公司收费"), ("返还", "返还")):
            value = cell(row, src)
            if isinstance(value, (int, float)):
                fields[dst] = float(value)
        due = review_due(attended, 3, existing=cell(row, "复审到期日期"))
        if due:
            fields["复审到期日期"] = _ms(due)
        if company and company in company_ids:
            fields["公司"] = link_value([company_ids[company]])
        if title and title in session_ids:
            fields["班期"] = link_value([session_ids[title]])
        record_rows.append(fields)
        row_meta.append((name, fee, registered))

    # —— 分批写报名记录（500/批），保留 id 供收款关联 ——
    record_ids = []
    for start in range(0, len(record_rows), 500):
        chunk = record_rows[start:start + 500]
        data_ = api(client, "POST", f"/bitable/v1/apps/{bitable['app_token']}"
                                    f"/tables/{tables['报名记录']}/records/batch_create",
                    json={"records": [{"fields": f} for f in chunk]})
        ids = [rec["record_id"] for rec in data_.get("records", [])]
        record_ids.extend(ids)
        print(f"报名记录 {start + len(chunk)}/{len(record_rows)}")
    if len(record_ids) != len(record_rows):
        print(f"[警告] 返回 id 数 {len(record_ids)} ≠ 记录数 {len(record_rows)}，收款关联可能不全")

    # —— 收款流水（缴费>0 的）——
    payments = []
    for i, (name, fee, registered) in enumerate(row_meta):
        if not fee or i >= len(record_ids):
            continue
        payload = {"姓名": name, "金额": float(fee), "收款方式": "微信",
                   "收款人类型": "业务员代收", "业务员": args.business,
                   "关联报名记录": link_value([record_ids[i]])}
        if registered:                       # 空日期会触发 DatetimeFieldConvFail
            payload["时间"] = _ms(registered)
        payments.append(payload)
    for start in range(0, len(payments), 500):
        chunk = payments[start:start + 500]
        api(client, "POST", f"/bitable/v1/apps/{bitable['app_token']}"
                            f"/tables/{tables['收款']}/records/batch_create",
            json={"records": [{"fields": f} for f in chunk]})
        print(f"收款流水 {start + len(chunk)}/{len(payments)}")

    print(f"\n完成：公司 {len(company_ids)} / 班期 {len(session_ids)} / "
          f"报名记录 {len(record_rows)} / 收款 {len(payments)}"
          f"，身份证校验不过 {invalid_ids} 条")
    if misses:
        print("字典未命中（已归「其他」，可补别名表）：")
        for (field, raw), cnt in misses.most_common(16):
            print(f"  {field}「{raw}」×{cnt}")


if __name__ == "__main__":
    main()
