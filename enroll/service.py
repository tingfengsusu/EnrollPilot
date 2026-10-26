"""指令执行服务：把解析出的 Command 变成对 store 的操作与回群文案。

demo 模式传 DemoStore，真连模式（M1 联调）换同一接口的 bitable 实现——
本模块不感知存储后端。
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from enroll.instructions import USAGE, Command
from enroll.reminders import due_reminders, render_reminders
from enroll.settlement import render_daily


def fmt_time(value) -> str:
    """bitable 日期字段读回是毫秒时间戳；展示时转可读字符串。"""
    if isinstance(value, (int, float)) and value > 100_000_000_000:
        return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M:%S")
    return "" if value is None else str(value)


class StoreLike(Protocol):
    """store 需要提供的方法（结构化类型，DemoStore 已满足）。"""

    def records(self) -> list: ...
    def counts(self) -> dict: ...
    def payments_by_key(self) -> dict: ...
    def set_status(self, name: str, verb: str, field: str,
                   operator: str, source: str = "群指令") -> tuple: ...
    def add_payment(self, name: str, amount: float, operator: str,
                    source: str = "群指令") -> tuple: ...
    def timeline(self, name: str, limit: int = 10) -> list: ...


def execute(store: StoreLike, cmd: Command, operator: str = "系统") -> str:
    """执行一条指令，返回回群文案。"""
    if cmd.action == "status":
        c = store.counts()
        return "当前数据：" + " / ".join(f"{k} {v}" for k, v in c.items())
    if cmd.action == "set_status":
        if cmd.amount is not None:
            # 「已缴费 700」：收款流水是事实源，由它顺带改缴费状态并写一条日志
            ok, reply = store.add_payment(cmd.name, cmd.amount, operator,
                                          qual=cmd.qual)
            return reply
        ok, reply = store.set_status(cmd.name, cmd.verb, cmd.field, operator,
                                     qual=cmd.qual)
        return reply
    if cmd.action == "records":
        rows = store.timeline(cmd.name)
        if not rows:
            return f"「{cmd.name}」暂无变更记录"
        lines = [f"【{cmd.name} 的变更时间线】"]
        for e in rows:
            # bitable 对空字段不返回键，全部用 .get() 安全取值
            lines.append(f"  {fmt_time(e.get('时间'))} {e.get('字段', '')}："
                         f"{e.get('旧值') or '（空）'} → {e.get('新值', '')}"
                         f"（{e.get('操作人', '')}，{e.get('触发来源', '')}）")
        return "\n".join(lines)
    if cmd.action == "query":
        hits = [r for r in store.records()
                if cmd.keyword in (r.get("姓名", "") + r.get("公司", ""))]
        if not hits:
            return f"没有匹配「{cmd.keyword}」的记录"
        lines = [f"【查询「{cmd.keyword}」→ {len(hits)} 条】"]
        for r in hits[:5]:
            lines.append(f"  {r.get('姓名')}｜{r.get('公司', '')}｜"
                         f"{r.get('工种', '')}｜缴费 {r.get('缴费', '-')}｜"
                         f"缴费状态 {r.get('缴费状态', '')}")
        return "\n".join(lines)
    if cmd.action == "remind":
        from datetime import date as _date
        items = due_reminders(store.records(), store.sessions(), _date.today())
        return render_reminders(items)
    if cmd.action == "settle":
        return render_daily(store.records(), store.payments_by_key(),
                            date=cmd.date or "今天")
    if cmd.action == "export":
        return "名单导出在 M4 开通（按班期/集团/状态出 Excel）"
    return "未支持的指令\n" + USAGE
