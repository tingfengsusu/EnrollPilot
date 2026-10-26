"""真机 GUI 自测：真实窗口 + 真实事件（剪贴板/鼠标点击），并输出截图。

用法（在真实桌面会话里跑，不要加 offscreen）::

    .venv/Scripts/python tools/gui_selftest.py

验证项：剪贴板文本自动填入 → 点「登记入库」→ 列表/回执 → 结算/提醒/导出 →
选中记录看时间线；每步截图存 data/gui_real_*.png。退出码非 0 = 有失败项。
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

ID_TEXT = ("姓名：真机测试\n性别：男\n出生：1990年1月1日\n"
           "住址：北京市海淀区清华园1号\n公民身份号码：410102199001010012")

failures = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        failures.append(name)


def pump(app, ms=300):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    store = DemoStore()  # 内存库，不落盘、不碰真连
    store.seed()
    base = len(store.records())
    win = DesktopTool(store=store, backend="自检-演示库")
    win.resize(1180, 760)
    win.show()
    pump(app, 600)

    # 1) 剪贴板文本 → 自动填入
    app.clipboard().setText(ID_TEXT)
    pump(app, 500)
    check("剪贴板身份证文本自动填入",
          "真机测试" in win.text_edit.toPlainText(),
          win.preview.text()[:30])

    # 2) 点「登记入库」（真实鼠标点击）
    QTest.mouseClick(win.btn_register, Qt.LeftButton)
    pump(app, 500)
    check("点登记后记录 +1", len(store.records()) == base + 1, f"{len(store.records())}")
    check("回执含已登记", "已登记" in win.reply_view.toPlainText())
    win.grab().save(os.path.join(ROOT, "data", "gui_real_1.png"))

    # 3) 选中第一条记录 → 详情时间线
    win.record_list.setCurrentRow(0)
    pump(app, 300)
    check("详情显示变更时间线", "变更时间线" in win.detail_view.toPlainText())

    # 4) 结算 / 提醒
    QTest.mouseClick(win.btn_settle, Qt.LeftButton)
    pump(app, 400)
    check("结算日报出现在回执区", "结算日报" in win.reply_view.toPlainText())
    QTest.mouseClick(win.btn_remind, Qt.LeftButton)
    pump(app, 400)
    check("提醒出现在回执区", "提醒" in win.reply_view.toPlainText())

    # 5) 导出名单
    QTest.mouseClick(win.btn_export, Qt.LeftButton)
    pump(app, 600)
    exports = os.path.join(ROOT, "data", "exports")
    files = [f for f in os.listdir(exports) if f.endswith(".xlsx")] if os.path.isdir(exports) else []
    check("导出 xlsx 已生成", bool(files), str(files[:2]))
    win.grab().save(os.path.join(ROOT, "data", "gui_real_2.png"))

    print(f"\n截图：data/gui_real_1.png（登记后）、data/gui_real_2.png（动作后）")
    print("失败项：" + (", ".join(failures) if failures else "无 ✓"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
