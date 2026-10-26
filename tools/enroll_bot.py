"""EnrollPilot CLI：离线演示 / 配置体检 / 真连长连接。

用法::

    # 1) 离线闭环演示（不需要飞书凭据、不联网）：
    #    种子数据 → 群指令（改状态/写日志/收款/结算日报）→ 剪贴板文本登记 → Excel 导出
    python tools/enroll_bot.py --demo

    # 2) 配置体检：config/enroll.yaml 是否存在、必填键是否齐
    python tools/enroll_bot.py --check-config

    # 3) 桌面登记台（M2 入口B：剪贴板 → 登记同一个库）
    python tools/enroll_bot.py --desktop

    # 4) 真连模式（长连接收消息 + 真实多维表格）：先 --check-config 通过再跑
    python tools/enroll_bot.py --listen

真连前置（详见 README「M1 联调清单」）：飞书侧建好五张表（bitable API 建不了
关联字段，须 UI 建）并授权应用；config/enroll.yaml 填凭据与表 id。
收图 OCR 未配置时，收到图片会提示"微信复制图片内容→粘贴文本"的人肉兜底。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from enroll.demo_store import DemoStore
from enroll.intake import intake_text
from enroll.instructions import parse
from enroll.service import execute

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "enroll.yaml")
DEMO_PATH = os.path.join(ROOT, "data", "demo_store.json")

#: 必填键（真连模式）：凭据 + 五张表的 table_id
_REQUIRED_KEYS = (
    ("feishu", "app_id"), ("feishu", "app_secret"),
    ("bitable", "app_token"),
    ("bitable", "tables", "报名记录"), ("bitable", "tables", "收款"),
    ("bitable", "tables", "公司"), ("bitable", "tables", "班期"),
    ("bitable", "tables", "变更日志"),
)

#: 演示用微信「复制图片内容」文本（合成证件号，非真人）
_DEMO_WECHAT_TEXT = (
    "姓名\n性别\n出生\n住址\n测试员\n男\n1990\n民族汉\n年1月1日\n"
    "北京市海淀区清华园1号100084\n公民身份号码\n410102199001010012"
)


def demo_script() -> None:
    """跑一遍演示闭环，每步打印，全程不联网（内存 DemoStore；导出写 data/）。"""
    from enroll.export import export_roster, export_settlement

    store = DemoStore()  # 不传 path → 不落盘
    store.seed()
    print("== ① 种子数据（金额结构忠实真实样表：缴费=公司收费+返还）==")
    print(execute(store, parse("状态"), operator="演示"))
    for text, who in [
        ("张莹 已缴费 700", "业务员A"),   # 改状态 + 落收款流水
        ("李蕾 已退", "业务员A"),         # 缴费状态改已退（结算里会亮红灯）
        ("记录 张莹", "演示"),
        ("查 某集团", "演示"),
        ("结算", "演示"),
    ]:
        cmd = parse(text)
        print(f"\n> {text}   （{who}）")
        print(execute(store, cmd, operator=who))

    print("\n== ② 剪贴板登记（入口B：微信「复制图片内容」→ 粘贴文本 → 幂等入库）==")
    print(intake_text(store, _DEMO_WECHAT_TEXT, operator="前台", source="剪贴板"))

    p1 = export_settlement(store, os.path.join(ROOT, "data", "demo_结算单.xlsx"))
    p2 = export_roster(store, os.path.join(ROOT, "data", "demo_名单.xlsx"),
                       group="某集团集团")
    print(f"\n== ③ 导出（旧表三张手工衍生表的系统版）：\n   {p1}\n   {p2} ==")
    print("\n== 演示结束：登记/状态/日志/流水/结算/导出全是真实业务函数，只差换 bitable 后端 ==")


def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def check_config() -> int:
    if not os.path.exists(CONFIG_PATH):
        print(f"[缺] {CONFIG_PATH} 不存在。"
              f"先 cp config/enroll.example.yaml config/enroll.yaml 填凭据。")
        return 1
    cfg = _load_config()
    missing = []
    for path in _REQUIRED_KEYS:
        node = cfg
        for key in path:
            if not isinstance(node, dict) or key not in node or not node[key]:
                missing.append("/".join(path))
                break
            node = node[key]
    if missing:
        print("[缺] 以下配置为空：\n  " + "\n  ".join(sorted(set(missing))))
        return 1
    print("[齐] 配置完整（表 id 是否有效需真连验证）")
    return 0


def _start_daily_push(store, channel, cfg: dict) -> None:
    """每日定时推送：结算日报 + 到期的班期提醒（配置了 push_chat_id 才启动）。"""
    import threading
    import time as _time
    from datetime import datetime, timedelta

    settlement = cfg.get("settlement") or {}
    push_at = str(settlement.get("daily_push") or "")
    chat = str(settlement.get("push_chat_id") or "")
    if not push_at or not chat:
        print("[push] 未配置 settlement.push_chat_id，跳过每日推送")
        return
    try:
        hh, mm = (int(x) for x in push_at.split(":"))
    except ValueError:
        print(f"[push] daily_push 格式应为 HH:MM，收到 {push_at!r}，跳过")
        return

    def loop():
        from enroll.reminders import due_reminders, render_reminders
        from enroll.settlement import render_daily
        while True:
            now = datetime.now()
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            _time.sleep(max(1.0, (target - now).total_seconds()))
            try:
                text = render_daily(store.records(), store.payments_by_key())
                items = due_reminders(store.records(), store.sessions(),
                                      datetime.now().date())
                if items:
                    text += "\n" + render_reminders(items)
                channel.send_text(chat, text)
                print(f"[push] 已推送日报与提醒到 {chat}")
            except Exception as e:  # noqa: BLE001 — 推送失败不影响收消息
                print(f"[push] 推送失败：{e}")

    threading.Thread(target=loop, daemon=True, name="daily-push").start()
    print(f"[push] 每日 {push_at} 推送已启动 → {chat}")


def listen() -> int:
    """真连模式：长连接收消息 → 聚合 → 抽取/指令 → bitable → 回推。"""
    if check_config():
        return 1
    from enroll.bitable import BitableClient
    from enroll.bitable_store import BitableStore
    from enroll.runner import EnrollRunner
    from gateway.feishu import FeishuChannel

    cfg = _load_config()
    feishu, bitable = cfg["feishu"], cfg["bitable"]
    channel = FeishuChannel(app_id=feishu["app_id"], app_secret=feishu["app_secret"],
                            attachment_dir=os.path.join(ROOT, "data", "inbox"))
    client = BitableClient(feishu["app_id"], feishu["app_secret"], bitable["app_token"])
    store = BitableStore(client, dict(bitable["tables"]))
    from enroll.ocr import make_ocr
    ocr = make_ocr(cfg)
    if ocr is None:
        print("[ocr] 未配置（config/enroll.yaml → ocr.provider=tencent + 密钥），图片将走文本兜底")
    runner = EnrollRunner(store, channel,
                          hold_seconds=float(feishu.get("merge_hold_seconds", 45)),
                          dedupe_path=os.path.join(ROOT, "data", "runner_state.db"),
                          export_dir=os.path.join(ROOT, "data", "exports"),
                          ocr=ocr)
    channel.on_message = runner.on_message
    _start_daily_push(store, channel, cfg)
    print("长连接已启动，等待群消息…（Ctrl+C 退出；图片 OCR 未配置时按提示走文本兜底）")
    try:
        channel.start(blocking=True)
    except KeyboardInterrupt:
        channel.stop()
        print("\n已退出")
    return 0


def desktop() -> int:
    from gui.desktop_tool import main as gui_main
    return gui_main()


def main() -> None:
    ap = argparse.ArgumentParser(description="EnrollPilot 培训报名结算助手")
    ap.add_argument("--demo", action="store_true", help="离线闭环演示（不联网）")
    ap.add_argument("--check-config", action="store_true", help="体检 config/enroll.yaml")
    ap.add_argument("--desktop", action="store_true", help="桌面登记台（剪贴板入口B）")
    ap.add_argument("--listen", action="store_true", help="真连长连接（需先 --check-config 通过）")
    args = ap.parse_args()
    if args.demo:
        demo_script()
    elif args.check_config:
        sys.exit(check_config())
    elif args.desktop:
        sys.exit(desktop())
    elif args.listen:
        sys.exit(listen())
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
