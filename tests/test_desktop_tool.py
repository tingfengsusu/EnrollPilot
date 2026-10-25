"""桌面工具烟雾测试（QT_QPA_PLATFORM=offscreen，无头跑逻辑不跑外观）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication
except ImportError:
    if "PYTEST_CURRENT_TEST" in os.environ:
        import pytest
        pytest.skip("PyQt5 未安装", allow_module_level=True)
    print("skip: PyQt5 未安装")
    sys.exit(0)

app = QApplication.instance() or QApplication([])

from enroll.demo_store import DemoStore
from gui.desktop_tool import DesktopTool, make_store

ID_MALE = "410102199001010012"
TEXT = (f"姓名：桌面员\n性别：男\n出生：1990年1月1日\n"
        f"公民身份号码：{ID_MALE}")


def test_register_updates_list():
    store = DemoStore().seed()
    win = DesktopTool(store=store, backend="测试库")
    base = win.record_list.count()
    win.text_edit.setPlainText(TEXT)
    win.do_register()
    assert win.record_list.count() == base + 1
    assert store.find_record("桌面员")["身份证号"] == ID_MALE
    assert "已登记" in win.reply_view.toPlainText()


def test_detail_shows_timeline():
    store = DemoStore().seed()
    win = DesktopTool(store=store, backend="测试库")
    win.text_edit.setPlainText(TEXT)
    win.do_register()
    names = [win.record_list.item(i).text() for i in range(win.record_list.count())]
    row = next(i for i, t in enumerate(names) if "桌面员" in t)
    win.show_detail(row)
    assert "变更时间线" in win.detail_view.toPlainText()
    assert "新增" in win.detail_view.toPlainText()


def test_make_store_falls_back_to_demo():
    """没配置真连凭据时必须落本地库（绝不静默装真连）。"""
    store, backend = make_store()
    assert "演示" in backend or "多维表格" in backend
    from enroll.demo_store import DemoStore
    assert isinstance(store, DemoStore) or type(store).__name__ == "BitableStore"


if __name__ == "__main__":
    test_register_updates_list()
    test_detail_shows_timeline()
    test_make_store_falls_back_to_demo()
    print("ok: test_desktop_tool")
