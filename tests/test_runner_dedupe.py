"""runner：重复投递去重（内存 + SQLite）与纯文字快速通过（不压聚合器）。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.demo_store import DemoStore
from enroll.runner import EnrollRunner, MessageDedupe
from gateway.models import InboundMessage


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.files = []
        self.cards = []

    def send_text(self, chat_id, text):
        self.sent.append((chat_id, text))

    def send_file(self, chat_id, path):
        self.files.append((chat_id, path))

    def send_card(self, chat_id, title, text, template="blue"):
        self.cards.append((title, text))

    def download_all(self, message):
        return []


def _msg(mid, text):
    return InboundMessage(channel="test", msg_id=mid, sender_id="ou_test",
                          chat_id="oc_test", text=text)


def test_dedupe_memory_ttl():
    d = MessageDedupe()
    assert d.is_duplicate("m1", now=1000.0) is False
    assert d.is_duplicate("m1", now=1001.0) is True
    assert d.is_duplicate("m1", now=2000.0) is False   # 超过 TTL 视为新消息
    assert d.is_duplicate("", now=2000.0) is False     # 空 id 不去重


def test_dedupe_sqlite_survives_restart():
    path = os.path.join(tempfile.mkdtemp(), "state.db")
    d1 = MessageDedupe(path)
    assert d1.is_duplicate("m9", now=1000.0) is False
    d2 = MessageDedupe(path)                       # 模拟重启
    assert d2.is_duplicate("m9", now=1001.0) is True
    assert d2.is_duplicate("m9", now=9999.0) is False


def test_runner_dedupes_and_replies_once():
    channel = FakeChannel()
    runner = EnrollRunner(DemoStore().seed(), channel)
    runner.on_message(_msg("m1", "状态"))
    assert len(channel.cards) == 1 and "当前数据" in channel.cards[0][1]
    runner.on_message(_msg("m1", "状态"))           # 平台重推
    assert len(channel.cards) == 1                  # 不重复回复
    runner.on_message(_msg("m2", "状态"))
    assert len(channel.cards) == 2


def test_runner_text_only_no_hold_wait():
    """纯文字指令必须立即处理（不能被 45 秒合并窗口压住）。"""
    channel = FakeChannel()
    runner = EnrollRunner(DemoStore().seed(), channel, hold_seconds=45)
    runner.on_message(_msg("m3", "结算"))
    assert len(channel.cards) == 1 and "结算日报" in channel.cards[0][1]


def test_runner_qa_question():
    """非指令的自然语言问题走规则问答。"""
    channel = FakeChannel()
    runner = EnrollRunner(DemoStore().seed(), channel)
    runner.on_message(_msg("m5", "某集团集团还欠多少"))
    assert len(channel.cards) == 1 and "待收" in channel.cards[0][1]


def test_runner_export_command_sends_file():
    channel = FakeChannel()
    tmp = tempfile.mkdtemp()
    runner = EnrollRunner(DemoStore().seed(), channel, export_dir=tmp)
    runner.on_message(_msg("m4", "导出 名单 某集团集团"))
    assert len(channel.files) == 1 and channel.files[0][1].endswith(".xlsx")
    assert runner.dedupe.is_duplicate("m4") is True


if __name__ == "__main__":
    test_dedupe_memory_ttl()
    test_dedupe_sqlite_survives_restart()
    test_runner_dedupes_and_replies_once()
    test_runner_text_only_no_hold_wait()
    test_runner_qa_question()
    test_runner_export_command_sends_file()
    print("ok: test_runner_dedupe")
