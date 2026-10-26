"""离线演示库：一个 JSON 文件顶替多维表格，跑通"指令 → 改状态 → 写日志 → 结算"闭环。

真连模式（M1 联调）时用同一套接口换 BitableClient 实现；接口即本类的公开方法。
种子数据来自真实样表的金额结构（缴费 700 = 公司收费 400 + 返还 300；一条退训）。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

#: 五张表（设计文档 二）：报名记录 / 收款 / 变更日志 / 公司 / 班期
_EMPTY = {"报名记录": [], "收款": [], "变更日志": [], "公司": [], "班期": [], "收费标准": []}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DemoStore:
    def __init__(self, path: str = ""):
        self.path = path
        self.tables: Dict[str, List] = json.loads(json.dumps(_EMPTY))
        self._lock = threading.Lock()
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                self.tables = json.load(fh)

    # ------------------------------------------------------------------
    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.tables, fh, ensure_ascii=False, indent=1)

    def records(self) -> List[Dict]:
        return self.tables["报名记录"]

    def companies(self) -> List[Dict]:
        return self.tables["公司"]

    def sessions(self) -> List[Dict]:
        return self.tables["班期"]

    def pricing(self) -> List[Dict]:
        return self.tables.setdefault("收费标准", [])

    def find_by_key(self, key: str):
        from enroll.records import id_key
        if not key:
            return None
        for rec in self.records():
            if id_key(rec) == key:
                return rec
        return None

    def create(self, fields: Dict) -> Dict:
        rec = dict(fields)
        self.records().append(rec)
        return rec

    def update_fields(self, rec: Dict, fields: Dict) -> None:
        rec.update(fields)

    def log(self, name: str, ctype: str, field: str, old, new,
            operator: str, source: str) -> None:
        self._log(name, ctype, field, old, new, operator, source)

    def payments_by_key(self) -> Dict[str, List[Dict]]:
        """收款流水按姓名归组（演示库用姓名做关联；真连模式用关联字段 record_id）。"""
        grouped: Dict[str, List[Dict]] = {}
        for p in self.tables["收款"]:
            grouped.setdefault(p.get("姓名", ""), []).append(p)
        return grouped

    def counts(self) -> Dict[str, int]:
        return {name: len(rows) for name, rows in self.tables.items()}

    # ------------------------------------------------------------------
    def seed(self) -> "DemoStore":
        """样表数据结构（人名为演示替身，金额结构忠实于真实表）。"""
        self.tables = json.loads(json.dumps(_EMPTY))
        self.tables["公司"] = [
            {"公司全名": "某集团收获机具公司", "简称": "某集团（收获机具）",
             "所属集团": "某集团集团"},
            {"公司全名": "某集团（中小拖）", "简称": "某集团（中小拖）", "所属集团": "某集团集团"},
        ]
        self.tables["班期"] = [{"班期名称": "26.6.24 期", "考试日期": "2026-06-24",
                               "起始日期": "2026-06-24", "状态": "已结束"}]
        self.tables["收费标准"] = [
            {"工种": "危化经营主要负责人", "培训类型": "新办", "标准价": 700},  # 合同价口径
            {"工种": "叉车", "培训类型": "新办", "标准价": 700},
        ]
        self.records().extend([
            {"姓名": "李蕾", "手机号": "18800000000", "身份证号": "410102199001010004",
             "公司": "某集团（中小拖）", "班期": "26.6.24 期",
             "人员类别": "主要负责人", "工种": "危化经营主要负责人",
             "培训类型": "新办", "登记日期": "6月21日", "登记渠道": "群机器人",
             "缴费": 700, "公司收费": 400, "返还": 300,
             "报名状态": "已确认", "缴费状态": "已缴费", "开票状态": "已开"},
            {"姓名": "张莹", "手机号": "15100000000", "身份证号": "410102199202020022",
             "公司": "某集团（收获机具）", "班期": "26.6.24 期",
             "人员类别": "安全员", "工种": "叉车",
             "培训类型": "新办", "登记日期": "6月21日", "登记渠道": "群机器人",
             "缴费": 700, "公司收费": 400, "返还": 300,
             "报名状态": "已确认", "缴费状态": "未收", "开票状态": "未开"},
        ])
        self.tables["收款"].extend([
            {"姓名": "李蕾", "金额": 700, "收款方式": "微信",
             "收款人类型": "业务员代收", "业务员": "业务员A", "时间": "2026-06-21 10:00"},
        ])
        return self

    # ------------------------------------------------------------------
    def _log(self, name: str, ctype: str, field: str, old, new,
             operator: str, source: str) -> None:
        self.tables["变更日志"].append({
            "姓名": name, "时间": now_str(), "操作人": operator,
            "变更类型": ctype, "字段": field, "旧值": old, "新值": new,
            "触发来源": source})

    def find_record(self, name: str) -> Optional[Dict]:
        for rec in self.records():
            if rec.get("姓名") == name:
                return rec
        return None

    def _pick(self, name: str, qual: str = "") -> Tuple[Optional[Dict], str]:
        """按姓名+限定词定位唯一记录；返回 (记录, 错误文案)。重名不猜。"""
        from enroll.records import describe_candidates, qualify
        hits = qualify(self.records(), name, qual)
        if not hits:
            return None, (f"没有找到「{name}」的报名记录，请先登记或检查姓名"
                          + ("（限定词没匹配上）" if qual else ""))
        if len(hits) > 1:
            return None, (f"「{name}」有 {len(hits)} 条记录，请加限定词：\n"
                          + describe_candidates(hits)
                          + f"\n例：{name} <尾号或登记日期> 已缴费")
        return hits[0], ""

    def set_status(self, name: str, verb: str, field: str,
                   operator: str, source: str = "群指令",
                   qual: str = "") -> Tuple[bool, str]:
        """改状态并写日志；记录不存在/重名 → (False, 提示)。绝不猜。"""
        rec, err = self._pick(name, qual)
        if rec is None:
            return False, err
        old = rec.get(field, "")
        rec[field] = verb
        self._log(name, "状态变更", field, old, verb, operator, source)
        return True, f"{name}：{old or '（空）'} → {verb}（{operator}，{source}）"

    def add_payment(self, name: str, amount: float, operator: str,
                    source: str = "群指令", method: str = "微信",
                    payee: str = "业务员代收", qual: str = "") -> Tuple[bool, str]:
        rec, err = self._pick(name, qual)
        if rec is None:
            return False, err
        self.tables["收款"].append({"姓名": name, "金额": amount,
                                    "收款方式": method, "收款人类型": payee,
                                    "业务员": operator, "时间": now_str()})
        old = rec.get("缴费状态", "")
        rec["缴费状态"] = "已退" if amount < 0 else "已缴费"
        self._log(name, "状态变更", "缴费状态", old, rec["缴费状态"],
                  operator, f"{source}（收款 {amount:g} 元）")
        return True, (f"{name}：缴费状态 {old or '（空）'} → {rec['缴费状态']}"
                      f"（收款 {amount:g} 元入流水）")

    def timeline(self, name: str, limit: int = 10) -> List[Dict]:
        rows = [e for e in self.tables["变更日志"] if e.get("姓名") == name]
        return list(reversed(rows))[:limit]
