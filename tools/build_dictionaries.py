"""从真实报名 Excel 提取字典值域（工种/培训类型/人员类别/学历）→ config/options_*.yaml。

用法::

    python tools/build_dictionaries.py --file "业务员A报名人员.xlsm"

产出每列的去重值（按出现次数排序）。归一化规则：命中权威值 → 保留；
未命中 → 「其他」（导入时汇总告警，不猜）。别名表 *_aliases.yaml 生成空模板，
后续人工确认后再补（与 FormPilot 的字典纪律一致）。
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")

#: 目标列 → (表头候选名, 归一化映射)
TARGETS = {
    "工种": (("工种",), None),
    "培训类型": (("培训类型",), {"新办": "新办", "复审": "复审", "换证": "换证",
                                "初训": "新办"}),
    "人员类别": (("安全员/负责人", "负责人"), {
        "主要负责人": "主要负责人", "负责人": "主要负责人",
        "职业健康单位负责人": "主要负责人",
        "安全员": "安全员", "安全管理人员": "安全员",
        "职业健康管理人员": "安全员", "管理员": "管理员"}),
    "学历": (("学历",), {
        "初中": "初中", "高中": "高中", "中专": "中专", "大专": "大专", "本科": "本科",
        "高中或同等学历": "高中", "中专或同等学历": "中专",
        "专科或同等学历": "大专", "本科或同等学历": "本科",
        "研究生及以上": "其他"}),
}


def read_rows(path: str):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["总表"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    # 同名列表头（如两个「学历」）只取第一列——第二列是材料图片状态，不是值域
    index = {}
    for i, name in enumerate(header):
        index.setdefault(name, i)
    return header, index, rows[1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="报名总表 .xlsm/.xlsx")
    args = ap.parse_args()

    header, index, rows = read_rows(args.file)
    print(f"读取 {len(rows)} 行，表头 {len(header)} 列")
    for name, (candidates, mapping) in TARGETS.items():
        col = next((index[c] for c in candidates if c in index), None)
        if col is None:
            print(f"[跳过] {name}：表头里没有 {candidates}")
            continue
        counter = Counter()
        for row in rows:
            raw = row[col] if col < len(row) else None
            if raw is None or str(raw).strip() == "":
                continue
            text = str(raw).strip()
            if text.startswith("=DISPIMG") or text.startswith("="):
                continue                          # 嵌图公式不是值域
            canonical = (mapping or {}).get(text, text)
            counter[canonical] += 1
        values = [v for v, _ in counter.most_common()]
        options_path = os.path.join(CONFIG, f"options_{name}.yaml")
        aliases_path = os.path.join(CONFIG, f"{name}_aliases.yaml")
        with open(options_path, "w", encoding="utf-8", newline="\n") as fh:
            yaml.safe_dump(values, fh, allow_unicode=True)
        if not os.path.exists(aliases_path):
            with open(aliases_path, "w", encoding="utf-8", newline="\n") as fh:
                yaml.safe_dump({}, fh, allow_unicode=True)
        print(f"{name}: {len(values)} 个值 → {os.path.basename(options_path)}  {values[:8]}")


if __name__ == "__main__":
    main()
