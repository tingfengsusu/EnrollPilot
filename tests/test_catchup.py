"""历史消息补拉：过滤机器人自己/非文本/重复，只回放有效文本。"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enroll.catchup import replay_chat_messages


def _item(mid, text, sender_type="user", mid_type="text"):
    return {"message_id": mid, "msg_type": mid_type,
            "sender": {"id": "ou_user", "sender_type": sender_type},
            "body": {"content": json.dumps({"text": text}, ensure_ascii=False)}}


def test_replay_filters():
    seen = set()
    handled = []

    def is_dup(mid):
        if mid in seen:
            return True
        seen.add(mid)
        return False

    def handle(mid, sender, text):
        handled.append((mid, sender, text))

    items = [
        _item("m1", "张三 已缴费 700"),
        _item("m2", "（机器人自己发的）", sender_type="app"),
        _item("m3", "![图]", mid_type="image"),
        _item("m4", "   "),                       # 空文本
        _item("m1", "重复的消息"),                 # 同 id 重复
        _item("m5", "考试安排"),
    ]
    count = replay_chat_messages(items, handle, is_dup)
    assert count == 2
    assert [h[0] for h in handled] == ["m1", "m5"]
    assert handled[0][1] == "ou_user" and handled[0][2] == "张三 已缴费 700"


def test_bad_content_skipped():
    items = [{"message_id": "m9", "msg_type": "text",
              "sender": {"id": "ou", "sender_type": "user"},
              "body": {"content": "not-json"}}]
    assert replay_chat_messages(items, lambda *a: None, lambda m: False) == 0


if __name__ == "__main__":
    test_replay_filters()
    test_bad_content_skipped()
    print("ok: test_catchup")
