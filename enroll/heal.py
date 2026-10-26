"""异常自愈（轻量版）：已知故障 → 白名单处置自动重试；未知 → 记案例转人工。

设计沿用 FormPilot 的「不猜」原则：
- 只在**白名单处置**（目前是 retry 一次）命中时自动执行；
- 未命中的错误不自动修，落成**禁用案例**并回执案例编号，等人工确认；
- 案例库存 data/heal_store.json（可 git 忽略），支持查看/启用/计数。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

#: 白名单处置
REMEDIES = {"retry": "原样重试一次"}

#: 种子案例（症状子串 → 处置）
_SEED = [
    {"id": "H1", "symptom": "Timeout", "remedy": "retry", "enabled": True,
     "note": "网络/接口超时，重试一次通常可恢复"},
    {"id": "H2", "symptom": "429", "remedy": "retry", "enabled": True,
     "note": "限流，等调用方退避后重试"},
    {"id": "H3", "symptom": "1254045", "remedy": "retry", "enabled": False,
     "note": "字段不存在：已在存储层过滤，保留作参考"},
]


class HealStore:
    def __init__(self, path: str = ""):
        self.path = path
        self.cases: List[Dict] = []
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                self.cases = json.load(fh).get("cases") or []
        if not self.cases:
            self.cases = [dict(c) for c in _SEED]

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"cases": self.cases}, fh, ensure_ascii=False, indent=1)

    def match(self, error_text: str) -> Optional[Dict]:
        text = str(error_text or "")
        for case in self.cases:
            if case.get("enabled") and case.get("symptom") in text:
                return case
        return None

    def record(self, symptom: str) -> Dict:
        """未知故障：新增禁用案例（同症状去重），返回案例。"""
        key = str(symptom)[:120]
        for case in self.cases:
            if case.get("symptom") == key:
                return case
        case = {"id": f"H{len(self.cases) + 1}", "symptom": key, "remedy": "",
                "enabled": False,
                "note": f"自动记录 {datetime.now():%Y-%m-%d %H:%M}"}
        self.cases.append(case)
        self.save()
        return case

    def bump(self, case_id: str) -> None:
        for case in self.cases:
            if case.get("id") == case_id:
                case["hits"] = int(case.get("hits") or 0) + 1
                self.save()
                return
