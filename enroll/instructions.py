"""群指令解析（纯逻辑，白名单动词，未知/不完整 → None，绝不猜）。

支持（设计文档 四/5.2/5.3）：

    状态                      → 表计数
    结算 [日期]                → 当日结算日报
    记录 <姓名>                → 变更时间线（审计浮现）
    查 <关键词>                → 记录摘要
    导出 名单 [筛选词]          → M4，先应答"尚未开通"
    <姓名> 已确认|已参加|未参加|已缴费|已退|已开票 [金额]

``<姓名> 已缴费 700`` 的金额用于收款流水；其余状态动词只改状态。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

#: 状态动词 → 它改的是哪个状态字段（三维状态：报名/缴费/开票）
STATUS_VERBS = {
    "已确认": "报名状态",
    "已参加": "报名状态",
    "未参加": "报名状态",
    "已缴费": "缴费状态",
    "已退": "缴费状态",
    "已开票": "开票状态",
}

_NAME_RE = r"[\u4e00-\u9fa5]{2,4}"
_VERB_RE = "|".join(STATUS_VERBS)
#: 可选限定词：身份证后4位（6417）或 登记日期（6.23 / 6.23期）——重名时用来定位记录
_QUAL_RE = r"(?:\s+(?P<qual>\d{1,2}\.\d{1,2}\s?期?|\d{4}))?"
_SET_RE = re.compile(
    rf"^({_NAME_RE}){_QUAL_RE}\s*({_VERB_RE})(?:\s*([0-9]+(?:\.[0-9]+)?))?$")


@dataclass
class Command:
    action: str              # status / settle / records / query / export / set_status
    raw: str = ""
    name: str = ""           # set_status / records 的目标姓名
    verb: str = ""           # 状态动词原文
    field: str = ""          # 该动词对应的状态字段
    amount: Optional[float] = None   # 已缴费 N 的金额
    keyword: str = ""        # 查 / 导出 的筛选词
    date: str = ""           # 结算日期（空 = 今天）
    qual: str = ""           # 重名限定：身份证后4位 / 登记日期（6.23）


def parse(text) -> Optional[Command]:
    """解析一条群消息；不是白名单指令 → None（上层回用法提示，不猜）。"""
    t = (text or "").strip()
    if not t:
        return None
    if t == "状态":
        return Command("status", raw=t)
    if t == "提醒":
        return Command("remind", raw=t)
    if t in ("业务员账", "业务员对账", "销售账"):
        return Command("sales", raw=t)
    if t in ("开票对账", "开票核对"):
        return Command("invoice", raw=t)
    if t.startswith("结算"):
        return Command("settle", raw=t, date=t[2:].strip())
    if t.startswith("记录"):
        name = t[2:].strip()
        return Command("records", raw=t, name=name) if name else None
    if t.startswith("查"):
        kw = t[1:].strip()
        return Command("query", raw=t, keyword=kw) if kw else None
    if t.startswith("导出"):
        return Command("export", raw=t, keyword=t[2:].strip())
    m = _SET_RE.match(t)
    if m:
        name, qual, verb, amount = m.group(1), m.group("qual") or "", m.group(3), m.group(4)
        return Command("set_status", raw=t, name=name, verb=verb,
                       field=STATUS_VERBS[verb],
                       qual=qual.replace("期", "").strip(),
                       amount=float(amount) if amount else None)
    return None


USAGE = ("支持的指令：状态 / 提醒 / 结算 [日期] / 业务员账 / 开票对账 / "
         "记录 <姓名> / 查 <关键词> / 导出 名单 [集团] / 导出 结算 [日期] /\n"
         "<姓名> 已确认|已参加|未参加|已缴费 [金额]|已退|已开票\n"
         "重名时加限定：<姓名> <身份证后4位或登记日期 6.23> <状态>")
