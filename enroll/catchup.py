"""历史消息补拉：补上「程序没运行时发给机器人的消息」。

飞书长连接只在连接期间推事件，**离线期间的消息不会重推**。启动时按配置的会话
（settlement.push_chat_id）拉取上次记录之后的消息，用同一套 runner 处理；
已处理过的 message_id 由持久化去重挡住，不会重复执行。

本模块只做纯逻辑（选择/过滤/回放）；API 拉取在 tools/enroll_bot.py 里。
"""
from __future__ import annotations

import json
from typing import Callable, Dict, List


def replay_chat_messages(items: List[Dict],
                         handle: Callable[[str, str, str], None],
                         is_duplicate: Callable[[str], bool]) -> int:
    """回放历史消息。``handle(msg_id, sender_id, text)``；返回处理条数。

    过滤：跳过机器人自己发的（sender_type=app）、非文本消息、空文本、已处理过的。
    """
    count = 0
    for item in items or []:
        sender = item.get("sender") or {}
        if str(sender.get("sender_type") or "") == "app":
            continue
        if str(item.get("msg_type") or "") != "text":
            continue
        mid = str(item.get("message_id") or "")
        if not mid or is_duplicate(mid):
            continue
        try:
            content = json.loads((item.get("body") or {}).get("content") or "{}")
        except ValueError:
            continue
        text = str(content.get("text") or "").strip()
        if not text:
            continue
        handle(mid, str(sender.get("id") or ""), text)
        count += 1
    return count


def load_state(path: str) -> Dict[str, int]:
    import os
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    return {}


def save_state(path: str, state: Dict[str, int]) -> None:
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
