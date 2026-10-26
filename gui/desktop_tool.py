"""桌面剪贴板入口（M2，入口B）——前台的工具，与群机器人写同一个库。

用法::

    python tools/enroll_bot.py --desktop        # 或直接 python -m gui.desktop_tool

设计要点（设计文档 三·入口B）：

- **剪贴板双模式**：是图片 → 提示走微信「复制图片内容」人肉兜底（OCR 后端未配置）；
  是身份证识别文本 → 自动填入文本框，**前台可以人工修正再登记**（修正动作天然合规：
  机器只补空，人改的字段由人负责）；
- **双入口一个库**：检测到 config/enroll.yaml 凭据就用 BitableStore 真连多维表格，
  否则落本地 JSON 演示库（标题栏注明后端，绝不装真连）；
- 登记走 :func:`enroll.intake.intake_text`，与机器人完全同一条代码路径。
"""
from __future__ import annotations

import os
import sys

ROOT = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QGroupBox, QHBoxLayout, QLabel,
                             QListWidget, QMainWindow, QPlainTextEdit,
                             QPushButton, QSplitter, QTextEdit, QVBoxLayout,
                             QWidget)

from enroll.demo_store import DemoStore
from enroll.extract import looks_like_id_text
from enroll.intake import intake_text
from enroll.service import fmt_time


