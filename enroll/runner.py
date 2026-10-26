"""真连编排：收消息 → 分流（图片/文本/指令）→ 处理 → 回推。

- 文本走白名单指令（instructions.parse）或身份证识别文本自动登记（intake）；
- 图片走 ``ocr`` 回调（未配置则提示"复制图片内容"的人肉兜底）；
- 文本+图片两条事件先过 MessageAggregator 合并窗口（FormPilot 实测：飞书会拆开推）；
- **重复投递去重**（实测：同一 msg_id 会被飞书重推一次，须幂等，否则会双回复）；
- 单条消息处理失败不拖垮长连接：异常转文本回推。
"""
from __future__ import annotations

import time

from gateway.aggregator import MessageAggregator
from enroll.extract import looks_like_id_text
from enroll.intake import intake_text
from enroll.instructions import USAGE, parse
from enroll.service import execute


class EnrollRunner:
    def __init__(self, store, channel, hold_seconds: float = 45.0, ocr=None):
        self.store = store
        self.channel = channel
        self.ocr = ocr                    # callable(image_path) -> 识别文本；None = 未配置
        # 本项目的"完整消息"= 有文字或有附件即可。FormPilot 的默认规则是「文字+附件齐全」
        # （学平险场景：品种关键词+照片），会把纯文字指令压 hold 秒——对群指令场景是错的。
        self.aggregator = MessageAggregator(
            on_complete=self.handle_message, hold_seconds=hold_seconds,
            is_complete=lambda m: bool((m.text or "").strip()) or bool(m.attachments))
        self._seen: dict = {}             # msg_id -> 处理时间（防重复投递）
        self._seen_ttl = 600.0

    # 长连接回调：只进聚合器，不做重活（避免平台重推）
    def on_message(self, message) -> None:
        mid = message.msg_id
        now = time.time()
        if mid:
            stamp = self._seen.get(mid)
            if stamp is not None and now - stamp < self._seen_ttl:
                print(f"[runner] 忽略重复投递 msg_id={mid}")
                return
            self._seen[mid] = now
            if len(self._seen) > 500:     # 定期清理过期键
                self._seen = {k: v for k, v in self._seen.items()
                              if now - v < self._seen_ttl}
        print(f"[runner] 收到消息 msg_id={mid} type={message.message_type} "
              f"attachments={len(message.attachments)} text={(message.text or '')[:40]!r}")
        self.aggregator.add(message)

    def handle_message(self, message) -> None:
        chat = message.chat_id
        try:
            self._handle(message, chat)
        except Exception as e:  # noqa: BLE001 — 单条失败不影响连接
            print(f"[runner] 处理失败：{e}")
            try:
                self.channel.send_text(chat, f"处理失败：{e}")
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
            self.channel.send_text(chat, execute(self.store, cmd, operator=operator))
            return
        if looks_like_id_text(text):
            self.channel.send_text(chat, intake_text(
                self.store, text, operator=operator, source=message.channel or "群消息"))
            return
        self.channel.send_text(chat, "不是认识的指令。\n" + USAGE)

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
