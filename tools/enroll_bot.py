"""EnrollPilot CLI：离线演示 / 配置体检。

用法::

    # 1) 离线闭环演示（不需要飞书凭据、不联网）：
    #    种子数据 → 一串群指令（改状态/写日志/收款/结算日报）全程打印
    python tools/enroll_bot.py --demo

    # 2) 配置体检：config/enroll.yaml 是否存在、必填键是否齐
    python tools/enroll_bot.py --check-config

真连模式（长连接 + 真实多维表格）属 M1 联调，见 README「M1 联调清单」——
前置条件是先在飞书侧手动建好五张表（bitable API 建不了关联字段），再把
app_token / table_id 填进 config/enroll.yaml。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from enroll.demo_store import DemoStore
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


def demo_script() -> None:
    """跑一遍演示闭环，每步打印，全程不联网不写库（内存 DemoStore）。"""
    store = DemoStore()  # 不传 path → 不落盘
    store.seed()
    print("== 种子数据（金额结构忠实真实样表：缴费=公司收费+返还）==")
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
    print("\n== 演示结束：状态/日志/流水/结算全部走的是真实业务函数，只差换 bitable 后端 ==")


def check_config() -> int:
    if not os.path.exists(CONFIG_PATH):
        print(f"[缺] {CONFIG_PATH} 不存在。"
              f"先 cp config/enroll.example.yaml config/enroll.yaml 填凭据。")
        return 1
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    missing = []
    node = cfg
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


def main() -> None:
    ap = argparse.ArgumentParser(description="EnrollPilot 培训报名结算助手")
    ap.add_argument("--demo", action="store_true", help="离线闭环演示（不联网）")
    ap.add_argument("--check-config", action="store_true", help="体检 config/enroll.yaml")
    args = ap.parse_args()
    if args.demo:
        demo_script()
    elif args.check_config:
        sys.exit(check_config())
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