def make_store():
    """有凭据 → BitableStore（真连）；否则本地 JSON 演示库。返回 (store, 后端说明)。"""
    cfg_path = os.path.join(ROOT, "config", "enroll.yaml")
    if os.path.exists(cfg_path):
        try:
            import yaml
            from enroll.bitable import BitableClient
            from enroll.bitable_store import BitableStore
            with open(cfg_path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            feishu, bitable = cfg.get("feishu", {}), cfg.get("bitable", {})
            if feishu.get("app_id") and bitable.get("app_token"):
                client = BitableClient(feishu["app_id"], feishu["app_secret"],
                                       bitable["app_token"])
                return (BitableStore(client, dict(bitable.get("tables", {}))),
                        "多维表格（真连）")
        except Exception as e:  # noqa: BLE001 — 配置坏/依赖缺 → 降级本地库，别崩
            print(f"[desktop] 真连配置不可用（{e}），降级本地演示库")
    path = os.path.join(ROOT, "data", "desktop_store.json")
    return DemoStore(path), "本地演示库（未配置真连凭据）"


class DesktopTool(QMainWindow):
    def __init__(self, store=None, backend: str = ""):
        super().__init__()
        self.store, default_backend = (store, backend) if store else make_store()
        if not backend:
            backend = default_backend
        self.setWindowTitle(f"EnrollPilot 报名登记台 — 后端：{backend}")
        self.resize(980, 620)
        self._build_ui()
        self.refresh_records()
        # 启动读一次剪贴板 + 运行中持续监听（QClipboard 事件，无全局钩子）
        self.clip = QApplication.clipboard()
        self.clip.dataChanged.connect(self.on_clipboard_changed)
        self.on_clipboard_changed()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([480, 480])
        self.setCentralWidget(splitter)

    def _build_left(self) -> QWidget:
        box = QGroupBox("① 录入（剪贴板/粘贴身份证识别文本，可人工修正）")
        layout = QVBoxLayout(box)
        self.preview = QLabel("（剪贴板预览）")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "微信里对图片点「复制图片内容」，把文字粘贴到这里（或 Ctrl+V 自动带出）；\n"
            "识别错位可以直接改，改完再登记——人改的字段由人负责。")
        layout.addWidget(self.text_edit)
        buttons = QHBoxLayout()
        grab = QPushButton("从剪贴板读取")
        grab.clicked.connect(self.on_clipboard_changed)
        register = QPushButton("登记入库")
        register.clicked.connect(self.do_register)
        buttons.addWidget(grab)
        buttons.addWidget(register)
        layout.addLayout(buttons)
        self.reply_view = QTextEdit()
        self.reply_view.setReadOnly(True)
        self.reply_view.setPlaceholderText("登记回执与存疑提示会显示在这里")
        layout.addWidget(self.reply_view)
        return box

    def _build_right(self) -> QWidget:
        box = QGroupBox("② 报名记录（点击看详情与变更时间线）")
        layout = QVBoxLayout(box)
        self.record_list = QListWidget()
        self.record_list.currentRowChanged.connect(self.show_detail)
        layout.addWidget(self.record_list)
        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        layout.addWidget(self.detail_view)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_records)
        layout.addWidget(refresh)
        return box

    # ------------------------------------------------------------------
    # 行为
    # ------------------------------------------------------------------
    def on_clipboard_changed(self) -> None:
        image = self.clip.image()
        if not image.isNull():
            self.preview.setText("（剪贴板是图片。OCR 未配置：请在微信里打开图片 →"
                                 "「复制图片内容」→ 回到这里粘贴文字）")
            return
        text = (self.clip.text() or "").strip()
        if not text:
            return
        if looks_like_id_text(text):
            self.text_edit.setPlainText(text)
            self.preview.setText("检测到身份证识别文本，已填入——可人工修正后登记。")
        else:
            self.preview.setText("（剪贴板文本不是身份证识别格式，需要时手动粘贴）")

    def do_register(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            self.reply_view.append("（文本框为空：先粘贴或从剪贴板读取）")
            return
        reply = intake_text(self.store, text, operator="桌面工具", source="桌面工具")
        self.reply_view.append(f"[{reply.splitlines()[0]}]")
        self.reply_view.append(reply)
        self.reply_view.append("———")
        self.refresh_records()

    def refresh_records(self) -> None:
        self.record_list.clear()
        try:
            records = self.store.records()
        except Exception as e:  # noqa: BLE001 — 真连失败时界面别崩
            self.detail_view.setPlainText(f"读取记录失败：{e}")
            return
        for rec in records:
            self.record_list.addItem(
                f"{rec.get('姓名', '（无名）')}｜{rec.get('公司', '')}｜"
                f"缴费 {rec.get('缴费', '-')}｜{rec.get('缴费状态', '')}")
        self.statusBar().showMessage(f"共 {len(records)} 条记录")

    def show_detail(self, row: int) -> None:
        try:
            records = self.store.records()
        except Exception as e:  # noqa: BLE001
            self.detail_view.setPlainText(f"读取失败：{e}")
            return
        if row < 0 or row >= len(records):
            return
        rec = records[row]
        lines = [f"姓名：{rec.get('姓名', '')}    公司：{rec.get('公司', '')}",
                 f"身份证号：{rec.get('身份证号', '')}    手机号：{rec.get('手机号', '')}",
                 f"工种：{rec.get('工种', '')}    培训类型：{rec.get('培训类型', '')}",
                 f"登记：{rec.get('登记日期', '')}（{rec.get('登记渠道', '')}）",
                 f"状态：报名 {rec.get('报名状态', '')} / 缴费 {rec.get('缴费状态', '')}"
                 f" / 开票 {rec.get('开票状态', '')}",
                 f"金额：缴费 {rec.get('缴费', '-')} = 公司收费 {rec.get('公司收费', '-')}"
                 f" + 返还 {rec.get('返还', '-')}",
                 "—— 变更时间线 ——"]
        for e in self.store.timeline(rec.get("姓名", "")):
            lines.append(f"{fmt_time(e.get('时间'))} [{e.get('变更类型', '')}] "
                         f"{e.get('字段')}：{e.get('旧值') or '（空）'} → {e.get('新值')}"
                         f"（{e.get('操作人')}，{e.get('触发来源')}）")
        self.detail_view.setPlainText("\n".join(lines))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = DesktopTool()
    window.show()
    if os.environ.get("ENROLLPILOT_SMOKE") == "1":
        # 打包/CI 自检：开窗 → 1.5 秒后退出（用于验证 exe 能起得来）
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(1500, app.quit)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
