"""生成 README 演示截图（真实窗口渲染 + 演示库数据，不碰真实租户）。

产物写入 docs/screenshots/，用于 README 演示区。

运行：.venv/Scripts/python tools/shoot_screenshots.py
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from enroll.demo_store import DemoStore
from gui.desktop_tool import DesktopTool

OUT_DIR = os.path.join(ROOT, "docs", "screenshots")

ID_TEXT = ("姓名：测试人\n性别：男\n出生：1990年1月1日\n"
           "住址：北京市海淀区测试路1号\n公民身份号码：410102199001010012")


def pump(app: QApplication, ms: int = 400) -> None:
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def shot(win, name: str) -> None:
    path = os.path.join(OUT_DIR, name)
    win.grab().save(path)
    print("已保存", os.path.relpath(path, ROOT))


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    app = QApplication(sys.argv)

    store = DemoStore()
    store.seed()
    win = DesktopTool(store=store, backend="演示库（离线）")
    win.resize(1280, 820)
    win.show()
    pump(app, 900)

    # 1) 主界面：左登记台 + 右报名记录
    shot(win, "01-main-window.png")

    # 2) 剪贴板身份证文本 → 自动填入待确认
    app.clipboard().setText(ID_TEXT)
    pump(app, 700)
    shot(win, "02-register.png")

    # 3) 登记入库 → 选中记录看变更时间线
    QTest.mouseClick(win.btn_register, Qt.LeftButton)
    pump(app, 700)
    win.record_list.setCurrentRow(0)
    pump(app, 500)
    shot(win, "03-timeline.png")

    # 4) 结算日报
    QTest.mouseClick(win.btn_settle, Qt.LeftButton)
    pump(app, 700)
    shot(win, "04-settlement.png")

    print("完成：docs/screenshots/01-main-window.png ~ 04-settlement.png")


if __name__ == "__main__":
    main()
