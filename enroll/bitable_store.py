"""多维表格后端：与 DemoStore 同一套接口（service/export/intake 无感切换）。

字段名 = bitable 中文业务名（设计文档 2.1）。约定：

- ``报名记录`` 表每条记录的各字段直接用中文业务名；本类给每条记录附 ``_record_id``
  供更新用（下划线前缀字段不写回 bitable）；
- bitable 字段值形态多样（文本可能是字符串或 [{text:...}]、人员是列表），
  ``_plain`` 统一拍平成标量，M1 联调遇到新形态再补；
- ``收款`` 表联调用「姓名」文本列归组（与 DemoStore 同口径）；真实关联字段
  （record_id 关联）联调后再切换，接口不变。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from enroll.records import id_key
from enroll.demo_store import now_str


def _plain(value):
    """bitable 字段值 → 标量（文本拍平、列表取首个）。"""
    if isinstance(value, list):
        if not value:
            return ""
        first = value[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("text") or first.get("name") or first.get("file_token") or ""
        return first
    if isinstance(value, dict):
        return value.get("text") or value.get("name") or str(value)
    return value


class BitableStore:
    """StoreLike 的 bitable 实现——真连模式只差 config/enroll.yaml 填凭据。"""

    def __init__(self, client, tables: Dict[str, str]):
        self.client = client
        self.tables_cfg = tables

    def _tid(self, name: str) -> str:
        return self.tables_cfg[name]

    def _rows(self, table: str) -> List[Dict]:
        rows = []
        for item in self.client.list_records(self._tid(table)):
            rec = {k: _plain(v) for k, v in (item.get("fields") or {}).items()}
            rec["_record_id"] = item.get("record_id")
            rows.append(rec)
        return rows

    # ------------------------------------------------------------------
    # StoreLike 接口
    # ------------------------------------------------------------------
    def records(self) -> List[Dict]:
        return self._rows("报名记录")

    def companies(self) -> List[Dict]:
        return self._rows("公司")

    def counts(self) -> Dict[str, int]:
        return {name: len(self._rows(name)) for name in self.tables_cfg}

    def payments_by_key(self) -> Dict[str, List[Dict]]:
        grouped: Dict[str, List[Dict]] = {}
        for p in self._rows("收款"):
            grouped.setdefault(str(p.get("姓名", "")), []).append(p)
        return grouped

    def find_record(self, name: str) -> Optional[Dict]:
        for rec in self.records():
            if rec.get("姓名") == name:
                return rec
        return None

    def find_by_key(self, key: str) -> Optional[Dict]:
        if not key:
            return None
        for rec in self.records():
            if id_key(rec) == key:
                return rec
        return None

    def create(self, fields: Dict) -> Dict:
        payload = {k: v for k, v in fields.items() if not k.startswith("_")}
        rid = self.client.create_record(self._tid("报名记录"), payload)
        rec = dict(fields)
        rec["_record_id"] = rid
        return rec

    def update_fields(self, rec: Dict, fields: Dict) -> None:
        payload = {k: v for k, v in fields.items() if not k.startswith("_")}
        rid = rec.get("_record_id")
        if not rid:
            raise ValueError("记录缺少 _record_id，无法更新（先 records()/find_record() 取回）")
        self.client.update_record(self._tid("报名记录"), rid, payload)
        rec.update(fields)

    def log(self, name: str, ctype: str, field: str, old, new,
            operator: str, source: str) -> None:
        self.client.create_record(self._tid("变更日志"), {
            "姓名": name, "时间": now_str(), "操作人": operator,
            "变更类型": ctype, "字段": field, "旧值": "" if old is None else str(old),
            "新值": "" if new is None else str(new), "触发来源": source})

    # ------------------------------------------------------------------
    def set_status(self, name: str, verb: str, field: str,
                   operator: str, source: str = "群指令") -> Tuple[bool, str]:
        rec = self.find_record(name)
        if rec is None:
            return False, f"没有找到「{name}」的报名记录，请先登记或检查姓名"
        old = rec.get(field, "")
        self.update_fields(rec, {field: verb})
        self.log(name, "状态变更", field, old, verb, operator, source)
        return True, f"{name}：{old or '（空）'} → {verb}（{operator}，{source}）"

    def add_payment(self, name: str, amount: float, operator: str,
                    source: str = "群指令", method: str = "微信",
                    payee: str = "业务员代收") -> Tuple[bool, str]:
        rec = self.find_record(name)
        if rec is None:
            return False, f"没有找到「{name}」的报名记录"
        self.client.create_record(self._tid("收款"), {
            "姓名": name, "金额": amount, "收款方式": method,
            "收款人类型": payee, "业务员": operator, "时间": now_str()})
        old = rec.get("缴费状态", "")
        new = "已退" if amount < 0 else "已缴费"
        self.update_fields(rec, {"缴费状态": new})
        self.log(name, "状态变更", "缴费状态", old, new, operator,
                 f"{source}（收款 {amount:g} 元）")
        return True, (f"{name}：缴费状态 {old or '（空）'} → {new}"
                      f"（收款 {amount:g} 元入流水）")

    def timeline(self, name: str, limit: int = 10) -> List[Dict]:
        rows = [e for e in self._rows("变更日志") if e.get("姓名") == name]
        rows.sort(key=lambda e: str(e.get("时间", "")), reverse=True)
        return rows[:limit]
