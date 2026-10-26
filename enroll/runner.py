"""真连编排：收消息 → 分流（图片/文本/指令）→ 处理 → 回推。

- 文本走白名单指令（instructions.parse）或身份证识别文本自动登记（intake）；
- 图片走 ``ocr`` 回调（未配置则提示"复制图片内容"的人肉兜底）；
- 文本+图片两条事件先过 MessageAggregator 合并窗口（FormPilot 实测：飞书会拆开推）；
- **重复投递去重**（实测：同一 msg_id 会被飞书重推，须幂等，否则双回复）——
  默认内存 TTL；传 ``dedupe_path`` 则落 SQLite，重启后仍生效；
- 单条消息处理失败不拖垮长连接：异常转文本回推。
"""
from __future__ import annotations

import os
import sqlite3
import time

from gateway.aggregator import MessageAggregator
from enroll.extract import looks_like_id_text
from enroll.heal import HealStore
from enroll.intake import intake_text
from enroll.instructions import USAGE, parse
from enroll.service import execute


class MessageDedupe:
    """msg_id 去重：内存 TTL，可选 SQLite 持久化（重启后仍挡得住旧事件重推）。"""

    def __init__(self, path: str = "", ttl: float = 600.0):
        self.path = path
        self.ttl = ttl
        self._mem: dict = {}
        self._db = None
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS seen"
                             "(msg_id TEXT PRIMARY KEY, ts REAL NOT NULL)")
            self._db.commit()

    def is_duplicate(self, msg_id: str, now: float = 0.0) -> bool:
        """True = 已处理过（TTL 内重复投递）。首次出现会登记并返回 False。"""
        if not msg_id:
            return False
        now = now or time.time()
        if self._db is not None:
            row = self._db.execute("SELECT ts FROM seen WHERE msg_id=?",
                                   (msg_id,)).fetchone()
            if row and now - row[0] < self.ttl:
                return True
            self._db.execute("INSERT OR REPLACE INTO seen(msg_id, ts) VALUES(?, ?)",
                             (msg_id, now))
            self._db.execute("DELETE FROM seen WHERE ts < ?", (now - self.ttl,))
            self._db.commit()
            return False
        stamp = self._mem.get(msg_id)
        if stamp is not None and now - stamp < self.ttl:
            return True
        self._mem[msg_id] = now
        if len(self._mem) > 500:
            self._mem = {k: v for k, v in self._mem.items() if now - v < self.ttl}
        return False


class EnrollRunner:
    def __init__(self, store, channel, hold_seconds: float = 45.0, ocr=None,
                 dedupe_path: str = "", export_dir: str = "", healer=None):
        self.store = store
        self.channel = channel
        self.ocr = ocr                    # callable(image_path) -> 识别文本；None = 未配置
        self.export_dir = export_dir or os.path.join("data", "exports")
        self.dedupe = MessageDedupe(dedupe_path)
        self.healer = healer or HealStore()
        # 本项目的"完整消息"= 有文字或有附件即可。FormPilot 的默认规则是「文字+附件齐全」
        # （学平险场景：品种关键词+照片），会把纯文字指令压 hold 秒——对群指令场景是错的。
        self.aggregator = MessageAggregator(
            on_complete=self.handle_message, hold_seconds=hold_seconds,
            is_complete=lambda m: bool((m.text or "").strip()) or bool(m.attachments))

    # 长连接回调：只进聚合器，不做重活（避免平台重推）
    def on_message(self, message) -> None:
        mid = message.msg_id
        if self.dedupe.is_duplicate(mid):
            print(f"[runner] 忽略重复投递 msg_id={mid}")
            return
        print(f"[runner] 收到消息 msg_id={mid} chat={message.chat_id} "
              f"sender={message.sender_id} type={message.message_type} "
              f"attachments={len(message.attachments)} text={(message.text or '')[:40]!r}")
        self.aggregator.add(message)

    def handle_message(self, message) -> None:
        chat = message.chat_id
        try:
            self._handle(message, chat)
            return
        except Exception as e:  # noqa: BLE001 — 单条失败不影响连接
            error_text = str(e)
            case = self.healer.match(error_text)
            if case and case.get("remedy") == "retry":
                print(f"[heal] 命中案例 {case.get('id')}（{case.get('symptom')}），自动重试一次")
                try:
                    self._handle(message, chat)
                    self.healer.bump(case["id"])
                    return
                except Exception as e2:  # noqa: BLE001
                    error_text = str(e2)
            case = self.healer.record(error_text)
            print(f"[heal] 未命中白名单，记案例 {case.get('id')}：{error_text}")
            try:
                print(f"[runner] 处理失败：{error_text}")
                self.channel.send_text(
                    chat, f"处理失败（已记录故障案例 {case.get('id')}，待人工确认）：{error_text}")
            except Exception:
                pass

    def _handle(self, message, chat: str) -> None:
        operator = message.sender_id or "群成员"
        if message.attachments:
            self._handle_attachments(message, chat, operator)
            return
        text = (message.text or "").strip()
        if not text:
            return
        cmd = parse(text)
        if cmd is not None:
            if cmd.action == "export":
                self._handle_export(cmd, chat)
                return
            reply = execute(self.store, cmd, operator=operator)
            self._send(chat, cmd, reply)
            return
        if looks_like_id_text(text):
            self.channel.send_text(chat, intake_text(
                self.store, text, operator=operator, source=message.channel or "群消息"))
            return
        # 规则式问答（P2）：不是指令、不是身份证文本时，尝试当问题回答
        from enroll.qa import answer as qa_answer
        qa_reply = None
        try:
            qa_reply = qa_answer(text, self.store)
        except Exception as e:  # noqa: BLE001 — 问答失败不阻塞
            print(f"[runner] 问答失败：{e}")
        if qa_reply:
            self.channel.send_card(chat, "数据问答", qa_reply)
            return
        self.channel.send_text(chat, "不是认识的指令。\n" + USAGE)

    #: 用卡片渲染的指令（标题, 颜色）
    _CARDS = {"settle": ("结算日报", "blue"), "remind": ("提醒", "orange"),
              "status": ("数据状态", "grey"), "records": ("变更时间线", "blue")}

    def _send(self, chat: str, cmd, reply: str) -> None:
        card = self._CARDS.get(cmd.action)
        if card:
            self.channel.send_card(chat, card[0], reply, template=card[1])
        else:
            self.channel.send_text(chat, reply)

    def _handle_export(self, cmd, chat: str) -> None:
        """「导出 名单/结算」→ 生成 Excel 并发到当前会话。"""
        from enroll.export import export_for_command
        path = export_for_command(self.store, cmd.keyword, self.export_dir)
        self.channel.send_text(chat, f"已生成：{os.path.basename(path)}")
        self.channel.send_file(chat, path)

    def _handle_attachments(self, message, chat: str, operator: str) -> None:
        if self.ocr is None:
            self.channel.send_text(
                chat,
                "收到图片，但尚未配置 OCR。临时办法：在微信里对图片点「复制图片内容」，"
                "把文字直接粘贴发我。")
            return
        paths = self.channel.download_all(message)
        if not paths:
            self.channel.send_text(chat, "附件下载失败，请重发一次。")
            return
        replies = []
        for path in paths:
            text = self.ocr(path)
            replies.append(intake_text(self.store, text, operator=operator,
                                       source=message.channel or "群消息"))
        self.channel.send_text(chat, "\n———\n".join(replies))
