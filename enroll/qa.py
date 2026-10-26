"""报名数据问答（P2，规则式，不依赖 LLM）。

支持四类问题（返回 None = 不会答，调用方回用法提示）：

- 欠款：「某集团集团还欠多少」「张三欠多少」「7.28期还欠多少」
- 人数/名单：「7.28期多少人」「某集团集团名单」「谁还没缴费」
- 收款：「今天收款多少」「一共收了多少钱」
- 状态：「张三什么状态」「某集团（中小拖）什么情况」

匹配口径：主体同时匹配 姓名 / 公司（含集团映射）/ 班期；不猜同音字。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from core.dictionaries import normalize as _norm
from enroll.records import record_day
from enroll.reminders import to_date

_DEBT_WORDS = ("还欠多少", "欠多少", "欠款", "待收", "没交", "没缴费", "未缴费", "欠")
_COUNT_WORDS = ("多少人", "几个人", "人数", "名单", "有哪些", "有谁", "谁还")
_PAY_WORDS = ("收款", "收了", "入账", "到账")
_STATUS_WORDS = ("状态", "情况", "怎么样")
_EXAM_WORDS = ("考试时间", "什么时候考试", "哪天考试", "几号考试",
               "考试是什么时候", "考试安排", "什么时候考", "几号考", "考试日期")

_FILLER = ("的", "了", "呢", "吗", "请", "帮我", "查一下", "问一下", "?", "？",
           "，", ",", "。", " ", "　", "什么", "啥", "如何", "今天", "今日",
           "昨天", "本周", "本月", "一共", "总共", "都", "一下",
           "多少", "几笔", "多少钱", "金额", "钱")


def _strip_words(text: str, words) -> Tuple[str, bool]:
    hit = False
    for w in sorted(words, key=len, reverse=True):
        if w in text:
            hit = True
            text = text.replace(w, " ")
    for f in _FILLER:
        text = text.replace(f, " ")
    return " ".join(text.split()), hit


def _paid(payments: Dict[str, List[Dict]], name: str) -> float:
    total = 0.0
    for p in payments.get(name, []):
        try:
            total += float(p.get("金额") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _company_group(store) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    try:
        for c in store.companies():
            group = c.get("所属集团", "")
            for key in (c.get("公司全名"), c.get("简称"), c.get("公司名")):
                if key and group:
                    mapping[_norm(key)] = group
    except Exception:  # noqa: BLE001 — 公司表读不到不影响问答
        pass
    return mapping


def _match(records, subject: str, groups: Dict[str, str]):
    if not subject:
        return list(records or [])
    key = _norm(subject)
    out = []
    for rec in records or []:
        company = str(rec.get("公司", "") or "")
        session = str(rec.get("班期", "") or "")
        name = str(rec.get("姓名", "") or "")
        if key in _norm(name) or key in _norm(company) or key in _norm(session):
            out.append(rec)
            continue
        group = groups.get(_norm(company), "")
        if group and key in _norm(group):
            out.append(rec)
    return out


def _exam_texts(sessions, names=None):
    out = []
    for s in sessions or []:
        if names and _norm(str(s.get("班期名称", ""))) not in names:
            continue
        exam = to_date(s.get("考试日期")) or to_date(s.get("起始日期"))
        if exam is None:
            continue
        loc = s.get("考点") or ""
        out.append(f"{s.get('班期名称', '')}：{exam.isoformat()}"
                   + (f"（{loc}）" if loc else ""))
    return out


def _exam_answer(text: str, store) -> Optional[str]:
    """考试时间查询：按班期名、按人（关联班期）或直接列近期安排。"""
    sessions = store.sessions() if hasattr(store, "sessions") else []
    if not sessions:
        return None
    subject, _ = _strip_words(text, _EXAM_WORDS)
    key = _norm(text)
    hits = [s for s in sessions
            if s.get("班期名称") and _norm(str(s.get("班期名称"))) in key]
    if not hits and subject:
        recs = _match(store.records(), subject, {})
        if not recs:
            return f"没有匹配「{subject}」的报名记录"
        names = {_norm(str(r.get("班期") or "")) for r in recs if r.get("班期")}
        days = {record_day(r) for r in recs if record_day(r)}
        hits = [s for s in sessions
                if _norm(str(s.get("班期名称", ""))) in names
                or any(d and _norm(d) in _norm(str(s.get("班期名称", "")))
                       for d in days)]
        if not hits:
            return (f"「{subject}」暂无班期/考试日期信息"
                    f"（报名记录缺少登记日期或班期关联）")
    if hits:
        return "考试时间：\n" + "\n".join(_exam_texts(hits)[:5])
    if not subject:                      # 没指名 → 列近期考试
        today = date.today()
        upcoming = []
        for s in sessions:
            d = to_date(s.get("考试日期")) or to_date(s.get("起始日期"))
            if d and d >= today:
                upcoming.append((d, s))
        upcoming.sort(key=lambda x: x[0])
        lines = _exam_texts([s for _, s in upcoming[:3]])
        if lines:
            return "近期考试安排：\n" + "\n".join(lines)
    return None


def answer(question: str, store) -> Optional[str]:
    text = (question or "").strip()
    if not text:
        return None
    records = store.records()
    payments = store.payments_by_key()
    groups = _company_group(store)

    subject, _ = _strip_words(text, _EXAM_WORDS)
    if any(w in text for w in _EXAM_WORDS):
        exam = _exam_answer(text, store)
        if exam:
            return exam

    subject, debt = _strip_words(text, _DEBT_WORDS)
    if debt:
        hits = _match(records, subject, groups)
        total = 0.0
        detail = []
        for rec in hits:
            fee = rec.get("缴费")
            if not isinstance(fee, (int, float)):
                continue
            remain = float(fee) - _paid(payments, str(rec.get("姓名", "")))
            if remain > 0:
                total += remain
                detail.append(f"{rec.get('姓名')} {remain:g}")
        if not hits:
            return f"没有匹配「{subject}」的报名记录"
        head = f"「{subject or '全部'}」待收合计 {total:g} 元"
        if detail:
            head += "：" + "、".join(detail[:8]) + ("…" if len(detail) > 8 else "")
        return head

    subject, count = _strip_words(text, _COUNT_WORDS)
    if count:
        hits = _match(records, subject, groups)
        if not hits:
            return f"没有匹配「{subject}」的报名记录"
        names = [str(r.get("姓名", "")) for r in hits]
        return (f"「{subject or '全部'}」共 {len(hits)} 人："
                + "、".join(names[:12]) + ("…" if len(names) > 12 else ""))

    subject, pay = _strip_words(text, _PAY_WORDS)
    if pay:
        today = date.today()
        total = 0.0
        count_ = 0
        for name, flows in payments.items():
            for p in flows:
                if subject and subject not in _norm(name):
                    continue
                if "今天" in text:
                    when = to_date(p.get("时间"))
                    if when != today:
                        continue
                try:
                    total += float(p.get("金额") or 0)
                except (TypeError, ValueError):
                    continue
                count_ += 1
        scope = "今天" if "今天" in text else "累计"
        return f"{scope}收款 {count_} 笔，共 {total:g} 元"

    subject, status = _strip_words(text, _STATUS_WORDS)
    if status and subject:
        hits = _match(records, subject, groups)
        if not hits:
            return None          # 泛泛的问题（如"今天天气怎么样"）不硬答
        lines = []
        for rec in hits[:6]:
            fee = rec.get("缴费")
            paid = _paid(payments, str(rec.get("姓名", "")))
            money = f"缴费 {fee}" if isinstance(fee, (int, float)) else "金额未填"
            lines.append(f"{rec.get('姓名')}：报名{rec.get('报名状态', '')}/"
                         f"缴费{rec.get('缴费状态', '')}/开票{rec.get('开票状态', '')}"
                         f"（{money}，实收 {paid:g}）")
        return "；\n".join(lines)
    return None
