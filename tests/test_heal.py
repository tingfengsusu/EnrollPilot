"""异常自愈：白名单命中自动重试、未知故障记案例转人工。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.demo_store import DemoStore
from enroll.heal import HealStore
from enroll.runner import EnrollRunner
from gateway.models import InboundMessage


class Channel:
    def __init__(self):
        self.texts = []
        self.cards = []

    def send_text(self, chat, text):
        self.texts.append(text)

    def send_card(self, chat, title, text, template="blue"):
        self.cards.append(text)

    def send_file(self, chat, path):
        pass

    def download_all(self, message):
        return []


class FlakyStore(DemoStore):
    """第一次抛 Timeout，第二次正常 —— 模拟瞬时故障。"""

    def __init__(self, mode="timeout_once"):
        super().__init__()
        self.calls = 0
        self.mode = "normal"          # seed 阶段不注入故障
        self.seed()
        self.mode = mode
        self.calls = 0                # seed 期间的读表不计入故障计数

    def records(self):
        self.calls += 1
        if self.mode == "normal":
            return super().records()
        if self.mode == "timeout_once" and self.calls == 1:
            raise TimeoutError("request Timeout")
        if self.mode == "unknown":
            raise ValueError("某种没见过的错误")
        return super().records()


def _msg(mid="m1", text="结算"):
    return InboundMessage(channel="feishu", msg_id=mid, sender_id="ou_x",
                          chat_id="oc_x", text=text)


def test_heal_retry_on_known_symptom():
    channel = Channel()
    store = FlakyStore("timeout_once")
    healer = HealStore()
    runner = EnrollRunner(store, channel, hold_seconds=1, healer=healer)
    runner.handle_message(_msg())
    assert channel.cards and "结算日报" in channel.cards[0]      # 重试成功并回执
    assert not channel.texts                                    # 没有错误提示
    hit = [c for c in healer.cases if c.get("id") == "H1"][0]
    assert hit.get("hits") == 1


def test_unknown_symptom_recorded_disabled():
    channel = Channel()
    store = FlakyStore("unknown")
    healer = HealStore()
    runner = EnrollRunner(store, channel, hold_seconds=1, healer=healer)
    runner.handle_message(_msg())
    assert channel.texts and "故障案例" in channel.texts[0]
    new = [c for c in healer.cases if "没见过的错误" in str(c.get("symptom"))]
    assert new and new[0]["enabled"] is False


def test_heal_store_dedupe():
    store = HealStore()
    a = store.record("same error")
    b = store.record("same error")
    assert a["id"] == b["id"] and len([c for c in store.cases
                                        if c["symptom"] == "same error"]) == 1


if __name__ == "__main__":
    test_heal_retry_on_known_symptom()
    test_unknown_symptom_recorded_disabled()
    test_heal_store_dedupe()
    print("ok: test_heal")
